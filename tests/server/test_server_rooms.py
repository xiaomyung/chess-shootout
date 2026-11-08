import pytest

from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import square_from_coord
from chessshootout.server import rooms as rooms_module
from chessshootout.server.broadcasts import game_start_message
from chessshootout.server.protocol import (
    FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, IDLE_RESIGN_SECONDS, Reason,
)
from chessshootout.server.rooms import (
    AlreadyInGameError, GameAlreadyStartedError, InvalidTokenError, NotInRoomError,
    QUEUE_ABANDON_SECONDS, REMATCH_ABSOLUTE_CAP_SECONDS, REMATCH_IDLE_SECONDS, Room,
    RoomManager, ServerFullError, SharedAnnotations,
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
    assert manager.queue_depth == 1


@pytest.mark.asyncio
async def test_enqueue_second_matching_player_pairs_them(manager):
    room1 = await manager.enqueue(**_enqueue_kwargs("alice"))
    room2 = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room1.room_id == room2.room_id
    assert room2.color_of("alice") != room2.color_of("bob")
    assert room2.is_paired()
    assert room2.backend is not None
    assert len(room2.backend.move_history) == 0
    assert room2.started_at == 0.0
    assert manager.rooms_active == 1
    assert manager.queue_depth == 0


@pytest.mark.asyncio
async def test_enqueue_pairs_only_within_same_time_control(manager):
    r1 = await manager.enqueue(**_enqueue_kwargs("alice", time_minutes=5))
    r2 = await manager.enqueue(**_enqueue_kwargs("bob", time_minutes=10))
    assert r1.room_id != r2.room_id
    assert not r1.is_paired()
    assert not r2.is_paired()
    assert manager.rooms_active == 0
    assert manager.queue_depth == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_pref, second_pref, alice_color, bob_color",
    [
        pytest.param("white", "black", "white", "black",
                     id="explicit_complementary_sides_honored"),
        pytest.param("black", "random", "black", "white",
                     id="random_takes_opposite_of_explicit"),
        pytest.param("white", "white", "black", "white",
                     id="white_clash_goes_to_the_arrival"),
        pytest.param("black", "black", "white", "black",
                     id="black_clash_goes_to_the_arrival"),
        pytest.param("random", "white", "black", "white",
                     id="waiting_shrug_yields_to_the_arrival"),
    ],
)
async def test_enqueue_deterministic_color_resolution(
    manager, first_pref, second_pref, alice_color, bob_color,
):
    """Every pairing with at least one stated side resolves deterministically
    (no coin flip): a stated preference wins, and when both players asked for
    the same colour the arriving player gets it. The colour-clash rows used to
    sit in a test named for a coin flip that never happens -- only two shrugs
    are left to chance."""
    await manager.enqueue(**_enqueue_kwargs("alice", side_preference=first_pref))
    room = await manager.enqueue(**_enqueue_kwargs("bob", side_preference=second_pref))
    assert room.color_of("alice") == alice_color
    assert room.color_of("bob") == bob_color


@pytest.mark.asyncio
async def test_enqueue_rejects_already_in_game(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    await manager.enqueue(**_enqueue_kwargs("bob"))
    with pytest.raises(AlreadyInGameError):
        await manager.enqueue(**_enqueue_kwargs("alice"))


@pytest.mark.asyncio
async def test_cancel_wait_removes_from_queue(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    await manager.cancel_wait(room.room_id, session_token="tok-alice")
    assert manager.queue_depth == 0
    assert manager.get(room.room_id) is None
    room2 = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert room2.room_id != room.room_id


@pytest.mark.asyncio
async def test_cancel_wait_invalid_token_rejected(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    with pytest.raises(InvalidTokenError):
        await manager.cancel_wait(room.room_id, session_token="bogus")
    assert manager.get(room.room_id) is room


@pytest.mark.asyncio
async def test_cancel_wait_unknown_room_raises(manager):
    with pytest.raises(NotInRoomError):
        await manager.cancel_wait("no-such-room", session_token="anything")


@pytest.mark.asyncio
async def test_cancel_wait_on_a_started_game_raises_game_already_started(manager):
    """A paired room is out of the queue, so cancelling it is not "not in room"
    but "too late" -- its own exception, which the route answers with the
    already_started status instead of a 404."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room.is_paired()
    with pytest.raises(GameAlreadyStartedError):
        await manager.cancel_wait(room.room_id, session_token="tok-alice")


@pytest.mark.parametrize("exc_type", [ServerFullError, GameAlreadyStartedError])
def test_refusal_errors_are_not_runtime_errors(exc_type):
    """Both used to be `RuntimeError("server_full")` / `("game_already_started")`
    string-matched at the route. A plain Exception subclass is what makes the
    `except` arm precise: were either one still a RuntimeError, an unrelated
    RuntimeError raised deeper in the room manager would be caught by the same
    arm and answered as a polite refusal."""
    assert issubclass(exc_type, Exception)
    assert not issubclass(exc_type, RuntimeError)


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
async def test_finalize_result_aborts_with_no_winner(manager, clock):
    """A disconnect abort records a no-winner result and is idempotent (first sticks)."""
    clock.advance(12)
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "aborted")
    assert room.result == ("aborted", None)
    assert room.ended_at == 12.0
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    assert room.result == ("aborted", None)


@pytest.mark.asyncio
async def test_finalize_result_reports_whether_it_applied(manager):
    """The return value tells a racing caller (e.g. resign vs. mate landing at the
    same instant) whether IT won the state, so it knows whether to broadcast."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert manager.finalize_result(room.room_id, "checkmate", winner_color="white") is True
    assert manager.finalize_result(room.room_id, "resignation", winner_color="black") is False
    assert manager.finalize_result("no-such-room", "checkmate", winner_color="white") is False


@pytest.mark.asyncio
async def test_active_rooms_returns_an_iteration_safe_snapshot(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    snapshot = manager.active_rooms()
    assert snapshot == [room]
    assert isinstance(snapshot, list), \
        "callers mutate rooms while iterating; a live view would break"


@pytest.mark.asyncio
async def test_in_progress_room_for_only_matches_started_unfinished_games(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    assert manager.in_progress_room_for("alice") is None
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert manager.in_progress_room_for("alice") is None
    room.first_move_at = 1.0
    in_prog = manager.in_progress_room_for("alice")
    assert in_prog is not None
    assert in_prog[0] is room
    assert in_prog[1] == room.color_of("alice")
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    assert manager.in_progress_room_for("alice") is None


@pytest.mark.asyncio
async def test_release_for_new_game_frees_active_and_queued_uuids(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.release_for_new_game("alice")
    assert manager.get(room.room_id) is None
    await manager.enqueue(**_enqueue_kwargs("alice"))
    manager.release_for_new_game("bob")
    await manager.enqueue(**_enqueue_kwargs("bob"))


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
    room.rematch_offered_by = {"white", "black"}
    room.game_start_broadcast = True
    room.white.game_start_sent = True
    room.black.game_start_sent = True
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    assert room.result is not None
    assert room.white.at_result is True
    assert room.black.at_result is True
    assert room.last_rematch_activity_at == room.ended_at

    assert manager.reset_for_rematch(room.room_id) is True
    assert room.result is None
    assert room.draw_offered_by is None
    assert room.takeback_offered_by is None
    assert room.rematch_offered_by == set()
    assert room.game_start_broadcast is False
    assert room.ended_at is None
    assert room.last_rematch_activity_at is None
    assert room.first_move_at is None
    assert room.white.at_result is False
    assert room.black.at_result is False
    assert room.white.game_start_sent is False
    assert room.black.game_start_sent is False
    assert room.white.client_uuid == pre_black_uuid
    assert room.black.client_uuid == pre_white_uuid
    assert len(room.backend.move_history) == 0
    assert room.backend.clock is not None


@pytest.mark.asyncio
async def test_reset_for_rematch_gives_an_away_player_a_fresh_grace(manager, clock):
    """REGRESSION: finalize_result restamps a disconnected slot to ended_at, and
    the rematch used to inherit that stamp -- a player who dropped during the
    previous game started the new one with their whole grace already spent and
    lost it by abandonment on the first sweep. The reset restamps to now for a
    player still away, and clears the stamp for one who is back."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.white.connected = True
    room.black.connected = True
    manager.mark_disconnected(room.room_id, "white")
    manager.finalize_result(room.room_id, "checkmate", winner_color="black")
    assert room.white.disconnected_at == room.ended_at
    clock.advance(120)

    assert manager.reset_for_rematch(room.room_id) is True
    back, away = room.white, room.black
    assert back.connected is True and back.disconnected_at is None
    assert away.connected is False and away.disconnected_at == clock()


@pytest.mark.asyncio
async def test_reset_for_rematch_returns_false_when_room_gone(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    manager.drop_room_now(room.room_id)
    assert manager.reset_for_rematch(room.room_id) is False


@pytest.mark.asyncio
async def test_reset_for_rematch_returns_false_when_not_finished(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert manager.reset_for_rematch(room.room_id) is False


@pytest.mark.asyncio
async def test_enqueue_stores_country_per_slot(manager):
    await manager.enqueue(**_enqueue_kwargs("alice", country="US"))
    room = await manager.enqueue(**_enqueue_kwargs("bob", country="RO"))
    alice_color = room.color_of("alice")
    assert room.slot(alice_color).country == "US"
    assert room.slot(room.opp_color(alice_color)).country == "RO"


@pytest.mark.asyncio
async def test_enqueue_country_defaults_none(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert room.slot(room.color_of("alice")).country is None


@pytest.mark.asyncio
async def test_rematch_swaps_country_with_player(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice", country="US"))
    room = await manager.enqueue(**_enqueue_kwargs("bob", country="RO"))
    pre_white_country = room.white.country
    pre_black_country = room.black.country
    room.game_start_broadcast = True
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    manager.reset_for_rematch(room.room_id)
    assert room.white.country == pre_black_country
    assert room.black.country == pre_white_country


@pytest.mark.asyncio
async def test_gc_drops_finished_rooms_after_idle(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    clock.advance(REMATCH_IDLE_SECONDS - 1)
    manager.gc_finished_rooms()
    assert manager.rooms_active == 1
    clock.advance(2)
    manager.gc_finished_rooms()
    assert manager.rooms_active == 0
    new_room = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert new_room.room_id != room.room_id


@pytest.mark.asyncio
async def test_gc_rematch_activity_extends_idle_until_cap(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    for _ in range(2):
        clock.advance(REMATCH_IDLE_SECONDS - 1)
        manager.mark_rematch_activity(room)
        manager.gc_finished_rooms()
        assert manager.rooms_active == 1
    clock.advance(REMATCH_ABSOLUTE_CAP_SECONDS)
    manager.gc_finished_rooms()
    assert manager.rooms_active == 0


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
    assert room.slot(room.color_of("alice")).client_uuid == "alice"
    assert room.slot(room.color_of("bob")).client_uuid == "bob"


@pytest.mark.asyncio
async def test_slot_by_token_returns_correct_slot(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    color, slot = room.slot_by_token("tok-alice")
    assert slot.client_uuid == "alice"
    assert color == room.color_of("alice")
    color, slot = room.slot_by_token("bogus")
    assert slot is None and color is None


@pytest.mark.asyncio
async def test_series_scores_award_win_and_persist_across_rematch(manager):
    """A win gives the winner +1 keyed by client uuid; a later draw gives both
    +0.5; the tally survives the color swap of a rematch."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    rid = room.room_id
    white_uuid = room.white.client_uuid
    black_uuid = room.black.client_uuid
    manager.finalize_result(rid, "checkmate", "white")
    assert room.series_scores[white_uuid] == 1.0
    assert room.score_for("white") == 1.0
    assert room.score_for("black") == 0.0
    manager.reset_for_rematch(rid)
    manager.finalize_result(rid, "draw_repetition", None)
    assert room.series_scores[white_uuid] == 1.5
    assert room.series_scores[black_uuid] == 0.5


@pytest.mark.asyncio
async def test_series_scores_stay_separate_for_two_identical_nicknames(manager):
    """REGRESSION: scores were keyed by nickname, so two players who both left
    the default name in place shared one tally -- a draw read as 1.0 apiece on
    both strips, and a win credited the loser too. Keyed by the uuid they are
    two players again."""
    await manager.enqueue(**_enqueue_kwargs("alice", nickname="Player"))
    room = await manager.enqueue(**_enqueue_kwargs("bob", nickname="Player"))
    assert room.white.nickname == room.black.nickname == "Player"
    manager.finalize_result(room.room_id, "draw_repetition", None)
    assert room.score_for("white") == 0.5
    assert room.score_for("black") == 0.5
    assert sorted(room.series_scores) == sorted(
        [room.white.client_uuid, room.black.client_uuid])


@pytest.mark.asyncio
async def test_series_scores_not_awarded_on_abort(manager):
    """An abort is neutral: no series point to either player."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "aborted", None)
    assert room.series_scores == {}
    assert room.score_for("white") == 0.0
    assert room.score_for("black") == 0.0


def test_annotations_for_returns_the_matching_color_store():
    room = Room(room_id="r", time_minutes=5, increment_seconds=0, created_at=0.0)
    assert room.annotations_for("white") is room.annotations_white
    assert room.annotations_for("black") is room.annotations_black
    assert isinstance(room.annotations_for("white"), SharedAnnotations)
    assert room.annotations_white is not room.annotations_black


def test_shared_annotations_clear_marks_preserves_sharing():
    ann = SharedAnnotations(sharing=True)
    ann.highlights.add("e4")
    ann.arrows.append(("e2", "e4"))
    ann.clear_marks()
    assert ann.highlights == set()
    assert ann.arrows == []
    assert ann.sharing is True


def test_shared_annotations_reset_clears_marks_and_sharing():
    ann = SharedAnnotations(sharing=True)
    ann.highlights.add("e4")
    ann.arrows.append(("e2", "e4"))
    ann.reset()
    assert ann.highlights == set() and ann.arrows == []
    assert ann.sharing is False


@pytest.mark.asyncio
async def test_finalize_result_resets_both_shared_annotation_stores(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    for color in ("white", "black"):
        ann = room.annotations_for(color)
        ann.sharing = True
        ann.highlights.add("e4")
        ann.arrows.append(("e2", "e4"))
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    for color in ("white", "black"):
        ann = room.annotations_for(color)
        assert ann.sharing is False
        assert ann.highlights == set()
        assert ann.arrows == []


@pytest.mark.asyncio
async def test_reset_for_rematch_installs_fresh_annotation_stores(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    white_before = room.annotations_white
    black_before = room.annotations_black
    room.annotations_white.sharing = True
    room.annotations_white.highlights.add("d4")
    room.annotations_black.arrows.append(("g1", "f3"))
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    assert manager.reset_for_rematch(room.room_id) is True
    assert room.annotations_white is not white_before
    assert room.annotations_black is not black_before
    assert room.annotations_white.sharing is False
    assert room.annotations_white.highlights == set()
    assert room.annotations_black.arrows == []


async def test_timeout_with_no_plies_finalizes_as_aborted_draw(manager):
    """User rule: a flag fall before any move landed is nobody's win -- the game
    aborts with no winner and awards no series points, the same as every other
    ending reachable before both sides have moved."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room.plies_ever == 0
    manager.finalize_result(room.room_id, "timeout", "white")
    assert room.result == ("aborted", None)
    assert room.series_scores == {}


async def test_timeout_after_both_sides_moved_keeps_its_winner(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = 2
    manager.finalize_result(room.room_id, "timeout", "white")
    assert room.result == ("timeout", "white")
    assert room.score_for("white") == 1.0


@pytest.mark.parametrize("plies", [0, 1], ids=["ply_zero", "ply_one"])
@pytest.mark.parametrize(
    "reason, winner",
    [
        ("timeout", "white"),
        ("abandonment", "black"),
        ("resignation", "black"),
        ("resignation", "white"),
        ("draw_agreement", None),
    ],
)
async def test_a_pregame_ending_finalizes_as_aborted_and_scores_nothing(
        manager, plies, reason, winner):
    """Before both sides have moved (plies_ever 0 or 1) every ending a player
    can reach -- a flag, a walk-away, a resignation, an agreed draw -- is an
    abort: no winner, no series point for anybody."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = plies
    assert manager.finalize_result(room.room_id, reason, winner) is True
    assert room.result == ("aborted", None)
    assert room.series_scores == {}
    assert room.score_for("white") == 0.0
    assert room.score_for("black") == 0.0


async def test_zero_ply_resignation_finalizes_as_aborted_and_scores_nothing(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "resignation", "black")
    assert room.result == ("aborted", None)
    assert room.series_scores == {}


async def test_zero_ply_draw_agreement_finalizes_as_aborted_and_scores_nothing(manager):
    """An agreed draw before anyone moved is a cancelled game, not a real draw:
    it is rewritten to aborted and splits nothing."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room.plies_ever == 0
    manager.finalize_result(room.room_id, "draw_agreement", None)
    assert room.result == ("aborted", None)
    assert room.series_scores == {}
    assert room.score_for("white") == 0.0
    assert room.score_for("black") == 0.0


@pytest.mark.parametrize("plies", [2, 3, 40])
async def test_a_resignation_after_both_sides_moved_keeps_its_winner(manager, plies):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = plies
    manager.finalize_result(room.room_id, "resignation", "black")
    assert room.result == ("resignation", "black")
    assert room.score_for("black") == 1.0
    assert room.score_for("white") == 0.0


@pytest.mark.parametrize("plies", [2, 3, 40])
async def test_a_draw_agreement_after_both_sides_moved_splits_the_point(manager, plies):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = plies
    manager.finalize_result(room.room_id, "draw_agreement", None)
    assert room.result == ("draw_agreement", None)
    assert room.score_for("white") == 0.5
    assert room.score_for("black") == 0.5


@pytest.mark.parametrize("plies", [0, 1])
@pytest.mark.parametrize(
    "reason, winner",
    [("checkmate", "white"), ("stalemate", None), ("draw_repetition", None),
     ("server_shutdown", None)],
)
async def test_endings_outside_the_pregame_set_are_never_rewritten(
        manager, plies, reason, winner):
    """Only the four pregame reasons are rewritten; any other code (reachable
    in tests via fabricated positions) is recorded as given."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = plies
    manager.finalize_result(room.room_id, reason, winner)
    assert room.result == (reason, winner)


async def test_a_pregame_resignation_in_a_rematch_leaves_the_carried_series_untouched(
        manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    rid = room.room_id
    white_uuid = room.white.client_uuid
    room.plies_ever = 30
    manager.finalize_result(rid, "checkmate", "white")
    before = dict(room.series_scores)
    assert before == {white_uuid: 1.0}
    assert manager.reset_for_rematch(rid) is True
    room.plies_ever = 1
    manager.finalize_result(rid, "resignation", "white")
    assert room.result == ("aborted", None)
    assert room.series_scores == before


async def test_a_takeback_to_an_empty_board_still_counts_as_played(manager):
    """plies_ever counts every ply ever seen and a takeback never lowers it:
    after two plies taken back to an empty board, a resignation still scores.
    Pins the plies_ever predicate deliberately over 'board empty'."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = 2
    assert room.backend is not None and room.backend.move_history == []
    manager.finalize_result(room.room_id, "resignation", "black")
    assert room.result == ("resignation", "black")
    assert room.score_for("black") == 1.0


async def test_zero_ply_abandonment_finalizes_as_aborted_draw(manager):
    """Leaving before any move landed cancels the game instead of awarding a win:
    nobody played, nobody scores (same rule as a zero-ply flag fall)."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    manager.finalize_result(room.room_id, "abandonment", "black")
    assert room.result == ("aborted", None)
    assert room.series_scores == {}


async def test_is_live_tracks_a_queued_room_a_paired_room_and_a_dropped_room(manager):
    queued = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert not queued.is_paired()
    assert manager.is_live(queued) is True
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room is queued
    assert manager.is_live(room) is True
    manager.finalize_result(room.room_id, "checkmate", "white")
    assert manager.is_live(room) is True
    manager.drop_room_now(room.room_id)
    assert manager.is_live(room) is False


async def test_is_live_is_false_for_a_room_the_manager_never_held(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    await manager.enqueue(**_enqueue_kwargs("bob"))
    assert manager.is_live(_bare_room(room_id="stranger")) is False


async def test_is_live_is_false_for_a_lookalike_with_a_live_rooms_id(manager):
    """Identity, not id: a different Room object carrying a registered id is not
    the live room."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert manager.is_live(_bare_room(room_id=room.room_id)) is False


def _bare_room(**overrides):
    base = dict(room_id="r", time_minutes=5, increment_seconds=0, created_at=0.0)
    base.update(overrides)
    return Room(**base)


@pytest.mark.parametrize(
    "plies, expected",
    [
        pytest.param(0, (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS),
                     id="ply_zero_abort_window"),
        pytest.param(1, (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS),
                     id="ply_one_abort_window"),
        pytest.param(2, (Reason.RESIGNATION, IDLE_RESIGN_SECONDS),
                     id="ply_two_resign_window"),
        pytest.param(3, None, id="ply_three_disarmed"),
    ],
)
def test_idle_window_table_arms_by_plies_ever(plies, expected):
    """The whole lifecycle policy in one table: plies 0 and 1 get the no-winner
    abort window, ply 2 the somebody-loses resign window, and from ply 3 the
    game never arms an idle window again."""
    room = _bare_room()
    room.plies_ever = plies
    assert room.idle_window() == expected


def test_idle_remaining_floors_at_zero_and_is_none_when_disarmed():
    room = _bare_room()
    room.plies_ever = 2
    room.idle_since = 10.0
    assert room.idle_remaining(10.0) == IDLE_RESIGN_SECONDS
    assert room.idle_remaining(30.0) == IDLE_RESIGN_SECONDS - 20.0
    assert room.idle_remaining(10.0 + IDLE_RESIGN_SECONDS + 5.0) == 0.0, \
        "expired windows report 0.0, never a negative countdown"
    room.idle_since = None
    assert room.idle_remaining(30.0) is None
    room.idle_since = 10.0
    room.plies_ever = 3
    assert room.idle_remaining(30.0) is None, \
        "a stale idle_since past the table's last row means no window at all"


@pytest.mark.asyncio
async def test_pairing_arms_the_abort_window_from_started_at(manager, clock):
    """The queued waiter carries no window (there is nobody to abort against);
    the moment the second player pairs, the abort window arms anchored at
    started_at — the same instant game_start's started_seconds_ago measures
    from, so server and client count down the same 60 seconds."""
    queued = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert queued.idle_since is None
    clock.advance(5)
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room.started_at == 5.0
    assert room.idle_since == room.started_at
    assert room.idle_window() == (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS)


@pytest.mark.asyncio
async def test_finalize_result_disarms_the_idle_window(manager):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.idle_pushed_at = 1.0
    assert room.idle_since is not None
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    assert room.idle_since is None
    assert room.idle_pushed_at is None


@pytest.mark.asyncio
async def test_reset_for_rematch_rearms_the_abort_window(manager, clock):
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    room.plies_ever = 6
    manager.finalize_result(room.room_id, "checkmate", winner_color="white")
    room.idle_pushed_at = 99.0
    clock.advance(30)
    assert manager.reset_for_rematch(room.room_id) is True
    assert room.plies_ever == 0
    assert room.idle_since == room.started_at == clock()
    assert room.idle_pushed_at is None
    assert room.idle_window() == (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS)


def test_pregame_abort_reasons_are_every_ending_a_player_can_reach_before_a_move():
    """The pregame rule covers exactly the endings reachable before both sides
    have moved: a flag, a walk-away, a resignation and an agreed draw. The idle
    forfeit fires only at plies_ever == 2, so it never meets the rewrite."""
    assert RoomManager.PREGAME_ABORT_REASONS == frozenset(
        {"timeout", "abandonment", "resignation", "draw_agreement"})
    assert "checkmate" not in RoomManager.PREGAME_ABORT_REASONS


@pytest.mark.asyncio
async def test_color_to_move_is_none_without_a_backend(manager):
    """The unified helper (it replaced handlers._color_to_move) guards the
    pre-pairing shape instead of raising on backend=None."""
    assert _bare_room().color_to_move() is None
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room.color_to_move() == "white"


async def test_stale_queued_rooms_ignores_fresh_waiters(manager, clock):
    """SECURITY (queue GC): nothing but age decides staleness, and a waiter that
    has not yet reached the TTL is never listed. Without this floor the reap
    would evict players in the middle of a normal match search."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    clock.advance(QUEUE_ABANDON_SECONDS - 1)
    assert manager.stale_queued_rooms() == []
    clock.advance(2)
    assert len(manager.stale_queued_rooms()) == 1


async def test_stale_queued_rooms_never_lists_active_or_paired_rooms(manager, clock):
    """Only `_queue` entries are reapable. A paired room carries the same
    `created_at` as the queued room it grew out of, so an age-only filter that
    walked `_active` too would delete live games the moment they aged past the
    TTL."""
    await manager.enqueue(**_enqueue_kwargs("alice"))
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    clock.advance(QUEUE_ABANDON_SECONDS * 10)
    assert manager.stale_queued_rooms() == []
    assert manager.get(room.room_id) is room
    assert manager.rooms_active == 1


async def test_drop_queued_room_frees_the_slot_and_the_uuid(manager, clock):
    """SECURITY (finding: queued rooms were never garbage-collected). A client
    that matchmakes and then vanishes without DELETE /matchmake used to pin its
    queue slot forever; the reap must release the room AND its `_uuid_to_room`
    entry, otherwise the uuid stays wedged in AlreadyInGame."""
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    clock.advance(QUEUE_ABANDON_SECONDS + 1)
    stale = manager.stale_queued_rooms()
    assert stale == [room]
    assert manager.drop_queued_room(room) is True
    assert manager.queue_depth == 0
    assert manager.get(room.room_id) is None
    assert manager.drop_queued_room(room) is False


async def test_reaped_uuid_can_matchmake_again_cleanly(manager, clock):
    """After the reap the same client re-queues into a brand new room instead of
    hitting AlreadyInGameError."""
    room = await manager.enqueue(**_enqueue_kwargs("alice"))
    clock.advance(QUEUE_ABANDON_SECONDS + 1)
    manager.drop_queued_room(room)
    fresh = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert fresh.room_id != room.room_id
    assert manager.queue_depth == 1


async def test_reaping_a_queued_room_frees_capacity_against_max_rooms(clock):
    """The bug that made the queue leak exploitable: `enqueue` counts queue depth
    against `_max_rooms`, so abandoned waiters permanently consumed the room
    budget and every later matchmake got refused as full."""
    manager = RoomManager(now_provider=clock, max_rooms=2)
    stale = [await manager.enqueue(**_enqueue_kwargs(name, time_minutes=minutes))
             for name, minutes in (("alice", 5), ("bob", 10))]
    with pytest.raises(ServerFullError):
        await manager.enqueue(**_enqueue_kwargs("carl", time_minutes=15))
    clock.advance(QUEUE_ABANDON_SECONDS + 1)
    for room in manager.stale_queued_rooms():
        manager.drop_queued_room(room)
    assert manager.queue_depth == 0
    assert all(manager.get(room.room_id) is None for room in stale)
    assert await manager.enqueue(**_enqueue_kwargs("carl", time_minutes=15)) is not None


@pytest.mark.parametrize(
    "drain",
    [
        pytest.param(
            lambda m, room: m.drop_queued_room(room), id="reap",
        ),
        pytest.param(
            lambda m, room: m.release_for_new_game("alice"), id="release_for_new_game",
        ),
    ],
)
async def test_emptying_a_time_control_bucket_removes_it(manager, drain):
    """`_queue` is a defaultdict keyed by the caller-supplied (minutes, increment)
    pair. Every drain path must delete the emptied bucket, else a flood of
    distinct time controls grows the dict without bound even after the rooms
    themselves are gone."""
    room = await manager.enqueue(**_enqueue_kwargs("alice", time_minutes=7,
                                                   increment_seconds=3))
    assert (7, 3) in manager._queue
    drain(manager, room)
    assert (7, 3) not in manager._queue
    assert manager.queue_depth == 0


async def test_pairing_removes_the_emptied_bucket(manager):
    """Pairing pops the waiting room out of its bucket; the leftover empty list
    must go too."""
    await manager.enqueue(**_enqueue_kwargs("alice", time_minutes=7))
    await manager.enqueue(**_enqueue_kwargs("bob", time_minutes=7))
    assert manager._queue == {}


async def test_cancel_wait_removes_the_emptied_bucket(manager):
    room = await manager.enqueue(**_enqueue_kwargs("alice", time_minutes=7))
    await manager.cancel_wait(room.room_id, session_token="tok-alice")
    assert manager._queue == {}


@pytest.mark.parametrize("coin, bob_color, alice_color",
                         [(0, "white", "black"), (1, "black", "white")])
async def test_two_shrugs_are_settled_by_the_coin_and_still_split_the_colours(
        manager, monkeypatch, coin, bob_color, alice_color):
    """Two random preferences are the one pairing left to chance; whichever way
    the coin lands, the arriving player takes it and the waiter gets the other."""
    await manager.enqueue(**_enqueue_kwargs("alice", side_preference="random"))
    monkeypatch.setattr(rooms_module.random, "choice", lambda seq: seq[coin])
    room = await manager.enqueue(**_enqueue_kwargs("bob", side_preference="random"))
    assert room.color_of("bob") == bob_color
    assert room.color_of("alice") == alice_color


async def _paired(manager, **overrides):
    """Alice on white, Bob on black, on whatever time control the overrides set."""
    await manager.enqueue(**_enqueue_kwargs("alice", side_preference="white", **overrides))
    return await manager.enqueue(**_enqueue_kwargs("bob", side_preference="black",
                                                   **overrides))


def _play(room, *plies):
    """Put real plies on the board and count them the way the move handler does."""
    for frm, to in plies:
        assert room.backend.try_move(square_from_coord(frm), square_from_coord(to)).legal
        room.plies_ever += 1


def _lookups(manager, uuid):
    unstarted = manager.unstarted_room_for(uuid)
    in_progress = manager.in_progress_room_for(uuid)
    assert unstarted is None or in_progress is None, \
        "a player is never in an unstarted and an in-progress game at once"
    return unstarted, in_progress


async def test_unstarted_room_for_matches_only_paired_unfinished_unmoved_rooms(manager):
    """The new-search abort keys on this lookup, so it has to be exactly the
    paired, unfinished rooms nobody has moved in -- and never overlap the
    in-progress lookup that forfeits a game instead."""
    assert _lookups(manager, "alice") == (None, None)
    queued = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert _lookups(manager, "alice") == (None, None), "a queued waiter is not in a game"
    room = await manager.enqueue(**_enqueue_kwargs("bob"))
    assert room is queued
    for uuid in ("alice", "bob"):
        assert _lookups(manager, uuid) == (room, None)
    room.first_move_at = 1.0
    unstarted, in_progress = _lookups(manager, "alice")
    assert unstarted is None and in_progress is not None and in_progress[0] is room
    manager.finalize_result(room.room_id, "checkmate", "white")
    assert _lookups(manager, "alice") == (None, None), "a finished game is neither"
    assert manager.reset_for_rematch(room.room_id) is True
    assert _lookups(manager, "bob") == (room, None), "a restarted rematch is unstarted"
    manager.drop_room_now(room.room_id)
    assert _lookups(manager, "bob") == (None, None)


async def test_unstarted_seat_by_token_needs_a_seat_token_in_that_very_room(manager):
    """The cancel-versus-pairing abort is only ever triggered by the seat's own
    token: a room id with somebody else's token, or a token from another room,
    finds nothing."""
    room = await _paired(manager)
    await manager.enqueue(**_enqueue_kwargs("carol", time_minutes=7))
    other = await manager.enqueue(**_enqueue_kwargs("dave", time_minutes=7))
    found = manager.unstarted_seat_by_token(room.room_id, "tok-alice")
    assert found is not None
    assert found[0] is room and found[1] is room.white
    found = manager.unstarted_seat_by_token(room.room_id, "tok-bob")
    assert found is not None and found[1] is room.black
    assert manager.unstarted_seat_by_token(room.room_id, "bogus") is None
    assert manager.unstarted_seat_by_token(room.room_id, "tok-carol") is None
    assert manager.unstarted_seat_by_token(other.room_id, "tok-alice") is None
    assert manager.unstarted_seat_by_token("no-such-room", "tok-alice") is None
    room.first_move_at = 1.0
    assert manager.unstarted_seat_by_token(room.room_id, "tok-alice") is None, \
        "a game somebody has moved in cannot be cancelled away"
    room.first_move_at = None
    manager.finalize_result(room.room_id, "aborted")
    assert manager.unstarted_seat_by_token(room.room_id, "tok-alice") is None


async def test_unstarted_seat_by_token_ignores_a_room_still_waiting(manager):
    """A queued room is the ordinary cancel's business, not the abort's."""
    queued = await manager.enqueue(**_enqueue_kwargs("alice"))
    assert manager.unstarted_seat_by_token(queued.room_id, "tok-alice") is None


@pytest.mark.parametrize(
    "minutes, plies, expected",
    [
        pytest.param(1, 0, (Reason.ABORTED, 30.0), id="bullet_ply_zero_halves"),
        pytest.param(1, 1, (Reason.ABORTED, 30.0), id="bullet_ply_one_halves"),
        pytest.param(1, 2, (Reason.RESIGNATION, IDLE_RESIGN_SECONDS),
                     id="bullet_resign_window_keeps_its_length"),
        pytest.param(1, 3, None, id="bullet_ply_three_disarmed"),
        pytest.param(3, 0, (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS),
                     id="blitz_ply_zero_full"),
        pytest.param(5, 1, (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS),
                     id="blitz_ply_one_full"),
        pytest.param(5, 2, (Reason.RESIGNATION, IDLE_RESIGN_SECONDS),
                     id="blitz_resign_window"),
        pytest.param(180, 1, (Reason.ABORTED, FIRST_MOVE_ABORT_SECONDS),
                     id="longest_ply_one_full"),
    ],
)
def test_idle_window_is_fitted_to_the_time_control(minutes, plies, expected):
    """The abort window is min(60 s, half the starting clock): a 1-minute game
    aborts after 30 s, so the abort is always reachable before any flag, while
    3 minutes and longer keep the full minute. The resign window never shrinks."""
    room = _bare_room(time_minutes=minutes)
    room.plies_ever = plies
    assert room.idle_window() == expected


async def test_a_bullet_abort_window_runs_out_at_thirty_seconds(manager, clock):
    room = await _paired(manager, time_minutes=1)
    assert room.idle_since == 0.0
    assert room.idle_remaining(0.0) == 30.0
    assert room.idle_timeout_reason(29.9) is None
    assert room.idle_timeout_reason(30.0) == Reason.ABORTED


async def test_running_backend_only_from_the_first_move_on(manager, clock):
    """The one predicate the sweep and /resume tick through: a fresh pairing is
    not charged, while a board taken all the way back still is (the takeback
    re-anchors the clock, so only time since the rewind is charged)."""
    assert _bare_room().running_backend() is None, "no board, no clock"
    room = await _paired(manager)
    assert room.running_backend() is None, "nobody has moved yet"
    room.first_move_at = clock()
    assert room.running_backend() is room.backend, "stamped first move"
    _play(room, ("e2", "e4"))
    assert room.running_backend() is room.backend
    room.backend.undo()
    assert room.backend.move_history == []
    assert room.running_backend() is room.backend, "an empty board after a takeback runs"
    _play(room, ("e2", "e4"))
    room.first_move_at = None
    assert room.running_backend() is None, "moves on a board with no first-move stamp"


async def test_running_backend_keeps_a_flagged_clock_running_so_the_flag_settles(
        manager, clock):
    """No flagged term: a flag latched outside the sweep (a /resume tick) must
    still reach the sweep's game_result and finalize as a timeout."""
    room = await _paired(manager, time_minutes=1)
    room.first_move_at = clock()
    _play(room, ("e2", "e4"), ("e7", "e5"))
    clock.advance(70)
    room.backend.tick_clock()
    assert room.backend.clock.flagged is not None
    assert room.running_backend() is room.backend


async def test_running_backend_is_none_for_a_board_without_a_clock(manager, clock):
    room = await _paired(manager)
    room.backend = Backend()
    room.backend.new_game()
    room.first_move_at = clock()
    _play(room, ("e2", "e4"))
    assert room.backend.clock is None
    assert room.running_backend() is None


async def _ply_two_after_a_slow_first_move(manager, clock, minutes, think):
    """White thinks `think` seconds over the first move, black replies at once:
    the ply-2 resign window opens with white's clock at minutes*60 - think."""
    room = await _paired(manager, time_minutes=minutes)
    clock.advance(think)
    _play(room, ("e2", "e4"))
    room.first_move_at = clock()
    _play(room, ("e7", "e5"))
    room.mark_idle_activity(clock())
    return room


async def test_the_resign_badge_is_capped_at_a_clock_that_runs_out_first(manager, clock):
    """1+0 after a 40 s first move: white has 20 s but the resign window 60 s.
    The shown countdown follows the clock and reaches zero with the flag, while
    the window itself -- what the sweep ends the game on -- stays uncapped."""
    room = await _ply_two_after_a_slow_first_move(manager, clock, 1, 40)
    start = clock()
    assert room.idle_window() == (Reason.RESIGNATION, IDLE_RESIGN_SECONDS)
    assert room.idle_display_remaining(start) == pytest.approx(20.0)
    assert room.idle_display_remaining(start + 10) == pytest.approx(10.0)
    assert room.idle_remaining(start + 10) == pytest.approx(50.0)
    assert room.idle_display_remaining(start + 20) == 0.0
    assert room.idle_display_remaining(start + 25) == 0.0, "never below zero"
    assert room.idle_timeout_reason(start + 20) is None, "the outcome is not capped"
    assert room.backend.clock.white_remaining == pytest.approx(20.0), \
        "reading the cap never ticks the clock"


async def test_the_resign_badge_is_not_capped_when_the_clock_outlasts_it(manager, clock):
    room = await _ply_two_after_a_slow_first_move(manager, clock, 5, 40)
    start = clock()
    assert room.idle_display_remaining(start) == IDLE_RESIGN_SECONDS
    assert room.idle_display_remaining(start + 10) == room.idle_remaining(start + 10)


async def test_an_abort_badge_is_never_capped_by_the_clock(manager, clock):
    """Only a resign window reads the clock. Even a clock forced below the abort
    window leaves the abort countdown as it is."""
    room = await _paired(manager, time_minutes=1)
    room.first_move_at = clock()
    _play(room, ("e2", "e4"))
    room.mark_idle_activity(clock())
    room.backend.clock.black_remaining = 5.0
    assert room.idle_window() == (Reason.ABORTED, 30.0)
    assert room.idle_display_remaining(clock()) == 30.0


async def test_the_shown_countdown_is_none_without_a_window_and_uncapped_without_a_board(
        manager, clock):
    room = await _paired(manager)
    room.mark_idle_activity(None)
    assert room.idle_display_remaining(clock()) is None
    bare = _bare_room()
    bare.plies_ever = 2
    bare.idle_since = 0.0
    assert bare.idle_display_remaining(10.0) == bare.idle_remaining(10.0) == 50.0


@pytest.mark.parametrize(
    "close",
    [
        pytest.param(lambda m, clock, room: m.release_for_new_game("alice"),
                     id="left_and_searched"),
        pytest.param(lambda m, clock, room: m.drop_room_now(room.room_id),
                     id="declined"),
        pytest.param(lambda m, clock, room: (clock.advance(REMATCH_IDLE_SECONDS),
                                             m.gc_finished_rooms()),
                     id="window_expired"),
    ],
)
async def test_a_new_pairing_of_the_same_players_starts_the_series_at_zero(
        manager, clock, close):
    """Deck #98, pinned: a series lives only inside one room's rematch chain.
    However the old room ended, the same two players matched again get a fresh
    room, a 0-0 series and a start frame that says it is not a rematch."""
    room = await _paired(manager)
    room.plies_ever = 10
    manager.finalize_result(room.room_id, "checkmate", "white")
    assert room.score_for("white") == 1.0
    close(manager, clock, room)
    assert manager.get(room.room_id) is None
    fresh = await _paired(manager)
    assert fresh is not room and fresh.room_id != room.room_id
    assert fresh.series_scores == {}
    assert fresh.is_rematch is False
    for color in ("white", "black"):
        start = game_start_message(fresh, color, clock())
        assert start.white_score == 0.0 and start.black_score == 0.0
        assert start.rematch is False


async def test_a_rematch_series_accumulates_over_three_games_through_the_swaps(
        manager, clock):
    """The other half of the pin: only reset_for_rematch carries a series, and
    it keeps growing across games while the colours swap underneath it."""
    room = await _paired(manager)
    rid = room.room_id
    room.plies_ever = 10
    manager.finalize_result(rid, "checkmate", "white")
    assert manager.reset_for_rematch(rid) is True
    assert room.color_of("alice") == "black"
    start = game_start_message(room, "black", clock())
    assert (start.white_score, start.black_score, start.rematch) == (0.0, 1.0, True)
    room.plies_ever = 10
    manager.finalize_result(rid, "draw_repetition")
    assert manager.reset_for_rematch(rid) is True
    assert room.color_of("alice") == "white"
    start = game_start_message(room, "white", clock())
    assert (start.white_score, start.black_score, start.rematch) == (1.5, 0.5, True)
    room.plies_ever = 10
    manager.finalize_result(rid, "resignation", "white")
    assert manager.reset_for_rematch(rid) is True
    assert room.series_scores == {"alice": 2.5, "bob": 0.5}
    start = game_start_message(room, "white", clock())
    assert (start.white_score, start.black_score) == (0.5, 2.5)
