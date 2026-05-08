from dataclasses import dataclass

from backend.pieces import Piece
from backend.utils import Square


@dataclass(frozen=True)
class Premove:
    from_sq: Square
    to_sq: Square
    piece: Piece


def speculative_board(backend, queue):
    grid = [row[:] for row in backend.state]
    for pm in queue:
        grid[pm.to_sq.row][pm.to_sq.col] = grid[pm.from_sq.row][pm.from_sq.col]
        grid[pm.from_sq.row][pm.from_sq.col] = None
    return grid
