import math
import random
from collections.abc import Callable
from typing import Any, cast

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
SPIN_FRICTION_TAU = 0.85
WHEEL_IMPULSE_DEG_PER_S = 150.0
SPIN_STOP_DEG_PER_S = 12.0
SPIN_MAX_DT = 0.05

ROULETTE_MIN_DEG_PER_S = 640.0
ROULETTE_MAX_DEG_PER_S = 1700.0
TURRET_ROULETTE_MS = 700

DRAG_CLICK_THRESHOLD_DEG = 3.5
DRAG_VELOCITY_EMA_ALPHA = 0.35
DRAG_MAX_VELOCITY_DEG_PER_S = 2800.0

SEAT_POP_SCALE = 1.18
SEAT_POP_MS = 150

DISC_MARGIN_FRAC = 0.34
CHAMBER_RING_FRAC = 0.58
CHAMBER_RADIUS_FRAC = 0.25
DRUM_GRAB_RADIUS_FRAC = 1.18
HUB_HIT_RADIUS_FRAC = 0.32
HUB_RING_RADIUS_FRAC = 0.085
HUB_RING_PULSE_MS = 1400
HUB_RING_ALPHA_LO = 50
HUB_RING_ALPHA_HI = 160
SCALLOP_RING_FRAC = 1.05
SCALLOP_RADIUS_FRAC = 0.23
STAR_RADIUS_FRAC = 0.15
STAR_INNER_FRAC = 0.44
PIN_RADIUS_FRAC = 0.077
HAMMER_TIP_FRAC = 1.06
HAMMER_BASE_FRAC = 1.28
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


def _turret_bubble_surface(diameter: int, ring_w: int) -> pg.Surface:
    """
    The amber ring that marks the chosen increment on the turret's label ring.
    It is drawn once per size and shared, like every other hand-drawn piece of
    the picker

    :param diameter: outer width and height of the bubble in pixels
    :param ring_w: thickness of the ring in pixels at final size
    :returns: the bubble surface, cached and shared by size
    """
    def build() -> pg.Surface:
        """
        Draw the bubble oversized and shrink it down on a cache miss, which is
        how the picker gets smooth edges out of pygame

        :returns: the freshly drawn bubble surface
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the filled disc and its ring at the oversampled size, with
            every length multiplied by the oversampling factor

            :param surf: the oversized surface being painted
            :param k: how many times bigger than final this surface is
            """
            r = surf.get_width() / 2.0
            pg.draw.circle(surf, pg.Color(Colors.surface_raised), (r, r), r)
            pg.draw.circle(surf, pg.Color(Colors.amber), (r, r), r, max(int(ring_w * k), 1))
        return supersample((diameter, diameter), render, scale=8)
    return cast(pg.Surface, memoized_surface(_TURRET_BUBBLE_CACHE, (diameter, ring_w), build))


def _quantize(value: float, step: float) -> float:
    """
    Round an angle onto a coarse grid so that spinning parts reuse a handful of
    cached pictures instead of demanding a new one every frame. Half a degree
    of rounding is invisible in motion and is what keeps the drum cheap

    :param value: the angle in degrees to round
    :param step: grid spacing in degrees to round onto
    :returns: the angle snapped to the nearest step
    """
    return round(value / step) * step


def _bounded_set(cache: dict[Any, Any], key: Any, build: Callable[[], Any],
                 cap: int) -> Any:
    """
    Cache a drawable that comes in many near-identical versions -- one per
    quantized angle -- keeping only the most recently used few. The plain
    surface cache would grow without limit here, since a full turn of the drum
    visits hundreds of angles

    :param cache: the cache dict to store the entry in
    :param key: hashable identity of the drawable, angle included
    :param build: makes the value on a miss
    :param cap: how many entries to keep before dropping the oldest used one
    :returns: the cached value for that key
    """
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


def _pt(cx: float, cy: float, radius: float, deg: float) -> tuple[float, float]:
    """
    Find the point at an angle and distance from a centre, the one place this
    module turns dial angles into pixels. Zero degrees points straight up and
    angles grow clockwise, so the code reads like a clock face

    :param cx: centre x in the target surface's pixels
    :param cy: centre y in the target surface's pixels
    :param radius: distance from the centre in pixels
    :param deg: angle in degrees, 0 straight up and growing clockwise
    :returns: the point as x and y in the same pixel space
    """
    angle = math.radians(deg - 90.0)
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def _star_points(cx: float, cy: float, outer: float, inner: float,
                 rotation: float) -> list[tuple[float, float]]:
    """
    Build the outline of the star at the middle of the drum, which has one
    point per chamber so it turns with them and sells the revolver

    :param cx: centre x in the target surface's pixels
    :param cy: centre y in the target surface's pixels
    :param outer: distance to the tips of the star in pixels
    :param inner: distance to the notches between the tips in pixels
    :param rotation: the drum's current angle in degrees
    :returns: the polygon points, alternating tip and notch
    """
    points = []
    for i in range(CHAMBER_COUNT):
        points.append(_pt(cx, cy, outer, rotation + i * CHAMBER_STEP_DEG))
        points.append(_pt(cx, cy, inner, rotation + (i + 0.5) * CHAMBER_STEP_DEG))
    return points


class TimePicker:
    """
    The revolver the player sets the clock with, and the whole content of the
    Play panel's time popover: a drum whose chambers are the minute choices, a
    turret dial for the increment, and a hub in the middle of the drum that
    spins both at random. The minute drum can be clicked, flicked, dragged or
    scrolled, and it always settles on a chamber.

    Every timing and proportion in it is a named constant at the top of this
    file -- rotation and swing durations, spin friction, roulette speeds, and
    the radius fractions each part is drawn at. They are the approved feel of
    the widget and the only place to retune it: nothing here re-derives them
    from the geometry, and everything is anchored to the dial radius so the
    picker keeps its feel at any size
    """

    def __init__(self, on_change: Callable[[], None] | None = None,
                 on_tick: Callable[[], None] | None = None,
                 on_ratchet: Callable[[], None] | None = None) -> None:
        """
        Build the picker on ten minutes plus five seconds, the default the Play
        panel then overrides with the player's stored settings. Callbacks are
        how it talks to the panel around it -- it never reaches back out itself

        :param on_change: run whenever the chosen time control settles on a new
            value, which is how the Play panel learns about it
        :param on_tick: run on each chamber the drum passes, the revolver click
        :param on_ratchet: run on each increment step the turret swings through
        """
        self._on_change = on_change
        self._on_tick = on_tick
        self._on_ratchet = on_ratchet
        self._min_index = 3
        self._inc_index = 2
        self.rect = pg.Rect(0, 0, 0, 0)
        self._drum_center: tuple[float, float] = (0, 0)
        self._turret_center: tuple[float, float] = (0, 0)
        self._radius = 1.0
        self._turret_radius = 1.0
        self._readout_rect = pg.Rect(0, 0, 0, 0)
        self._rotation = -self._min_index * CHAMBER_STEP_DEG
        self._rot_tween: Tween | None = None
        self._rot_start = self._rotation
        self._rot_target = self._rotation
        self._rot_steps = 0
        self._rot_ticks = 0
        self._spinning = False
        self._spin_vel = 0.0
        self._spin_last_ms: int | None = None
        self._spin_tick_gate = TickGate(on_tick)
        self._drag_active = False
        self._drag_last_pointer_angle = 0.0
        self._drag_total_delta = 0.0
        self._drag_last_ms: int | None = None
        self._drag_vel = 0.0
        self._drag_vsampled = False
        self._seat_pop_tween: Tween | None = None
        self._seat_pop_index = self._min_index
        self._turret_angle = TURRET_BASE_DEG + self._inc_index * TURRET_SPREAD_DEG
        self._turret_tween: Tween | None = None
        self._turret_pending_index = self._inc_index
        self._turret_sweep_start = self._turret_angle
        self._turret_sweep_steps = 0
        self._turret_sweep_ticks = 0
        self._now = 0
        self._hub_ring: pg.Surface | None = None
        self._label_font = get_mono_font(11, bold=True)
        self._value_font = get_display_font(18)
        self._chamber_font = get_mono_font(13, bold=True)
        self._caption_font = get_mono_font(9, bold=True)
        self._readout_label_font = get_mono_font(9, bold=True)
        self._readout_value_font = get_mono_font(15, bold=True)

    @property
    def selected_minutes(self) -> int | None:
        """
        The minutes on the clock the drum is currently seated on, one of the
        game's offered time controls

        :returns: minutes per side, or None for the untimed chamber
        """
        return CHAMBERS[self._min_index][0]

    @property
    def selected_increment(self) -> int:
        """
        The seconds added after each move that the turret is pointing at. An
        untimed game reports no increment, because there is no clock to add to

        :returns: increment in seconds, always 0 for an untimed game
        """
        if self.selected_minutes is None:
            return 0
        return INCREMENTS[self._inc_index]

    def set_selection(self, minutes: int | None, increment: int) -> None:
        """
        Put the picker on a given time control with no animation at all, which
        is what the Play panel does as it opens the popover so the drum and the
        turret come up already showing the current choice. Everything in flight
        -- spins, drags and swings -- is dropped

        :param minutes: minutes per side, or None for the untimed chamber; a
            value the drum does not carry leaves the chamber where it was
        :param increment: seconds added per move, ignored unless it is one of
            the turret's own values
        """
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
        self._turret_pending_index = self._inc_index
        self._turret_sweep_steps = 0

    def _chamber_index_for(self, minutes: int | None) -> int:
        """
        Find which chamber carries a given time control, so a stored setting
        can be mapped onto the drum

        :param minutes: minutes per side, or None for the untimed chamber
        :returns: index of that chamber, or the current one when the drum has
            no chamber for that value
        """
        return next((i for i, (value, _) in enumerate(CHAMBERS) if value == minutes),
                    self._min_index)

    def readout_text(self) -> str:
        """
        Spell the chosen time control the way the strip under the dials prints
        it, as minutes plus increment

        :returns: the reading as text; an untimed game reads as the infinity
            sign, which the strip draws as a shape instead
        """
        if self.selected_minutes is None:
            return "∞"
        return f"{self.selected_minutes}+{self.selected_increment}"

    def set_rect(self, rect: pg.Rect) -> None:
        """
        Take the box the popover has room for and size the whole picker into
        it: the drum in the left half, the turret in the right, the reading
        along the bottom. Every part is derived from one radius, so the widget
        keeps its proportions at any size

        :param rect: the area the picker may use, in window pixels
        """
        rect = pg.Rect(rect)
        resized = rect.size != self.rect.size
        self.rect = rect
        readout_h = max(int(rect.height * 0.16), 1)
        dial_h = rect.height - readout_h
        half = rect.width / 2.0
        self._radius = max(min(half, dial_h) / (2.0 * (1.0 + DISC_MARGIN_FRAC)), 8.0)
        self._turret_radius = self._radius * TURRET_SIZE_FRAC
        cy = rect.y + dial_h / 2.0
        self._drum_center = (rect.x + half / 2.0, cy)
        self._turret_center = (rect.right - half / 2.0, cy)
        self._readout_rect = pg.Rect(rect.x, rect.bottom - readout_h, rect.width, readout_h)
        if resized:
            self._fit_fonts()

    def _fit_fonts(self) -> None:
        """
        Rebuild every font in the picker against the current dial radius, so
        the chamber numbers, the turret labels and the reading all keep their
        proportion to the dials rather than to the window
        """
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

    def _turret_dead(self) -> bool:
        """
        Whether the increment dial means anything right now. It does not for an
        untimed game, and everything about the turret -- input, needle, colour
        -- follows this one answer

        :returns: True while the drum is on the untimed chamber
        """
        return self.selected_minutes is None

    def chamber_center(self, index: int) -> tuple[float, float]:
        """
        Where a chamber sits on screen at this instant, which moves with every
        degree the drum turns. Both hit testing and the numbers painted over
        the drum are placed from here, so they can never disagree

        :param index: chamber index into the offered time controls
        :returns: the chamber's centre in window pixels
        """
        return _pt(self._drum_center[0], self._drum_center[1],
                   self._radius * CHAMBER_RING_FRAC,
                   index * CHAMBER_STEP_DEG + self._rotation)

    def _nearest_chamber(self, pos: tuple[int, int]) -> int:
        """
        Pick the chamber closest to where the player clicked, so anywhere on
        the drum face selects something rather than only the small circles

        :param pos: click position in window pixels
        :returns: index of the nearest chamber
        """
        def sq_dist(i: int) -> float:
            """
            How far a chamber is from the click, squared -- comparing squares
            avoids a square root that would not change the answer

            :param i: chamber index to measure
            :returns: squared distance in pixels
            """
            cx, cy = self.chamber_center(i)
            return (cx - pos[0]) ** 2 + (cy - pos[1]) ** 2
        return min(range(CHAMBER_COUNT), key=sq_dist)

    def _turret_label_rect(self, i: int) -> pg.Rect:
        """
        Where one increment label sits around the turret, used both to draw the
        label and to catch a click straight on it

        :param i: index into the offered increments
        :returns: the label's box in window pixels
        """
        cx, cy = _pt(self._turret_center[0], self._turret_center[1],
                     self._turret_radius * TURRET_LABEL_RING_FRAC,
                     TURRET_BASE_DEG + i * TURRET_SPREAD_DEG)
        side = self._turret_radius * TURRET_BUBBLE_R_FRAC * 2
        return pg.Rect(cx - side / 2, cy - side / 2, side, side)

    def _in_drum(self, pos: tuple[int, int]) -> bool:
        """
        Whether a point is on the drum face, the area where a click seats a
        chamber

        :param pos: point in window pixels
        :returns: True when the point is on the drum
        """
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        return dx * dx + dy * dy <= (self._radius * 1.08) ** 2

    def _in_drum_grab(self, pos: tuple[int, int]) -> bool:
        """
        Whether a point is close enough to grab the drum and turn it. The grab
        area reaches past the drum's edge, so a flick started just outside it
        still takes hold

        :param pos: point in window pixels
        :returns: True when the point can start a drag or take a scroll
        """
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        return dx * dx + dy * dy <= (self._radius * DRUM_GRAB_RADIUS_FRAC) ** 2

    def _in_hub(self, pos: tuple[int, int]) -> bool:
        """
        Whether a point is on the pin at the middle of the drum, the button
        that spins both dials at random

        :param pos: point in window pixels
        :returns: True when the point is on the hub
        """
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        return dx * dx + dy * dy <= (self._radius * HUB_HIT_RADIUS_FRAC) ** 2

    def _in_turret(self, pos: tuple[int, int]) -> bool:
        """
        Whether a point is on the increment dial, which takes clicks and the
        wheel anywhere on its face

        :param pos: point in window pixels
        :returns: True when the point is on the turret
        """
        dx = pos[0] - self._turret_center[0]
        dy = pos[1] - self._turret_center[1]
        return dx * dx + dy * dy <= (self._turret_radius * 1.05) ** 2

    def _pointer_angle(self, pos: tuple[int, int]) -> float:
        """
        The angle from the drum's centre out to the cursor, which is what a
        drag turns the drum by

        :param pos: cursor position in window pixels
        :returns: angle in degrees in the same frame the drum's rotation uses
        """
        dx = pos[0] - self._drum_center[0]
        dy = pos[1] - self._drum_center[1]
        return math.degrees(math.atan2(dy, dx)) + 90.0

    def is_visible(self) -> bool:
        """
        Part of the app's scrollable contract: the picker is only ever offered
        to the wheel while its popover is open, so by the time anything asks it
        is on screen by definition

        :returns: True always
        """
        return True

    def _now_ms(self, now_ms: int | None) -> int:
        """
        Settle on the timestamp an input happened at, reading the clock when
        the caller did not say. Input handlers accept a time so a test can
        drive a drag at whatever pace it likes

        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock now
        :returns: the timestamp to use in milliseconds
        """
        return pg.time.get_ticks() if now_ms is None else now_ms

    def handle_press(self, pos: tuple[int, int], now_ms: int | None = None) -> bool:
        """
        Take hold of the drum where the player pressed, ending any spin or
        settle already running so the drum answers the hand immediately. Taking
        the press is what makes the following motion a rotation drag rather
        than a click

        :param pos: press position in window pixels
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock; unused here, kept so every input handler is called alike
        :returns: True when the drum took the press
        """
        if not self._in_drum_grab(pos):
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

    def handle_motion(self, pos: tuple[int, int], now_ms: int | None = None) -> bool:
        """
        Turn the drum by however far the cursor swept around it since the last
        report, clicking as chambers pass. The speed of the sweep is smoothed
        as it goes, and that is what a release throws the drum with

        :param pos: cursor position in window pixels
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock; it is what the speed is measured against
        :returns: True while a drag is in progress
        """
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

    def handle_release(self, pos: tuple[int, int], now_ms: int | None = None) -> bool:
        """
        Let the drum go. A hand that actually moved throws it into a free spin
        at the speed it was travelling, which friction later brings to rest on
        a chamber; a hand that barely moved counts as a click instead, and the
        answer here is what tells the app's input router which it was

        :param pos: release position in window pixels, not needed because the
            throw comes from the sweep and not from where it ended
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock; unused here, kept so every input handler is called alike
        :returns: True when the drum was really dragged, False when the press
            should be treated as a plain click
        """
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

    def handle_scroll(self, pos: tuple[int, int], notches: int) -> bool:
        """
        Answer the mouse wheel: over the drum each notch shoves it round a
        little further, so repeated notches build a real spin, and over the
        turret each notch steps the increment by one. Both dials swallow the
        wheel, which stops it reaching the menu behind the popover

        :param pos: cursor position in window pixels
        :param notches: wheel steps this event carried, negative downwards
        :returns: True when either dial took the wheel
        """
        if self._in_drum_grab(pos):
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

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Answer a click anywhere on the picker: the hub spins both dials at
        random, the drum seats the nearest chamber, an increment label picks
        that increment and the turret's face steps to the next one. Anything
        in motion is stopped first, so a click always wins over a spin

        :param pos: click position in window pixels
        :returns: True when part of the picker took the click
        """
        self._spinning = False
        self._spin_vel = 0.0
        self._drag_active = False
        if self._in_hub(pos):
            self._start_roulette()
            return True
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

    def _select_minutes(self, index: int) -> None:
        """
        Seat a chamber: the choice counts from this moment, and the drum then
        turns the short way round to bring it under the hammer, clicking once
        per chamber it passes. Landing on the untimed chamber kills the
        increment with it

        :param index: chamber index to seat
        """
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
            self._deaden_turret()
        self._changed()

    def _select_increment(self, index: int) -> None:
        """
        Pick an increment: it counts at once and the needle swings across to
        it, with one ratchet sound for the move

        :param index: index into the offered increments
        """
        self._inc_index = index
        self._turret_pending_index = index
        self._turret_sweep_steps = 0
        self._turret_tween = Tween(
            self._turret_angle, TURRET_BASE_DEG + index * TURRET_SPREAD_DEG,
            TURRET_SWING_MS, self._now)
        self._emit_ratchet()
        self._changed()

    def _deaden_turret(self) -> None:
        """
        Park the increment dial on zero and stop it answering anything, because
        an untimed game has no clock to add seconds to. The turret is drawn
        faded and needle-less while it is in this state
        """
        self._inc_index = 0
        self._turret_pending_index = 0
        self._turret_sweep_steps = 0
        self._turret_angle = TURRET_BASE_DEG
        self._turret_tween = None

    def _start_roulette(self) -> None:
        """
        Let the hub choose the whole time control: the drum is thrown into a
        fast spin and the turret sweeps to a random increment, so one press
        gives the player a game they did not pick
        """
        self._start_drum_roulette()
        self._start_turret_roulette()

    def _start_drum_roulette(self) -> None:
        """
        Throw the drum into a hard spin in a random direction, fast enough to
        take several turns before friction settles it on whichever chamber it
        happens to reach
        """
        self._spinning = True
        self._spin_vel = random.choice((-1.0, 1.0)) * random.uniform(
            ROULETTE_MIN_DEG_PER_S, ROULETTE_MAX_DEG_PER_S)
        self._spin_last_ms = None
        self._rot_tween = None
        self._spin_tick_gate.reset()

    def _start_turret_roulette(self) -> None:
        """
        Send the needle sweeping to a randomly chosen increment the long way
        round, at least one full turn, ratcheting at every increment it passes.
        The choice is only adopted when the sweep settles, so the reading does
        not jump ahead of the needle
        """
        index = random.randrange(len(INCREMENTS))
        direction = random.choice((-1.0, 1.0))
        base = TURRET_BASE_DEG + index * TURRET_SPREAD_DEG
        start = self._turret_angle
        travel = ((base - start) * direction) % 360.0 + 360.0
        self._turret_pending_index = index
        self._turret_sweep_start = start
        self._turret_sweep_steps = max(int(round(travel / TURRET_SPREAD_DEG)), 1)
        self._turret_sweep_ticks = 0
        self._turret_tween = Tween(start, start + direction * travel,
                                   TURRET_ROULETTE_MS, self._now)

    def _settle_turret_roulette(self) -> None:
        """
        Adopt the increment the sweep was heading for once it finishes and park
        the needle exactly on it. The Play panel is only told when the value
        really did change, so an unchanged spin is silent
        """
        self._turret_sweep_steps = 0
        changed = self._turret_pending_index != self._inc_index
        self._inc_index = self._turret_pending_index
        self._turret_angle = TURRET_BASE_DEG + self._inc_index * TURRET_SPREAD_DEG
        if changed:
            self._changed()

    def _select_increment_clamped(self, index: int) -> None:
        """
        Step the increment by wheel, stopping at the ends of the list rather
        than wrapping, so scrolling feels like a detented dial

        :param index: index the wheel is aiming at, pulled back into range
        """
        index = max(0, min(len(INCREMENTS) - 1, index))
        if index == self._inc_index:
            return
        self._select_increment(index)

    def _changed(self) -> None:
        """
        Tell the Play panel the chosen time control has moved on, the picker's
        only way of reporting a choice
        """
        if self._on_change is not None:
            self._on_change()

    def _emit_tick(self) -> None:
        """
        Fire the revolver click that marks one chamber going past
        """
        if self._on_tick is not None:
            self._on_tick()

    def _emit_ratchet(self) -> None:
        """
        Fire the ratchet the turret makes as it steps through an increment
        """
        if self._on_ratchet is not None:
            self._on_ratchet()

    def _feed_spin_tick(self, now: int) -> None:
        """
        Click the drum while it is being dragged or is spinning freely. The
        chamber the drum is nearest is folded into the gate's own 0.0 to 1.0
        range, so a click fires as each new chamber comes up and a wild spin
        cannot machine-gun the sound

        :param now: pygame tick count in milliseconds for this step
        """
        idx = round(-self._rotation / CHAMBER_STEP_DEG)
        self._spin_tick_gate.feed((idx % 100) / 100.0, now)

    def _settle_from_spin(self) -> None:
        """
        Bring a free spin to rest on a real chamber: the nearest one is adopted
        as the choice at once, and the drum eases the last few degrees onto it.
        Stopping on the untimed chamber kills the increment as a click would
        """
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
            self._deaden_turret()
        if changed:
            self._changed()

    def update(self, now: int) -> None:
        """
        Move the picker on one frame: the free spin, the drum's settle, the
        chamber pop and the needle's swing. The Play panel calls this while the
        popover is open and drawing calls it again, so it is written to be safe
        to run more than once for the same moment

        :param now: pygame tick count in milliseconds since pygame init
        """
        self._now = now
        self._update_spin(now)
        self._update_rotation_tween(now)
        self._update_seat_pop(now)
        self._update_turret_tween(now)

    def _update_spin(self, now: int) -> None:
        """
        Carry a free spin forward by the time since the last frame and bleed
        its speed away, clicking as chambers pass. A long stall is capped, so
        the drum cannot jump a quarter turn after the window was dragged; once
        the spin drops below walking pace it settles onto a chamber

        :param now: pygame tick count in milliseconds since pygame init
        """
        if not self._spinning:
            return
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

    def _update_rotation_tween(self, now: int) -> None:
        """
        Drive the drum's eased turn towards a seated chamber, clicking once for
        every chamber it crosses and never more often than it really passes
        them. When it lands, the chosen chamber's number pops as a reward

        :param now: pygame tick count in milliseconds since pygame init
        """
        if self._rot_tween is None:
            return
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

    def _update_seat_pop(self, now: int) -> None:
        """
        Drop the little pop the seated chamber's number makes once it has run,
        so the drawing goes back to the plain glyph

        :param now: pygame tick count in milliseconds since pygame init
        """
        if self._seat_pop_tween is not None and self._seat_pop_tween.done(now):
            self._seat_pop_tween = None

    def _update_turret_tween(self, now: int) -> None:
        """
        Drive the needle, whether it is a short swing to a chosen increment or
        a long roulette sweep, ratcheting at each increment a sweep passes. A
        sweep adopts its value when it lands; a plain swing simply parks the
        needle exactly on the value that was already chosen

        :param now: pygame tick count in milliseconds since pygame init
        """
        if self._turret_tween is None:
            return
        self._turret_angle = self._turret_tween.value(now)
        if self._turret_sweep_steps > 0:
            crossed = min(int(round(abs(self._turret_angle - self._turret_sweep_start)
                                    / TURRET_SPREAD_DEG)), self._turret_sweep_steps)
            while self._turret_sweep_ticks < crossed:
                self._turret_sweep_ticks += 1
                self._emit_ratchet()
        if self._turret_tween.done(now):
            self._turret_tween = None
            if self._turret_sweep_steps > 0:
                self._settle_turret_roulette()
            else:
                self._turret_angle = TURRET_BASE_DEG + self._inc_index * TURRET_SPREAD_DEG

    def draw(self, surface: pg.Surface, now: int) -> None:
        """
        Paint the whole picker -- drum, turret and reading -- onto whatever it
        is given, which is the popover panel normally and an offscreen scratch
        while that popover pops in or out. It steps the animation first, so the
        picker keeps moving even during the pop

        :param surface: surface to draw on, the window or the popover's scratch
        :param now: pygame tick count in milliseconds since pygame init
        """
        self.update(now)
        self._draw_drum(surface)
        self._draw_turret(surface)
        self._draw_readout(surface)

    def _footprint(self, radius: float) -> int:
        """
        How large a surface a dial needs, its own radius plus the margin its
        hammer and scallops stick out into

        :param radius: the dial's radius in pixels
        :returns: side of the square surface to draw it on, in pixels
        """
        return int(round(radius * (1.0 + DISC_MARGIN_FRAC) * 2)) + 2

    def _draw_drum(self, surface: pg.Surface) -> None:
        """
        Paint the minute drum: the cylinder with its scalloped edge, the star,
        the seven chambers with the chosen one ringed, the pin and the hammer
        at the top. The turning body is cached per rounded angle, and only the
        numbers -- which must stay upright and can pop -- are drawn live

        :param surface: surface to draw on, the window or the popover's scratch
        """
        size = self._footprint(self._radius)
        rotation = _quantize(self._rotation, DRUM_ANGLE_QUANT_DEG)
        key = (size, rotation, self._min_index)

        def build() -> pg.Surface:
            """
            Draw the drum body oversized and shrink it on a cache miss

            :returns: the drum body at this angle and size
            """
            return supersample((size, size), render)

        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the whole drum body at the oversampled size, every length
            multiplied by the oversampling factor

            :param surf: the oversized surface being painted
            :param k: how many times bigger than final this surface is
            """
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
        self._draw_hub_ring(surface)
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

    def _draw_hub_ring(self, surface: pg.Surface) -> None:
        """
        Breathe an accent ring around the hub to invite a press on it, which is
        how the player finds the random-time-control button. It is hidden while
        the drum is moving, since the invitation would be a lie mid-spin

        :param surface: surface to draw on, the window or the popover's scratch
        """
        if self._spinning or self._rot_tween is not None:
            return
        ring_r = self._radius * HUB_RING_RADIUS_FRAC
        d = int(round(ring_r * 2)) + 6
        if self._hub_ring is None or self._hub_ring.get_width() != d:

            def render(surf: pg.Surface, k: int) -> None:
                """
                Paint the ring at the oversampled size, its stroke scaled with
                everything else

                :param surf: the oversized surface being painted
                :param k: how many times bigger than final this surface is
                """
                c = surf.get_width() / 2.0
                pg.draw.circle(surf, pg.Color(Colors.accent), (c, c), ring_r * k,
                               max(int(2 * k), 2))
            self._hub_ring = supersample((d, d), render)
        phase = math.sin(self._now * math.tau / HUB_RING_PULSE_MS)
        span = HUB_RING_ALPHA_HI - HUB_RING_ALPHA_LO
        self._hub_ring.set_alpha(int(HUB_RING_ALPHA_LO + span * (0.5 + 0.5 * phase)))
        surface.blit(self._hub_ring, (int(self._drum_center[0] - d / 2),
                                      int(self._drum_center[1] - d / 2)))

    def _blit_chamber_glyph(self, surface: pg.Surface, glyph: pg.Surface, cx: float,
                            cy: float, scale: float) -> None:
        """
        Put a chamber's number on the drum, centred on the chamber and grown
        for a moment when that chamber has just been seated

        :param surface: surface to draw on, the window or the popover's scratch
        :param glyph: the number already rendered, or the drawn infinity sign
        :param cx: chamber centre x in window pixels
        :param cy: chamber centre y in window pixels
        :param scale: size multiplier for the seating pop, 1.0 at rest
        """
        if scale != 1.0:
            w = max(round(glyph.get_width() * scale), 1)
            h = max(round(glyph.get_height() * scale), 1)
            glyph = pg.transform.smoothscale(glyph, (w, h))
        surface.blit(glyph, (cx - glyph.get_width() / 2, cy - glyph.get_height() / 2))

    def _draw_turret_dial(self, surface: pg.Surface) -> None:
        """
        Paint the increment dial's fixed parts: the tick ring, the heavier
        marks at each offered increment and the knurled knob. It never turns,
        so one cached picture per size serves every frame, faded when an
        untimed game has left the dial dead

        :param surface: surface to draw on, the window or the popover's scratch
        """
        tr = self._turret_radius
        size = self._footprint(tr)
        dead = self._turret_dead()
        key = (size, dead)

        def build() -> pg.Surface:
            """
            Draw the dial oversized and shrink it on a cache miss, dimming the
            whole thing when the dial is dead

            :returns: the dial at this size and liveness
            """
            dial = supersample((size, size), render)
            if dead:
                dial.set_alpha(TURRET_DEAD_ALPHA)
            return dial

        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the ticks, the major marks and the knurled knob at the
            oversampled size, every length multiplied by the factor

            :param surf: the oversized surface being painted
            :param k: how many times bigger than final this surface is
            """
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

    def _draw_turret_needle(self, surface: pg.Surface) -> None:
        """
        Paint the amber needle pointing at the chosen increment, the one part
        of the turret that moves. It is cached per rounded angle, and a dead
        dial has no needle at all

        :param surface: surface to draw on, the window or the popover's scratch
        """
        if self._turret_dead():
            return
        tr = self._turret_radius
        size = self._footprint(tr)
        angle = _quantize(self._turret_angle, NEEDLE_ANGLE_QUANT_DEG)
        key = (size, angle)

        def build() -> pg.Surface:
            """
            Draw the needle oversized and shrink it on a cache miss

            :returns: the needle at this angle and size
            """
            return supersample((size, size), render)

        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the needle as a triangle from its wide base out to the tip,
            at the oversampled size

            :param surf: the oversized surface being painted
            :param k: how many times bigger than final this surface is
            """
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

    def _draw_turret_labels(self, surface: pg.Surface) -> None:
        """
        Paint the increment numbers around the turret, the chosen one ringed in
        its amber bubble. These are the boxes a click on a label lands in, so
        what is drawn and what is clickable are one and the same

        :param surface: surface to draw on, the window or the popover's scratch
        """
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

    def _draw_turret(self, surface: pg.Surface) -> None:
        """
        Paint the whole increment side: the dial, the needle, the labels, the
        seconds printed across the middle and the caption telling the player
        the face can be clicked to ratchet through the values

        :param surface: surface to draw on, the window or the popover's scratch
        """
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

    def _draw_readout(self, surface: pg.Surface) -> None:
        """
        Paint the strip along the bottom that spells the whole choice out in
        words, so the player reads the time control rather than deducing it
        from where two dials happen to be pointing

        :param surface: surface to draw on, the window or the popover's scratch
        """
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
