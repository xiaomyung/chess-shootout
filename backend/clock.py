import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pieces import PieceColor


def _opposite(color):
    return PieceColor.BLACK if color == PieceColor.WHITE else PieceColor.WHITE


@dataclass
class Clock:
    initial_seconds: float
    increment_seconds: float
    white_remaining: float
    black_remaining: float
    running_for: Optional[PieceColor] = None
    last_tick_at: Optional[float] = None
    flagged: Optional[PieceColor] = None
    now_provider: Callable[[], float] = field(default=time.monotonic)

    @classmethod
    def create(cls, initial_seconds, increment_seconds, now_provider=time.monotonic):
        return cls(
            initial_seconds=float(initial_seconds),
            increment_seconds=float(increment_seconds),
            white_remaining=float(initial_seconds),
            black_remaining=float(initial_seconds),
            now_provider=now_provider,
        )

    def start(self):
        self.running_for = PieceColor.WHITE
        self.last_tick_at = self.now_provider()

    def tick(self):
        if self.running_for is None or self.last_tick_at is None:
            return
        now = self.now_provider()
        elapsed = now - self.last_tick_at
        self.last_tick_at = now
        if self.running_for == PieceColor.WHITE:
            self.white_remaining -= elapsed
            if self.white_remaining <= 0:
                self.white_remaining = 0
                self.flagged = PieceColor.WHITE
                self.running_for = None
                self.last_tick_at = None
        else:
            self.black_remaining -= elapsed
            if self.black_remaining <= 0:
                self.black_remaining = 0
                self.flagged = PieceColor.BLACK
                self.running_for = None
                self.last_tick_at = None

    def on_move_made(self, mover):
        self.tick()
        if self.flagged is not None:
            return
        if mover == PieceColor.WHITE:
            self.white_remaining += self.increment_seconds
        else:
            self.black_remaining += self.increment_seconds
        self.running_for = _opposite(mover)
        self.last_tick_at = self.now_provider()

    def stop(self):
        self.running_for = None
        self.last_tick_at = None

    def remaining(self, color):
        return self.white_remaining if color == PieceColor.WHITE else self.black_remaining

    def snapshot(self):
        return (
            self.white_remaining,
            self.black_remaining,
            self.running_for,
            self.last_tick_at,
            self.flagged,
        )

    def restore(self, snap):
        (
            self.white_remaining,
            self.black_remaining,
            self.running_for,
            self.last_tick_at,
            self.flagged,
        ) = snap
