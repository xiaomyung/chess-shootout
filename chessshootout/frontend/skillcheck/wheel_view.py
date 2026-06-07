import math

import pygame as pg

from chessshootout.frontend.skillcheck.controller import SkillCheckController
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.skillcheck.wheel import adjudicate

WHEEL_DIAL_SCALE = 1.5
WHEEL_RING_WIDTH = 5
WHEEL_BAND_WIDTH = 13
WHEEL_NEEDLE_WIDTH = 6
WHEEL_RESULT_HOLD_MS = 380
WHEEL_DEFAULT_DEADLINE_MS = 60000
_ARC_STEPS = 48


def _rim_point(cx, cy, radius, deg):
    angle = math.radians(deg - 90.0)
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def _band_polygon(cx, cy, inner, outer, deg_from, deg_to):
    points = []
    for i in range(_ARC_STEPS + 1):
        deg = deg_from + (deg_to - deg_from) * i / _ARC_STEPS
        points.append(_rim_point(cx, cy, outer, deg))
    for i in range(_ARC_STEPS + 1):
        deg = deg_to - (deg_to - deg_from) * i / _ARC_STEPS
        points.append(_rim_point(cx, cy, inner, deg))
    return points


def _needle_polygon(cx, cy, deg, length, width):
    angle = math.radians(deg - 90.0)
    dx, dy = math.cos(angle), math.sin(angle)
    px, py = -dy, dx
    half = width / 2.0
    tip_x, tip_y = cx + dx * length, cy + dy * length
    return [
        (cx + px * half, cy + py * half),
        (tip_x + px * half, tip_y + py * half),
        (tip_x - px * half, tip_y - py * half),
        (cx - px * half, cy - py * half),
    ]


class WheelController(SkillCheckController):

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms=WHEEL_DEFAULT_DEADLINE_MS):
        self.challenge = challenge
        self.center = cell_rect.center
        self.radius = max(30, int(cell_rect.width * WHEEL_DIAL_SCALE * 0.5))
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self._committed_at = None
        self._landed = None
        self._hint_font = get_font(max(11, cell_rect.width // 6), bold=True)

    def handle_event(self, event):
        if self._committed_at is not None:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._commit(self._landed_now())
            return True
        if event.type == pg.KEYDOWN and event.key in (pg.K_SPACE, pg.K_RETURN):
            self._commit(self._landed_now())
            return True
        return False

    def update(self, now_ms):
        self._now = now_ms
        if self._committed_at is None and now_ms - self.start_ms >= self.deadline_ms:
            self._commit(False)

    @property
    def done(self):
        return (self._committed_at is not None
                and self._now - self._committed_at >= WHEEL_RESULT_HOLD_MS)

    @property
    def landed(self):
        return self._landed

    def _landed_now(self):
        return adjudicate(self.challenge, self._now, self.start_ms, 0.0)

    def _commit(self, landed):
        self._landed = landed
        self._committed_at = self._now

    def _frozen_elapsed(self):
        frozen = self._committed_at if self._committed_at is not None else self._now
        return frozen - self.start_ms

    def draw(self, window):
        cx, cy = self.center
        radius = self.radius
        size = radius * 2 + 10
        disc = pg.Surface((size, size), pg.SRCALPHA)
        pg.draw.circle(disc, pg.Color(Colors.bg + "ea"), (size // 2, size // 2), radius + 4)
        window.blit(disc, (cx - size // 2, cy - size // 2))
        pg.draw.circle(window, pg.Color(Colors.border_strong), (cx, cy), radius, WHEEL_RING_WIDTH)

        elapsed = self._frozen_elapsed()
        arc_width = self.challenge.arc_width_at(elapsed)
        arc_color = Colors.accent
        if self._committed_at is not None:
            arc_color = Colors.win if self._landed else Colors.loss
        band = _band_polygon(
            cx, cy, radius - WHEEL_BAND_WIDTH, radius,
            self.challenge.arc_start_deg,
            self.challenge.arc_start_deg + arc_width,
        )
        pg.draw.polygon(window, pg.Color(arc_color), band)

        needle = _needle_polygon(cx, cy, self.challenge.needle_deg(elapsed),
                                 radius - 4, WHEEL_NEEDLE_WIDTH)
        pg.draw.polygon(window, pg.Color(Colors.text), needle)
        pg.draw.circle(window, pg.Color(Colors.text), (cx, cy), WHEEL_NEEDLE_WIDTH // 2 + 1)

        if self._committed_at is None:
            hint = self._hint_font.render("SPACE / CLICK", True, pg.Color(Colors.text_dim))
            window.blit(hint, hint.get_rect(center=(cx, cy + radius + 14)))
