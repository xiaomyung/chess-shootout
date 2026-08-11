"""Whack-a-mole skillcheck engine (chessshootout/skillcheck/mole.py): a seeded
schedule of mole pops over board holes, hit by clicking inside a tall
piece-fitted OVAL in board space while the pop's half-open window
[t_up, t_down + grace) is live. The oval is narrower than a cell and taller
than it is wide, and its centre sits ABOVE the pit square's centre because the
popped piece rises out of the hole -- so the hitbox hugs the drawn body, not
the hole. The schedule is solved into the skillcheck deadline budget by ONE common
scale factor with per-component floors; when floors make the full quota
impossible the required hit count is downgraded at construction time, so the
challenge is always deterministic for (seed, value_diff, deadline, value).
Windows stay disjoint even with grace BY CONSTRUCTION: the precue + gap floors
(180 + 80) exceed the 120ms grace tail.

The pit LAYOUT (`hole_squares`) is a second, independent derivation: a seeded
farthest-point walk over the free squares around the capture square. The first
pit is a plain seeded draw; every later one takes the candidate that maximises
its minimum distance to the pits already placed, exact ties broken by the next
seeded float. Distances are compared as integer squares, so "exact tie" really
is exact and the walk is a pure function of (seed, value, square, occupied) --
load-bearing, because the server re-derives the same layout in its own process
to adjudicate positional whack shots.
"""

import itertools
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

import chessshootout
from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.skillcheck import mole, wheel
from chessshootout.skillcheck.combo import COMBO_MAX_WRONGS
from chessshootout.skillcheck.mole import MoleChallenge

CAPTURE_SQ = (3, 3)
OCCUPIED = {(3, 3), (4, 4)}
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(chessshootout.__file__)))
SPREAD_SEEDS = 50


def _durations(challenge):
    return [pop.t_down_ms - pop.t_up_ms for pop in challenge.pops]


def _measured_gaps(challenge):
    return [nxt.t_telegraph_ms - cur.t_down_ms
            for cur, nxt in zip(challenge.pops, challenge.pops[1:])]


def _window_ends(challenge):
    return [pop.t_down_ms + mole.MOLE_GRACE_MS for pop in challenge.pops]


def test_from_seed_is_deterministic_for_identical_inputs():
    a = MoleChallenge.from_seed("room-1:5", value_diff=3, deadline_ms=4200.0, captured_value=4)
    b = MoleChallenge.from_seed("room-1:5", value_diff=3, deadline_ms=4200.0, captured_value=4)
    assert a == b
    assert a.pops == b.pops and a.deadline_ms == 4200.0


def test_distinct_seeds_vary_hole_assignment():
    sequences = {tuple(pop.hole for pop in MoleChallenge.from_seed(f"s:{i}").pops)
                 for i in range(20)}
    assert len(sequences) >= 10


def test_default_budget_five_pops_fit_the_deadline():
    for i in range(30):
        ch = MoleChallenge.from_seed(f"budget:{i}")
        assert len(ch.pops) == 5 and ch.hits_required == 3
        assert _window_ends(ch)[-1] <= wheel.SKILLCHECK_DEADLINE_MS + 1e-6


def test_first_pop_up_time_leaves_reaction_room_at_the_default_deadline():
    for i in range(30):
        for diff in (-8, 0, 8):
            ch = MoleChallenge.from_seed(f"react:{i}", value_diff=diff)
            assert ch.pops[0].t_up_ms >= mole.MOLE_FIRST_POP_MIN_MS


def test_up_time_ramp_dips_mid_run_and_the_final_pop_is_never_the_shortest():
    for i in range(20):
        d = _durations(MoleChallenge.from_seed(f"ramp:{i}"))
        assert d[0] == pytest.approx(d[1])
        assert d[1] >= d[2] >= d[3]
        assert d[4] >= d[3], "the final pop eases back up; it is never the lone shortest"


def test_up_times_respect_the_floor_across_the_real_value_diff_range():
    for diff in range(-8, 9):
        for i in range(5):
            ch = MoleChallenge.from_seed(f"floor:{diff}:{i}", value_diff=diff)
            assert all(d >= mole.MOLE_POP_UP_FLOOR_MS - 1e-9 for d in _durations(ch))
            assert _window_ends(ch)[-1] <= wheel.SKILLCHECK_DEADLINE_MS + 1e-6


def test_gap_jitter_varies_between_seeds_within_the_band():
    gaps = [gap for i in range(30) for gap in _measured_gaps(MoleChallenge.from_seed(f"j:{i}"))]
    assert len({round(gap, 3) for gap in gaps}) >= 5, "gaps are jittered, not metronomic"
    band_top = mole.MOLE_GAP_MS + mole.MOLE_GAP_JITTER_MS
    for gap in gaps:
        assert mole.MOLE_GAP_FLOOR_MS - 1e-9 <= gap <= band_top + 1e-6


def test_windows_are_disjoint_even_with_grace_across_regimes():
    assert mole.MOLE_PRECUE_FLOOR_MS + mole.MOLE_GAP_FLOOR_MS > mole.MOLE_GRACE_MS, \
        "the floors alone guarantee disjointness by construction"
    for i in range(12):
        for diff in (-8, 0, 8):
            for deadline in (5000.0, 3500.0, 3000.0, 2000.0, 1000.0):
                ch = MoleChallenge.from_seed(f"dj:{i}", value_diff=diff, deadline_ms=deadline)
                for pop in ch.pops:
                    assert pop.t_telegraph_ms < pop.t_up_ms < pop.t_down_ms
                for cur, nxt in zip(ch.pops, ch.pops[1:]):
                    assert nxt.t_up_ms > cur.t_down_ms + mole.MOLE_GRACE_MS


def test_pop_window_boundaries_are_half_open():
    ch = MoleChallenge.from_seed("boundary")
    pop = ch.pops[1]
    assert ch.pop_up_at(pop.t_up_ms) == 1, "the lower edge is inclusive"
    assert ch.pop_up_at(pop.t_down_ms + mole.MOLE_GRACE_MS) is None, \
        "t_down + grace is the exclusive upper edge"
    assert ch.pop_up_at(pop.t_down_ms + mole.MOLE_GRACE_MS - 0.001) == 1
    assert ch.pop_up_at(0.0) is None
    assert ch.pop_up_at(ch.pops[0].t_telegraph_ms) is None, "telegraphed is not yet hittable"


def test_compressed_tier_flips_below_the_compress_deadline():
    for i in range(15):
        assert len(MoleChallenge.from_seed(f"t:{i}", deadline_ms=3500.0).pops) == 5
        assert MoleChallenge.from_seed(f"t:{i}", deadline_ms=3500.0).hits_required == 3
        for deadline in (3000.0, 2000.0):
            ch = MoleChallenge.from_seed(f"t:{i}", deadline_ms=deadline)
            assert len(ch.pops) == 3
        assert MoleChallenge.from_seed(f"t:{i}", deadline_ms=3000.0).hits_required == 2


def test_compressed_schedules_stay_winnable_and_floored():
    for i in range(15):
        for deadline in (3500.0, 3000.0, 2000.0):
            ch = MoleChallenge.from_seed(f"c:{i}", deadline_ms=deadline)
            inside = sum(1 for end in _window_ends(ch) if end < deadline)
            assert inside >= ch.hits_required
            assert ch.pops[0].t_telegraph_ms >= mole.MOLE_INTRO_FLOOR_MS - 1e-9
            assert ch.pops[0].t_up_ms >= mole.MOLE_FIRST_POP_FLOOR_MS - 1e-9
            for pop in ch.pops:
                assert pop.t_up_ms - pop.t_telegraph_ms >= mole.MOLE_PRECUE_FLOOR_MS - 1e-9
                assert pop.t_down_ms - pop.t_up_ms >= mole.MOLE_POP_UP_FLOOR_MS - 1e-9
            for gap in _measured_gaps(ch):
                assert gap >= mole.MOLE_GAP_FLOOR_MS - 1e-9


def test_a_two_second_deadline_floors_everything_and_downgrades_the_quota():
    # target 1880ms cannot even hold the floored sum of two windows, so the
    # schedule collapses to the all-floors layout regardless of seed jitter and
    # the quota deterministically downgrades to the one window that fits.
    for i in range(10):
        ch = MoleChallenge.from_seed(f"tiny:{i}", deadline_ms=2000.0)
        assert ch.hits_required == 1
        assert _window_ends(ch) == [pytest.approx(1150.0), pytest.approx(2010.0),
                                    pytest.approx(2870.0)]


def test_hole_derivation_is_stable_across_tiers():
    for i in range(10):
        full = MoleChallenge.from_seed(f"tier:{i}", captured_value=4)
        short = MoleChallenge.from_seed(f"tier:{i}", deadline_ms=3000.0, captured_value=4)
        assert [pop.hole for pop in short.pops] == [pop.hole for pop in full.pops][:3]


@pytest.mark.parametrize("captured_value, expected", [
    (0, 3), (1, 3), (3, 3), (5, 5), (9, 5),
])
def test_hole_count_clamps_to_the_min_cap_band(captured_value, expected):
    ch = MoleChallenge.from_seed("clamp", captured_value=captured_value)
    assert ch.hole_count == expected
    squares = mole.hole_squares("clamp", captured_value, CAPTURE_SQ, OCCUPIED)
    assert len(squares) == expected


def test_no_consecutive_repeat_holes_and_all_holes_in_range():
    for i in range(30):
        for captured_value in (0, 4, 9):
            ch = MoleChallenge.from_seed(f"h:{i}", captured_value=captured_value)
            holes = [pop.hole for pop in ch.pops]
            assert all(0 <= hole < ch.hole_count for hole in holes)
            for cur, nxt in zip(holes, holes[1:]):
                assert cur != nxt


def test_hit_at_is_a_timed_oval_hitbox_with_dedup():
    ch = MoleChallenge.from_seed("hit-seed", captured_value=5)
    squares = mole.hole_squares("hit-seed", 5, CAPTURE_SQ, OCCUPIED)
    pop = ch.pops[0]
    t = (pop.t_up_ms + pop.t_down_ms) / 2.0
    row, col = squares[pop.hole]
    # the oval's own centre: half a cell into the square, then lifted by the
    # pop offset so it sits on the risen piece's body.
    oval_row = row + 0.5 + mole.MOLE_HITBOX_CY_FRAC
    oval_col = col + 0.5
    assert ch.hit_at(t, oval_row, oval_col, squares) is True, "dead centre of the oval"
    assert ch.hit_at(t, row + 0.5, col + 0.5, squares) is True, \
        "the square centre stays inside: the 0.30 lift is well within the 0.52 half-height"
    assert ch.hit_at(pop.t_up_ms - 1.0, oval_row, oval_col, squares) is False, "wrong time"
    assert ch.hit_at(t, oval_row, oval_col, squares, last_hit_pop=0) is False, \
        "an already-credited pop cannot be double-hit"


def test_hit_at_oval_is_taller_than_wide_and_lifted_off_the_hole():
    ch = MoleChallenge.from_seed("hit-seed", captured_value=5)
    squares = mole.hole_squares("hit-seed", 5, CAPTURE_SQ, OCCUPIED)
    pop = ch.pops[0]
    t = (pop.t_up_ms + pop.t_down_ms) / 2.0
    row, col = squares[pop.hole]
    oval_row = row + 0.5 + mole.MOLE_HITBOX_CY_FRAC
    oval_col = col + 0.5
    rx, ry = mole.MOLE_HITBOX_RX_FRAC, mole.MOLE_HITBOX_RY_FRAC
    assert ry > rx, "a standing piece is taller than it is wide"
    assert ch.hit_at(t, oval_row, oval_col + rx - 0.001, squares) is True, "just inside the waist"
    assert ch.hit_at(t, oval_row, oval_col + rx + 0.001, squares) is False, "just outside it"
    assert ch.hit_at(t, oval_row + ry - 0.001, oval_col, squares) is True, "just inside the head"
    assert ch.hit_at(t, oval_row + ry + 0.001, oval_col, squares) is False, "just past it"
    # containment is `<=`, so a shot landing exactly ON the rim still counts.
    assert ch.hit_at(t, oval_row, oval_col + rx, squares) is True, "the rim itself is a hit"
    assert ch.hit_at(t, oval_row - ry, oval_col, squares) is True, "top of the rim, likewise"
    # the shape really is an ellipse, not the bounding box: the corner where the
    # full half-width and the full half-height meet is outside.
    assert ch.hit_at(t, oval_row + ry * 0.8, oval_col + rx * 0.8, squares) is False, \
        "the diagonal corner falls outside the oval"
    assert ch.hit_at(t, row + 0.9, col + 0.5, squares) is False, \
        "low in the square is under the piece: the oval does not reach the pit floor"
    assert ch.hit_at(t, row + 0.2, col + 0.95, squares) is False, "wide of the body"
    assert ch.hit_at(t, row - 0.1, col + 0.5, squares) is True, \
        "the oval spills ABOVE the pit square, where the risen piece is drawn"


def test_hit_at_flipped_mirrors_the_lift_below_the_pit_row_in_board_space():
    # On a flipped board (black at the bottom) the popped piece still rises UP
    # the SCREEN, which is +rows in board space -- so flipped=True mirrors the
    # CY lift to the other side of the pit centre. CY is negative, so the
    # flipped oval centre is row + 0.5 - CY = row + 0.8.
    ch = MoleChallenge.from_seed("hit-seed", captured_value=5)
    squares = mole.hole_squares("hit-seed", 5, CAPTURE_SQ, OCCUPIED)
    pop = ch.pops[0]
    t = (pop.t_up_ms + pop.t_down_ms) / 2.0
    row, col = squares[pop.hole]
    unflipped_row = row + 0.5 + mole.MOLE_HITBOX_CY_FRAC
    flipped_row = row + 0.5 - mole.MOLE_HITBOX_CY_FRAC
    oval_col = col + 0.5
    assert ch.hit_at(t, flipped_row, oval_col, squares, flipped=True) is True, \
        "dead centre of the mirrored oval"
    assert ch.hit_at(t, unflipped_row, oval_col, squares, flipped=True) is False, \
        "the unflipped centre is 0.6 rows off the mirrored oval, past the 0.52 half-height"
    assert ch.hit_at(t, flipped_row, oval_col, squares) is False, \
        "and symmetrically the mirrored centre misses the unflipped oval"
    assert ch.hit_at(t, row + 0.5, oval_col, squares, flipped=True) is True, \
        "the square centre hits under BOTH orientations: 0.30 lift < 0.52 half-height"
    assert ch.hit_at(t, row + 0.5, oval_col, squares) is True
    ry = mole.MOLE_HITBOX_RY_FRAC
    assert ch.hit_at(t, flipped_row + ry, oval_col, squares, flipped=True) is True, \
        "the mirrored oval spills BELOW the pit row, where the flipped screen draws the body"
    assert ch.hit_at(t, flipped_row + ry + 0.001, oval_col, squares, flipped=True) is False
    assert ch.hit_at(t, unflipped_row, oval_col, squares, flipped=False) is True, \
        "explicit flipped=False is byte-identical to the historical default"


def test_hitbox_lift_mirrors_with_the_orientation():
    # hitbox_lift is the ONE named rule for which side of the pit the body rises
    # on: hit_at reads it here and the client's wire normalisation reads the very
    # same function, so the two can never drift apart again.
    assert mole.hitbox_lift(False) == mole.MOLE_HITBOX_CY_FRAC
    assert mole.hitbox_lift(True) == -mole.MOLE_HITBOX_CY_FRAC
    assert mole.hitbox_lift(True) == -mole.hitbox_lift(False)
    ch = MoleChallenge.from_seed("hit-seed", captured_value=5)
    squares = mole.hole_squares("hit-seed", 5, CAPTURE_SQ, OCCUPIED)
    pop = ch.pops[0]
    t = (pop.t_up_ms + pop.t_down_ms) / 2.0
    row, col = squares[pop.hole]
    for flipped in (False, True):
        assert ch.hit_at(t, row + 0.5 + mole.hitbox_lift(flipped), col + 0.5, squares,
                         flipped=flipped) is True, \
            "hit_at still agrees with the raw constant on both orientations"


def test_hit_at_with_a_short_hole_list_is_a_safe_miss():
    ch = MoleChallenge.from_seed("short-list", captured_value=9)
    index = next(i for i, pop in enumerate(ch.pops) if pop.hole >= 1)
    pop = ch.pops[index]
    t = (pop.t_up_ms + pop.t_down_ms) / 2.0
    assert ch.hit_at(t, 0.5, 0.5, []) is False
    assert ch.hit_at(t, 0.5, 0.5, [(0, 0)]) is False, "hole index beyond the list never crashes"


def test_remaining_hittable_counts_open_windows_and_skips_a_credited_up_pop():
    ch = MoleChallenge.from_seed("remaining")
    pop = ch.pops[0]
    mid = (pop.t_up_ms + pop.t_down_ms) / 2.0
    assert ch.remaining_hittable(0.0) == 5
    assert ch.remaining_hittable(0.0, last_hit_pop=0) == 5, \
        "a not-yet-up pop stays counted regardless of the credit marker"
    assert ch.remaining_hittable(mid) == 5
    assert ch.remaining_hittable(mid, last_hit_pop=0) == 4, "the credited up pop is spent"
    closed = pop.t_down_ms + mole.MOLE_GRACE_MS
    assert ch.remaining_hittable(closed) == 4
    assert ch.remaining_hittable(closed, last_hit_pop=0) == 4


def test_quota_unreachable_boundaries_derive_from_the_schedule():
    ch = MoleChallenge.from_seed("quota")
    ends = _window_ends(ch)
    assert ch.quota_unreachable(0.0, 0) is False
    grid = [ch.quota_unreachable(step * 25.0, 0) for step in range(280)]
    assert grid == sorted(grid), "monotone non-decreasing in elapsed for fixed hits"
    # 0 hits, need 3: unreachable exactly when only 2 windows remain, i.e. when
    # the 3rd window (index 2 = 5 - hits_required) closes.
    assert ch.quota_unreachable(ends[2] - 0.001, 0) is False
    assert ch.quota_unreachable(ends[2], 0) is True
    # 1 hit: decisive window is index 3.
    assert ch.quota_unreachable(ends[3] - 0.001, 1) is False
    assert ch.quota_unreachable(ends[3], 1) is True
    # 2 hits: only flips once every window is gone.
    assert ch.quota_unreachable(ends[4] - 0.001, 2) is False
    assert ch.quota_unreachable(ends[4], 2) is True
    assert ch.quota_unreachable(1e9, 3) is False, "quota already met never flips"


def test_quota_unreachable_discounts_the_still_up_credited_pop():
    ch = MoleChallenge.from_seed("quota")
    last = ch.pops[4]
    mid = (last.t_up_ms + last.t_down_ms) / 2.0
    assert ch.quota_unreachable(mid, 2) is False, "the open final window can still supply hit 3"
    assert ch.quota_unreachable(mid, 2, last_hit_pop=4) is True, \
        "but not when that final window already produced the credited hit"


@pytest.mark.parametrize("captured_value, expected", [(0, 3), (1, 3), (3, 4), (5, 4), (9, 5)])
def test_required_hits_scales_with_the_captured_piece_value(captured_value, expected):
    # pawn(1) 3-of-5, knight/bishop(3) and rook(5) 4-of-5, queen(9) 5-of-5; a
    # value of 0 (promotions / edge cases) stays at the base 3.
    assert mole._required_hits(captured_value) == expected


@pytest.mark.parametrize("captured_value, expected", [(0, 3), (1, 3), (3, 4), (5, 4)])
def test_from_seed_quota_follows_the_value_map_at_the_default_deadline(captured_value, expected):
    for i in range(40):
        assert MoleChallenge.from_seed(f"map:{i}", captured_value=captured_value).hits_required \
            == expected


def test_a_queen_capture_demands_all_five_pops():
    # the full 5-of-5 only survives when the seeded schedule fits the 5s budget
    # without scaling; "queen" is such a seed. Nominal-overflow seeds get scaled
    # and the untouched budget-solve fallback trims the unreachable fifth hit to 4.
    ch = MoleChallenge.from_seed("queen", captured_value=9)
    assert ch.hits_required == 5 and len(ch.pops) == 5


@pytest.mark.parametrize("required, expected", [(3, 2), (4, 2), (5, 3)])
def test_compressed_hits_scales_the_quota_by_the_pop_ratio(required, expected):
    assert mole._compressed_hits(required) == expected


@pytest.mark.parametrize("captured_value, expected", [(1, 2), (5, 2), (9, 3)])
def test_compressed_deadline_scales_the_value_map(captured_value, expected):
    # deadline 3000 -> the 3-pop tier; "t:9" fits all three windows so the
    # compressed map shows through without the budget-solve fallback trimming it.
    ch = MoleChallenge.from_seed("t:9", deadline_ms=3000.0, captured_value=captured_value)
    assert ch.hits_required == expected


def test_pop_mandatory_flags_a_pop_whose_miss_dooms_the_quota():
    queen = MoleChallenge.from_seed("queen", captured_value=9)
    assert queen.hits_required == 5 and len(queen.pops) == 5
    assert queen.pop_mandatory(0, 0) is True, "a 5-of-5 has zero slack from the opening pop"
    assert all(queen.pop_mandatory(i, i) for i in range(5)), \
        "along the perfect run every queen pop is mandatory"
    assert [queen.pop_mandatory(i, 0) for i in range(5)] == [True, False, False, False, False], \
        "at zero hits only the opening pop still sits on the exact-quota line"
    pawn = MoleChallenge.from_seed("pawn", captured_value=1)
    assert pawn.hits_required == 3 and len(pawn.pops) == 5
    assert pawn.pop_mandatory(0, 0) is False, "a 3-of-5 carries two pops of slack at the start"
    assert pawn.pop_mandatory(2, 0) is True, "with two pops already gone the third is forced"


def test_a_five_of_five_dies_the_instant_one_pop_expires_unhit():
    ch = MoleChallenge.from_seed("queen", captured_value=9)
    ends = _window_ends(ch)
    assert ch.quota_unreachable(0.0, 0) is False, "reachable while every pop is still ahead"
    assert ch.quota_unreachable(ends[0] - 0.001, 0) is False, "the opening pop is still live"
    assert ch.quota_unreachable(ends[0], 0) is True, \
        "the first unhit expiry already makes 5-of-5 impossible"
    assert ch.pop_mandatory(0, 0) is True, \
        "pop_mandatory foretells exactly the pop whose miss triggers that death"


def test_whiff_cap_mirrors_the_combo_wrong_cap():
    # Unlimited free misses made whack the one blindly automatable check: a bot
    # could spam every hole and only the hits counted. Three whiffs now fail the
    # check outright, the exact budget combo grants wrong presses — the two caps
    # are deliberately the same number and the same >= comparison.
    assert mole.MOLE_MAX_WHIFFS == COMBO_MAX_WRONGS == 3
    ch = MoleChallenge.from_seed("whiffs")
    assert ch.whiffs_exhausted(0) is False
    assert ch.whiffs_exhausted(mole.MOLE_MAX_WHIFFS - 1) is False
    assert ch.whiffs_exhausted(mole.MOLE_MAX_WHIFFS) is True
    assert ch.whiffs_exhausted(mole.MOLE_MAX_WHIFFS + 5) is True


def test_whiffs_exhausted_ignores_the_schedule_entirely():
    # the cap is a pure counter rule: the same miss_count reads identically on a
    # full 5-pop schedule and a compressed 3-pop one, before or after any pop.
    full = MoleChallenge.from_seed("cap:sched")
    short = MoleChallenge.from_seed("cap:sched", deadline_ms=2000.0)
    for count in range(6):
        assert full.whiffs_exhausted(count) == short.whiffs_exhausted(count) \
            == (count >= mole.MOLE_MAX_WHIFFS)


def test_hole_squares_is_deterministic_and_iteration_order_independent():
    occupied = [(3, 3), (4, 4), (2, 2), (5, 1)]
    first = mole.hole_squares("stable", 5, CAPTURE_SQ, occupied)
    again = mole.hole_squares("stable", 5, CAPTURE_SQ, occupied)
    permuted = mole.hole_squares("stable", 5, CAPTURE_SQ, list(reversed(occupied)))
    as_set = mole.hole_squares("stable", 5, CAPTURE_SQ, set(occupied))
    assert first == again == permuted == as_set
    assert len(first) == 5


def test_hole_squares_excludes_occupied_and_stays_in_radius():
    occupied = {(3, 3), (4, 4), (2, 3), (3, 2), (6, 6)}
    for i in range(30):
        squares = mole.hole_squares(f"ex:{i}", 5, CAPTURE_SQ, occupied)
        for row, col in squares:
            assert (row, col) not in occupied
            assert 0 <= row < 8 and 0 <= col < 8
            assert max(abs(row - 3), abs(col - 3)) <= mole.MOLE_HOLE_RADIUS_CELLS


def test_hole_squares_widens_the_radius_on_a_crowded_board():
    occupied = {(row, col) for row in range(8) for col in range(8)
                if max(abs(row - 3), abs(col - 3)) <= 3}
    squares = mole.hole_squares("crowd", 5, CAPTURE_SQ, occupied)
    assert len(squares) == 5
    for row, col in squares:
        assert max(abs(row - 3), abs(col - 3)) == 4, "every base-radius square was occupied"


def test_hole_squares_returns_what_exists_when_the_board_is_nearly_full():
    everything = {(row, col) for row in range(8) for col in range(8)}
    two_free = everything - {(0, 0), (7, 7)}
    assert sorted(mole.hole_squares("full", 5, CAPTURE_SQ, two_free)) == [(0, 0), (7, 7)]
    assert mole.hole_squares("full", 5, CAPTURE_SQ, everything) == ()


def test_hole_squares_always_finds_the_full_count_on_a_near_empty_board():
    for capture_sq in ((0, 0), (7, 7), (3, 3), (0, 7)):
        for captured_value in (0, 3, 5, 9):
            occupied = {capture_sq, (4, 4), (3, 4)}
            squares = mole.hole_squares("open", captured_value, capture_sq, occupied)
            assert len(squares) == min(5, max(3, captured_value))
            assert len(squares) >= 3


_LAYOUT_DRIVER = (
    "from chessshootout.skillcheck import mole;"
    "print(mole.hole_squares('cross-proc', 9, (3, 3), [(3, 3), (4, 4)]))"
)


def _spread_layouts(count=SPREAD_SEEDS):
    return [mole.hole_squares(f"spread:{i}", 9, CAPTURE_SQ, {CAPTURE_SQ})
            for i in range(count)]


def _min_gap(square, chosen):
    return min(math.hypot(square[0] - row, square[1] - col) for row, col in chosen)


def _all_collinear(points):
    (row0, col0), (row1, col1) = points[0], points[1]
    d_row, d_col = row1 - row0, col1 - col0
    return all((row - row0) * d_col == (col - col0) * d_row for row, col in points[2:])


def test_hole_squares_is_identical_across_repeat_calls_and_a_fresh_process():
    # the server re-derives this layout in ITS OWN process from (seed, value,
    # square, occupied) alone, so a pick that leaked hash-order or any live
    # randomness would desync every positional whack shot. Fresh interpreters
    # under different PYTHONHASHSEEDs must reproduce the in-process tuple.
    occupied = [(3, 3), (4, 4)]
    calls = {mole.hole_squares("cross-proc", 9, (3, 3), occupied) for _ in range(3)}
    assert len(calls) == 1, "three identical calls, one layout"
    expected = repr(calls.pop())
    for hash_seed in ("0", "1", "424242"):
        out = subprocess.run([sys.executable, "-c", _LAYOUT_DRIVER],
                             capture_output=True, text=True, cwd=REPO_ROOT,
                             env={**os.environ, "PYTHONHASHSEED": hash_seed}, check=False)
        assert out.stdout.strip() == expected, out.stderr


def test_hole_squares_never_places_two_pits_on_touching_squares():
    # the whole point of the farthest-point walk. On the open 7x7 pool the greedy
    # max-min guarantee (>= half the optimal spread) sits far above the 1.41 that
    # a diagonal touch would need, so this holds flat -- no "usually" allowance.
    for layout in _spread_layouts():
        assert len(layout) == 5
        assert len(set(layout)) == 5, "pits never repeat a square"
        for first, second in itertools.combinations(layout, 2):
            chebyshev = max(abs(first[0] - second[0]), abs(first[1] - second[1]))
            assert chebyshev > 1, f"{first} and {second} are adjacent in {layout}"


def test_hole_squares_never_lines_all_five_pits_up():
    for layout in _spread_layouts():
        assert not _all_collinear(list(layout)), f"{layout} is a straight line of pits"


def test_each_pit_after_the_first_maximises_its_distance_to_the_earlier_ones():
    # the placement rule itself, checked against the pool the engine saw: at every
    # step the taken square is (one of) the candidates whose nearest already-placed
    # pit is farthest away.
    occupied = {(3, 3), (4, 4), (2, 5)}
    for i in range(20):
        layout = mole.hole_squares(f"greedy:{i}", 9, CAPTURE_SQ, occupied)
        pool = mole._free_squares(CAPTURE_SQ, occupied, mole.MOLE_HOLE_RADIUS_CELLS, 8)
        chosen, remaining = [layout[0]], [sq for sq in pool if sq != layout[0]]
        for square in layout[1:]:
            best = max(_min_gap(candidate, chosen) for candidate in remaining)
            assert _min_gap(square, chosen) == pytest.approx(best), \
                f"{square} is not a farthest point from {chosen}"
            chosen.append(square)
            remaining.remove(square)


def test_exact_ties_are_broken_by_the_seeded_float_not_by_list_order():
    # four candidates exactly equidistant from the one placed pit: list order
    # alone would always hand back the first, which is how straight lines and
    # clumps crept in. The seeded float has to reach into the whole tied subset.
    candidates = [(0, 3), (3, 0), (3, 6), (6, 3)]
    reached = {mole._farthest_index(list(candidates), [(3, 3)], value)
               for value in (0.0, 0.3, 0.6, 0.9)}
    assert reached == {0, 1, 2, 3}
    assert mole._farthest_index(list(candidates), [(3, 3)], 0.999999) == 3
    near = candidates + [(4, 4)]
    assert mole._farthest_index(near, [(3, 3)], 0.9) == 3, \
        "a closer candidate never joins the tie, whatever the float says"


def test_hole_squares_layouts_still_vary_across_seeds():
    # dispersion must not collapse into one canonical corner set: the seeded first
    # pit plus the seeded tie-breaks keep the layouts genuinely different.
    layouts = _spread_layouts()
    assert len(set(layouts)) >= SPREAD_SEEDS // 2
    assert len({frozenset(layout) for layout in layouts}) >= SPREAD_SEEDS // 3


def test_scripted_midpoint_solver_always_reaches_the_quota():
    for i in range(200):
        seed = f"win:{i}"
        ch = MoleChallenge.from_seed(seed, captured_value=5)
        squares = mole.hole_squares(seed, 5, CAPTURE_SQ, OCCUPIED)
        hits, last_hit, last_shot = 0, -1, None
        for index, pop in enumerate(ch.pops):
            shot = (pop.t_up_ms + pop.t_down_ms + mole.MOLE_GRACE_MS) / 2.0
            if last_shot is not None:
                assert shot - last_shot >= mole.MOLE_RECOIL_LOCKOUT_MS, \
                    "midpoint pacing respects the client recoil lockout"
            row, col = squares[pop.hole]
            if ch.hit_at(shot, row + 0.5, col + 0.5, squares, last_hit):
                hits += 1
                last_hit = index
            last_shot = shot
        assert hits >= ch.hits_required


# Fixed draw from Normal(720, 150), generated once and frozen here so the sweep
# below never touches live randomness.
MOTOR_OFFSETS_MS = [
    974.1, 1044.9, 677.6, 838.2, 684.1, 522.0, 866.7, 805.9, 736.5, 784.8,
    797.8, 830.1, 943.3, 726.1, 716.5, 839.6, 426.3, 985.8, 766.4, 712.7,
    562.5, 697.1, 964.5, 663.9, 613.9, 727.6, 402.5, 722.4, 498.0, 970.2,
    647.7, 596.0, 773.5, 790.2, 883.2, 847.7, 741.6, 475.0, 601.0, 858.3,
]


def _motor_model_success_rate():
    wins = 0
    draw = 0
    for i in range(100):
        seed = f"motor:{i}"
        ch = MoleChallenge.from_seed(seed, captured_value=5)
        squares = mole.hole_squares(seed, 5, CAPTURE_SQ, OCCUPIED)
        hits, last_hit = 0, -1
        for pop in ch.pops:
            shot = pop.t_telegraph_ms + MOTOR_OFFSETS_MS[draw % len(MOTOR_OFFSETS_MS)]
            draw += 1
            row, col = squares[pop.hole]
            if ch.hit_at(shot, row + 0.5, col + 0.5, squares, last_hit):
                hits += 1
                last_hit = ch.pop_up_at(shot)
        wins += hits >= ch.hits_required
    return wins / 100.0


def test_motor_model_sweep_matches_its_pinned_snapshot():
    # The sweep is a pure function of frozen constants (the offsets above, the pop
    # schedule and the hitbox), so "run it twice, same answer" could never fail --
    # it was a tautology dressed up as a determinism check. Pinning the VALUE is
    # what makes it a regression: retune the schedule or the hitbox and this trips.
    # The number is DIAGNOSTIC, not a balance target -- there is no success band to
    # ease toward, so a change here is a prompt to look, not a failure to "fix" by
    # nudging the rate back.
    assert _motor_model_success_rate() == pytest.approx(0.93)


def test_pick_taunt_is_deterministic_per_seed_and_drawn_from_the_table():
    # the taunt lives in the pure engine so the pygame-free server side and the
    # view render the SAME string for one check without duplicating the table.
    assert mole.pick_taunt("seed-x") == mole.pick_taunt("seed-x")
    texts = {mole.pick_taunt(f"seed-{i}") for i in range(30)}
    assert texts <= set(mole.MOLE_TAUNTS)
    assert len(set(mole.MOLE_TAUNTS)) == len(mole.MOLE_TAUNTS), "no duplicate taunts"
    assert len(mole.MOLE_TAUNTS) >= 10, "the pool is wide enough not to feel canned"
    assert len(texts) >= 5, "the whole table is genuinely sampled, not a handful of entries"


def test_occupied_squares_is_row_major_and_skips_empty_cells():
    # hole_squares() consumes this as a set (order-independence is pinned by its
    # own test), so what matters here is the CONTENT: every occupied cell and no
    # empty one, in the row-major shape the scan is specified to produce.
    state = [[None] * 3 for _ in range(3)]
    state[0][2] = "wK"
    state[2][0] = "bq"
    state[2][1] = "bp"
    assert mole.occupied_squares(state, 3) == [(0, 2), (2, 0), (2, 1)]
    assert mole.occupied_squares([[None] * 3 for _ in range(3)], 3) == []


def test_deadline_is_single_sourced_from_wheel():
    assert mole.SKILLCHECK_DEADLINE_MS is wheel.SKILLCHECK_DEADLINE_MS
    assert "5000" not in Path(mole.__file__).read_text(encoding="utf-8"), \
        "mole.py must import the deadline, never restate the literal"


def test_queen_value_is_single_sourced_from_the_piece_table():
    # the quota ladder steps at the queen's value; restating 9 here would silently
    # desync the ladder from the engine if a piece were ever revalued.
    assert mole.MOLE_QUEEN_PIECE_VALUE == PIECE_VALUES[PieceType.QUEEN]
    assert mole._required_hits(PIECE_VALUES[PieceType.QUEEN]) == mole.MOLE_POPS_TOTAL, \
        "a queen capture still demands every pop"


def test_holes_for_composes_the_occupancy_scan_and_the_layout_walk():
    # the wrapper is the single spelling of "derive this check's pits from a board
    # state"; server and client must not each re-compose the two primitives.
    state = [[None] * 8 for _ in range(8)]
    state[3][3] = "wQ"
    state[4][4] = "bp"
    composed = mole.hole_squares("wrap", 5, CAPTURE_SQ,
                                 mole.occupied_squares(state, 8), 8)
    assert mole.holes_for("wrap", 5, CAPTURE_SQ, state, 8) == composed
    assert composed, "the layout is non-empty on a nearly empty board"
    assert (3, 3) not in composed and (4, 4) not in composed, \
        "the occupied squares the wrapper scanned are genuinely excluded"
    assert mole.holes_for("wrap", 5, CAPTURE_SQ, state) == composed, \
        "board_size defaults to the engine's BOARD_SIZE"
