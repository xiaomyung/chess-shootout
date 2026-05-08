import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.player_strip import PlayerStrip, format_clock


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def strip():
    s = PlayerStrip(pg.display.get_surface())
    s.set_rect(pg.Rect(0, 0, 400, 40))
    return s


def test_format_clock_minutes_seconds():
    assert format_clock(75.0) == "1:15"


def test_format_clock_zero():
    # Zero is below 30s threshold → tenths display.
    assert format_clock(0.0) == "0:00.0"


def test_format_clock_floors_fraction_above_30s():
    # 599.9s should display as 9:59 (integer floor), not roll up to 10:00.
    assert format_clock(599.9) == "9:59"


def test_format_clock_none_renders_em_dashes():
    assert format_clock(None) == "—:—"


def test_format_clock_negative_clamps_to_zero():
    assert format_clock(-3.0) == "0:00.0"


def test_format_clock_at_30s_no_tenths():
    # 30.0 is the boundary; tenths only below 30.
    assert format_clock(30.0) == "0:30"


def test_format_clock_just_below_30s_shows_tenths():
    assert format_clock(29.999) == "0:29.9"


def test_format_clock_low_seconds_with_tenths():
    assert format_clock(25.3) == "0:25.3"


def test_format_clock_truncates_tenths():
    # 9.95s should show 0:09.9 (truncate, not round to 10.0).
    assert format_clock(9.95) == "0:09.9"


def test_format_clock_well_above_30s_no_tenths():
    assert format_clock(125.7) == "2:05"


def test_set_state_records_fields(strip):
    strip.set_state("Alice", 75.0, True)
    assert strip.name == "Alice"
    assert strip.clock_seconds == 75.0
    assert strip.active is True


def test_draw_smoke_active_with_clock(strip):
    strip.set_state("Alice", 65.0, True)
    strip.draw()


def test_draw_smoke_inactive_with_clock(strip):
    strip.set_state("Bob", 599.9, False)
    strip.draw()


def test_draw_smoke_no_clock(strip):
    strip.set_state("Carol", None, False)
    strip.draw()


def test_set_rect_rebuilds_fonts(strip):
    initial = strip.name_font.get_height()
    strip.set_rect(pg.Rect(0, 0, 400, 80))
    bigger = strip.name_font.get_height()
    assert bigger > initial


def test_draw_at_multiple_sizes_does_not_crash(strip):
    for size in [(200, 24), (400, 40), (800, 80)]:
        strip.set_rect(pg.Rect(0, 0, *size))
        strip.set_state("X" * 25, 12.3, True)
        strip.draw()
