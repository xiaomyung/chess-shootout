"""Idle-window choreography through the real dispatch choke point.

Every allowlisted message runs _touch_idle_window AFTER its handler, so the
handler's arm/disarm (a landed ply) and finalize (a resign) are what the touch
re-validates against. Two guards carry the whole policy: only the RESIGNATION
window ever resets on activity, and only the side on the hook can reset it.
"""
import json

import pytest

from chessshootout.backend.utils import square_from_coord
from chessshootout.server.broadcasts import IDLE_WINDOW_PUSH_MIN_INTERVAL_SECONDS
from chessshootout.server.handlers import HANDLERS, IDLE_ACTIVITY_TYPES, dispatch
from chessshootout.server.protocol import (
    FIRST_MOVE_ABORT_SECONDS, IDLE_RESIGN_SECONDS, PROTOCOL_VERSION, Reason,
)
from tests.server.conftest import ALICE, BOB
from tests.server.test_server_broadcasts import RecordingWS


async def _wired_room(app):
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    room = await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                               time_minutes=5, increment_seconds=0,
                               side_preference="black")
    ws_w, ws_b = RecordingWS(), RecordingWS()
    app.state.connections.add(room.room_id, room.white.client_uuid, ws_w)
    app.state.connections.add(room.room_id, room.black.client_uuid, ws_b)
    rooms.mark_connected(room.room_id, "white")
    rooms.mark_connected(room.room_id, "black")
    return room, ws_w, ws_b


def _msg(**fields):
    return json.dumps({"version": PROTOCOL_VERSION, **fields})


async def _move(app, room, ws, color, frm, to):
    return await dispatch(app, ws, room, color,
                          _msg(type="move", **{"from": frm, "to": to}))


async def _room_at_ply_two(app):
    room, ws_w, ws_b = await _wired_room(app)
    await _move(app, room, ws_w, "white", "e2", "e4")
    await _move(app, room, ws_b, "black", "e7", "e5")
    assert room.plies_ever == 2
    return room, ws_w, ws_b


async def test_ply_one_rearms_the_abort_window_for_the_replier(app, clock):
    room, ws_w, ws_b = await _wired_room(app)
    clock.advance(10)

    await _move(app, room, ws_w, "white", "e2", "e4")

    assert room.plies_ever == 1
    assert room.idle_since == clock(), "restamped at the ply, not left at pairing time"
    assert room.idle_window() == (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS)
    for ws in (ws_w, ws_b):
        pushes = ws.of_type("idle_window")
        assert len(pushes) == 1, "one forced push per landed ply, to both sockets"
        assert pushes[0]["outcome"] == "aborted"
        assert pushes[0]["color"] == "black"
        assert pushes[0]["seconds_remaining"] == pytest.approx(FIRST_MOVE_ABORT_SECONDS)
        types = [m["type"] for m in ws.sent]
        assert types.index("move_applied") < types.index("idle_window"), \
            "the client must clear on move_applied BEFORE it arms on the push"


async def test_ply_two_arms_the_resign_window_and_pushes_it(app, clock):
    room, ws_w, ws_b = await _wired_room(app)
    await _move(app, room, ws_w, "white", "e2", "e4")
    clock.advance(3)

    await _move(app, room, ws_b, "black", "e7", "e5")

    assert room.idle_since == clock()
    for ws in (ws_w, ws_b):
        push = ws.of_type("idle_window")[-1]
        assert push["outcome"] == "resignation"
        assert push["color"] == "white"
        assert push["seconds_remaining"] == pytest.approx(IDLE_RESIGN_SECONDS)


async def test_ply_three_disarms_the_window_and_pushes_nothing(app, clock):
    room, ws_w, ws_b = await _room_at_ply_two(app)
    before = len(ws_b.of_type("idle_window"))

    await _move(app, room, ws_w, "white", "g1", "f3")

    assert room.plies_ever == 3
    assert room.idle_since is None
    assert room.idle_pushed_at is None
    assert len(ws_b.of_type("idle_window")) == before
    assert len(ws_w.of_type("idle_window")) == before


async def test_only_the_side_to_move_refreshes_the_idle_window(app, clock):
    room, ws_w, ws_b = await _room_at_ply_two(app)
    armed_at = room.idle_since
    clock.advance(5)

    await dispatch(app, ws_b, room, "black", _msg(type="quick_chat", preset=0))
    assert room.idle_since == armed_at
    await dispatch(app, ws_b, room, "black",
                   _msg(type="annotation_delta", action="add", kind="highlight",
                        square="e4"))
    assert room.idle_since == armed_at, \
        "the waiting side cannot keep an AFK opponent alive by drawing marks"

    await dispatch(app, ws_w, room, "white", _msg(type="quick_chat", preset=0))
    assert room.idle_since == clock(), "the idler's own activity is what refreshes"


@pytest.mark.parametrize("plies", [0, 1])
async def test_the_abort_windows_never_refresh_on_activity(app, clock, plies):
    """The room-slot DoS guard: during the abort windows the sweep does not tick
    the clock (first_move_at gates it at ply 0, and the idler's clock only bounds
    the game once moves land), so if activity reset them a client spamming
    annotation deltas could hold a room slot — which counts against MAX_ROOMS —
    forever. Only the ply-2 resign window, where the idler's own clock is already
    running, resets on activity."""
    room, ws_w, ws_b = await _wired_room(app)
    if plies == 1:
        await _move(app, room, ws_w, "white", "e2", "e4")
    armed_at = room.idle_since
    on_hook = "white" if plies == 0 else "black"
    ws = ws_w if on_hook == "white" else ws_b
    clock.advance(5)

    await dispatch(app, ws, room, on_hook, _msg(type="quick_chat", preset=0))
    await dispatch(app, ws, room, on_hook,
                   _msg(type="annotation_delta", action="add", kind="highlight",
                        square="d4"))

    assert room.idle_since == armed_at


async def test_ping_never_refreshes_the_idle_window(app, clock):
    room, ws_w, ws_b = await _room_at_ply_two(app)
    armed_at = room.idle_since
    clock.advance(5)

    await dispatch(app, ws_w, room, "white", _msg(type="ping", ply=2))

    assert "ping" not in IDLE_ACTIVITY_TYPES, \
        "the heartbeat is automatic — it proves the process lives, not the player"
    assert room.idle_since == armed_at


async def test_give_time_from_the_waiting_side_does_not_postpone_the_forfeit(app, clock):
    room, ws_w, ws_b = await _room_at_ply_two(app)
    armed_at = room.idle_since
    clock.advance(5)
    room.backend.tick_clock()

    _, verdict = await dispatch(app, ws_b, room, "black",
                                _msg(type="give_time", hold_ms=0))

    assert verdict == "granted"
    assert room.idle_since == armed_at, \
        "gifted clock time must not buy the idler more idle-window time"


async def test_idle_window_pushes_are_throttled(app, clock):
    room, ws_w, ws_b = await _room_at_ply_two(app)
    clock.advance(IDLE_WINDOW_PUSH_MIN_INTERVAL_SECONDS)
    base = len(ws_b.of_type("idle_window"))
    delta = dict(type="annotation_delta", action="add", kind="highlight")

    await dispatch(app, ws_w, room, "white", _msg(square="a3", **delta))
    assert len(ws_b.of_type("idle_window")) == base + 1

    clock.advance(0.5)
    await dispatch(app, ws_w, room, "white", _msg(square="b3", **delta))
    assert len(ws_b.of_type("idle_window")) == base + 1, \
        "a second refresh inside the interval broadcasts nothing"
    assert room.idle_since == clock(), \
        "but the server-side window still refreshed — the throttle is wire-only"

    clock.advance(IDLE_WINDOW_PUSH_MIN_INTERVAL_SECONDS)
    await dispatch(app, ws_w, room, "white", _msg(square="c3", **delta))
    assert len(ws_b.of_type("idle_window")) == base + 2


async def test_a_finalized_room_never_refreshes_or_pushes(app, clock):
    room, ws_w, ws_b = await _room_at_ply_two(app)
    await dispatch(app, ws_w, room, "white", _msg(type="resign"))
    assert room.result is not None
    assert room.idle_since is None
    base = len(ws_b.of_type("idle_window"))
    clock.advance(5)

    await dispatch(app, ws_w, room, "white", _msg(type="quick_chat", preset=0))

    assert room.idle_since is None
    assert len(ws_b.of_type("idle_window")) == base
    assert len(ws_w.of_type("idle_window")) == base


def test_idle_activity_types_is_a_subset_of_the_dispatch_table():
    """IDLE_ACTIVITY_TYPES is a free-standing string set with no structural tie
    to HANDLERS: a typo'd entry, or a handler rename that misses the set, would
    silently stop that message type from resetting the resign window — no
    error anywhere, the idler just forfeits while visibly active. Pinning the
    subset relation makes any drift loud."""
    assert IDLE_ACTIVITY_TYPES <= set(HANDLERS)


async def test_an_accepted_takeback_at_ply_two_restamps_and_pushes_the_new_hook(
    app, clock,
):
    """backend.undo() flips color_to_move while plies_ever stays at 2, so the
    takeback requester walks onto the resign hook mid-burn — and the client
    cleared its badge on takeback_applied, so without a fresh push they could
    be auto-resigned with no countdown ever shown. The accept branch restamps
    idle_since and force-pushes the window against the new side to move, after
    the takeback_applied broadcast so the client clears before it re-arms."""
    room, ws_w, ws_b = await _room_at_ply_two(app)
    clock.advance(50)
    await dispatch(app, ws_b, room, "black", _msg(type="takeback_request"))
    await dispatch(app, ws_w, room, "white",
                   _msg(type="takeback_response", accept=True))

    assert room.color_to_move() == "black"
    assert room.idle_since == clock()
    for ws in (ws_w, ws_b):
        push = ws.of_type("idle_window")[-1]
        assert push["outcome"] == "resignation"
        assert push["color"] == "black"
        assert push["seconds_remaining"] == pytest.approx(IDLE_RESIGN_SECONDS)
        types = [m["type"] for m in ws.sent]
        last_push_at = max(i for i, t in enumerate(types) if t == "idle_window")
        assert types.index("takeback_applied") < last_push_at


async def test_an_accepted_takeback_at_ply_one_restamps_the_abort_window(app, clock):
    """The restamp is unconditional whenever a window is armed, so the ply-1
    abort window gets the same treatment: the undo hands the board back to
    white while plies_ever stays 1, and the full window is re-anchored and
    force-pushed with the new color."""
    room, ws_w, ws_b = await _wired_room(app)
    await _move(app, room, ws_w, "white", "e2", "e4")
    clock.advance(30)
    await dispatch(app, ws_w, room, "white", _msg(type="takeback_request"))
    await dispatch(app, ws_b, room, "black",
                   _msg(type="takeback_response", accept=True))

    assert room.color_to_move() == "white"
    assert room.idle_since == clock()
    for ws in (ws_w, ws_b):
        push = ws.of_type("idle_window")[-1]
        assert push["outcome"] == "aborted"
        assert push["color"] == "white"
        assert push["seconds_remaining"] == pytest.approx(FIRST_MOVE_ABORT_SECONDS)


async def test_a_declined_takeback_never_restamps_from_the_accept_branch(app, clock):
    """Decline leaves any restamp to the dispatch touch hook alone, and that
    hook only fires for the RESIGNATION window when the sender is the side on
    the hook. On the ply-1 abort window the decliner IS the side to move, yet
    nothing restamps and nothing is pushed — proof the accept branch's restamp
    did not leak into the decline path (abort windows never reset on
    activity)."""
    room, ws_w, ws_b = await _wired_room(app)
    await _move(app, room, ws_w, "white", "e2", "e4")
    armed_at = room.idle_since
    pushes_before = len(ws_b.of_type("idle_window"))
    clock.advance(5)
    await dispatch(app, ws_w, room, "white", _msg(type="takeback_request"))
    await dispatch(app, ws_b, room, "black",
                   _msg(type="takeback_response", accept=False))

    assert room.idle_since == armed_at
    assert len(ws_b.of_type("idle_window")) == pushes_before


async def test_a_ply_two_decline_from_the_hook_side_refreshes_via_the_touch_hook(
    app, clock,
):
    """The counterpart: at ply 2 the decliner is the side on the resign hook,
    so the decline frame proves presence and the generic activity hook
    restamps — the ordinary refresh path, not the accept branch's."""
    room, ws_w, ws_b = await _room_at_ply_two(app)
    clock.advance(5)
    await dispatch(app, ws_b, room, "black", _msg(type="takeback_request"))
    await dispatch(app, ws_w, room, "white",
                   _msg(type="takeback_response", accept=False))

    assert room.color_to_move() == "white"
    assert room.idle_since == clock()


async def test_a_rejected_move_by_the_side_to_move_still_refreshes(app, clock):
    """A locked-move retry (the shape a failed skill check leaves behind) is a
    present human fighting the UI, not an idler — the reset keys off the frame
    arriving from the side on the hook, never off the handler's verdict."""
    room, ws_w, ws_b = await _room_at_ply_two(app)
    room.skillcheck_locks.add((square_from_coord("g1"), square_from_coord("f3")))
    clock.advance(5)

    _, verdict = await _move(app, room, ws_w, "white", "g1", "f3")

    assert verdict == "locked"
    assert room.idle_since == clock()
    assert ws_w.of_type("idle_window")[-1]["seconds_remaining"] == pytest.approx(
        IDLE_RESIGN_SECONDS)
