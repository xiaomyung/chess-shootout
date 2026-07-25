"""Whack-a-mole skillcheck engine (chessshootout/skillcheck/mole.py): a seeded
schedule of mole pops over board holes, hit by clicking inside a circular
board-space hitbox while the pop's half-open window [t_up, t_down + grace) is
live. The schedule is solved into the skillcheck deadline budget by ONE common
scale factor with per-component floors; when floors make the full quota
impossible the required hit count is downgraded at construction time, so the
challenge is always deterministic for (seed, value_diff, deadline, value).
Windows stay disjoint even with grace BY CONSTRUCTION: the precue + gap floors
(180 + 80) exceed the 120ms grace tail.
"""

from pathlib import Path

import pytest

from chessshootout.skillcheck import mole, wheel
from chessshootout.skillcheck.mole import MoleChallenge

CAPTURE_SQ = (3, 3)
OCCUPIED = {(3, 3), (4, 4)}


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


def test_hit_at_is_a_timed_circular_hitbox_with_dedup():
    ch = MoleChallenge.from_seed("hit-seed", captured_value=5)
    squares = mole.hole_squares("hit-seed", 5, CAPTURE_SQ, OCCUPIED)
    pop = ch.pops[0]
    t = (pop.t_up_ms + pop.t_down_ms) / 2.0
    row, col = squares[pop.hole]
    center = (row + 0.5, col + 0.5)
    assert ch.hit_at(t, center[0], center[1], squares) is True
    assert ch.hit_at(t, center[0], center[1] + 0.549, squares) is True, "just inside 0.55"
    assert ch.hit_at(t, center[0], center[1] + 0.551, squares) is False, "just outside 0.55"
    assert ch.hit_at(pop.t_up_ms - 1.0, center[0], center[1], squares) is False, "wrong time"
    assert ch.hit_at(t, center[0], center[1], squares, last_hit_pop=0) is False, \
        "an already-credited pop cannot be double-hit"


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


def test_motor_model_sweep_is_deterministic_and_bounded():
    # Diagnostic only: NO pass-band assertion on the rate itself.
    first = _motor_model_success_rate()
    second = _motor_model_success_rate()
    assert first == second
    assert isinstance(first, float)
    assert 0.0 <= first <= 1.0


def test_pick_taunt_is_deterministic_per_seed_and_drawn_from_the_table():
    # the taunt lives in the pure engine so the pygame-free server side and the
    # view render the SAME string for one check without duplicating the table.
    assert mole.pick_taunt("seed-x") == mole.pick_taunt("seed-x")
    texts = {mole.pick_taunt(f"seed-{i}") for i in range(30)}
    assert texts <= set(mole.MOLE_TAUNTS)
    assert len(texts) >= 2, "the table is genuinely sampled, not pinned to one entry"


def test_occupied_squares_is_row_major_and_skips_empty_cells():
    # the hole-layout derivation is seeded off this list, so its ORDER is
    # load-bearing: server and client must walk the grid identically.
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
