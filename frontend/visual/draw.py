import math

import pygame as pg

SUPERSAMPLE = 4


def supersample(size, render, scale=SUPERSAMPLE):
    if isinstance(size, int):
        size = (size, size)
    big = pg.Surface((size[0] * scale, size[1] * scale), pg.SRCALPHA)
    render(big, scale)
    return pg.transform.smoothscale(big, size)


def infinity_surface(height, color):
    h = max(int(height), 6)
    w = int(h * 1.7)
    th = max(h * 0.2, 3.0)

    def render(surf, k):
        big_w, big_h = surf.get_size()
        cx, cy = big_w / 2, big_h / 2
        ax, ay = big_w * 0.355, big_h * 0.275
        lw = max(int(th * k), 2)
        n = 140
        pts = []
        for i in range(n):
            t = 2 * math.pi * i / n
            d = 1 + math.sin(t) ** 2
            pts.append((cx + ax * math.cos(t) / d,
                        cy + ay * math.sin(t) * math.cos(t) / d / 0.3536))
        pg.draw.lines(surf, pg.Color(color), True, pts, lw)
    return supersample((w, h), render, scale=8)


def blit_centered(surface, text, center):
    ink = text.get_bounding_rect()
    surface.blit(text, (round(center[0] - ink.centerx), round(center[1] - ink.centery)))


def rounded_rect_surface(size, radius, fill, border=None, border_width=1):
    def render(surf, k):
        r = max(int(radius * k), 1)
        pg.draw.rect(surf, pg.Color(fill), surf.get_rect(), border_radius=r)
        if border is not None:
            pg.draw.rect(surf, pg.Color(border), surf.get_rect(),
                         width=max(int(border_width * k), 1), border_radius=r)
    return supersample(size, render)
