import math

import pygame as pg

from chessshootout.frontend.modals.base import BaseModal, MODAL_MAX_WIDTH, MODAL_RAIL
from chessshootout.frontend.visual.clock_visual import format_countdown
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample, rounded_rect_surface, circle_surface
from chessshootout.frontend.visual.widgets import draw_button_row
from chessshootout.frontend.visual.fonts import (
    fonts_for_width, get_display_font, get_font, get_mono_font,
)


RADAR_SWEEP_MS = 1400
RADAR_PING_MS = 1600
_SWEEP_CACHE = {}

PILL_VPAD = 12
PILL_INSET = 14
PILL_GAP = 8
PILL_HPAD = 28


def _radar_sweep(size, color):
    key = (size, color)
    if key not in _SWEEP_CACHE:
        def render(surf, k):
            s = surf.get_width()
            cx = cy = s / 2
            outer = s / 2
            inner = s * 0.40
            base = pg.Color(color)
            steps = 120
            for i in range(steps):
                frac = i / steps
                if frac < 0.55:
                    continue
                alpha = int(210 * (frac - 0.55) / 0.45)
                a0 = math.radians(i * 360 / steps)
                a1 = math.radians((i + 1) * 360 / steps)
                col = pg.Color(base.r, base.g, base.b, alpha)
                pg.draw.polygon(surf, col, [
                    (cx, cy),
                    (cx + outer * math.cos(a0), cy + outer * math.sin(a0)),
                    (cx + outer * math.cos(a1), cy + outer * math.sin(a1)),
                ])
            pg.draw.circle(surf, (0, 0, 0, 0), (int(cx), int(cy)), int(inner))
        _SWEEP_CACHE[key] = supersample(int(size), render)
    return _SWEEP_CACHE[key]


class WaitModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.mode_label = ""
        self.tc_text = ""
        self.elapsed = 0
        self.on_cancel = None
        self.button_rects = {}
        self._font_cache = {}

    def show(self, mode_label, tc_text, on_cancel):
        super().show()
        self.mode_label = mode_label
        self.tc_text = tc_text
        self.elapsed = 0
        self.on_cancel = on_cancel

    def set_elapsed(self, seconds):
        self.elapsed = seconds

    def hide(self):
        super().hide()
        self.on_cancel = None
        self.button_rects = {}

    def _draw_radar(self, cx, cy, size):
        now = pg.time.get_ticks()
        lsize = int(size * 1.4)
        pt = (now % RADAR_PING_MS) / RADAR_PING_MS

        def render(surf, k):
            s = surf.get_width()
            c = (s / 2, s / 2)
            r = (size / 2) * k
            stroke = max(int(2 * k), 2)
            ring = pg.Color(Colors.accent)
            ring.a = 80
            pg.draw.circle(surf, ring, c, int(r - k), stroke)
            ping = pg.Color(Colors.accent)
            ping.a = int(180 * (1 - pt))
            pg.draw.circle(surf, ping, c, max(int(r * (0.7 + 0.55 * pt)), 1), stroke)
        self.window.blit(supersample(lsize, render),
                         (cx - lsize / 2, cy - lsize / 2))
        sweep = pg.transform.rotozoom(
            _radar_sweep(int(size), Colors.accent),
            -(now % RADAR_SWEEP_MS) / RADAR_SWEEP_MS * 360, 1.0)
        self.window.blit(sweep, (cx - sweep.get_width() / 2, cy - sweep.get_height() / 2))
        dot = circle_surface(max(int(size * 0.12), 6), Colors.accent)
        self.window.blit(dot, (cx - dot.get_width() / 2, cy - dot.get_height() / 2))

    def _fonts(self, panel_w):
        return fonts_for_width(self._font_cache, panel_w, self._build_fonts)

    def _build_fonts(self, panel_w):
        return (
            get_display_font(max(int(panel_w * 0.06), 20)),
            get_font(max(int(panel_w * 0.03), 12), bold=False),
            get_font(max(int(panel_w * 0.024), 9), bold=True),
            get_mono_font(max(int(panel_w * 0.034), 13), bold=True),
            get_mono_font(max(int(panel_w * 0.03), 11)),
            get_font(max(int(panel_w * 0.034), 13), bold=True),
        )

    def draw(self):
        if not self.visible or self.rect.width <= 0:
            self.button_rects = {}
            return
        pad = self.padding
        panel_w = min(self.rect.width, MODAL_MAX_WIDTH)
        (title_font, sub_font, mode_font, tc_font,
         elapsed_font, button_font) = self._fonts(panel_w)
        radar = min(68, max(int(panel_w * 0.15), 52))

        title = title_font.render("SEARCHING…", True, Colors.text)
        sub = sub_font.render("Finding you an opponent", True, Colors.text_dim)
        elapsed = elapsed_font.render(
            f"elapsed {format_countdown(self.elapsed)}", True, Colors.text_muted)
        mode = mode_font.render(self.mode_label.upper(), True, Colors.amber_hi)
        tc = tc_font.render(self.tc_text, True, Colors.text)
        pill_h = max(mode.get_height(), tc.get_height()) + PILL_VPAD
        pill_w = mode.get_width() + PILL_GAP + tc.get_width() + PILL_HPAD

        g = max(int(panel_w * 0.03), 12)
        g2 = max(int(panel_w * 0.012), 5)
        btn_h = max(int(panel_w * 0.11), 38)
        panel_h = (MODAL_RAIL + pad + radar + g + title.get_height() + g2
                   + sub.get_height() + g + pill_h + g2 + elapsed.get_height()
                   + g + btn_h + pad)
        panel = pg.Rect(0, 0, panel_w, panel_h)
        panel.center = self.rect.center

        self.draw_shell(None, panel)
        content = self.content_rect(panel)
        cx = content.centerx
        y = content.y
        self._draw_radar(cx, y + radar / 2, radar)
        y += radar + g
        self.window.blit(title, (cx - title.get_width() / 2, y))
        y += title.get_height() + g2
        self.window.blit(sub, (cx - sub.get_width() / 2, y))
        y += sub.get_height() + g

        pill = rounded_rect_surface((int(pill_w), int(pill_h)), pill_h // 2,
                                    Colors.surface, border=Colors.border)
        px = cx - pill_w / 2
        self.window.blit(pill, (px, y))
        pcy = y + pill_h / 2
        self.window.blit(mode, (px + PILL_INSET, pcy - mode.get_height() / 2))
        self.window.blit(tc, (px + PILL_INSET + mode.get_width() + PILL_GAP,
                              pcy - tc.get_height() / 2))
        y += pill_h + g2
        self.window.blit(elapsed, (cx - elapsed.get_width() / 2, y))

        row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        self.button_rects = draw_button_row(
            self.window, row, [("Cancel search", "cancel")], button_font, pad, cut=True)

    def handle_click(self, pos):
        if not self.visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                callback = self.on_cancel
                self.hide()
                if callback is not None:
                    callback()
                return True
        return False
