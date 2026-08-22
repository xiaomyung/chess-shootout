from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import Square
from chessshootout.skillcheck.locks import MoveLockSet
from chessshootout.skillcheck.online import select_kind
from chessshootout.skillcheck.rng import move_roll_key
from chessshootout.skillcheck.types import SkillCheckKind

__all__ = ["SkillCheckCoordinator", "move_roll_key"]


class SkillCheckCoordinator:
    """
    The pygame-free seam that decides whether a move fires a skill check,
    shared by the local game screen and the server-side selection path. It
    owns the three things that decision needs: whether checks are on at all,
    the seed the per-move roll is drawn from, and the moves already locked
    this turn
    """

    def __init__(self, enabled: bool = False, seed: str = "local") -> None:
        """
        Set up the coordinator for one game. A game screen keeps a single
        instance for its whole life and reconfigures it through reset rather
        than replacing it

        :param enabled: False for a casual game, where no move ever fires a
            check
        :param seed: seed the per-move rolls are drawn from; online it is only
            a placeholder, since the server holds the real secret and decides
            for both players
        """
        self.enabled = enabled
        self.seed = seed
        self.locks = MoveLockSet()

    def reset(self, enabled: bool | None = None, seed: str | None = None) -> None:
        """
        Start a fresh game: drop every lock and optionally change the rules.
        Leaving a setting as None keeps the current one, so a bare reset is
        the same-rules, clean-slate call

        :param enabled: new on/off setting, or None to keep the current one
        :param seed: new roll seed, or None to keep the current one
        """
        if enabled is not None:
            self.enabled = enabled
        if seed is not None:
            self.seed = seed
        self.locks.clear()

    def clear_locks(self) -> None:
        """
        Release the moves locked this turn, done once a ply lands and whenever
        the game is rewound or restarted
        """
        self.locks.clear()

    def lock(self, from_sq: Square, to_sq: Square) -> None:
        """
        Forbid a move for the rest of the turn after its check was lost, which
        is what makes a missed shot cost the player something

        :param from_sq: square the failed move started from
        :param to_sq: square it was aimed at
        """
        self.locks.lock(from_sq, to_sq)

    def is_locked(self, from_sq: Square, to_sq: Square) -> bool:
        """
        Say whether a move is currently forbidden, asked by the board before
        it lets a piece be dropped on that square

        :param from_sq: square the move would start from
        :param to_sq: square it would land on
        :returns: True when that pair was already fluffed this turn
        """
        return self.locks.is_locked(from_sq, to_sq)

    def select(self, backend: Backend, from_sq: Square, to_sq: Square) -> SkillCheckKind:
        """
        Decide which mini-game, if any, a move sets off -- the call the local
        move gate makes before letting a capture or promotion through. A
        disabled coordinator and a locked move both answer NONE

        :param backend: engine holding the position the move is judged against
        :param from_sq: square the piece would leave
        :param to_sq: square it would land on
        :returns: the kind to run, NONE to let the move simply land
        """
        if not self.enabled:
            return SkillCheckKind.NONE
        return select_kind(self.seed, len(backend.move_history),
                           backend, from_sq, to_sq, self.locks)
