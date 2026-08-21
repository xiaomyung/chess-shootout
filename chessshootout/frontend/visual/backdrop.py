import math
import random

import pygame as pg

from chessshootout.frontend.visual.colors import Colors


SCALE_MIN = 0.85
SCALE_MAX = 1.5
SCALE_REF_HEIGHT = 760.0
DITHER_SEED = 0x5EED

_DITHER_TILES = {}


def _dither_tiles(t: int) -> tuple[pg.Surface, pg.Surface]:
    """
    Build the pair of noise tiles the dither is stamped with: one that lifts a
    pixel by a single level, one that drops it. They come from a fixed seed,
    so the same backdrop always comes out pixel for pixel identical

    :param t: tile side in pixels
    :returns: the add tile and the subtract tile, cached per tile size
    """
    cached = _DITHER_TILES.get(t)
    if cached is not None:
        return cached
    rng = random.Random(DITHER_SEED)
    add = bytearray(t * t * 3)
    sub = bytearray(t * t * 3)
    for i in range(t * t):
        r = rng.random()
        if r < 0.25:
            add[i * 3] = add[i * 3 + 1] = add[i * 3 + 2] = 1
        elif r < 0.5:
            sub[i * 3] = sub[i * 3 + 1] = sub[i * 3 + 2] = 1
    tiles = (pg.image.frombuffer(bytes(add), (t, t), "RGB").copy(),
             pg.image.frombuffer(bytes(sub), (t, t), "RGB").copy())
    _DITHER_TILES[t] = tiles
    return tiles


def dither(surf: pg.Surface, t: int = 128) -> pg.Surface:
    """
    Rough a smooth gradient up by one level of noise, which is what stops the
    arena backdrop from showing banding rings on a large display. The surface
    is changed in place and handed straight back

    :param surf: surface to dither, modified in place
    :param t: side of the noise tile stamped across it, in pixels
    :returns: that same surface, so the call can be chained
    """
    w, h = surf.get_size()
    add, sub = _dither_tiles(t)
    for x in range(0, w, t):
        for y in range(0, h, t):
            surf.blit(add, (x, y), special_flags=pg.BLEND_RGB_ADD)
            surf.blit(sub, (x, y), special_flags=pg.BLEND_RGB_SUB)
    return surf


def radial_gradient(n: int, cx: float, cy: float, rx: float, ry: float,
                    c0: str, c1: str, c2: str) -> pg.Surface:
    """
    Paint the small square gradient the arena backdrop is stretched from: a
    bright core easing through a mid tone into a dark edge. It is drawn small
    and scaled up afterwards, because filling a window-sized surface pixel by
    pixel would be far too slow to do on a resize

    :param n: side of the square in pixels, before it is scaled up
    :param cx: horizontal center, as a fraction of the square
    :param cy: vertical center, as a fraction of the square
    :param rx: horizontal radius, as a fraction of the square
    :param ry: vertical radius, as a fraction of the square
    :param c0: color at the center
    :param c1: mid color, reached at six tenths of the radius
    :param c2: color at the outer edge
    :returns: the gradient surface, n pixels square
    """
    surf = pg.Surface((n, n))
    col0, col1, col2 = pg.Color(c0), pg.Color(c1), pg.Color(c2)
    for yy in range(n):
        fy = (yy / (n - 1) - cy) / ry
        for xx in range(n):
            fx = (xx / (n - 1) - cx) / rx
            d = min(1.0, math.hypot(fx, fy))
            if d < 0.6:
                surf.set_at((xx, yy), col0.lerp(col1, d / 0.6))
            else:
                surf.set_at((xx, yy), col1.lerp(col2, (d - 0.6) / 0.4))
    return surf


def grid_step(h: int) -> int:
    """
    Pick how far apart the backdrop's grid lines sit for a given window
    height, so the arena reads at the same density in a small window as in a
    maximised one

    :param h: window height in pixels
    :returns: spacing between grid lines, in pixels
    """
    scale = max(SCALE_MIN, min(SCALE_MAX, h / SCALE_REF_HEIGHT))
    return max(int(64 * scale), 32)


def arena_background(size: tuple[int, int], center: tuple[float, float] = (0.5, 0.18),
                     grid: int | None = None) -> pg.Surface:
    """
    Build the arena the game is played in front of: a radial glow centered on
    wherever the board sits, a faint grid across it, an accent wash along the
    floor and a dither pass to kill banding. The menu battle and the
    focus-mode transition paint theirs from this same function, so every
    screen shares one arena look

    :param size: window width and height in pixels
    :param center: glow center as fractions of the window, x then y
    :param grid: grid spacing in pixels, or None to scale it to the height
    :returns: the finished backdrop surface
    """
    w, h = size
    grad = radial_gradient(128, center[0], center[1], 1.2, 0.8,
                           Colors.battle_bg_hi, Colors.battle_bg, Colors.battle_bg_edge)
    surf = pg.transform.smoothscale(grad, size)
    step = grid if grid is not None else grid_step(h)
    grid = pg.Surface(size, pg.SRCALPHA)
    line = (*pg.Color(Colors.battle_grid)[:3], 6)
    for gx in range(0, w, step):
        pg.draw.line(grid, line, (gx, 0), (gx, h))
    for gy in range(0, h, step):
        pg.draw.line(grid, line, (0, gy), (w, gy))
    surf.blit(grid, (0, 0))
    floor_h = int(h * 0.38)
    floor = pg.Surface((w, floor_h), pg.SRCALPHA)
    fr, fg, fb = pg.Color(Colors.accent)[:3]
    for row in range(floor_h):
        a = int(13 * row / floor_h)
        pg.draw.line(floor, (fr, fg, fb, a), (0, row), (w, row))
    surf.blit(floor, (0, h - floor_h))
    return dither(surf)


class ArenaBackdrop:
    """
    The arena backdrop as a screen owns it: the painted surface is kept and
    only rebuilt when the window size or the board's position changes, which
    keeps a per-pixel gradient off the frame budget. The game screen and the
    review screen each hold one
    """

    def __init__(self) -> None:
        """
        Start with nothing cached; the first draw paints the arena
        """
        self._cache = None

    def draw(self, window: pg.Surface, board_rect: pg.Rect) -> None:
        """
        Paint the arena behind the board, repainting only when the window size
        or the board's center has actually moved -- on a resize, on entering
        focus mode, or when the side panel changes the board's place

        :param window: surface drawn to, normally the app window
        :param board_rect: the board's box; its center is where the glow goes
        """
        size = window.get_size()
        w, h = size
        if w <= 0 or h <= 0:
            return
        center = board_rect.center
        key = (size, center)
        if self._cache is None or self._cache[0] != key:
            surface = arena_background(size, (center[0] / w, center[1] / h))
            self._cache = (key, surface.convert())
        window.blit(self._cache[1], (0, 0))
