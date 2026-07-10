"""Sweep step methods exercised in isolation via a fake clock.

The Sweep class wraps the per-tick lifecycle: each step does one thing
(clock + first-move abort, grace expiry, orphan/post-result drop, beacon,
GC) so we drive each independently without the full asyncio loop.
"""
import pytest

from chessshootout.server.app import create_app
from chessshootout.server.protocol import GRACE_SECONDS, HEARTBEAT_TIMEOUT_SECONDS, Reason
from chessshootout.server.sweep import PREGAME_CONNECT_GRACE_SECONDS
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
async def test_sweep_step_grace_expired_without_desync_awards_opponent(sweep, app, clock):
    room = await _pair(app.state.rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    room.white.connected = True
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABANDONMENT, "black")


@pytest.mark.asyncio
async def test_sweep_step_grace_expired_after_desync_aborts(sweep, app, clock):
    room = await _pair(app.state.rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    room.white.connected = True
    room.white.desync_active = True
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABORTED_DISCONNECT, None)


CARL = fake_uuid4(3)
DAVE = fake_uuid4(4)


@pytest.mark.asyncio
async def test_sweep_step_grace_expired_revalidates_a_reconnect_that_lands_mid_pass(
    sweep, app, clock,
):
    """grace_expired_rooms() snapshots eagerly, then the loop awaits a broadcast
    per room -- if a reconnect for a LATER room in the batch lands during an
    earlier room's await, that later room must not be steamrolled by the stale
    snapshot read. A fake socket on room_a's present side reconnects room_b's
    gone player as a side effect of being sent room_a's own result broadcast,
    which is exactly the kind of state change a truly concurrent task could
    cause mid-await."""
    rooms = app.state.rooms
    connections = app.state.connections

    room_a = await _pair(rooms)
    room_a.started_at = clock()
    room_a.first_move_at = clock()
    room_a.white.connected = True
    room_a.black.connected = True

    await rooms.enqueue(client_uuid=CARL, nickname="C", session_token="tc",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    room_b = await rooms.enqueue(client_uuid=DAVE, nickname="D", session_token="td",
                                 time_minutes=5, increment_seconds=0, side_preference="black")
    room_b.started_at = clock()
    room_b.first_move_at = clock()
    room_b.white.connected = True
    room_b.black.connected = True

    rooms.mark_disconnected(room_a.room_id, "white")
    rooms.mark_disconnected(room_b.room_id, "white")
    clock.advance(GRACE_SECONDS + 1)

    class ReconnectingWS:
        def __init__(self):
            self.sent = []

        async def send_json(self, payload):
            self.sent.append(payload)
            rooms.mark_connected(room_b.room_id, "white")

    connections.add(room_a.room_id, room_a.black.client_uuid, ReconnectingWS())

    await sweep.step_grace_expired()

    assert room_a.result == (Reason.ABANDONMENT, "black")
    assert room_b.result is None, "the reconnect that landed mid-pass must be honored"
    assert room_b.white.connected is True


@pytest.mark.asyncio
async def test_sweep_step_drop_orphans_pre_game(sweep, app, clock):
    """A paired pre-game room with no live ws survives within the connect
    grace (so client ws handshakes can still land) and is dropped past it."""
    rooms = app.state.rooms
    await _pair(rooms)
    assert rooms.rooms_active == 1
    sweep.step_drop_orphans_pre_game()
    assert rooms.rooms_active == 1
    clock.advance(PREGAME_CONNECT_GRACE_SECONDS)
    sweep.step_drop_orphans_pre_game()
    assert rooms.rooms_active == 0


@pytest.mark.asyncio
async def test_sweep_step_drop_orphans_skips_after_first_move(sweep, app, clock):
    """After the first move a missing connection starts the grace timer
    instead of dropping the room immediately."""
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.first_move_at = clock()
    sweep.step_drop_orphans_pre_game()
    assert rooms.rooms_active == 1


@pytest.mark.asyncio
async def test_sweep_step_all_runs_in_documented_order(sweep, app, clock, monkeypatch):
    calls = []

    async def _trace_clock():
        calls.append("clock_and_first_move")

    async def _trace_grace():
        calls.append("grace")

    async def _trace_heartbeat():
        calls.append("heartbeat_timeout")

    def _trace_drop():
        calls.append("drop_orphans")

    async def _trace_post_game():
        calls.append("post_game")

    monkeypatch.setattr(sweep, "step_clock_and_first_move_abort", _trace_clock)
    monkeypatch.setattr(sweep, "step_grace_expired", _trace_grace)
    monkeypatch.setattr(sweep, "step_heartbeat_timeout", _trace_heartbeat)
    monkeypatch.setattr(sweep, "step_drop_orphans_pre_game", _trace_drop)
    monkeypatch.setattr(sweep, "step_post_game", _trace_post_game)
    monkeypatch.setattr(sweep.rooms, "gc_finished_rooms",
                        lambda: calls.append("gc"))
    await sweep.step_all()
    assert calls == ["clock_and_first_move", "heartbeat_timeout", "grace",
                     "drop_orphans", "post_game", "gc"]


@pytest.mark.asyncio
async def test_heartbeat_timeout_marks_disconnected(sweep, app, clock):
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    room.white.connected = True
    room.white.last_seen = clock()
    clock.advance(HEARTBEAT_TIMEOUT_SECONDS + 1)
    await sweep.step_heartbeat_timeout()
    assert room.white.connected is False
    assert room.white.disconnected_at is not None


@pytest.mark.asyncio
async def test_heartbeat_timeout_ignores_fresh_pings(sweep, app, clock):
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    room.white.connected = True
    room.white.last_seen = clock()
    clock.advance(1)
    await sweep.step_heartbeat_timeout()
    assert room.white.connected is True


@pytest.mark.asyncio
async def test_heartbeat_timeout_skips_pre_first_move_and_finished(sweep, app, clock):
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.started_at = clock()
    room.white.connected = True
    room.white.last_seen = clock()
    clock.advance(HEARTBEAT_TIMEOUT_SECONDS + 1)
    await sweep.step_heartbeat_timeout()
    assert room.white.connected is True
    room.first_move_at = clock()
    rooms.finalize_result(room.room_id, Reason.RESIGNATION, winner_color="white")
    await sweep.step_heartbeat_timeout()
    assert room.white.connected is True
