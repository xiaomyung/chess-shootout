from typing import Any

import pygame as pg

from chessshootout.frontend.visual import backdrop
from chessshootout.frontend.visual.draw import smoothstep

FOCUS_TRANSITION_MS = 230.0
STRIP_SLIDE_CLEAR_PX = 4


def _lerp_rect(a: pg.Rect, b: pg.Rect, t: float) -> pg.Rect:
    """
    Blend two rects, which is how a snapshot travels and grows from where it
    started to where it is going

    :param a: rect at the start of the transition
    :param b: rect at the end of it
    :param t: eased progress from 0 to 1
    :returns: the rect at that point of the journey
    """
    return pg.Rect(
        round(a.x + (b.x - a.x) * t),
        round(a.y + (b.y - a.y) * t),
        round(a.width + (b.width - a.width) * t),
        round(a.height + (b.height - a.height) * t),
    )


def _grab(window: pg.Surface, rect: pg.Rect) -> pg.Surface:
    """
    Take a photograph of one part of the window, the trick the whole transition
    rests on: widgets are drawn once, then only their pictures are moved around.
    A rect with nothing on screen gives a harmless single pixel

    :param window: the live window surface
    :param rect: region to copy, which may hang off the window
    :returns: a private copy of those pixels
    """
    clip = rect.clip(window.get_rect())
    if clip.width <= 0 or clip.height <= 0:
        return pg.Surface((1, 1))
    return window.subsurface(clip).copy()


class _Elem:
    """
    One photographed widget on its way across the screen: where it starts,
    where it ends and how its opacity changes on the way. The transition is
    just a handful of these drawn in order
    """

    def __init__(self, snap: pg.Surface, r0: pg.Rect, r1: pg.Rect,
                 a0: int = 255, a1: int = 255) -> None:
        """
        Describe one element's journey. Equal start and end rects mean it only
        fades, which is how strips cross-fade in the strips mode

        :param snap: the photographed pixels
        :param r0: rect it starts at, in window pixels
        :param r1: rect it ends at
        :param a0: opacity it starts at, 0 to 255
        :param a1: opacity it ends at
        """
        self.snap = snap
        self.r0 = r0
        self.r1 = r1
        self.a0 = a0
        self.a1 = a1

    def draw(self, window: pg.Surface, e: float) -> None:
        """
        Draw this element at one point of the transition, scaled to the rect it
        has reached and faded to the opacity it has reached. Anything that has
        shrunk to nothing or faded out is skipped

        :param window: surface to draw on
        :param e: eased progress from 0 to 1
        """
        r = _lerp_rect(self.r0, self.r1, e)
        if r.width < 1 or r.height < 1:
            return
        a = int(self.a0 + (self.a1 - self.a0) * e)
        if a <= 0:
            return
        if r.size == self.snap.get_size():
            surf = self.snap
        else:
            surf = pg.transform.smoothscale(self.snap, r.size)
        surf.set_alpha(a if a < 255 else None)
        window.blit(surf, r.topleft)


class FocusTransition:
    """
    The animation that collapses the game down to the bare board and expands it
    back. It photographs the widgets in both layouts, then slides and fades
    those pictures between the two, which is why the real widgets can be
    relaid out the instant the transition begins
    """

    def __init__(self, frontend: Any) -> None:
        """
        Bind a transition to the game screen playing it. One is built per
        toggle and thrown away when it finishes, so its state describes exactly
        one collapse or expansion

        :param frontend: the GameScreen running this transition, read for the
            board, the strips, the rail and the window
        """
        self.frontend = frontend
        self.collapsing = True
        self.start_ms = 0
        self.elems: list[_Elem] = []
        self.bg: pg.Surface | None = None
        self.cur_e = 0.0
        self.cur_board_rect: pg.Rect | None = None

    def begin_collapse(self, show: str) -> None:
        """
        Set up the way into focus mode: photograph the full view, switch the
        screen to the focus layout and photograph that too, then line up the
        journeys -- the board grows into the middle, the rail slides off to the
        right, and the strips either cross-fade into their focus places or
        slide out past the top and bottom edges

        :param show: what focus mode keeps on screen, "line", "strips" or
            "nothing", from the CHESS_FOCUS_SHOW setting
        """
        f = self.frontend
        window = f.window
        self.collapsing = True
        self.start_ms = pg.time.get_ticks()
        normal_board = pg.Rect(f.board.rect)
        norm_top = pg.Rect(f.player_strip_top.rect)
        norm_bot = pg.Rect(f.player_strip_bottom.rect)
        panel_home = pg.Rect(f.right_menu.outer_rect)
        panel_snap = _grab(window, panel_home)
        norm_top_snap = _grab(window, norm_top)
        norm_bot_snap = _grab(window, norm_bot)
        f.focus_mode = True
        f._compute_layout()
        focus_board = pg.Rect(f.board.rect)
        f.board.draw_board()
        board_snap = _grab(window, focus_board)
        elems = [_Elem(board_snap, normal_board, focus_board)]
        if show == "strips":
            f.player_strip_top.draw()
            f.player_strip_bottom.draw()
            focus_top = pg.Rect(f.player_strip_top.rect)
            focus_bot = pg.Rect(f.player_strip_bottom.rect)
            elems.append(_Elem(norm_top_snap, norm_top, norm_top, 255, 0))
            elems.append(_Elem(norm_bot_snap, norm_bot, norm_bot, 255, 0))
            elems.append(_Elem(_grab(window, focus_top), focus_top, focus_top, 0, 255))
            elems.append(_Elem(_grab(window, focus_bot), focus_bot, focus_bot, 0, 255))
        else:
            elems.append(_Elem(norm_top_snap, norm_top,
                               norm_top.move(0, -norm_top.height - STRIP_SLIDE_CLEAR_PX), 255, 0))
            elems.append(_Elem(norm_bot_snap, norm_bot,
                               norm_bot.move(0, norm_bot.height + STRIP_SLIDE_CLEAR_PX), 255, 0))
        elems.append(_Elem(panel_snap, panel_home,
                           panel_home.move(panel_home.width, 0), 255, 0))
        self.elems = elems
        self._build_bg(window, focus_board)

    def begin_expand(self, show: str) -> None:
        """
        Set up the way back out of focus mode: photograph the bare board,
        switch the screen to the full layout and draw the whole scene so it can
        be photographed too, then run every journey of the collapse backwards

        :param show: what focus mode was keeping on screen, "line", "strips" or
            "nothing", which decides how the strips come back
        """
        f = self.frontend
        window = f.window
        self.collapsing = False
        self.start_ms = pg.time.get_ticks()
        focus_board = pg.Rect(f.board.rect)
        f.board.draw_board()
        board_snap = _grab(window, focus_board)
        focus_top = pg.Rect(f.player_strip_top.rect)
        focus_bot = pg.Rect(f.player_strip_bottom.rect)
        focus_top_snap = _grab(window, focus_top)
        focus_bot_snap = _grab(window, focus_bot)
        f.focus_mode = False
        f._compute_layout()
        normal_board = pg.Rect(f.board.rect)
        f._draw_game_scene(show_panel=True, show_strips=True)
        norm_top = pg.Rect(f.player_strip_top.rect)
        norm_bot = pg.Rect(f.player_strip_bottom.rect)
        panel_home = pg.Rect(f.right_menu.outer_rect)
        panel_snap = _grab(window, panel_home)
        elems = [_Elem(board_snap, focus_board, normal_board)]
        if show == "strips":
            elems.append(_Elem(focus_top_snap, focus_top, focus_top, 255, 0))
            elems.append(_Elem(focus_bot_snap, focus_bot, focus_bot, 255, 0))
            elems.append(_Elem(_grab(window, norm_top), norm_top, norm_top, 0, 255))
            elems.append(_Elem(_grab(window, norm_bot), norm_bot, norm_bot, 0, 255))
        else:
            elems.append(_Elem(_grab(window, norm_top),
                               norm_top.move(0, -norm_top.height - STRIP_SLIDE_CLEAR_PX), norm_top,
                               0, 255))
            elems.append(_Elem(_grab(window, norm_bot),
                               norm_bot.move(0, norm_bot.height + STRIP_SLIDE_CLEAR_PX), norm_bot,
                               0, 255))
        elems.append(_Elem(panel_snap, panel_home.move(panel_home.width, 0),
                           panel_home, 0, 255))
        self.elems = elems
        self._build_bg(window, normal_board)

    def _build_bg(self, window: pg.Surface, dest_board: pg.Rect) -> None:
        """
        Build the arena backdrop the moving pictures are drawn over, lit around
        where the board is going to end up. Painting it fresh each frame is what
        stops the widgets leaving trails behind them

        :param window: the window, read only for its size
        :param dest_board: board rect at the end of the transition, which
            centres the backdrop's glow
        """
        w, h = window.get_size()
        center = (dest_board.centerx / w, dest_board.centery / h)
        self.bg = backdrop.arena_background((w, h), center).convert()

    def done(self, now: int) -> bool:
        """
        Whether the transition has run its course, which the game screen asks
        every frame so it can drop it and hand the window back to the real
        widgets

        :param now: pygame tick count in milliseconds
        :returns: True once the animation is over
        """
        return now - self.start_ms >= FOCUS_TRANSITION_MS

    def cancel(self) -> None:
        """
        Throw the photographs away, leaving the transition drawing nothing. A
        window resize invalidates every snapshot at once, so the transition is
        abandoned rather than finished
        """
        self.elems = []
        self.bg = None

    def draw(self, now: int) -> None:
        """
        Draw one frame of the transition: the backdrop, then every element at
        its eased position. Where the board has got to is remembered, so the
        focus-mode clock bars can be drawn against the moving board

        :param now: pygame tick count in milliseconds
        """
        window = self.frontend.window
        q = min(max((now - self.start_ms) / FOCUS_TRANSITION_MS, 0.0), 1.0)
        e = smoothstep(q)
        self.cur_e = e
        if self.bg is not None:
            window.blit(self.bg, (0, 0))
        for el in self.elems:
            el.draw(window, e)
        if self.elems:
            self.cur_board_rect = _lerp_rect(self.elems[0].r0, self.elems[0].r1, e)
