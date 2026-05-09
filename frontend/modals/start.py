import pygame as pg

from backend.match import SINGLE_SCREEN, BOT, ONLINE
from frontend import env
from frontend.visual.colors import Colors
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import draw_button, draw_selector


MODE_OPTIONS = [
    ("Single-screen", SINGLE_SCREEN),
    ("Bot", BOT),
    ("Online", ONLINE),
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


SECTIONS = [
    ("Game mode", "selected_mode", MODE_OPTIONS),
    ("Time", "selected_time_minutes", TIME_OPTIONS),
    ("Increment (s)", "selected_increment_seconds", INCREMENT_OPTIONS),
    ("Side", "selected_side", SIDE_OPTIONS),
]


class StartMenu:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.visible = True
        self.title = "Chess"

        self.text_input = TextInput(window)
        self.text_input.text = env.get_nickname()

        last_mode = env.get_last_mode()
        self.selected_mode = last_mode if last_mode in (SINGLE_SCREEN, BOT, ONLINE) else SINGLE_SCREEN
        self.selected_time_minutes = 10
        self.selected_increment_seconds = 5
        self.selected_side = "random"

        self.title_font = pg.font.SysFont("Arial", 28, bold=True)
        self.label_font = pg.font.SysFont("Arial", 12, bold=True)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self.start_font = pg.font.SysFont("Arial", 18, bold=True)

        self._outer = pg.Rect(0, 0, 0, 0)
        self._title_pos = (0, 0)
        self._input_rect = pg.Rect(0, 0, 0, 0)
        self._section_label_ys = [0, 0, 0, 0]
        self._section_selector_rects = [pg.Rect(0, 0, 0, 0) for _ in range(4)]
        self._load_pgn_rect = pg.Rect(0, 0, 0, 0)
        self._fen_rect = pg.Rect(0, 0, 0, 0)
        self._reconnect_rect = pg.Rect(0, 0, 0, 0)
        self._start_rect = pg.Rect(0, 0, 0, 0)

        self._section_rects_by_key = {
            "selected_mode": {},
            "selected_time_minutes": {},
            "selected_increment_seconds": {},
            "selected_side": {},
        }

        self.row_gap = 6
        self.load_pgn_available = False
        self.reconnect_available = False

    def set_reconnect_available(self, available):
        if self.reconnect_available == available:
            return
        self.reconnect_available = available
        if self._outer.width > 0:
            self.set_rect(self._outer)

    def set_rect(self, rect):
        self._outer = pg.Rect(rect)
        h = rect.height

        padding = max(int(h * 0.03), 10)
        self.title_font = pg.font.SysFont("Arial", max(int(h / 14), 14), bold=True)
        self.label_font = pg.font.SysFont("Arial", max(int(h / 32), 10), bold=True)
        self.button_font = pg.font.SysFont("Arial", max(int(h / 38), 10), bold=True)
        self.start_font = pg.font.SysFont("Arial", max(int(h / 30), 11), bold=True)

        inner_x = rect.x + padding
        inner_w = rect.width - 2 * padding
        inner_top = rect.y + padding
        inner_bottom = rect.bottom - padding

        title_h = self.title_font.get_height()
        title_top = inner_top
        self._title_pos = (rect.centerx, title_top)

        start_h = max(int(h * 0.075), 28)
        start_y = inner_bottom - start_h

        title_to_input_gap = max(int(h * 0.035), 10)
        input_to_sections_gap = max(int(h * 0.04), 12)
        sections_to_button_gap = max(int(h * 0.035), 10)

        input_h = min(max(int(h * 0.05), 26), 52)
        input_y = title_top + title_h + title_to_input_gap
        self._input_rect = pg.Rect(inner_x, input_y, inner_w, input_h)

        sections_top = input_y + input_h + input_to_sections_gap
        sections_bottom = start_y - sections_to_button_gap
        sections_h = max(sections_bottom - sections_top, 0)

        inter_block_gap = max(int(h * 0.022), 6)
        block_count = 4
        block_h = max(
            (sections_h - inter_block_gap * (block_count - 1)) // block_count, 1,
        )

        section_label_h = max(int(block_h * 0.3), 10)
        section_label_to_selector_gap = max(int(block_h * 0.08), 3)
        selector_h = max(
            block_h - section_label_h - section_label_to_selector_gap, 12,
        )

        block_y = sections_top
        for i in range(block_count):
            self._section_label_ys[i] = block_y
            self._section_selector_rects[i] = pg.Rect(
                inner_x,
                block_y + section_label_h + section_label_to_selector_gap,
                inner_w,
                selector_h,
            )
            block_y += block_h + inter_block_gap

        gap = self.row_gap
        button_keys = ["load_pgn", "fen"]
        if self.reconnect_available:
            button_keys.append("reconnect")
        button_keys.append("start")
        n = len(button_keys)
        cell_w = (inner_w - gap * (n - 1)) // n
        layout = {}
        x = inner_x
        for i, key in enumerate(button_keys):
            width = inner_w - x + inner_x if i == n - 1 else cell_w
            layout[key] = pg.Rect(x, start_y, width, start_h)
            x += cell_w + gap
        self._load_pgn_rect = layout["load_pgn"]
        self._fen_rect = layout["fen"]
        self._reconnect_rect = layout.get("reconnect", pg.Rect(0, 0, 0, 0))
        self._start_rect = layout["start"]

    @property
    def _mode_rects(self):
        return self._section_rects_by_key["selected_mode"]

    @property
    def _time_rects(self):
        return self._section_rects_by_key["selected_time_minutes"]

    @property
    def _increment_rects(self):
        return self._section_rects_by_key["selected_increment_seconds"]

    @property
    def _side_rects(self):
        return self._section_rects_by_key["selected_side"]

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

    @property
    def start_button_label(self):
        return "Start Search" if self.selected_mode == "online" else "Start Game"

    def draw(self):
        if not self.visible:
            self._section_rects_by_key = {k: {} for k in self._section_rects_by_key}
            return

        pg.draw.rect(self.window, Colors.light_grey_menu, self._outer, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self._outer, 2, border_radius=8)

        title_surf = self.title_font.render(self.title, True, Colors.white)
        title_x = self._title_pos[0] - title_surf.get_width() / 2
        self.window.blit(title_surf, (title_x, self._title_pos[1]))

        self.text_input.set_rect(self._input_rect)
        self.text_input.draw()

        for i, (label, attr, options) in enumerate(SECTIONS):
            self._draw_section(
                i, label, options, getattr(self, attr), attr,
            )

        draw_button(self.window, self._load_pgn_rect, "Load PGN", self.start_font,
                    disabled=not self.load_pgn_available)
        draw_button(self.window, self._fen_rect, "From FEN", self.start_font)
        if self.reconnect_available:
            draw_button(self.window, self._reconnect_rect, "Reconnect", self.start_font)
        draw_button(self.window, self._start_rect, self.start_button_label, self.start_font)

    def _draw_section(self, idx, label, options, selected_key, attr):
        label_surf = self.label_font.render(label, True, Colors.white)
        x = self._section_selector_rects[idx].x
        self.window.blit(label_surf, (x, self._section_label_ys[idx]))
        rects = draw_selector(
            self.window, self._section_selector_rects[idx], options,
            self.button_font, gap=self.row_gap, selected_key=selected_key,
        )
        self._section_rects_by_key[attr] = rects

    def handle_click(self, pos):
        if not self.visible:
            return False

        if self._input_rect.collidepoint(pos):
            self.text_input.handle_click(pos)
            return True
        self.text_input.handle_click(pos)

        for attr, rects in self._section_rects_by_key.items():
            for key, br in rects.items():
                if br.collidepoint(pos):
                    setattr(self, attr, key)
                    return True

        if self._load_pgn_rect.collidepoint(pos):
            if self.load_pgn_available and "load_pgn" in self.callbacks:
                self.callbacks["load_pgn"]()
            return True

        if self._fen_rect.collidepoint(pos):
            if "fen" in self.callbacks:
                self.callbacks["fen"]()
            return True

        if self.reconnect_available and self._reconnect_rect.collidepoint(pos):
            if "reconnect" in self.callbacks:
                self.callbacks["reconnect"]()
            return True

        if self._start_rect.collidepoint(pos):
            self.callbacks["start_game"](self.build_config())
            return True

        return False

    def handle_key(self, event):
        return self.text_input.handle_key(event)
