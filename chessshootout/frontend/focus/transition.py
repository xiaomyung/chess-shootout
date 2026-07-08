import pygame as pg

from chessshootout.frontend.visual import backdrop
from chessshootout.frontend.visual import gunfx

FOCUS_TRANSITION_MS = 230.0


def _lerp_rect(a, b, t):
    return pg.Rect(
        round(a.x + (b.x - a.x) * t),
        round(a.y + (b.y - a.y) * t),
        round(a.width + (b.width - a.width) * t),
        round(a.height + (b.height - a.height) * t),
    )


def _grab(window, rect):
    clip = rect.clip(window.get_rect())
    if clip.width <= 0 or clip.height <= 0:
        return pg.Surface((1, 1))
    return window.subsurface(clip).copy()


class _Elem:

    def __init__(self, snap, r0, r1, a0=255, a1=255):
        self.snap = snap
        self.r0 = r0
        self.r1 = r1
        self.a0 = a0
        self.a1 = a1

    def draw(self, window, e):
        r = _lerp_rect(self.r0, self.r1, e)
        if r.width < 1 or r.height < 1:
            return
        a = int(self.a0 + (self.a1 - self.a0) * e)
        if a <= 0:
            return
        surf = pg.transform.smoothscale(self.snap, r.size)
        if a < 255:
            surf.set_alpha(a)
        window.blit(surf, r.topleft)


class FocusTransition:

    def __init__(self, frontend):
        self.frontend = frontend
        self.collapsing = True
        self.start_ms = 0
        self.elems = []
        self.bg = None
        self.cur_e = 0.0
        self.cur_board_rect = None

    def begin_collapse(self, show):
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
                               norm_top.move(0, -norm_top.height - 4), 255, 0))
            elems.append(_Elem(norm_bot_snap, norm_bot,
                               norm_bot.move(0, norm_bot.height + 4), 255, 0))
        elems.append(_Elem(panel_snap, panel_home,
                           panel_home.move(panel_home.width, 0), 255, 0))
        self.elems = elems
        self._build_bg(window, focus_board)

    def begin_expand(self, show):
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
        f._draw_game_children()
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
                               norm_top.move(0, -norm_top.height - 4), norm_top, 0, 255))
            elems.append(_Elem(_grab(window, norm_bot),
                               norm_bot.move(0, norm_bot.height + 4), norm_bot, 0, 255))
        elems.append(_Elem(panel_snap, panel_home.move(panel_home.width, 0),
                           panel_home, 0, 255))
        self.elems = elems
        self._build_bg(window, normal_board)

    def _build_bg(self, window, dest_board):
        w, h = window.get_size()
        center = (dest_board.centerx / w, dest_board.centery / h)
        self.bg = backdrop.arena_background((w, h), center).convert()

    def is_active(self):
        return True

    def done(self, now):
        return now - self.start_ms >= FOCUS_TRANSITION_MS

    def cancel(self):
        self.elems = []
        self.bg = None

    def draw(self, now):
        window = self.frontend.window
        q = min(max((now - self.start_ms) / FOCUS_TRANSITION_MS, 0.0), 1.0)
        e = gunfx.smoothstep(q)
        self.cur_e = e
        if self.bg is not None:
            window.blit(self.bg, (0, 0))
        for el in self.elems:
            el.draw(window, e)
        if self.elems:
            self.cur_board_rect = _lerp_rect(self.elems[0].r0, self.elems[0].r1, e)
