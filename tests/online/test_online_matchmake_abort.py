"""Leaving a game for a new search, or cancelling into a pairing, over the wire.

A player who searches again while still seated -- or cancels from the wait card
just as an opponent pairs them -- gives the old game up. What the opponent's
socket hears is the contract pinned here, frame by frame:

- nobody moved yet (or only white did): `result{aborted, None}`, then
  `rematch_update{opponent_left}`;
- both sides moved: `result{abandonment, <opponent>}`, then `opponent_left`.

The second frame is the fix for an old gap: a player abandoned mid-game used to
leave the opponent on a result card whose Rematch talked to a room that was
already gone. Only the first two frames are asserted -- the leaver's old socket
may still close afterwards and that late close is the session's business.
"""
import json
import random
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from chessshootout.server.app import create_app
from chessshootout.server.protocol import PROTOCOL_VERSION, Reason
from tests.helpers import FakeClock, auth_msg, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


@pytest.fixture
def app():
    return create_app(now_provider=FakeClock(), max_rooms=8)


@pytest.fixture
def client(app):
    return TestClient(app)


def _matchmake(client, *, uuid, side, minutes=5):
    r = client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": uuid, "nickname": uuid[:6],
        "time_minutes": minutes, "increment_seconds": 0, "side_preference": side,
    })
    assert r.status_code == 200
    return r.json()


def _cancel(client, seat, token=None):
    return client.request("DELETE", "/matchmake", json={
        "version": PROTOCOL_VERSION, "room_id": seat["room_id"],
        "session_token": token if token is not None else seat["session_token"],
    })


def _move(frm, to):
    return {"version": PROTOCOL_VERSION, "type": "move", "from": frm, "to": to}


def _next(ws):
    return json.loads(ws.receive_text())


def _settle(ws):
    """Drain everything already queued on a socket: the server answers a ping in
    order, so every frame before the pong has been read once the pong arrives."""
    ws.send_text(json.dumps({"version": PROTOCOL_VERSION, "type": "ping"}))
    seen = []
    while True:
        frame = _next(ws)
        if frame["type"] == "pong":
            return seen
        seen.append(frame)


def _play(ws_w, ws_b, plies):
    for index, (frm, to) in enumerate(plies):
        mover = ws_w if index % 2 == 0 else ws_b
        mover.send_text(json.dumps(_move(frm, to)))
        applied = [f for f in _settle(mover) if f["type"] == "move_applied"]
        assert applied and applied[-1]["ply"] == index + 1
    _settle(ws_w)
    _settle(ws_b)


def _seated(client):
    random.seed(0)
    white = _matchmake(client, uuid=ALICE, side="white")
    black = _matchmake(client, uuid=BOB, side="black")
    assert white["room_id"] == black["room_id"]
    return white, black


def _open(client, ws_stack, seat):
    ws = ws_stack.enter_context(client.websocket_connect(f"/ws/{seat['room_id']}"))
    ws.send_text(json.dumps(auth_msg(seat["session_token"])))
    return ws


@pytest.fixture
def ws_stack():
    with ExitStack() as stack:
        yield stack


def _both_on_the_board(client, ws_stack):
    white, black = _seated(client)
    ws_w = _open(client, ws_stack, white)
    ws_b = _open(client, ws_stack, black)
    assert _next(ws_w)["type"] == "game_start"
    assert _next(ws_b)["type"] == "game_start"
    _settle(ws_w)
    _settle(ws_b)
    return white, black, ws_w, ws_b


def _assert_told_left_after(ws, reason, winner):
    result = _next(ws)
    assert result["type"] == "result"
    assert (result["reason"], result["winner_color"]) == (reason, winner)
    left = _next(ws)
    assert left["type"] == "rematch_update"
    assert left["event"] == "opponent_left"


@pytest.mark.parametrize(
    "plies, reason, winner",
    [
        pytest.param((), Reason.ABORTED, None, id="nobody_moved_aborts"),
        pytest.param((("e2", "e4"),), Reason.ABORTED, None,
                     id="only_white_moved_aborts"),
        pytest.param((("e2", "e4"), ("e7", "e5")), Reason.ABANDONMENT, "black",
                     id="both_moved_is_abandoned"),
    ],
)
def test_a_new_search_tells_the_opponent_the_ending_then_that_the_player_left(
        client, app, ws_stack, plies, reason, winner):
    """Alice (white) searches again from a seated game. Bob hears how the old
    game ended -- a no-winner abort before both sides moved, a forfeit after --
    and then that Alice has left, so his card offers New Search instead of a
    Rematch into a room that is gone."""
    white, _, ws_w, ws_b = _both_on_the_board(client, ws_stack)
    _play(ws_w, ws_b, plies)
    fresh = _matchmake(client, uuid=ALICE, side="random", minutes=10)
    assert fresh["room_id"] != white["room_id"]
    _assert_told_left_after(ws_b, reason, winner)
    assert app.state.rooms.get(white["room_id"]) is None
    assert app.state.rooms.queue_depth == 1, "the searcher is waiting for a new game"


def test_a_cancel_that_races_the_pairing_tells_the_opponent_it_was_called_off(
        client, app, ws_stack):
    """Bob is already on the board when Alice's cancel from the wait card
    arrives. Her own token calls the pairing off: Bob hears the abort and then
    that she has left, and both of them are free to search again."""
    white, _, _, ws_b = _both_on_the_board(client, ws_stack)
    cancel = _cancel(client, white)
    assert cancel.json() == {"status": "ok"}
    _assert_told_left_after(ws_b, Reason.ABORTED, None)
    assert app.state.rooms.get(white["room_id"]) is None
    assert app.state.rooms.rooms_active == 0


def test_a_cancel_with_the_wrong_token_leaves_the_opponents_game_running(
        client, app, ws_stack):
    """The token check is what stops a room id alone from ending somebody's
    game: Bob's socket hears nothing about it -- the next frame after his own
    ping is the pong."""
    white, _, _, ws_b = _both_on_the_board(client, ws_stack)
    cancel = _cancel(client, white, token="not-alices-token")
    assert cancel.json() == {"status": "already_started"}
    assert _settle(ws_b) == []
    room = app.state.rooms.get(white["room_id"])
    assert room is not None and room.result is None
