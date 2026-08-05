def _close_controller(controller):
    close = getattr(controller, "close", None)
    if close is not None:
        close()


class SkillCheckOverlay:

    def __init__(self):
        self._controller = None
        self._context = None
        self._on_done = None
        self._farewell = None

    def start(self, controller, context, on_done):
        if self._controller is not None and self._controller is not controller:
            _close_controller(self._controller)
        self._controller = controller
        self._context = context
        self._on_done = on_done

    def is_active(self):
        return self._controller is not None

    def is_passive(self):
        return getattr(self._controller, "_passive", False)

    def aim_victim_scale(self):
        fn = getattr(self._controller, "victim_scale", None)
        return fn() if fn is not None else 1.0

    def spectate_shot(self, elapsed, miss_count, won, progress=0, direction=None, target=None):
        if self._controller is not None:
            self._controller.spectate_shot(elapsed, miss_count, won, progress=progress,
                                           direction=direction, target=target)

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
        controller = self._controller if self._controller is not None else self._farewell
        self._farewell = None
        if controller is not None:
            controller.draw(window)

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
        controller = self._controller
        self._controller = None
        self._context = None
        self._on_done = None
        self._farewell = None
        if controller is not None:
            _close_controller(controller)

    def _finish(self):
        context = self._context
        controller = self._controller
        landed = controller.landed
        on_done = self._on_done
        self.cancel()
        self._farewell = controller
        if on_done is not None:
            on_done(context, landed)
