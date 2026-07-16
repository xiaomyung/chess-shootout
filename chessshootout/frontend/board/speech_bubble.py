import pygame as pg

from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface, scale_floor
from chessshootout.frontend.visual.fonts import get_font


BUBBLE_MS = 2800
BUBBLE_POP_MS = 160
BUBBLE_FADE_MS = 350
BUBBLE_CUT = 8
BUBBLE_TAIL_W = 10
BUBBLE_TAIL_H = 7
BUBBLE_PAD_X = 10
BUBBLE_PAD_Y = 6
BUBBLE_GAP = 4

BUBBLE_TEXT = 11
POP_START = 0.7
POP_STEPS = 8

_CUT_FLOOR = 5
_TEXT_FLOOR = 9
_TAIL_W_FLOOR = 6
_TAIL_H_FLOOR = 4
_PAD_X_FLOOR = 6
_PAD_Y_FLOOR = 4
_GAP_FLOOR = 2

_BUBBLE_CACHE = new_cache()


def _build_base(text, flipped, scale):
    font = get_font(scale_floor(BUBBLE_TEXT, scale, _TEXT_FLOOR), bold=True)
    text_surf = font.render(text.upper(), True, pg.Color(Colors.text))
    pad_x = scale_floor(BUBBLE_PAD_X, scale, _PAD_X_FLOOR)
    pad_y = scale_floor(BUBBLE_PAD_Y, scale, _PAD_Y_FLOOR)
    tail_w = scale_floor(BUBBLE_TAIL_W, scale, _TAIL_W_FLOOR)
    tail_h = scale_floor(BUBBLE_TAIL_H, scale, _TAIL_H_FLOOR)
    cut = scale_floor(BUBBLE_CUT, scale, _CUT_FLOOR)
    body_w = text_surf.get_width() + 2 * pad_x
    body_h = text_surf.get_height() + 2 * pad_y
    surf = pg.Surface((body_w, body_h + tail_h), pg.SRCALPHA)
    body_y = tail_h if flipped else 0
    shell = cut_rect_surface((body_w, body_h), cut, Colors.surface,
                             border=Colors.border, border_width=1, corners=("br",))
    surf.blit(shell, (0, body_y))
    surface_col = pg.Color(Colors.surface)
    border_col = pg.Color(Colors.border)
    cx = body_w / 2.0
    half = tail_w / 2.0
    if flipped:
        apex = (cx, 0.0)
        base_l = (cx - half, float(tail_h))
        base_r = (cx + half, float(tail_h))
        pg.draw.rect(surf, surface_col, pg.Rect(int(cx - half), tail_h - 1, tail_w, 3))
    else:
        apex = (cx, float(body_h + tail_h))
        base_l = (cx - half, float(body_h))
        base_r = (cx + half, float(body_h))
        pg.draw.rect(surf, surface_col, pg.Rect(int(cx - half), body_h - 2, tail_w, 3))
    pg.draw.polygon(surf, surface_col, (base_l, base_r, apex))
    pg.draw.aaline(surf, border_col, base_l, apex)
    pg.draw.aaline(surf, border_col, base_r, apex)
    surf.blit(text_surf, (pad_x, body_y + pad_y))
    return surf


def _base_surface(text, flipped, scale):
    key = (text, flipped, round(scale, 3))
    return memoized_surface(_BUBBLE_CACHE, key,
                            lambda: _build_base(text, flipped, scale))


class SpeechBubble:

    def __init__(self):
        self.text = ""
        self.shown_at = None
        self.last_rect = None
        self._owned = {}
        self._pop_variants = {}

    def show(self, text, now_ms):
        self.text = text.upper()
        self.shown_at = now_ms
        self.last_rect = None
        self._owned = {}
        self._pop_variants = {}

    def active(self, now_ms):
        return self.shown_at is not None and 0 <= now_ms - self.shown_at < BUBBLE_MS

    def clear(self):
        self.shown_at = None
        self.last_rect = None
        self._owned = {}
        self._pop_variants = {}

    def _anim(self, now_ms):
        age = now_ms - self.shown_at
        p = min(1.0, max(0.0, age / BUBBLE_POP_MS))
        eased = 1.0 - (1.0 - p) ** 3
        bucket = min(POP_STEPS - 1, int(eased * POP_STEPS))
        remaining = BUBBLE_MS - age
        if remaining < BUBBLE_FADE_MS:
            alpha = max(0, min(255, int(255 * remaining / BUBBLE_FADE_MS)))
        else:
            alpha = 255
        return bucket, alpha

    def _pop_variant(self, flipped, bucket, base):
        key = (flipped, bucket)
        surf = self._pop_variants.get(key)
        if surf is None:
            pop = POP_START + (1.0 - POP_START) * (bucket / (POP_STEPS - 1))
            w, h = base.get_size()
            surf = pg.transform.smoothscale(
                base, (max(1, int(w * pop)), max(1, int(h * pop))))
            self._pop_variants[key] = surf
        return surf

    def _owned_surface(self, flipped, base):
        surf = self._owned.get(flipped)
        if surf is None:
            surf = base.copy()
            self._owned[flipped] = surf
        return surf

    def draw(self, window, anchor_rect, bounds_rect, now_ms, scale=1.0):
        if not self.active(now_ms):
            self.last_rect = None
            return
        gap = scale_floor(BUBBLE_GAP, scale, _GAP_FLOOR)
        base = _base_surface(self.text, False, scale)
        w, h = base.get_size()
        flipped = (anchor_rect.top - gap - h) < bounds_rect.top
        if flipped:
            base = _base_surface(self.text, True, scale)
            y = anchor_rect.bottom + gap
        else:
            y = anchor_rect.top - gap - h
        x = anchor_rect.centerx - w // 2
        x = max(bounds_rect.left + gap, min(x, bounds_rect.right - w - gap))
        rect = pg.Rect(x, y, w, h)
        bucket, alpha = self._anim(now_ms)
        if bucket < POP_STEPS - 1:
            scaled = self._pop_variant(flipped, bucket, base)
            draw_rect = scaled.get_rect(center=rect.center)
            window.blit(scaled, draw_rect.topleft)
            self.last_rect = draw_rect
            return
        if alpha >= 255:
            window.blit(base, rect.topleft)
        else:
            owned = self._owned_surface(flipped, base)
            owned.set_alpha(alpha)
            window.blit(owned, rect.topleft)
        self.last_rect = rect
