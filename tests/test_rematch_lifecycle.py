"""Post-game room lifecycle: the v2.3.4 rematch/menu/reconnect state machine.

These drive handlers + the Sweep directly with a fake connection registry so
the zombie-room race (a finished room GC'd while both players are still
connected, which silently dropped rematch moves and skipped the color swap) is
pinned end to end alongside every close condition.
"""
import json

import pytest

from chessshootout.server.app import create_app
from chessshootout.server.handlers import (
    handle_left_result, handle_move, handle_rematch_request, handle_rematch_response,
)
from chessshootout.server.protocol import PROTOCOL_VERSION, Reason
from chessshootout.server.rooms import (
    POST_GAME_DISCONNECT_GRACE, REMATCH_ABSOLUTE_CAP_SECONDS, REMATCH_IDLE_SECONDS,
)
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    def types(self):
        return [m.get("type") for m in self.sent]

    def events(self):
        return [m["event"] for m in self.sent if m.get("type") == "rematch_update"]


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


async def _finished_room(app, *, connect_a=True, connect_b=True):
    rooms = app.state.rooms
    connections = app.state.connections
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    room = await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                               time_minutes=5, increment_seconds=0, side_preference="black")
    room.first_move_at = app.state.now()
    ws_a = ws_b = None
    if connect_a:
        ws_a = FakeWS()
        rooms.mark_connected(room.room_id, room.color_of(ALICE))
        connections.add(room.room_id, ALICE, ws_a)
    if connect_b:
        ws_b = FakeWS()
        rooms.mark_connected(room.room_id, room.color_of(BOB))
        connections.add(room.room_id, BOB, ws_b)
    rooms.finalize_result(room.room_id, "checkmate", winner_color="white")
    return room, ws_a, ws_b


def _raw(**fields):
    return json.dumps({"version": PROTOCOL_VERSION, **fields})


async def _offer(app, room, ws, uuid):
    return await handle_rematch_request(
        app, ws, room, room.color_of(uuid), _raw(type="rematch_request"))


async def _respond(app, room, ws, uuid, accept):
    return await handle_rematch_response(
        app, ws, room, room.color_of(uuid),
        _raw(type="rematch_response", accept=accept))


async def _move(app, room, ws, uuid, frm, to):
    return await handle_move(
        app, ws, room, room.color_of(uuid), _raw(type="move", **{"from": frm, "to": to}))


@pytest.mark.asyncio
async def test_late_rematch_swaps_colors_and_moves_flow(app, clock):
    """The #2/#4 regression: a rematch accepted long after game-over (past the
    old 60s keep-alive) still restarts, swaps colors, and relays moves."""
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    clock.advance(90)
    await app.state.sweep.step_all()
    assert rooms.rooms_active == 1

    await _offer(app, room, ws_a, ALICE)
    assert "rematch_request" in ws_b.types()
    assert await _respond(app, room, ws_b, BOB, True) == "restarted"

    starts_a = [m for m in ws_a.sent if m.get("type") == "game_start"]
    starts_b = [m for m in ws_b.sent if m.get("type") == "game_start"]
    assert starts_a and starts_a[-1]["rematch"] is True
    assert starts_a[-1]["your_color"] == "black"
    assert starts_b[-1]["your_color"] == "white"
    assert starts_a[-1]["started_seconds_ago"] == pytest.approx(0.0, abs=1.0)

    assert await _move(app, room, ws_b, BOB, "e2", "e4") == "applied"
    assert "move_applied" in ws_a.types()
    assert "move_applied" in ws_b.types()


@pytest.mark.asyncio
async def test_rematch_request_requires_at_result(app):
    room, ws_a, ws_b = await _finished_room(app)
    room.slot(room.color_of(ALICE)).at_result = False
    assert await _offer(app, room, ws_a, ALICE) == "unavailable"
    assert room.rematch_offered_by == set()
    errs = [m for m in ws_a.sent if m.get("type") == "error"]
    assert errs and errs[-1]["reason"] == Reason.REMATCH_UNAVAILABLE


@pytest.mark.asyncio
async def test_dead_room_accept_errors_no_game_start(app):
    room, ws_a, ws_b = await _finished_room(app)
    await _offer(app, room, ws_a, ALICE)
    app.state.rooms.drop_room_now(room.room_id)
    assert await _respond(app, room, ws_b, BOB, True) == "unavailable"
    assert "game_start" not in ws_b.types()
    errs = [m for m in ws_b.sent if m.get("type") == "error"]
    assert errs and errs[-1]["reason"] == Reason.REMATCH_UNAVAILABLE


@pytest.mark.asyncio
async def test_decline_notifies_both_and_drops_room(app):
    """The offerer hears 'declined'; the decliner hears 'window_expired' so they
    leave the result screen too instead of stranding on the orphaned room."""
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    await _offer(app, room, ws_a, ALICE)
    assert await _respond(app, room, ws_b, BOB, False) == "declined"
    assert "declined" in ws_a.events()
    assert "window_expired" in ws_b.events()
    assert rooms.rooms_active == 0


@pytest.mark.asyncio
async def test_duplicate_rematch_request_gets_error_feedback(app):
    room, ws_a, ws_b = await _finished_room(app)
    assert await _offer(app, room, ws_a, ALICE) == "offered"
    assert await _offer(app, room, ws_a, ALICE) == "duplicate"
    errs = [m for m in ws_a.sent if m.get("type") == "error"]
    assert errs and errs[-1]["reason"] == Reason.REMATCH_ALREADY_PENDING
    assert errs[-1]["msg_type"] == "rematch_request"


class _RaceThenClearWS(FakeWS):
    """Simulates the opponent's own concurrent action (a decline, a self-accept
    race, etc.) already invalidating our just-sent offer by the time our own
    `await send(...)` for it returns."""

    def __init__(self, room, offering_color):
        super().__init__()
        self._room = room
        self._offering_color = offering_color

    async def send_json(self, data):
        await super().send_json(data)
        self._room.rematch_offered_by.discard(self._offering_color)


@pytest.mark.asyncio
async def test_stray_rematch_banner_is_corrected_if_offer_invalidated_mid_await(app):
    """REGRESSION: after `await send(opp_ws, RematchRequestMessage())` yields,
    the opponent's own concurrent action may have already cleared our offer
    (game restarted, or they declined) -- without the post-await re-check the
    opponent is left staring at a stale 'wants a rematch' banner. With it, a
    corrective 'cancelled' event follows immediately."""
    room, ws_a, _ = await _finished_room(app, connect_b=False)
    alice_color = room.color_of(ALICE)
    racing = _RaceThenClearWS(room, alice_color)
    app.state.connections.add(room.room_id, BOB, racing)

    out = await _offer(app, room, ws_a, ALICE)

    assert out == "offered"
    assert racing.types() == ["rematch_request", "rematch_update"]
    assert racing.events() == ["cancelled"], \
        "the opponent must get a corrective cancel, not a stray live banner"


@pytest.mark.asyncio
async def test_rematch_offer_sends_no_corrective_cancel_in_the_normal_case(app):
    room, ws_a, ws_b = await _finished_room(app)
    await _offer(app, room, ws_a, ALICE)
    assert ws_b.types() == ["rematch_request"], "no stray corrective when nothing raced"


@pytest.mark.asyncio
async def test_offerer_cannot_self_accept_rematch(app):
    """An offerer accepting their own offer must be a no-op — not a forced restart
    that yanks the opponent into a new game without consent."""
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    await _offer(app, room, ws_a, ALICE)
    assert await _respond(app, room, ws_a, ALICE, True) == "noop"
    assert rooms.rooms_active == 1
    assert "game_start" not in ws_a.types()
    assert "game_start" not in ws_b.types()


@pytest.mark.asyncio
async def test_move_to_finished_room_sends_error_not_silent(app):
    room, ws_a, ws_b = await _finished_room(app)
    assert await _move(app, room, ws_a, ALICE, "e2", "e4") == "already_over"
    errs = [m for m in ws_a.sent if m.get("type") == "error"]
    assert errs and errs[-1]["reason"] == Reason.GAME_ALREADY_OVER


@pytest.mark.asyncio
async def test_left_result_withdraws_pending_offer(app):
    room, ws_a, ws_b = await _finished_room(app)
    await _offer(app, room, ws_a, ALICE)
    out = await handle_left_result(
        app, ws_a, room, room.color_of(ALICE), _raw(type="left_result"))
    assert out == "left_result"
    assert room.slot(room.color_of(ALICE)).at_result is False
    assert room.rematch_offered_by == set()
    assert "cancelled" in ws_b.events()


@pytest.mark.asyncio
async def test_sweep_keeps_room_while_both_on_result(app, clock):
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    clock.advance(POST_GAME_DISCONNECT_GRACE + 30)
    await app.state.sweep.step_post_game()
    rooms.gc_finished_rooms()
    assert rooms.rooms_active == 1


@pytest.mark.asyncio
async def test_sweep_drops_both_disconnected_immediately(app):
    rooms = app.state.rooms
    room, _, _ = await _finished_room(app, connect_a=False, connect_b=False)
    await app.state.sweep.step_post_game()
    assert rooms.rooms_active == 0


@pytest.mark.asyncio
async def test_sweep_one_gone_grace_then_opponent_left(app, clock):
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    bob_color = room.color_of(BOB)
    app.state.connections.remove(room.room_id, BOB, ws_b)
    rooms.mark_disconnected(room.room_id, bob_color)
    await app.state.sweep.step_post_game()
    assert rooms.rooms_active == 1
    clock.advance(POST_GAME_DISCONNECT_GRACE + 1)
    await app.state.sweep.step_post_game()
    assert rooms.rooms_active == 0
    assert "opponent_left" in ws_a.events()


@pytest.mark.asyncio
async def test_sweep_both_in_menu_drops_with_window_expired(app):
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    room.white.at_result = False
    room.black.at_result = False
    await app.state.sweep.step_post_game()
    assert rooms.rooms_active == 0
    assert "window_expired" in ws_a.events()
    assert "window_expired" in ws_b.events()


@pytest.mark.asyncio
async def test_sweep_idle_drops_with_window_expired(app, clock):
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    clock.advance(REMATCH_IDLE_SECONDS + 1)
    await app.state.sweep.step_post_game()
    assert rooms.rooms_active == 0
    assert "window_expired" in ws_a.events()
    assert "window_expired" in ws_b.events()


@pytest.mark.asyncio
async def test_sweep_absolute_cap_drops_and_notifies_both_present(app, clock):
    rooms = app.state.rooms
    room, ws_a, ws_b = await _finished_room(app)
    clock.advance(REMATCH_ABSOLUTE_CAP_SECONDS + 1)
    await app.state.sweep.step_post_game()
    assert rooms.rooms_active == 0
    assert "window_expired" in ws_a.events()
    assert "window_expired" in ws_b.events()
