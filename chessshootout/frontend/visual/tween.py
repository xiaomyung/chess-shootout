from collections.abc import Callable

OUT_BACK_OVERSHOOT = 1.70158


def out_cubic(x: float) -> float:
    """
    The default easing curve of the UI: fast at the start, softly settling at
    the end. Menu slides, popovers and the rail reticle all move on this, which
    is what makes the interface feel like it comes to rest rather than stopping

    :param x: progress through the animation, clamped into 0.0 to 1.0
    :returns: eased progress, 0.0 at the start and 1.0 at the end
    """
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def out_back(x: float) -> float:
    """
    An easing curve that overshoots the target and swings back, used where a
    widget should feel like it snaps into place -- a chamber seating, a chip
    popping in. It leaves the 0.0 to 1.0 range in the middle, on purpose

    :param x: progress through the animation, clamped into 0.0 to 1.0
    :returns: eased progress; peaks above 1.0 before settling at 1.0
    """
    x = max(0.0, min(1.0, x)) - 1.0
    return 1 + (OUT_BACK_OVERSHOOT + 1) * x ** 3 + OUT_BACK_OVERSHOOT * x ** 2


class Tween:
    """
    One animated number moving from a start value to a target over a fixed
    time. Widgets keep a Tween instead of stepping values themselves and just
    ask it what the value is at the current frame, so animation never depends
    on how many frames were drawn
    """

    def __init__(self, start: float, target: float, duration_ms: int, now_ms: int,
                 ease: Callable[[float], float] = out_cubic) -> None:
        """
        Start the animation immediately, timed from the moment given rather
        than from when the object happens to be built

        :param start: value the animation begins at
        :param target: value the animation ends at
        :param duration_ms: run time in milliseconds, forced to at least 1
        :param now_ms: pygame tick count in milliseconds taken as time zero
        :param ease: shaping curve mapping 0.0 to 1.0 progress onto 0.0 to 1.0
        """
        self._start = start
        self._target = target
        self._duration_ms = max(duration_ms, 1)
        self._begin_ms = now_ms
        self._ease = ease

    def value(self, now_ms: int) -> float:
        """
        The animated value at this frame, which is all a drawing routine needs
        from a tween. Before the start it reads as the start value and after
        the end as the target, so an expired tween is safe to keep asking

        :param now_ms: pygame tick count in milliseconds for the current frame
        :returns: eased value between start and target
        """
        t = max(0.0, min(1.0, (now_ms - self._begin_ms) / self._duration_ms))
        return self._start + (self._target - self._start) * self._ease(t)

    def done(self, now_ms: int) -> bool:
        """
        Say whether the animation has run its course, which is how owners know
        they can drop the tween and stop redrawing

        :param now_ms: pygame tick count in milliseconds for the current frame
        :returns: True once the full duration has elapsed
        """
        return now_ms - self._begin_ms >= self._duration_ms

    def retarget(self, new_target: float, now_ms: int) -> None:
        """
        Aim an in-flight animation at a new value without jumping: the current
        eased value becomes the new start and the clock restarts. This is what
        keeps a widget smooth when the player changes their mind mid-slide

        :param new_target: value the animation should now end at
        :param now_ms: pygame tick count in milliseconds, the new time zero
        """
        self._start = self.value(now_ms)
        self._target = new_target
        self._begin_ms = now_ms
