from collections.abc import Callable

SLIDER_TICK_MIN_INTERVAL_MS = 28


class TickGate:
    """
    The clicker behind a dragged control: it watches a 0.0 to 1.0 value and
    fires a tick every time the value crosses a whole percent, so dragging the
    time-picker drum or a volume slider sounds mechanical instead of noisy. It
    holds no pygame state, which is why its cadence is testable on its own
    """

    def __init__(self, on_tick: Callable[[], None] | None,
                 min_interval_ms: int = SLIDER_TICK_MIN_INTERVAL_MS) -> None:
        """
        Build a gate around the sound (or any effect) a drag should trigger.
        The very first value fed to a fresh gate ticks, so a drag is audible
        from its first movement

        :param on_tick: what to run on each tick, or None to disable ticking
        :param min_interval_ms: shortest gap in milliseconds between two ticks,
            which caps how fast a violent drag can machine-gun the sound
        """
        self._on_tick = on_tick
        self._min_interval_ms = min_interval_ms
        self._last_pct = None
        self._last_ms = 0

    def reset(self) -> None:
        """
        Forget the last percent so the next fed value counts as a fresh start
        and ticks even if the control has not moved. Owners call this when a
        new drag begins, which is what gives every drag an opening click
        """
        self._last_pct = None

    def feed(self, ratio: float, now_ms: int) -> None:
        """
        Report where the dragged control is now and let the gate decide whether
        that deserves a tick. Ticks fire only on a whole-percent change and only
        once the minimum interval has passed since the previous one

        :param ratio: control position from 0.0 to 1.0, clamped into that range
        :param now_ms: pygame tick count in milliseconds for this input
        """
        if self._on_tick is None:
            return
        pct = int(round(max(0.0, min(1.0, ratio)) * 100))
        if pct == self._last_pct:
            return
        if self._last_pct is not None and now_ms - self._last_ms < self._min_interval_ms:
            return
        self._last_pct = pct
        self._last_ms = now_ms
        self._on_tick()
