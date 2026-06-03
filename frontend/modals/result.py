import pygame as pg

from frontend.modals.base import BaseModal
from frontend.panels.player_strip import format_clock
from frontend.visual.colors import Colors
from frontend.visual.draw import rounded_rect_surface, blit_centered, stroked_text
from frontend.visual.widgets import draw_button_row, fit_text_to_rect, draw_series_chip
from frontend.visual.fonts import get_font, get_display_font


BUTTONS = [("New Game", "new_game"), ("Open PGN", "open_pgn"), ("Menu", "menu")]
ONLINE_BUTTONS = [("Rematch", "rematch"), ("Open PGN", "open_pgn"), ("Menu", "menu")]

SCORE_SEP = "–"
STRIP_RADIUS = 10
CARD_RADIUS = 9
HIGHLIGHT_PAD_RATIO = 0.3

OUTCOME_COLOR = {
    "win": Colors.win,
    "loss": Colors.loss,
    "draw": Colors.text,
}


def _glow_behind(text_surf, color):
    w, h = text_surf.get_size()
    small = pg.transform.smoothscale(text_surf, (max(w // 5, 1), max(h // 5, 1)))
    glow = pg.transform.smoothscale(small, (w, h))
    tint = pg.Surface(glow.get_size(), pg.SRCALPHA)
    tint.fill((*pg.Color(color)[:3], 130))
    glow.blit(tint, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    return glow


class ResultMenu(BaseModal):

    def __init__(self, window, callbacks):
        super().__init__(window)
        self.callbacks = callbacks
        self.online_mode = False
        self.outcome = None
        self.intent = "draw"
        self.reason = ""
        self.stats = None
        self.series = None
        self.rematch_offered = False
        self.button_rects = {}
        self.outcome_font = get_display_font(48)
        self.reason_font = get_font(12, bold=True)
        self.value_font = get_font(20, bold=True, mono=True)
        self.label_font = get_font(10, bold=True)
        self.button_font = get_font(14, bold=True)
        self.series_name_font = get_font(12, bold=True)
        self.series_score_font = get_font(16, mono=True)
        self._outcome_cache = None

    def _on_rect_changed(self):
        h = self.rect.height
        self.outcome_font = get_display_font(max(int(h * 0.14), 26))
        self.reason_font = get_font(max(int(h * 0.05), 14), bold=True)
        self.detail_font = get_font(max(int(h * 0.032), 11), bold=True)
        self.value_font = get_font(max(int(h * 0.052), 13), bold=True, mono=True)
        self.label_font = get_font(max(int(h * 0.026), 8), bold=True)
        self.button_font = get_font(max(int(h * 0.04), 11), bold=True)
        self.series_name_font = get_font(max(int(h * 0.032), 11), bold=True)
        self.series_score_font = get_font(max(int(h * 0.042), 13), mono=True)
        self._outcome_cache = None

    def set_result(self, outcome, intent, reason, stats=None):
        self.outcome = outcome
        self.intent = intent or "draw"
        self.reason = reason or ""
        self.stats = stats

    def set_series(self, name_a, name_b, score_a, score_b):
        if name_a is None or name_b is None:
            self.series = None
        else:
            self.series = (name_a, name_b, f"{score_a}{SCORE_SEP}{score_b}")

    def set_online_mode(self, online):
        self.online_mode = online

    def set_rematch_offered(self, offered):
        self.rematch_offered = offered

    def is_visible(self):
        return self.outcome is not None

    def draw(self):
        if not self.is_visible() or self.rect.width <= 0:
            self.button_rects = {}
            return
        self.draw_shell(self.intent)
        content = self.content_rect()
        y = content.y + max(int(self.rect.height * 0.02), 4)
        y = self._draw_outcome(content, y)
        y = self._draw_reason(content, y)
        y = self._draw_series(content, y)
        y = self._draw_highlight(content, y)
        self._draw_stats(content, y)
        self._draw_buttons(content)

    def _draw_outcome(self, content, y):
        sw = max(int(self.outcome_font.get_height() * 0.035), 2)
        key = (self.outcome, self.intent, self.outcome_font.get_height())
        if self._outcome_cache is None or self._outcome_cache[0] != key:
            color = OUTCOME_COLOR.get(self.intent, Colors.text)
            text = stroked_text(self.outcome_font, self.outcome.upper(),
                                color, Colors.outcome_stroke, sw)
            text = fit_text_to_rect(
                text, pg.Rect(0, 0, content.width, int(content.height * 0.3)))
            glow = _glow_behind(text, color) if self.intent != "draw" else None
            self._outcome_cache = (key, text, glow)
        _, text, glow = self._outcome_cache
        cx = content.centerx
        if glow is not None:
            self.window.blit(glow, (cx - glow.get_width() / 2, y))
        self.window.blit(text, (cx - text.get_width() / 2, y))
        return y + text.get_height() + max(int(self.rect.height * 0.012), 3)

    def _draw_reason(self, content, y):
        if not self.reason:
            return y
        surf = self.reason_font.render(self.reason.upper(), True, Colors.text_dim)
        surf = fit_text_to_rect(surf, pg.Rect(0, 0, content.width, surf.get_height()))
        self.window.blit(surf, (content.centerx - surf.get_width() / 2, y))
        return y + surf.get_height() + max(int(self.rect.height * 0.03), 8)

    def _draw_series(self, content, y):
        if not self.online_mode or self.series is None:
            return y
        name_a, name_b, score = self.series
        chip = draw_series_chip(
            self.window, (content.centerx, y + self.series_score_font.get_height()),
            name_a, name_b, score, self.series_name_font, self.series_score_font)
        return chip.bottom + max(int(self.rect.height * 0.02), 5)

    def _draw_highlight(self, content, y):
        potg = self.stats.get("play_of_the_game") if self.stats else None
        if not potg:
            return y
        h = max(int(self.rect.height * 0.085), 28)
        strip = rounded_rect_surface((content.width, h), STRIP_RADIUS, Colors.potg_bg,
                                     border=Colors.potg_border, border_width=1)
        self.window.blit(strip, (content.x, y))
        pad = max(int(h * HIGHLIGHT_PAD_RATIO), 8)
        cy = y + h / 2
        label = self.detail_font.render("HIGHLIGHT", True, Colors.amber_hi)
        self.window.blit(label, (content.x + pad, cy - label.get_height() / 2))
        detail_x = content.x + pad + label.get_width() + max(int(h * HIGHLIGHT_PAD_RATIO), 8)
        detail = self.detail_font.render(potg, True, Colors.text)
        max_w = content.right - pad - detail_x
        if detail.get_width() > max_w > 0:
            detail = fit_text_to_rect(detail, pg.Rect(0, 0, max_w, detail.get_height()))
        self.window.blit(detail, (detail_x, cy - detail.get_height() / 2))
        return y + h + max(int(self.rect.height * 0.025), 6)

    def _stat_cells(self):
        s = self.stats
        mine, theirs = s["kos"]
        mat = s["material"]
        mat_str = f"+{mat}" if mat > 0 else str(mat)
        return [
            (str(mine), f"/{theirs}", "KOs"),
            (f"×{s['streak']}", "", "Best streak"),
            (str(s["checks"]), "", "Checks"),
            (str(s["moves"]), "", "Moves"),
            (format_clock(s["clock_left"]), "", "Clock left"),
            (mat_str, "", "Material"),
        ]

    def _draw_stats(self, content, y):
        if not self.stats:
            return
        cols, rows = 3, 2
        gap = max(int(content.width * 0.02), 6)
        cell_w = (content.width - gap * (cols - 1)) / cols
        avail = self._buttons_top(content) - y - gap
        cell_h = (avail - gap * (rows - 1)) / rows
        if cell_h <= 0:
            return
        for i, (value, vs, label) in enumerate(self._stat_cells()):
            cx = content.x + (i % cols) * (cell_w + gap)
            cy = y + (i // cols) * (cell_h + gap)
            cell = pg.Rect(int(cx), int(cy), int(cell_w), int(cell_h))
            bg = rounded_rect_surface(cell.size, CARD_RADIUS, Colors.surface,
                                      border=Colors.border, border_width=1)
            self.window.blit(bg, cell.topleft)
            value_surf = self.value_font.render(value, True, Colors.text)
            total_w = value_surf.get_width()
            vs_surf = None
            if vs:
                vs_surf = self.detail_font.render(vs, True, Colors.text_muted)
                total_w += vs_surf.get_width()
            vx = cell.centerx - total_w / 2
            vy = cell.y + cell_h * 0.28
            self.window.blit(value_surf, (vx, vy - value_surf.get_height() / 2))
            if vs_surf is not None:
                self.window.blit(vs_surf, (vx + value_surf.get_width(),
                                           vy - vs_surf.get_height() / 2))
            label_surf = self.label_font.render(label.upper(), True, Colors.text_muted)
            blit_centered(self.window, label_surf, (cell.centerx, cell.y + cell_h * 0.72))

    def _button_height(self):
        return max(int(self.rect.height * 0.1), 30)

    def _buttons_top(self, content):
        btn_h = self._button_height()
        return content.bottom - btn_h

    def _draw_buttons(self, content):
        btn_h = self._button_height()
        gap = max(int(content.width * 0.02), 6)
        row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        buttons = ONLINE_BUTTONS if self.online_mode else BUTTONS
        if self.online_mode and self.rematch_offered:
            buttons = [("Accept", "rematch")] + buttons[1:]
        self.button_rects = draw_button_row(
            self.window, row, buttons, self.button_font, gap,
            primary_keys={buttons[0][1]},
        )

    def handle_click(self, pos):
        if not self.is_visible():
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.callbacks[key]()
                return True
        return False
