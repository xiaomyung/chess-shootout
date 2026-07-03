import math

import pygame as pg

from chessshootout.frontend.visual.cache import new_cache, memoized_surface

SUPERSAMPLE = 4
GLOW_BLUR_PASSES = 3


def supersample(size, render, scale=SUPERSAMPLE):
    if isinstance(size, int):
        size = (size, size)
    big = pg.Surface((size[0] * scale, size[1] * scale), pg.SRCALPHA)
    render(big, scale)
    return pg.transform.smoothscale(big, size)


def _pyramid_blur(surface, passes):
    w, h = surface.get_size()
    factor = 1 << passes
    pw, ph = -(-w // factor) * factor, -(-h // factor) * factor
    ox, oy = (pw - w) // 2, (ph - h) // 2
    work = surface
    if (pw, ph) != (w, h):
        work = pg.Surface((pw, ph), pg.SRCALPHA)
        work.blit(surface, (ox, oy))
    for _ in range(passes):
        work = pg.transform.smoothscale(work, (work.get_width() // 2, work.get_height() // 2))
    for _ in range(passes):
        work = pg.transform.smoothscale(work, (work.get_width() * 2, work.get_height() * 2))
    if (pw, ph) != (w, h):
        return work.subsurface(pg.Rect(ox, oy, w, h)).copy()
    return work


def soft_blur(surface, passes=GLOW_BLUR_PASSES):
    if passes <= 0:
        return surface
    forward = _pyramid_blur(surface, passes)
    mirror = pg.transform.flip(
        _pyramid_blur(pg.transform.flip(surface, True, True), passes), True, True)
    forward.fill((128, 128, 128, 128), special_flags=pg.BLEND_RGBA_MULT)
    mirror.fill((128, 128, 128, 128), special_flags=pg.BLEND_RGBA_MULT)
    forward.blit(mirror, (0, 0), special_flags=pg.BLEND_RGBA_ADD)
    return forward


_INFINITY_CACHE = new_cache()


def infinity_surface(height, color):
    h = max(int(height), 6)
    w = int(h * 1.7)
    th = max(h * 0.2, 3.0)

    def build():
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
    return memoized_surface(_INFINITY_CACHE, (h, str(color)), build)


_CIRCLE_CACHE = new_cache()


def circle_surface(diameter, color):
    d = max(int(diameter), 1)

    def build():
        def render(surf, k):
            r = surf.get_width() / 2
            pg.draw.circle(surf, pg.Color(color), (r, r), r)
        return supersample(d, render)
    return memoized_surface(_CIRCLE_CACHE, (d, color), build)


def stroked_text(font, text, fill, stroke, sw):
    base = font.render(text, True, fill)
    edge = font.render(text, True, stroke)
    w, h = base.get_size()
    surf = pg.Surface((w + 2 * sw, h + 2 * sw), pg.SRCALPHA)
    for dx in range(-sw, sw + 1):
        for dy in range(-sw, sw + 1):
            if dx * dx + dy * dy <= sw * sw:
                surf.blit(edge, (sw + dx, sw + dy))
    surf.blit(base, (sw, sw))
    return surf


def blit_centered(surface, text, center):
    ink = text.get_bounding_rect()
    surface.blit(text, (round(center[0] - ink.centerx), round(center[1] - ink.centery)))


_ROUNDED_RECT_CACHE = new_cache()


def rounded_rect_surface(size, radius, fill, border=None, border_width=1):
    size_key = size if isinstance(size, int) else tuple(size)
    key = (size_key, int(radius), str(fill), None if border is None else str(border),
           border_width)

    def build():
        def render(surf, k):
            r = max(int(radius * k), 1)
            pg.draw.rect(surf, pg.Color(fill), surf.get_rect(), border_radius=r)
            if border is not None:
                pg.draw.rect(surf, pg.Color(border), surf.get_rect(),
                             width=max(int(border_width * k), 1), border_radius=r)
        return supersample(size, render)
    return memoized_surface(_ROUNDED_RECT_CACHE, key, build)
