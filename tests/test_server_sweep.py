"""Sweep step methods exercised in isolation via a fake clock.

The Sweep class wraps the per-tick lifecycle: each step does one thing
(clock + first-move abort, grace expiry, orphan/post-result drop, beacon,
GC) so we drive each independently without the full asyncio loop.
"""
import pytest

from chessshootout.server.app import create_app
from chessshootout.server.protocol import Reason
from chessshootout.server.sweep import BEACON_INTERVAL_SECONDS, PREGAME_CONNECT_GRACE_SECONDS
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


async def _pair(rooms, time_minutes=5):
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=time_minutes, increment_seconds=0,
                        side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=time_minutes, increment_seconds=0,
                        side_preference="black")
    return list(rooms._active.values())[0]


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def sweep(app):
    return app.state.sweep


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time_minutes, set_first_move, advance, expected_result, expected_reason",
    [
        pytest.param(5, False, 61, ("aborted", None), None,
                     id="no_first_move_aborts"),
        pytest.param(1, True, 70, None, Reason.TIMEOUT,
                     id="flagged_clock_times_out"),
    ],
)
async def test_sweep_step_clock_and_first_move(sweep, app, clock, time_minutes,
                                               set_first_move, advance,
                                               expected_result, expected_reason):
    """Same step, two distinct outcomes: pre-first-move abort vs clock timeout.

    Expected differs in kind per case (the abort branch yields a fixed
    ("aborted", None) tuple; the timeout branch yields a TIMEOUT reason on the
    flagged side), so each case carries its own expected — never flattened.
    """
    room = await _pair(app.state.rooms, time_minutes=time_minutes)
    room.started_at = clock()
    if set_first_move:
        room.first_move_at = clock()
    clock.advance(advance)
    await sweep.step_clock_and_first_move_abort()
    if expected_result is not None:
        assert room.result == expected_result
    else:
        assert room.result is not None
        assert room.result[0] == expected_reason


@pytest.mark.asyncio
async def test_sweep_step_grace_expired_yields_abandonment(sweep, app, clock):
    room = await _pair(app.state.rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABANDONMENT, "black")


@pytest.mark.asyncio
async def test_sweep_step_drop_orphans_pre_game(sweep, app, clock):
    """A paired pre-game room with no live ws survives within the connect
    grace (so client ws handshakes can still land) and is dropped past it."""
    rooms = app.state.rooms
    await _pair(rooms)
    assert rooms.rooms_active == 1
    sweep.step_drop_orphans_and_post_result()
    assert rooms.rooms_active == 1
    clock.advance(PREGAME_CONNECT_GRACE_SECONDS)
    sweep.step_drop_orphans_and_post_result()
    assert rooms.rooms_active == 0


@pytest.mark.asyncio
async def test_sweep_step_drop_orphans_skips_after_first_move(sweep, app, clock):
    """After the first move a missing connection starts the grace timer
    instead of dropping the room immediately."""
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.first_move_at = clock()
    sweep.step_drop_orphans_and_post_result()
    assert rooms.rooms_active == 1


@pytest.mark.asyncio
async def test_sweep_step_all_runs_in_documented_order(sweep, app, clock, monkeypatch):
    calls = []

    async def _trace_clock():
        calls.append("clock_and_first_move")

    async def _trace_grace():
        calls.append("grace")

    async def _trace_beacon():
        calls.append("state_sync_beacon")

    def _trace_drop():
        calls.append("drop_orphans")

    monkeypatch.setattr(sweep, "step_clock_and_first_move_abort", _trace_clock)
    monkeypatch.setattr(sweep, "step_grace_expired", _trace_grace)
    monkeypatch.setattr(sweep, "step_state_sync_beacon", _trace_beacon)
    monkeypatch.setattr(sweep, "step_drop_orphans_and_post_result", _trace_drop)
    monkeypatch.setattr(sweep.rooms, "gc_finished_rooms",
                        lambda: calls.append("gc"))
    await sweep.step_all()
    assert calls == ["clock_and_first_move", "grace", "state_sync_beacon",
                     "drop_orphans", "gc"]


@pytest.mark.asyncio
async def test_beacon_emits_state_sync_for_active_started_room(sweep, app, clock, monkeypatch):
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    clock.advance(10)
    sent = []

    async def _capture(connections, r, message):
        sent.append((r.room_id, message))

    monkeypatch.setattr("chessshootout.server.sweep.broadcast", _capture)
    await sweep.step_state_sync_beacon()
    assert len(sent) == 1
    room_id, message = sent[0]
    assert room_id == room.room_id
    assert message.type == "state_sync"
    assert message.ply == len(room.backend.move_history)


@pytest.mark.asyncio
async def test_beacon_throttled_to_interval(sweep, app, clock, monkeypatch):
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.first_move_at = clock()
    clock.advance(10)
    sent = []

    async def _capture(connections, r, message):
        sent.append(message)

    monkeypatch.setattr("chessshootout.server.sweep.broadcast", _capture)
    await sweep.step_state_sync_beacon()
    await sweep.step_state_sync_beacon()
    assert len(sent) == 1
    clock.advance(BEACON_INTERVAL_SECONDS + 0.01)
    await sweep.step_state_sync_beacon()
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_beacon_skips_pre_first_move_and_finished_rooms(sweep, app, clock, monkeypatch):
    rooms = app.state.rooms
    room = await _pair(rooms)
    clock.advance(10)
    sent = []

    async def _capture(connections, r, message):
        sent.append(message)

    monkeypatch.setattr("chessshootout.server.sweep.broadcast", _capture)
    await sweep.step_state_sync_beacon()
    assert sent == []
    room.first_move_at = clock()
    rooms.finalize_result(room.room_id, Reason.RESIGNATION, winner_color="white")
    await sweep.step_state_sync_beacon()
    assert sent == []
