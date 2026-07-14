import math

import pygame as pg

from chessshootout.frontend.visual.cache import (
    memoized_surface, new_size_cache, render_text)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import infinity_surface, supersample
from chessshootout.frontend.visual.fonts import get_display_font, get_mono_font
from chessshootout.frontend.visual.slider_tick import TickGate
from chessshootout.frontend.visual.tween import Tween


CHAMBERS = ((1, "1"), (3, "3"), (5, "5"), (10, "10"), (15, "15"), (30, "30"), (None, "∞"))
INCREMENTS = (0, 2, 5, 10, 15)
CHAMBER_COUNT = len(CHAMBERS)
CHAMBER_STEP_DEG = 360.0 / CHAMBER_COUNT

ROTATION_MS = 220
TURRET_SWING_MS = 260
SETTLE_MS = 90
SPIN_SETTLE_MS = 170
SPIN_FRICTION_TAU = 0.4
WHEEL_IMPULSE_DEG_PER_S = 150.0
SPIN_STOP_DEG_PER_S = 12.0
SPIN_MAX_DT = 0.05

DRAG_CLICK_THRESHOLD_DEG = 3.5
DRAG_VELOCITY_EMA_ALPHA = 0.35
DRAG_MAX_VELOCITY_DEG_PER_S = 2000.0

SEAT_POP_SCALE = 1.18
SEAT_POP_MS = 150

DISC_MARGIN_FRAC = 0.34
CHAMBER_RING_FRAC = 0.58
CHAMBER_RADIUS_FRAC = 0.25
SCALLOP_RING_FRAC = 1.05
SCALLOP_RADIUS_FRAC = 0.23
STAR_RADIUS_FRAC = 0.15
STAR_INNER_FRAC = 0.44
PIN_RADIUS_FRAC = 0.07
HAMMER_TIP_FRAC = 0.98
HAMMER_BASE_FRAC = 1.20
HAMMER_HALF_FRAC = 0.14
CHAMBER_FONT_FRAC = 0.20

TURRET_SIZE_FRAC = 0.78
TURRET_KNOB_FRAC = 0.60
TURRET_KNURL_TEETH = 36
TURRET_KNURL_LEN_FRAC = 0.06
TURRET_TICK_RING_FRAC = 0.98
TURRET_TICK_COUNT = 40
TURRET_TICK_MINOR_FRAC = 0.05
TURRET_TICK_MAJOR_FRAC = 0.12
TURRET_LABEL_RING_FRAC = 1.22
TURRET_BUBBLE_R_FRAC = 0.20
TURRET_NEEDLE_FRAC = 0.56
TURRET_NEEDLE_INNER_FRAC = 0.30
TURRET_NEEDLE_BASE_HALF_FRAC = 0.06
TURRET_VALUE_FONT_FRAC = 0.24
TURRET_LABEL_FONT_FRAC = 0.20
TURRET_CAPTION_FONT_FRAC = 0.14
TURRET_CAPTION_Y_FRAC = 1.30
TURRET_SPREAD_DEG = 72.0
TURRET_BASE_DEG = -144.0
TURRET_DEAD_ALPHA = 90

READOUT_LABEL_FONT_FRAC = 0.20
READOUT_VALUE_FONT_FRAC = 0.30
READOUT_INSET_FRAC = 0.10

DRUM_ANGLE_QUANT_DEG = 0.5
DRUM_CACHE_CAP = 32
NEEDLE_ANGLE_QUANT_DEG = 0.5
NEEDLE_CACHE_CAP = 16

_DRUM_CACHE = new_size_cache()
_TURRET_DIAL_CACHE = new_size_cache()
_TURRET_NEEDLE_CACHE = new_size_cache()
_TURRET_BUBBLE_CACHE = new_size_cache()


def _turret_bubble_surface(diameter, ring_w):
    def build():
        def render(surf, k):
            r = surf.get_width() / 2.0
            pg.draw.circle(surf, pg.Color(Colors.surface_raised), (r, r), r)
            pg.draw.circle(surf, pg.Color(Colors.amber), (r, r), r, max(int(ring_w * k), 1))
        return supersample((diameter, diameter), render, scale=8)
    return memoized_surface(_TURRET_BUBBLE_CACHE, (diameter, ring_w), build)


def _quantize(value, step):
    return round(value / step) * step


def _bounded_set(cache, key, build, cap):
    cached = cache.get(key)
    if cached is not None:
        del cache[key]
        cache[key] = cached
        return cached
    value = build()
    cache[key] = value
    if len(cache) > cap:
        del cache[next(iter(cache))]
    return value


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

    def __init__(self, on_change=None, on_tick=None, on_ratchet=None):
        self._on_change = on_change
        self._on_tick = on_tick
        self._on_ratchet = on_ratchet
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
        self._spinning = False
        self._spin_vel = 0.0
        self._spin_last_ms = None
        self._spin_tick_gate = TickGate(on_tick)
        self._drag_active = False
        self._drag_last_pointer_angle = 0.0
        self._drag_total_delta = 0.0
        self._drag_last_ms = None
        self._drag_vel = 0.0
        self._drag_vsampled = False
        self._seat_pop_tween = None
        self._seat_pop_index = self._min_index
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
        self._spinning = False
        self._spin_vel = 0.0
        self._drag_active = False
        self._seat_pop_tween = None
        self._seat_pop_index = self._min_index
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
        self._radius = max(min(half, dial_h) / (2.0 * (1.0 + DISC_MARGIN_FRAC)), 8.0)
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

    def _in_drum(self, pos):
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        return dx * dx + dy * dy <= (self._radius * 1.08) ** 2

    def _in_turret(self, pos):
        dx = pos[0] - self._turret_center[0]
        dy = pos[1] - self._turret_center[1]
        return dx * dx + dy * dy <= (self._turret_radius * 1.05) ** 2

    def _pointer_angle(self, pos):
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        return math.degrees(math.atan2(dy, dx)) + 90.0

    def is_visible(self):
        return True

    def _now_ms(self, now_ms):
        return pg.time.get_ticks() if now_ms is None else now_ms

    def handle_press(self, pos, now_ms=None):
        if not self._in_drum(pos):
            return False
        self._spinning = False
        self._spin_vel = 0.0
        self._rot_tween = None
        self._drag_active = True
        self._drag_last_pointer_angle = self._pointer_angle(pos)
        self._drag_total_delta = 0.0
        self._drag_last_ms = None
        self._drag_vel = 0.0
        self._drag_vsampled = False
        self._spin_tick_gate.reset()
        return True

    def handle_motion(self, pos, now_ms=None):
        if not self._drag_active:
            return False
        now = self._now_ms(now_ms)
        angle = self._pointer_angle(pos)
        delta = ((angle - self._drag_last_pointer_angle + 180.0) % 360.0) - 180.0
        self._drag_last_pointer_angle = angle
        self._rotation += delta
        self._drag_total_delta += delta
        self._feed_spin_tick(now)
        if self._drag_last_ms is not None:
            dt = (now - self._drag_last_ms) / 1000.0
            if dt > 0:
                inst = delta / dt
                if self._drag_vsampled:
                    self._drag_vel += (inst - self._drag_vel) * DRAG_VELOCITY_EMA_ALPHA
                else:
                    self._drag_vel = inst
                    self._drag_vsampled = True
        self._drag_last_ms = now
        return True

    def handle_release(self, pos, now_ms=None):
        if not self._drag_active:
            return False
        self._drag_active = False
        dragged = abs(self._drag_total_delta) >= DRAG_CLICK_THRESHOLD_DEG
        if dragged:
            vel = self._drag_vel if self._drag_vsampled else 0.0
            vel = max(-DRAG_MAX_VELOCITY_DEG_PER_S, min(vel, DRAG_MAX_VELOCITY_DEG_PER_S))
            self._spinning = True
            self._spin_vel = vel
            self._spin_last_ms = None
            self._spin_tick_gate.reset()
        return dragged

    def handle_scroll(self, pos, notches):
        if self._in_drum(pos):
            self._spinning = True
            self._spin_vel += notches * WHEEL_IMPULSE_DEG_PER_S
            self._spin_last_ms = None
            self._rot_tween = None
            self._spin_tick_gate.reset()
            return True
        if self._in_turret(pos):
            if not self._turret_dead() and notches != 0:
                step = 1 if notches > 0 else -1
                self._select_increment_clamped(self._inc_index + step)
            return True
        return False

    def handle_click(self, pos):
        self._spinning = False
        self._spin_vel = 0.0
        self._drag_active = False
        if self._in_drum(pos):
            self._select_minutes(self._nearest_chamber(pos))
            return True
        if self._turret_dead():
            return False
        for i in range(len(INCREMENTS)):
            if self._turret_label_rect(i).collidepoint(pos):
                self._select_increment(i)
                return True
        if self._in_turret(pos):
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
        self._emit_ratchet()
        self._changed()

    def _select_increment_clamped(self, index):
        index = max(0, min(len(INCREMENTS) - 1, index))
        if index == self._inc_index:
            return
        self._select_increment(index)

    def _changed(self):
        if self._on_change is not None:
            self._on_change()

    def _emit_tick(self):
        if self._on_tick is not None:
            self._on_tick()

    def _emit_ratchet(self):
        if self._on_ratchet is not None:
            self._on_ratchet()

    def _feed_spin_tick(self, now):
        idx = round(-self._rotation / CHAMBER_STEP_DEG)
        self._spin_tick_gate.feed((idx % 100) / 100.0, now)

    def _settle_from_spin(self):
        index = round(-self._rotation / CHAMBER_STEP_DEG) % CHAMBER_COUNT
        base_target = -index * CHAMBER_STEP_DEG
        delta = ((base_target - self._rotation + 180.0) % 360.0) - 180.0
        self._rot_start = self._rotation
        self._rot_target = self._rotation + delta
        self._rot_steps = int(round(abs(delta) / CHAMBER_STEP_DEG))
        self._rot_ticks = 0
        self._rot_tween = Tween(self._rotation, self._rot_target, SPIN_SETTLE_MS, self._now)
        changed = index != self._min_index
        self._min_index = index
        if self.selected_minutes is None:
            self._inc_index = 0
            self._turret_angle = TURRET_BASE_DEG
            self._turret_tween = None
        if changed:
            self._changed()

    def update(self, now):
        self._now = now
        if self._spinning:
            if self._spin_last_ms is None:
                self._spin_last_ms = now
            dt = min(max(0.0, (now - self._spin_last_ms) / 1000.0), SPIN_MAX_DT)
            self._spin_last_ms = now
            self._rotation += self._spin_vel * dt
            self._feed_spin_tick(now)
            self._spin_vel *= math.exp(-dt / SPIN_FRICTION_TAU)
            if abs(self._spin_vel) < SPIN_STOP_DEG_PER_S:
                self._spinning = False
                self._spin_vel = 0.0
                self._settle_from_spin()
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
                self._seat_pop_tween = Tween(SEAT_POP_SCALE, 1.0, SEAT_POP_MS, now)
                self._seat_pop_index = self._min_index
        if self._seat_pop_tween is not None and self._seat_pop_tween.done(now):
            self._seat_pop_tween = None
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
        rotation = _quantize(self._rotation, DRUM_ANGLE_QUANT_DEG)
        key = (size, rotation, self._min_index)

        def build():
            return supersample((size, size), render)

        def render(surf, k):
            c = surf.get_width() / 2.0
            r = self._radius * k
            lw = max(int(1 * k), 1)
            pg.draw.circle(surf, pg.Color(Colors.surface_active), (c, c), r)
            pg.draw.circle(surf, pg.Color(Colors.dial_border), (c, c), r, lw)
            for i in range(CHAMBER_COUNT):
                sx, sy = _pt(c, c, r * SCALLOP_RING_FRAC,
                             (i + 0.5) * CHAMBER_STEP_DEG + rotation)
                pg.draw.circle(surf, (0, 0, 0, 0), (sx, sy), r * SCALLOP_RADIUS_FRAC)
            pg.draw.polygon(surf, pg.Color(Colors.dial_star),
                            _star_points(c, c, r * STAR_RADIUS_FRAC,
                                         r * STAR_RADIUS_FRAC * STAR_INNER_FRAC, rotation))
            for i in range(CHAMBER_COUNT):
                cx, cy = _pt(c, c, r * CHAMBER_RING_FRAC, i * CHAMBER_STEP_DEG + rotation)
                cr = r * CHAMBER_RADIUS_FRAC
                sel = i == self._min_index
                pg.draw.circle(surf, pg.Color(Colors.battle_bg), (cx, cy), cr)
                border = Colors.accent if sel else Colors.dial_border
                pg.draw.circle(surf, pg.Color(border), (cx, cy), cr,
                               max(int((2.0 if sel else 1.0) * k), 1))
            pg.draw.circle(surf, pg.Color(Colors.battle_bg), (c, c), r * PIN_RADIUS_FRAC)
            pg.draw.circle(surf, pg.Color(Colors.dial_border), (c, c), r * PIN_RADIUS_FRAC, lw)
            base_y = c - r * HAMMER_BASE_FRAC
            base_half = r * HAMMER_HALF_FRAC
            pg.draw.polygon(surf, pg.Color(Colors.accent),
                            [(c, c - r * HAMMER_TIP_FRAC),
                             (c - base_half, base_y), (c + base_half, base_y)])

        dial = _bounded_set(_DRUM_CACHE, key, build, DRUM_CACHE_CAP)
        top = (int(self._drum_center[0] - size / 2), int(self._drum_center[1] - size / 2))
        surface.blit(dial, top)
        for i in range(CHAMBER_COUNT):
            cx, cy = self.chamber_center(i)
            sel = i == self._min_index
            label = CHAMBERS[i][1]
            color = Colors.text if sel else Colors.text_dim
            if label == "∞":
                glyph = infinity_surface(self._chamber_font.get_height() * 0.8, color)
            else:
                glyph = render_text(self._chamber_font, label, color)
            scale = 1.0
            if self._seat_pop_tween is not None and i == self._seat_pop_index:
                scale = self._seat_pop_tween.value(self._now)
            self._blit_chamber_glyph(surface, glyph, cx, cy, scale)

    def _blit_chamber_glyph(self, surface, glyph, cx, cy, scale):
        if scale != 1.0:
            w = max(round(glyph.get_width() * scale), 1)
            h = max(round(glyph.get_height() * scale), 1)
            glyph = pg.transform.smoothscale(glyph, (w, h))
        surface.blit(glyph, (cx - glyph.get_width() / 2, cy - glyph.get_height() / 2))

    def _draw_turret_dial(self, surface):
        tr = self._turret_radius
        size = self._footprint(tr)
        dead = self._turret_dead()
        key = (size, dead)

        def build():
            dial = supersample((size, size), render)
            if dead:
                dial.set_alpha(TURRET_DEAD_ALPHA)
            return dial

        def render(surf, k):
            c = surf.get_width() / 2.0
            r = tr * k
            lw = max(int(1 * k), 1)
            ring_r = r * TURRET_TICK_RING_FRAC
            for t in range(TURRET_TICK_COUNT):
                deg = t * 360.0 / TURRET_TICK_COUNT
                pg.draw.line(surf, pg.Color(Colors.dial_border),
                             _pt(c, c, ring_r - r * TURRET_TICK_MINOR_FRAC, deg),
                             _pt(c, c, ring_r, deg), lw)
            for i in range(len(INCREMENTS)):
                deg = TURRET_BASE_DEG + i * TURRET_SPREAD_DEG
                pg.draw.line(surf, pg.Color(Colors.border_strong),
                             _pt(c, c, ring_r - r * TURRET_TICK_MAJOR_FRAC, deg),
                             _pt(c, c, ring_r, deg), max(lw, int(2 * k)))
            knob_r = r * TURRET_KNOB_FRAC
            knurl = r * TURRET_KNURL_LEN_FRAC
            for t in range(TURRET_KNURL_TEETH):
                deg = t * 360.0 / TURRET_KNURL_TEETH
                pg.draw.line(surf, pg.Color(Colors.dial_border),
                             _pt(c, c, knob_r - knurl * 0.5, deg),
                             _pt(c, c, knob_r + knurl * 0.5, deg), lw)
            pg.draw.circle(surf, pg.Color(Colors.surface_raised), (c, c), knob_r)
            pg.draw.circle(surf, pg.Color(Colors.dial_border), (c, c), knob_r, lw)

        dial = memoized_surface(_TURRET_DIAL_CACHE, key, build)
        cx, cy = self._turret_center
        surface.blit(dial, (cx - size / 2, cy - size / 2))

    def _draw_turret_needle(self, surface):
        if self._turret_dead():
            return
        tr = self._turret_radius
        size = self._footprint(tr)
        angle = _quantize(self._turret_angle, NEEDLE_ANGLE_QUANT_DEG)
        key = (size, angle)

        def build():
            return supersample((size, size), render)

        def render(surf, k):
            c = surf.get_width() / 2.0
            r = tr * k
            rad = math.radians(angle - 90.0)
            dirx, diry = math.cos(rad), math.sin(rad)
            perpx, perpy = -diry, dirx
            hw = r * TURRET_NEEDLE_BASE_HALF_FRAC
            base_x = c + r * TURRET_NEEDLE_INNER_FRAC * dirx
            base_y = c + r * TURRET_NEEDLE_INNER_FRAC * diry
            tipx = c + r * TURRET_NEEDLE_FRAC * dirx
            tipy = c + r * TURRET_NEEDLE_FRAC * diry
            pg.draw.polygon(surf, pg.Color(Colors.amber),
                            [(base_x + perpx * hw, base_y + perpy * hw),
                             (base_x - perpx * hw, base_y - perpy * hw), (tipx, tipy)])

        needle = _bounded_set(_TURRET_NEEDLE_CACHE, key, build, NEEDLE_CACHE_CAP)
        cx, cy = self._turret_center
        surface.blit(needle, (cx - size / 2, cy - size / 2))

    def _draw_turret_labels(self, surface):
        dead = self._turret_dead()
        tr = self._turret_radius
        for i, inc in enumerate(INCREMENTS):
            rect = self._turret_label_rect(i)
            sel = i == self._inc_index and not dead
            if sel:
                bw = max(int(tr * 0.04), 1)
                d = max(int(round(rect.width)), 1)
                bubble = _turret_bubble_surface(d, bw)
                surface.blit(bubble, (rect.centerx - d / 2, rect.centery - d / 2))
            color = Colors.amber_hi if sel else (
                Colors.text_muted if dead else Colors.text_dim)
            surf = render_text(self._label_font, str(inc), color)
            surface.blit(surf, (rect.centerx - surf.get_width() / 2,
                                rect.centery - surf.get_height() / 2))

    def _draw_turret(self, surface):
        self._draw_turret_dial(surface)
        self._draw_turret_needle(surface)
        self._draw_turret_labels(surface)
        cx, cy = self._turret_center
        dead = self._turret_dead()
        value = render_text(self._value_font, f"+{self.selected_increment}s",
                            Colors.text_muted if dead else Colors.amber_hi)
        surface.blit(value, (cx - value.get_width() / 2, cy - value.get_height() / 2))
        caption = render_text(self._caption_font, "INCREMENT · CLICK TO RATCHET",
                              Colors.text_muted)
        cap_y = cy + self._turret_radius * TURRET_CAPTION_Y_FRAC
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
