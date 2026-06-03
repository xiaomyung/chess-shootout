import json
import random

import pytest
from fastapi.testclient import TestClient

from chessshootout.server.app import PROTOCOL_VERSION, create_app


async def _sweep(app):
    await app.state.sweep.step_all()
from chessshootout.server.connections import ConnectionRegistry
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, Reason
from tests.helpers import FakeClock, fake_uuid4


def test_registry_add_returns_displaced_socket():
    reg = ConnectionRegistry()
    ws_old, ws_new = object(), object()
    assert reg.add("r", "u", ws_old) is None
    assert reg.add("r", "u", ws_new) is ws_old
    assert reg.add("r", "u", ws_new) is None


def test_registry_remove_is_identity_guarded():
    reg = ConnectionRegistry()
    ws_old, ws_new = object(), object()
    reg.add("r", "u", ws_old)
    reg.add("r", "u", ws_new)
    assert reg.remove("r", "u", ws_old) is False
    assert reg._by_room["r"]["u"] is ws_new
    assert reg.remove("r", "u", ws_new) is True
    assert "r" not in reg._by_room


def test_registry_remove_unknown_room_returns_false():
    reg = ConnectionRegistry()
    assert reg.remove("nope", "u", object()) is False


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
    """/healthz exposes status, rooms_active, queue_depth, uptime_s, version."""
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["rooms_active"] == 0
    assert body["queue_depth"] == 0
    assert body["uptime_s"] >= 0.0
    assert body["version"] == PROTOCOL_VERSION


def test_matchmake_returns_room_and_token(client):
    r = _matchmake(client)
    assert r.status_code == 200
    body = r.json()
    assert "room_id" in body and "session_token" in body


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {"version": PROTOCOL_VERSION, "client_uuid": ALICE, "nickname": "Alice",
             "time_minutes": 0, "increment_seconds": 0, "side_preference": "random"},
            id="zero_time_minutes",
        ),
        pytest.param(
            {"version": PROTOCOL_VERSION, "client_uuid": ZED, "nickname": "Z",
             "time_minutes": 5, "increment_seconds": -1},
            id="negative_increment",
        ),
        pytest.param(
            {"version": PROTOCOL_VERSION, "client_uuid": ZED,
             "nickname": "", "time_minutes": 5, "increment_seconds": 0},
            id="empty_nickname",
        ),
    ],
)
def test_matchmake_rejects_invalid_field(client, body):
    """Each invalid matchmake field is rejected with 422 before any room is created."""
    assert client.post("/matchmake", json=body).status_code == 422
    assert client.get("/healthz").json()["rooms_active"] == 0


def test_matchmake_rejects_already_in_game(client):
    r1 = _matchmake(client, uuid=ALICE)
    r2 = _matchmake(client, uuid=BOB)
    assert r1.status_code == 200 and r2.status_code == 200
    r3 = _matchmake(client, uuid=ALICE)
    assert r3.status_code == 409


def test_cancel_matchmake_removes_from_queue(client):
    """Cancelling frees the uuid: it can re-matchmake afterwards."""
    r = _matchmake(client, uuid=ALICE)
    body = r.json()
    cancel = client.request("DELETE", "/matchmake", json={
        "version": PROTOCOL_VERSION,
        "room_id": body["room_id"], "session_token": body["session_token"],
    })
    assert cancel.status_code == 200
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
    _matchmake(client, uuid=ALICE)
    r2 = _matchmake(client, uuid=BOB)
    body = r2.json()
    with client.websocket_connect(f"/ws/{body['room_id']}") as ws:
        ws.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "auth",
                                  "session_token": "bogus"}))
        with pytest.raises(Exception):
            ws.receive_text()


def test_ws_rejects_non_auth_first_message(client):
    _matchmake(client, uuid=ALICE)
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
            assert msg_a["black_name"] == "Alice"
            assert "started_seconds_ago" in msg_a
            assert msg_a["started_seconds_ago"] == pytest.approx(0.0, abs=1.0)


def test_full_short_game_e4_e5_resign(client):
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
            ws_b.receive_text()
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
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "move",
                                        "from": "e7", "to": "e5"}))
            err = json.loads(ws_b.receive_text())
            assert err["type"] == "error"
            assert err["reason"] == Reason.NOT_YOUR_TURN
            assert err["msg_type"] == "move"


def test_draw_offer_allowed_off_turn(client):
    """Draws may be offered at any moment, regardless of whose turn it is: black
    (not on move at the start) offers and white receives the draw_offered relay."""
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                        "type": "draw_offer"}))
            msg = json.loads(ws_w.receive_text())
            assert msg["type"] == "draw_offered"


def test_takeback_request_off_turn_tags_msg_type(client):
    random.seed(0)
    r1 = _matchmake(client, uuid=ALICE, side="white")
    r2 = _matchmake(client, uuid=BOB, side="black")
    with client.websocket_connect(f"/ws/{r1.json()['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth_msg(r1.json()["session_token"])))
        with client.websocket_connect(f"/ws/{r2.json()['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth_msg(r2.json()["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_w.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                        "type": "takeback_request"}))
            err = json.loads(ws_w.receive_text())
            assert err["type"] == "error"
            assert err["reason"] == Reason.NOT_YOUR_TURN
            assert err["msg_type"] == "takeback_request"


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
    clock.advance(FIRST_MOVE_ABORT_SECONDS + 1)
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
    """first_move_at set skips the abort window; grace expiry awards the opponent."""
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    room.first_move_at = clock()
    rooms.mark_disconnected(room.room_id, "white")
    clock.advance(GRACE_SECONDS + 1)
    await _sweep(app)
    assert room.result == (Reason.ABANDONMENT, "black")


@pytest.mark.asyncio
async def test_resume_ticks_clock_before_snapshotting(app, client, clock):
    """/resume ticks the clock before snapshotting, so its reply reflects elapsed
    time as of the request rather than the last sweep tick (a stale snapshot would
    return the pre-advance white_remaining)."""
    random.seed(0)
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    room.first_move_at = clock()
    initial_white = room.backend.clock.white_remaining
    clock.advance(7)
    r = client.post("/resume", json={
        "version": PROTOCOL_VERSION,
        "room_id": room.room_id,
        "session_token": "ta",
    })
    assert r.status_code == 200
    snap = r.json()["clock"]
    assert snap["white_remaining"] == pytest.approx(initial_white - 7, abs=0.01)
    assert snap["running_for"] == "white"
