"""End-to-end test: two clients pair against an in-process server, play
a short game over real WebSockets, and verify state symmetry.

The `server` fixture lives in tests/conftest.py (shared with
test_server_transport.py). Poll timeouts here are deliberately generous:
OnlineClient._matchmake_with_retries can spend ~4.5s retrying before it
gives up, so a tight poll would time out before a transient first attempt
recovers."""
import time

import httpx
import pytest

from chessshootout.online.client import ClientReason, OnlineClient
from chessshootout.online.transport import ServerTransport
from chessshootout.server.protocol import PROTOCOL_VERSION
from tests.helpers import fake_uuid4
from tests.online.online_helpers import wait_for


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)
ALICE2 = fake_uuid4(11)
BOB2 = fake_uuid4(12)
ALICE3 = fake_uuid4(13)
BOB3 = fake_uuid4(14)


def _drain(client, timeout=15.0):
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        events = client.drain_inbound()
        for ev in events:
            seen.append(ev)
            if ev.type == "game_start":
                return seen
        time.sleep(0.05)
    return seen


def test_two_clients_pair_and_play_a_move(server):
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": ALICE,
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": BOB,
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "black"})

    a_game = wait_for(a, "game_start")
    b_game = wait_for(b, "game_start")
    assert a_game is not None and b_game is not None
    assert a_game.payload["your_color"] == "white"
    assert b_game.payload["your_color"] == "black"

    a.send_move("e2", "e4")
    a_applied = wait_for(a, "move_applied")
    b_applied = wait_for(b, "move_applied")
    assert a_applied.payload["san"] == "e4"
    assert b_applied.payload["san"] == "e4"

    b.send_move("e7", "e5")
    a_applied2 = wait_for(a, "move_applied")
    b_applied2 = wait_for(b, "move_applied")
    assert a_applied2.payload["san"] == "e5"
    assert b_applied2.payload["san"] == "e5"

    a.disconnect()
    b.disconnect()


def test_resign_broadcasts_result_to_both_clients(server):
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": ALICE2,
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": BOB2,
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "black"})
    wait_for(a, "game_start")
    wait_for(b, "game_start")

    a.send_move("e2", "e4")
    wait_for(a, "move_applied")
    wait_for(b, "move_applied")
    # Black replies first: a resignation before both sides moved is an abort.
    b.send_move("e7", "e5")
    assert wait_for(a, "move_applied").payload["san"] == "e5"
    assert wait_for(b, "move_applied").payload["san"] == "e5"
    a.send_resign()
    a_result = wait_for(a, "result")
    b_result = wait_for(b, "result")
    assert a_result.payload["reason"] == "resignation"
    assert a_result.payload["winner_color"] == "black"
    assert b_result.payload["reason"] == "resignation"
    a.disconnect()
    b.disconnect()


def test_online_rematch_swaps_colors(server):
    """On a mutual rematch the server swaps colours: White becomes Black and vice
    versa, and each client's fresh game_start carries the flipped your_color."""
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": ALICE3,
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": BOB3,
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "black"})
    assert wait_for(a, "game_start").payload["your_color"] == "white"
    assert wait_for(b, "game_start").payload["your_color"] == "black"

    a.send_resign()
    wait_for(a, "result")
    wait_for(b, "result")

    a.send_rematch_request()
    b.send_rematch_request()
    a_game2 = wait_for(a, "game_start")
    b_game2 = wait_for(b, "game_start")
    assert a_game2 is not None and b_game2 is not None
    assert a_game2.payload["your_color"] == "black"
    assert b_game2.payload["your_color"] == "white"

    a.disconnect()
    b.disconnect()


@pytest.mark.parametrize("plies", [0, 1], ids=["nobody_moved", "only_white_moved"])
def test_a_resign_before_both_sides_moved_comes_back_aborted_to_both(server, plies):
    """The pregame rule over real sockets: a resignation before both sides have
    moved is sent like any other, and the server answers both players with a
    no-winner abort rather than a win -- so neither card scores it."""
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": fake_uuid4(21 + plies * 2),
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": fake_uuid4(22 + plies * 2),
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "black"})
    assert wait_for(a, "game_start").payload["your_color"] == "white"
    assert wait_for(b, "game_start").payload["your_color"] == "black"
    if plies:
        a.send_move("e2", "e4")
        assert wait_for(b, "move_applied").payload["san"] == "e4"
    a.send_resign()
    for client in (a, b):
        result = wait_for(client, "result")
        assert result is not None
        assert result.payload["reason"] == "aborted"
        assert result.payload["winner_color"] is None
    a.disconnect()
    b.disconnect()


def test_an_opponent_whose_pairing_is_cancelled_before_it_connects_hears_the_search_ended(
        server, monkeypatch):
    """REGRESSION, over real sockets: Alice's cancel lands after Bob's
    /matchmake paired them but before his game socket authenticated. The
    server calls the pairing off and lets the room go, so Bob's socket is
    refused -- and his client used to end the session without a word, leaving
    the wait card counting. It now reports a lost search."""
    base = f"http://127.0.0.1:{server}"
    seat = httpx.post(f"{base}/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": ALICE3, "nickname": "Alice",
        "time_minutes": 7, "increment_seconds": 0, "side_preference": "white"}).json()
    real_connect = ServerTransport.ws_connect
    cancels = []

    async def cancel_first(self, room_id, session_token):
        async with httpx.AsyncClient() as http:
            answer = await http.request("DELETE", f"{base}/matchmake", json={
                "version": PROTOCOL_VERSION, "room_id": seat["room_id"],
                "session_token": seat["session_token"]})
        cancels.append(answer.json())
        return await real_connect(self, room_id, session_token)

    monkeypatch.setattr(ServerTransport, "ws_connect", cancel_first)
    bob = OnlineClient()
    bob.connect(f"localhost:{server}", {"nickname": "Bob", "client_uuid": BOB3,
                                        "time_minutes": 7, "increment_seconds": 0,
                                        "side_preference": "black"})
    try:
        error = wait_for(bob, "error")
    finally:
        bob.disconnect()

    assert cancels == [{"status": "ok"}]
    assert error is not None
    assert error.payload == {"reason": ClientReason.SEARCH_LOST}
