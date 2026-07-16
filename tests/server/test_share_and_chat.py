"""Shared annotations + quick chat: the server relay, rate limiters, move-wipe,
and /resume payload, driven end-to-end through real websockets with a fake clock.

Every relaying handler mutates its store synchronously and only then awaits the
opponent send; there is exactly one await per handler (the relay). A finalize
racing in between the mutate and the send is therefore harmless -- the store is
already coherent and a stray relay to a just-finished room is dropped by the
receiving client. That single-await discipline is why the tests can assert store
state immediately after a send without worrying about interleaving.

Sender-received-nothing is proved with a ping sentinel: after a relay/noop, the
mover pings and the very next frame it reads back must be the pong, so a stray
echo would have surfaced ahead of it.
"""
import contextlib
import json
import random

from chessshootout.server.app import PROTOCOL_VERSION
from chessshootout.server.protocol import CHAT_PRESET_COUNT, MAX_SHARED_ARROWS, Reason
from tests.server.conftest import ALICE, BOB, auth_msg


def _matchmake(client, *, uuid, nickname, side, time=5, inc=0):
    return client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": uuid, "nickname": nickname,
        "time_minutes": time, "increment_seconds": inc, "side_preference": side,
    }).json()


@contextlib.contextmanager
def _paired_sockets(client):
    random.seed(0)
    a = _matchmake(client, uuid=ALICE, nickname="Alice", side="white")
    b = _matchmake(client, uuid=BOB, nickname="Bob", side="black")
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(auth_msg(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(auth_msg(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            yield ws_w, ws_b, a


def _send(ws, **fields):
    ws.send_text(json.dumps({"version": PROTOCOL_VERSION, **fields}))


def _recv(ws):
    return json.loads(ws.receive_text())


def _pong(ws, ply=0):
    _send(ws, type="ping", ply=ply)
    return _recv(ws)


def _room(client, a):
    return client.app.state.rooms.get(a["room_id"])


def test_annotations_state_relays_to_opponent_only_and_stores(client):
    with _paired_sockets(client) as (ws_w, ws_b, a):
        _send(ws_w, type="annotations_state", sharing=True,
              highlights=["e4", "d5"], arrows=[{"from": "e2", "to": "e4"}])
        relayed = _recv(ws_b)
        assert relayed["type"] == "annotations_state"
        assert relayed["sharing"] is True
        assert set(relayed["highlights"]) == {"e4", "d5"}
        assert relayed["arrows"] == [{"from": "e2", "to": "e4"}]

        assert _pong(ws_w)["type"] == "pong"

        room = _room(client, a)
        assert room.annotations_white.sharing is True
        assert room.annotations_white.highlights == {"e4", "d5"}
        assert room.annotations_white.arrows == [("e2", "e4")]
        assert room.annotations_black.highlights == set()
        assert room.annotations_black.arrows == []


def test_annotations_state_arrow_aliases_survive_relay(client):
    """The opponent must receive arrow endpoints under the wire aliases from/to,
    never the internal field names -- send() re-serializes by_alias."""
    with _paired_sockets(client) as (ws_w, ws_b, _a):
        _send(ws_w, type="annotations_state", sharing=True, highlights=[],
              arrows=[{"from": "g1", "to": "f3"}, {"from": "b1", "to": "c3"}])
        relayed = _recv(ws_b)
        assert relayed["arrows"] == [
            {"from": "g1", "to": "f3"}, {"from": "b1", "to": "c3"}]
        for arrow in relayed["arrows"]:
            assert "from_sq" not in arrow and "to_sq" not in arrow


def test_annotations_state_toggle_off_overwrites_store_and_relays(client):
    with _paired_sockets(client) as (ws_w, ws_b, a):
        room = _room(client, a)
        room.annotations_white.sharing = True
        room.annotations_white.highlights = {"e4"}
        room.annotations_white.arrows = [("e2", "e4")]

        _send(ws_w, type="annotations_state", sharing=False, highlights=[], arrows=[])
        relayed = _recv(ws_b)
        assert relayed["sharing"] is False
        assert relayed["highlights"] == []
        assert relayed["arrows"] == []

        assert room.annotations_white.sharing is False
        assert room.annotations_white.highlights == set()
        assert room.annotations_white.arrows == []


def test_annotation_delta_add_remove_highlight_and_arrow(client):
    with _paired_sockets(client) as (ws_w, ws_b, a):
        room = _room(client, a)

        _send(ws_w, type="annotation_delta", action="add", kind="highlight", square="e4")
        d = _recv(ws_b)
        assert (d["type"], d["action"], d["kind"], d["square"]) == (
            "annotation_delta", "add", "highlight", "e4")
        assert room.annotations_white.highlights == {"e4"}

        _send(ws_w, type="annotation_delta", action="remove", kind="highlight",
              square="e4")
        assert _recv(ws_b)["action"] == "remove"
        assert room.annotations_white.highlights == set()

        _send(ws_w, type="annotation_delta", action="add", kind="arrow",
              **{"from": "e2", "to": "e4"})
        d = _recv(ws_b)
        assert d["from"] == "e2" and d["to"] == "e4"
        assert room.annotations_white.arrows == [("e2", "e4")]

        _send(ws_w, type="annotation_delta", action="remove", kind="arrow",
              **{"from": "e2", "to": "e4"})
        assert _recv(ws_b)["kind"] == "arrow"
        assert room.annotations_white.arrows == []


def test_annotation_delta_kind_incoherent_is_silently_dropped(client):
    """A highlight delta with no square (and an arrow delta with from==to) is
    coherence-rejected in the handler: no relay to the opponent, no error frame
    to the sender."""
    with _paired_sockets(client) as (ws_w, ws_b, a):
        _send(ws_w, type="annotation_delta", action="add", kind="highlight")
        _send(ws_w, type="annotation_delta", action="add", kind="arrow",
              **{"from": "e2", "to": "e2"})

        assert _pong(ws_w)["type"] == "pong"
        assert _pong(ws_b)["type"] == "pong"
        room = _room(client, a)
        assert room.annotations_white.highlights == set()
        assert room.annotations_white.arrows == []


def test_annotation_delta_arrow_cap_refuses_add_without_relay(client):
    with _paired_sockets(client) as (ws_w, ws_b, a):
        room = _room(client, a)
        room.annotations_white.arrows = [
            (f"x{i}", f"y{i}") for i in range(MAX_SHARED_ARROWS)]

        _send(ws_w, type="annotation_delta", action="add", kind="arrow",
              **{"from": "e2", "to": "e4"})

        assert _pong(ws_w)["type"] == "pong"
        assert _pong(ws_b)["type"] == "pong"
        assert len(room.annotations_white.arrows) == MAX_SHARED_ARROWS
        assert ("e2", "e4") not in room.annotations_white.arrows


def test_annotation_rate_limit_trips_on_eleventh_frame_in_a_frozen_second(client, clock):
    """The eleventh annotations_state frame inside one frozen second is refused by
    the 10/s annotation limiter (not the 30/s WS limiter, since 11 < 30): the
    opponent sees exactly ten relays and the sender gets one rate_limited error
    tagged annotations_state. Advancing past the window lets it flow again."""
    with _paired_sockets(client) as (ws_w, ws_b, _a):
        for _ in range(11):
            _send(ws_w, type="annotations_state", sharing=True,
                  highlights=["e4"], arrows=[])
        for _ in range(10):
            assert _recv(ws_b)["type"] == "annotations_state"
        err = _recv(ws_w)
        assert err["type"] == "error"
        assert err["reason"] == Reason.RATE_LIMITED
        assert err["msg_type"] == "annotations_state"

        clock.advance(1.1)
        _send(ws_w, type="annotations_state", sharing=True, highlights=["d4"], arrows=[])
        assert _recv(ws_b)["type"] == "annotations_state"


def test_move_wipes_marks_keeps_sharing_and_emits_no_annotation_frame(client):
    with _paired_sockets(client) as (ws_w, ws_b, a):
        room = _room(client, a)
        for store in (room.annotations_white, room.annotations_black):
            store.sharing = True
            store.highlights = {"e4"}
            store.arrows = [("e2", "e4")]

        _send(ws_w, type="move", **{"from": "e2", "to": "e4"})
        assert _recv(ws_w)["type"] == "move_applied"
        assert _recv(ws_b)["type"] == "move_applied"

        for store in (room.annotations_white, room.annotations_black):
            assert store.sharing is True
            assert store.highlights == set()
            assert store.arrows == []

        assert _pong(ws_w, ply=1)["type"] == "pong"
        assert _pong(ws_b, ply=1)["type"] == "pong"


def test_takeback_does_not_wipe_shared_marks(client):
    with _paired_sockets(client) as (ws_w, ws_b, a):
        _send(ws_w, type="move", **{"from": "e2", "to": "e4"})
        assert _recv(ws_w)["type"] == "move_applied"
        assert _recv(ws_b)["type"] == "move_applied"

        room = _room(client, a)
        room.annotations_white.sharing = True
        room.annotations_white.highlights = {"c4"}
        room.annotations_white.arrows = [("b1", "c3")]

        _send(ws_w, type="takeback_request")
        assert _recv(ws_b)["type"] == "takeback_offered"
        _send(ws_b, type="takeback_response", accept=True)
        assert _recv(ws_w)["type"] == "takeback_applied"
        assert _recv(ws_b)["type"] == "takeback_applied"

        assert room.annotations_white.sharing is True
        assert room.annotations_white.highlights == {"c4"}
        assert room.annotations_white.arrows == [("b1", "c3")]


def test_after_result_share_and_chat_are_silent_noops(client):
    with _paired_sockets(client) as (ws_w, ws_b, _a):
        _send(ws_w, type="resign")
        assert _recv(ws_w)["type"] == "result"
        assert _recv(ws_b)["type"] == "result"

        _send(ws_w, type="annotations_state", sharing=True,
              highlights=["e4"], arrows=[])
        _send(ws_w, type="quick_chat", preset=0)

        assert _pong(ws_b)["type"] == "pong"
        assert _pong(ws_w)["type"] == "pong"


def test_resume_carries_both_annotation_sets(client):
    random.seed(0)
    a = _matchmake(client, uuid=ALICE, nickname="Alice", side="white")
    _matchmake(client, uuid=BOB, nickname="Bob", side="black")
    room = _room(client, a)
    room.annotations_white.sharing = True
    room.annotations_white.highlights = {"e4", "a1", "d5"}
    room.annotations_white.arrows = [("e2", "e4"), ("g1", "f3")]
    room.annotations_black.sharing = False
    room.annotations_black.highlights = {"h7"}
    room.annotations_black.arrows = [("b8", "c6")]

    r = client.post("/resume", json={
        "version": PROTOCOL_VERSION, "room_id": a["room_id"],
        "session_token": a["session_token"],
    })
    assert r.status_code == 200
    body = r.json()

    wa = body["white_annotations"]
    assert wa["sharing"] is True
    assert wa["highlights"] == ["a1", "d5", "e4"]
    assert wa["arrows"] == [{"from": "e2", "to": "e4"}, {"from": "g1", "to": "f3"}]

    ba = body["black_annotations"]
    assert ba["sharing"] is False
    assert ba["highlights"] == ["h7"]
    assert ba["arrows"] == [{"from": "b8", "to": "c6"}]


def test_quick_chat_relays_to_opponent_only(client):
    with _paired_sockets(client) as (ws_w, ws_b, _a):
        _send(ws_w, type="quick_chat", preset=2)
        got = _recv(ws_b)
        assert got["type"] == "quick_chat_received"
        assert got["preset"] == 2
        assert got["sender"] == "white"

        assert _pong(ws_w)["type"] == "pong"


def test_quick_chat_cooldown_then_recovers(client, clock):
    with _paired_sockets(client) as (ws_w, ws_b, _a):
        _send(ws_w, type="quick_chat", preset=1)
        assert _recv(ws_b)["type"] == "quick_chat_received"

        _send(ws_w, type="quick_chat", preset=1)
        err = _recv(ws_w)
        assert err["type"] == "error"
        assert err["reason"] == Reason.RATE_LIMITED
        assert err["msg_type"] == "quick_chat"
        assert _pong(ws_b)["type"] == "pong"

        clock.advance(3.05)
        _send(ws_w, type="quick_chat", preset=3)
        assert _recv(ws_b)["preset"] == 3


def test_quick_chat_out_of_range_preset_is_silently_invalid(client, clock):
    with _paired_sockets(client) as (ws_w, ws_b, _a):
        _send(ws_w, type="quick_chat", preset=CHAT_PRESET_COUNT)
        assert _pong(ws_w)["type"] == "pong"
        assert _pong(ws_b)["type"] == "pong"
