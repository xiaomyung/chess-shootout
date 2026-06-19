"""Weighted skill-check selection. Every capture and (non-capturing) promotion
fires 100% wheel. Checks/checkmates never fire. A forced move never fires,
capture takes precedence over promotion, and the per-ply RNG is deterministic +
uniform. Wheel DIFFICULTY (needle speed) scales with capturer-vs-victim material
in chessshootout/skillcheck/wheel.py, NOT the selection odds.

Distribution tests sweep evenly-spaced rolls (i+0.5)/n through the deterministic
selector, so observed proportions equal the cumulative distribution exactly to
the sweep resolution (1/n) -- these are exact assertions, not statistical ones.
"""

from collections import Counter

import pytest

from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.skillcheck import weights
from chessshootout.skillcheck.rng import ply_roll
from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts

NONE = SkillCheckKind.NONE
WHEEL = SkillCheckKind.WHEEL

N = 20000


def sweep(facts):
    counts = Counter()
    for i in range(N):
        counts[weights.roll_skillcheck(facts, (i + 0.5) / N)] += 1
    return {k: counts[k] / N for k in (NONE, WHEEL)}


def assert_dist(observed, expected, tol=0.001):
    for k in (NONE, WHEEL):
        assert observed[k] == pytest.approx(expected.get(k, 0.0), abs=tol)


# ---- piece values are the single source in backend.pieces ------------------

def test_piece_values_match_locked_design():
    assert PIECE_VALUES[PieceType.PAWN] == 1
    assert PIECE_VALUES[PieceType.KNIGHT] == 3
    assert PIECE_VALUES[PieceType.BISHOP] == 3
    assert PIECE_VALUES[PieceType.ROOK] == 5
    assert PIECE_VALUES[PieceType.QUEEN] == 9


def test_capture_summary_reexports_shared_values():
    from chessshootout.domain.capture_summary import PIECE_VALUES as reexport
    assert reexport is PIECE_VALUES


# ---- capture: 100% wheel ---------------------------------------------------

def test_capture_share_is_full_wheel():
    assert weights.CAPTURE_WHEEL_SHARE == 1.0


@pytest.mark.parametrize("cap, vic", [(9, 1), (3, 3), (1, 9)])
def test_capture_always_fires_the_wheel(cap, vic):
    facts = TriggerFacts(is_capture=True, capturer_value=cap, captured_value=vic)
    assert_dist(sweep(facts), {NONE: 0.0, WHEEL: 1.0})


def test_material_does_not_change_the_selection_odds():
    big = sweep(TriggerFacts(is_capture=True, capturer_value=9, captured_value=1))
    small = sweep(TriggerFacts(is_capture=True, capturer_value=1, captured_value=9))
    assert big == small, "material drives the needle SPEED, never which check fires"


# ---- precedence: capture wins over promotion -------------------------------

def test_capture_takes_precedence_over_promotion():
    facts = TriggerFacts(
        is_capture=True, capturer_value=1, captured_value=5, is_promotion=True)
    assert_dist(sweep(facts), {NONE: 0.0, WHEEL: 1.0})


# ---- forced-move guard -----------------------------------------------------

@pytest.mark.parametrize(
    "facts",
    [
        TriggerFacts(is_capture=True, capturer_value=9, captured_value=1, is_forced=True),
        TriggerFacts(is_promotion=True, is_forced=True),
        TriggerFacts(is_forced=True),
    ],
)
def test_forced_move_never_fires(facts):
    assert_dist(sweep(facts), {NONE: 1.0})


# ---- promotion: wheel-only -------------------------------------------------

def test_non_capturing_promotion_is_wheel_only():
    assert_dist(sweep(TriggerFacts(is_promotion=True)), {NONE: 0.0, WHEEL: 1.0})


# ---- quiet (non-triggering) move -------------------------------------------

def test_quiet_move_never_fires():
    assert_dist(sweep(TriggerFacts()), {NONE: 1.0})


# ---- selector correctness --------------------------------------------------

def test_every_distribution_sums_to_one():
    for dist in (weights.CAPTURE_FIRE, weights.PROMOTION_FIRE):
        assert sum(dist.values()) == pytest.approx(1.0)


def test_roll_zero_picks_the_wheel_for_a_capture():
    facts = TriggerFacts(is_capture=True, capturer_value=3, captured_value=3)
    assert weights.roll_skillcheck(facts, 0.0) == WHEEL


def test_roll_near_one_still_picks_the_wheel_for_a_capture():
    facts = TriggerFacts(is_capture=True, capturer_value=9, captured_value=1)
    assert weights.roll_skillcheck(facts, 0.999999) == WHEEL


# ---- deterministic per-ply RNG ---------------------------------------------

def test_ply_roll_is_deterministic():
    first = ply_roll("room-abc", 7)
    repeated = [ply_roll("room-abc", 7) for _ in range(5)]
    assert all(value == first for value in repeated)


def test_ply_roll_varies_by_ply_and_seed():
    assert ply_roll("room-abc", 7) != ply_roll("room-abc", 8)
    assert ply_roll("room-abc", 7) != ply_roll("room-xyz", 7)


def test_ply_roll_in_unit_interval():
    for i in range(500):
        value = ply_roll("seed", i)
        assert 0.0 <= value < 1.0


def test_ply_roll_is_roughly_uniform():
    buckets = Counter(int(ply_roll("seed", i) * 10) for i in range(10000))
    for b in range(10):
        assert 800 < buckets[b] < 1200
