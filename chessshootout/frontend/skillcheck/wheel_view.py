import math

import pygame as pg

from chessshootout.frontend.skillcheck.controller import (
    SkillCheckController, SKILLCHECK_RESULT_HOLD_MS, EdgeTrigger)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import rounded_rect_surface, supersample
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS, adjudicate

WHEEL_DIAL_SCALE = 1.0
WHEEL_RESULT_HOLD_MS = 380
WHEEL_TIME_LIMIT_MS = SKILLCHECK_DEADLINE_MS
WHEEL_DEFAULT_DEADLINE_MS = WHEEL_TIME_LIMIT_MS
WHEEL_TIMER_RAMP = 2.0
_ARC_STEPS = 56


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

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms=WHEEL_DEFAULT_DEADLINE_MS,
                 on_shot=None, passive=False, audio=None):
        self.challenge = challenge
        self._apply_geometry(cell_rect)
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self._committed_at = None
        self._resolved_at = None
        self._landed = None
        self._on_shot = on_shot
        self._passive = passive
        self._online = on_shot is not None or passive
        self._frozen_override = None
        self._audio = audio
        self._tick_edge = EdgeTrigger()
        self._cue("play_skillcheck_appear")

    def _apply_geometry(self, cell_rect):
        self.center = cell_rect.center
        self.radius = max(24, int(cell_rect.width * WHEEL_DIAL_SCALE * 0.5))
        self.ring_w = max(4, int(self.radius * 0.07))
        self.band_w = max(10, int(self.radius * 0.17))
        self.needle_w = max(6, int(self.radius * 0.09))
        self.hub_r = max(5, int(self.radius * 0.07))
        self._hint_font = get_font(max(13, int(self.radius * 0.20)), bold=True)

    def relayout(self, cell_rect):
        self._apply_geometry(cell_rect)

    def handle_event(self, event):
        if self._passive:
            return False
        if self._committed_at is not None:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._fire()
            return True
        if event.type == pg.KEYDOWN and event.key in (pg.K_SPACE, pg.K_RETURN):
            self._fire()
            return True
        return False

    def _fire(self):
        if self._online:
            self._committed_at = self._now
            self._on_shot(self._now - self.start_ms)
            return
        self._commit(self._landed_now())

    def resolve(self, won):
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        self._emit_verdict()

    def spectate_shot(self, elapsed, miss_count, won):
        self._frozen_override = elapsed
        self._committed_at = self._now

    def update(self, now_ms):
        self._now = now_ms
        if self._committed_at is None:
            elapsed = now_ms - self.start_ms
            in_arc = self.challenge.in_arc_at(self.challenge.needle_deg(elapsed), elapsed)
            if self._tick_edge.update(in_arc):
                self._cue("play_wheel_tick")
        if (not self._online and self._committed_at is None
                and now_ms - self.start_ms >= self.deadline_ms):
            self._commit(False)

    @property
    def done(self):
        if self._online:
            return (self._resolved_at is not None
                    and self._now - self._resolved_at >= SKILLCHECK_RESULT_HOLD_MS)
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
        self._emit_verdict()

    def _frozen_elapsed(self):
        if self._frozen_override is not None:
            return self._frozen_override
        frozen = self._committed_at if self._committed_at is not None else self._now
        return frozen - self.start_ms

    def draw(self, window):
        cx, cy = self.center
        elapsed = self._frozen_elapsed()
        timer_outer = self.radius + self.ring_w + 3
        size = timer_outer * 2 + 8
        window.blit(self._render_dial(elapsed, size), (cx - size // 2, cy - size // 2))
        if self._committed_at is None and not self._passive:
            self._draw_hint_bubble(window, cx, cy, timer_outer)

    def _render_dial(self, elapsed, size):
        def render(surf, k):
            c = surf.get_width() / 2.0
            radius = self.radius * k
            pg.draw.circle(surf, pg.Color(Colors.bg + "ea"), (c, c), (self.radius + 4) * k)
            pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), radius,
                           max(int(self.ring_w * k), 1))

            if self._committed_at is None and self.deadline_ms > 0:
                remaining = max(0.0, 1.0 - elapsed / self.deadline_ms)
                if remaining > 0.0:
                    blend = (1.0 - remaining) ** WHEEL_TIMER_RAMP
                    timer_base = Colors.spectate if self._passive else Colors.amber
                    timer_color = pg.Color(timer_base).lerp(pg.Color(Colors.loss), blend)
                    inner, outer = (self.radius + 3) * k, (self.radius + self.ring_w + 3) * k
                    end_deg = remaining * 360.0
                    pg.draw.polygon(surf, timer_color,
                                    _band_polygon(c, c, inner, outer, 0.0, end_deg))
                    cap_mid, cap_r = (inner + outer) / 2.0, (outer - inner) / 2.0
                    for cap_deg in (0.0, end_deg):
                        pg.draw.circle(surf, timer_color, _rim_point(c, c, cap_mid, cap_deg), cap_r)

            arc_width = self.challenge.arc_width_at(elapsed)
            arc_color = Colors.spectate if self._passive else Colors.accent
            if self._committed_at is not None and self._landed is not None:
                arc_color = Colors.win if self._landed else Colors.loss
            band = _band_polygon(c, c, (self.radius - self.band_w) * k, radius,
                                 self.challenge.arc_start_deg,
                                 self.challenge.arc_start_deg + arc_width)
            pg.draw.polygon(surf, pg.Color(arc_color), band)

            needle_len = (self.radius - self.ring_w - 2) * k
            needle_deg = self.challenge.needle_deg(elapsed)
            pg.draw.polygon(surf, pg.Color(Colors.text),
                            _needle_polygon(c, c, needle_deg, needle_len, self.needle_w * k))
            pg.draw.circle(surf, pg.Color(Colors.text),
                           _rim_point(c, c, needle_len, needle_deg), self.needle_w * k / 2.0)
            pg.draw.circle(surf, pg.Color(Colors.text), (c, c), max(self.hub_r * k, 1))

        return supersample((size, size), render)

    def _draw_hint_bubble(self, window, cx, cy, timer_outer):
        label = self._hint_font.render("SPACE / CLICK", True, pg.Color(Colors.text))
        pad_x, pad_y = 12, 6
        bubble_w = label.get_width() + pad_x * 2
        bubble_h = label.get_height() + pad_y * 2
        bubble = rounded_rect_surface((bubble_w, bubble_h), bubble_h // 2,
                                      Colors.surface_raised, border=Colors.border_strong,
                                      border_width=1)
        left = cx - bubble_w // 2
        top = cy + timer_outer + 10
        if top + bubble_h > window.get_height():
            top = cy - timer_outer - 10 - bubble_h
        window.blit(bubble, (left, top))
        window.blit(label, (left + pad_x, top + pad_y))
