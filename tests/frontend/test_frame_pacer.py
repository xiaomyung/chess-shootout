import pytest

from chessshootout.frontend.frame_pacer import FramePacer


class FakeTime:

    def __init__(self, start=0.0, overshoot=0.0):
        self.t = start
        self.overshoot = overshoot
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.t += delay + self.overshoot

    def advance(self, dt):
        self.t += dt


def _pacer(target_fps=300, **kwargs):
    ft = FakeTime(**kwargs)
    pacer = FramePacer(target_fps, now=ft.now, sleep=ft.sleep)
    return pacer, ft


def test_first_wait_sets_baseline_and_sleeps_one_period():
    pacer, ft = _pacer()
    pacer.wait()
    assert ft.sleeps == [pytest.approx(pacer.period)]
    assert ft.t == pytest.approx(pacer.period)


def test_consecutive_waits_hold_zero_cumulative_drift():
    pacer, ft = _pacer()
    pacer.wait()
    ft.advance(0.0005)
    pacer.wait()
    ft.advance(0.001)
    pacer.wait()
    assert ft.t == pytest.approx(3 * pacer.period)
    assert ft.sleeps[1] == pytest.approx(pacer.period - 0.0005)
    assert ft.sleeps[2] == pytest.approx(pacer.period - 0.001)


def test_oversleep_in_one_frame_shortens_the_next_sleep():
    overshoot = 0.001
    pacer, ft = _pacer(overshoot=overshoot)
    pacer.wait()
    pacer.wait()
    assert ft.sleeps[1] == pytest.approx(pacer.period - overshoot)


def test_persistent_overrun_free_runs_without_sleeping():
    # A frame budget that's blown every frame must never sleep, or the pacer
    # settles into a stable limit cycle at a fraction of the target rate.
    pacer, ft = _pacer()
    pacer.wait()
    sleeps_before_overrun = len(ft.sleeps)
    for _ in range(5):
        ft.advance(2 * pacer.period)
        pacer.wait()
    assert len(ft.sleeps) == sleeps_before_overrun
    resume_deadline = ft.t
    pacer.wait()
    assert ft.sleeps[-1] == pytest.approx(pacer.period)
    assert ft.t == pytest.approx(resume_deadline + pacer.period)


def test_delay_at_or_below_zero_does_not_call_sleep():
    pacer, ft = _pacer()
    pacer.wait()
    ft.advance(pacer.period)
    pacer.wait()
    assert len(ft.sleeps) == 1


def test_sub_millisecond_delay_passed_through_as_float():
    pacer, ft = _pacer(target_fps=300)
    pacer.wait()
    delay = ft.sleeps[0]
    assert delay == pytest.approx(1.0 / 300.0)
    assert delay * 1000.0 != int(delay * 1000.0)
