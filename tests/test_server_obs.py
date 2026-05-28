"""M18b: WS dispatch DEBUG observability + per-WS rate limit.

ADD-39 asks for a DEBUG-level dispatch line of the shape:
    room=… uuid=… type=… latency_ms=… outcome=…

We assert the line shape by capturing the records the dispatch code
emits during a real (in-process) WS session, plus a unit test on the
dispatch function so the outcome string is part of the public contract
of every handler.
"""
import json
import logging
import random

import pytest
from fastapi.testclient import TestClient

from server.app import (
    PROTOCOL_VERSION, WS_MESSAGES_PER_SECOND, create_app,
)
from server.handlers import HANDLERS, dispatch
from server.protocol import Reason
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


# ---- HANDLERS dispatch table is the canonical message map -------------------

def test_handlers_dispatch_table_covers_all_known_message_types():
    expected = {
        "move", "resign", "draw_offer", "draw_response",
        "rematch_request", "rematch_response",
        "takeback_request", "takeback_response",
        "give_time", "resync",
    }
    assert set(HANDLERS.keys()) == expected


# ---- Dispatch emits a DEBUG log line with the documented shape -------------

def test_dispatch_debug_log_contains_required_keys(client, caplog):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with caplog.at_level(logging.DEBUG, logger="chess.server.app"):
        with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
            ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
            with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
                ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
                ws_w.receive_text()  # game_start
                ws_b.receive_text()
                ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                            "type": "move",
                                            "from": "e2", "to": "e4"}))
                ws_w.receive_text()
                ws_b.receive_text()
    dispatch_lines = [r.getMessage() for r in caplog.records
                      if "ws dispatch" in r.getMessage()]
    assert dispatch_lines, "expected at least one ws dispatch DEBUG line"
    line = dispatch_lines[0]
    for key in ("room=", "uuid=", "type=", "latency_ms=", "outcome="):
        assert key in line, f"missing {key} in {line!r}"


# ---- Per-WS rate limit -------------------------------------------------------

def test_per_ws_rate_limit_constant_is_documented():
    # Plan calls for "in-process limiter (e.g. 30/sec)". Pin the value so
    # we don't silently drift from the documented threshold.
    assert WS_MESSAGES_PER_SECOND == 30


def test_per_ws_rate_limit_emits_rate_limited_error(client, clock):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()  # game_start
            ws_b.receive_text()
            # Burst more bogus moves than the WS limit — they're cheap and
            # don't change game state, so we get pure rate-limit feedback.
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


# ---- dispatch() return contract — (msg_type, outcome) ----------------------

@pytest.mark.asyncio
async def test_dispatch_returns_invalid_message_for_unknown_type(app):
    # Build the smallest viable room+websocket stand-in so we can call
    # dispatch directly without going through TestClient.
    class _FakeWS:
        def __init__(self):
            self.sent = []

        async def send_json(self, payload):
            self.sent.append(payload)
    ws = _FakeWS()

    # We don't even need a real Room — dispatch returns before consulting
    # the handler when peek_type returns None.
    msg_type, outcome = await dispatch(app, ws, room=None, color="white",
                                          raw='{"type":"made_up","version":1}')
    assert msg_type == "made_up"
    assert outcome == "invalid_message"
    assert any(p.get("reason") == Reason.INVALID_MESSAGE for p in ws.sent)
