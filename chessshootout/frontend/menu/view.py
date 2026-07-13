class MenuView:

    name = ""

    def __init__(self, app):
        self.app = app

    def enter(self, payload=None):
        pass

    def exit(self):
        pass

    def update(self, now):
        pass

    def draw(self, window, menu_layout):
        pass

    def relayout(self, menu_layout):
        pass

    def handle_click(self, pos):
        return False

    def handle_key(self, event):
        return False

    def escape(self):
        return False

    def active_scrollable(self, pos=None):
        return None

    def scrollables(self):
        return []

    def avoid_rects(self):
        return []
