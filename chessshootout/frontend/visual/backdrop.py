import math
import random

import pygame as pg

from chessshootout.frontend.visual.colors import Colors


SCALE_MIN = 0.85
SCALE_MAX = 1.5
SCALE_REF_HEIGHT = 760.0

_DITHER_TILES = {}


def _dither_tiles(t):
    cached = _DITHER_TILES.get(t)
    if cached is not None:
        return cached
    rng = random.Random(0x5EED)
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


def dither(surf, t=128):
    w, h = surf.get_size()
    add, sub = _dither_tiles(t)
    for x in range(0, w, t):
        for y in range(0, h, t):
            surf.blit(add, (x, y), special_flags=pg.BLEND_RGB_ADD)
            surf.blit(sub, (x, y), special_flags=pg.BLEND_RGB_SUB)
    return surf


def radial_gradient(n, cx, cy, rx, ry, c0, c1, c2):
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


def grid_step(h):
    scale = max(SCALE_MIN, min(SCALE_MAX, h / SCALE_REF_HEIGHT))
    return max(int(64 * scale), 32)


def arena_background(size, center=(0.5, 0.18)):
    w, h = size
    grad = radial_gradient(128, center[0], center[1], 1.2, 0.8,
                           Colors.battle_bg_hi, Colors.battle_bg, Colors.battle_bg_edge)
    surf = pg.transform.smoothscale(grad, size)
    step = grid_step(h)
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

    def __init__(self):
        self._cache = None

    def draw(self, window, board_rect):
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
