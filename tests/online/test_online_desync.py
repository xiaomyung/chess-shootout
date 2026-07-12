"""Desync detection + /resume recovery.

Invariant under test: a client detects a dropped/out-of-order broadcast by
comparing the server's `ply` field against `len(move_history)`, fires
request_state_sync, and gates every further move_applied/takeback behind the
`_resyncing` flag until _handle_game_resumed clears it.
"""
import json
import logging
import random

from unittest.mock import MagicMock

import pygame as pg
import pytest
from fastapi.testclient import TestClient

from tests.conftest import pygame_display
from chessshootout.domain.match import ONLINE
from chessshootout.backend.pieces import PieceColor
from chessshootout.server import connections as connections_module
from chessshootout.server.app import PROTOCOL_VERSION, create_app
from chessshootout.server.protocol import MoveAppliedMessage
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def client(app):
    return TestClient(app)


def _matchmake(client, *, uuid, nickname, side):
    return client.post("/matchmake", json={
        "version": PROTOCOL_VERSION,
        "client_uuid": uuid, "nickname": nickname,
        "time_minutes": 5, "increment_seconds": 0,
        "side_preference": side,
    }).json()


def _auth(token):
    return {"version": PROTOCOL_VERSION, "type": "auth", "session_token": token}


def _move(from_sq, to_sq):
    return {"version": PROTOCOL_VERSION, "type": "move",
            "from": from_sq, "to": to_sq}


def _paired_ws(client):
    random.seed(0)
    a = _matchmake(client, uuid=ALICE, nickname="Alice", side="white")
    b = _matchmake(client, uuid=BOB, nickname="Bob", side="black")
    return a, b


def test_move_applied_includes_ply(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps(_move("e2", "e4")))
            applied_w = json.loads(ws_w.receive_text())
            applied_b = json.loads(ws_b.receive_text())
            assert applied_w["ply"] == 1
            assert applied_b["ply"] == 1
            ws_b.send_text(json.dumps(_move("e7", "e5")))
            applied_w2 = json.loads(ws_w.receive_text())
            applied_b2 = json.loads(ws_b.receive_text())
            assert applied_w2["ply"] == 2
            assert applied_b2["ply"] == 2


def test_takeback_applied_includes_ply(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps(_move("e2", "e4")))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_b.send_text(json.dumps(_move("e7", "e5")))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "takeback_request"}))
            ws_w.receive_text()
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "takeback_response",
                                       "accept": True}))
            tb_w = json.loads(ws_w.receive_text())
            tb_b = json.loads(ws_b.receive_text())
            assert tb_w["type"] == "takeback_applied"
            assert tb_w["ply"] == 1
            assert tb_b["ply"] == 1


def test_dropped_broadcast_pushes_reconnecting_to_surviving_peer(client, monkeypatch):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()

            real_send = connections_module.send
            dropped = {"once": False}

            async def flaky_send(ws, message):
                if (isinstance(message, MoveAppliedMessage)
                        and not dropped["once"]):
                    dropped["once"] = True
                    return False
                return await real_send(ws, message)

            monkeypatch.setattr(connections_module, "send", flaky_send)

            ws_w.send_text(json.dumps(_move("e2", "e4")))
            seen_types = set()
            for _ in range(2):
                msg = json.loads(ws_b.receive_text())
                seen_types.add(msg["type"])
            assert "connection_status" in seen_types


def _ping(ply):
    return {"version": PROTOCOL_VERSION, "type": "ping", "ply": ply}


def test_ping_with_matching_ply_pongs_without_directive(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps(_ping(0)))
            msg = json.loads(ws_w.receive_text())
            assert msg["type"] == "pong"


def test_ping_with_wrong_ply_directs_resync_and_flags_opponent(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps(_ping(7)))
            got = {json.loads(ws_w.receive_text())["type"] for _ in range(2)}
            assert got == {"pong", "resync_directive"}
            status = json.loads(ws_b.receive_text())
            assert status["type"] == "connection_status"
            assert status["opp_state"] == "resyncing"


def test_reconnecting_client_gets_opponent_present_snapshot(client):
    """On reconnect the server tells the returning client its opponent's real
    presence, so a client that dropped can't be stuck showing the opponent red."""
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
        ws_b.send_text(json.dumps(_auth(b["session_token"])))
        with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
            ws_w.send_text(json.dumps(_auth(a["session_token"])))
            ws_w.receive_text()                       # game_start
            ws_b.receive_text()                       # game_start
        # white dropped -> black is told "reconnecting"; drain it
        assert json.loads(ws_b.receive_text())["type"] == "connection_status"
        with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w2:
            ws_w2.send_text(json.dumps(_auth(a["session_token"])))
            snap = json.loads(ws_w2.receive_text())
            assert snap["type"] == "connection_status"
            assert snap["opp_state"] == "connected", "opponent b is still here"


def test_reconnecting_client_told_opponent_still_gone(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()                       # game started, both present
        # black dropped inside; now white drops too
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w2:
        ws_w2.send_text(json.dumps(_auth(a["session_token"])))
        snap = json.loads(ws_w2.receive_text())
        assert snap["type"] == "connection_status"
        assert snap["opp_state"] == "reconnecting", "opponent is still gone"


def test_new_matchmake_abandons_in_progress_game(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps(_move("e2", "e4")))
            ws_w.receive_text()
            ws_b.receive_text()
            resp = _matchmake(client, uuid=ALICE, nickname="Alice", side="white")
            assert "room_id" in resp
            results = []
            for _ in range(3):
                msg = json.loads(ws_b.receive_text())
                if msg["type"] == "result":
                    results.append(msg)
                    break
            assert results and results[0]["reason"] == "abandonment"
            assert results[0]["winner_color"] == "black"


def _online_app():
    from chessshootout.frontend.frontend import Frontend
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.coordinator.client = MagicMock()
    app.coordinator.client.get_ping_ms.return_value = None
    app.coordinator.client.is_server_silent.return_value = False
    app.coordinator.client.heartbeat_interval.return_value = 2.0
    app.mode = ONLINE
    app.coordinator.subscribe(app.game)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game.match.mode = ONLINE
    app.game.match.local_color = PieceColor.WHITE
    return app


def test_remote_move_with_correct_ply_applies():
    app = _online_app()
    payload = {"from": "e2", "to": "e4", "san": "e4", "ply": 1,
               "clock": {}}
    app.coordinator._handle_remote_move_applied(payload)
    assert app.coordinator._resyncing is False
    app.coordinator.client.request_state_sync.assert_not_called()
    assert len(app.game.match.move_history) == 1


def test_remote_move_with_skipped_ply_triggers_resync():
    """Empty local history (ply 0) vs server ply 3 means plies 1-2 were missed."""
    app = _online_app()
    payload = {"from": "e7", "to": "e5", "san": "e5", "ply": 3,
               "clock": {}}
    app.coordinator._handle_remote_move_applied(payload)
    assert app.coordinator._resyncing is True
    app.coordinator.client.request_state_sync.assert_called_once()
    assert len(app.game.match.move_history) == 0


def test_remote_move_with_illegal_payload_triggers_resync():
    """Ply matches but from/to is illegal (no piece on e3); apply returns legal=False."""
    app = _online_app()
    payload = {"from": "e3", "to": "e4", "san": "e4", "ply": 1,
               "clock": {}}
    app.coordinator._handle_remote_move_applied(payload)
    assert app.coordinator._resyncing is True
    app.coordinator.client.request_state_sync.assert_called_once()


def test_resync_gate_drops_subsequent_move_applied():
    """A held gate drops the move without applying it or firing a new request."""
    app = _online_app()
    app.coordinator._resyncing = True
    payload = {"from": "e2", "to": "e4", "san": "e4", "ply": 1,
               "clock": {}}
    app.coordinator._handle_remote_move_applied(payload)
    assert len(app.game.match.move_history) == 0
    app.coordinator.client.request_state_sync.assert_not_called()


def test_takeback_applied_with_skipped_ply_triggers_resync():
    """Local has 1 ply but server's post-takeback ply 5 is impossible without misses."""
    from chessshootout.backend.utils import Square
    app = _online_app()
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    payload = {"clock": {}, "fen": "", "ply": 5}
    app.coordinator._handle_takeback_applied(payload)
    assert app.coordinator._resyncing is True
    app.coordinator.client.request_state_sync.assert_called_once()


def test_game_resumed_clears_resync_gate():
    app = _online_app()
    app.game._time_control = (300, 0)
    app.game.match.setup_clock(300, 0)
    app.coordinator._resyncing = True
    payload = {
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "move_history": [{"san": "e4"}, {"san": "e5"}],
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0,
                  "running_for": None},
    }
    app.coordinator._handle_game_resumed(payload)
    assert app.coordinator._resyncing is False
    assert len(app.game.match.move_history) == 2


def test_begin_resync_is_idempotent_during_inflight_request():
    """The in-flight flag suppresses duplicate requests across repeated calls."""
    app = _online_app()
    app.coordinator._begin_resync()
    app.coordinator._begin_resync()
    app.coordinator._begin_resync()
    assert app.coordinator._resyncing is True
    assert app.coordinator.client.request_state_sync.call_count == 1


def test_resync_directive_triggers_resync():
    """A server resync directive (sent when a heartbeat shows the client is behind)
    drives the standard /resume recovery."""
    from chessshootout.online.client import Event
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._handle_online_event(Event("resync_directive", {}))
    assert app.coordinator._resyncing is True
    app.coordinator.client.request_state_sync.assert_called_once()


def test_resyncing_shows_toast_each_frame():
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._resyncing = True
    app.coordinator._resync_started_at_ms = pg.time.get_ticks()
    app.coordinator._update_online_phase()
    assert app.toast.message == "Resyncing…"


def test_resyncing_self_heals_after_timeout():
    from chessshootout.frontend.online_coordinator import RESYNC_TIMEOUT_MS
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._resyncing = True
    app.coordinator._resync_started_at_ms = pg.time.get_ticks() - (RESYNC_TIMEOUT_MS + 1000)
    app.coordinator._update_online_phase()
    assert app.coordinator._resyncing is False


def test_resync_timeout_escalates_to_reconnect():
    """A resync that never lands escalates to a full reconnect, so the opponent's abandon
    countdown starts and recovery runs through the standard reconnect path."""
    from chessshootout.frontend.online_coordinator import RESYNC_TIMEOUT_MS
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._resyncing = True
    app.coordinator._resync_started_at_ms = pg.time.get_ticks() - (RESYNC_TIMEOUT_MS + 1000)
    app.coordinator._update_online_phase()
    assert app.coordinator._resyncing is False
    app.coordinator.client.force_reconnect.assert_called_once()


def test_resync_timeout_escalation_logs_a_warning_not_an_info(caplog):
    """Escalating a stuck resync to a full reconnect is a degraded path, not a
    routine state transition — it must not read as just another INFO line."""
    from chessshootout.frontend.online_coordinator import RESYNC_TIMEOUT_MS
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._resyncing = True
    app.coordinator._resync_started_at_ms = pg.time.get_ticks() - (RESYNC_TIMEOUT_MS + 1000)
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.coordinator._update_online_phase()
    lines = [r for r in caplog.records if "resync timed out" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.WARNING


def test_resync_timeout_no_escalation_when_already_reconnecting():
    from chessshootout.frontend.online_coordinator import RESYNC_TIMEOUT_MS
    app = _online_app()
    app.coordinator.client.state = "reconnecting"
    app.coordinator._resyncing = True
    app.coordinator._resync_started_at_ms = pg.time.get_ticks() - (RESYNC_TIMEOUT_MS + 1000)
    app.coordinator._update_online_phase()
    assert app.coordinator._resyncing is False
    app.coordinator.client.force_reconnect.assert_not_called()


def test_online_error_room_lost_clears_resyncing():
    app = _online_app()
    app.coordinator._resyncing = True
    app.coordinator._handle_online_error({"reason": "room_lost"})
    assert app.coordinator._resyncing is False


def test_opponent_resyncing_status_shows_toast():
    """The server drives the opponent-resyncing indication via connection_status."""
    app = _online_app()
    app.coordinator._handle_connection_status({"opp_state": "resyncing"})
    assert app.toast.message == "Opponent is resyncing…"
    assert app.game._opp_disconnected_at_ms is None


def test_heartbeat_sent_when_interval_elapsed():
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._last_heartbeat_sent_ms = pg.time.get_ticks() - 5000
    app.coordinator._send_heartbeat_if_due()
    app.coordinator.client.send_ping.assert_called_once_with(len(app.game.match.move_history))


def test_heartbeat_not_sent_before_interval():
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator._last_heartbeat_sent_ms = pg.time.get_ticks()
    app.coordinator._send_heartbeat_if_due()
    app.coordinator.client.send_ping.assert_not_called()


def test_server_silence_escalates_to_reconnect():
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator.client.is_server_silent.return_value = True
    app.coordinator._send_heartbeat_if_due()
    app.coordinator.client.force_reconnect.assert_called_once()
    app.coordinator.client.send_ping.assert_not_called()


def test_server_silence_logs_a_warning_not_an_info(caplog):
    """A missed heartbeat is a degraded connection, not routine chatter."""
    app = _online_app()
    app.coordinator.client.state = "connected"
    app.coordinator.client.is_server_silent.return_value = True
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.coordinator._send_heartbeat_if_due()
    lines = [r for r in caplog.records if "heartbeat silent" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.WARNING
