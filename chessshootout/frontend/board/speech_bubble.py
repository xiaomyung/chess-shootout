from typing import cast

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


def _build_base(text: str, flipped: bool, scale: float) -> pg.Surface:
    """
    Draw the bubble a quick-chat line is shown in: a cut-corner plate with the
    line in it and a tail pointing at the piece it belongs to. The tail sits
    below the plate normally and above it when the bubble had to be flipped
    under the piece for want of room

    :param text: line to show, drawn in upper case
    :param flipped: True when the bubble hangs below its piece, which puts the
        tail on top
    :param scale: UI scale factor, which every padding and font size follows
    :returns: the finished bubble, tail included
    """
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


def _base_surface(text: str, flipped: bool, scale: float) -> pg.Surface:
    """
    Fetch the bubble for a line, building it only the first time it is asked
    for. The preset lines repeat all game, so this keeps the text rendering off
    the frame path

    :param text: line to show
    :param flipped: True for the below-the-piece version, which is cached apart
    :param scale: UI scale factor, part of the cache key
    :returns: the shared bubble surface, which callers must not draw on
    """
    key = (text, flipped, round(scale, 3))
    return memoized_surface(_BUBBLE_CACHE, key,
                            lambda: _build_base(text, flipped, scale))


class SpeechBubble:
    """
    One player's quick-chat bubble: the canned line they last sent, popping
    into view over their king or queen and fading out after a few seconds. The
    game screen keeps one per side and both players see the same thing, since
    sender and receiver drive it the same way
    """

    def __init__(self) -> None:
        """
        Start with no line to show. A bubble exists for the whole game and is
        simply idle until a quick-chat line arrives
        """
        self.text = ""
        self.shown_at: int | None = None
        self.last_rect: pg.Rect | None = None
        self._owned: dict[bool, pg.Surface] = {}
        self._pop_variants: dict[tuple[bool, int], pg.Surface] = {}

    def show(self, text: str, now_ms: int) -> None:
        """
        Show a line from now, restarting the pop and the fade even if a bubble
        was already up, so the newest line is always the one on screen

        :param text: preset line to show, kept in upper case
        :param now_ms: pygame tick count in milliseconds, the moment the line
            appeared
        """
        self.text = text.upper()
        self.shown_at = now_ms
        self.last_rect = None
        self._owned = {}
        self._pop_variants = {}

    def active(self, now_ms: int) -> bool:
        """
        Whether this bubble still belongs on screen, which the game screen asks
        every frame before drawing it

        :param now_ms: pygame tick count in milliseconds
        :returns: True while the line is inside its few seconds on screen
        """
        return self.shown_at is not None and 0 <= now_ms - self.shown_at < BUBBLE_MS

    def clear(self) -> None:
        """
        Take the bubble down at once, without the fade. A new game and a screen
        being left both do this, so no line survives into the next game
        """
        self.shown_at = None
        self.last_rect = None
        self._owned = {}
        self._pop_variants = {}

    def _anim(self, now_ms: int) -> tuple[int, int]:
        """
        Work out how the bubble should look at this moment: how far through the
        pop-in it is, in whole steps so the scaled copies can be reused, and how
        far the fade-out has taken its alpha

        :param now_ms: pygame tick count in milliseconds
        :returns: the pop step, 0 to POP_STEPS - 1, and the alpha, 0 to 255
        """
        age = now_ms - cast(int, self.shown_at)
        p = min(1.0, max(0.0, age / BUBBLE_POP_MS))
        eased = 1.0 - (1.0 - p) ** 3
        bucket = min(POP_STEPS - 1, int(eased * POP_STEPS))
        remaining = BUBBLE_MS - age
        if remaining < BUBBLE_FADE_MS:
            alpha = max(0, min(255, int(255 * remaining / BUBBLE_FADE_MS)))
        else:
            alpha = 255
        return bucket, alpha

    def _pop_variant(self, flipped: bool, bucket: int, base: pg.Surface) -> pg.Surface:
        """
        Fetch the shrunken copy of the bubble for one step of the pop-in,
        building it once. Stepping the scale rather than smoothly scaling every
        frame is what keeps the pop cheap

        :param flipped: which version of the bubble is being drawn
        :param bucket: pop step, 0 for the smallest
        :param base: the full-size bubble to shrink
        :returns: the scaled bubble for this step
        """
        key = (flipped, bucket)
        surf = self._pop_variants.get(key)
        if surf is None:
            pop = POP_START + (1.0 - POP_START) * (bucket / (POP_STEPS - 1))
            w, h = base.get_size()
            surf = pg.transform.smoothscale(
                base, (max(1, int(w * pop)), max(1, int(h * pop))))
            self._pop_variants[key] = surf
        return surf

    def _owned_surface(self, flipped: bool, base: pg.Surface) -> pg.Surface:
        """
        Get this bubble's private copy of the shared surface, made once and kept
        for the rest of the line's life. The fade sets an alpha on it, which
        must never be done to the surface the cache hands out

        :param flipped: which version of the bubble is being drawn
        :param base: the shared bubble to copy
        :returns: a copy this bubble alone may alter
        """
        surf = self._owned.get(flipped)
        if surf is None:
            surf = base.copy()
            self._owned[flipped] = surf
        return surf

    def draw(self, window: pg.Surface, anchor_rect: pg.Rect, bounds_rect: pg.Rect,
             now_ms: int, scale: float = 1.0) -> None:
        """
        Draw the bubble over the piece it belongs to, popping in and fading out
        as its age says. It sits above the piece by default, flips below when
        there is no room above, and is nudged sideways to stay on the board.
        The rect it ended up on is remembered, so the screen can repaint just
        that patch

        :param window: surface to draw on
        :param anchor_rect: rect of the piece's square in window pixels
        :param bounds_rect: the board rect the bubble must stay inside
        :param now_ms: pygame tick count in milliseconds
        :param scale: UI scale factor for the text and the padding
        """
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
