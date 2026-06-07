"""The turn-based Duel engine: the two captured/capturing pieces fight on a
shrinking 4x4 -> 3x3 -> 2x2 arena (4 plies per size), attacker fires first,
first clean shot wins, and an unresolved duel hands the win to the defender
(the capture fails). Firepower scales with piece value (range pawn1/minor2/
rook3/queen,king any); queen & rook shotguns add +1 effective kill range.

The engine is fully deterministic with NO randomness -- two humans supply the
intents and the server replays them -- so a fixed intent log always yields the
identical winner and final positions (the perft-style determinism guarantee
the server relies on for authority + resume).
"""

import pytest

from chessshootout.backend.pieces import PieceType
from chessshootout.skillcheck import duel
from chessshootout.skillcheck.duel import (
    ATTACKER, DEFENDER, DuelEngine, DuelIntent, chebyshev,
)

P, N, B, R, Q, K = (PieceType.PAWN, PieceType.KNIGHT, PieceType.BISHOP,
                    PieceType.ROOK, PieceType.QUEEN, PieceType.KING)


# ---- firepower table -------------------------------------------------------

@pytest.mark.parametrize(
    "ptype, expected_range, shotgun",
    [
        (P, 1, False), (N, 2, False), (B, 2, False),
        (R, 3, True), (Q, duel.RANGE_ANY, True), (K, duel.RANGE_ANY, False),
    ],
)
def test_firepower_by_piece(ptype, expected_range, shotgun):
    assert duel.fighter_range(ptype) == expected_range
    assert duel.is_shotgun(ptype) is shotgun


def test_chebyshev_distance():
    assert chebyshev((0, 0), (3, 1)) == 3
    assert chebyshev((2, 2), (2, 2)) == 0
    assert chebyshev((0, 0), (2, 3)) == 3


# ---- start layout ----------------------------------------------------------

def test_pieces_start_on_opposite_corners():
    eng = DuelEngine(Q, P)
    assert eng.size == 4
    assert eng.attacker_pos == (3, 0)
    assert eng.defender_pos == (0, 3)
    assert eng.to_move == ATTACKER


# ---- legal movement --------------------------------------------------------

def test_legal_steps_from_corner_are_three():
    eng = DuelEngine(P, P)
    assert sorted(eng.legal_steps(ATTACKER)) == sorted([(2, 0), (2, 1), (3, 1)])


def test_cannot_step_onto_opponent():
    eng = DuelEngine(P, P)
    eng.attacker_pos = (1, 1)
    eng.defender_pos = (0, 1)
    assert (0, 1) not in eng.legal_steps(ATTACKER)


def test_illegal_step_raises():
    eng = DuelEngine(P, P)
    with pytest.raises(ValueError):
        eng.apply(DuelIntent(step=(0, 0)))


# ---- long-range attacker wins immediately ----------------------------------

def test_queen_attacker_hits_turn_one():
    eng = DuelEngine(Q, P)
    eng.apply(DuelIntent(fire=eng.defender_pos))
    assert eng.is_over()
    assert eng.winner == ATTACKER
    assert eng.capture_succeeds() is True


def test_king_attacker_hits_anywhere():
    eng = DuelEngine(K, P)
    assert eng.can_hit_from(ATTACKER, eng.attacker_pos) is True


def test_pawn_attacker_cannot_hit_across_board():
    eng = DuelEngine(P, P)
    assert eng.can_hit_from(ATTACKER, eng.attacker_pos) is False
    with pytest.raises(ValueError):
        eng.apply(DuelIntent(fire=eng.defender_pos))


# ---- shotgun scatter extends kill range by one -----------------------------

def test_rook_shotgun_kills_at_range_four():
    eng = DuelEngine(R, P)
    eng.attacker_pos = (3, 0)
    eng.defender_pos = (3, 3)
    assert chebyshev(eng.attacker_pos, eng.defender_pos) == 3
    eng.apply(DuelIntent(fire=(3, 2)))
    assert eng.winner == ATTACKER


def test_nonshotgun_must_hit_exact_cell():
    eng = DuelEngine(B, R)
    eng.attacker_pos = (2, 1)
    eng.defender_pos = (2, 3)
    assert eng.fire_hits(ATTACKER, (2, 2)) is False
    assert eng.fire_hits(ATTACKER, (2, 3)) is True


def test_fire_out_of_range_raises():
    eng = DuelEngine(B, P)
    eng.attacker_pos = (3, 0)
    eng.defender_pos = (0, 3)
    with pytest.raises(ValueError):
        eng.apply(DuelIntent(fire=(0, 3)))


# ---- attacker fires first, each round --------------------------------------

def test_turn_alternates_attacker_first():
    eng = DuelEngine(P, P)
    assert eng.to_move == ATTACKER
    eng.apply(DuelIntent(step=(2, 1)))
    assert eng.to_move == DEFENDER
    eng.apply(DuelIntent(step=(1, 2)))
    assert eng.to_move == ATTACKER


# ---- shrink schedule + no-hit fallback -------------------------------------

def test_unresolved_duel_shrinks_then_defender_wins():
    eng = DuelEngine(P, P)
    sizes_seen = [eng.size]
    for _ in range(duel.DUEL_PLIES_PER_SIZE * len(duel.DUEL_SIZES)):
        if eng.is_over():
            break
        eng.apply(DuelIntent())
        sizes_seen.append(eng.size)
    assert eng.is_over()
    assert eng.winner == DEFENDER
    assert eng.capture_succeeds() is False
    assert 4 in sizes_seen and 3 in sizes_seen and 2 in sizes_seen


def test_shrink_clamps_positions_inside_board():
    eng = DuelEngine(P, P)
    eng.attacker_pos = (3, 3)
    eng.defender_pos = (3, 2)
    for _ in range(duel.DUEL_PLIES_PER_SIZE):
        eng.apply(DuelIntent())
    assert eng.size == 3
    assert 0 <= eng.attacker_pos[0] < 3 and 0 <= eng.attacker_pos[1] < 3
    assert 0 <= eng.defender_pos[0] < 3 and 0 <= eng.defender_pos[1] < 3
    assert eng.attacker_pos != eng.defender_pos


# ---- a real back-and-forth: pawn closes and fires --------------------------

def test_pawn_maneuvers_into_range_and_wins():
    eng = DuelEngine(P, P)
    eng.apply(DuelIntent(step=(2, 1)))
    eng.apply(DuelIntent(step=(1, 2)))
    eng.apply(DuelIntent(step=(2, 2), fire=(1, 2)))
    assert eng.winner == ATTACKER
    assert eng.attacker_pos == (2, 2)


# ---- play after decision is rejected ---------------------------------------

def test_apply_after_win_raises():
    eng = DuelEngine(Q, P)
    eng.apply(DuelIntent(fire=eng.defender_pos))
    with pytest.raises(ValueError):
        eng.apply(DuelIntent())


# ---- determinism: a fixed intent log replays identically -------------------

def _scripted_log():
    return [
        DuelIntent(step=(2, 1)),
        DuelIntent(step=(1, 2)),
        DuelIntent(step=(2, 2)),
        DuelIntent(step=(1, 1), fire=None),
        DuelIntent(step=(1, 2)),
        DuelIntent(fire=(1, 2)),
    ]


def _replay(log):
    eng = DuelEngine(N, B)
    for intent in log:
        if eng.is_over():
            break
        eng.apply(intent)
    return eng


def test_fixed_intent_log_is_deterministic():
    log = _scripted_log()
    a = _replay(log)
    b = _replay(log)
    assert (a.winner, a.attacker_pos, a.defender_pos) == (b.winner, b.attacker_pos, b.defender_pos)
