import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from chessshootout.backend.pieces import PieceColor, opponent_of


log = logging.getLogger("chess.backend")


@dataclass
class Clock:
    """
    The game clock: how many seconds each side has left, which side is counting
    down right now, and who has run out. One clock belongs to a game, and every
    surface that shows or checks time -- the on-screen clocks, the server sweep,
    the give-time button -- reads it instead of timing anything itself
    """

    initial_seconds: float
    increment_seconds: float
    white_remaining: float
    black_remaining: float
    running_for: PieceColor | None = None
    last_tick_at: float | None = None
    flagged: PieceColor | None = None
    now_provider: Callable[[], float] = field(default=time.monotonic)

    @classmethod
    def create(
        cls,
        initial_seconds: float,
        increment_seconds: float,
        now_provider: Callable[[], float] = time.monotonic,
    ) -> "Clock":
        """
        Build the clock for a fresh game, with both sides holding the full
        starting time and neither counting down yet. This is the only way a
        clock is made, since the bare dataclass would leave both remaining-time
        fields to be filled in by hand

        :param initial_seconds: starting time per side in seconds
        :param increment_seconds: seconds handed back to a player each time
            they complete a move
        :param now_provider: source of monotonic seconds; tests pass a fake one
            so time can be advanced deliberately
        :returns: a clock waiting for start()
        """
        return cls(
            initial_seconds=float(initial_seconds),
            increment_seconds=float(increment_seconds),
            white_remaining=float(initial_seconds),
            black_remaining=float(initial_seconds),
            now_provider=now_provider,
        )

    def start(self) -> None:
        """
        Start the game clock on White, who moves first. Nothing counts down
        until this is called, so a clock can be built well before the first
        move is due
        """
        self.running_for = PieceColor.WHITE
        self.last_tick_at = self.now_provider()

    def tick(self) -> None:
        """
        Charge the side to move for the real time gone by since the previous
        tick; this is what actually makes the clock run down, and callers do it
        once per frame on the client and once per sweep step on the server.
        Reaching zero latches that side as flagged and stops the clock, so a
        flag is recorded exactly once
        """
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

    def on_move_made(self, mover: PieceColor) -> None:
        """
        Settle the clock for a ply that has just landed: charge the mover for
        the time they thought, add their increment, then hand the countdown to
        the opponent. A mover whose time ran out while thinking flags here
        instead and receives no increment

        :param mover: side that played the ply
        """
        self.tick()
        if self.flagged is not None:
            return
        if mover == PieceColor.WHITE:
            self.white_remaining += self.increment_seconds
        else:
            self.black_remaining += self.increment_seconds
        self.running_for = opponent_of(mover)
        self.last_tick_at = self.now_provider()

    def stop(self) -> None:
        """
        Freeze the clock without flagging anybody, which is what happens when a
        game ends on the board -- checkmate, stalemate, resignation or an agreed
        result. Both remaining times stay put, so the final clocks stay readable
        """
        self.running_for = None
        self.last_tick_at = None

    def add_time(self, color: PieceColor, seconds: float) -> float:
        """
        Hand one side extra seconds from the give-time button, capped so nobody
        can end up richer than the time control started them with. A game that
        already has a flag refuses the gift outright

        :param color: side receiving the time
        :param seconds: seconds asked for; only the part that fits under the
            starting-time cap is granted
        :returns: seconds actually added, 0.0 when none could be
        """
        if self.flagged is not None:
            return 0.0
        remaining = self.remaining(color)
        headroom = max(self.initial_seconds - remaining, 0.0)
        added = min(float(seconds), headroom)
        if added <= 0:
            return 0.0
        if color == PieceColor.WHITE:
            self.white_remaining += added
        else:
            self.black_remaining += added
        return added

    def remaining(self, color: PieceColor) -> float:
        """
        Read one side's time left, the number the clock widgets draw and the
        server copies into every clock snapshot it sends

        :param color: side to read
        :returns: seconds remaining for that side
        """
        return self.white_remaining if color == PieceColor.WHITE else self.black_remaining

    def snapshot(self) -> tuple[float, float, PieceColor | None, float | None, PieceColor | None]:
        """
        Capture the whole clock so an undo or an agreed takeback can put it back
        exactly as it was. The move history stores one snapshot per ply, which
        is why the running side and the last-tick stamp travel along with the
        two remaining times

        :returns: white remaining, black remaining, running side, last-tick
            timestamp in monotonic seconds, and the flagged side
        """
        return (
            self.white_remaining,
            self.black_remaining,
            self.running_for,
            self.last_tick_at,
            self.flagged,
        )

    def restore(
        self,
        snap: tuple[float, float, PieceColor | None, float | None, PieceColor | None],
    ) -> None:
        """
        Put the clock back to a captured state, which is how a player gets their
        time back when a ply is undone. Everything outside the snapshot -- the
        time control and the time source -- is left alone

        :param snap: tuple previously produced by snapshot()
        """
        (
            self.white_remaining,
            self.black_remaining,
            self.running_for,
            self.last_tick_at,
            self.flagged,
        ) = snap

    def restore_from_server(
        self,
        white_remaining: float,
        black_remaining: float,
        running_for: str | None,
    ) -> None:
        """
        Adopt the clock the server sent, which is the last word on both times in
        an online game. The local countdown is re-anchored to now, so the
        seconds the message spent in flight are not charged to anyone twice

        :param white_remaining: seconds left for White as the server sees it
        :param black_remaining: seconds left for Black as the server sees it
        :param running_for: side counting down, spelled as it is on the wire;
            None leaves the clock stopped, and so does any word this does not
            recognise -- that one is taken tolerantly but logged as degraded
        """
        self.white_remaining = float(white_remaining)
        self.black_remaining = float(black_remaining)
        if running_for == "white":
            self.running_for = PieceColor.WHITE
        elif running_for == "black":
            self.running_for = PieceColor.BLACK
        else:
            if running_for is not None:
                log.warning("clock sync: unknown running_for=%r, leaving the clock stopped",
                            running_for)
            self.running_for = None
        self.last_tick_at = self.now_provider() if self.running_for is not None else None
