"""M18b: Sweep step methods tested in isolation via fake clock.

The Sweep class wraps the per-tick lifecycle that used to live as a
free `_sweep` function. Each step does one thing — clock + first-move
abort, grace expiry, orphan/post-result drop, GC — so we can drive
each independently without going through the full asyncio loop.
"""
import pytest

from server.app import create_app
from server.protocol import Reason
from server.sweep import Sweep
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
def sweep(app):
    return app.state.sweep


@pytest.mark.asyncio
async def test_sweep_step_first_move_abort(sweep, app, clock):
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                          time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                          time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    clock.advance(61)
    await sweep.step_clock_and_first_move_abort()
    assert room.result == ("aborted", None)


@pytest.mark.asyncio
async def test_sweep_step_clock_flag_yields_timeout(sweep, app, clock):
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                          time_minutes=1, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                          time_minutes=1, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    room.first_move_at = clock()
    clock.advance(70)
    await sweep.step_clock_and_first_move_abort()
    assert room.result is not None
    assert room.result[0] == Reason.TIMEOUT


@pytest.mark.asyncio
async def test_sweep_step_grace_expired_yields_abandonment(sweep, app, clock):
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                          time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                          time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    room.started_at = clock()
    room.first_move_at = clock()
    rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABANDONMENT, "black")


@pytest.mark.asyncio
async def test_sweep_step_drop_orphans_pre_game(sweep, app, clock):
    # Both players are pre-game and neither has a live ws — the room is
    # garbage and should be dropped immediately, not after the rematch
    # keep-alive window.
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                          time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                          time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
    assert rooms.rooms_active == 1
    sweep.step_drop_orphans_and_post_result()
    assert rooms.rooms_active == 0


@pytest.mark.asyncio
async def test_sweep_step_drop_orphans_skips_after_first_move(sweep, app, clock):
    # After the first move, missing connections start the grace timer
    # rather than triggering an immediate drop.
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                          time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                          time_minutes=5, increment_seconds=0, side_preference="black")
    room = list(rooms._active.values())[0]
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

    def _trace_drop():
        calls.append("drop_orphans")

    monkeypatch.setattr(sweep, "step_clock_and_first_move_abort", _trace_clock)
    monkeypatch.setattr(sweep, "step_grace_expired", _trace_grace)
    monkeypatch.setattr(sweep, "step_drop_orphans_and_post_result", _trace_drop)
    monkeypatch.setattr(sweep.rooms, "gc_finished_rooms",
                          lambda: calls.append("gc"))
    await sweep.step_all()
    assert calls == ["clock_and_first_move", "grace", "drop_orphans", "gc"]
