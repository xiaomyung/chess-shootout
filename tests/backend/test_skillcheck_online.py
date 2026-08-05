"""The pure, server-importable online adjudication layer (chessshootout/skillcheck/
online.py) that both the authoritative server and the client build on: the single
challenge_from() both sides render/adjudicate from, server-secret selection,
value_diff parity, the full-RTT + ms-quantized shot adjudication, the shared human
floor applied to every kind, the 5s deadline as a hard ceiling, and the rtt-credit
session-min/cap policy. These are the security-critical primitives, so each property
is pinned independently.
"""

import pytest

from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.skillcheck import online
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.combo import (
    COMBO_MIN_INTER_PRESS_MS, COMBO_SERVER_MIN_INTER_PRESS_MS, ComboChallenge)
from chessshootout.skillcheck.mole import (
    MOLE_MAX_WHIFFS, MOLE_MIN_INTER_SHOT_MS, MoleChallenge)
from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts
from chessshootout.skillcheck import wheel
from chessshootout.skillcheck.wheel import WheelChallenge, period_for_diff
from tests.helpers import BLACK, K, P, Q, WHITE, make_backend, piece, sq

WHEEL = SkillCheckKind.WHEEL
AIM = SkillCheckKind.AIM
WHACK = SkillCheckKind.WHACK
COMBO = SkillCheckKind.COMBO
NONE = SkillCheckKind.NONE
FIRE_KINDS = (WHEEL, AIM, WHACK, COMBO)


def test_challenge_from_wheel_uses_value_diff_scaled_period():
    ch = online.challenge_from(WHEEL, "s", value_diff=9)
    assert isinstance(ch, WheelChallenge)
    assert ch.period_ms == pytest.approx(period_for_diff(9))


def test_challenge_from_aim_threads_value_diff():
    ch = online.challenge_from(AIM, "s", value_diff=5)
    assert isinstance(ch, AimChallenge)
    assert ch == AimChallenge.from_seed("s", 5)


def test_challenge_from_is_deterministic_for_seed_and_diff():
    a = online.challenge_from(WHEEL, "seed-x", 4)
    b = online.challenge_from(WHEEL, "seed-x", 4)
    assert a == b


def test_challenge_from_none_kind_is_none():
    assert online.challenge_from(NONE, "s", 0) is None


def test_value_diff_capture_is_capturer_minus_captured():
    facts = TriggerFacts(is_capture=True, capturer_value=1, captured_value=9)
    assert online.value_diff_for(facts) == -8


def test_value_diff_promotion_scores_as_a_pawn_capturing_the_promoted_piece():
    facts = TriggerFacts(is_promotion=True)
    pawn = PIECE_VALUES[PieceType.PAWN]
    assert online.value_diff_for(facts, "q") == pawn - PIECE_VALUES[PieceType.QUEEN]
    assert online.value_diff_for(facts, "q") == -8, "queen promotion is as easy as pawn x queen"
    assert online.value_diff_for(facts, "n") == pawn - PIECE_VALUES[PieceType.KNIGHT]
    assert online.value_diff_for(facts, "n") == -2, "knight underpromotion is a bit harder"


def test_value_diff_promotion_with_no_letter_defaults_to_queen():
    facts = TriggerFacts(is_promotion=True)
    assert online.value_diff_for(facts, None) == online.value_diff_for(facts, "q") == -8, \
        "an omitted promotion scores as the applied queen, not pawn-0=+1"


def test_promotion_takes_precedence_over_the_landing_capture_for_value():
    facts = TriggerFacts(is_capture=True, capturer_value=1, captured_value=5, is_promotion=True)
    assert online.value_diff_for(facts, "q") == -8, \
        "a capturing promotion scores as the piece it promotes to, not the piece it lands on"


def test_value_diff_quiet_move_is_zero():
    assert online.value_diff_for(TriggerFacts()) == 0


def test_promotion_value_drives_an_easy_slow_needle():
    diff = online.value_diff_for(TriggerFacts(is_promotion=True), "q")
    assert diff < 0
    assert period_for_diff(diff) > period_for_diff(0), \
        "promoting to a queen spins slower (easier) -- the same as a pawn taking a queen"


def test_promo_value_maps_chars_through_piece_values():
    assert online.promo_value("r") == PIECE_VALUES[PieceType.ROOK]
    assert online.promo_value(None) == 0
    assert online.promo_value("x") == 0


def _qxp():
    return make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    })


def test_select_kind_is_deterministic_for_a_secret():
    backend = _qxp()
    a = online.select_kind("secret", 0, backend, sq(4, 3), sq(3, 3), set())
    b = online.select_kind("secret", 0, backend, sq(4, 3), sq(3, 3), set())
    assert a == b and a in FIRE_KINDS


def test_select_kind_differs_by_secret():
    backend = _qxp()
    kinds = {online.select_kind("k{}".format(i), 0, backend, sq(4, 3), sq(3, 3), set())
             for i in range(120)}
    assert kinds == set(FIRE_KINDS), "different secrets sweep every capture outcome"


def test_select_kind_varies_with_ply_index():
    # the ply index is part of the roll key: the SAME secret/move on different plies
    # genuinely re-rolls the kind. A bug dropping ply_index from move_roll_key would
    # collapse this to a single constant kind for the whole game.
    backend = _qxp()
    kinds = {online.select_kind("s", p, backend, sq(4, 3), sq(3, 3), set())
             for p in range(120)}
    assert kinds == set(FIRE_KINDS), "the ply perturbs the roll -- every kind appears over a game"


def test_select_kind_unpredictable_without_the_secret():
    backend = _qxp()
    server = online.select_kind("server-secret", 7, backend, sq(4, 3), sq(3, 3), set())
    guesses = {online.select_kind("guess{}".format(i), 7, backend, sq(4, 3), sq(3, 3), set())
               for i in range(200)}
    assert len(guesses) > 1, "a client guessing the secret cannot pin the kind"
    assert server in FIRE_KINDS


def test_select_kind_locked_move_is_none():
    backend = _qxp()
    locks = {(sq(4, 3), sq(3, 3))}
    assert online.select_kind("s", 0, backend, sq(4, 3), sq(3, 3), locks) == NONE


def test_select_kind_two_legal_one_locked_is_forced_none():
    backend = make_backend({
        sq(7, 0): piece(K, WHITE), sq(5, 2): piece(K, BLACK), sq(1, 7): piece(P, BLACK),
    })
    locks = {(sq(7, 0), sq(6, 0))}
    assert online.select_kind("s", 0, backend, sq(7, 0), sq(7, 1), locks) == NONE


def _always_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def _never_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=0.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def test_adjudicated_elapsed_uses_the_client_value_when_physically_plausible():
    e = online.adjudicated_elapsed_ms(client_elapsed_ms=380.4, recv_ms=1500.0, start_ms=1000.0)
    assert e == 380 and isinstance(e, int), "honest play is judged at exactly what the client saw"


def test_adjudicated_elapsed_floors_at_zero():
    assert online.adjudicated_elapsed_ms(0.0, recv_ms=1000.0, start_ms=1000.0) == 0


def test_shot_below_human_floor_never_wins_either_kind():
    floor = int(online.SKILLCHECK_HUMAN_FLOOR_MS)
    assert online.shot_wins(WHEEL, _always_arc(), floor - 1) is False
    aim = AimChallenge.from_seed("a", 0)
    assert online.shot_wins(AIM, aim, floor - 1, miss_count=0) is False


def test_shot_at_floor_in_arc_wins():
    floor = int(online.SKILLCHECK_HUMAN_FLOOR_MS)
    assert online.shot_wins(WHEEL, _always_arc(), floor) is True


def test_shot_outside_arc_fails():
    assert online.shot_wins(WHEEL, _never_arc(), 300) is False


def test_shot_past_deadline_never_wins():
    late = int(online.SKILLCHECK_DEADLINE_MS) + 1
    assert online.shot_wins(WHEEL, _always_arc(), late) is False


def test_aim_shot_uses_miss_count_geometry():
    aim = AimChallenge.from_seed("aimseed", 0)
    elapsed = next(e for e in range(120, 5000, 5) if aim.on_target(e, 0))
    assert online.shot_wins(AIM, aim, elapsed, miss_count=0) is True


def test_shot_wins_uses_the_shrinking_arc_not_the_full_arc():
    # a fixed needle angle that sits INSIDE the full 60-degree arc but OUTSIDE the
    # arc once it has shrunk after several rotations must read as a LOSS -- proving
    # shot_wins adjudicates via in_arc_at (time-shrunk) and not the static in_arc.
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=60.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    elapsed = 4084  # ~4 rotations in: needle ~30deg, full arc 60, shrunk arc ~19
    needle = ch.needle_deg(elapsed)
    assert ch.in_arc(needle) is True, "the needle is inside the original 60-degree arc"
    assert ch.in_arc_at(needle, elapsed) is False, "but outside the arc once it has shrunk"
    assert online.shot_wins(WHEEL, ch, elapsed) is False, "so the shot loses on the shrunk arc"
    # sanity: an EARLY pass through the same arc, before it shrinks, still wins.
    early = next(e for e in range(int(online.SKILLCHECK_HUMAN_FLOOR_MS), 200)
                 if ch.in_arc(ch.needle_deg(e)))
    assert online.shot_wins(WHEEL, ch, early) is True


def test_is_past_deadline_boundary():
    assert online.is_past_deadline(online.SKILLCHECK_DEADLINE_MS) is False
    assert online.is_past_deadline(online.SKILLCHECK_DEADLINE_MS + 0.1) is True


def test_a_too_late_claim_is_clamped_down_to_the_arrival_time():
    # the player cannot have perceived MORE elapsed than the shot physically took to arrive
    assert online.adjudicated_elapsed_ms(9999.0, recv_ms=1500.0, start_ms=1000.0) == 500


def test_a_too_early_claim_is_clamped_up_to_the_lag_bound():
    # raw = 1000, bound 200 -> earliest plausible perceived elapsed is raw - bound = 800
    assert online.adjudicated_elapsed_ms(0.0, recv_ms=2000.0, start_ms=1000.0) == 800


def test_the_manipulable_window_is_exactly_the_lag_bound():
    lo = online.adjudicated_elapsed_ms(-1e9, recv_ms=5000.0, start_ms=0.0)
    hi = online.adjudicated_elapsed_ms(1e9, recv_ms=5000.0, start_ms=0.0)
    assert hi - lo == int(online.SKILLCHECK_LAG_BOUND_MS), \
        "a modded client can shift its effective time by at most the lag bound"


def test_a_forged_early_claim_cannot_buy_a_sub_floor_win():
    effective = online.adjudicated_elapsed_ms(0.0, recv_ms=119.0, start_ms=0.0)
    assert effective == 0
    assert online.shot_wins(WHEEL, _always_arc(), effective) is False, "sub-floor stays a loss"


def test_adjudicated_elapsed_truncates_toward_floor_loss():
    # int() truncation straddles the human floor: a 119.9ms render becomes 119
    # (a sub-floor LOSS), while exactly 120.0 becomes 120 (at the floor, eligible).
    # recv-start is kept tight (200ms) so the honest client value is what's judged,
    # not the raw-bound clamp.
    below = online.adjudicated_elapsed_ms(119.9, recv_ms=200.0, start_ms=0.0)
    at = online.adjudicated_elapsed_ms(120.0, recv_ms=200.0, start_ms=0.0)
    assert below == 119 and at == 120
    assert below < online.SKILLCHECK_HUMAN_FLOOR_MS <= at
    assert online.shot_wins(WHEEL, _always_arc(), below) is False, "119 truncates into a loss"
    assert online.shot_wins(WHEEL, _always_arc(), at) is True, "120 clears the floor"


def test_effective_elapsed_floors_a_forged_negative_rtt_to_zero_credit():
    # a negative (forged) half-rtt must never be CREDITED as extra time: the
    # compensation is floored to 0, so the elapsed equals the raw arrival gap.
    assert wheel.effective_elapsed_ms(1000.0, 0.0, -500.0) == pytest.approx(1000.0)
    # contrast: an honest positive rtt within the cap is subtracted as a credit.
    assert wheel.effective_elapsed_ms(1000.0, 0.0, 150.0) == pytest.approx(850.0)


def test_aim_piece_scale_no_crash_on_negative_elapsed():
    aim = AimChallenge.from_seed("neg", 0)
    assert aim.piece_scale(-1000.0, 0) == aim.piece_scale(0.0, 0)
    assert isinstance(aim.on_target(-5.0, 0), bool)
    assert isinstance(aim.is_expired(-5.0, 0), bool)


@pytest.mark.parametrize("initial_seconds, expected", [
    (300, 5000.0),     # 5+0: 10% = 30s, base 5s wins
    (1800, 5000.0),    # 30+0: 10% = 180s, base 5s wins
    (40, 4000.0),      # 40s game: 10% = 4s binds below the base
    (20, 2000.0),      # 20s game: 10% = 2s
    (0, 5000.0),       # no clock -> the base deadline
])
def test_skillcheck_deadline_ms_is_min_of_base_and_tenth_of_tc(initial_seconds, expected):
    assert online.skillcheck_deadline_ms(initial_seconds) == expected


def test_skillcheck_deadline_never_exceeds_the_base_and_shrinks_for_fast_tc():
    assert online.skillcheck_deadline_ms(600) == online.SKILLCHECK_DEADLINE_MS
    assert online.skillcheck_deadline_ms(30) < online.SKILLCHECK_DEADLINE_MS
    assert online.skillcheck_deadline_ms(30) == 30 * 0.10 * 1000.0


def test_is_past_deadline_honors_a_capped_deadline():
    assert online.is_past_deadline(3500, deadline_ms=3000.0) is True
    assert online.is_past_deadline(3500) is False


def test_shot_past_the_capped_deadline_never_wins():
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=800.0,
                        start_angle_deg=0.0)
    assert online.shot_wins(SkillCheckKind.WHEEL, ch, 3500, deadline_ms=3000.0) is False
    assert online.shot_wins(SkillCheckKind.WHEEL, ch, 3500) is True


def test_challenge_from_whack_builds_a_mole_challenge_threading_all_params():
    ch = online.challenge_from(WHACK, "s", value_diff=3, deadline_ms=3000.0, captured_value=5)
    assert isinstance(ch, MoleChallenge)
    assert ch == MoleChallenge.from_seed("s", 3, 3000.0, 5)
    assert ch.deadline_ms == 3000.0


def test_challenge_from_combo_builds_a_combo_challenge_threading_all_params():
    ch = online.challenge_from(COMBO, "s", value_diff=3, deadline_ms=3000.0, captured_value=6)
    assert isinstance(ch, ComboChallenge)
    assert ch == ComboChallenge.from_seed("s", 3, 3000.0, 6)
    assert ch.deadline_ms == 3000.0


def test_challenge_from_wheel_and_aim_ignore_the_new_defaulted_params():
    # regression: the new deadline_ms/captured_value must NOT leak into the wheel/aim
    # branches. AIM's own from_seed default deadline is load-bearing geometry, so an
    # old-style call and a new-style call passing explicit kwargs must build the SAME
    # challenge -- byte-identical to the pre-change construction.
    wheel_baseline = WheelChallenge.from_seed("seed-x", period_ms=period_for_diff(7))
    aim_baseline = AimChallenge.from_seed("seed-x", 7)
    assert online.challenge_from(WHEEL, "seed-x", 7) == wheel_baseline
    assert online.challenge_from(WHEEL, "seed-x", 7, deadline_ms=1234.0,
                                 captured_value=9) == wheel_baseline
    assert online.challenge_from(AIM, "seed-x", 7) == aim_baseline
    assert online.challenge_from(AIM, "seed-x", 7, deadline_ms=1234.0,
                                 captured_value=9) == aim_baseline


def _mole_and_holes():
    ch = online.challenge_from(WHACK, "moleseed", value_diff=0, captured_value=3)
    holes = tuple((row, 0) for row in range(ch.hole_count))
    up_ms = next(e for e in range(120, 5000) if ch.pop_up_at(e) is not None)
    idx = ch.pop_up_at(up_ms)
    row, col = holes[ch.pops[idx].hole]
    return ch, holes, up_ms, idx, (row + 0.5, col + 0.5)


def test_shot_wins_whack_center_hit_inside_an_up_window():
    ch, holes, up_ms, _idx, center = _mole_and_holes()
    assert online.shot_wins(WHACK, ch, up_ms, target=center, hole_squares=holes) is True


def test_shot_wins_whack_same_position_between_pops_is_a_miss():
    ch, holes, _up, _idx, center = _mole_and_holes()
    between = next(e for e in range(120, 5000) if ch.pop_up_at(e) is None)
    assert online.shot_wins(WHACK, ch, between, target=center, hole_squares=holes) is False


def test_shot_wins_whack_dedups_the_already_hit_pop():
    ch, holes, up_ms, idx, center = _mole_and_holes()
    assert online.shot_wins(WHACK, ch, up_ms, target=center, hole_squares=holes,
                            last_hit_pop=idx) is False


def test_shot_wins_whack_needs_both_target_and_hole_squares():
    ch, holes, up_ms, _idx, center = _mole_and_holes()
    assert online.shot_wins(WHACK, ch, up_ms, hole_squares=holes) is False
    assert online.shot_wins(WHACK, ch, up_ms, target=center) is False


def test_shot_wins_whack_respects_the_shared_floor_and_deadline():
    ch, holes, _up, _idx, center = _mole_and_holes()
    late = int(online.SKILLCHECK_DEADLINE_MS) + 1
    assert online.shot_wins(WHACK, ch, 100, target=center, hole_squares=holes) is False
    assert online.shot_wins(WHACK, ch, late, target=center, hole_squares=holes) is False


def _combo():
    return online.challenge_from(COMBO, "comboseed", value_diff=0, captured_value=3)


def test_shot_wins_combo_correct_wrong_and_missing_direction():
    ch = _combo()
    first = ch.prompts[0]
    wrong = next(d for d in ("up", "down", "left", "right") if d != first)
    assert online.shot_wins(COMBO, ch, 200, progress=0, direction=first) is True
    assert online.shot_wins(COMBO, ch, 200, progress=0, direction=wrong) is False
    assert online.shot_wins(COMBO, ch, 200, progress=0, direction=None) is False


def test_shot_wins_combo_respects_the_shared_floor_and_deadline():
    ch = _combo()
    first = ch.prompts[0]
    late = int(online.SKILLCHECK_DEADLINE_MS) + 1
    assert online.shot_wins(COMBO, ch, 100, progress=0, direction=first) is False
    assert online.shot_wins(COMBO, ch, late, progress=0, direction=first) is False


def test_hits_required_dispatches_by_kind():
    assert online.hits_required(WHEEL, _always_arc()) == 1
    assert online.hits_required(AIM, AimChallenge.from_seed("a", 0)) == 1
    mole = online.challenge_from(WHACK, "s", 0, captured_value=3)
    assert online.hits_required(WHACK, mole) == mole.hits_required
    combo = online.challenge_from(COMBO, "s", 0, captured_value=3)
    assert online.hits_required(COMBO, combo) == combo.prompt_count


def test_check_expired_wheel_is_always_false():
    assert online.check_expired(WHEEL, _always_arc(), 10000) is False


def test_check_expired_aim_matches_aim_expired():
    aim = AimChallenge.from_seed("a", 0)
    for elapsed, miss in [(0, 0), (4000, 0), (10000, 3)]:
        assert online.check_expired(AIM, aim, elapsed, miss) \
            == online.aim_expired(aim, elapsed, miss)


def test_check_expired_whack_flips_when_quota_becomes_unreachable():
    mole = online.challenge_from(WHACK, "s", 0, captured_value=3)
    assert online.check_expired(WHACK, mole, 0.0, progress=0) is False
    late = mole.pops[-1].t_down_ms + 200.0
    assert online.check_expired(WHACK, mole, late, progress=0) is True


def test_check_expired_whack_flips_at_max_whiffs_even_mid_schedule():
    # the whiff cap is the second, independent death condition: the schedule can
    # still be perfectly winnable (quota reachable, every pop ahead) and the check
    # is dead anyway once three misses are spent. This is what closes the
    # spam-every-hole exploit at every server surface through the one predicate.
    mole_ch = online.challenge_from(WHACK, "s", 0, captured_value=3)
    early = mole_ch.pops[0].t_up_ms
    assert mole_ch.quota_unreachable(early, 0) is False, "the schedule alone is winnable"
    assert online.check_expired(WHACK, mole_ch, early,
                                miss_count=MOLE_MAX_WHIFFS - 1, progress=0) is False
    assert online.check_expired(WHACK, mole_ch, early,
                                miss_count=MOLE_MAX_WHIFFS, progress=0) is True
    assert online.check_expired(WHACK, mole_ch, early,
                                miss_count=MOLE_MAX_WHIFFS + 2, progress=0) is True


def test_check_expired_whack_either_death_arm_suffices():
    mole_ch = online.challenge_from(WHACK, "s", 0, captured_value=3)
    late = mole_ch.pops[-1].t_down_ms + 200.0
    assert online.check_expired(WHACK, mole_ch, late, miss_count=0, progress=0) is True, \
        "quota death still fires with zero whiffs"
    assert online.check_expired(WHACK, mole_ch, 0.0, miss_count=MOLE_MAX_WHIFFS,
                                progress=0) is True, \
        "whiff death still fires with the whole schedule ahead"
    assert online.check_expired(WHACK, mole_ch, 0.0, miss_count=0, progress=0) is False


def test_check_expired_combo_flips_at_max_wrongs():
    combo = online.challenge_from(COMBO, "s", 0, captured_value=3)
    assert online.check_expired(COMBO, combo, 200, miss_count=2) is False
    assert online.check_expired(COMBO, combo, 200, miss_count=3) is True


def test_min_inter_input_ms_by_kind():
    assert online.min_inter_input_ms(WHEEL) == 0.0
    assert online.min_inter_input_ms(AIM) == 0.0
    assert online.min_inter_input_ms(WHACK) == MOLE_MIN_INTER_SHOT_MS
    assert online.min_inter_input_ms(COMBO) == COMBO_SERVER_MIN_INTER_PRESS_MS


def test_server_press_gate_sits_below_the_client_press_gap():
    # Both gates measure the same inter-press spacing on different clocks. The
    # elapsed clamp lets network jitter compress a legit gap by up to
    # SKILLCHECK_LAG_BOUND_MS on the server side, so a server gate at or above
    # the client's own minimum silently drops presses the client accepted and
    # desyncs progress. The server threshold must stay strictly below.
    assert COMBO_SERVER_MIN_INTER_PRESS_MS < COMBO_MIN_INTER_PRESS_MS
