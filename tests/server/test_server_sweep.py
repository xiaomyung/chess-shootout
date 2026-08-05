"""Sweep step methods exercised in isolation via a fake clock.

The Sweep class wraps the per-tick lifecycle: each step does one thing
(clock + first-move abort, grace expiry, orphan/post-result drop, beacon,
GC) so we drive each independently without the full asyncio loop.
"""
import pytest

from chessshootout.server.protocol import GRACE_SECONDS, HEARTBEAT_TIMEOUT_SECONDS, Reason
from chessshootout.server.rooms import POST_GAME_DISCONNECT_GRACE, QUEUE_ABANDON_SECONDS
from chessshootout.server.sweep import PREGAME_CONNECT_GRACE_SECONDS
from tests.server.test_server_broadcasts import RecordingWS
from tests.helpers import fake_uuid4
from tests.server.conftest import ALICE, BOB


async def _pair(rooms, time_minutes=5):
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=time_minutes, increment_seconds=0,
                        side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=time_minutes, increment_seconds=0,
                        side_preference="black")
    return list(rooms._active.values())[0]


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
        room.plies_ever = 1
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
    room.plies_ever = 1
    room.white.connected = True
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABANDONMENT, "black")


@pytest.mark.asyncio
async def test_sweep_step_grace_expired_with_desync_awards_opponent(sweep, app, clock):
    """See test_server_app: the desync flag never downgrades an abandonment win
    once moves were played; zero-ply games abort via finalize_result instead."""
    room = await _pair(app.state.rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    room.plies_ever = 1
    room.white.connected = True
    room.white.desync_active = True
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABANDONMENT, "black")


async def test_post_game_leaver_grace_restarts_at_the_result(sweep, app, clock):
    """REGRESSION (v2.10.0 live smoke): the winner never saw the VICTORY screen.
    The leaver's pre-result disconnected_at also satisfied the post-game rematch
    grace, so opponent_left fired in the same sweep pass as the result and the
    client tore the session down instantly. finalize_result now restamps a
    disconnected slot's clock to ended_at: the post-game window gets its full
    grace measured from the result, not from the original disconnect."""
    room = await _pair(app.state.rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    room.plies_ever = 1
    room.white.connected = True
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance(61)
    await sweep.step_grace_expired()
    assert room.result == (Reason.ABANDONMENT, "black")
    assert room.white.disconnected_at == room.ended_at
    ws_black = RecordingWS()
    app.state.connections.add(room.room_id, room.black.client_uuid, ws_black)
    clock.advance(POST_GAME_DISCONNECT_GRACE - 1)
    await sweep.step_post_game()
    assert app.state.rooms.get(room.room_id) is room, "room survives inside the fresh grace"
    assert not ws_black.of_type("rematch_update")
    clock.advance(2)
    await sweep.step_post_game()
    updates = ws_black.of_type("rematch_update")
    assert updates and updates[-1]["event"] == "opponent_left"


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
    room_a.plies_ever = 1
    room_a.white.connected = True
    room_a.black.connected = True

    await rooms.enqueue(client_uuid=CARL, nickname="C", session_token="tc",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    room_b = await rooms.enqueue(client_uuid=DAVE, nickname="D", session_token="td",
                                 time_minutes=5, increment_seconds=0, side_preference="black")
    room_b.started_at = clock()
    room_b.first_move_at = clock()
    room_b.plies_ever = 1
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

    def _trace_reap_queue():
        calls.append("reap_queue")

    async def _trace_post_game():
        calls.append("post_game")

    monkeypatch.setattr(sweep, "step_clock_and_first_move_abort", _trace_clock)
    monkeypatch.setattr(sweep, "step_grace_expired", _trace_grace)
    monkeypatch.setattr(sweep, "step_heartbeat_timeout", _trace_heartbeat)
    monkeypatch.setattr(sweep, "step_drop_orphans_pre_game", _trace_drop)
    monkeypatch.setattr(sweep, "step_reap_abandoned_queue", _trace_reap_queue)
    monkeypatch.setattr(sweep, "step_post_game", _trace_post_game)
    monkeypatch.setattr(sweep.rooms, "gc_finished_rooms",
                        lambda: calls.append("gc"))
    await sweep.step_all()
    assert calls == ["clock_and_first_move", "heartbeat_timeout", "grace",
                     "drop_orphans", "reap_queue", "post_game", "gc"]


async def _queue_alone(rooms, time_minutes=5):
    return await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                               time_minutes=time_minutes, increment_seconds=0,
                               side_preference="white")


@pytest.mark.asyncio
async def test_sweep_reaps_a_queued_room_nobody_ever_connected_to(sweep, app, clock):
    """SECURITY: POST /matchmake with no websocket and no DELETE used to pin a
    queue slot until process restart, and queue depth counts against max_rooms --
    ~max_rooms such requests locked every later player out with 503 room_full.
    The sweep now reaps the abandoned waiter once it is past the TTL."""
    rooms = app.state.rooms
    room = await _queue_alone(rooms)
    clock.advance(QUEUE_ABANDON_SECONDS - 1)
    sweep.step_reap_abandoned_queue()
    assert rooms.queue_depth == 1, "a waiter inside the TTL is never reaped"
    clock.advance(2)
    sweep.step_reap_abandoned_queue()
    assert rooms.queue_depth == 0
    assert rooms.get(room.room_id) is None


@pytest.mark.asyncio
async def test_sweep_never_reaps_a_queued_player_holding_a_live_socket(sweep, app, clock):
    """A real player waiting for a match auths a websocket to the queued room and
    holds it open with no timeout on the client side, so age alone cannot mean
    abandoned. The live socket is the liveness proof: only a queued room with no
    connection behind it is reapable, which is exactly the shape of the
    HTTP-only flood. There is no protocol message that tells a waiting client its
    queue slot vanished, so evicting a connected waiter would strand it in a
    permanent 'searching' modal."""
    rooms = app.state.rooms
    room = await _queue_alone(rooms)
    app.state.connections.add(room.room_id, ALICE, RecordingWS())
    clock.advance(QUEUE_ABANDON_SECONDS * 10)
    sweep.step_reap_abandoned_queue()
    assert rooms.get(room.room_id) is room
    assert rooms.queue_depth == 1


@pytest.mark.asyncio
async def test_sweep_reap_leaves_paired_rooms_alone(sweep, app, clock):
    """The reap walks the queue only: a paired room keeps the `created_at` of the
    queued room it grew from, so an active game that outlives the TTL must be
    untouched."""
    rooms = app.state.rooms
    room = await _pair(rooms)
    room.started_at = clock()
    room.first_move_at = clock()
    clock.advance(QUEUE_ABANDON_SECONDS * 10)
    sweep.step_reap_abandoned_queue()
    assert rooms.get(room.room_id) is room
    assert rooms.rooms_active == 1


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
