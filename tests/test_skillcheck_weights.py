"""Weighted skill-check selection. The seeded roll picks none/wheel/duel in the
locked proportions per trigger: capture brackets keyed on capturer-vs-captured
value (C>V 0/30/70, C==V 50/25/25, C<V 80/15/5), value-scaled checks
(70% duel / 30% wheel of the fire chance), a 10% checkmate duel, and wheel-only
promotion. Capture takes precedence over check/promotion, a forced move never
fires, and the per-ply RNG is deterministic + uniform.

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
DUEL = SkillCheckKind.DUEL

N = 20000


def sweep(facts):
    counts = Counter()
    for i in range(N):
        counts[weights.roll_skillcheck(facts, (i + 0.5) / N)] += 1
    return {k: counts[k] / N for k in (NONE, WHEEL, DUEL)}


def assert_dist(observed, expected, tol=0.001):
    for k in (NONE, WHEEL, DUEL):
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


# ---- capture brackets ------------------------------------------------------

@pytest.mark.parametrize(
    "capturer, captured, expected",
    [
        pytest.param(9, 1, weights.CAPTURE_GREATER, id="queen_takes_pawn_C>V"),
        pytest.param(5, 3, weights.CAPTURE_GREATER, id="rook_takes_minor_C>V"),
        pytest.param(3, 3, weights.CAPTURE_EQUAL, id="bishop_takes_bishop_C==V"),
        pytest.param(5, 5, weights.CAPTURE_EQUAL, id="rook_takes_rook_C==V"),
        pytest.param(1, 9, weights.CAPTURE_LESSER, id="pawn_takes_queen_C<V"),
        pytest.param(3, 5, weights.CAPTURE_LESSER, id="minor_takes_rook_C<V"),
    ],
)
def test_capture_bracket_distribution(capturer, captured, expected):
    facts = TriggerFacts(is_capture=True, capturer_value=capturer, captured_value=captured)
    assert_dist(sweep(facts), expected)


def test_capture_greater_is_seventy_percent_duel():
    assert weights.CAPTURE_GREATER == {NONE: 0.0, WHEEL: 0.30, DUEL: 0.70}


def test_capture_equal_is_fifty_fifty_split():
    assert weights.CAPTURE_EQUAL == {NONE: 0.50, WHEEL: 0.25, DUEL: 0.25}


def test_capture_lesser_rarely_fires():
    assert weights.CAPTURE_LESSER == {NONE: 0.80, WHEEL: 0.15, DUEL: 0.05}


# ---- precedence: capture wins over check / checkmate / promotion ------------

def test_capture_takes_precedence_over_check():
    facts = TriggerFacts(
        is_capture=True, capturer_value=9, captured_value=1,
        is_check=True, checker_value=9,
    )
    assert_dist(sweep(facts), weights.CAPTURE_GREATER)


def test_capture_takes_precedence_over_checkmate():
    facts = TriggerFacts(
        is_capture=True, capturer_value=3, captured_value=3,
        is_check=True, is_checkmate=True, checker_value=3,
    )
    assert_dist(sweep(facts), weights.CAPTURE_EQUAL)


def test_capture_takes_precedence_over_promotion():
    facts = TriggerFacts(
        is_capture=True, capturer_value=1, captured_value=5,
        is_promotion=True, promo_value=9,
    )
    assert_dist(sweep(facts), weights.CAPTURE_LESSER)


# ---- forced-move guard -----------------------------------------------------

@pytest.mark.parametrize(
    "facts",
    [
        TriggerFacts(is_capture=True, capturer_value=9, captured_value=1, is_forced=True),
        TriggerFacts(is_check=True, checker_value=9, is_forced=True),
        TriggerFacts(is_checkmate=True, is_forced=True),
        TriggerFacts(is_promotion=True, promo_value=9, is_forced=True),
    ],
)
def test_forced_move_never_fires(facts):
    assert_dist(sweep(facts), {NONE: 1.0})


# ---- checks scale by checker value, duel-heavy -----------------------------

@pytest.mark.parametrize(
    "checker_value, fire",
    [(1, 0.15), (3, 0.25), (5, 0.35), (9, 0.50)],
)
def test_check_distribution_value_scaled(checker_value, fire):
    facts = TriggerFacts(is_check=True, checker_value=checker_value)
    expected = {NONE: 1 - fire, WHEEL: fire * 0.30, DUEL: fire * 0.70}
    assert_dist(sweep(facts), expected)


def test_check_is_duel_heavy():
    assert weights.CHECK_DUEL_SHARE > weights.CHECK_WHEEL_SHARE
    assert weights.CHECK_DUEL_SHARE + weights.CHECK_WHEEL_SHARE == pytest.approx(1.0)


def test_unknown_checker_value_never_fires():
    facts = TriggerFacts(is_check=True, checker_value=0)
    assert_dist(sweep(facts), {NONE: 1.0})


# ---- checkmate: 10% duel, never wheel --------------------------------------

def test_checkmate_distribution():
    facts = TriggerFacts(is_checkmate=True, is_check=True, checker_value=9)
    assert_dist(sweep(facts), {NONE: 0.90, WHEEL: 0.0, DUEL: 0.10})


# ---- promotion: wheel only, by chosen piece --------------------------------

@pytest.mark.parametrize(
    "promo_value, fire",
    [(9, 0.60), (5, 0.40), (3, 0.20)],
)
def test_promotion_distribution_wheel_only(promo_value, fire):
    facts = TriggerFacts(is_promotion=True, promo_value=promo_value)
    assert_dist(sweep(facts), {NONE: 1 - fire, WHEEL: fire, DUEL: 0.0})


def test_promotion_never_duels():
    for promo_value in (3, 5, 9):
        assert weights.promotion_distribution(promo_value)[DUEL] == 0.0


# ---- quiet (non-triggering) move -------------------------------------------

def test_quiet_move_never_fires():
    assert_dist(sweep(TriggerFacts()), {NONE: 1.0})


# ---- selector correctness --------------------------------------------------

def test_every_distribution_sums_to_one():
    dists = [
        weights.CAPTURE_GREATER, weights.CAPTURE_EQUAL, weights.CAPTURE_LESSER,
        weights.checkmate_distribution(),
        *[weights.check_distribution(v) for v in (1, 3, 5, 9)],
        *[weights.promotion_distribution(v) for v in (3, 5, 9)],
    ]
    for dist in dists:
        assert sum(dist.values()) == pytest.approx(1.0)


def test_roll_zero_picks_first_nonzero_kind():
    equal = TriggerFacts(is_capture=True, capturer_value=3, captured_value=3)
    assert weights.roll_skillcheck(equal, 0.0) == NONE
    greater = TriggerFacts(is_capture=True, capturer_value=9, captured_value=1)
    assert weights.roll_skillcheck(greater, 0.0) == WHEEL


def test_roll_near_one_picks_last_kind():
    facts = TriggerFacts(is_capture=True, capturer_value=9, captured_value=1)
    assert weights.roll_skillcheck(facts, 0.999999) == DUEL


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
