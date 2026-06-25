SKILLCHECK_RESULT_HOLD_MS = 200


class SkillCheckController:

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
