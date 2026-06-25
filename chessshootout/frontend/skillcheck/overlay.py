class SkillCheckOverlay:

    def __init__(self):
        self._controller = None
        self._context = None
        self._on_done = None

    def start(self, controller, context, on_done):
        self._controller = controller
        self._context = context
        self._on_done = on_done

    def is_active(self):
        return self._controller is not None

    def is_passive(self):
        return getattr(self._controller, "_passive", False)

    def spectate_shot(self, elapsed, miss_count, won):
        if self._controller is not None:
            self._controller.spectate_shot(elapsed, miss_count, won)

    def handle_event(self, event):
        if self._controller is None:
            return False
        return self._controller.handle_event(event)

    def update(self, now_ms):
        if self._controller is None:
            return
        self._controller.update(now_ms)
        if self._controller.done:
            self._finish()

    def draw(self, window):
        if self._controller is not None:
            self._controller.draw(window)

    def relayout(self, cell_rect):
        if self._controller is not None:
            self._controller.relayout(cell_rect)

    def set_board_rect(self, board_rect):
        setter = getattr(self._controller, "set_board_rect", None)
        if setter is not None:
            setter(board_rect)

    def resolve_online(self, won):
        if self._controller is not None:
            self._controller.resolve(won)

    def cancel(self):
        self._controller = None
        self._context = None
        self._on_done = None

    def _finish(self):
        context = self._context
        landed = self._controller.landed
        on_done = self._on_done
        self.cancel()
        if on_done is not None:
            on_done(context, landed)
