import json
import random

import pytest
from fastapi.testclient import TestClient

from server.app import (
    PROTOCOL_VERSION, WS_CLOSE_INVALID_TOKEN, _sweep, create_app,
)
from server.protocol import Reason
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)
CARL = fake_uuid4(3)
ZED = fake_uuid4(99)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def client(app):
    return TestClient(app)


def _matchmake(client, *, uuid=ALICE, nickname="Alice", time=5, inc=0, side="random"):
    return client.post("/matchmake", json={
        "version": PROTOCOL_VERSION,
        "client_uuid": uuid, "nickname": nickname,
        "time_minutes": time, "increment_seconds": inc,
        "side_preference": side,
    })


def _auth_msg(token):
    return {"version": PROTOCOL_VERSION, "type": "auth", "session_token": token}


def test_health_returns_zero_rooms_initially(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["rooms_active"] == 0
    # Expanded /healthz: queue_depth, uptime_s, version are all present.
    assert body["queue_depth"] == 0
    assert body["uptime_s"] >= 0.0
    assert body["version"] == PROTOCOL_VERSION


def test_matchmake_returns_room_and_token(client):
    r = _matchmake(client)
    assert r.status_code == 200
    body = r.json()
    assert "room_id" in body and "session_token" in body


def test_matchmake_rejects_invalid_time_control(client):
    r = _matchmake(client, time=0)
    assert r.status_code == 422
    r = client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": ZED, "nickname": "Z",
        "time_minutes": 5, "increment_seconds": -1,
    })
    assert r.status_code == 422


def test_matchmake_rejects_invalid_nickname(client):
    r = client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": ZED,
        "nickname": "", "time_minutes": 5, "increment_seconds": 0,
    })
    assert r.status_code == 422


def test_matchmake_rejects_already_in_game(client):
    r1 = _matchmake(client, uuid=ALICE)
    r2 = _matchmake(client, uuid=BOB)
    assert r1.status_code == 200 and r2.status_code == 200
    r3 = _matchmake(client, uuid=ALICE)
    assert r3.status_code == 409


def test_cancel_matchmake_removes_from_queue(client):
    r = _matchmake(client, uuid=ALICE)
    body = r.json()
    cancel = client.request("DELETE", "/matchmake", json={
        "version": PROTOCOL_VERSION,
        "room_id": body["room_id"], "session_token": body["session_token"],
    })
    assert cancel.status_code == 200
    # Same uuid can re-matchmake afterwards.
    r2 = _matchmake(client, uuid=ALICE)
    assert r2.status_code == 200


def test_cancel_with_bogus_token_rejected(client):
    r = _matchmake(client, uuid=ALICE)
    body = r.json()
    cancel = client.request("DELETE", "/matchmake", json={
        "version": PROTOCOL_VERSION,
        "room_id": body["room_id"], "session_token": "bogus",
    })
    assert cancel.status_code == 401


def test_ws_rejects_bad_auth_token(client):
    r1 = _matchmake(client, uuid=ALICE)
    r2 = _matchmake(client, uuid=BOB)
    body = r2.json()
    with client.websocket_connect(f"/ws/{body['room_id']}") as ws:
        ws.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "auth",
                                  "session_token": "bogus"}))
        with pytest.raises(Exception):
            ws.receive_text()


def test_ws_rejects_non_auth_first_message(client):
    r1 = _matchmake(client, uuid=ALICE)
    r2 = _matchmake(client, uuid=BOB)
    body = r2.json()
    with client.websocket_connect(f"/ws/{body['room_id']}") as ws:
        ws.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "move",
                                  "from": "e2", "to": "e4"}))
        with pytest.raises(Exception):
            ws.receive_text()


def test_two_clients_pair_and_get_game_start(client):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    a = r1.json()
    b = r2.json()
    assert a["room_id"] == b["room_id"]
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_a:
        ws_a.send_text(json.dumps(_auth_msg(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(b["session_token"])))
            msg_a = json.loads(ws_a.receive_text())
            msg_b = json.loads(ws_b.receive_text())
            assert msg_a["type"] == "game_start"
            assert msg_b["type"] == "game_start"
            assert msg_a["your_color"] == "white"
            assert msg_b["your_color"] == "black"
            assert msg_a["white_name"] == "Alice"
            assert msg_a["black_name"] == "Alice"  # nickname default in helper


def test_full_short_game_e4_e5_resign(client):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()  # game_start
            ws_b.receive_text()
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "move",
                                        "from": "e2", "to": "e4"}))
            applied_w = json.loads(ws_w.receive_text())
            applied_b = json.loads(ws_b.receive_text())
            assert applied_w["type"] == "move_applied"
            assert applied_w["san"] == "e4"
            assert applied_b["from"] == "e2"
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "move",
                                        "from": "e7", "to": "e5"}))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "resign"}))
            res_w = json.loads(ws_w.receive_text())
            res_b = json.loads(ws_b.receive_text())
            assert res_w["type"] == "result"
            assert res_w["reason"] == Reason.RESIGNATION
            assert res_w["winner_color"] == "black"


def test_out_of_turn_move_rejected(client):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            # Black tries to move first.
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "move",
                                        "from": "e7", "to": "e5"}))
            err = json.loads(ws_b.receive_text())
            assert err["type"] == "error"
            assert err["reason"] == Reason.NOT_YOUR_TURN


def test_invalid_move_format_rejected(client):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "move",
                                        "from": "z9", "to": "a1"}))
            err = json.loads(ws_w.receive_text())
            assert err["type"] == "error"
            assert err["reason"] == Reason.INVALID_MOVE_FORMAT


@pytest.mark.asyncio
async def test_first_move_timeout_aborts_room(app, clock):
    random.seed(0)
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    clock.advance(61)
    await _sweep(app)
    assert room.result == ("aborted", None)


@pytest.mark.asyncio
async def test_clock_flag_during_play_broadcasts_timeout(app, clock):
    random.seed(0)
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=1, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=1, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    room.first_move_at = clock()
    clock.advance(70)
    await _sweep(app)
    assert room.result is not None
    assert room.result[0] == Reason.TIMEOUT


@pytest.mark.asyncio
async def test_grace_expiry_yields_abandonment(app, clock):
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    # Pretend a move was already made — this skips the first-move-abort window.
    room.started_at = clock()
    room.first_move_at = clock()
    rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await _sweep(app)
    assert room.result == (Reason.ABANDONMENT, "black")
