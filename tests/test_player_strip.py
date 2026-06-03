import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from backend.pieces import PieceType, PieceColor
from frontend.visual.colors import Colors
from frontend.panels.player_strip import (
    GIVE_TIME_FLOAT_MS, PlayerStrip, format_clock, format_countdown,
    give_time_float_alpha,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((900, 400))
    yield
    pg.quit()


def _fake_icons():
    icons = {}
    for pt in PieceType:
        for color in PieceColor:
            surf = pg.Surface((40, 40), pg.SRCALPHA)
            surf.fill((90, 200, 240, 255))
            icons[(pt, color)] = surf
    return icons


@pytest.fixture
def strip():
    s = PlayerStrip(pg.display.get_surface())
    s.set_rect(pg.Rect(0, 80, 560, 56))
    s.set_piece_icons(_fake_icons())
    return s


def _draw(strip):
    strip.window.fill((0, 0, 0))
    strip.draw()


def _has_color(win, rect, hexcolor, tol=6):
    want = pg.Color(hexcolor)
    rect = rect.clip(win.get_rect())
    for x in range(rect.x, rect.right, 2):
        for y in range(rect.y, rect.bottom, 2):
            c = win.get_at((x, y))
            if (abs(c.r - want.r) <= tol and abs(c.g - want.g) <= tol
                    and abs(c.b - want.b) <= tol):
                return True
    return False


def _snapshot(strip):
    return pg.image.tobytes(strip.window.subsurface(strip.rect), "RGB")


@pytest.mark.parametrize(
    "seconds, expected",
    [
        pytest.param(75.0, "1:15", id="minutes_seconds"),
        pytest.param(0.0, "0:00.0", id="zero_below_30s_shows_tenths"),
        pytest.param(599.9, "9:59", id="floors_fraction_not_roll_up"),
        pytest.param(None, "∞", id="none_renders_infinity"),
        pytest.param(-3.0, "0:00.0", id="negative_clamps_to_zero"),
        pytest.param(30.0, "0:30", id="at_30s_boundary_no_tenths"),
        pytest.param(29.999, "0:29.9", id="just_below_30s_shows_tenths"),
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
        pytest.param(60, "1:00", id="exact_minute"),
        pytest.param(125, "2:05", id="minutes_and_seconds"),
        pytest.param(-5, "0:00", id="negative_clamps_to_zero"),
    ],
)
def test_format_countdown(seconds, expected):
    assert format_countdown(seconds) == expected


@pytest.mark.parametrize(
    "progress, expected",
    [
        pytest.param(-0.1, 0, id="before_start"),
        pytest.param(0.0, 0, id="at_start_transparent"),
        pytest.param(0.3, 255, id="peak_opacity"),
        pytest.param(0.15, 127, id="ramps_up"),
        pytest.param(1.0, 0, id="finished"),
        pytest.param(1.5, 0, id="past_end"),
    ],
)
def test_give_time_float_alpha(progress, expected):
    assert give_time_float_alpha(progress) == expected


def test_give_time_float_alpha_decays_after_peak():
    assert give_time_float_alpha(0.5) > give_time_float_alpha(0.85)


def test_set_state_records_fields(strip):
    strip.set_state("Alice", 75.0, True, player_color=PieceColor.WHITE,
                    rating="1500", ko_count=2)
    assert strip.name == "Alice"
    assert strip.clock_seconds == 75.0
    assert strip.active is True
    assert strip.player_color == PieceColor.WHITE
    assert strip.rating == "1500"
    assert strip.ko_count == 2


def test_set_rect_rebuilds_fonts(strip):
    initial = strip.name_font.get_height()
    strip.set_rect(pg.Rect(0, 0, 560, 110))
    assert strip.name_font.get_height() > initial


@pytest.mark.parametrize(
    "clock_seconds, initial, expected",
    [
        pytest.param(60.0, None, None, id="none_when_initial_missing"),
        pytest.param(30.0, 300.0, pytest.approx(0.10, abs=1e-6), id="computed"),
        pytest.param(-5.0, 300.0, 0.0, id="clamps_negative_to_zero"),
    ],
)
def test_clock_fraction(strip, clock_seconds, initial, expected):
    strip.set_state("Alice", clock_seconds, True, clock_initial_seconds=initial)
    assert strip._clock_fraction() == expected


def test_low_time_below_threshold(strip):
    strip.set_state("Alice", 5.0, True, clock_initial_seconds=300.0)
    assert strip._is_low_time() is True
    assert strip._clock_text_color() == Colors.clock_low_text
    assert strip._clock_border_color() == Colors.clock_low_time


def test_not_low_time_above_threshold(strip):
    strip.set_state("Alice", 200.0, False, clock_initial_seconds=300.0)
    assert strip._is_low_time() is False
    assert strip._clock_text_color() == Colors.white


def test_untimed_clock_is_never_low(strip):
    strip.set_state("Alice", None, False)
    assert strip._is_low_time() is False
    assert strip._clock_text_color() == Colors.white


def test_active_clock_border_stays_neutral(strip):
    """The active cue is the glow, not a hard accent ring on the clock box."""
    strip.set_state("Alice", 200.0, True, clock_initial_seconds=300.0)
    assert strip._clock_border_color() == Colors.button_border


def _avatar_top_pixel(strip):
    pad = max(int(strip.rect.height * 0.16), 4)
    av = strip.rect.height - 2 * pad
    return strip.window.get_at(
        (strip.rect.x + pad + av // 2, strip.rect.y + pad + max(3, av // 6)))


def test_white_avatar_is_warm_amber(strip):
    strip.set_state("Alice", 60.0, False, player_color=PieceColor.WHITE)
    _draw(strip)
    px = _avatar_top_pixel(strip)
    assert px.r > 180 and px.r > px.b, "white avatar top should be warm amber→accent"


def test_black_avatar_is_cool_slate(strip):
    strip.set_state("Bob", 60.0, False, player_color=PieceColor.BLACK)
    _draw(strip)
    px = _avatar_top_pixel(strip)
    assert px.b >= px.r, "black avatar should be cool slate, not warm"


def test_bot_avatar_uses_slate_even_when_white(strip):
    strip.set_state("Bot", 60.0, False, player_color=PieceColor.WHITE, is_bot=True)
    _draw(strip)
    px = _avatar_top_pixel(strip)
    assert px.b >= px.r, "bot avatar is slate regardless of board color"


def test_rating_pill_drawn(strip):
    strip.set_state("Alice", 60.0, False, player_color=PieceColor.WHITE,
                    rating="1500", ko_count=0)
    _draw(strip)
    assert _has_color(strip.window, strip.rect, Colors.button_hover), \
        "rating pill background (button_hover) should be visible"


def test_captured_icons_drawn(strip):
    strip.set_state("Alice", 60.0, False, captured=[PieceType.QUEEN, PieceType.PAWN],
                    captured_color=PieceColor.BLACK, player_color=PieceColor.WHITE,
                    rating="1500", ko_count=0)
    _draw(strip)
    assert _has_color(strip.window, strip.rect, "#5ac8f0", tol=20)


def test_advantage_pill_amber_when_ahead(strip):
    strip.set_state("Bob", 60.0, False, captured=[PieceType.QUEEN],
                    captured_color=PieceColor.WHITE, advantage=9,
                    player_color=PieceColor.BLACK, rating="1500", ko_count=0)
    _draw(strip)
    assert _has_color(strip.window, strip.rect, Colors.amber), \
        "amber +N pill should show when ahead"


def test_advantage_pill_clears_last_captured_icon(strip):
    """The +N pill anchors past the last captured icon's full right edge, not at the
    fanned-overlap cursor (which sits 1/3 of an icon short and drew the pill on top)."""
    strip.captured = [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP]
    strip.captured_color = PieceColor.WHITE
    strip.advantage = 14
    pill_x = []
    strip._draw_advantage_pill = lambda x, cy, right, max_h=None: pill_x.append(x)
    ih, x0, n = 44, 100, 3
    strip._draw_captured(x0, cy=30, right=10_000, ih=ih)
    size = max(int(ih * 0.5), 6)
    gap = max(int(ih * 0.18), 5)
    last_right = x0 + (n - 1) * (size - size // 3) + size
    assert pill_x == [last_right + gap]


def test_advantage_pill_survives_truncated_captures(strip):
    """When the captured row is too long to fully fit, the pill still gets a chance
    to draw (break, not return) rather than being silently dropped."""
    drawn = []
    strip._draw_advantage_pill = lambda x, cy, right, max_h=None: drawn.append(x)
    strip.captured = [PieceType.PAWN] * 10
    strip.captured_color = PieceColor.WHITE
    strip.advantage = 6
    strip._draw_captured(0, 30, 40, 44)
    assert drawn, "advantage pill should still be offered after truncated captures"


def test_rating_and_material_pills_dont_overlap_vertically(strip):
    """Two-row layout caps each pill to its half-row so the rating and material
    bubbles can't collide vertically."""
    strip.set_rect(pg.Rect(0, 0, 320, 56))
    boxes = {}
    strip._draw_rating_pill = lambda x, cy, right, max_h=0: boxes.update(rating=(cy, max_h)) or x
    strip._draw_advantage_pill = lambda x, cy, right, max_h=0: boxes.update(adv=(cy, max_h))
    strip.set_state("Bob", None, False, captured=[PieceType.QUEEN],
                    captured_color=PieceColor.WHITE, advantage=9,
                    player_color=PieceColor.BLACK, rating="1500", ko_count=0)
    _draw(strip)
    (r_cy, r_max), (a_cy, a_max) = boxes["rating"], boxes["adv"]
    assert a_cy - r_cy >= max(r_max, a_max), \
        "rating and material pills must be at least one capped-height apart"


def test_short_strip_falls_back_to_single_row(strip):
    """A min-window-height strip puts the rating and material pills on one centered
    row (no vertical stacking), so they never overlap."""
    strip.set_rect(pg.Rect(0, 0, 200, 28))
    cys = {}
    strip._draw_rating_pill = lambda x, cy, right, max_h=0: cys.update(rating=cy) or (x + 30)
    strip._draw_advantage_pill = lambda x, cy, right, max_h=0: cys.update(adv=cy)
    strip.set_state("Bob", None, False, captured=[PieceType.QUEEN],
                    captured_color=PieceColor.WHITE, advantage=9,
                    player_color=PieceColor.BLACK, rating="1500", ko_count=0)
    _draw(strip)
    assert cys["rating"] == cys["adv"], "short strip should draw both pills on one row"


def test_advantage_pill_absent_when_even(strip):
    strip.set_state("Bob", 60.0, False, captured=[], captured_color=PieceColor.WHITE,
                    advantage=0, player_color=PieceColor.BLACK, rating="1500", ko_count=0)
    _draw(strip)
    assert not _has_color(strip.window, strip.rect, Colors.amber), \
        "no amber pill/shell when even and no kills"


def test_ko_block_returns_left_edge_when_present(strip):
    strip.set_state("Alice", 60.0, False, player_color=PieceColor.WHITE,
                    rating="1500", ko_count=3)
    left = strip._draw_ko(strip.rect.right - 20, strip.rect.height - 16)
    assert left is not None and left < strip.rect.right


def test_ko_block_absent_when_zero(strip):
    strip.set_state("Alice", 60.0, False, ko_count=0)
    assert strip._draw_ko(strip.rect.right - 20, strip.rect.height - 16) is None


def test_ko_wink_arms_on_increment(strip):
    strip.set_state("Alice", 60.0, False, ko_count=1)
    strip._ko_wink_until_ms = 0
    strip.set_state("Alice", 60.0, False, ko_count=2)
    assert strip._ko_wink_until_ms > 0


def test_ko_wink_does_not_arm_without_increment(strip):
    strip.set_state("Alice", 60.0, False, ko_count=2)
    strip._ko_wink_until_ms = 0
    strip.set_state("Alice", 60.0, False, ko_count=2)
    assert strip._ko_wink_until_ms == 0


def test_flag_surface_returns_sized_emoji(strip):
    strip.country = "US"
    surf = strip._flag_surface(20)
    assert surf is not None
    assert surf.get_height() == 20
    assert surf.get_width() > 0


@pytest.mark.parametrize("code", [None, "", "ZZ", "usa"])
def test_flag_surface_none_for_missing_or_invalid_country(strip, code):
    strip.country = code
    assert strip._flag_surface(20) is None


def test_flag_changes_strip_render(strip):
    strip.set_state("Alice", 300.0, True, connection_state="connected",
                    player_color=PieceColor.WHITE)
    _draw(strip)
    without = _snapshot(strip)
    strip.set_state("Alice", 300.0, True, connection_state="connected",
                    player_color=PieceColor.WHITE, country="US")
    _draw(strip)
    assert _snapshot(strip) != without


def test_flag_renders_us_red(strip):
    strip.set_state("Alice", 300.0, False, connection_state="connected",
                    player_color=PieceColor.BLACK, country="US")
    _draw(strip)
    region = pg.Rect(strip.rect.x + 55, strip.rect.y, 130, strip.rect.height)
    assert _has_color(strip.window, region, "#b22234", tol=70)


def test_flag_rect_set_when_country_present(strip):
    strip.set_state("Alice", 300.0, True, player_color=PieceColor.BLACK, country="US")
    _draw(strip)
    assert strip._flag_rect.width > 0


def test_flag_rect_empty_without_country(strip):
    strip.set_state("Alice", 300.0, True, player_color=PieceColor.BLACK)
    _draw(strip)
    assert strip._flag_rect.width == 0


def test_tooltip_alpha_eases_in_and_out(strip):
    strip._tooltip_alpha = 0.0
    for _ in range(60):
        strip._advance_tooltip(True)
    assert strip._tooltip_alpha > 0.9
    for _ in range(60):
        strip._advance_tooltip(False)
    assert strip._tooltip_alpha < 0.1


def test_tooltip_bubble_renders_country_name(strip):
    strip.set_state("Alice", 300.0, True, player_color=PieceColor.BLACK, country="US")
    _draw(strip)
    strip._tooltip_alpha = 1.0
    strip._blit_tooltip("United States")
    flag = strip._flag_rect
    region = pg.Rect(max(flag.centerx - 80, 0), flag.bottom + 2, 160, 30)
    assert _has_color(strip.window, region, Colors.white, tol=20)


def test_tooltip_resets_alpha_when_country_absent(strip):
    strip.set_state("Alice", 300.0, True, player_color=PieceColor.BLACK)
    strip._tooltip_alpha = 0.5
    _draw(strip)
    assert strip._tooltip_alpha == 0.0


def test_active_black_strip_shows_accent_inactive_does_not(strip):
    """A slate (black) strip has no accent at rest, so the accent border is a
    clean discriminator for the active 'whose turn' cue."""
    strip.set_state("Bob", 60.0, True, player_color=PieceColor.BLACK,
                    clock_initial_seconds=300.0, rating="1500")
    _draw(strip)
    assert _has_color(strip.window, strip.rect.inflate(20, 20), Colors.accent), \
        "active strip should show the accent cue"
    strip.set_state("Bob", 60.0, False, player_color=PieceColor.BLACK,
                    clock_initial_seconds=300.0, rating="1500")
    _draw(strip)
    assert not _has_color(strip.window, strip.rect.inflate(20, 20), Colors.accent), \
        "inactive slate strip should have no accent"


def test_flash_alpha_decays_to_zero(strip):
    base = 1000
    strip.flash_increment(now_ms=base)
    assert strip._flash_alpha(now_ms=base) > 0
    assert strip._flash_alpha(now_ms=base + 10_000) == 0


def test_flash_increment_with_seconds_arms_float(strip):
    strip.flash_increment(15, now_ms=2000)
    assert strip._give_time_amount == 15
    assert strip._give_time_start_ms == 2000


def test_flash_increment_without_seconds_does_not_arm_float(strip):
    strip.flash_increment(now_ms=2000)
    assert strip._give_time_start_ms == 0


def test_give_time_float_label_renders_above_strip(strip, monkeypatch):
    """The rising +0:Ns label paints green above the clock box during its window."""
    strip.set_state("Alice", 60.0, True, player_color=PieceColor.BLACK,
                    clock_initial_seconds=300.0, rating="1500")
    strip._give_time_amount = 15
    strip._give_time_start_ms = 1000
    monkeypatch.setattr(pg.time, "get_ticks",
                        lambda: 1000 + int(GIVE_TIME_FLOAT_MS * 0.3))
    _draw(strip)
    above = pg.Rect(strip.rect.x, strip.rect.y - 40, strip.rect.width, 44)
    assert _has_color(strip.window, above, Colors.clock_increment_flash, tol=45), \
        "give-time float label should rise above the strip"


def test_auto_end_badge_absent_without_label(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0)
    assert strip._draw_auto_end_badge(strip.rect.right, strip.rect.centery) is None


def test_auto_end_badge_within_bounds(strip):
    strip.set_state("Alice", 60.0, True, clock_initial_seconds=300.0,
                    auto_end_label="Abort in", auto_end_seconds=45)
    badge_x = strip._draw_auto_end_badge(strip.rect.right, strip.rect.centery)
    assert badge_x is not None and badge_x <= strip.rect.right


@pytest.mark.parametrize("size", [(300, 28), (560, 56), (820, 96)])
def test_draw_at_multiple_sizes(strip, size):
    strip.set_rect(pg.Rect(0, 80, *size))
    strip.set_state("X" * 22, 12.3, True, captured=[PieceType.PAWN] * 6,
                    captured_color=PieceColor.BLACK, advantage=4,
                    player_color=PieceColor.WHITE, rating="1500", ko_count=5)
    _draw(strip)
    painted = strip.window.subsurface(strip.rect)
    assert pg.image.tobytes(painted, "RGB") != bytes(painted.get_width()
                                                      * painted.get_height() * 3)


def test_name_text_changes_pixels(strip):
    strip.set_state("Alice", 65.0, True, player_color=PieceColor.WHITE, rating="1500")
    _draw(strip)
    a = _snapshot(strip)
    strip.set_state("Zynqx", 65.0, True, player_color=PieceColor.WHITE, rating="1500")
    _draw(strip)
    assert a != _snapshot(strip)


def test_draw_untimed_shows_infinity(strip):
    strip.set_state("Carol", None, False, player_color=PieceColor.WHITE, rating="1500")
    _draw(strip)
    assert format_clock(strip.clock_seconds) == "∞"
