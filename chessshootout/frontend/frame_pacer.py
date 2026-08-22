import time
from collections.abc import Callable


class FramePacer:
    """
    The metronome the game loop runs on, holding the frame rate steady between
    the end of one frame's work and the start of the next. It counts forward in
    absolute deadlines rather than sleeping a rounded number of milliseconds per
    frame, which is what the millisecond-quantised pacing it replaced did and
    what cost a wide window a large slice of its frame rate
    """

    def __init__(self, target_fps: int, now: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        """
        Set the pace, and the two clock calls the pacing stands on so tests can
        drive it without ever really waiting. The first wait establishes the
        baseline, so building this early costs nothing. A rate of zero or less
        describes no frame at all and is turned away here, where the caller can
        see what it asked for, rather than dividing by zero

        :param target_fps: frames per second to hold, which must be positive
        :param now: reads a monotonic clock in seconds
        :param sleep: waits the given number of seconds
        """
        if target_fps <= 0:
            raise ValueError(f"target_fps must be positive, got {target_fps}")
        self.period = 1.0 / target_fps
        self._now = now
        self._sleep = sleep
        self._deadline: float | None = None

    def wait(self) -> None:
        """
        Hold the frame until its deadline, called once a frame after the work
        is done and before the finished frame is presented. Each deadline is
        exactly one period after the last, so a frame that ran slightly long is
        paid back by the ones after it instead of accumulating as drift; a
        frame that overran a whole period gives up on catching up and re-bases
        from now, which stops a stall from banking sleep it would then spend
        """
        now = self._now()
        if self._deadline is None:
            self._deadline = now
        self._deadline += self.period
        if self._deadline <= now:
            self._deadline = now
            return
        self._sleep(self._deadline - now)
