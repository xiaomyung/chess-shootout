import pygame as pg

from frontend.colors import Colors
from frontend.text_input import TextInput
from frontend.widgets import _draw_button, draw_selector


MODE_OPTIONS = [
    ("Single-screen", "single_screen"),
    ("Bot", "bot"),
    ("Online", "online"),
]

TIME_OPTIONS = [
    ("No clock", None),
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
]

INCREMENT_OPTIONS = [
    ("+0", 0),
    ("+2", 2),
    ("+5", 5),
    ("+10", 10),
]

SIDE_OPTIONS = [
    ("White", "white"),
    ("Random", "random"),
    ("Black", "black"),
]


class StartMenu:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.visible = True
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.padding = 14
        self.row_gap = 6
        self.section_gap = 10
        self.label_to_selector_gap = 6
        self.input_to_section_gap = 20
        self.title = "Chess"

        self.text_input = TextInput(window)

        self.selected_mode = "single_screen"
        self.selected_time_minutes = 10
        self.selected_increment_seconds = 5
        self.selected_side = "white"

        self.title_font = pg.font.SysFont("Arial", 28, bold=True)
        self.label_font = pg.font.SysFont("Arial", 12, bold=True)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self.start_font = pg.font.SysFont("Arial", 18, bold=True)

        self._mode_rects = {}
        self._time_rects = {}
        self._increment_rects = {}
        self._side_rects = {}
        self._start_rect = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect):
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height
        self.padding = max(int(rect.height * 0.03), 10)
        self.section_gap = max(int(rect.height * 0.025), 8)
        self.label_to_selector_gap = max(int(rect.height * 0.015), 4)
        self.input_to_section_gap = max(int(rect.height * 0.05), 14)
        self.title_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 14), 14), bold=True,
        )
        self.label_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 28), 10), bold=True,
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 38), 10), bold=True,
        )
        self.start_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 18), 12), bold=True,
        )

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def is_visible(self):
        return self.visible

    def build_config(self):
        return {
            "mode": self.selected_mode,
            "nickname": self.text_input.text,
            "time_minutes": self.selected_time_minutes,
            "increment_seconds": self.selected_increment_seconds,
            "side": self.selected_side,
        }

    def draw(self):
        if not self.visible:
            self._mode_rects = {}
            self._time_rects = {}
            self._increment_rects = {}
            self._side_rects = {}
            self._start_rect = pg.Rect(0, 0, 0, 0)
            return

        outer = pg.Rect(self.x, self.y, self.width, self.height)
        pg.draw.rect(self.window, Colors.light_grey_menu, outer, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, outer, 2, border_radius=8)

        title_surf = self.title_font.render(self.title, True, Colors.white)
        title_y = outer.y + self.padding
        self.window.blit(
            title_surf,
            (outer.centerx - title_surf.get_width() / 2, title_y),
        )

        content_x = outer.x + self.padding
        content_w = outer.width - 2 * self.padding

        input_h = max(int(outer.height * 0.07), 24)
        selector_h = max(int(outer.height * 0.075), 26)
        start_h = max(int(outer.height * 0.09), 30)
        label_h = max(int(outer.height * 0.04), 12)

        cursor = title_y + title_surf.get_height() + self.section_gap

        input_rect = pg.Rect(content_x, cursor, content_w, input_h)
        self.text_input.set_rect(input_rect)
        self.text_input.draw()
        cursor = input_rect.bottom + self.input_to_section_gap

        section_step = label_h + self.label_to_selector_gap + selector_h + self.section_gap

        self._mode_rects = self._draw_section(
            "Game mode", cursor, content_x, content_w, label_h, selector_h,
            MODE_OPTIONS, self.selected_mode,
        )
        cursor += section_step

        self._time_rects = self._draw_section(
            "Time", cursor, content_x, content_w, label_h, selector_h,
            TIME_OPTIONS, self.selected_time_minutes,
        )
        cursor += section_step

        self._increment_rects = self._draw_section(
            "Increment (s)", cursor, content_x, content_w, label_h, selector_h,
            INCREMENT_OPTIONS, self.selected_increment_seconds,
        )
        cursor += section_step

        self._side_rects = self._draw_section(
            "Side", cursor, content_x, content_w, label_h, selector_h,
            SIDE_OPTIONS, self.selected_side,
        )
        cursor += section_step

        start_rect = pg.Rect(content_x, cursor + self.section_gap,
                             content_w, start_h)
        self._start_rect = start_rect
        _draw_button(self.window, start_rect, "Start Game", self.start_font,
                     force_pressed=False)

    def _draw_section(self, label, top, content_x, content_w, label_h,
                      selector_h, options, selected_key):
        label_surf = self.label_font.render(label, True, Colors.white)
        self.window.blit(label_surf, (content_x, top))
        selector_rect = pg.Rect(
            content_x,
            top + label_h + self.label_to_selector_gap,
            content_w,
            selector_h,
        )
        return draw_selector(
            self.window, selector_rect, options, self.button_font,
            gap=self.row_gap, selected_key=selected_key,
        )

    def handle_click(self, pos):
        if not self.visible:
            return False

        if self.text_input.rect.collidepoint(pos):
            self.text_input.handle_click(pos)
            return True
        self.text_input.handle_click(pos)

        for key, br in self._mode_rects.items():
            if br.collidepoint(pos):
                self.selected_mode = key
                return True
        for key, br in self._time_rects.items():
            if br.collidepoint(pos):
                self.selected_time_minutes = key
                return True
        for key, br in self._increment_rects.items():
            if br.collidepoint(pos):
                self.selected_increment_seconds = key
                return True
        for key, br in self._side_rects.items():
            if br.collidepoint(pos):
                self.selected_side = key
                return True

        if self._start_rect.collidepoint(pos):
            self.callbacks["start_game"](self.build_config())
            return True

        return False

    def handle_key(self, event):
        return self.text_input.handle_key(event)
