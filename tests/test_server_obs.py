"""WS dispatch DEBUG observability + per-WS rate limit.

The dispatch path emits a DEBUG line of the shape
``ws dispatch room=… uuid=… type=… latency_ms=… outcome=…``; we assert that
shape (and the field values) by capturing the records emitted during a real
in-process WS session, plus a unit test on ``dispatch`` so the outcome string
stays part of every handler's public contract.
"""
import json
import logging
import random

import pytest
from fastapi.testclient import TestClient

from chessshootout.server.app import (
    PROTOCOL_VERSION, WS_MESSAGES_PER_SECOND, create_app,
)
from chessshootout.server.handlers import HANDLERS, dispatch
from chessshootout.server.protocol import Reason
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def client(app):
    return TestClient(app)


def _matchmake(client, *, uuid, side):
    return client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": uuid,
        "nickname": uuid[:8], "time_minutes": 5, "increment_seconds": 0,
        "side_preference": side,
    })


def _auth_msg(token):
    return {"version": PROTOCOL_VERSION, "type": "auth", "session_token": token}


def _parse_dispatch_line(line):
    """``ws dispatch room=… uuid=… type=… latency_ms=… outcome=…`` -> field dict."""
    body = line.split("ws dispatch", 1)[1].strip()
    fields = {}
    for token in body.split():
        key, _, value = token.partition("=")
        fields[key] = value
    return fields


def test_handlers_dispatch_table_covers_all_known_message_types():
    expected = {
        "move", "resign", "draw_offer", "draw_response",
        "rematch_request", "rematch_response",
        "takeback_request", "takeback_response",
        "give_time", "resync",
    }
    assert set(HANDLERS.keys()) == expected


def test_dispatch_debug_log_reports_move_room_type_and_outcome(client, caplog):
    """The first move's dispatch line carries all five keys plus type=move,
    outcome=applied, and the room id it acted on — verified against
    handle_move (returns "applied") and the app.py log format."""
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    room_id = r1.json()["room_id"]
    with caplog.at_level(logging.DEBUG, logger="chess.server.app"):
        with client.websocket_connect(f"/ws/{room_id}") as ws_w:
            ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
            with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
                ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
                ws_w.receive_text()
                ws_b.receive_text()
                ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                            "type": "move",
                                            "from": "e2", "to": "e4"}))
                ws_w.receive_text()
                ws_b.receive_text()
    dispatch_lines = [r.getMessage() for r in caplog.records
                      if "ws dispatch" in r.getMessage()]
    assert dispatch_lines, "expected at least one ws dispatch DEBUG line"
    move_fields = next(
        (f for f in map(_parse_dispatch_line, dispatch_lines)
         if f.get("type") == "move"), None)
    assert move_fields is not None, "expected a ws dispatch line for the move"
    assert set(move_fields) == {"room", "uuid", "type", "latency_ms", "outcome"}
    assert move_fields["room"] == room_id
    assert move_fields["uuid"] == ALICE[:8]
    assert move_fields["outcome"] == "applied"
    assert float(move_fields["latency_ms"]) >= 0.0


def test_per_ws_rate_limit_constant_is_documented():
    """Pin the documented 30/sec WS threshold so the limiter can't drift silently."""
    assert WS_MESSAGES_PER_SECOND == 30


def test_per_ws_rate_limit_emits_rate_limited_error(client):
    """A burst past the per-WS cap yields at least one rate_limited error.

    Bogus moves are used because they're cheap and never mutate game state, so
    the burst response is pure rate-limit feedback.
    """
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            for _ in range(WS_MESSAGES_PER_SECOND + 5):
                ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                            "type": "move",
                                            "from": "z9", "to": "a1"}))
            seen = []
            for _ in range(WS_MESSAGES_PER_SECOND + 5):
                msg = json.loads(ws_w.receive_text())
                seen.append(msg)
            reasons = [m.get("reason") for m in seen if m.get("type") == "error"]
            assert Reason.RATE_LIMITED in reasons, (
                "expected at least one rate_limited error in burst response")


@pytest.mark.asyncio
async def test_dispatch_returns_invalid_message_for_unknown_type(app):
    """dispatch returns (msg_type, "invalid_message") and sends an error before
    consulting any handler when the type is unknown, so room may be None."""
    class _FakeWS:
        def __init__(self):
            self.sent = []

        async def send_json(self, payload):
            self.sent.append(payload)
    ws = _FakeWS()

    msg_type, outcome = await dispatch(app, ws, room=None, color="white",
                                         raw='{"type":"made_up","version":1}')
    assert msg_type == "made_up"
    assert outcome == "invalid_message"
    assert any(p.get("reason") == Reason.INVALID_MESSAGE for p in ws.sent)
