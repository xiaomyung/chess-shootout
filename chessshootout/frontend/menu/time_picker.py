import math

import pygame as pg

from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    dashed_rounded_rect_surface, infinity_surface, supersample)
from chessshootout.frontend.visual.fonts import get_display_font, get_mono_font
from chessshootout.frontend.visual.tween import Tween


CHAMBERS = ((1, "1"), (3, "3"), (5, "5"), (10, "10"), (15, "15"), (30, "30"), (None, "∞"))
INCREMENTS = (0, 2, 5, 10, 15)
CHAMBER_COUNT = len(CHAMBERS)
CHAMBER_STEP_DEG = 360.0 / CHAMBER_COUNT

ROTATION_MS = 220
TURRET_SWING_MS = 260
SETTLE_MS = 90

DISC_MARGIN_FRAC = 0.20
CHAMBER_RING_FRAC = 0.58
CHAMBER_RADIUS_FRAC = 0.22
CHAMBER_BORE_FRAC = 0.58
FLUTE_RING_FRAC = 0.82
FLUTE_RADIUS_FRAC = 0.11
STAR_RADIUS_FRAC = 0.16
STAR_INNER_FRAC = 0.44
PIN_RADIUS_FRAC = 0.10
HAMMER_TIP_FRAC = 0.90
HAMMER_BASE_FRAC = 1.12
HAMMER_HALF_FRAC = 0.16
CHAMBER_FONT_FRAC = 0.26

TURRET_SIZE_FRAC = 0.75
TURRET_RING_FRAC = 0.94
TURRET_RING_DASH_FRAC = 0.11
TURRET_RING_GAP_FRAC = 0.09
TURRET_LABEL_RING_FRAC = 0.94
TURRET_LABEL_R_FRAC = 0.15
TURRET_BUBBLE_R_FRAC = 0.22
TURRET_NEEDLE_FRAC = 0.80
TURRET_NEEDLE_WIDTH_FRAC = 0.05
TURRET_VALUE_FONT_FRAC = 0.34
TURRET_LABEL_FONT_FRAC = 0.24
TURRET_CAPTION_FONT_FRAC = 0.13
TURRET_CAPTION_GAP_FRAC = 0.22
TURRET_SPREAD_DEG = 72.0
TURRET_BASE_DEG = -144.0
TURRET_DEAD_ALPHA = 90

READOUT_LABEL_FONT_FRAC = 0.22
READOUT_VALUE_FONT_FRAC = 0.34
READOUT_INSET_FRAC = 0.10


def _pt(cx, cy, radius, deg):
    angle = math.radians(deg - 90.0)
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def _star_points(cx, cy, outer, inner, rotation):
    points = []
    for i in range(CHAMBER_COUNT):
        points.append(_pt(cx, cy, outer, rotation + i * CHAMBER_STEP_DEG))
        points.append(_pt(cx, cy, inner, rotation + (i + 0.5) * CHAMBER_STEP_DEG))
    return points


class TimePicker:

    def __init__(self, on_change=None, on_tick=None):
        self._on_change = on_change
        self._on_tick = on_tick
        self._min_index = 3
        self._inc_index = 2
        self.rect = pg.Rect(0, 0, 0, 0)
        self._drum_center = (0, 0)
        self._turret_center = (0, 0)
        self._radius = 1.0
        self._turret_radius = 1.0
        self._readout_rect = pg.Rect(0, 0, 0, 0)
        self._rotation = -self._min_index * CHAMBER_STEP_DEG
        self._rot_tween = None
        self._rot_start = self._rotation
        self._rot_target = self._rotation
        self._rot_steps = 0
        self._rot_ticks = 0
        self._turret_angle = TURRET_BASE_DEG + self._inc_index * TURRET_SPREAD_DEG
        self._turret_tween = None
        self._now = 0
        self._label_font = get_mono_font(11, bold=True)
        self._value_font = get_display_font(18)
        self._chamber_font = get_mono_font(13, bold=True)
        self._caption_font = get_mono_font(9, bold=True)
        self._readout_label_font = get_mono_font(9, bold=True)
        self._readout_value_font = get_mono_font(15, bold=True)

    @property
    def selected_minutes(self):
        return CHAMBERS[self._min_index][0]

    @property
    def selected_increment(self):
        if self.selected_minutes is None:
            return 0
        return INCREMENTS[self._inc_index]

    def set_selection(self, minutes, increment):
        self._min_index = self._chamber_index_for(minutes)
        if minutes is None:
            self._inc_index = 0
        elif increment in INCREMENTS:
            self._inc_index = INCREMENTS.index(increment)
        self._rotation = -self._min_index * CHAMBER_STEP_DEG
        self._rot_tween = None
        self._turret_angle = TURRET_BASE_DEG + self._inc_index * TURRET_SPREAD_DEG
        self._turret_tween = None

    def _chamber_index_for(self, minutes):
        for i, (value, _) in enumerate(CHAMBERS):
            if value == minutes:
                return i
        return self._min_index

    def readout_text(self):
        if self.selected_minutes is None:
            return "∞"
        return f"{self.selected_minutes}+{self.selected_increment}"

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        readout_h = max(int(rect.height * 0.16), 1)
        dial_h = rect.height - readout_h
        half = rect.width / 2.0
        self._radius = max(min(half, dial_h) / 2.0 * 0.88, 8.0)
        self._turret_radius = self._radius * TURRET_SIZE_FRAC
        cy = rect.y + dial_h / 2.0
        self._drum_center = (rect.x + half / 2.0, cy)
        self._turret_center = (rect.right - half / 2.0, cy)
        self._readout_rect = pg.Rect(rect.x, rect.bottom - readout_h, rect.width, readout_h)
        r = self._radius
        tr = self._turret_radius
        self._label_font = get_mono_font(max(int(tr * TURRET_LABEL_FONT_FRAC), 1), bold=True)
        self._value_font = get_display_font(max(int(tr * TURRET_VALUE_FONT_FRAC), 1))
        self._chamber_font = get_mono_font(max(int(r * CHAMBER_FONT_FRAC), 1), bold=True)
        self._caption_font = get_mono_font(max(int(tr * TURRET_CAPTION_FONT_FRAC), 1), bold=True)
        self._readout_label_font = get_mono_font(
            max(int(r * READOUT_LABEL_FONT_FRAC), 1), bold=True)
        self._readout_value_font = get_mono_font(
            max(int(r * READOUT_VALUE_FONT_FRAC), 1), bold=True)

    def _turret_dead(self):
        return self.selected_minutes is None

    def chamber_center(self, index):
        return _pt(self._drum_center[0], self._drum_center[1],
                   self._radius * CHAMBER_RING_FRAC,
                   index * CHAMBER_STEP_DEG + self._rotation)

    def _nearest_chamber(self, pos):
        best, best_d = 0, None
        for i in range(CHAMBER_COUNT):
            cx, cy = self.chamber_center(i)
            d = (cx - pos[0]) ** 2 + (cy - pos[1]) ** 2
            if best_d is None or d < best_d:
                best, best_d = i, d
        return best

    def _turret_label_rect(self, i):
        cx, cy = _pt(self._turret_center[0], self._turret_center[1],
                     self._turret_radius * TURRET_LABEL_RING_FRAC,
                     TURRET_BASE_DEG + i * TURRET_SPREAD_DEG)
        side = self._turret_radius * TURRET_BUBBLE_R_FRAC * 2
        return pg.Rect(cx - side / 2, cy - side / 2, side, side)

    def handle_click(self, pos):
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        if dx * dx + dy * dy <= (self._radius * 1.08) ** 2:
            self._select_minutes(self._nearest_chamber(pos))
            return True
        if self._turret_dead():
            return False
        for i in range(len(INCREMENTS)):
            if self._turret_label_rect(i).collidepoint(pos):
                self._select_increment(i)
                return True
        tx = pos[0] - self._turret_center[0]
        ty = pos[1] - self._turret_center[1]
        if tx * tx + ty * ty <= (self._turret_radius * 1.05) ** 2:
            self._select_increment((self._inc_index + 1) % len(INCREMENTS))
            return True
        return False

    def _select_minutes(self, index):
        if index == self._min_index:
            return
        self._min_index = index
        base_target = -index * CHAMBER_STEP_DEG
        delta = ((base_target - self._rotation + 180.0) % 360.0) - 180.0
        self._rot_start = self._rotation
        self._rot_target = self._rotation + delta
        self._rot_steps = int(round(abs(delta) / CHAMBER_STEP_DEG))
        self._rot_ticks = 0
        self._rot_tween = Tween(self._rotation, self._rot_target,
                                ROTATION_MS + SETTLE_MS, self._now)
        if self.selected_minutes is None:
            self._inc_index = 0
            self._turret_angle = TURRET_BASE_DEG
            self._turret_tween = None
        self._changed()

    def _select_increment(self, index):
        self._inc_index = index
        self._turret_tween = Tween(
            self._turret_angle, TURRET_BASE_DEG + index * TURRET_SPREAD_DEG,
            TURRET_SWING_MS, self._now)
        self._emit_tick()
        self._changed()

    def _changed(self):
        if self._on_change is not None:
            self._on_change()

    def _emit_tick(self):
        if self._on_tick is not None:
            self._on_tick()

    def update(self, now):
        self._now = now
        if self._rot_tween is not None:
            self._rotation = self._rot_tween.value(now)
            crossed = int(round(abs(self._rotation - self._rot_start) / CHAMBER_STEP_DEG))
            crossed = min(crossed, self._rot_steps)
            while self._rot_ticks < crossed:
                self._rot_ticks += 1
                self._emit_tick()
            if self._rot_tween.done(now):
                self._rotation = self._rot_target
                self._rot_tween = None
        if self._turret_tween is not None:
            self._turret_angle = self._turret_tween.value(now)
            if self._turret_tween.done(now):
                self._turret_angle = TURRET_BASE_DEG + self._inc_index * TURRET_SPREAD_DEG
                self._turret_tween = None

    def draw(self, surface, now):
        self.update(now)
        self._draw_drum(surface)
        self._draw_turret(surface)
        self._draw_readout(surface)

    def _footprint(self, radius):
        return int(round(radius * (1.0 + DISC_MARGIN_FRAC) * 2)) + 2

    def _draw_drum(self, surface):
        size = self._footprint(self._radius)
        rotation = self._rotation

        def render(surf, k):
            c = surf.get_width() / 2.0
            r = self._radius * k
            pg.draw.circle(surf, pg.Color(Colors.surface_raised), (c, c), r)
            pg.draw.circle(surf, pg.Color(Colors.dial_border), (c, c), r,
                           max(int(1 * k), 1))
            for i in range(CHAMBER_COUNT):
                fx, fy = _pt(c, c, r * FLUTE_RING_FRAC,
                             (i + 0.5) * CHAMBER_STEP_DEG + rotation)
                fr = r * FLUTE_RADIUS_FRAC
                pg.draw.circle(surf, pg.Color(Colors.battle_bg), (fx, fy), fr)
                pg.draw.circle(surf, pg.Color(Colors.dial_border), (fx, fy), fr,
                               max(int(1 * k), 1))
            pg.draw.polygon(surf, pg.Color(Colors.dial_star),
                            _star_points(c, c, r * STAR_RADIUS_FRAC,
                                         r * STAR_RADIUS_FRAC * STAR_INNER_FRAC, rotation))
            for i in range(CHAMBER_COUNT):
                cx, cy = _pt(c, c, r * CHAMBER_RING_FRAC, i * CHAMBER_STEP_DEG + rotation)
                cr = r * CHAMBER_RADIUS_FRAC
                sel = i == self._min_index
                pg.draw.circle(surf, pg.Color(Colors.bg), (cx, cy), cr)
                pg.draw.circle(surf, pg.Color(Colors.surface), (cx, cy),
                               cr * CHAMBER_BORE_FRAC)
                border = Colors.accent if sel else Colors.dial_border
                pg.draw.circle(surf, pg.Color(border), (cx, cy), cr,
                               max(int((2.0 if sel else 1.0) * k), 1))
            pg.draw.circle(surf, pg.Color(Colors.dial_border), (c, c),
                           r * PIN_RADIUS_FRAC)
            pg.draw.circle(surf, pg.Color(Colors.bg), (c, c), r * PIN_RADIUS_FRAC,
                           max(int(1 * k), 1))
            base_y = c - r * HAMMER_BASE_FRAC
            base_half = r * HAMMER_HALF_FRAC
            pg.draw.polygon(surf, pg.Color(Colors.accent),
                            [(c, c - r * HAMMER_TIP_FRAC),
                             (c - base_half, base_y), (c + base_half, base_y)])

        dial = supersample((size, size), render)
        top = (int(self._drum_center[0] - size / 2), int(self._drum_center[1] - size / 2))
        surface.blit(dial, top)
        for i in range(CHAMBER_COUNT):
            cx, cy = self.chamber_center(i)
            sel = i == self._min_index
            label = CHAMBERS[i][1]
            color = Colors.text if sel else Colors.text_muted
            if label == "∞":
                glyph = infinity_surface(self._chamber_font.get_height() * 0.7, color)
                surface.blit(glyph, (cx - glyph.get_width() / 2, cy - glyph.get_height() / 2))
            else:
                surf = render_text(self._chamber_font, label, color)
                surface.blit(surf, (cx - surf.get_width() / 2, cy - surf.get_height() / 2))

    def _draw_turret_ring(self, surface):
        tr = self._turret_radius
        ring_d = max(int(round(tr * TURRET_RING_FRAC * 2)), 2)
        ring = dashed_rounded_rect_surface(
            ring_d, ring_d // 2, Colors.border_strong, border_width=2,
            dash=max(int(tr * TURRET_RING_DASH_FRAC), 2),
            gap=max(int(tr * TURRET_RING_GAP_FRAC), 2))
        if self._turret_dead():
            ring = ring.copy()
            ring.set_alpha(TURRET_DEAD_ALPHA)
        cx, cy = self._turret_center
        surface.blit(ring, (cx - ring_d / 2, cy - ring_d / 2))

    def _draw_turret_needle(self, surface):
        tr = self._turret_radius
        size = self._footprint(tr)
        angle = self._turret_angle
        dead = self._turret_dead()

        def render(surf, k):
            if dead:
                return
            c = surf.get_width() / 2.0
            r = tr * k
            tip = _pt(c, c, r * TURRET_NEEDLE_FRAC, angle)
            lw = max(int(r * TURRET_NEEDLE_WIDTH_FRAC), 2)
            pg.draw.line(surf, pg.Color(Colors.amber), (c, c), tip, lw)

        needle = supersample((size, size), render)
        cx, cy = self._turret_center
        surface.blit(needle, (cx - size / 2, cy - size / 2))

    def _draw_turret_labels(self, surface):
        dead = self._turret_dead()
        for i, inc in enumerate(INCREMENTS):
            rect = self._turret_label_rect(i)
            sel = i == self._inc_index and not dead
            if sel:
                bw = max(int(self._turret_radius * 0.05), 1)
                pg.draw.circle(surface, pg.Color(Colors.surface_raised), rect.center,
                               rect.width / 2)
                pg.draw.circle(surface, pg.Color(Colors.amber), rect.center,
                               rect.width / 2, bw)
            color = Colors.amber_hi if sel else Colors.text_muted
            surf = render_text(self._label_font, str(inc), color)
            surface.blit(surf, (rect.centerx - surf.get_width() / 2,
                                rect.centery - surf.get_height() / 2))

    def _draw_turret(self, surface):
        self._draw_turret_ring(surface)
        self._draw_turret_needle(surface)
        self._draw_turret_labels(surface)
        cx, cy = self._turret_center
        value = render_text(self._value_font, f"+{self.selected_increment}s",
                            Colors.amber_hi if not self._turret_dead() else Colors.text_muted)
        surface.blit(value, (cx - value.get_width() / 2, cy - value.get_height() / 2))
        caption = render_text(self._caption_font, "INCREMENT · CLICK TO RATCHET",
                              Colors.text_muted)
        cap_y = cy + self._turret_radius * TURRET_RING_FRAC + self._turret_radius * (
            TURRET_CAPTION_GAP_FRAC)
        surface.blit(caption, (cx - caption.get_width() / 2, cap_y))

    def _draw_readout(self, surface):
        rect = self._readout_rect
        inset = max(int(self._radius * READOUT_INSET_FRAC), 4)
        label = render_text(self._readout_label_font, "CHAMBERED", Colors.text_muted)
        infinite = self.selected_minutes is None
        if infinite:
            value = infinity_surface(self._readout_value_font.get_height(), Colors.text)
        else:
            value = render_text(self._readout_value_font, self.readout_text(), Colors.text)
        surface.blit(label, (rect.x + inset, rect.centery - label.get_height() / 2))
        surface.blit(value, (rect.right - inset - value.get_width(),
                             rect.centery - value.get_height() / 2))
