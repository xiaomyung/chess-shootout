"""End-to-end tests for shared annotations + quick chat over two real clients.

Two OnlineClient instances pair against an in-process uvicorn server (the
`server` fixture in tests/conftest.py) and exchange annotation/chat frames over
real WebSockets. These cover the server relay behaviour that the unit-level
test_share_chat_client.py cannot reach: opponent-only relay, aliased arrow keys
on the wire, the server-side mark wipe on a move (no frame emitted), the
annotations carried by /resume, the 3s chat cooldown, and the post-result noop.

Structure/timeouts mirror test_online_flow.py (its `_wait_for` is reused by
import). Exactly one real-clock sleep lives in this file: the chat cooldown is
enforced against the server's real monotonic clock (the fixture builds the app
with the default now_provider and exposes no override), so the cooldown test
sleeps ~3.1s to cross the 3.0s window."""
import time

from chessshootout.online.client import OnlineClient, fetch_resume
from tests.helpers import fake_uuid4
from tests.online.test_online_flow import _wait_for


ANNO_WHITE = fake_uuid4(21)
ANNO_BLACK = fake_uuid4(22)
CHAT_WHITE = fake_uuid4(23)
CHAT_BLACK = fake_uuid4(24)
DONE_WHITE = fake_uuid4(25)
DONE_BLACK = fake_uuid4(26)


def _pair(server, white_uuid, black_uuid):
    """Matchmake two real clients (white + black) against the in-process server
    and return (addr, white_client, black_client) once both see game_start."""
    addr = f"localhost:{server}"
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": white_uuid,
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": black_uuid,
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "black"})
    assert _wait_for(a, "game_start").payload["your_color"] == "white"
    assert _wait_for(b, "game_start").payload["your_color"] == "black"
    return addr, a, b


def _collect_for(client, timeout):
    """Drain a client's inbound queue for a fixed window, returning every event
    seen. Used for absence assertions where nothing should arrive (unlike
    _wait_for, which discards the events it steps past)."""
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        seen.extend(client.drain_inbound())
        time.sleep(0.05)
    seen.extend(client.drain_inbound())
    return seen


def test_shared_annotations_relay_state_sync_and_move_wipe(server):
    """White shares an annotation set + a delta (opponent-only relay, arrows keyed
    by their aliases); a move silently wipes the marks server-side with no frame
    relayed; /resume then carries white's current (empty-marks, still-sharing)
    store; and turning sharing off relays as an empty state."""
    addr, a, b = _pair(server, ANNO_WHITE, ANNO_BLACK)

    a.send_annotations_state(True, ["e4"], [("g1", "f3")])
    state_ev = _wait_for(b, "annotations_state")
    assert state_ev is not None
    assert state_ev.payload["sharing"] is True
    assert state_ev.payload["highlights"] == ["e4"]
    assert state_ev.payload["arrows"] == [{"from": "g1", "to": "f3"}]

    a.send_annotation_delta("add", "highlight", square="d4")
    delta_ev = _wait_for(b, "annotation_delta")
    assert delta_ev is not None
    assert delta_ev.payload["action"] == "add"
    assert delta_ev.payload["kind"] == "highlight"
    assert delta_ev.payload["square"] == "d4"

    a.send_move("e2", "e4")
    assert _wait_for(a, "move_applied") is not None
    b_after_move = _collect_for(b, 1.0)
    types = [ev.type for ev in b_after_move]
    assert "move_applied" in types
    assert "annotations_state" not in types
    assert "annotation_delta" not in types

    resumed = fetch_resume(addr, b.room_id, b._session_token)
    assert resumed is not None
    white_store = resumed["white_annotations"]
    assert white_store["sharing"] is True
    assert white_store["highlights"] == []
    assert white_store["arrows"] == []

    a.send_annotations_state(False, [], [])
    stop_ev = _wait_for(b, "annotations_state")
    assert stop_ev is not None
    assert stop_ev.payload["sharing"] is False
    assert stop_ev.payload["highlights"] == []
    assert stop_ev.payload["arrows"] == []

    a.disconnect()
    b.disconnect()


def test_quick_chat_relay_and_cooldown(server):
    """A quick-chat preset relays opponent-only as quick_chat_received{preset,
    sender}; a second chat inside the 3s cooldown is rejected with a
    rate_limited error to the sender and nothing to the opponent; after the
    window passes a fresh preset flows through again."""
    _addr, a, b = _pair(server, CHAT_WHITE, CHAT_BLACK)

    a.send_quick_chat(1)
    chat_ev = _wait_for(b, "quick_chat_received")
    assert chat_ev is not None
    assert chat_ev.payload["preset"] == 1
    assert chat_ev.payload["sender"] == "white"

    a.send_quick_chat(2)
    err = _wait_for(a, "error")
    assert err is not None
    assert err.payload["reason"] == "rate_limited"
    assert err.payload.get("msg_type") == "quick_chat"
    throttled = _collect_for(b, 1.0)
    assert not any(ev.type == "quick_chat_received" for ev in throttled)

    time.sleep(3.1)
    a.send_quick_chat(3)
    chat_ev3 = _wait_for(b, "quick_chat_received")
    assert chat_ev3 is not None
    assert chat_ev3.payload["preset"] == 3
    assert chat_ev3.payload["sender"] == "white"

    a.disconnect()
    b.disconnect()


def test_post_result_chat_and_annotations_are_noops(server):
    """Once the game is over, quick-chat and annotation frames are server-side
    noops: neither is relayed to the opponent."""
    _addr, a, b = _pair(server, DONE_WHITE, DONE_BLACK)

    a.send_resign()
    a_result = _wait_for(a, "result")
    b_result = _wait_for(b, "result")
    assert a_result is not None and a_result.payload["reason"] == "resignation"
    assert b_result is not None and b_result.payload["reason"] == "resignation"

    a.send_quick_chat(0)
    a.send_annotations_state(True, ["e4"], [("g1", "f3")])
    leftover = _collect_for(b, 1.0)
    stray = [ev.type for ev in leftover
             if ev.type in ("quick_chat_received", "annotations_state", "annotation_delta")]
    assert stray == []

    a.disconnect()
    b.disconnect()
