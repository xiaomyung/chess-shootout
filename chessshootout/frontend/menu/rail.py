import math

import pygame as pg

from chessshootout import paths
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.fonts import get_font, get_mono_font
from chessshootout.frontend.visual.icons import (
    draw_clock, draw_gear, draw_medal, draw_people, draw_play, draw_reticle, draw_shield,
)
from chessshootout.frontend.visual.tween import Tween


CREDIT_TEXT = "xiaomyung"
CREDIT_URL = "https://github.com/xiaomyung"

ROWS = (
    ("play", "Play", draw_play),
    ("battlepass", "Battle Pass", draw_medal),
    ("armory", "Armory", draw_shield),
    ("social", "Social", draw_people),
    ("history", "History", draw_clock),
)
OPTIONS_ROW = ("options", "Options", draw_gear)

ROW_CUT = 8
ROW_PAD = 14
ROW_GAP = 10
ROW_Y_OFFSET = 14
ICON_PAD = 38
ICON_SIDE = 18
LABEL_GAP = 7
LABEL_FONT_SIZE = 15
RETICLE_SLIDE_MS = 260
RETICLE_PULSE_MS = 900
RETICLE_SIZE = 22


class MenuRail:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.rect = pg.Rect(0, 0, 0, 0)
        self.scale = 1.0
        self.active = "play"
        self._row_rects = {}
        self._reticle_tween = None
        self._label_font = get_font(13, bold=True)
        self._version_font = get_mono_font(10)
        self._credit_font = get_font(11, bold=True)
        self._version_text = ""
        self._version_surf = None
        self._version_pos = (0, 0)
        self._credit_surf = None
        self._credit_rect = pg.Rect(0, 0, 0, 0)
        self._credit_hitbox = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect, scale):
        self.rect = pg.Rect(rect)
        self.scale = scale
        self._label_font = get_font(max(int(LABEL_FONT_SIZE * scale), 12), bold=True)
        self._version_font = get_mono_font(max(int(11 * scale), 9))
        self._credit_font = get_font(max(int(11 * scale), 9), bold=True)
        pad = max(int(ROW_PAD * scale), 9)
        row_h = max(int(46 * scale), 34)
        gap = max(int(ROW_GAP * scale), 6)
        x = rect.x + pad
        w = rect.width - 2 * pad
        y = rect.y + max(int(ROW_Y_OFFSET * scale), 8)
        self._row_rects = {}
        for key, _, _ in ROWS:
            self._row_rects[key] = pg.Rect(x, y, w, row_h)
            y += row_h + gap
        footer_h = max(int(46 * scale), 34)
        opt_y = rect.bottom - footer_h - row_h - max(int(10 * scale), 6)
        self._row_rects["options"] = pg.Rect(x, opt_y, w, row_h)
        self._build_footer(x, w, footer_h)
        target = self._row_rects[self.active].centery
        now = pg.time.get_ticks()
        if self._reticle_tween is None:
            self._reticle_tween = Tween(target, target, RETICLE_SLIDE_MS, now)
        else:
            self._reticle_tween.retarget(target, now)

    def _build_footer(self, x, w, footer_h):
        version = paths.get_app_version()
        self._version_text = f"v{version} · dev" if version else "dev"
        self._version_surf = render_text(self._version_font, self._version_text,
                                         Colors.text_dim)
        self._credit_surf = render_text(self._credit_font, CREDIT_TEXT, Colors.text_muted)
        base_y = self.rect.bottom - max(int(14 * self.scale), 8)
        credit_h = self._credit_surf.get_height()
        credit_y = base_y - credit_h
        self._credit_rect = pg.Rect(x, credit_y, self._credit_surf.get_width(), credit_h)
        self._credit_hitbox = self._credit_rect.inflate(max(int(10 * self.scale), 6),
                                                        max(int(10 * self.scale), 6))
        version_h = self._version_surf.get_height()
        self._version_pos = (x, credit_y - max(int(4 * self.scale), 2) - version_h)

    def set_active(self, name, now_ms):
        if name == self.active:
            return
        self.active = name
        if self._reticle_tween is not None and name in self._row_rects:
            self._reticle_tween.retarget(self._row_rects[name].centery, now_ms)

    def reticle_y(self, now_ms):
        if self._reticle_tween is None:
            return 0.0
        return self._reticle_tween.value(now_ms)

    def hit_test(self, pos):
        for key in list(self._row_rects):
            if self._row_rects[key].collidepoint(pos):
                return key
        return None

    def handle_footer_click(self, pos):
        if self._credit_hitbox.collidepoint(pos):
            self.callbacks["open_url"](CREDIT_URL)
            return True
        return False

    def draw(self, window, now_ms):
        if self.rect.width <= 0:
            return
        pg.draw.rect(window, pg.Color(Colors.surface), self.rect)
        pg.draw.line(window, pg.Color(Colors.border), (self.rect.right - 1, self.rect.top),
                     (self.rect.right - 1, self.rect.bottom - 1))
        mouse = pg.mouse.get_pos()
        cut = max(int(ROW_CUT * self.scale), 5)
        icon_side = max(int(ICON_SIDE * self.scale), 14)
        icon_pad = max(int(ICON_PAD * self.scale), 24)
        label_gap = max(int(LABEL_GAP * self.scale), 4)
        for key, label, icon_fn in ROWS + (OPTIONS_ROW,):
            rect = self._row_rects[key]
            active = key == self.active
            hovered = rect.collidepoint(mouse)
            if active:
                window.blit(cut_rect_surface(rect.size, cut, Colors.surface_raised,
                                             border=Colors.border_strong, border_width=1,
                                             corners=("tr", "bl")), rect.topleft)
                icon_color, text_color = Colors.text, Colors.text
            elif hovered:
                window.blit(cut_rect_surface(rect.size, cut, Colors.surface_hover,
                                             corners=("tr", "bl")), rect.topleft)
                icon_color, text_color = Colors.text, Colors.text
            else:
                icon_color, text_color = Colors.text_dim, Colors.text_dim
            icon_rect = pg.Rect(rect.x + icon_pad, rect.y, icon_side, rect.height)
            icon_fn(window, icon_rect, icon_color)
            label_surf = render_text(self._label_font, label, text_color)
            window.blit(label_surf, (icon_rect.right + label_gap,
                                     rect.centery - label_surf.get_height() // 2))
        self._draw_reticle(window, now_ms)
        self._draw_footer(window)

    def _draw_reticle(self, window, now_ms):
        if self._reticle_tween is None:
            return
        y = int(self._reticle_tween.value(now_ms))
        size = max(int(RETICLE_SIZE * self.scale), 16)
        cx = self._row_rects[self.active].x
        pulse = 0.5 + 0.5 * math.sin(now_ms / RETICLE_PULSE_MS * math.tau)
        alpha = int(150 + 90 * pulse)
        draw_reticle(window, pg.Rect(cx - size // 2, y - size // 2, size, size),
                     Colors.accent, alpha=alpha)

    def _draw_footer(self, window):
        if self._version_surf is None:
            return
        window.blit(self._version_surf, self._version_pos)
        window.blit(self._credit_surf, self._credit_rect.topleft)
        hovered = self._credit_hitbox.collidepoint(pg.mouse.get_pos())
        underline = Colors.text if hovered else Colors.text_dim
        pg.draw.line(window, underline, (self._credit_rect.x, self._credit_rect.bottom - 1),
                     (self._credit_rect.right - 1, self._credit_rect.bottom - 1))
