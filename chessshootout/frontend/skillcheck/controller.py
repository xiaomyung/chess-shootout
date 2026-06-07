class SkillCheckController:

    def handle_event(self, event):
        return False

    def update(self, now_ms):
        pass

    def draw(self, window):
        pass

    @property
    def done(self):
        return False

    @property
    def landed(self):
        return None
