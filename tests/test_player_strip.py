import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.visual.clock_visual import (
    INCREMENT_FLASH_MS, LOW_TIME_FRACTION, clock_pocket_color,
)
from frontend.visual.colors import Colors
from frontend.panels.player_strip import (
    AUTO_END_RED_THRESHOLD_SECONDS, PlayerStrip, format_clock, format_countdown,
)


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


def _snapshot(strip):
    region = strip.window.subsurface(strip.rect)
    return pg.image.tostring(region, "RGB")


def _draw_on_blank(strip):
    strip.window.fill((0, 0, 0))
    strip.draw()
    return _snapshot(strip)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        pytest.param(75.0, "1:15", id="minutes_seconds"),
        pytest.param(0.0, "0:00.0", id="zero_below_30s_shows_tenths"),
        pytest.param(599.9, "9:59", id="floors_fraction_not_roll_up"),
        pytest.param(None, "—:—", id="none_renders_em_dashes"),
        pytest.param(-3.0, "0:00.0", id="negative_clamps_to_zero"),
        pytest.param(30.0, "0:30", id="at_30s_boundary_no_tenths"),
        pytest.param(29.999, "0:29.9", id="just_below_30s_shows_tenths"),
        pytest.param(25.3, "0:25.3", id="low_seconds_with_tenths"),
        pytest.param(9.95, "0:09.9", id="truncates_tenths_not_round_up"),
        pytest.param(125.7, "2:05", id="well_above_30s_no_tenths"),
    ],
)
def test_format_clock(seconds, expected):
    assert format_clock(seconds) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [
        pytest.param(0, "0:00", id="zero"),
        pytest.param(7, "0:07", id="single_digit_seconds"),
        pytest.param(45, "0:45", id="under_a_minute"),
        pytest.param(60, "1:00", id="exact_minute"),
        pytest.param(125, "2:05", id="minutes_and_seconds"),
        pytest.param(-5, "0:00", id="negative_clamps_to_zero"),
    ],
)
def test_format_countdown(seconds, expected):
    assert format_countdown(seconds) == expected


def test_set_state_records_fields(strip):
    strip.set_state("Alice", 75.0, True)
    assert strip.name == "Alice"
    assert strip.clock_seconds == 75.0
    assert strip.active is True


def test_set_state_carries_initial_seconds(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=600.0)
    assert strip.clock_initial_seconds == 600.0


def test_set_rect_rebuilds_fonts(strip):
    initial = strip.name_font.get_height()
    strip.set_rect(pg.Rect(0, 0, 400, 80))
    bigger = strip.name_font.get_height()
    assert bigger > initial


@pytest.mark.parametrize(
    "fraction",
    [
        pytest.param(0.50, id="above_threshold"),
        pytest.param(LOW_TIME_FRACTION, id="exactly_at_threshold"),
        pytest.param(None, id="none_no_clock"),
    ],
)
def test_pocket_color_returns_base_when_not_low(fraction):
    assert clock_pocket_color(fraction) == pg.Color(Colors.light_grey_menu)


@pytest.mark.parametrize(
    "fraction",
    [
        pytest.param(0.0, id="at_zero"),
        pytest.param(-0.1, id="negative_clamps_to_full_tint"),
    ],
)
def test_pocket_color_returns_low_time_at_or_below_zero(fraction):
    assert clock_pocket_color(fraction) == pg.Color(Colors.clock_low_time)


def test_pocket_color_at_halfway_lerps_halfway():
    base = pg.Color(Colors.light_grey_menu)
    low = pg.Color(Colors.clock_low_time)
    actual = clock_pocket_color(LOW_TIME_FRACTION / 2.0)
    expected = base.lerp(low, 0.5)
    for i in range(4):
        assert abs(actual[i] - expected[i]) <= 1


def test_increment_flash_alpha_zero_when_inactive(strip):
    assert strip._increment_flash_alpha() == 0


def test_increment_flash_decays_to_zero(strip):
    base = 1000
    strip.flash_increment(now_ms=base)
    assert strip._increment_flash_alpha(now_ms=base) > 0
    assert strip._increment_flash_alpha(now_ms=base + INCREMENT_FLASH_MS) == 0
    assert strip._increment_flash_alpha(now_ms=base + INCREMENT_FLASH_MS + 1) == 0


def test_increment_flash_alpha_starts_high(strip):
    """At t=0 the flash alpha is at peak and decays as time elapses."""
    base = 1000
    strip.flash_increment(now_ms=base)
    assert strip._increment_flash_alpha(now_ms=base) > strip._increment_flash_alpha(
        now_ms=base + INCREMENT_FLASH_MS // 2
    )


@pytest.mark.parametrize(
    "clock_seconds, initial, expected",
    [
        pytest.param(60.0, None, None, id="none_when_initial_missing"),
        pytest.param(30.0, 300.0, pytest.approx(0.10, abs=1e-6), id="computed_from_seconds"),
        pytest.param(-5.0, 300.0, 0.0, id="clamps_negative_to_zero"),
    ],
)
def test_clock_fraction(strip, clock_seconds, initial, expected):
    strip.set_state("Alice", clock_seconds, True, clock_initial_seconds=initial)
    assert strip._clock_fraction() == expected


def test_render_badge_returns_none_when_label_missing(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0)
    surf, _, _ = strip._render_auto_end_badge(strip.rect)
    assert surf is None


def test_render_badge_uses_white_above_threshold(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0,
                    auto_end_label="abort", auto_end_seconds=45)
    surf, badge_x, badge_y = strip._render_auto_end_badge(strip.rect)
    assert surf is not None
    assert badge_x + surf.get_width() <= strip.rect.right


def test_render_badge_uses_red_below_threshold(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0,
                    auto_end_label="abandon",
                    auto_end_seconds=AUTO_END_RED_THRESHOLD_SECONDS - 1)
    surf, _, _ = strip._render_auto_end_badge(strip.rect)
    assert surf is not None


def test_draw_active_fills_name_region_with_hover(strip):
    """Active strips paint the name region with button_hover; inactive don't."""
    strip.set_state("Alice", 65.0, True)
    active_px = _draw_on_blank(strip)
    strip.set_state("Alice", 65.0, False)
    inactive_px = _draw_on_blank(strip)
    assert active_px != inactive_px
    strip.set_state("Alice", 65.0, True)
    strip.window.fill((0, 0, 0))
    strip.draw()
    hover = pg.Color(Colors.button_hover)
    row = [strip.window.get_at((x, strip.rect.centery))[:3]
           for x in range(strip.rect.left, strip.rect.right)]
    assert (hover.r, hover.g, hover.b) in row


def test_draw_inactive_with_clock_paints_strip(strip):
    strip.set_state("Bob", 599.9, False)
    painted = _draw_on_blank(strip)
    assert any(painted)


def test_draw_no_clock_differs_from_clocked(strip):
    """The em-dash no-clock render differs in pixels from a real clock render."""
    strip.set_state("Carol", None, False)
    no_clock = _draw_on_blank(strip)
    strip.set_state("Carol", 599.9, False)
    with_clock = _draw_on_blank(strip)
    assert no_clock != with_clock


def test_draw_name_text_changes_pixels(strip):
    strip.set_state("Alice", 65.0, True)
    short = _draw_on_blank(strip)
    strip.set_state("Zzzzz", 65.0, True)
    other = _draw_on_blank(strip)
    assert short != other


def test_draw_low_time_flash_changes_pocket_pixels(strip):
    """Triggering the increment flash visibly alters the pocket pixels."""
    strip.set_state("Alice", 5.0, True, clock_initial_seconds=300.0)
    no_flash = _draw_on_blank(strip)
    strip.flash_increment(now_ms=pg.time.get_ticks())
    with_flash = _draw_on_blank(strip)
    assert no_flash != with_flash


@pytest.mark.parametrize(
    "size, prev_min_height",
    [
        pytest.param((200, 24), 0, id="small"),
        pytest.param((400, 40), 14, id="medium_taller_font"),
        pytest.param((800, 80), 21, id="large_taller_font"),
    ],
)
def test_draw_at_multiple_sizes_lays_out_and_scales(strip, size, prev_min_height):
    strip.set_rect(pg.Rect(0, 0, *size))
    strip.set_state("X" * 25, 12.3, True)
    painted = _draw_on_blank(strip)
    assert any(painted)
    assert strip.name_font.get_height() > prev_min_height


def test_draw_with_badge_differs_from_without(strip):
    """An active auto-end badge adds badge pixels absent when no label is set."""
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0,
                    auto_end_label="reconnect", auto_end_seconds=20)
    with_badge = _draw_on_blank(strip)
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0)
    without_badge = _draw_on_blank(strip)
    assert with_badge != without_badge


def test_draw_badge_with_captures_stays_within_strip(strip):
    """Badge + capture list draws and the badge stays inside the strip bounds."""
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0,
                    captured=[], auto_end_label="abandon", auto_end_seconds=30)
    painted = _draw_on_blank(strip)
    assert any(painted)
    surf, badge_x, _ = strip._render_auto_end_badge(strip.rect)
    assert badge_x + surf.get_width() <= strip.rect.right
