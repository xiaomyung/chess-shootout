import math
import os

import pygame as pg

from chessshootout.paths import PIECES_PNG_DIR
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample

_ICON_CACHE = new_cache()


def _blit_icon(window, rect, side, key, build):
    window.blit(memoized_surface(_ICON_CACHE, key, build),
                (rect.centerx - side // 2, rect.centery - side // 2))


def piece_png_path(piece):
    return os.path.join(PIECES_PNG_DIR, f"{piece.type.value}_{piece.color.value}.png")


_SPEAKER_BODY = [(3, 9), (6.5, 9), (11, 5.2), (11, 18.8), (6.5, 15), (3, 15)]


def draw_speaker(window, rect, color, muted=False):
    side = int(min(rect.width, rect.height) * 0.62)
    if side < 4:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _SPEAKER_BODY])
        lw = max(int(1.8 * u), 2)
        if muted:
            pg.draw.line(surf, col, (14.5 * u, 9.5 * u), (20.5 * u, 15 * u), lw)
            pg.draw.line(surf, col, (20.5 * u, 9.5 * u), (14.5 * u, 15 * u), lw)
        else:
            for radius in (4.2, 7.2):
                r = radius * u
                cx, cy = 11.5 * u, 12 * u
                pg.draw.arc(surf, col, pg.Rect(cx - r, cy - r, 2 * r, 2 * r), -0.7, 0.7, lw)

    _blit_icon(window, rect, side, ("speaker", side, str(color), muted),
               lambda: supersample(side, render))


def make_speaker_icon(muted):
    color = Colors.accent if muted else Colors.text_dim

    def render(window, rect):
        draw_speaker(window, rect, color, muted=muted)

    return render


_FOLDER_BODY = [(3, 7.5), (3.6, 6.4), (8.6, 6.4), (10.6, 8.2),
                (20.4, 8.2), (21, 9.2), (21, 17.6), (3, 17.6)]
_FILE_BODY = [(6, 4), (13.5, 4), (18, 8.5), (18, 20), (6, 20)]
_FILE_FOLD = [(13.5, 4), (13.5, 8.5), (18, 8.5)]


def _icon_side(rect, fraction=0.74):
    return int(min(rect.width, rect.height) * fraction)


def draw_folder(window, rect, color):
    side = _icon_side(rect)
    if side < 4:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _FOLDER_BODY])

    _blit_icon(window, rect, side, ("folder", side, str(color)),
               lambda: supersample(side, render))


def draw_file(window, rect, color):
    side = _icon_side(rect)
    if side < 4:
        return
    col = pg.Color(color)
    fold = col.lerp(pg.Color(Colors.bg), 0.55)

    def render(surf, k):
        u = side * k / 24.0
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _FILE_BODY])
        pg.draw.polygon(surf, fold, [(x * u, y * u) for x, y in _FILE_FOLD])

    _blit_icon(window, rect, side, ("file", side, str(color)),
               lambda: supersample(side, render))


_FOLDER_OUTLINE = [(3.5, 8), (3.5, 7), (4.4, 6.2), (8.6, 6.2), (10.6, 8.2),
                   (20, 8.2), (20.5, 9), (20.5, 18), (3.5, 18)]


def _stroke(surf, col, pts, closed, lw):
    pg.draw.lines(surf, col, closed, pts, lw)
    r = max(lw // 2, 1)
    for px, py in pts:
        pg.draw.circle(surf, col, (int(px), int(py)), r)


def draw_folder_plus(window, rect, color):
    side = _icon_side(rect, 0.86)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        lw = max(int(1.7 * u), 2)
        _stroke(surf, col, [(x * u, y * u) for x, y in _FOLDER_OUTLINE], True, lw)
        pg.draw.line(surf, col, (12 * u, 11 * u), (12 * u, 16 * u), lw)
        pg.draw.line(surf, col, (9.5 * u, 13.5 * u), (14.5 * u, 13.5 * u), lw)

    _blit_icon(window, rect, side, ("folder_plus", side, str(color)),
               lambda: supersample(side, render, scale=6))


def draw_eye(window, rect, color, off=False):
    side = _icon_side(rect, 0.86)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        lw = max(int(1.7 * u), 2)
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
               lambda: supersample(side, render, scale=6))


_PLAY_TRIANGLE = [(8, 5), (8, 19), (19, 12)]


def draw_play(window, rect, color):
    side = _icon_side(rect)
    if side < 4:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _PLAY_TRIANGLE])

    _blit_icon(window, rect, side, ("play", side, str(color)),
               lambda: supersample(side, render))


def draw_clock(window, rect, color):
    side = _icon_side(rect, 0.82)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        lw = max(int(1.7 * u), 2)
        cx, cy, r = 12 * u, 12.5 * u, 8 * u
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r), width=lw)
        pg.draw.line(surf, col, (cx, cy), (cx, cy - r * 0.62), lw)
        pg.draw.line(surf, col, (cx, cy), (cx + r * 0.48, cy + r * 0.24), lw)

    _blit_icon(window, rect, side, ("clock", side, str(color)),
               lambda: supersample(side, render, scale=6))


_MEDAL_RIBBON_L = [(9, 15), (9, 21), (12, 18.5)]
_MEDAL_RIBBON_R = [(15, 15), (15, 21), (12, 18.5)]


def draw_medal(window, rect, color):
    side = _icon_side(rect, 0.82)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        lw = max(int(1.6 * u), 2)
        cx, cy, r = 12 * u, 9.5 * u, 6 * u
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r), width=lw)
        pg.draw.polygon(surf, col, [
            (cx, cy - r * 0.5), (cx + r * 0.5, cy), (cx, cy + r * 0.5), (cx - r * 0.5, cy)])
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _MEDAL_RIBBON_L])
        pg.draw.polygon(surf, col, [(x * u, y * u) for x, y in _MEDAL_RIBBON_R])

    _blit_icon(window, rect, side, ("medal", side, str(color)),
               lambda: supersample(side, render, scale=6))


def draw_swords(window, rect, color):
    side = _icon_side(rect, 0.86)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        lw = max(int(1.8 * u), 2)
        pg.draw.line(surf, col, (5 * u, 5 * u), (19 * u, 19 * u), lw)
        pg.draw.line(surf, col, (19 * u, 5 * u), (5 * u, 19 * u), lw)
        guard = 2.6 * u
        pg.draw.line(surf, col, (12 * u - guard, 12 * u - guard * 0.35),
                     (12 * u + guard, 12 * u + guard * 0.35), lw)
        pg.draw.line(surf, col, (12 * u - guard, 12 * u + guard * 0.35),
                     (12 * u + guard, 12 * u - guard * 0.35), lw)
        pg.draw.circle(surf, col, (int(5 * u), int(19 * u)), int(1.6 * u))
        pg.draw.circle(surf, col, (int(19 * u), int(19 * u)), int(1.6 * u))

    _blit_icon(window, rect, side, ("swords", side, str(color)),
               lambda: supersample(side, render, scale=6))


def draw_people(window, rect, color):
    side = _icon_side(rect, 0.82)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        lw = max(int(1.6 * u), 2)
        pg.draw.circle(surf, col, (int(8 * u), int(8.5 * u)), int(2.6 * u), width=lw)
        pg.draw.arc(surf, col, pg.Rect(2 * u, 11 * u, 12 * u, 11 * u), 0.15,
                    math.pi - 0.15, lw)
        pg.draw.circle(surf, col, (int(15.5 * u), int(9.5 * u)), int(3.2 * u), width=lw)
        pg.draw.arc(surf, col, pg.Rect(8.5 * u, 12.3 * u, 14 * u, 12 * u), 0.1,
                    math.pi - 0.1, lw)

    _blit_icon(window, rect, side, ("people", side, str(color)),
               lambda: supersample(side, render, scale=6))


def draw_gear(window, rect, color):
    side = _icon_side(rect, 0.86)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
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
               lambda: supersample(side, render, scale=6))


def draw_reticle(window, rect, color, alpha=255):
    side = _icon_side(rect, 0.9)
    if side < 6:
        return
    col = pg.Color(color)

    def render(surf, k):
        u = side * k / 24.0
        cx, cy = 12 * u, 12 * u
        r = 7 * u
        lw = max(int(1.6 * u), 2)
        pg.draw.circle(surf, col, (int(cx), int(cy)), int(r), width=lw)
        tick, gap = 3.2 * u, 1.6 * u
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            x0, y0 = cx + dx * (r + gap), cy + dy * (r + gap)
            x1, y1 = cx + dx * (r + gap + tick), cy + dy * (r + gap + tick)
            pg.draw.line(surf, col, (x0, y0), (x1, y1), lw)
        pg.draw.circle(surf, col, (int(cx), int(cy)), max(int(1.6 * u), 2))

    surf = memoized_surface(_ICON_CACHE, ("reticle", side, str(color)),
                             lambda: supersample(side, render, scale=6))
    surf.set_alpha(max(0, min(255, int(alpha))))
    window.blit(surf, (rect.centerx - side // 2, rect.centery - side // 2))
