import math

import pygame as pg

from chessshootout.frontend.visual.colors import Colors


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
    scale = max(0.85, min(1.5, h / 760.0))
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
    return surf
