from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.widgets import avatar_palette


TITLE_TOP_FRAC = 0.05


def scale_floor(value, scale, floor=1):
    return max(int(value * scale), floor)


def subview_title_top(rect):
    return rect.y + int(rect.height * TITLE_TOP_FRAC)


def draw_subview_title(window, font, text, x, top):
    window.blit(render_text(font, text, Colors.text), (x, top))


def seeded_avatar_palette(nickname, cached_seed, cached_palette):
    if cached_palette is None or cached_seed != nickname:
        return nickname, avatar_palette(nickname)
    return cached_seed, cached_palette


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

    def handle_press(self, pos):
        return False

    def handle_motion(self, pos):
        return False

    def handle_release(self, pos):
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
