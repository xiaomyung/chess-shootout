from dataclasses import dataclass

from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece
from chessshootout.backend.utils import Square
from chessshootout.domain.match import Match


@dataclass(frozen=True)
class Premove:
    """
    One move a player has queued up to play the instant it becomes their turn.
    Queueing only checks that the piece could pseudo-legally reach the target,
    so a premove may still turn out illegal and be dropped when the turn comes
    """

    from_sq: Square
    to_sq: Square
    piece: Piece


def speculative_board(backend: Backend | Match,
                      queue: list[Premove]) -> list[list[Piece | None]]:
    """
    Project a queue of premoves onto a copy of the live position so the board
    can draw where the player expects their pieces to be. Each premove moves
    whatever now stands on its origin in the projection, which is what lets a
    bouncing chain relay through a square the same piece has just left; the
    real position is never touched

    :param backend: live game to read the current position from, the engine or
        the Match wrapper around it
    :param queue: premoves in the order the player queued them
    :returns: an 8x8 grid with the queue applied, None where a square is empty
    """
    grid = [row[:] for row in backend.state]
    for pm in queue:
        grid[pm.to_sq.row][pm.to_sq.col] = grid[pm.from_sq.row][pm.from_sq.col]
        grid[pm.from_sq.row][pm.from_sq.col] = None
    return grid
