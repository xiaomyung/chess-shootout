import math

import pygame as pg

from chessshootout.frontend.modals.base import BaseModal
from chessshootout.online.client import RECONNECT_TOTAL_SECONDS
from chessshootout.frontend.visual.clock_visual import format_countdown
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.cache import new_cache, memoized_surface, render_text
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.widgets import draw_button_row
from chessshootout.frontend.visual.fonts import (
    fonts_for_width, get_display_font, get_font, get_mono_font,
)


SPINNER_STROKE = 3
SPINNER_GAP_DEG = 70
SPIN_MS = 1000

REF_DIAG = 480.0
SPINNER_REF = 56
HEADING_REF = 26
SUB_REF = 13
COUNTDOWN_REF = 30
BUTTON_REF = 15
GAP_REF = 16
BUTTON_HEIGHT_REF = 46

_RING_CACHE = new_cache()


def _ring_base(size, color):
    def build():
        def render(surf, k):
            s = surf.get_width()
            c = (s / 2, s / 2)
            stroke = max(int(SPINNER_STROKE * k), 2)
            pg.draw.circle(surf, pg.Color(color), c, s / 2)
            pg.draw.circle(surf, (0, 0, 0, 0), c, s / 2 - stroke)
            base = math.radians(-90)
            g = math.radians(SPINNER_GAP_DEG)
            a0, a1 = base - g / 2, base + g / 2
            wedge = [c]
            for i in range(13):
                a = a0 + (a1 - a0) * i / 12
                wedge.append((c[0] + s * math.cos(a), c[1] + s * math.sin(a)))
            pg.draw.polygon(surf, (0, 0, 0, 0), wedge)
        return supersample(int(size), render)
    return memoized_surface(_RING_CACHE, (int(size), color), build)


def _ring_surface(size, color, angle_deg):
    base = _ring_base(size, color)
    return pg.transform.rotozoom(base, -angle_deg, 1.0)


class ReconnectingModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.on_abandon = None
        self._disconnected_at_ms = None
        self.button_rects = {}
        self._font_cache = {}

    def show(self, disconnected_at_ms, on_abandon):
        super().show()
        self._disconnected_at_ms = disconnected_at_ms
        self.on_abandon = on_abandon

    def hide(self):
        super().hide()
        self.on_abandon = None
        self._disconnected_at_ms = None
        self.button_rects = {}

    def _remaining(self):
        if self._disconnected_at_ms is None:
            return RECONNECT_TOTAL_SECONDS
        elapsed = (pg.time.get_ticks() - self._disconnected_at_ms) / 1000.0
        return RECONNECT_TOTAL_SECONDS - elapsed

    def _fonts(self, scale):
        return fonts_for_width(self._font_cache, scale, self._build_fonts)

    def _build_fonts(self, scale):
        return (
            get_display_font(max(int(HEADING_REF * scale), 16)),
            get_font(max(int(SUB_REF * scale), 11), bold=False),
            get_mono_font(max(int(COUNTDOWN_REF * scale), 18), bold=True),
            get_font(max(int(BUTTON_REF * scale), 12), bold=True),
        )

    def draw(self):
        if not self.visible or self.rect.width <= 0:
            self.button_rects = {}
            return
        rect = self.rect
        scrim = pg.Surface(rect.size, pg.SRCALPHA)
        scrim.fill(pg.Color(Colors.overlay_scrim))
        self.window.blit(scrim, rect.topleft)

        scale = min(1.0, min(rect.width, rect.height) / REF_DIAG)
        spinner = max(int(SPINNER_REF * scale), 30)
        heading_font, sub_font, cd_font, button_font = self._fonts(scale)

        heading = render_text(heading_font, "RECONNECTING…", Colors.text)
        sub = render_text(sub_font, "Hang tight, restoring your game", Colors.text_dim)
        cd = render_text(cd_font, format_countdown(self._remaining()), Colors.amber_hi)

        g = max(int(GAP_REF * scale), 8)
        btn_h = max(int(BUTTON_HEIGHT_REF * scale), 30)
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
            self.window, row, [("Abandon game", "abandon")], button_font, self.padding,
            cut=True)

    def handle_click(self, pos):
        if not self.visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                if self.on_abandon is not None:
                    self.on_abandon()
                return True
        return False
