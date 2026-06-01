import math

import pygame as pg

from frontend.modals.base import BaseModal
from frontend.online.client import RECONNECT_TOTAL_SECONDS
from frontend.panels.player_strip import format_countdown
from frontend.visual.colors import Colors
from frontend.visual.draw import supersample
from frontend.visual.widgets import draw_button_row
from frontend.visual.fonts import get_display_font, get_font, get_mono_font


SPINNER_STROKE = 3
SPINNER_GAP_DEG = 70
SPIN_MS = 1000


def _ring_surface(size, color, angle_deg):
    def render(surf, k):
        s = surf.get_width()
        c = (s / 2, s / 2)
        stroke = max(int(SPINNER_STROKE * k), 2)
        pg.draw.circle(surf, pg.Color(color), c, s / 2)
        pg.draw.circle(surf, (0, 0, 0, 0), c, s / 2 - stroke)
        base = math.radians(-90 + angle_deg)
        g = math.radians(SPINNER_GAP_DEG)
        a0, a1 = base - g / 2, base + g / 2
        wedge = [c]
        for i in range(13):
            a = a0 + (a1 - a0) * i / 12
            wedge.append((c[0] + s * math.cos(a), c[1] + s * math.sin(a)))
        pg.draw.polygon(surf, (0, 0, 0, 0), wedge)
    return supersample(int(size), render)


class ReconnectingModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self.on_cancel = None
        self._disconnected_at_ms = None
        self.button_rects = {}

    def show(self, disconnected_at_ms, on_cancel):
        self._visible = True
        self._disconnected_at_ms = disconnected_at_ms
        self.on_cancel = on_cancel

    def hide(self):
        self._visible = False
        self.on_cancel = None
        self._disconnected_at_ms = None
        self.button_rects = {}

    def is_visible(self):
        return self._visible

    def _remaining(self):
        if self._disconnected_at_ms is None:
            return RECONNECT_TOTAL_SECONDS
        elapsed = (pg.time.get_ticks() - self._disconnected_at_ms) / 1000.0
        return RECONNECT_TOTAL_SECONDS - elapsed

    def draw(self):
        if not self._visible or self.rect.width <= 0:
            self.button_rects = {}
            return
        rect = self.rect
        scrim = pg.Surface(rect.size, pg.SRCALPHA)
        scrim.fill(pg.Color(Colors.overlay_scrim))
        self.window.blit(scrim, rect.topleft)

        scale = min(1.0, min(rect.width, rect.height) / 480.0)
        spinner = max(int(56 * scale), 30)
        heading_font = get_display_font(max(int(26 * scale), 16))
        sub_font = get_font(max(int(13 * scale), 11), bold=False)
        cd_font = get_mono_font(max(int(30 * scale), 18), bold=True)
        button_font = get_font(max(int(15 * scale), 12), bold=True)

        heading = heading_font.render("RECONNECTING…", True, Colors.white)
        sub = sub_font.render("Hang tight, restoring your game", True, Colors.text_dim)
        cd = cd_font.render(format_countdown(self._remaining()), True, Colors.amber_hi)

        g = max(int(16 * scale), 8)
        btn_h = max(int(46 * scale), 30)
        total = (spinner + g + heading.get_height() + g // 2 + sub.get_height()
                 + g + cd.get_height() + g + btn_h)
        y = rect.centery - total / 2
        cx = rect.centerx

        angle = (pg.time.get_ticks() % SPIN_MS) / SPIN_MS * 360
        ring = _ring_surface(spinner, Colors.amber, angle)
        self.window.blit(ring, (cx - ring.get_width() / 2,
                                y + spinner / 2 - ring.get_height() / 2))
        y += spinner + g
        self.window.blit(heading, (cx - heading.get_width() / 2, y))
        y += heading.get_height() + g // 2
        self.window.blit(sub, (cx - sub.get_width() / 2, y))
        y += sub.get_height() + g
        self.window.blit(cd, (cx - cd.get_width() / 2, y))
        y += cd.get_height() + g

        row_w = min(int(rect.width * 0.7), 220)
        row = pg.Rect(cx - row_w / 2, y, row_w, btn_h)
        self.button_rects = draw_button_row(
            self.window, row, [("Abandon game", "abandon")], button_font, self.padding)

    def handle_click(self, pos):
        if not self._visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                if self.on_cancel is not None:
                    self.on_cancel()
                return True
        return False
