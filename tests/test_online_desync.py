"""Desync detection + /resume recovery (commit 1).

Covers:
- Server's MoveAppliedMessage / TakebackAppliedMessage carry a `ply` field
  (used by clients to detect dropped broadcasts).
- Server pushes ConnectionStatusMessage(opp_state="reconnecting") to the
  surviving peer when a broadcast send fails.
- Client detects out-of-order moves by ply mismatch and fires
  request_state_sync, gating further move_applied via the `_resyncing` flag.
- _handle_game_resumed clears the gate.
"""
import json
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest
from fastapi.testclient import TestClient

from backend.match import ONLINE
from backend.pieces import PieceColor
from server import connections as connections_module
from server.app import PROTOCOL_VERSION, create_app
from server.protocol import MoveAppliedMessage
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


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


# ---------- Server: ply field on broadcasts ----------

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
            # Ply 1 because exactly one move has been played.
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
            # The player who just moved (black) can request a takeback
            # of their own last move; white accepts.
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "takeback_request"}))
            ws_w.receive_text()  # takeback_offered
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "takeback_response",
                                       "accept": True}))
            tb_w = json.loads(ws_w.receive_text())
            tb_b = json.loads(ws_b.receive_text())
            assert tb_w["type"] == "takeback_applied"
            assert tb_w["ply"] == 1
            assert tb_b["ply"] == 1


# ---------- Server: dropped broadcast pushes reconnecting status ----------

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
            # The first recipient gets dropped; the second peer gets the
            # move_applied AND a connection_status: reconnecting.
            seen_types = set()
            for _ in range(2):
                msg = json.loads(ws_b.receive_text())
                seen_types.add(msg["type"])
            assert "connection_status" in seen_types


# ---------- Client: ply check + resync gate ----------

def _online_app(monkeypatch=None):
    from frontend.frontend import Frontend
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.online_client = MagicMock()
    app.online_client.get_ping_ms.return_value = None
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app.match.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    return app


def test_remote_move_with_correct_ply_applies(monkeypatch):
    app = _online_app()
    payload = {"from": "e2", "to": "e4", "san": "e4", "ply": 1,
               "clock": {}}
    app._handle_remote_move_applied(payload)
    assert app._resyncing is False
    app.online_client.request_state_sync.assert_not_called()
    assert len(app.match.move_history) == 1


def test_remote_move_with_skipped_ply_triggers_resync(monkeypatch):
    app = _online_app()
    # Local history is empty (ply 0); server claims this is ply 3 —
    # we've missed plies 1 and 2.
    payload = {"from": "e7", "to": "e5", "san": "e5", "ply": 3,
               "clock": {}}
    app._handle_remote_move_applied(payload)
    assert app._resyncing is True
    app.online_client.request_state_sync.assert_called_once()
    # The illegal/out-of-order move must not have been applied.
    assert len(app.match.move_history) == 0


def test_remote_move_with_illegal_payload_triggers_resync(monkeypatch):
    app = _online_app()
    # Ply matches but the from/to is illegal in the current position
    # (no piece on e3). apply_remote_move returns legal=False.
    payload = {"from": "e3", "to": "e4", "san": "e4", "ply": 1,
               "clock": {}}
    app._handle_remote_move_applied(payload)
    assert app._resyncing is True
    app.online_client.request_state_sync.assert_called_once()


def test_resync_gate_drops_subsequent_move_applied(monkeypatch):
    app = _online_app()
    app._resyncing = True
    payload = {"from": "e2", "to": "e4", "san": "e4", "ply": 1,
               "clock": {}}
    app._handle_remote_move_applied(payload)
    # Gate held → no apply, no further request.
    assert len(app.match.move_history) == 0
    app.online_client.request_state_sync.assert_not_called()


def test_takeback_applied_with_skipped_ply_triggers_resync(monkeypatch):
    from backend.utils import Square
    app = _online_app()
    app.match.try_move(Square(6, 4), Square(4, 4))
    # Local has 1 ply. Server claims post-takeback ply is 5 —
    # impossible without missed moves.
    payload = {"clock": {}, "fen": "", "ply": 5}
    app._handle_takeback_applied(payload)
    assert app._resyncing is True
    app.online_client.request_state_sync.assert_called_once()


def test_game_resumed_clears_resync_gate(monkeypatch):
    app = _online_app()
    app._time_control = (300, 0)
    app.match.setup_clock(300, 0)
    app._resyncing = True
    payload = {
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "move_history": [
            {"san": "e4", "from": "e2", "to": "e3"},
            {"san": "e5", "from": "e7", "to": "e6"},
        ],
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0,
                  "running_for": None},
    }
    app._handle_game_resumed(payload)
    assert app._resyncing is False
    assert len(app.match.move_history) == 2


def test_begin_resync_is_idempotent_during_inflight_request(monkeypatch):
    app = _online_app()
    app._begin_resync()
    app._begin_resync()
    app._begin_resync()
    # The flag prevents duplicate requests while a resync is in flight.
    assert app._resyncing is True
    assert app.online_client.request_state_sync.call_count == 1


# ---------- Client: periodic state-sync beacon reconciliation ----------

def test_state_sync_matching_ply_is_noop():
    app = _online_app()
    app.online_client.state = "connected"
    # Local history is empty (ply 0) and the beacon agrees.
    app._handle_state_sync({"ply": 0})
    assert app._resyncing is False
    assert app._last_beacon_mismatch_ply is None
    app.online_client.request_state_sync.assert_not_called()


def test_state_sync_single_mismatch_does_not_resync():
    app = _online_app()
    app.online_client.state = "connected"
    # One diverged beacon could be a move legitimately in flight — debounce.
    app._handle_state_sync({"ply": 2})
    assert app._resyncing is False
    assert app._last_beacon_mismatch_ply == 2
    app.online_client.request_state_sync.assert_not_called()


def test_state_sync_stable_mismatch_triggers_resync():
    app = _online_app()
    app.online_client.state = "connected"
    # The same divergence on two consecutive beacons is a real lost move.
    app._handle_state_sync({"ply": 2})
    app._handle_state_sync({"ply": 2})
    assert app._resyncing is True
    app.online_client.send_resync.assert_called_once()
    app.online_client.request_state_sync.assert_called_once()


def test_state_sync_ignored_while_reconnecting():
    app = _online_app()
    app.online_client.state = "reconnecting"
    app._handle_state_sync({"ply": 5})
    app._handle_state_sync({"ply": 5})
    assert app._resyncing is False
    assert app._last_beacon_mismatch_ply is None
    app.online_client.request_state_sync.assert_not_called()


def test_state_sync_ignored_while_resyncing():
    app = _online_app()
    app.online_client.state = "connected"
    app._resyncing = True
    app._handle_state_sync({"ply": 5})
    app.online_client.request_state_sync.assert_not_called()


# ---------- Client: resync self-heal + both-player indicators ----------

def test_resyncing_shows_toast_each_frame():
    app = _online_app()
    app.online_client.state = "connected"
    app._resyncing = True
    app._resync_started_at_ms = pg.time.get_ticks()
    app._update_online_phase()
    assert app.toast.message == "Resyncing…"


def test_resyncing_self_heals_after_timeout():
    from frontend.frontend import RESYNC_TIMEOUT_MS
    app = _online_app()
    app.online_client.state = "connected"
    app._resyncing = True
    app._last_beacon_mismatch_ply = 3
    app._resync_started_at_ms = pg.time.get_ticks() - (RESYNC_TIMEOUT_MS + 1000)
    app._update_online_phase()
    assert app._resyncing is False
    assert app._last_beacon_mismatch_ply is None


def test_online_error_room_lost_clears_resyncing():
    app = _online_app()
    app._resyncing = True
    app._handle_online_error({"reason": "room_lost"})
    assert app._resyncing is False


def test_opponent_resync_shows_toast():
    from frontend.online.client import Event
    app = _online_app()
    app._handle_online_event(Event("resync", {}))
    assert app.toast.message == "Opponent is resyncing…"
