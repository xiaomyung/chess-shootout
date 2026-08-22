from dataclasses import dataclass
from typing import Callable

from chessshootout.backend.utils import Square
from chessshootout.backend.pieces import Piece


@dataclass
class PieceAnimation:
    """
    One piece travelling between two squares on screen. The board keeps a list
    of these and interpolates each one while drawing, which is why a move is
    never drawn as a jump; the same record also carries the bump used when a
    move is refused and the callback that runs once the piece lands
    """

    from_sq: Square
    to_sq: Square
    piece: Piece
    start_ms: int
    duration_ms: int
    on_complete: Callable[[], None] | None = None
    bump: bool = False

    def progress(self, now_ms: int) -> float:
        """
        How far along the travel is at this frame, which the board turns into
        a screen position through its easing. A zero-length animation reads as
        finished straight away rather than dividing by zero

        :param now_ms: pygame tick count in milliseconds for the current frame
        :returns: fraction from 0.0 at the start square to 1.0 at the target
        """
        if self.duration_ms <= 0:
            return 1.0
        return min(max((now_ms - self.start_ms) / self.duration_ms, 0.0), 1.0)

    def is_done(self, now_ms: int) -> bool:
        """
        Say whether the piece has arrived, which is the board's cue to drop the
        animation, draw the piece on its square again and run on_complete

        :param now_ms: pygame tick count in milliseconds for the current frame
        :returns: True once the full duration has elapsed
        """
        return self.progress(now_ms) >= 1.0
