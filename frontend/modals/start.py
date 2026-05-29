import pygame as pg

import paths
from backend.match import SINGLE_SCREEN, BOT, ONLINE
from frontend import env
from frontend.visual.colors import Colors
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import draw_button, draw_gear, draw_icon_button, draw_selector
from frontend.visual.fonts import get_font


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


FOOTER_PREFIX = "Chess Shootout {label} - Designed and developed by "
FOOTER_LINK_TEXT = "xiaomyung"
FOOTER_URL = "https://github.com/xiaomyung"
FOOTER_MARGIN_PX = 10
FOOTER_LINK_HITBOX_PAD_PX = 9
FOOTER_SHINE_PERIOD_MS = 10000
FOOTER_SHINE_SWEEP_MS = 1100
FOOTER_SHINE_HOVER_PERIOD_MS = 500
FOOTER_SHINE_HOVER_SWEEP_MS = 450
FOOTER_SHINE_MAX_ALPHA = 200


def footer_prefix_text():
    version = paths.get_app_version()
    label = "v" + version if version else "(dev)"
    return FOOTER_PREFIX.format(label=label)


class StartMenu:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.visible = True
        self.title = "Chess"

        self.text_input = TextInput(window)
        self.text_input.text = env.get_nickname()

        last_mode = env.get_last_mode()
        self.selected_mode = (
            last_mode if last_mode in (SINGLE_SCREEN, BOT, ONLINE)
            else SINGLE_SCREEN
        )
        self.selected_time_minutes = 10
        self.selected_increment_seconds = 5
        self.selected_side = "random"

        self.title_font = get_font(28, bold=True)
        self.label_font = get_font(12, bold=True)
        self.button_font = get_font(14, bold=True)
        self.start_font = get_font(18, bold=True)

        self._outer = pg.Rect(0, 0, 0, 0)
        self._title_pos = (0, 0)
        self._input_rect = pg.Rect(0, 0, 0, 0)
        self._section_label_ys = [0, 0, 0, 0]
        self._section_selector_rects = [pg.Rect(0, 0, 0, 0) for _ in range(4)]
        self._load_pgn_rect = pg.Rect(0, 0, 0, 0)
        self._fen_rect = pg.Rect(0, 0, 0, 0)
        self._reconnect_rect = pg.Rect(0, 0, 0, 0)
        self._start_rect = pg.Rect(0, 0, 0, 0)
        self._gear_rect = pg.Rect(0, 0, 0, 0)

        self._footer_prefix_surf = None
        self._footer_link_surf = None
        self._footer_link_mask_surf = None
        self._footer_shine_band = None
        self._footer_shine_w = 0
        self._footer_prefix_pos = (0, 0)
        self._footer_link_rect = pg.Rect(0, 0, 0, 0)
        self._footer_link_hitbox = pg.Rect(0, 0, 0, 0)
        self._footer_underline_y = 0

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
        gear_size = min(max(int(h * 0.05), 26), 46)
        self._gear_rect = pg.Rect(
            rect.right - padding - gear_size, rect.y + padding, gear_size, gear_size,
        )
        self.title_font = get_font(max(int(h / 14), 14), bold=True)
        self.label_font = get_font(max(int(h / 32), 10), bold=True)
        self.button_font = get_font(max(int(h / 38), 10), bold=True)
        self.start_font = get_font(max(int(h / 30), 11), bold=True)

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

        self._build_footer()

    def _build_footer(self):
        win_w, win_h = self.window.get_size()
        font = get_font(max(int(win_h / 64), 9))
        prefix = footer_prefix_text()
        self._footer_prefix_surf = font.render(prefix, True, Colors.footer_text)
        self._footer_link_surf = font.render(FOOTER_LINK_TEXT, True, Colors.footer_link)
        self._footer_link_mask_surf = font.render(FOOTER_LINK_TEXT, True, Colors.white)
        prefix_w = self._footer_prefix_surf.get_width()
        link_w, link_h = self._footer_link_surf.get_size()
        x = (win_w - prefix_w - link_w) // 2
        y = win_h - FOOTER_MARGIN_PX - link_h
        self._footer_prefix_pos = (x, y)
        self._footer_link_rect = pg.Rect(x + prefix_w, y, link_w, link_h)
        self._footer_link_hitbox = self._footer_link_rect.inflate(
            FOOTER_LINK_HITBOX_PAD_PX * 2, FOOTER_LINK_HITBOX_PAD_PX * 2,
        )
        self._footer_underline_y = y + link_h - 1
        band_w = max(int(link_w * 0.5), 12)
        band = pg.Surface((band_w, link_h), pg.SRCALPHA)
        half = band_w / 2
        for col in range(band_w):
            alpha = int(FOOTER_SHINE_MAX_ALPHA * (1 - abs(col - half) / half))
            pg.draw.line(band, (255, 255, 255, alpha), (col, 0), (col, link_h))
        self._footer_shine_band = band
        self._footer_shine_w = band_w

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

        draw_icon_button(self.window, self._gear_rect, draw_gear)

        self.text_input.set_rect(self._input_rect)
        self.text_input.draw()

        for i, (label, attr, options) in enumerate(SECTIONS):
            self._draw_section(
                i, label, options, getattr(self, attr), attr,
            )

        draw_button(self.window, self._load_pgn_rect, "History", self.start_font,
                    disabled=not self.load_pgn_available)
        draw_button(self.window, self._fen_rect, "From FEN", self.start_font,
                    disabled=self.selected_mode == "online")
        if self.reconnect_available:
            draw_button(self.window, self._reconnect_rect, "Reconnect", self.start_font)
        draw_button(self.window, self._start_rect, self.start_button_label, self.start_font)

        self._draw_footer()

    def _footer_link_hovered(self):
        return bool(self._footer_link_hitbox.collidepoint(pg.mouse.get_pos()))

    def _draw_footer(self):
        if self._footer_prefix_surf is None:
            return
        self.window.blit(self._footer_prefix_surf, self._footer_prefix_pos)
        self.window.blit(self._footer_link_surf, self._footer_link_rect.topleft)
        pg.draw.line(self.window, Colors.footer_link,
                     (self._footer_link_rect.x, self._footer_underline_y),
                     (self._footer_link_rect.right - 1, self._footer_underline_y))
        hovered = self._footer_link_hovered()
        period = FOOTER_SHINE_HOVER_PERIOD_MS if hovered else FOOTER_SHINE_PERIOD_MS
        sweep = FOOTER_SHINE_HOVER_SWEEP_MS if hovered else FOOTER_SHINE_SWEEP_MS
        elapsed = pg.time.get_ticks() % period
        if elapsed >= sweep:
            return
        progress = elapsed / sweep
        link_w = self._footer_link_rect.width
        link_h = self._footer_link_rect.height
        offset = int(progress * (link_w + self._footer_shine_w) - self._footer_shine_w)
        shine = pg.Surface((link_w, link_h), pg.SRCALPHA)
        shine.blit(self._footer_shine_band, (offset, 0))
        shine.blit(self._footer_link_mask_surf, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self.window.blit(shine, self._footer_link_rect.topleft)

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

        if self._gear_rect.collidepoint(pos):
            if "options" in self.callbacks:
                self.callbacks["options"]()
            return True

        if self._footer_link_hitbox.collidepoint(pos):
            if "open_url" in self.callbacks:
                self.callbacks["open_url"](FOOTER_URL)
            return True

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
            if self.selected_mode == "online":
                return True
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
