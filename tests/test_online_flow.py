"""End-to-end test: two clients pair against an in-process server, play
a short game over real WebSockets, and verify state symmetry."""
import asyncio
import threading
import time

import pytest
import uvicorn

from frontend.online_client import OnlineClient
from server.app import create_app


@pytest.fixture
def server_port():
    """Find a free port (0 → kernel picks); spin up a uvicorn server in a thread."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(server_port):
    app = create_app(max_rooms=8)
    config = uvicorn.Config(app, host="127.0.0.1", port=server_port,
                             log_level="warning",
                             ws_ping_interval=20, ws_ping_timeout=30)
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    deadline = time.time() + 5
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    yield server_port
    srv.should_exit = True
    t.join(timeout=2)


def _drain(client, timeout=4.0):
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


def _wait_for(client, type_name, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = client.drain_inbound()
        for ev in events:
            if ev.type == type_name:
                return ev
        time.sleep(0.05)
    return None


def test_two_clients_pair_and_play_a_move(server):
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": "alice",
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": "bob",
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "black"})

    a_game = _wait_for(a, "game_start")
    b_game = _wait_for(b, "game_start")
    assert a_game is not None and b_game is not None
    assert a_game.payload["your_color"] == "white"
    assert b_game.payload["your_color"] == "black"

    a.send_move("e2", "e4")
    a_applied = _wait_for(a, "move_applied")
    b_applied = _wait_for(b, "move_applied")
    assert a_applied.payload["san"] == "e4"
    assert b_applied.payload["san"] == "e4"

    b.send_move("e7", "e5")
    a_applied2 = _wait_for(a, "move_applied")
    b_applied2 = _wait_for(b, "move_applied")
    assert a_applied2.payload["san"] == "e5"
    assert b_applied2.payload["san"] == "e5"

    a.disconnect()
    b.disconnect()


def test_resign_broadcasts_result_to_both_clients(server):
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": "alice2",
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": "bob2",
                      "time_minutes": 5, "increment_seconds": 0,
                      "side_preference": "black"})
    _wait_for(a, "game_start")
    _wait_for(b, "game_start")

    a.send_move("e2", "e4")
    _wait_for(a, "move_applied")
    _wait_for(b, "move_applied")
    a.send_resign()
    a_result = _wait_for(a, "result")
    b_result = _wait_for(b, "result")
    assert a_result.payload["reason"] == "resignation"
    assert a_result.payload["winner_color"] == "black"
    assert b_result.payload["reason"] == "resignation"
    a.disconnect()
    b.disconnect()
