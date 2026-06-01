import math

import pygame as pg

from frontend.modals.base import BaseModal, MODAL_RAIL
from frontend.panels.player_strip import format_countdown
from frontend.visual.colors import Colors
from frontend.visual.draw import supersample, rounded_rect_surface, circle_surface
from frontend.visual.widgets import draw_button_row
from frontend.visual.fonts import get_display_font, get_font, get_mono_font


RADAR_SWEEP_MS = 1400
RADAR_PING_MS = 1600
_SWEEP_CACHE = {}


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
        self._visible = False
        self.mode_label = ""
        self.tc_text = ""
        self.elapsed = 0
        self.on_cancel = None
        self.button_rects = {}

    def show(self, mode_label, tc_text, on_cancel):
        self._visible = True
        self.mode_label = mode_label
        self.tc_text = tc_text
        self.elapsed = 0
        self.on_cancel = on_cancel

    def set_elapsed(self, seconds):
        self.elapsed = seconds

    def hide(self):
        self._visible = False
        self.on_cancel = None
        self.button_rects = {}

    def is_visible(self):
        return self._visible

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

    def draw(self):
        if not self._visible or self.rect.width <= 0:
            self.button_rects = {}
            return
        pad = self.padding
        panel_w = min(self.rect.width, 440)
        title_font = get_display_font(max(int(panel_w * 0.06), 20))
        sub_font = get_font(max(int(panel_w * 0.03), 12), bold=False)
        mode_font = get_font(max(int(panel_w * 0.024), 9), bold=True)
        tc_font = get_mono_font(max(int(panel_w * 0.034), 13), bold=True)
        elapsed_font = get_mono_font(max(int(panel_w * 0.03), 11))
        button_font = get_font(max(int(panel_w * 0.034), 13), bold=True)
        radar = min(68, max(int(panel_w * 0.15), 52))

        title = title_font.render("SEARCHING…", True, Colors.white)
        sub = sub_font.render("Finding you an opponent", True, Colors.text_dim)
        elapsed = elapsed_font.render(
            f"elapsed {format_countdown(self.elapsed)}", True, Colors.text_mute)
        mode = mode_font.render(self.mode_label.upper(), True, Colors.amber_hi)
        tc = tc_font.render(self.tc_text, True, Colors.white)
        pill_h = max(mode.get_height(), tc.get_height()) + 12
        pill_w = mode.get_width() + 8 + tc.get_width() + 28

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
                                    Colors.surface, border=Colors.button_border)
        px = cx - pill_w / 2
        self.window.blit(pill, (px, y))
        pcy = y + pill_h / 2
        self.window.blit(mode, (px + 14, pcy - mode.get_height() / 2))
        self.window.blit(tc, (px + 14 + mode.get_width() + 8, pcy - tc.get_height() / 2))
        y += pill_h + g2
        self.window.blit(elapsed, (cx - elapsed.get_width() / 2, y))

        row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        self.button_rects = draw_button_row(
            self.window, row, [("Cancel search", "cancel")], button_font, pad)

    def handle_click(self, pos):
        if not self._visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                callback = self.on_cancel
                self.hide()
                if callback is not None:
                    callback()
                return True
        return False
