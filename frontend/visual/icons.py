import pygame as pg

from frontend.visual.colors import Colors

_SS = 4
_SPEAKER_BODY = [(3, 9), (6.5, 9), (11, 5.2), (11, 18.8), (6.5, 15), (3, 15)]


def draw_speaker(window, rect, color, muted=False):
    side = int(min(rect.width, rect.height) * 0.62)
    if side < 4:
        return
    big = side * _SS
    surf = pg.Surface((big, big), pg.SRCALPHA)
    u = big / 24.0
    col = pg.Color(color)
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
    small = pg.transform.smoothscale(surf, (side, side))
    window.blit(small, (rect.centerx - side // 2, rect.centery - side // 2))


def make_speaker_icon(muted):
    color = Colors.accent if muted else Colors.text_dim

    def render(window, rect):
        draw_speaker(window, rect, color, muted=muted)

    return render
