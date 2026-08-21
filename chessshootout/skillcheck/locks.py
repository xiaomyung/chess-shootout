from collections.abc import Iterator

from chessshootout.backend.utils import Square


class MoveLockSet:
    """
    The moves a player has already fluffed this turn. Losing a skill check
    locks that exact (from, to) pair until a ply lands, so nobody can retry
    the same capture over and over until the dice fall their way
    """

    def __init__(self) -> None:
        """
        Start with nothing locked, which is also the state a completed ply and
        a new game return the set to
        """
        self._locked: set[tuple[Square, Square]] = set()

    def lock(self, from_sq: Square, to_sq: Square) -> None:
        """
        Forbid one move for the rest of the turn, called the moment its skill
        check is lost. Only this exact pair is locked -- the same piece may
        still take the same victim from somewhere else

        :param from_sq: square the failed move started from
        :param to_sq: square it was aimed at
        """
        self._locked.add((from_sq, to_sq))

    def is_locked(self, from_sq: Square, to_sq: Square) -> bool:
        """
        Say whether this move is currently forbidden. The board asks before it
        lets a piece be dropped, and the move gate asks again so a locked move
        can never reach the engine

        :param from_sq: square the move would start from
        :param to_sq: square it would land on
        :returns: True when that pair was already fluffed this turn
        """
        return (from_sq, to_sq) in self._locked

    def clear(self) -> None:
        """
        Release every lock, done once a ply actually lands and whenever a game
        starts over; locks are per-turn and are never carried into the next
        """
        self._locked.clear()

    def __contains__(self, key: object) -> bool:
        """
        Support the `(from_sq, to_sq) in locks` spelling, which is how the
        trigger and selection code tests locks so it can take either this set
        or a plain set of pairs

        :param key: the (from square, to square) pair being tested
        :returns: True when that pair is locked
        """
        return key in self._locked

    def __iter__(self) -> Iterator[tuple[Square, Square]]:
        """
        Walk the locked pairs, so tests and debug views can report what a
        player has already lost this turn

        :returns: iterator over (from square, to square) pairs, unordered
        """
        return iter(self._locked)

    def __len__(self) -> int:
        """
        Count the moves locked this turn, which is how a caller cheaply tells
        a clean turn from one where a check has already been lost

        :returns: number of locked (from, to) pairs
        """
        return len(self._locked)
