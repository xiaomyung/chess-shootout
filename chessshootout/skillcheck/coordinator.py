from chessshootout.skillcheck.locks import MoveLockSet
from chessshootout.skillcheck.rng import move_roll_key, ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind

__all__ = ["SkillCheckCoordinator", "move_roll_key"]


class SkillCheckCoordinator:

    def __init__(self, enabled=False, seed="local"):
        self.enabled = enabled
        self.seed = seed
        self.locks = MoveLockSet()

    def reset(self, enabled=None, seed=None):
        if enabled is not None:
            self.enabled = enabled
        if seed is not None:
            self.seed = seed
        self.locks.clear()

    def clear_locks(self):
        self.locks.clear()

    def lock(self, from_sq, to_sq):
        self.locks.lock(from_sq, to_sq)

    def is_locked(self, from_sq, to_sq):
        return self.locks.is_locked(from_sq, to_sq)

    def select(self, backend, from_sq, to_sq):
        if not self.enabled or self.locks.is_locked(from_sq, to_sq):
            return SkillCheckKind.NONE
        ply_index = len(backend.move_history)
        roll = ply_roll(self.seed, move_roll_key(ply_index, from_sq, to_sq))
        return select_skillcheck(backend, from_sq, to_sq, roll, self.locks)
