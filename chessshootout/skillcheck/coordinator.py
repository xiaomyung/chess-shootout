from chessshootout.skillcheck.locks import MoveLockSet
from chessshootout.skillcheck.online import select_kind
from chessshootout.skillcheck.rng import move_roll_key
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
        if not self.enabled:
            return SkillCheckKind.NONE
        return select_kind(self.seed, len(backend.move_history),
                           backend, from_sq, to_sq, self.locks)
