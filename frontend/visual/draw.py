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
    th = max(int(h * 0.16), 2)

    def render(surf, k):
        big_w, big_h = surf.get_size()
        r = int(big_h * 0.38)
        cy = big_h // 2
        for cx in (int(big_w * 0.30), int(big_w * 0.70)):
            pg.draw.circle(surf, pg.Color(color), (cx, cy), r, max(int(th * k), 1))
    return supersample((w, h), render)


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
