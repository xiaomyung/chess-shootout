import math

import pygame as pg

from chessshootout import paths
from chessshootout.frontend.menu.view import scale_floor
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
ROW_H = 46
ROW_MIN_H = 34
ICON_X = 48
ICON_SIDE = 35
LABEL_X = 83
LABEL_FONT_SIZE = 15
FOOTER_FONT_SIZE = 13
FOOTER_FONT_FLOOR = 11
RETICLE_SLIDE_MS = 260
RETICLE_PULSE_MS = 900
RETICLE_SIZE = 28
RETICLE_INSET = 20
RETICLE_ALPHA_FLOOR = 190


class MenuRail:

    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.rect = pg.Rect(0, 0, 0, 0)
        self.scale = 1.0
        self.active = "play"
        self._row_rects = {}
        self._reticle_tween = None
        self._label_font = get_font(13, bold=True)
        self._footer_font = get_mono_font(FOOTER_FONT_FLOOR)
        self._footer_prefix = ""
        self._footer_prefix_surf = None
        self._footer_prefix_pos = (0, 0)
        self._credit_surf = None
        self._credit_rect = pg.Rect(0, 0, 0, 0)
        self._credit_hitbox = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect, scale):
        old_rects = self._row_rects
        self.rect = pg.Rect(rect)
        self.scale = scale
        self._label_font = get_font(scale_floor(LABEL_FONT_SIZE, scale, 12), bold=True)
        self._footer_font = get_mono_font(scale_floor(FOOTER_FONT_SIZE, scale, FOOTER_FONT_FLOOR))
        pad = scale_floor(ROW_PAD, scale, 9)
        row_h = scale_floor(ROW_H, scale, ROW_MIN_H)
        gap = scale_floor(ROW_GAP, scale, 6)
        x = rect.x + pad
        w = rect.width - 2 * pad
        y = rect.y + scale_floor(ROW_Y_OFFSET, scale, 8)
        self._row_rects = {}
        for key, _, _ in ROWS:
            self._row_rects[key] = pg.Rect(x, y, w, row_h)
            y += row_h + gap
        footer_h = scale_floor(ROW_H, scale, ROW_MIN_H)
        opt_y = rect.bottom - footer_h - row_h - scale_floor(10, scale, 6)
        self._row_rects["options"] = pg.Rect(x, opt_y, w, row_h)
        self._build_footer()
        self._remap_reticle(old_rects)

    def _remap_reticle(self, old_rects):
        if self.active not in self._row_rects:
            return
        row_rect = self._row_rects[self.active]
        if self._reticle_tween is not None and old_rects.get(self.active) == row_rect:
            return
        target = row_rect.centery
        self._reticle_tween = Tween(target, target, RETICLE_SLIDE_MS, 0)

    def _build_footer(self):
        version = paths.get_app_version()
        version_label = f"v{version}" if version else "dev"
        self._footer_prefix = f"{version_label} · by "
        self._footer_prefix_surf = render_text(self._footer_font, self._footer_prefix,
                                               Colors.text_muted)
        self._credit_surf = render_text(self._footer_font, CREDIT_TEXT, Colors.text_dim)
        base_y = self.rect.bottom - scale_floor(14, self.scale, 8)
        line_h = max(self._footer_prefix_surf.get_height(), self._credit_surf.get_height())
        line_y = base_y - line_h
        total_w = self._footer_prefix_surf.get_width() + self._credit_surf.get_width()
        start_x = self.rect.x + (self.rect.width - total_w) // 2
        self._footer_prefix_pos = (start_x, line_y)
        credit_x = start_x + self._footer_prefix_surf.get_width()
        self._credit_rect = pg.Rect(credit_x, line_y, self._credit_surf.get_width(), line_h)
        self._credit_hitbox = self._credit_rect.inflate(scale_floor(8, self.scale, 4),
                                                        scale_floor(8, self.scale, 4))

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
        return next((key for key, rect in self._row_rects.items() if rect.collidepoint(pos)),
                    None)

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
        cut = scale_floor(ROW_CUT, self.scale, 5)
        icon_side = scale_floor(ICON_SIDE, self.scale, 19)
        icon_x = self.rect.x + scale_floor(ICON_X, self.scale, 40)
        label_x = self.rect.x + scale_floor(LABEL_X, self.scale, 63)
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
            icon_rect = pg.Rect(icon_x, rect.y, icon_side, rect.height)
            icon_fn(window, icon_rect, icon_color)
            label_surf = render_text(self._label_font, label, text_color)
            window.blit(label_surf, (label_x, rect.centery - label_surf.get_height() // 2))
        self._draw_reticle(window, now_ms)
        self._draw_footer(window)

    def _draw_reticle(self, window, now_ms):
        if self._reticle_tween is None or self.active not in self._row_rects:
            return
        y = int(self._reticle_tween.value(now_ms))
        size = scale_floor(RETICLE_SIZE, self.scale, 20)
        cx = self._row_rects[self.active].x + scale_floor(RETICLE_INSET, self.scale, 12)
        pulse = 0.5 + 0.5 * math.sin(now_ms / RETICLE_PULSE_MS * math.tau)
        alpha = int(RETICLE_ALPHA_FLOOR + (255 - RETICLE_ALPHA_FLOOR) * pulse)
        draw_reticle(window, pg.Rect(cx - size // 2, y - size // 2, size, size),
                     Colors.accent, alpha=alpha)

    def _draw_footer(self, window):
        if self._footer_prefix_surf is None:
            return
        window.blit(self._footer_prefix_surf, self._footer_prefix_pos)
        window.blit(self._credit_surf, self._credit_rect.topleft)
        hovered = self._credit_hitbox.collidepoint(pg.mouse.get_pos())
        underline = Colors.text if hovered else Colors.text_dim
        pg.draw.line(window, underline, (self._credit_rect.x, self._credit_rect.bottom - 1),
                     (self._credit_rect.right - 1, self._credit_rect.bottom - 1))
