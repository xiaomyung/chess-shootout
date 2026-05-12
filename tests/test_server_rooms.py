import random

import pytest

from server.protocol import GRACE_SECONDS
from server.rooms import (
    AlreadyInGameError, InvalidTokenError, NotInRoomError,
    PlayerSlot, REMATCH_KEEP_ALIVE_SECONDS, Room, RoomManager,
)
from tests.helpers import FakeClock


def _enqueue_kwargs(client_uuid, **overrides):
    base = dict(
        client_uuid=client_uuid,
        nickname=client_uuid.title(),
        session_token=f"tok-{client_uuid}",
        time_minutes=5,
        increment_seconds=0,
        side_preference="random",
    )
    base.update(overrides)
    return base


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def manager(clock):
    return RoomManager(now_provider=clock)


@pytest.mark.asyncio
async def test_enqueue_first_player_creates_pending_room(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert room.color_of("alice") in ("white", "black")
    assert not room.is_paired()
    assert room.backend is None
    assert manager.rooms_active == 0


@pytest.mark.asyncio
async def test_enqueue_second_matching_player_pairs_them(manager):
    room1 = await manager.enqueue(**_enqueue_kwargs("alice"))
    room2 = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room1.room_id == room2.room_id
    assert room2.color_of("alice") != room2.color_of("bob")
    assert room2.is_paired()
    assert room2.backend is not None
    assert manager.rooms_active == 1


@pytest.mark.asyncio
async def test_enqueue_pairs_only_within_same_time_control(manager):
    r1 = await manager.enqueue(**_enqueue_kwargs("alice", time_minutes=5))
    r2 = await manager.enqueue(**_enqueue_kwargs("bob", time_minutes=10))
    assert r1.room_id != r2.room_id
    assert manager.rooms_active == 0


@pytest.mark.asyncio
async def test_enqueue_resolves_color_conflict_randomly(manager):
    random.seed(42)
    await manager.enqueue(**_enqueue_kwargs("alice", side_preference="white"))
    room = await manager.enqueue(**_enqueue_kwargs("bob", side_preference="white"))
    # After pairing, the conflict is resolved by coin flip; both must end up with
    # different colors regardless of which way the flip went.
    assert {room.color_of("alice"), room.color_of("bob")} == {"white", "black"}


@pytest.mark.asyncio
async def test_enqueue_honors_explicit_complementary_sides(manager):
    await manager.enqueue(**_enqueue_kwargs("alice", side_preference="white"))
    room = await manager.enqueue(**_enqueue_kwargs("bob", side_preference="black"))
    assert room.color_of("alice") == "white"
    assert room.color_of("bob") == "black"


@pytest.mark.asyncio
async def test_enqueue_random_takes_opposite_of_explicit(manager):
    await manager.enqueue(**_enqueue_kwargs("alice", side_preference="black"))
    room = await manager.enqueue(**_enqueue_kwargs("bob", side_preference="random"))
    assert room.color_of("alice") == "black"
    assert room.color_of("bob") == "white"


@pytest.mark.asyncio
async def test_enqueue_rejects_already_in_game(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    await manager.enqueue(**_enqueue_kwargs("bob"))  # pair them
    with pytest.raises(AlreadyInGameError):
        await manager.enqueue(**_enqueue_kwargs("alice"))


@pytest.mark.asyncio
async def test_cancel_wait_removes_from_queue(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    await manager.cancel_wait(room.room_id, session_token="tok-alice")
    room2 = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert room2.room_id != room.room_id


@pytest.mark.asyncio
async def test_cancel_wait_invalid_token_rejected(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    with pytest.raises(InvalidTokenError):
        await manager.cancel_wait(room.room_id, session_token="bogus")


@pytest.mark.asyncio
async def test_cancel_wait_unknown_room_raises(manager):
    with pytest.raises(NotInRoomError):
        await manager.cancel_wait("no-such-room", session_token="anything")


@pytest.mark.asyncio
async def test_drop_player_starts_grace_timer(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    color = room.color_of("alice")
    manager.mark_connected(room.room_id, "white")
    manager.mark_connected(room.room_id, "black")
    manager.mark_disconnected(room.room_id, color)
    clock.advance(GRACE_SECONDS - 1)
    assert list(manager.grace_expired_rooms()) == []
    clock.advance(2)
    expired = list(manager.grace_expired_rooms())
    assert len(expired) == 1
    expired_room, abandoned_color = expired[0]
    assert expired_room.room_id == room.room_id
    assert abandoned_color == color


@pytest.mark.asyncio
async def test_finalize_abandonment_sets_result(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_abandonment(room.room_id, "white")
    assert room.result == ("abandonment", "black")
    assert room.ended_at is not None


@pytest.mark.asyncio
async def test_finalize_abandonment_idempotent(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_abandonment(room.room_id, "white")
    manager.finalize_abandonment(room.room_id, "black")
    assert room.result == ("abandonment", "black")


@pytest.mark.asyncio
async def test_clock_keeps_ticking_during_grace(manager, clock):
    """Clock is server-authoritative and never pauses on disconnect."""
    await manager.enqueue(**_enqueue_kwargs("alice", time_minutes=1, increment_seconds=0))
    room = await manager.enqueue(**_enqueue_kwargs("bob", time_minutes=1, increment_seconds=0))
    manager.mark_disconnected(room.room_id, "white")
    clock.advance(70)
    room.backend.tick_clock()
    assert room.backend.clock.flagged is not None


@pytest.mark.asyncio
async def test_reset_for_rematch_swaps_colors_and_clears_state(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    pre_white_uuid = room.white.client_uuid
    pre_black_uuid = room.black.client_uuid
    room.draw_offered_by = "white"
    room.takeback_offered_by = "white"
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    assert room.result is not None

    manager.reset_for_rematch(room.room_id)
    assert room.result is None
    assert room.draw_offered_by is None
    assert room.takeback_offered_by is None
    assert room.white.client_uuid == pre_black_uuid
    assert room.black.client_uuid == pre_white_uuid
    assert len(room.backend.move_history) == 0
    assert room.backend.clock is not None


@pytest.mark.asyncio
async def test_gc_drops_finished_rooms_after_keep_alive(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    clock.advance(REMATCH_KEEP_ALIVE_SECONDS - 1)
    manager.gc_finished_rooms()
    assert manager.rooms_active == 1
    clock.advance(2)
    manager.gc_finished_rooms()
    assert manager.rooms_active == 0
    new_room = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert new_room.room_id != room.room_id


@pytest.mark.asyncio
async def test_get_finds_queued_room_before_pairing(manager):
    """First player's WS auth happens before the second matchmakes.
    `get(room_id)` must resolve queued rooms too, else auth fails."""
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    found = manager.get(room.room_id)
    assert found is room


@pytest.mark.asyncio
async def test_color_of_returns_correct_color(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room.color_of("alice") in ("white", "black")
    assert room.color_of("bob") in ("white", "black")
    assert room.color_of("alice") != room.color_of("bob")
    assert room.color_of("unknown") is None


@pytest.mark.asyncio
async def test_slot_by_token_returns_correct_slot(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    color, slot = room.slot_by_token("tok-alice")
    assert slot.client_uuid == "alice"
    assert color == room.color_of("alice")
    color, slot = room.slot_by_token("bogus")
    assert slot is None and color is None
