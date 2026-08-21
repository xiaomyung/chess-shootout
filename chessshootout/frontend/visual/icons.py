import math
import os
from collections.abc import Callable
from typing import Any

import pygame as pg

from chessshootout.backend.pieces import Piece
from chessshootout.paths import PIECES_PNG_DIR
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample

_ICON_CACHE = new_cache()

ICON_GRID = 24.0
ICON_SUPERSAMPLE = 6

_ICON_FOOTPRINT_MEDIUM = 0.82
_ICON_FOOTPRINT_LARGE = 0.86
_ICON_STROKE_FACTOR = 1.7
_ICON_STROKE_FACTOR_THIN = 1.6
_ICON_STROKE_FACTOR_BOLD = 2.2


def _blit_icon(window: pg.Surface, rect: pg.Rect, side: int, key: tuple[Any, ...],
               build: Callable[[], pg.Surface]) -> None:
    """
    Put a finished icon in the middle of the box it was asked for, drawing it
    only the first time that exact icon and size is needed. Every icon here
    ends with this call, which is why icons cost nothing after the first frame

    :param window: surface to draw onto
    :param rect: box the icon is centred in, in window pixels
    :param side: icon edge length in pixels, already fitted to the box
    :param key: cache identity -- name, size and every look-bearing argument
    :param build: draws the icon on a miss
    """
    window.blit(memoized_surface(_ICON_CACHE, key, build),
                (rect.centerx - side // 2, rect.centery - side // 2))


def piece_png_path(piece: Piece) -> str:
    """
    Name the artwork file for a chess piece. The board and the history view
    load their sprites through here, so the twelve piece pictures are addressed
    the same way everywhere

    :param piece: the piece whose art is wanted, type and colour both used
    :returns: absolute path to that piece's PNG
    """
    return os.path.join(PIECES_PNG_DIR, f"{piece.type.value}_{piece.color.value}.png")


_FOLDER_BODY = [(3, 7.5), (3.6, 6.4), (8.6, 6.4), (10.6, 8.2),
                (20.4, 8.2), (21, 9.2), (21, 17.6), (3, 17.6)]
_FILE_BODY = [(6, 4), (13.5, 4), (18, 8.5), (18, 20), (6, 20)]
_FILE_FOLD = [(13.5, 4), (13.5, 8.5), (18, 8.5)]


def _icon_side(rect: pg.Rect, fraction: float = 0.74) -> int:
    """
    Decide how big an icon may be inside the box it was given, leaving air
    around it. Icons are square, so the shorter side of the box wins

    :param rect: box the icon has to fit in
    :param fraction: share of that box the artwork may occupy
    :returns: icon edge length in pixels
    """
    return int(min(rect.width, rect.height) * fraction)


def draw_folder(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The folder mark on every directory row of the file browser, the one the
    player picks a save folder with. Too small a box is skipped rather than
    drawn as a smudge

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: fill colour as a hex token from Colors
    """
    side = _icon_side(rect)
    if side < 4:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Lay the folder outline onto the oversized canvas, in design units

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _FOLDER_BODY])

    _blit_icon(window, rect, side, ("folder", side, str(color)),
               lambda: supersample(side, render))


def draw_file(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The page mark shown for a plain file in the browser, and on the Open PGN
    cap in review. Its turned-down corner is drawn in a darker tint of the
    same colour so the shape reads at rail size

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: fill colour as a hex token from Colors
    """
    side = _icon_side(rect)
    if side < 4:
        return
    col = pg.Color(color)
    fold = col.lerp(pg.Color(Colors.bg), 0.55)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Lay the page and its folded corner onto the oversized canvas

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _FILE_BODY])
        pg.draw.polygon(surf, fold, [(x * u, y * u) for x, y in _FILE_FOLD])

    _blit_icon(window, rect, side, ("file", side, str(color)),
               lambda: supersample(side, render))


_FOLDER_OUTLINE = [(3.5, 8), (3.5, 7), (4.4, 6.2), (8.6, 6.2), (10.6, 8.2),
                   (20, 8.2), (20.5, 9), (20.5, 18), (3.5, 18)]


def _stroke(surf: pg.Surface, col: pg.Color, pts: list[tuple[float, float]],
            closed: bool, lw: int) -> None:
    """
    Draw an outline the way the icon set wants it: a polyline with a dot at
    every corner, which rounds the joints that pygame would otherwise leave
    notched at thick stroke widths

    :param surf: canvas being drawn on
    :param col: stroke colour
    :param pts: outline points in canvas pixels
    :param closed: whether the last point joins back to the first
    :param lw: stroke width in canvas pixels
    """
    pg.draw.lines(surf, col, closed, pts, lw)
    r = max(lw // 2, 1)
    for px, py in pts:
        pg.draw.circle(surf, col, (int(px), int(py)), r)


def draw_folder_plus(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The new-folder tool in the file browser, an outlined folder with a plus
    inside it. Outlined icons need more room than solid ones, so this one
    claims a larger share of its box

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_LARGE)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Stroke the folder outline and cross the plus inside it

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR * u), 2)
        _stroke(surf, col, [(x * u, y * u) for x, y in _FOLDER_OUTLINE], True, lw)
        pg.draw.line(surf, col, (12 * u, 11 * u), (12 * u, 16 * u), lw)
        pg.draw.line(surf, col, (9.5 * u, 13.5 * u), (14.5 * u, 13.5 * u), lw)

    _blit_icon(window, rect, side, ("folder_plus", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


def draw_eye(window: pg.Surface, rect: pg.Rect, color: str, off: bool = False) -> None:
    """
    The show-hidden-files tool in the file browser. The struck-through form is
    a separate cache entry, so toggling the tool swaps between two ready icons

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    :param off: draw the eye with a slash through it
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_LARGE)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Sweep the two lids as sine arcs, drop the pupil in and add the slash

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR * u), 2)
        x0, x1, cy, amp, n = 3 * u, 21 * u, 12 * u, 4.7 * u, 24
        top = [(x0 + (x1 - x0) * i / n, cy - amp * math.sin(math.pi * i / n))
               for i in range(n + 1)]
        bot = [(x0 + (x1 - x0) * i / n, cy + amp * math.sin(math.pi * i / n))
               for i in range(n + 1)]
        pg.draw.lines(surf, col, False, top, lw)
        pg.draw.lines(surf, col, False, bot, lw)
        pg.draw.circle(surf, col, (int(12 * u), int(cy)), int(2.5 * u))
        if off:
            pg.draw.line(surf, col, (3.5 * u, 4.5 * u), (20.5 * u, 19.5 * u), lw)

    _blit_icon(window, rect, side, ("eye", side, str(color), off),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


_PLAY_TRIANGLE = [(8, 5), (8, 19), (19, 12)]


def draw_play(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The play triangle on the Play row of the menu's Command Rail, the row that
    holds the whole match setup

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: fill colour as a hex token from Colors
    """
    side = _icon_side(rect)
    if side < 4:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Fill the triangle on the oversized canvas

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _PLAY_TRIANGLE])

    _blit_icon(window, rect, side, ("play", side, str(color)),
               lambda: supersample(side, render))


def draw_clock(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The clock face used for the History row of the rail and for the time
    control chip on the Play view, where it labels the chosen time

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Ring the dial and set the two hands

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR * u), 2)
        cx, cy, r = 12 * u, 12.5 * u, 8 * u
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r), width=lw)
        pg.draw.line(surf, col, (cx, cy), (cx, cy - r * 0.62), lw)
        pg.draw.line(surf, col, (cx, cy), (cx + r * 0.48, cy + r * 0.24), lw)

    _blit_icon(window, rect, side, ("clock", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


_MEDAL_RIBBON_L = [(9, 15), (9, 21), (12, 18.5)]
_MEDAL_RIBBON_R = [(15, 15), (15, 21), (12, 18.5)]


def draw_medal(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The medal on the Battle Pass row of the rail

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Ring the medal, set its diamond and hang the two ribbon tails

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR_THIN * u), 2)
        cx, cy, r = 12 * u, 9.5 * u, 6 * u
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r), width=lw)
        pg.draw.polygon(surf, col, [
            (cx, cy - r * 0.5), (cx + r * 0.5, cy), (cx, cy + r * 0.5), (cx - r * 0.5, cy)])
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _MEDAL_RIBBON_L])
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _MEDAL_RIBBON_R])

    _blit_icon(window, rect, side, ("medal", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


_SHIELD_BODY = [(5, 4), (19, 4), (19, 11.5), (12, 21), (5, 11.5)]


def draw_shield(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The shield on the Armory row of the rail

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Stroke the shield outline and its centre rib

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR * u), 2)
        _stroke(surf, col, [(x * u, y * u) for x, y in _SHIELD_BODY], True, lw)
        pg.draw.line(surf, col, (12 * u, 7 * u), (12 * u, 15 * u), lw)

    _blit_icon(window, rect, side, ("shield", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


def draw_people(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The two figures on the Social row of the rail

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Ring each head and arc the shoulders below it, the smaller figure
        behind the larger one

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR_THIN * u), 2)
        pg.draw.circle(surf, col, (int(8 * u), int(8.5 * u)), int(2.6 * u), width=lw)
        pg.draw.arc(surf, col, pg.Rect(2 * u, 11 * u, 12 * u, 11 * u), 0.15,
                    math.pi - 0.15, lw)
        pg.draw.circle(surf, col, (int(15.5 * u), int(9.5 * u)), int(3.2 * u), width=lw)
        pg.draw.arc(surf, col, pg.Rect(8.5 * u, 12.3 * u, 14 * u, 12 * u), 0.1,
                    math.pi - 0.1, lw)

    _blit_icon(window, rect, side, ("people", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


def draw_gear(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The cog on the Options row of the rail, the row pinned at the foot of the
    nav list

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: fill colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_LARGE)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Spoke eight tapered teeth around the hub, then punch the centre hole

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        cx, cy = 12 * u, 12 * u
        r0, r1 = 5.2 * u, 8.4 * u
        hw_base, hw_tip = 1.9 * u, 1.0 * u
        teeth = 8
        for i in range(teeth):
            a = math.tau * i / teeth
            dx, dy = math.cos(a), math.sin(a)
            px, py = -dy, dx
            pg.draw.polygon(surf, col, [
                (cx + dx * r0 + px * hw_base, cy + dy * r0 + py * hw_base),
                (cx + dx * r0 - px * hw_base, cy + dy * r0 - py * hw_base),
                (cx + dx * r1 - px * hw_tip, cy + dy * r1 - py * hw_tip),
                (cx + dx * r1 + px * hw_tip, cy + dy * r1 + py * hw_tip),
            ])
        hole_r = 2.1 * u
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r0), width=int(r0 - hole_r))

    _blit_icon(window, rect, side, ("gear", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


def draw_reticle(window: pg.Surface, rect: pg.Rect, color: str, alpha: int = 255) -> None:
    """
    The gunsight that marks which rail row is selected, slid onto the active
    row and breathing on a pulse. Fading is done on the shared cached surface
    rather than by caching one entry per alpha step

    :param window: surface to draw onto
    :param rect: box the reticle is centred in
    :param color: stroke colour as a hex token from Colors
    :param alpha: opacity from 0 to 255, clamped into that range
    """
    side = _icon_side(rect, 0.9)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Ring the sight, put a tick outside it on each axis and dot the centre

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        cx, cy = 12 * u, 12 * u
        r = 7 * u
        lw = max(int(_ICON_STROKE_FACTOR_THIN * u), 2)
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r), width=lw)
        tick, gap = 3.2 * u, 1.6 * u
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            x0, y0 = cx + dx * (r + gap), cy + dy * (r + gap)
            x1, y1 = cx + dx * (r + gap + tick), cy + dy * (r + gap + tick)
            pg.draw.line(surf, col, (x0, y0), (x1, y1), lw)
        pg.draw.circle(surf, col, (int(cx), int(cy)), max(int(1.6 * u), 2))

    surf = memoized_surface(_ICON_CACHE, ("reticle", side, str(color)),
                             lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))
    surf.set_alpha(max(0, min(255, int(alpha))))
    window.blit(surf, (rect.centerx - side // 2, rect.centery - side // 2))


def draw_undo_arrow(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The looping arrow on the Undo cap in the game rail, the button that asks
    to take a move back

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Sweep the arc most of the way round, cap its tail and point its head

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR_BOLD * u), 2)
        cx, cy, r = 12 * u, 12 * u, 7.4 * u
        head, sweep, n = math.radians(96), math.radians(268), 44
        start = head - sweep
        pts = [(cx + r * math.cos(start + sweep * i / n),
                cy - r * math.sin(start + sweep * i / n)) for i in range(n + 1)]
        pg.draw.lines(surf, col, False, pts, lw)
        pg.draw.circle(surf, col, (int(pts[0][0]), int(pts[0][1])), max(lw // 2, 1))
        hx, hy = pts[-1]
        fx, fy = -math.sin(head), -math.cos(head)
        px, py = -fy, fx
        hl, hw = 4.6 * u, 3.2 * u
        pg.draw.polygon(surf, col, [
            (hx + fx * hl, hy + fy * hl),
            (hx - fx * hl * 0.28 + px * hw, hy - fy * hl * 0.28 + py * hw),
            (hx - fx * hl * 0.28 - px * hw, hy - fy * hl * 0.28 - py * hw)])

    _blit_icon(window, rect, side, ("undo_arrow", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


_RESIGN_FLAG = [(8.2, 4.2), (18.8, 5.2), (16.2, 8.0), (18.8, 10.8), (8.2, 11.8)]
_RESIGN_POLE_X = 7.2
_RESIGN_BASE = ((4.6, 20.6), (9.8, 20.6))


def draw_resign_flag(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The white flag on the Resign cap in the game rail, the button that gives
    the game up

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: fill colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Stand the pole on its foot and hang the swallow-tailed flag off it

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        pole = max(int(2.0 * u), 2)
        px = _RESIGN_POLE_X
        pg.draw.line(surf, col, (px * u, 3.2 * u), (px * u, 20.6 * u), pole)
        (bx1, by), (bx2, _) = _RESIGN_BASE
        pg.draw.line(surf, col, (bx1 * u, by * u), (bx2 * u, by * u), pole)
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _RESIGN_FLAG])

    _blit_icon(window, rect, side, ("resign_flag", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


def draw_flip_arrows(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The opposed arrows on the Flip cap, which turns the board round so the
    other colour is at the bottom

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Draw the two shafts side by side, one headed up and one headed down

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR_BOLD * u), 2)
        pg.draw.line(surf, col, (9 * u, 5 * u), (9 * u, 19 * u), lw)
        pg.draw.lines(surf, col, False,
                      [(6.5 * u, 8 * u), (9 * u, 5 * u), (11.5 * u, 8 * u)], lw)
        pg.draw.line(surf, col, (15 * u, 5 * u), (15 * u, 19 * u), lw)
        pg.draw.lines(surf, col, False,
                      [(12.5 * u, 16 * u), (15 * u, 19 * u), (17.5 * u, 16 * u)], lw)

    _blit_icon(window, rect, side, ("flip_arrows", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))


def draw_left_arrow(window: pg.Surface, rect: pg.Rect, color: str) -> None:
    """
    The back arrow on the Menu cap of the review rail, the way out of a
    reviewed game

    :param window: surface to draw onto
    :param rect: box the icon is centred in
    :param color: stroke colour as a hex token from Colors
    """
    side = _icon_side(rect, _ICON_FOOTPRINT_MEDIUM)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf: pg.Surface, k: int) -> None:
        """
        Draw the shaft and its arrowhead pointing left

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the icon
        """
        u = side * k / ICON_GRID
        lw = max(int(_ICON_STROKE_FACTOR_BOLD * u), 2)
        pg.draw.line(surf, col, (5.5 * u, 12 * u), (18.5 * u, 12 * u), lw)
        pg.draw.lines(surf, col, False,
                      [(10.5 * u, 7 * u), (5.5 * u, 12 * u), (10.5 * u, 17 * u)], lw)

    _blit_icon(window, rect, side, ("left_arrow", side, str(color)),
               lambda: supersample(side, render, scale=ICON_SUPERSAMPLE))
