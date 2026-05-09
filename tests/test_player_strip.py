import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.visual.clock_visual import (
    INCREMENT_FLASH_MS, LOW_TIME_FRACTION, clock_pocket_color,
)
from frontend.visual.colors import Colors
from frontend.panels.player_strip import PlayerStrip, format_clock


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


# ---------- clock_pocket_color (low-time tint) ----------

def test_pocket_color_above_threshold_returns_base():
    # Above LOW_TIME_FRACTION → no tint.
    assert clock_pocket_color(0.50) == pg.Color(Colors.light_grey_menu)


def test_pocket_color_at_threshold_returns_base():
    # Exactly at the threshold → still base (tint kicks in only below).
    assert clock_pocket_color(LOW_TIME_FRACTION) == pg.Color(Colors.light_grey_menu)


def test_pocket_color_at_zero_returns_low_time():
    assert clock_pocket_color(0.0) == pg.Color(Colors.clock_low_time)


def test_pocket_color_at_halfway_lerps_halfway():
    base = pg.Color(Colors.light_grey_menu)
    low = pg.Color(Colors.clock_low_time)
    actual = clock_pocket_color(LOW_TIME_FRACTION / 2.0)
    expected = base.lerp(low, 0.5)
    # Each channel within 1 of the expected lerp.
    for i in range(4):
        assert abs(actual[i] - expected[i]) <= 1


def test_pocket_color_handles_none_fraction():
    # None is treated like "no clock" — base color, no tint.
    assert clock_pocket_color(None) == pg.Color(Colors.light_grey_menu)


def test_pocket_color_handles_negative_fraction():
    # Defensive: negative fractions are clamped to zero (full tint).
    assert clock_pocket_color(-0.1) == pg.Color(Colors.clock_low_time)


# ---------- Increment flash ----------

def test_increment_flash_alpha_zero_when_inactive(strip):
    assert strip._increment_flash_alpha() == 0


def test_increment_flash_decays_to_zero(strip):
    base = 1000
    strip.flash_increment(now_ms=base)
    assert strip._increment_flash_alpha(now_ms=base) > 0
    assert strip._increment_flash_alpha(now_ms=base + INCREMENT_FLASH_MS) == 0
    assert strip._increment_flash_alpha(now_ms=base + INCREMENT_FLASH_MS + 1) == 0


def test_increment_flash_alpha_starts_high(strip):
    base = 1000
    strip.flash_increment(now_ms=base)
    # At t=0 the alpha should be at peak (full progress).
    assert strip._increment_flash_alpha(now_ms=base) > strip._increment_flash_alpha(
        now_ms=base + INCREMENT_FLASH_MS // 2
    )


def test_set_state_carries_initial_seconds(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=600.0)
    assert strip.clock_initial_seconds == 600.0


def test_clock_fraction_none_when_initial_missing(strip):
    strip.set_state("Alice", 60.0, True)
    assert strip._clock_fraction() is None


def test_clock_fraction_computed_from_seconds(strip):
    strip.set_state("Alice", 30.0, True, clock_initial_seconds=300.0)
    assert strip._clock_fraction() == pytest.approx(0.10, abs=1e-6)


def test_clock_fraction_clamps_negative_to_zero(strip):
    strip.set_state("Alice", -5.0, True, clock_initial_seconds=300.0)
    assert strip._clock_fraction() == 0.0


def test_draw_smoke_with_low_time_fraction_and_flash(strip):
    strip.set_state("Alice", 5.0, True, clock_initial_seconds=300.0)
    strip.flash_increment(now_ms=pg.time.get_ticks())
    strip.draw()  # no exceptions, exercises both visual paths
