"""Revolver time-control picker: nearest-chamber hit tests, shortest-path drum
rotation with a tick per chamber crossed, the scope-turret ratchet/jump, the
∞ deadening that forces increment 0, the CHAMBERED readout string, and a pixel
pin that the seated chamber wears an accent outline on the owned surface."""

import math

import pygame as pg
import pytest

from tests.conftest import pygame_display
import chessshootout.frontend.menu.time_picker as time_picker
from chessshootout.frontend.menu.time_picker import (
    CHAMBER_RING_FRAC, CHAMBERS, CHAMBER_RADIUS_FRAC, CHAMBER_STEP_DEG,
    DRAG_CLICK_THRESHOLD_DEG, INCREMENTS, ROTATION_MS, ROULETTE_MAX_DEG_PER_S,
    ROULETTE_MIN_DEG_PER_S, HUB_HIT_RADIUS_FRAC, SEAT_POP_MS, SETTLE_MS, TimePicker)
from chessshootout.frontend.visual.colors import Colors


_pygame_init = pygame_display(400, 300)


def _picker(minutes=10, increment=5, on_tick=None):
    p = TimePicker(on_tick=on_tick)
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(minutes, increment)
    return p


def _settle(picker):
    picker.update(ROTATION_MS + SETTLE_MS + 10)


def test_defaults_seed_from_set_selection():
    p = _picker(10, 5)
    assert p.selected_minutes == 10
    assert p.selected_increment == 5


def test_nearest_chamber_hit_selects_that_chamber():
    p = _picker(10, 5)
    for i, (value, _) in enumerate([(1, "1"), (3, "3"), (5, "5"), (10, "10"),
                                    (15, "15"), (30, "30"), (None, "∞")]):
        p.handle_click(p.chamber_center(i))
        _settle(p)
        assert p.selected_minutes == value


def test_click_inside_drum_snaps_to_the_closest_chamber():
    p = _picker(10, 5)
    cx, cy = p.chamber_center(5)
    nudged = (cx + 3, cy - 2)
    assert p.handle_click(nudged) is True
    assert p.selected_minutes == 30


def test_rotation_takes_the_shortest_path():
    p = _picker(1, 5)
    p._select_minutes(6)
    assert abs(p._rot_target - p._rot_start) <= 180.0 + 1e-6
    assert p._rot_steps == 1


def test_tween_settles_at_the_exact_seat_angle():
    p = _picker(1, 5)
    p.handle_click(p.chamber_center(4))
    _settle(p)
    cx, cy = p.chamber_center(4)
    assert cy < p._drum_center[1], "seated chamber sits above center (at the pointer)"
    assert abs(cx - p._drum_center[0]) < 1.0, "and is centered under the top hammer"


def test_one_tick_fires_per_chamber_crossed():
    ticks = []
    p = _picker(10, 5, on_tick=lambda: ticks.append(1))
    p.handle_click(p.chamber_center(0))
    assert p._rot_steps == 3
    for t in range(0, ROTATION_MS + SETTLE_MS + 20, 8):
        p.update(t)
    assert len(ticks) == 3


def test_selecting_the_seated_chamber_is_a_noop_no_ticks():
    ticks = []
    p = _picker(10, 5, on_tick=lambda: ticks.append(1))
    p.handle_click(p.chamber_center(3))
    _settle(p)
    assert ticks == []
    assert p.selected_minutes == 10


def test_turret_knob_ratchets_through_increments():
    p = _picker(10, 5)
    seen = [p.selected_increment]
    for _ in range(len(INCREMENTS)):
        p.handle_click(p._turret_center)
        p.update(400)
        seen.append(p.selected_increment)
    assert seen == [5, 10, 15, 0, 2, 5]


def test_turret_label_click_jumps_to_that_value():
    p = _picker(10, 0)
    target = INCREMENTS.index(15)
    assert p.handle_click(p._turret_label_rect(target).center) is True
    assert p.selected_increment == 15


def test_infinity_deadens_turret_and_forces_zero_increment():
    p = _picker(10, 10)
    p.handle_click(p.chamber_center(6))
    _settle(p)
    assert p.selected_minutes is None
    assert p.selected_increment == 0
    assert p._turret_dead() is True
    before = p._inc_index
    assert p.handle_click(p._turret_center) is False, "the deadened turret ignores clicks"
    assert p._inc_index == before


def test_infinity_default_selection_forces_zero_increment():
    p = _picker(None, 10)
    assert p.selected_minutes is None
    assert p.selected_increment == 0


@pytest.mark.parametrize("minutes, increment, expected", [
    pytest.param(15, 10, "15+10", id="timed"),
    pytest.param(5, 0, "5+0", id="zero_increment"),
    pytest.param(None, 0, "∞", id="infinity"),
])
def test_readout_string(minutes, increment, expected):
    p = _picker(minutes, increment)
    assert p.readout_text() == expected


def _has_accent_on_ring(surface, center, radius):
    accent = pg.Color(Colors.accent)
    for deg in range(0, 360, 6):
        rad = math.radians(deg)
        x = int(center[0] + radius * math.cos(rad))
        y = int(center[1] + radius * math.sin(rad))
        if not surface.get_rect().collidepoint(x, y):
            continue
        r, g, b = surface.get_at((x, y))[:3]
        if r > 170 and abs(g - accent.g) < 70 and b < 110 and r > b:
            return True
    return False


def test_selected_chamber_wears_an_accent_outline():
    surface = pg.Surface((300, 190))
    surface.fill(pg.Color(Colors.surface_raised))
    p = _picker(10, 5)
    _settle(p)
    p.draw(surface, ROTATION_MS + SETTLE_MS + 10)
    center = p.chamber_center(3)
    chamber_r = p._radius * CHAMBER_RADIUS_FRAC
    assert _has_accent_on_ring(surface, center, chamber_r), \
        "the seated chamber's rim must show the accent outline"


def test_update_advances_a_rotation_tween():
    p = _picker(10, 5)
    p.handle_click(p.chamber_center(0))
    start = p._rotation
    p.update((ROTATION_MS + SETTLE_MS) // 2)
    assert p._rotation != start


def test_wheel_over_the_drum_spins_settles_and_selects_once_with_ticks():
    # 2 notches: travel = tau * (v0 - stop) must land BETWEEN chambers, not wrap
    # back onto the start (3 notches did exactly that once SPIN_FRICTION_TAU grew
    # past ~0.8 -- travel is tau-coupled, so pick the impulse from the physics).
    ticks = []
    changes = []
    p = TimePicker(on_change=lambda: changes.append(1), on_tick=lambda: ticks.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    assert p.handle_scroll(p._drum_center, 2) is True
    assert p._spinning is True
    t = 0
    for _ in range(3000):
        t += 16
        p.update(t)
        if not p._spinning and p._rot_tween is None:
            break
    assert p._spinning is False, "momentum decays and the drum settles"
    assert p.selected_minutes in [v for v, _ in CHAMBERS]
    assert len(changes) == 1, "the config change fires exactly once, on settle"
    assert len(ticks) > 0, "the ratchet ticks while spinning"


def test_wheel_off_the_drum_is_ignored():
    p = _picker(10, 5)
    assert p.handle_scroll((2, 2), 1) is False
    assert p._spinning is False


def test_a_click_cancels_an_in_progress_spin():
    p = _picker(10, 5)
    p.handle_scroll(p._drum_center, 4)
    assert p._spinning is True
    p.handle_click(p.chamber_center(2))
    assert p._spinning is False
    _settle(p)
    assert p.selected_minutes == 5


def test_turret_wheel_steps_through_increments_and_clamps_at_the_top():
    p = _picker(10, 5)
    assert p.handle_scroll(p._turret_center, 1) is True
    assert p.selected_increment == 10
    assert p.handle_scroll(p._turret_center, 1) is True
    assert p.selected_increment == 15
    assert p.handle_scroll(p._turret_center, 1) is True
    assert p.selected_increment == 15, "no wraparound past the top step"


def test_turret_wheel_clamps_at_the_bottom():
    p = _picker(10, 0)
    assert p.handle_scroll(p._turret_center, -1) is True
    assert p.selected_increment == 0, "no wraparound past the bottom step"


def test_turret_wheel_direction_matches_up_next_down_previous():
    p = _picker(10, 5)
    p.handle_scroll(p._turret_center, 1)
    assert p.selected_increment == 10, "wheel up steps to the next value"
    p.handle_scroll(p._turret_center, -1)
    assert p.selected_increment == 5, "wheel down steps back to the previous value"


def test_turret_wheel_plays_a_ratchet_through_the_dedicated_callback():
    ticks = []
    ratchets = []
    p = TimePicker(on_tick=lambda: ticks.append(1), on_ratchet=lambda: ratchets.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    p.handle_scroll(p._turret_center, 1)
    assert ratchets == [1]
    assert ticks == [], "the turret ratchet no longer shares the drum's tick callback"


def test_turret_click_and_label_jump_also_fire_the_ratchet_not_the_tick():
    ticks = []
    ratchets = []
    p = TimePicker(on_tick=lambda: ticks.append(1), on_ratchet=lambda: ratchets.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 0)
    p.handle_click(p._turret_center)
    target = INCREMENTS.index(15)
    p.handle_click(p._turret_label_rect(target).center)
    assert ratchets == [1, 1]
    assert ticks == []


def test_drum_rotation_ticks_do_not_fire_the_ratchet_callback():
    ticks = []
    ratchets = []
    p = TimePicker(on_tick=lambda: ticks.append(1), on_ratchet=lambda: ratchets.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    p.handle_click(p.chamber_center(0))
    for t in range(0, ROTATION_MS + SETTLE_MS + 20, 8):
        p.update(t)
    assert len(ticks) == 3
    assert ratchets == []


def test_turret_wheel_ignored_when_dead():
    p = _picker(10, 10)
    p.handle_click(p.chamber_center(6))
    _settle(p)
    assert p._turret_dead() is True
    before = p._inc_index
    assert p.handle_scroll(p._turret_center, 1) is True
    assert p._inc_index == before


def test_seat_pop_tween_fires_once_on_click_settle():
    p = _picker(10, 5)
    p.handle_click(p.chamber_center(0))
    assert p._seat_pop_tween is None
    _settle(p)
    assert p._seat_pop_tween is not None
    assert p._seat_pop_index == p._min_index
    p.update(ROTATION_MS + SETTLE_MS + 10 + SEAT_POP_MS + 10)
    assert p._seat_pop_tween is None, "the pop itself expires and clears"


def test_seat_pop_does_not_fire_for_a_noop_reselect():
    p = _picker(10, 5)
    p.handle_click(p.chamber_center(3))
    _settle(p)
    assert p._seat_pop_tween is None, "no rotation settle happened, so no seating"


def test_seat_pop_also_fires_on_inertia_settle():
    p = TimePicker()
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    p.handle_scroll(p._drum_center, 3)
    t = 0
    for _ in range(3000):
        t += 16
        p.update(t)
        if not p._spinning and p._rot_tween is None:
            break
    assert p._seat_pop_tween is not None


def _angle_pos(picker, deg):
    rad = math.radians(deg - 90.0)
    radius = picker._radius * CHAMBER_RING_FRAC
    cx, cy = picker._drum_center
    return (cx + radius * math.cos(rad), cy + radius * math.sin(rad))


def test_press_in_the_drum_arms_a_drag_and_cancels_any_spin():
    p = _picker(10, 5)
    p.handle_scroll(p._drum_center, 4)
    assert p._spinning is True
    assert p.handle_press(_angle_pos(p, 0), now_ms=0) is True
    assert p._drag_active is True
    assert p._spinning is False


def test_press_outside_the_drum_does_not_arm_a_drag():
    p = _picker(10, 5)
    assert p.handle_press(p._turret_center, now_ms=0) is False
    assert p._drag_active is False


def test_drag_rotates_the_drum_live_and_ticks_chamber_crossings():
    ticks = []
    p = TimePicker(on_tick=lambda: ticks.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    start_rotation = p._rotation
    p.handle_press(_angle_pos(p, 0), now_ms=0)
    for i in range(1, 9):
        p.handle_motion(_angle_pos(p, i * CHAMBER_STEP_DEG * 0.6), now_ms=i * 4)
    assert p._rotation != start_rotation
    assert abs(p._drag_total_delta) >= DRAG_CLICK_THRESHOLD_DEG
    assert len(ticks) > 0, "chamber boundary crossings tick while dragging"


def test_drag_release_above_threshold_flings_settles_and_selects_once():
    changes = []
    p = TimePicker(on_change=lambda: changes.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    p.handle_press(_angle_pos(p, 0), now_ms=0)
    for i in range(1, 8):
        p.handle_motion(_angle_pos(p, i * 23.0), now_ms=i * 5)
    assert p.handle_release(_angle_pos(p, 7 * 23.0), now_ms=40) is True
    assert p._spinning is True
    t = 40
    for _ in range(3000):
        t += 16
        p.update(t)
        if not p._spinning and p._rot_tween is None:
            break
    assert p._spinning is False, "momentum decays and the drum settles"
    assert p.selected_minutes in [v for v, _ in CHAMBERS]
    assert p._min_index != 3, "the fling carried it to a different chamber"
    assert len(changes) == 1, "the config change fires exactly once, on settle"


def test_sub_threshold_drag_release_reports_as_a_click():
    p = _picker(10, 5)
    target = p.chamber_center(5)
    assert p.handle_press(target, now_ms=0) is True
    nudged = (target[0] + 1, target[1])
    p.handle_motion(nudged, now_ms=8)
    assert abs(p._drag_total_delta) < DRAG_CLICK_THRESHOLD_DEG
    dragged = p.handle_release(nudged, now_ms=16)
    assert dragged is False, "a tap-sized drag is reported back as a plain click"
    assert p._spinning is False
    p.handle_click(nudged)
    _settle(p)
    assert p.selected_minutes == 30


def _spy_on_supersample(monkeypatch):
    calls = []
    real = time_picker.supersample

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(time_picker, "supersample", spy)
    return calls


def test_idle_redraw_never_resupersamples(monkeypatch):
    p = _picker(10, 5)
    surface = pg.Surface((300, 190))
    p.draw(surface, 0)
    calls = _spy_on_supersample(monkeypatch)
    p.draw(surface, 16)
    p.draw(surface, 32)
    assert calls == [], "an idle picker blits cached drum/turret layers, no re-render"


def test_idle_redraw_blits_the_same_cached_surface_object():
    p = _picker(10, 5)
    footprint = p._footprint(p._radius)
    key = (footprint, time_picker._quantize(p._rotation, time_picker.DRUM_ANGLE_QUANT_DEG),
           p._min_index)
    surface = pg.Surface((300, 190))
    p.draw(surface, 0)
    first = time_picker._DRUM_CACHE[key]
    p.draw(surface, 16)
    second = time_picker._DRUM_CACHE[key]
    assert first is second, "the same rotation/selection key reuses the same surface"


def test_rotation_change_rebuilds_the_drum_layer(monkeypatch):
    p = _picker(10, 5)
    surface = pg.Surface((300, 190))
    p.draw(surface, 0)
    calls = _spy_on_supersample(monkeypatch)
    p.handle_click(p.chamber_center(0))
    p.draw(surface, 30)
    assert calls, "a rotation/selection change must invalidate the drum cache"


def _spy_fonts(monkeypatch):
    calls = []
    real_mono = time_picker.get_mono_font
    real_display = time_picker.get_display_font

    def mono(*args, **kwargs):
        calls.append("mono")
        return real_mono(*args, **kwargs)

    def display(*args, **kwargs):
        calls.append("display")
        return real_display(*args, **kwargs)

    monkeypatch.setattr(time_picker, "get_mono_font", mono)
    monkeypatch.setattr(time_picker, "get_display_font", display)
    return calls


def test_same_size_move_reuses_fonts_and_still_repositions(monkeypatch):
    p = _picker(10, 5)
    before_center = p._drum_center
    calls = _spy_fonts(monkeypatch)
    p.set_rect(p.rect.move(40, 25))
    assert calls == [], "a position-only set_rect must not rebuild any size-derived font"
    assert p.rect.topleft == (40, 25)
    assert p._drum_center != before_center, "position-only move still repositions the dials"


def test_resize_rebuilds_the_fonts(monkeypatch):
    p = _picker(10, 5)
    calls = _spy_fonts(monkeypatch)
    p.set_rect(pg.Rect(0, 0, 480, 300))
    assert calls, "a genuine size change must rebuild the size-derived fonts"


def test_resize_changes_the_footprint_and_rebuilds(monkeypatch):
    p = _picker(10, 5)
    surface = pg.Surface((300, 190))
    p.draw(surface, 0)
    calls = _spy_on_supersample(monkeypatch)
    p.set_rect(pg.Rect(0, 0, 500, 300))
    surface = pg.Surface((500, 300))
    p.draw(surface, 0)
    assert calls, "a radius change must not reuse a stale-size cache entry"


def test_spin_keeps_rendering_fresh_geometry_every_frame(monkeypatch):
    p = TimePicker()
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    p.handle_scroll(p._drum_center, 4)
    surface = pg.Surface((300, 190))
    calls = _spy_on_supersample(monkeypatch)
    t = 0
    for _ in range(5):
        t += 16
        p.draw(surface, t)
    assert len(calls) >= 3, "a spinning drum keeps rendering, caching must not freeze it"


def test_seat_pop_still_smoothscales_the_cached_glyph(monkeypatch):
    p = _picker(10, 5)
    p.handle_click(p.chamber_center(0))
    _settle(p)
    assert p._seat_pop_tween is not None
    calls = []
    real = pg.transform.smoothscale

    def spy(surf, size):
        calls.append(size)
        return real(surf, size)

    monkeypatch.setattr(pg.transform, "smoothscale", spy)
    surface = pg.Surface((300, 190))
    p.draw(surface, ROTATION_MS + SETTLE_MS + 15)
    assert calls, "the seat-pop tween still smoothscales the cached glyph while it runs"


def test_drum_cache_stays_bounded_while_spinning():
    p = _picker(10, 5)
    surface = pg.Surface((300, 190))
    time_picker._DRUM_CACHE.clear()
    for i in range(time_picker.DRUM_CACHE_CAP + 20):
        p._rotation = i * 1.3
        p._draw_drum(surface)
    assert len(time_picker._DRUM_CACHE) <= time_picker.DRUM_CACHE_CAP


def test_turret_needle_cache_stays_bounded_during_a_swing():
    p = _picker(10, 5)
    surface = pg.Surface((300, 190))
    time_picker._TURRET_NEEDLE_CACHE.clear()
    for i in range(time_picker.NEEDLE_CACHE_CAP + 20):
        p._turret_angle = i * 1.3
        p._draw_turret_needle(surface)
    assert len(time_picker._TURRET_NEEDLE_CACHE) <= time_picker.NEEDLE_CACHE_CAP


# --- extractor-hub roulette ------------------------------------------------
# Pressing the central star hub free-spins the drum at a random speed and the
# physics landing (no pre-picked chamber) is the roll; the turret sweeps to a
# pre-picked increment in parallel. The impulse range is derived from the drum
# friction: travel ~= tau * (v0 - v_stop) with tau = SPIN_FRICTION_TAU (0.85)
# and v_stop = SPIN_STOP_DEG_PER_S (12). ROULETTE_MIN_DEG_PER_S = 640 gives
# 0.85 * (640 - 12) = 533.8 deg ~= 1.48 revs; ROULETTE_MAX_DEG_PER_S = 1700
# gives 0.85 * (1700 - 12) = 1434.8 deg ~= 3.99 revs -- so every roll travels
# between ~1.5 and ~4 full turns of the seven-chamber drum (pitch 360/7).


def _seed_roulette(monkeypatch, speed, direction=1.0, turret_index=0):
    monkeypatch.setattr(time_picker.random, "uniform", lambda a, b: speed)
    monkeypatch.setattr(time_picker.random, "choice",
                        lambda seq: seq[1] if direction > 0 else seq[0])
    monkeypatch.setattr(time_picker.random, "randrange", lambda n: turret_index)


def _run_to_rest(p):
    t = 0
    for _ in range(4000):
        t += 16
        p.update(t)
        if not p._spinning and p._rot_tween is None and p._turret_tween is None:
            break
    return t


def test_hub_click_spins_the_drum_at_a_roulette_speed():
    p = _picker(10, 5)
    assert p.handle_click(p._drum_center) is True
    assert p._spinning is True
    assert ROULETTE_MIN_DEG_PER_S <= abs(p._spin_vel) <= ROULETTE_MAX_DEG_PER_S


def test_hub_click_does_not_select_instantly_or_count_as_a_chamber():
    p = _picker(10, 5)
    before_min, before_inc = p._min_index, p._inc_index
    assert p.handle_click(p._drum_center) is True
    assert p._min_index == before_min, "the roll is undecided until the drum settles"
    assert p._inc_index == before_inc, "the turret result is deferred to its landing"
    assert p._rot_tween is None, "a hub click starts a free spin, not a chamber snap"
    assert p._spinning is True


def test_hub_zone_clears_the_chamber_bores():
    assert HUB_HIT_RADIUS_FRAC < CHAMBER_RING_FRAC - CHAMBER_RADIUS_FRAC, \
        "the hub trigger must not overlap the bore ring at 0.58R"


def test_chamber_click_outside_the_hub_still_selects():
    p = _picker(10, 5)
    p.handle_click(p.chamber_center(6))
    _settle(p)
    assert p.selected_minutes is None


def test_hub_roulette_settles_on_a_valid_chamber_and_notifies_once(monkeypatch):
    changes = []
    p = TimePicker(on_change=lambda: changes.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    _seed_roulette(monkeypatch, ROULETTE_MIN_DEG_PER_S, direction=1.0, turret_index=2)
    p.handle_click(p._drum_center)
    _run_to_rest(p)
    assert p.selected_minutes in [v for v, _ in CHAMBERS]
    assert p._min_index != 3, "the physics carried the drum off the starting chamber"
    assert changes == [1], "the drum settle notifies exactly once"
    assert p._seat_pop_tween is not None, "the landing reuses the seat-pop"


def test_hub_roulette_sweeps_the_turret_with_ratchet_ticks(monkeypatch):
    ratchets = []
    p = TimePicker(on_ratchet=lambda: ratchets.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    _seed_roulette(monkeypatch, ROULETTE_MIN_DEG_PER_S, direction=1.0, turret_index=4)
    p.handle_click(p._drum_center)
    _run_to_rest(p)
    assert p.selected_increment == INCREMENTS[4]
    assert len(ratchets) > 1, "the needle ratchets past several detents on its pass"


def test_hub_roulette_infinity_landing_forces_zero_increment(monkeypatch):
    p = _picker(10, 5)
    _seed_roulette(monkeypatch, 1500.0, direction=1.0, turret_index=4)
    p.handle_click(p._drum_center)
    _run_to_rest(p)
    assert p.selected_minutes is None
    assert p.selected_increment == 0, "infinity deadening wins over the turret roll"
    assert p._inc_index == 0


def test_reclick_mid_spin_restarts_the_roulette_cleanly(monkeypatch):
    changes = []
    p = TimePicker(on_change=lambda: changes.append(1))
    p.set_rect(pg.Rect(0, 0, 300, 190))
    p.set_selection(10, 5)
    _seed_roulette(monkeypatch, ROULETTE_MIN_DEG_PER_S, direction=1.0, turret_index=2)
    p.handle_click(p._drum_center)
    for t in range(16, 200, 16):
        p.update(t)
    assert p._spinning is True
    p.handle_click(p._drum_center)
    assert p._spinning is True
    assert ROULETTE_MIN_DEG_PER_S <= abs(p._spin_vel) <= ROULETTE_MAX_DEG_PER_S
    _run_to_rest(p)
    assert p.selected_minutes in [v for v, _ in CHAMBERS]
    assert changes == [1], "one settle notification survives the restart"


def _fringe_point(p, frac):
    cx, cy = p._drum_center
    return (cx, cy - p._radius * frac)


def test_drum_grab_fringe_drags_and_spins_while_a_click_selects_nothing():
    fringe = _fringe_point(_picker(10, 5), 1.12)
    p = _picker(10, 5)
    assert p.handle_press(fringe, now_ms=0) is True, "the fringe just outside arms a drag"
    assert p._drag_active is True
    p = _picker(10, 5)
    assert p.handle_scroll(fringe, 1) is True, "a wheel over the fringe spins the drum"
    assert p._spinning is True
    p = _picker(10, 5)
    before = p._min_index
    assert p.handle_click(fringe) is False, "a plain click on the fringe selects nothing"
    assert p._min_index == before


def test_idle_hub_wears_a_pulsing_accent_ring():
    """The roulette hub advertises itself: an accent ring pulses at the drum center
    while the drum is idle. Sampled at the pulse peak (now = PULSE/4 -> sin = 1 ->
    alpha HI) on the ring's +x point, well away from the accent hammer at the top."""
    from chessshootout.frontend.menu.time_picker import (
        HUB_RING_PULSE_MS, HUB_RING_RADIUS_FRAC)
    surface = pg.Surface((300, 190))
    surface.fill(pg.Color(Colors.surface_raised))
    p = _picker(10, 5)
    p.draw(surface, HUB_RING_PULSE_MS // 4)
    cx, cy = p._drum_center
    probe = (int(cx + p._radius * HUB_RING_RADIUS_FRAC), int(cy))
    r, g, b = surface.get_at(probe)[:3]
    assert r > 100 and r > b, f"expected accent-tinted ring pixel, got {(r, g, b)}"


def test_spinning_drum_hides_the_hub_ring():
    from chessshootout.frontend.menu.time_picker import (
        HUB_RING_PULSE_MS, HUB_RING_RADIUS_FRAC)
    surface = pg.Surface((300, 190))
    surface.fill(pg.Color(Colors.surface_raised))
    p = _picker(10, 5)
    idle = pg.Surface((300, 190))
    idle.fill(pg.Color(Colors.surface_raised))
    p.draw(idle, HUB_RING_PULSE_MS // 4)
    assert p.handle_scroll(p._drum_center, 2) is True
    p.draw(surface, HUB_RING_PULSE_MS // 4 + 16)
    cx, cy = p._drum_center
    probe = (int(cx + p._radius * HUB_RING_RADIUS_FRAC), int(cy))
    ri, gi, bi = idle.get_at(probe)[:3]
    rs, gs, bs = surface.get_at(probe)[:3]
    assert ri > 100 and ri > bi
    assert not (rs > 100 and rs > bs), "no invitation ring while the drum is in motion"
