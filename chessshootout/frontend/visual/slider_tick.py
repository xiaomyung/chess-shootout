SLIDER_TICK_MIN_INTERVAL_MS = 28


class TickGate:

    def __init__(self, on_tick, min_interval_ms=SLIDER_TICK_MIN_INTERVAL_MS):
        self._on_tick = on_tick
        self._min_interval_ms = min_interval_ms
        self._last_pct = None
        self._last_ms = 0

    def reset(self):
        self._last_pct = None

    def feed(self, ratio, now_ms):
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
