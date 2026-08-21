import math

import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import smoothstep

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
    """
    The little round arrow that collapses the game down to the board and brings
    it back, the mouse-driven way in and out of focus mode next to the H
    hotkey. It slides in when it is wanted, bobs gently, grows under the cursor
    and points whichever way it would take the player
    """

    def __init__(self) -> None:
        """
        Start hidden and off the board, with the slide and hover animations
        parked long ago so neither is mid-flight on the first frame. The game
        screen owns one arrow for the whole game
        """
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

    def reset(self) -> None:
        """
        Take the arrow off screen at once, with no slide. Toggling focus mode
        and leaving the game both do this, so the arrow never animates out of a
        layout that has already gone
        """
        self._shown = False
        self._hovering = False
        self._visible = False
        self._bounds = pg.Rect(0, 0, 0, 0)
        self._prev_bounds = pg.Rect(0, 0, 0, 0)

    def is_visible(self) -> bool:
        """
        Whether the arrow is on screen at all, which the game screen asks
        before it lets a click reach the arrow

        :returns: True when the arrow is drawn and has a size
        """
        return self._visible and self._bounds.width > 0

    def update(self, now: int, shown: bool, anchor: tuple[int, int] | None,
               mouse_pos: tuple[int, int] | None, focus_on: bool) -> None:
        """
        Advance the arrow one frame: slide it in or out as the caller asks,
        bob it, grow and brighten it under the cursor, and settle where its
        hitbox is. It is called once per frame from whichever of the two draw
        paths is running, so the same widget serves both views

        :param now: pygame tick count in milliseconds
        :param shown: True while the arrow is wanted on screen; a change here
            starts the slide
        :param anchor: where the arrow's centre belongs in window pixels, or
            None when there is nowhere to put it
        :param mouse_pos: cursor position in window pixels, or None when there
            is no cursor to test
        :param focus_on: True while focus mode is on, which decides which way
            the arrow points
        """
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
        hv = smoothstep((now - self._hover_start) / FOCUS_ARROW_HOVER_MS)
        hv = hv if self._hovering else 1.0 - hv
        scale = 1.0 + (FOCUS_ARROW_HOVER_SCALE - 1.0) * hv
        sized = pg.Rect(0, 0, int(FOCUS_ARROW_D * scale), int(FOCUS_ARROW_D * scale))
        sized.center = base.center
        self._bounds = sized
        alpha = FOCUS_ARROW_IDLE_ALPHA + (FOCUS_ARROW_HOVER_ALPHA - FOCUS_ARROW_IDLE_ALPHA) * hv
        self._alpha = max(0, min(255, int(alpha * prog)))

    def _slide_progress(self, now: int) -> float:
        """
        How far along the slide is, counted from the moment the arrow was last
        asked for or dismissed. It leaves more slowly than it arrives, so the
        way out stays findable for a beat

        :param now: pygame tick count in milliseconds
        :returns: 0 while fully hidden, 1 while fully out
        """
        dur = FOCUS_ARROW_REVEAL_MS if self._shown else FOCUS_ARROW_HIDE_MS
        e = smoothstep((now - self._slide_start) / dur)
        return e if self._shown else 1.0 - e

    def hit_test(self, pos: tuple[int, int]) -> bool:
        """
        Whether a point is on the arrow, with a few pixels of slop around it so
        a small target stays easy to hit

        :param pos: point in window pixels
        :returns: True when the point counts as on the arrow
        """
        return (self.is_visible()
                and self._bounds.inflate(FOCUS_ARROW_HIT_SLOP, FOCUS_ARROW_HIT_SLOP)
                .collidepoint(pos))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Answer a left click: taking it means the game screen toggles focus mode
        instead of passing the click on to the board or the rail

        :param pos: click position in window pixels
        :returns: True when the arrow was clicked
        """
        return self.hit_test(pos)

    def dirty_rect(self) -> pg.Rect:
        """
        The patch of window the arrow needs repainted this frame, covering both
        where it is now and where it was last frame, since it moves as it bobs
        and slides

        :returns: the region to present, empty when the arrow is nowhere
        """
        slop = FOCUS_ARROW_HIT_SLOP
        r = self._bounds.inflate(slop, slop) if self._bounds.width > 0 else pg.Rect(0, 0, 0, 0)
        if self._prev_bounds.width > 0:
            r = r.union(self._prev_bounds.inflate(slop, slop))
        return r

    def draw(self, window: pg.Surface) -> None:
        """
        Draw the arrow at the size and alpha the last update settled on. The
        glyph itself is cached, so the hover growth is a scale of a ready-made
        picture rather than a redraw

        :param window: surface to draw on
        """
        if not self._visible or self._bounds.width <= 0:
            return
        glyph = self._glyph(self._focus_on)
        if self._bounds.size != (FOCUS_ARROW_D, FOCUS_ARROW_D):
            glyph = pg.transform.smoothscale(glyph, self._bounds.size)
        else:
            glyph = glyph.copy()
        glyph.set_alpha(self._alpha)
        window.blit(glyph, self._bounds.topleft)

    def _glyph(self, focus_on: bool) -> pg.Surface:
        """
        Fetch the arrow picture for one direction, drawing it the first time it
        is asked for. There are only ever two, so they are kept for the life of
        the arrow

        :param focus_on: True for the leave-focus glyph, False for the enter one
        :returns: the glyph at its natural size
        """
        if focus_on not in self._glyphs:
            self._glyphs[focus_on] = self._build_glyph(focus_on)
        return self._glyphs[focus_on]

    def _build_glyph(self, focus_on: bool) -> pg.Surface:
        """
        Draw the arrow itself: a bordered disc with a triangle in it. In focus
        mode it points left, back toward the board, to say the rail is coming
        back; in the normal view it points right, to say the rail slides away.
        Drawing it oversized and scaling down is what keeps the small disc and
        its triangle smooth

        :param focus_on: True while focus mode is on, which points the triangle
            the other way
        :returns: the finished glyph at FOCUS_ARROW_D pixels across
        """
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
