import math
import os

import pygame as pg

from chessshootout.paths import PIECES_PNG_DIR
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample


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

    window.blit(supersample(side, render), (rect.centerx - side // 2, rect.centery - side // 2))


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

    window.blit(supersample(side, render), (rect.centerx - side // 2, rect.centery - side // 2))


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

    window.blit(supersample(side, render), (rect.centerx - side // 2, rect.centery - side // 2))


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

    window.blit(supersample(side, render, scale=6),
                (rect.centerx - side // 2, rect.centery - side // 2))


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

    window.blit(supersample(side, render, scale=6),
                (rect.centerx - side // 2, rect.centery - side // 2))
