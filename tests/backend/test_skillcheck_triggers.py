"""Trigger fact-extraction from a real Backend move + the per-turn move-lock.

compute_facts probes a candidate move on a deepcopy and reports what fired:
capture (with capturer/captured values), promotion (with the chosen piece's
value), and whether the mover was forced. Checks and checkmates were removed --
a non-capturing check or mate is a quiet move that never fires a skill-check.
The lock-set forbids the exact (from, to) of a failed move for the turn; a
forced count that drops to one (via locks) means the skill-check is skipped so a
player is never stranded.
"""

from chessshootout.skillcheck import triggers
from chessshootout.skillcheck.locks import MoveLockSet
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.weights import CAPTURE_WHEEL_SHARE
from tests.helpers import BLACK, K, P, Q, R, WHITE, make_backend, piece, sq

WHEEL = SkillCheckKind.WHEEL
AIM = SkillCheckKind.AIM
WHACK = SkillCheckKind.WHACK
COMBO = SkillCheckKind.COMBO
NONE = SkillCheckKind.NONE


def test_queen_takes_pawn_is_capture_C_greater_V():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    })
    facts = triggers.compute_facts(backend, sq(4, 3), sq(3, 3))
    assert facts.is_capture is True
    assert facts.capturer_value == 9
    assert facts.captured_value == 1
    assert facts.is_promotion is False


def test_pawn_takes_queen_is_capture_C_less_V():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 4): piece(P, WHITE), sq(3, 3): piece(Q, BLACK),
    })
    facts = triggers.compute_facts(backend, sq(4, 4), sq(3, 3))
    assert facts.is_capture is True
    assert facts.capturer_value == 1
    assert facts.captured_value == 9


def test_non_capturing_check_does_not_fire():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(7, 0): piece(R, WHITE),
    })
    facts = triggers.compute_facts(backend, sq(7, 0), sq(0, 0))
    assert facts.is_capture is False
    assert facts.is_promotion is False
    for roll in (0.0, 0.25, 0.5, 0.75, 0.999):
        assert triggers.select_skillcheck(backend, sq(7, 0), sq(0, 0), roll) == NONE


def test_back_rank_checkmate_does_not_fire():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 7): piece(K, BLACK),
        sq(1, 6): piece(P, BLACK), sq(1, 7): piece(P, BLACK),
        sq(7, 0): piece(R, WHITE),
    })
    facts = triggers.compute_facts(backend, sq(7, 0), sq(0, 0))
    assert facts.is_capture is False
    for roll in (0.0, 0.5, 0.999):
        assert triggers.select_skillcheck(backend, sq(7, 0), sq(0, 0), roll) == NONE


def test_quiet_promotion_is_a_promotion_not_a_capture():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(3, 4): piece(K, BLACK),
        sq(7, 7): piece(R, WHITE), sq(1, 0): piece(P, WHITE),
    })
    facts = triggers.compute_facts(backend, sq(1, 0), sq(0, 0))
    assert facts.is_promotion is True
    assert facts.is_capture is False


def test_capture_promotion_is_capture_not_promotion_weighting():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(4, 4): piece(K, BLACK),
        sq(1, 1): piece(P, WHITE), sq(0, 0): piece(R, BLACK),
    })
    facts = triggers.compute_facts(backend, sq(1, 1), sq(0, 0))
    assert facts.is_capture is True
    assert facts.capturer_value == 1
    assert facts.captured_value == 5
    assert facts.is_promotion is True


def test_quiet_move_has_no_trigger():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(7, 0): piece(R, WHITE),
    })
    facts = triggers.compute_facts(backend, sq(7, 4), sq(6, 4))
    assert (facts.is_capture, facts.is_promotion) == (False, False)


def test_illegal_move_returns_none():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK), sq(7, 7): piece(R, WHITE),
    })
    assert triggers.compute_facts(backend, sq(7, 4), sq(5, 4)) is None


def _two_move_king():
    return make_backend({
        sq(7, 0): piece(K, WHITE), sq(5, 2): piece(K, BLACK), sq(1, 7): piece(P, BLACK),
    })


def test_two_legal_moves_is_not_forced():
    backend = _two_move_king()
    assert triggers.total_legal_moves(backend, WHITE) == 2
    assert triggers.forced_move(backend) is False


def test_lock_reducing_to_one_move_is_forced():
    backend = _two_move_king()
    locks = MoveLockSet()
    locks.lock(sq(7, 0), sq(6, 0))
    assert triggers.forced_move(backend, locked=locks) is True


def test_forced_move_never_fires_a_skillcheck():
    backend = _two_move_king()
    locks = MoveLockSet()
    locks.lock(sq(7, 0), sq(6, 0))
    facts = triggers.compute_facts(backend, sq(7, 0), sq(7, 1), locked=locks)
    assert facts.is_forced is True
    assert triggers.select_skillcheck(backend, sq(7, 0), sq(7, 1), 0.99, locked=locks) == NONE


def test_select_uses_capture_bracket():
    backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    })
    assert triggers.select_skillcheck(backend, sq(4, 3), sq(3, 3), 0.0) == WHEEL
    assert triggers.select_skillcheck(backend, sq(4, 3), sq(3, 3), 0.3) == AIM
    assert triggers.select_skillcheck(backend, sq(4, 3), sq(3, 3), 0.6) == WHACK
    assert triggers.select_skillcheck(backend, sq(4, 3), sq(3, 3), 0.99) == COMBO
    assert CAPTURE_WHEEL_SHARE == 0.25


def test_select_illegal_move_is_none():
    backend = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    assert triggers.select_skillcheck(backend, sq(7, 4), sq(5, 4), 0.5) == NONE


def test_move_lock_set_basic_operations():
    locks = MoveLockSet()
    assert locks.is_locked(sq(1, 0), sq(0, 0)) is False
    locks.lock(sq(1, 0), sq(0, 0))
    assert locks.is_locked(sq(1, 0), sq(0, 0)) is True
    assert (sq(1, 0), sq(0, 0)) in locks
    assert len(locks) == 1
    locks.clear()
    assert len(locks) == 0
    assert locks.is_locked(sq(1, 0), sq(0, 0)) is False
