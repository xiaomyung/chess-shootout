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
from chessshootout.backend.utils import square_from_coord
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


def _recv_type(ws, msg_type):
    """Next frame of the given type. Protocol v5 force-pushes idle_window after
    plies 1 and 2, so positional reads are no longer stable."""
    while True:
        msg = json.loads(ws.receive_text())
        if msg["type"] == msg_type:
            return msg


def test_move_applied_includes_ply(client):
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps(_move("e2", "e4")))
            applied_w = _recv_type(ws_w, "move_applied")
            applied_b = _recv_type(ws_b, "move_applied")
            assert applied_w["ply"] == 1
            assert applied_b["ply"] == 1
            ws_b.send_text(json.dumps(_move("e7", "e5")))
            applied_w2 = _recv_type(ws_w, "move_applied")
            applied_b2 = _recv_type(ws_b, "move_applied")
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
            _recv_type(ws_w, "move_applied")
            _recv_type(ws_b, "move_applied")
            ws_b.send_text(json.dumps(_move("e7", "e5")))
            _recv_type(ws_w, "move_applied")
            _recv_type(ws_b, "move_applied")
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "takeback_request"}))
            _recv_type(ws_w, "takeback_offered")
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "takeback_response",
                                       "accept": True}))
            tb_w = _recv_type(ws_w, "takeback_applied")
            tb_b = _recv_type(ws_b, "takeback_applied")
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


def _quick_chat():
    return {"version": PROTOCOL_VERSION, "type": "quick_chat", "preset": 0}


def _drain_until_chat(ws):
    """Sentinel drain: quick_chat is relayed straight through with no state of
    its own, so the frame after it is a hard end-of-stream marker -- everything
    the flapping pings produced has to arrive ahead of it."""
    seen = []
    while True:
        msg = json.loads(ws.receive_text())
        if msg["type"] == "quick_chat_received":
            return seen
        seen.append(msg)


def test_flapping_ping_notifies_the_opponent_once_per_window(client, clock):
    """Griefing pin: `ply` is client-supplied, so a hostile client can alternate
    correct/incorrect plies at the websocket rate limit (30/s) and toggle the
    opponent's resync state 15 times a second. Every `resyncing` transition
    toasts the opponent, and toasts dedupe by key, so the opponent ends up with
    a permanently stuck banner plus UI state flapping at 15 Hz.

    The server debounces the NOTIFY direction only: the opponent is told
    `resyncing` at most once per RESYNC_NOTIFY_MIN_INTERVAL_SECONDS per
    connection. Clears stay ungated on purpose -- `connected` raises no toast,
    and delaying it would leave a stale "opponent is resyncing" banner up after
    a genuine recovery, which is the honest-path cost this fix must not pay."""
    from chessshootout.server.handlers import RESYNC_NOTIFY_MIN_INTERVAL_SECONDS

    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()

            for i in range(8):
                ws_w.send_text(json.dumps(_ping(7 if i % 2 == 0 else 0)))
            ws_w.send_text(json.dumps(_quick_chat()))

            states = [m["opp_state"] for m in _drain_until_chat(ws_b)
                      if m["type"] == "connection_status"]
            assert states == ["resyncing", "connected"]

            clock.advance(RESYNC_NOTIFY_MIN_INTERVAL_SECONDS + 0.1)
            ws_w.send_text(json.dumps(_ping(7)))
            status = json.loads(ws_b.receive_text())
            assert status["type"] == "connection_status"
            assert status["opp_state"] == "resyncing", (
                "a fresh window must notify again -- this is a debounce, not a latch")


def test_flapping_ping_cannot_amplify_resync_directives(client, clock):
    """The directive rides back to the sender, and each one drives a /resume, so
    an unbounded 30/s stream is self-inflicted amplification against the server's
    own state-rebuild path. One per RESYNC_DIRECTIVE_MIN_INTERVAL_SECONDS is
    enough: honest clients ping on the 2 s heartbeat, so their recovery cadence
    is untouched."""
    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()

            for _ in range(8):
                ws_w.send_text(json.dumps(_ping(7)))

            # Read the exact frame count the debounce must produce -- eight
            # pongs and one directive -- straight off the pinging socket, where
            # per-connection ordering makes it deterministic. The opponent's
            # chat cannot serve as the end marker here: it is sent on the OTHER
            # socket, so on a loaded runner its relay can overtake the tail of
            # this socket's pongs. It still proves nothing FURTHER is queued.
            kinds = [json.loads(ws_w.receive_text())["type"] for _ in range(9)]
            assert kinds.count("pong") == 8
            assert kinds.count("resync_directive") == 1

            ws_b.send_text(json.dumps(_quick_chat()))
            assert _drain_until_chat(ws_w) == [], "the window produced nothing else"


def test_sustained_desync_keeps_directing_resync_promptly(client, clock):
    """The debounce must not slow a real recovery: a client that is genuinely
    behind is directed on its very first mismatching ping, and again on the next
    heartbeat -- the directive interval is shorter than the heartbeat, so an
    honest client's cadence never hits the gate."""
    from chessshootout.server.handlers import RESYNC_DIRECTIVE_MIN_INTERVAL_SECONDS
    from chessshootout.server.protocol import HEARTBEAT_INTERVAL_SECONDS

    assert RESYNC_DIRECTIVE_MIN_INTERVAL_SECONDS < HEARTBEAT_INTERVAL_SECONDS

    a, b = _paired_ws(client)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()

            ws_w.send_text(json.dumps(_ping(7)))
            first = {json.loads(ws_w.receive_text())["type"] for _ in range(2)}
            assert first == {"pong", "resync_directive"}

            clock.advance(HEARTBEAT_INTERVAL_SECONDS)
            ws_w.send_text(json.dumps(_ping(7)))
            second = {json.loads(ws_w.receive_text())["type"] for _ in range(2)}
            assert second == {"pong", "resync_directive"}


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
    app.coordinator.subscribe(app.game)
    app.game.variant = "online"
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


def test_resync_gate_does_not_outlive_the_session_it_belongs_to():
    """_resyncing gates give-time holds and result promotion and drives a
    per-frame "Resyncing…" toast. Dropping the client without clearing it left a
    phantom toast on the start menu and, if the next match paired inside the 8 s
    window, silently gated the new game."""
    for drop in ("_tear_down_online_session", "_on_online_cancel"):
        app = _online_app()
        app.coordinator._begin_resync()
        assert app.coordinator._resyncing is True

        getattr(app.coordinator, drop)()

        assert app.coordinator._resyncing is False, drop


def test_resync_gate_is_cleared_when_the_socket_is_kept_for_a_rematch():
    app = _online_app()
    app.coordinator._begin_resync()

    app.coordinator.retain_for_rematch(True)

    assert app.coordinator._resyncing is False


def test_resume_with_no_active_online_game_is_dropped_and_clears_the_gate():
    """The post-game rematch window keeps the socket alive after the user is back
    on the menu (variant flipped to "local"). A late /resume reply there has no
    live game to rebuild — it must not replay moves into the inactive screen."""
    app = _online_app()
    app.game.variant = "local"
    app.coordinator._begin_resync()

    app.coordinator._handle_game_resumed({
        "fen": "",
        "move_history": [{"san": "e4"}, {"san": "e5"}],
        "clock": {},
    })

    assert app.game.match.move_history == []
    assert app.coordinator._resyncing is False


BLOCKED_ARROW = {"from": "e2", "to": "e4"}
BLOCKED_MARKS = {(square_from_coord("e2"), square_from_coord("e4")),
                 square_from_coord("c3")}


def _blocked_payload():
    return {"action": "blocked", "arrows": [BLOCKED_ARROW],
            "highlights": ["c3"], "share_muted": False}


def _resumable_app():
    app = _online_app()
    app.game._time_control = (300, 0)
    app.game.match.setup_clock(300, 0)
    return app


def _resumed_payload(**extra):
    payload = {
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "move_history": [],
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0,
                  "running_for": None},
    }
    payload.update(extra)
    return payload


def test_marks_state_is_dropped_not_buffered_while_resyncing():
    """Replaying annotation state/deltas on top of the /resume snapshot is the
    unsafe option: a mark the opponent deleted before the snapshot comes back
    from a buffered `add` and sticks until they toggle it again. Every resync
    exit is followed by an authoritative snapshot (the timeout escalates to a
    reconnect, which re-emits game_resumed), so marks state is dropped outright
    rather than queued."""
    app = _online_app()
    app.coordinator._resyncing = True

    app.coordinator._handle_annotation_delta(
        {"action": "add", "kind": "arrow", "from": "e2", "to": "e4"})
    app.coordinator._handle_annotations_state(
        {"sharing": True, "highlights": ["c3"], "arrows": [BLOCKED_ARROW]})

    assert app.coordinator._resync_buffer == []
    assert app.game.board.annotations.opp_arrows == []
    assert app.game.board.annotations.opp_highlighted_squares == set()


def test_a_blocked_notification_survives_a_cancelled_resync():
    """`annotations_blocked` is the one payload a /resume cannot rebuild: it is a
    one-shot notification (toast + flag_own), so it keeps buffering while the
    gate is up and replays on every exit -- including the timeout cancel. The
    toast assertion is the end-to-end claim: in the real timeout-cancel path a
    force_reconnect /resume follows and _restore_resumed_annotations hard-resets
    annotations.flagged, so only the toast truly survives. The flagged assertion
    is unit-local to this test, which has no follow-up resume."""
    app = _online_app()
    app.coordinator._resyncing = True
    app.coordinator._handle_annotations_blocked(_blocked_payload())
    assert app.game.board.annotations.flagged == set()

    app.coordinator._end_resync()

    assert app.toast.message == "Some marks can't be shared"
    assert app.game.board.annotations.flagged == BLOCKED_MARKS


def test_a_blocked_notification_replays_after_a_resume():
    """The replay has to run AFTER on_resume, not before: on_resume wipes
    annotations.flagged, so a blocked notification replayed ahead of it would be
    erased by the very snapshot that cannot carry it."""
    app = _resumable_app()
    app.coordinator._resyncing = True
    app.coordinator._handle_annotations_blocked(_blocked_payload())

    app.coordinator._handle_game_resumed(_resumed_payload())

    assert app.coordinator._resyncing is False
    assert app.coordinator._resync_buffer == []
    assert app.game.board.annotations.flagged == BLOCKED_MARKS


def test_a_cancelled_resync_with_no_subscriber_replays_nothing(caplog):
    """Teardown paths (_drop_client, retain_for_rematch, room_lost) cancel the
    resync once the GameScreen has already unsubscribed. Replaying there would
    toast onto the start menu and trip _forward_board_event's "no subscriber"
    log.error, so the buffer is dropped instead."""
    app = _online_app()
    app.coordinator._resyncing = True
    app.coordinator._handle_annotations_blocked(_blocked_payload())
    app.coordinator.unsubscribe(app.game)

    with caplog.at_level(logging.ERROR, logger="chess.frontend"):
        app.coordinator._end_resync()

    assert app.coordinator._resync_buffer == []
    assert app.toast.message is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_teardown_exit_drops_the_buffer_even_with_a_live_subscriber():
    """room_lost and the hard-failure confirms fire while the GameScreen is
    still subscribed, and the abandon path drops the client before the menu
    switch -- the no-subscriber guard misses all three orderings. Those exits
    pass replay=False: the game is over, so a late blocked notification must
    not toast over the end-of-game modal."""
    app = _online_app()
    app.coordinator._resyncing = True
    app.coordinator._handle_annotations_blocked(_blocked_payload())

    app.coordinator._end_resync(replay=False)

    assert app.coordinator._resync_buffer == []
    assert app.toast.message is None
    assert app.game.board.annotations.flagged == set()


def test_a_resume_snapshot_is_never_overwritten_by_stale_deltas():
    """The resurrection regression: the opponent draws an arrow and deletes it,
    the server's snapshot omits it, and the mid-resync `add` used to be replayed
    on top of the fresh board -- putting a mark back that the server had already
    settled as gone."""
    app = _resumable_app()
    arrow = (square_from_coord("e2"), square_from_coord("e4"))
    app.game.board.annotations.set_opp(set(), [arrow])
    app.coordinator._resyncing = True

    app.coordinator._handle_annotation_delta(
        {"action": "add", "kind": "arrow", "from": "e2", "to": "e4"})
    app.coordinator._handle_game_resumed(_resumed_payload(
        black_annotations={"sharing": True, "highlights": [], "arrows": []}))

    assert app.game.board.annotations.opp_arrows == []
