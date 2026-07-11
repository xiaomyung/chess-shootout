import math

import pygame as pg

from chessshootout.frontend.skillcheck.controller import (
    SkillCheckController, SKILLCHECK_RESULT_HOLD_MS, EdgeTrigger)
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import rounded_rect_surface, supersample
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS, adjudicate

WHEEL_RESULT_HOLD_MS = 380
WHEEL_TIME_LIMIT_MS = SKILLCHECK_DEADLINE_MS
WHEEL_DEFAULT_DEADLINE_MS = WHEEL_TIME_LIMIT_MS
WHEEL_TIMER_RAMP = 2.0
_ARC_STEPS = 56

WHEEL_MIN_RADIUS = 24
WHEEL_RING_FRAC = 0.08
WHEEL_MIN_RING_W = 2
WHEEL_BAND_FRAC = 0.20
WHEEL_MIN_BAND_W = 3
WHEEL_NEEDLE_FRAC = 0.12
WHEEL_MIN_NEEDLE_W = 2
WHEEL_HUB_FRAC = 0.10
WHEEL_MIN_HUB_R = 2
WHEEL_NEEDLE_TIP_FRAC = 0.30
WHEEL_MIN_NEEDLE_TIP_W = 2
WHEEL_TIMER_GAP_FRAC = 0.06
WHEEL_MIN_TIMER_GAP = 1
WHEEL_BACKDROP_PAD_FRAC = 0.08
WHEEL_HINT_FONT_FRAC = 0.26
WHEEL_MIN_HINT_FONT = 10
WHEEL_HINT_PAD_X_FRAC = 0.24
WHEEL_HINT_PAD_Y_FRAC = 0.12
WHEEL_HINT_GAP_FRAC = 0.20
WHEEL_FOOTPRINT_CELL_FRAC = 1.20
WHEEL_SURFACE_MARGIN_PX = 8
WHEEL_FOOTPRINT_DENOM = 2 * (1 + WHEEL_RING_FRAC + WHEEL_TIMER_GAP_FRAC)

_WHEEL_STATIC_CACHE = new_cache()


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


def _clamp_bubble_left(left, bubble_w, window_w):
    return max(4, min(left, window_w - bubble_w - 4))


def _needle_polygon(cx, cy, deg, length, base_w, tip_w):
    angle = math.radians(deg - 90.0)
    dx, dy = math.cos(angle), math.sin(angle)
    px, py = -dy, dx
    base_half, tip_half = base_w / 2.0, tip_w / 2.0
    tip_x, tip_y = cx + dx * length, cy + dy * length
    return [
        (cx + px * base_half, cy + py * base_half),
        (tip_x + px * tip_half, tip_y + py * tip_half),
        (tip_x - px * tip_half, tip_y - py * tip_half),
        (cx - px * base_half, cy - py * base_half),
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
        cell = cell_rect.width
        self.radius = max(WHEEL_MIN_RADIUS, round(
            (cell * WHEEL_FOOTPRINT_CELL_FRAC - WHEEL_SURFACE_MARGIN_PX) / WHEEL_FOOTPRINT_DENOM))
        r = self.radius
        self.ring_w = max(WHEEL_MIN_RING_W, round(r * WHEEL_RING_FRAC))
        self.band_w = max(WHEEL_MIN_BAND_W, round(r * WHEEL_BAND_FRAC))
        self.needle_w = max(WHEEL_MIN_NEEDLE_W, round(r * WHEEL_NEEDLE_FRAC))
        self.hub_r = max(WHEEL_MIN_HUB_R, round(r * WHEEL_HUB_FRAC))
        self.needle_tip_w = max(
            WHEEL_MIN_NEEDLE_TIP_W, round(self.needle_w * WHEEL_NEEDLE_TIP_FRAC))
        self.timer_gap = max(WHEEL_MIN_TIMER_GAP, round(r * WHEEL_TIMER_GAP_FRAC))
        self.backdrop_pad = round(r * WHEEL_BACKDROP_PAD_FRAC)
        self._hint_font = get_font(
            max(WHEEL_MIN_HINT_FONT, round(r * WHEEL_HINT_FONT_FRAC)), bold=True)
        self._hint_pad_x = round(r * WHEEL_HINT_PAD_X_FRAC)
        self._hint_pad_y = round(r * WHEEL_HINT_PAD_Y_FRAC)
        self._hint_gap = round(r * WHEEL_HINT_GAP_FRAC)

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
        timer_outer = self.radius + self.ring_w + self.timer_gap
        size = timer_outer * 2 + WHEEL_SURFACE_MARGIN_PX
        window.blit(self._render_dial(elapsed, size), (cx - size // 2, cy - size // 2))
        if self._committed_at is None and not self._passive:
            self._draw_hint_bubble(window, cx, cy, timer_outer)

    def _render_dial(self, elapsed, size):
        layer = self._static_layer(size).copy()
        layer.blit(self._render_dynamic(elapsed, size), (0, 0))
        return layer

    def _static_layer(self, size):
        def build():
            def render(surf, k):
                c = surf.get_width() / 2.0
                pg.draw.circle(surf, pg.Color(Colors.bg + "ea"), (c, c),
                               (self.radius + self.backdrop_pad) * k)
                pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), self.radius * k,
                               max(int(self.ring_w * k), 1))
            return supersample((size, size), render)
        return memoized_surface(_WHEEL_STATIC_CACHE, self.radius, build)

    def _render_dynamic(self, elapsed, size):
        def render(surf, k):
            c = surf.get_width() / 2.0

            if self._committed_at is None and self.deadline_ms > 0:
                remaining = max(0.0, 1.0 - elapsed / self.deadline_ms)
                if remaining > 0.0:
                    blend = (1.0 - remaining) ** WHEEL_TIMER_RAMP
                    timer_base = Colors.spectate if self._passive else Colors.amber
                    timer_color = pg.Color(timer_base).lerp(pg.Color(Colors.loss), blend)
                    inner = (self.radius + self.timer_gap) * k
                    outer = (self.radius + self.ring_w + self.timer_gap) * k
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
            band = _band_polygon(c, c, (self.radius - self.band_w) * k, self.radius * k,
                                 self.challenge.arc_start_deg,
                                 self.challenge.arc_start_deg + arc_width)
            pg.draw.polygon(surf, pg.Color(arc_color), band)

            needle_len = (self.radius - self.ring_w - 2) * k
            needle_deg = self.challenge.needle_deg(elapsed)
            pg.draw.polygon(surf, pg.Color(Colors.text),
                            _needle_polygon(c, c, needle_deg, needle_len,
                                            self.needle_w * k, self.needle_tip_w * k))
            pg.draw.circle(surf, pg.Color(Colors.text),
                           _rim_point(c, c, needle_len, needle_deg), self.needle_tip_w * k / 2.0)
            pg.draw.circle(surf, pg.Color(Colors.text), (c, c), max(self.hub_r * k, 1))

        return supersample((size, size), render)

    def _draw_hint_bubble(self, window, cx, cy, timer_outer):
        label = self._hint_font.render("SPACE / CLICK", True, pg.Color(Colors.text))
        pad_x, pad_y = self._hint_pad_x, self._hint_pad_y
        bubble_w = label.get_width() + pad_x * 2
        bubble_h = label.get_height() + pad_y * 2
        bubble = rounded_rect_surface((bubble_w, bubble_h), bubble_h // 2,
                                      Colors.surface_raised, border=Colors.border_strong,
                                      border_width=1)
        left = _clamp_bubble_left(cx - bubble_w // 2, bubble_w, window.get_width())
        top = cy + timer_outer + self._hint_gap
        if top + bubble_h > window.get_height():
            top = cy - timer_outer - self._hint_gap - bubble_h
        window.blit(bubble, (left, top))
        window.blit(label, (left + pad_x, top + pad_y))
