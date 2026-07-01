SKILLCHECK_RESULT_HOLD_MS = 200


class EdgeTrigger:

    def __init__(self):
        self._prev = False

    def update(self, inside):
        inside = bool(inside)
        rising = inside and not self._prev
        self._prev = inside
        return rising


class SkillCheckController:

    _audio = None
    _passive = False

    def _cue(self, method):
        if self._audio is not None and not self._passive:
            getattr(self._audio, method)()

    def _emit_verdict(self):
        self._cue("play_skillcheck_win" if self.landed else "play_skillcheck_miss")

    def handle_event(self, event):
        return False

    def update(self, now_ms):
        pass

    def draw(self, window):
        pass

    def relayout(self, cell_rect):
        pass

    @property
    def done(self):
        return False

    @property
    def landed(self):
        return None
