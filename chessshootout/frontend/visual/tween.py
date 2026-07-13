OUT_BACK_OVERSHOOT = 1.70158


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def out_cubic(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def out_back(x):
    x = max(0.0, min(1.0, x)) - 1.0
    return 1 + (OUT_BACK_OVERSHOOT + 1) * x ** 3 + OUT_BACK_OVERSHOOT * x ** 2


class Tween:
    def __init__(self, start, target, duration_ms, now_ms, ease=out_cubic):
        self._start = start
        self._target = target
        self._duration_ms = max(duration_ms, 1)
        self._begin_ms = now_ms
        self._ease = ease

    def value(self, now_ms):
        t = max(0.0, min(1.0, (now_ms - self._begin_ms) / self._duration_ms))
        return self._start + (self._target - self._start) * self._ease(t)

    def done(self, now_ms):
        return now_ms - self._begin_ms >= self._duration_ms

    def retarget(self, new_target, now_ms):
        self._start = self.value(now_ms)
        self._target = new_target
        self._begin_ms = now_ms

    def remap(self, transform):
        self._start = transform(self._start)
        self._target = transform(self._target)
