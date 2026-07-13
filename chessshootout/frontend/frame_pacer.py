import time


class FramePacer:

    def __init__(self, target_fps, now=time.perf_counter, sleep=time.sleep):
        self.period = 1.0 / target_fps
        self._now = now
        self._sleep = sleep
        self._deadline = None

    def wait(self):
        now = self._now()
        if self._deadline is None:
            self._deadline = now
        self._deadline += self.period
        if self._deadline <= now:
            self._deadline = now
            return
        self._sleep(self._deadline - now)
