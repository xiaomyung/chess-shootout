"""Revolver time-control picker: nearest-chamber hit tests, shortest-path drum
rotation with a tick per chamber crossed, the scope-turret ratchet/jump, the
∞ deadening that forces increment 0, the CHAMBERED readout string, and a pixel
pin that the seated chamber wears an accent outline on the owned surface."""

import math

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.menu.time_picker import (
    CHAMBER_RADIUS_FRAC, INCREMENTS, ROTATION_MS, SETTLE_MS, TimePicker)
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
