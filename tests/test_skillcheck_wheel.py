"""The timing Wheel (DBD-style needle + single correct arc, binary land/fail).

Geometry is derived deterministically from a seed (so server and client render
the identical dial), but the server alone adjudicates from its own receive clock
minus a capped half-RTT compensation -- a laggy honest tap is credited fairly, a
lag-switched one cannot widen the window, and an impossibly-early tap is rejected.
Difficulty is exactly the arc fraction of the circle.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from chessshootout.skillcheck import aim, online, wheel
from chessshootout.skillcheck.wheel import WheelChallenge


# ---- needle speed scales with capturer-vs-victim material ------------------

def test_needle_speed_mult_directions():
    assert wheel.needle_speed_mult(0) == pytest.approx(1.0)
    assert wheel.needle_speed_mult(8) == pytest.approx(1.4)
    assert wheel.needle_speed_mult(-8) == pytest.approx(0.6)


def test_strong_eats_weak_spins_faster_weak_eats_strong_slower():
    base = wheel.WHEEL_PERIOD_MS
    assert wheel.period_for_diff(8) < base, "queen takes pawn -> faster needle -> harder"
    assert wheel.period_for_diff(-8) > base, "pawn takes queen -> slower needle -> easier"
    assert wheel.period_for_diff(0) == pytest.approx(base)


def test_needle_speed_stays_positive_across_chess_values():
    for diff in range(-9, 10):
        assert wheel.period_for_diff(diff) > 0.0


def test_needle_speed_mult_floors_so_the_period_never_divides_by_zero():
    # an extreme negative value_diff would otherwise drive the multiplier non-positive
    # (1 + 0.2 * -50 / 4 = -1.5) and period_for_diff would divide by zero / go negative.
    assert wheel.needle_speed_mult(-50) == pytest.approx(wheel.WHEEL_SPEED_MULT_MIN)
    assert wheel.needle_speed_mult(-1000) > 0.0, "the floor keeps the multiplier strictly positive"
    assert wheel.period_for_diff(-50) == pytest.approx(
        wheel.WHEEL_PERIOD_MS / wheel.WHEEL_SPEED_MULT_MIN), "the period stays finite at the floor"


def test_the_floor_is_below_the_real_chess_range_so_it_never_perturbs_play():
    # the clamp is a safety net, not a gameplay knob: across every real capture
    # value_diff the unclamped formula already sits above the floor, so the floor
    # changes nothing in actual play.
    floor = wheel.WHEEL_SPEED_MULT_MIN
    for diff in range(-9, 9):
        raw = 1.0 + wheel.WHEEL_SPEED_PER_DIFF * diff / wheel.WHEEL_SPEED_DIFF_DIVISOR
        assert raw > floor, "real diff {} is above the floor, never clamped".format(diff)
        assert wheel.needle_speed_mult(diff) == pytest.approx(raw)
    assert wheel.needle_speed_mult(-9) == pytest.approx(0.55), "the real minimum multiplier"


def land_recv_ms(challenge, start_ms, half_rtt_ms=0.0, target_offset_deg=None):
    if target_offset_deg is None:
        target_offset_deg = challenge.arc_width_deg / 2.0
    target_angle = (challenge.arc_start_deg + target_offset_deg) % 360.0
    sweep = (target_angle - challenge.start_angle_deg) % 360.0
    elapsed = sweep / 360.0 * challenge.period_ms
    while elapsed < wheel.WHEEL_HUMAN_FLOOR_MS:
        elapsed += challenge.period_ms
    return start_ms + elapsed + min(half_rtt_ms, wheel.WHEEL_RTT_CAP_MS)


# ---- seeded geometry -------------------------------------------------------

def test_from_seed_is_deterministic():
    a = WheelChallenge.from_seed("room-1:5")
    b = WheelChallenge.from_seed("room-1:5")
    assert a == b


def test_distinct_seeds_vary_geometry():
    arcs = {WheelChallenge.from_seed(f"s:{i}").arc_start_deg for i in range(20)}
    assert len(arcs) > 10


def test_arc_within_circle():
    for i in range(50):
        ch = WheelChallenge.from_seed(f"s:{i}")
        assert 0.0 <= ch.arc_start_deg < 360.0
        assert ch.arc_width_deg == wheel.WHEEL_ARC_DEGREES


# ---- needle motion ---------------------------------------------------------

def test_needle_starts_at_start_angle():
    ch = WheelChallenge.from_seed("x")
    assert ch.needle_deg(0.0) == pytest.approx(ch.start_angle_deg % 360.0)


def test_needle_wraps_after_one_period():
    ch = WheelChallenge.from_seed("x")
    assert ch.needle_deg(ch.period_ms) == pytest.approx(ch.needle_deg(0.0))


def test_needle_advances_monotonically_within_a_period():
    ch = WheelChallenge.from_seed("x")
    quarter = ch.needle_deg(ch.period_ms * 0.25)
    expected = (ch.start_angle_deg + 90.0) % 360.0
    assert quarter == pytest.approx(expected)


# ---- arc membership (incl. wrap-around) ------------------------------------

def test_in_arc_center_and_edges():
    ch = WheelChallenge(arc_start_deg=100.0, arc_width_deg=60.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert ch.in_arc(130.0) is True
    assert ch.in_arc(100.0) is True
    assert ch.in_arc(159.9) is True
    assert ch.in_arc(160.1) is False
    assert ch.in_arc(99.0) is False


def test_in_arc_upper_edge_is_exclusive_half_open():
    # the arc is the half-open interval [start, start+width): the exact upper edge
    # is OUT. A `<` -> `<=` regression here would silently widen every sweet-spot
    # by one boundary point on the security-critical adjudication path.
    ch = WheelChallenge(arc_start_deg=100.0, arc_width_deg=60.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert ch.in_arc(100.0) is True, "the lower edge is inclusive"
    assert ch.in_arc(160.0) is False, "start + width is the exclusive upper edge"
    assert ch.in_arc(159.99999) is True, "just inside the upper edge still counts"


def test_in_arc_handles_wraparound():
    ch = WheelChallenge(arc_start_deg=350.0, arc_width_deg=40.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert ch.in_arc(355.0) is True
    assert ch.in_arc(10.0) is True
    assert ch.in_arc(30.1) is False


# ---- server adjudication ---------------------------------------------------

def test_perfect_tap_lands():
    ch = WheelChallenge.from_seed("room:9")
    recv = land_recv_ms(ch, start_ms=10_000.0)
    assert wheel.adjudicate(ch, recv, start_ms=10_000.0) is True


def test_tap_outside_arc_fails():
    ch = WheelChallenge.from_seed("room:9")
    miss = land_recv_ms(ch, start_ms=10_000.0,
                        target_offset_deg=ch.arc_width_deg + 90.0)
    assert wheel.adjudicate(ch, miss, start_ms=10_000.0) is False


def test_half_rtt_compensation_credits_laggy_tap():
    ch = WheelChallenge.from_seed("room:42")
    half_rtt = 100.0
    recv = land_recv_ms(ch, start_ms=0.0, half_rtt_ms=half_rtt)
    assert wheel.adjudicate(ch, recv, start_ms=0.0, half_rtt_ms=half_rtt) is True
    assert wheel.adjudicate(ch, recv, start_ms=0.0, half_rtt_ms=0.0) is False


# ---- sweet-spot shrinks smoothly, not in steps -----------------------------

def test_arc_shrinks_continuously_to_a_floor():
    ch = WheelChallenge.from_seed("shrink")
    p = ch.period_ms
    assert ch.arc_width_at(0.0) == 60.0
    assert ch.arc_width_at(p * 0.25) == pytest.approx(57.5), "bleeds down mid-rotation, no step"
    assert ch.arc_width_at(p * 0.5) == pytest.approx(55.0)
    assert ch.arc_width_at(p) == pytest.approx(50.0)
    assert ch.arc_width_at(p * 2) == pytest.approx(40.0)
    assert ch.arc_width_at(p * 6) == wheel.WHEEL_ARC_MIN_DEGREES
    assert ch.arc_width_at(p * 50) == wheel.WHEEL_ARC_MIN_DEGREES


def test_arc_width_is_strictly_decreasing_until_the_floor():
    ch = WheelChallenge.from_seed("mono")
    p = ch.period_ms
    widths = [ch.arc_width_at(p * i / 20.0) for i in range(109)]
    for earlier, later in zip(widths, widths[1:]):
        assert later < earlier, "the arc bleeds down every frame; no flat steps, never widens"
    assert ch.arc_width_at(p * 6) == wheel.WHEEL_ARC_MIN_DEGREES, "and clamps at the floor"


def test_one_period_is_exactly_one_full_revolution():
    # WHEEL_PERIOD_MS is the time for the needle to sweep a full 360: pin that
    # behavioural meaning rather than restating the literal constant.
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=60.0,
                        period_ms=wheel.WHEEL_PERIOD_MS, start_angle_deg=0.0)
    assert ch.needle_deg(wheel.WHEEL_PERIOD_MS) == pytest.approx(ch.needle_deg(0.0))
    assert ch.needle_deg(wheel.WHEEL_PERIOD_MS / 4.0) == pytest.approx(90.0)
    assert ch.needle_deg(wheel.WHEEL_PERIOD_MS / 2.0) == pytest.approx(180.0)


def test_same_needle_angle_misses_after_the_arc_shrinks():
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=60.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert wheel.adjudicate(ch, recv_ms=161.0, start_ms=0.0) is True
    assert wheel.adjudicate(ch, recv_ms=1161.0, start_ms=0.0) is False


def test_rtt_compensation_is_capped():
    assert wheel.effective_elapsed_ms(1000.0, 0.0, 5000.0) == pytest.approx(
        1000.0 - wheel.WHEEL_RTT_CAP_MS)


def test_sub_human_tap_is_rejected():
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert wheel.adjudicate(ch, recv_ms=wheel.WHEEL_HUMAN_FLOOR_MS - 1.0, start_ms=0.0) is False
    assert wheel.adjudicate(ch, recv_ms=wheel.WHEEL_HUMAN_FLOOR_MS + 1.0, start_ms=0.0) is True


# ---- difficulty == arc fraction --------------------------------------------

def test_in_arc_fraction_matches_arc_width():
    ch = WheelChallenge.from_seed("frac")
    steps = 36000
    hits = sum(ch.in_arc(ch.needle_deg(ch.period_ms * i / steps)) for i in range(steps))
    assert hits / steps == pytest.approx(ch.arc_width_deg / 360.0, abs=0.002)


# ---- seeded random placement (render-only difficulty) ----------------------
# A capture can spawn the dial on a random board square instead of the capture
# square. The chance scales with the same capturer-vs-victim material the needle
# speed uses (centered 50/50, clamped 0.1..0.9), so a queen grabbing a pawn is
# usually relocated (hard to find) and a pawn taking a queen rarely is. Position
# is purely visual -- the needle/arc/timing math never reads it.

def test_random_placement_prob_centered_and_matches_capture_table():
    assert wheel.random_placement_prob(0) == pytest.approx(0.5), "knight x bishop -> 50/50"
    assert wheel.random_placement_prob(8) == pytest.approx(0.9), "queen x pawn -> usually random"
    assert wheel.random_placement_prob(-8) == pytest.approx(0.1), "pawn x queen -> rarely random"
    assert wheel.random_placement_prob(4) == pytest.approx(0.7)
    assert wheel.random_placement_prob(2) == pytest.approx(0.6)
    assert wheel.random_placement_prob(-2) == pytest.approx(0.4)
    assert wheel.random_placement_prob(-4) == pytest.approx(0.3)


def test_random_placement_prob_mirrors_the_needle_speed_slope():
    assert wheel.WHEEL_PLACEMENT_PER_DIFF == pytest.approx(
        wheel.WHEEL_SPEED_PER_DIFF / wheel.WHEEL_SPEED_DIFF_DIVISOR), "same slope as the needle"
    for diff in range(-8, 9):
        assert wheel.random_placement_prob(diff) - 0.5 == pytest.approx(
            wheel.WHEEL_PLACEMENT_PER_DIFF * diff)


def test_random_placement_prob_is_clamped_both_ends():
    assert wheel.random_placement_prob(50) == pytest.approx(wheel.WHEEL_PLACEMENT_MAX_PROB)
    assert wheel.random_placement_prob(-50) == pytest.approx(wheel.WHEEL_PLACEMENT_MIN_PROB)


def test_random_placement_prob_is_monotonic_increasing():
    probs = [wheel.random_placement_prob(d) for d in range(-12, 13)]
    for earlier, later in zip(probs, probs[1:]):
        assert later >= earlier


def test_placement_is_deterministic_for_seed_and_diff():
    first = wheel.placement_square("seed-7", 6)
    again = wheel.placement_square("seed-7", 6)
    assert first == again
    assert first is None or (len(first) == 2 and all(isinstance(v, int) for v in first))


def test_relocates_exactly_when_the_seeded_roll_is_below_the_probability():
    for i in range(300):
        seed = f"roll:{i}"
        roll = wheel._placement_floats(seed)[0]
        relocated = wheel.placement_square(seed, 0) is not None
        assert relocated == (roll < wheel.random_placement_prob(0))


def test_relocation_rate_tracks_the_probability():
    for diff, prob in [(8, 0.9), (4, 0.7), (0, 0.5), (-4, 0.3), (-8, 0.1)]:
        n = 4000
        relocated = sum(
            wheel.placement_square(f"rate:{diff}:{i}", diff) is not None for i in range(n))
        assert relocated / n == pytest.approx(prob, abs=0.03)


def test_relocated_square_is_always_on_the_board():
    for i in range(2000):
        square = wheel.placement_square(f"board:{i}", 8)
        if square is not None:
            row, col = square
            assert 0 <= row < 8 and 0 <= col < 8


def test_excluded_squares_are_never_chosen():
    excluded = {(3, 3), (4, 4), (2, 6), (0, 0)}
    for i in range(2000):
        square = wheel.placement_square(f"excl:{i}", 8, excluded)
        if square is not None:
            assert square not in excluded


def test_excluding_the_natural_pick_shifts_to_a_different_allowed_square():
    seed = next(f"shift:{i}" for i in range(1000)
                if wheel.placement_square(f"shift:{i}", 8) is not None)
    natural = wheel.placement_square(seed, 8)
    shifted = wheel.placement_square(seed, 8, excluded={natural})
    assert shifted is not None and shifted != natural


def test_no_allowed_square_means_no_relocation():
    full = {(row, col) for row in range(8) for col in range(8)}
    seed = next(f"none:{i}" for i in range(1000)
                if wheel.placement_square(f"none:{i}", 8) is not None)
    assert wheel.placement_square(seed, 8, excluded=full) is None


def test_relocations_spread_across_the_board():
    squares = {wheel.placement_square(f"spread:{i}", 8) for i in range(800)}
    squares.discard(None)
    assert len(squares) > 24


def test_board_size_bounds_the_relocated_square():
    for i in range(2000):
        square = wheel.placement_square(f"size:{i}", 8, board_size=4)
        if square is not None:
            row, col = square
            assert 0 <= row < 4 and 0 <= col < 4


def test_placement_uses_a_separate_hash_namespace_from_the_dial():
    assert wheel._placement_floats("seed-q") != wheel._seed_floats("seed-q")


# ---- the 5s deadline is single-sourced across every module -----------------
# Wheel, aim, the online adjudicator, and the wheel_view frontend constant all
# derive their time limit from one source. A future literal-copy that diverged
# any of them (e.g. a 5000 hardcoded in one place) would fail here.

def test_skillcheck_deadline_is_single_sourced_across_modules():
    from chessshootout.frontend.skillcheck.wheel_view import WHEEL_TIME_LIMIT_MS

    assert wheel.SKILLCHECK_DEADLINE_MS == online.SKILLCHECK_DEADLINE_MS
    assert aim.AIM_DEADLINE_MS == wheel.SKILLCHECK_DEADLINE_MS
    assert WHEEL_TIME_LIMIT_MS == wheel.SKILLCHECK_DEADLINE_MS
