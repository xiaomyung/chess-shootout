from dataclasses import dataclass
from typing import Callable, Optional

from backend.utils import Square
from pieces import Piece


@dataclass
class PieceAnimation:
    from_sq: Square
    to_sq: Square
    piece: Piece
    start_ms: int
    duration_ms: int
    on_complete: Optional[Callable[[], None]] = None

    def progress(self, now_ms):
        if self.duration_ms <= 0:
            return 1.0
        return min(max((now_ms - self.start_ms) / self.duration_ms, 0.0), 1.0)

    def is_done(self, now_ms):
        return self.progress(now_ms) >= 1.0
