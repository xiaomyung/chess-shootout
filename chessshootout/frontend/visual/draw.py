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


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


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


_CUT_RECT_CACHE = new_cache()
_CUT_CORNERS = ("tl", "tr", "br", "bl")


def _cut_rect_points(left, top, right, bottom, cut, corners):
    c = max(0.0, min(cut, (right - left) / 2, (bottom - top) / 2))
    pts = []
    pts += [(left, top + c), (left + c, top)] if "tl" in corners and c > 0 else [(left, top)]
    pts += [(right - c, top), (right, top + c)] if "tr" in corners and c > 0 else [(right, top)]
    pts += [(right, bottom - c), (right - c, bottom)] if "br" in corners and c > 0 \
        else [(right, bottom)]
    pts += [(left + c, bottom), (left, bottom - c)] if "bl" in corners and c > 0 \
        else [(left, bottom)]
    return pts


def cut_rect_surface(size, cut, fill, border=None, border_width=1, corners=("tr",)):
    size_key = size if isinstance(size, int) else tuple(size)
    corner_key = tuple(c for c in _CUT_CORNERS if c in corners)
    key = (size_key, int(cut), str(fill), None if border is None else str(border),
           border_width, corner_key)

    def build():
        def render(surf, k):
            w, h = surf.get_size()
            if border is None:
                pg.draw.polygon(surf, pg.Color(fill),
                                _cut_rect_points(0, 0, w, h, cut * k, corners))
                return
            bw = max(border_width * k, 1.0)
            pg.draw.polygon(surf, pg.Color(border),
                            _cut_rect_points(0, 0, w, h, cut * k, corners))
            inner_cut = max(cut * k - bw * 1.414, 0.0)
            pg.draw.polygon(surf, pg.Color(fill),
                            _cut_rect_points(bw, bw, w - bw, h - bw, inner_cut, corners))
        return supersample(size, render)
    return memoized_surface(_CUT_RECT_CACHE, key, build)


def _rounded_rect_perimeter(w, h, r, arc_segs=8):
    r = max(0.0, min(r, w / 2, h / 2))
    pts = [(r, 0.0)]

    def arc(cx, cy, a0, a1):
        for i in range(1, arc_segs + 1):
            a = math.radians(a0 + (a1 - a0) * i / arc_segs)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    pts.append((w - r, 0.0))
    arc(w - r, r, -90, 0)
    pts.append((w, h - r))
    arc(w - r, h - r, 0, 90)
    pts.append((r, h))
    arc(r, h - r, 90, 180)
    pts.append((0, r))
    arc(r, r, 180, 270)
    return pts


def _densify(pts, step):
    dense = [(pts[0], 0.0)]
    dist = 0.0
    n = len(pts)
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if seg_len <= 0:
            continue
        steps = max(1, round(seg_len / step))
        for s in range(1, steps + 1):
            t = s / steps
            dist += seg_len / steps
            dense.append(((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t), dist))
    return dense


_DASHED_RECT_CACHE = new_cache()


def dashed_rounded_rect_surface(size, radius, border, border_width=1, dash=6, gap=5, fill=None):
    size_key = size if isinstance(size, int) else tuple(size)
    key = (size_key, int(radius), str(border), border_width, dash, gap,
           None if fill is None else str(fill))

    def build():
        def render(surf, k):
            w, h = surf.get_size()
            r = radius * k
            if fill is not None:
                pg.draw.rect(surf, pg.Color(fill), surf.get_rect(),
                             border_radius=max(int(r), 1))
            lw = max(int(border_width * k), 1)
            dense = _densify(_rounded_rect_perimeter(w, h, r), max(2.0 * k, 1.0))
            period = dash * k + gap * k
            run = []
            for pt, dist in dense:
                if (dist % period) < dash * k:
                    run.append(pt)
                else:
                    if len(run) >= 2:
                        pg.draw.lines(surf, pg.Color(border), False, run, lw)
                    run = []
            if len(run) >= 2:
                pg.draw.lines(surf, pg.Color(border), False, run, lw)
        return supersample(size, render)
    return memoized_surface(_DASHED_RECT_CACHE, key, build)


_CHEVRON_CACHE = new_cache()


def chevron_surface(height, color, up=False):
    h = max(int(height), 4)
    w = int(h * 1.6)

    def build():
        def render(surf, k):
            bw, bh = surf.get_size()
            lw = max(int(h * 0.16 * k), 2)
            if up:
                pts = [(bw * 0.12, bh * 0.68), (bw * 0.5, bh * 0.28), (bw * 0.88, bh * 0.68)]
            else:
                pts = [(bw * 0.12, bh * 0.32), (bw * 0.5, bh * 0.72), (bw * 0.88, bh * 0.32)]
            pg.draw.lines(surf, pg.Color(color), False, pts, lw)
        return supersample((w, h), render)
    return memoized_surface(_CHEVRON_CACHE, (h, up, str(color)), build)
