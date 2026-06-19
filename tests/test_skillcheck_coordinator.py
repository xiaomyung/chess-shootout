"""The pygame-free orchestration seam shared by the local frontend and the
authoritative server: it owns enabled/seed/locks, derives a deterministic
per-move roll (so server and client agree), and decides which skill-check (if
any) a move triggers. Casual games (disabled) never fire one, and a locked move
is treated as no-fire (the UI blocks it from being attempted at all).
"""

from chessshootout.skillcheck.coordinator import SkillCheckCoordinator, move_roll_key
from chessshootout.skillcheck.types import SkillCheckKind
from tests.helpers import BLACK, K, P, Q, WHITE, make_backend, piece, sq

NONE = SkillCheckKind.NONE


def _queen_takes_pawn():
    return make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    })


def test_disabled_coordinator_never_fires():
    coord = SkillCheckCoordinator(enabled=False, seed="s")
    backend = _queen_takes_pawn()
    assert coord.select(backend, sq(4, 3), sq(3, 3)) == NONE


def test_shootout_fires_on_capture():
    coord = SkillCheckCoordinator(enabled=True, seed="s")
    backend = _queen_takes_pawn()
    assert coord.select(backend, sq(4, 3), sq(3, 3)) != NONE


def test_selection_is_deterministic_for_seed_and_move():
    backend = _queen_takes_pawn()
    a = SkillCheckCoordinator(enabled=True, seed="game-7").select(backend, sq(4, 3), sq(3, 3))
    b = SkillCheckCoordinator(enabled=True, seed="game-7").select(backend, sq(4, 3), sq(3, 3))
    assert a == b


def test_locked_move_does_not_fire():
    coord = SkillCheckCoordinator(enabled=True, seed="s")
    coord.lock(sq(4, 3), sq(3, 3))
    backend = _queen_takes_pawn()
    assert coord.is_locked(sq(4, 3), sq(3, 3)) is True
    assert coord.select(backend, sq(4, 3), sq(3, 3)) == NONE


def test_reset_updates_flags_and_clears_locks():
    coord = SkillCheckCoordinator(enabled=False, seed="old")
    coord.lock(sq(1, 0), sq(0, 0))
    coord.reset(enabled=True, seed="new")
    assert coord.enabled is True
    assert coord.seed == "new"
    assert len(coord.locks) == 0


def test_roll_key_is_move_specific():
    assert move_roll_key(3, sq(4, 3), sq(3, 3)) != move_roll_key(3, sq(4, 3), sq(2, 3))
    assert move_roll_key(3, sq(4, 3), sq(3, 3)) != move_roll_key(4, sq(4, 3), sq(3, 3))
    first = move_roll_key(3, sq(4, 3), sq(3, 3))
    assert move_roll_key(3, sq(4, 3), sq(3, 3)) == first
