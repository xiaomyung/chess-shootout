import math

import pygame as pg

from chessshootout.frontend.visual import gunfx
from chessshootout.frontend.visual.colors import Colors

FOCUS_ARROW_D = 34
FOCUS_ARROW_REVEAL_MS = 200.0
FOCUS_ARROW_HIDE_MS = 260.0
FOCUS_ARROW_HOVER_MS = 110.0
FOCUS_ARROW_HIDE_DX = 44
FOCUS_ARROW_BOB_PX = 2.5
FOCUS_ARROW_BOB_MS = 1800.0
FOCUS_ARROW_HOVER_SCALE = 1.14
FOCUS_EDGE_ZONE_PX = 60
FOCUS_ARROW_IDLE_ALPHA = 210
FOCUS_ARROW_HOVER_ALPHA = 255
FOCUS_ARROW_HIT_SLOP = 10
LONG_AGO_MS = -100000.0
_SS = 4


class FocusArrow:

    def __init__(self):
        self._focus_on = False
        self._shown = False
        self._slide_start = LONG_AGO_MS
        self._hovering = False
        self._hover_start = LONG_AGO_MS
        self._visible = False
        self._bounds = pg.Rect(0, 0, 0, 0)
        self._prev_bounds = pg.Rect(0, 0, 0, 0)
        self._alpha = FOCUS_ARROW_IDLE_ALPHA
        self._glyphs = {}

    def reset(self):
        self._shown = False
        self._hovering = False
        self._visible = False
        self._bounds = pg.Rect(0, 0, 0, 0)
        self._prev_bounds = pg.Rect(0, 0, 0, 0)

    def is_visible(self):
        return self._visible and self._bounds.width > 0

    def update(self, now, shown, anchor, mouse_pos, focus_on):
        self._focus_on = focus_on
        self._prev_bounds = self._bounds.copy()
        if shown != self._shown:
            self._shown = shown
            self._slide_start = now
        prog = self._slide_progress(now)
        if prog <= 0.01 or anchor is None:
            self._visible = False
            self._bounds = pg.Rect(0, 0, 0, 0)
            return
        self._visible = True
        bob = math.sin(now / FOCUS_ARROW_BOB_MS * 2 * math.pi) * FOCUS_ARROW_BOB_PX * prog
        cx = anchor[0] + FOCUS_ARROW_HIDE_DX * (1.0 - prog)
        cy = anchor[1] + bob
        base = pg.Rect(0, 0, FOCUS_ARROW_D, FOCUS_ARROW_D)
        base.center = (int(cx), int(cy))
        hovering = mouse_pos is not None and base.collidepoint(mouse_pos)
        if hovering != self._hovering:
            self._hovering = hovering
            self._hover_start = now
        hv = gunfx.smoothstep((now - self._hover_start) / FOCUS_ARROW_HOVER_MS)
        hv = hv if self._hovering else 1.0 - hv
        scale = 1.0 + (FOCUS_ARROW_HOVER_SCALE - 1.0) * hv
        sized = pg.Rect(0, 0, int(FOCUS_ARROW_D * scale), int(FOCUS_ARROW_D * scale))
        sized.center = base.center
        self._bounds = sized
        alpha = FOCUS_ARROW_IDLE_ALPHA + (FOCUS_ARROW_HOVER_ALPHA - FOCUS_ARROW_IDLE_ALPHA) * hv
        self._alpha = max(0, min(255, int(alpha * prog)))

    def _slide_progress(self, now):
        dur = FOCUS_ARROW_REVEAL_MS if self._shown else FOCUS_ARROW_HIDE_MS
        e = gunfx.smoothstep((now - self._slide_start) / dur)
        return e if self._shown else 1.0 - e

    def hit_test(self, pos):
        return (self.is_visible()
                and self._bounds.inflate(FOCUS_ARROW_HIT_SLOP, FOCUS_ARROW_HIT_SLOP)
                .collidepoint(pos))

    def handle_click(self, pos):
        return self.hit_test(pos)

    def dirty_rect(self):
        slop = FOCUS_ARROW_HIT_SLOP
        r = self._bounds.inflate(slop, slop) if self._bounds.width > 0 else pg.Rect(0, 0, 0, 0)
        if self._prev_bounds.width > 0:
            r = r.union(self._prev_bounds.inflate(slop, slop))
        return r

    def draw(self, window):
        if not self._visible or self._bounds.width <= 0:
            return
        glyph = self._glyph(self._focus_on)
        if self._bounds.size != (FOCUS_ARROW_D, FOCUS_ARROW_D):
            glyph = pg.transform.smoothscale(glyph, self._bounds.size)
        else:
            glyph = glyph.copy()
        glyph.set_alpha(self._alpha)
        window.blit(glyph, self._bounds.topleft)

    def _glyph(self, focus_on):
        if focus_on not in self._glyphs:
            self._glyphs[focus_on] = self._build_glyph(focus_on)
        return self._glyphs[focus_on]

    def _build_glyph(self, focus_on):
        d = FOCUS_ARROW_D * _SS
        surf = pg.Surface((d, d), pg.SRCALPHA)
        c = d // 2
        r = c - _SS
        pg.draw.circle(surf, pg.Color(Colors.surface_raised), (c, c), r)
        pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), r, _SS)
        reach = d * 0.17
        half = d * 0.19
        if focus_on:
            tip_x, back_x = c - reach, c + reach
        else:
            tip_x, back_x = c + reach, c - reach
        points = [(tip_x, c), (back_x, c - half), (back_x, c + half)]
        cxs = sum(p[0] for p in points) / 3.0
        dx = c - cxs
        points = [(p[0] + dx, p[1]) for p in points]
        pg.draw.polygon(surf, pg.Color(Colors.text_dim), points)
        return pg.transform.smoothscale(surf, (FOCUS_ARROW_D, FOCUS_ARROW_D))
