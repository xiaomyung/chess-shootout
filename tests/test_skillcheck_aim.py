"""The Steady-Aim engine: a crosshair traces a rotating figure-8 (lemniscate of
Gerono) over the victim while the piece shrinks as the timer. A shot lands when
the crosshair CENTER is inside a circle scaled to the piece's current size --
all in NORMALISED cell-fraction units (no pixels), so the same geometry is
server-adjudicable regardless of render size. Deterministic from a seed; both
the travel and rotation speed scale with capturer-vs-victim material (the wheel's
formula). It is MULTI-shot: each miss speeds the sway + shrink (hard-capped, so
no death-spiral). The crosshair seeds onto a lobe so the first center-crossing
is a guaranteed beat away -- you cannot insta-click the instant it appears.
"""

import math

import pytest

from chessshootout.skillcheck import aim
from chessshootout.skillcheck.aim import AimChallenge


# ---- seeded geometry -------------------------------------------------------

def test_from_seed_is_deterministic():
    a = AimChallenge.from_seed("room:5", value_diff=3)
    b = AimChallenge.from_seed("room:5", value_diff=3)
    assert a == b


def test_distinct_seeds_vary_geometry():
    phases = {AimChallenge.from_seed("s:{}".format(i)).phase0 for i in range(40)}
    rotations = {AimChallenge.from_seed("s:{}".format(i)).rotation0_deg for i in range(40)}
    assert len(phases) > 20
    assert len(rotations) > 30


def test_seed_starts_on_a_lobe_not_a_crossing():
    for i in range(200):
        ch = AimChallenge.from_seed("lobe:{}".format(i))
        near = min(abs(ch.phase0 - c) for c in (0.25, 0.75))
        assert near > 0.1, "phase0 must seed onto a lobe, well clear of a crossing"


# ---- material scaling (both travel + rotation) -----------------------------

def test_strong_eats_weak_spins_and_sweeps_faster():
    base = AimChallenge.from_seed("m", value_diff=0)
    strong = AimChallenge.from_seed("m", value_diff=8)
    weak = AimChallenge.from_seed("m", value_diff=-8)
    assert strong.travel_period_ms < base.travel_period_ms < weak.travel_period_ms
    assert strong.rotation_period_ms < base.rotation_period_ms < weak.rotation_period_ms


def test_periods_stay_positive_across_chess_values():
    for diff in range(-9, 10):
        ch = AimChallenge.from_seed("p", value_diff=diff)
        assert ch.travel_period_ms > 0.0 and ch.rotation_period_ms > 0.0


# ---- figure-8 geometry: crossings at t=0.25 and 0.75 -----------------------

def test_lemniscate_crosses_center_at_quarter_and_three_quarter():
    ch = AimChallenge.from_seed("x")
    for crossing in (0.25, 0.75):
        elapsed = (crossing - ch.phase0) % 1.0 * ch.travel_period_ms
        assert ch.param_at(elapsed) == pytest.approx(crossing, abs=1e-6)
        fx, fy = ch.reticle_offset(elapsed)
        assert math.hypot(fx, fy) == pytest.approx(0.0, abs=1e-6), "crossing = dead center"


def test_offset_is_bounded_to_the_lobe_amplitude():
    ch = AimChallenge.from_seed("b")
    amp = aim.AIM_LOBE_FRACTION / 2.0
    for i in range(1000):
        fx, fy = ch.reticle_offset(i * 7.0)
        assert math.hypot(fx, fy) <= amp + 1e-9


# ---- you cannot insta-win --------------------------------------------------

def test_no_insta_win_at_appearance():
    for i in range(200):
        ch = AimChallenge.from_seed("nw:{}".format(i))
        assert ch.on_target(0.0) is False


@pytest.mark.parametrize("diff", [0, 9, -9])
def test_no_win_during_the_start_gap(diff):
    for i in range(120):
        ch = AimChallenge.from_seed("gap:{}".format(i), value_diff=diff)
        assert not any(ch.on_target(e) for e in range(0, 80, 4)), \
            "the crosshair cannot reach the piece within the opening beat"


# ---- but it IS winnable ----------------------------------------------------

def test_every_challenge_has_a_winnable_moment():
    for i in range(80):
        ch = AimChallenge.from_seed("win:{}".format(i))
        assert any(ch.on_target(e) for e in range(0, int(aim.AIM_DEADLINE_MS), 8)), \
            "the crosshair must pass through the piece while it is still big"


def test_a_centered_crossing_lands_while_the_piece_is_full():
    ch = AimChallenge.from_seed("ctr")
    elapsed = (0.25 - ch.phase0) % 1.0 * ch.travel_period_ms
    assert ch.on_target(elapsed) is True


# ---- hit radius shrinks with the piece -------------------------------------

def test_hit_radius_starts_full_and_shrinks_to_zero():
    ch = AimChallenge.from_seed("r")
    assert ch.hit_radius(0.0) == pytest.approx(aim.AIM_HIT_RADIUS_FRAC)
    assert ch.hit_radius(ch.deadline_ms * 0.5) < ch.hit_radius(0.0)
    assert ch.hit_radius(ch.deadline_ms * 0.95) < ch.hit_radius(ch.deadline_ms * 0.5)
    assert ch.hit_radius(ch.deadline_ms) == pytest.approx(0.0)


def test_same_offset_that_hits_early_misses_late():
    ch = AimChallenge.from_seed("late")
    early = (0.25 - ch.phase0) % 1.0 * ch.travel_period_ms
    late = early + ch.travel_period_ms * round(ch.deadline_ms / ch.travel_period_ms)
    assert ch.on_target(early) is True
    if late < ch.deadline_ms:
        assert ch.on_target(late) is False, "the shrunken piece slips the same crossing"


# ---- shrink curve: generous early, brutal finish ---------------------------

def test_shrink_is_generous_early_then_collapses():
    ch = AimChallenge.from_seed("shrink")
    assert ch.piece_scale(0.0) == pytest.approx(1.0)
    assert ch.piece_scale(ch.deadline_ms * 0.5) > 0.7
    assert ch.piece_scale(ch.deadline_ms * 0.9) < 0.3
    assert ch.piece_scale(ch.deadline_ms) == pytest.approx(0.0)


def test_expiry_is_the_full_shrink():
    ch = AimChallenge.from_seed("exp")
    assert ch.is_expired(ch.deadline_ms - 1.0) is False
    assert ch.is_expired(ch.deadline_ms) is True


# ---- multi-shot escalation: monotonic but hard-capped ----------------------

def test_miss_escalation_is_capped():
    ch = AimChallenge.from_seed("cap")
    assert ch.travel_mult(0) == pytest.approx(1.0)
    assert ch.travel_mult(1) > ch.travel_mult(0)
    assert ch.travel_mult(1000) == pytest.approx(aim.AIM_SWAY_CAP)
    assert ch.shrink_mult(0) == pytest.approx(1.0)
    assert ch.shrink_mult(1000) == pytest.approx(aim.AIM_SHRINK_CAP)


def test_misses_make_it_shrink_and_sweep_faster():
    ch = AimChallenge.from_seed("faster")
    at = ch.deadline_ms * 0.4
    assert ch.piece_scale(at, miss_count=5) < ch.piece_scale(at, miss_count=0)
    assert ch.param_at(300.0, miss_count=5) > ch.param_at(300.0, miss_count=0)
    assert ch.is_expired(ch.deadline_ms - 1.0, miss_count=5) is True


def test_capped_difficulty_still_leaves_a_winnable_window():
    cap_miss = int((aim.AIM_SWAY_CAP - 1.0) / aim.AIM_SWAY_STEP) + 5
    for i in range(40):
        ch = AimChallenge.from_seed("hard:{}".format(i))
        assert any(ch.on_target(e, cap_miss) for e in range(0, int(aim.AIM_DEADLINE_MS), 6)), \
            "even at the escalation cap there is some window to land a shot"


# ---- cell-size independence (normalised units) -----------------------------

def test_geometry_is_unitless():
    ch = AimChallenge.from_seed("unit")
    for e in range(0, 2000, 50):
        fx, fy = ch.reticle_offset(e)
        assert -1.0 <= fx <= 1.0 and -1.0 <= fy <= 1.0
        assert isinstance(ch.on_target(e), bool)
