"""Toast widget: visibility/alpha lifecycle and that draw() blits only while visible."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.visual.toast import DEFAULT_DURATION_MS, FADE_OUT_MS, Toast


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def toast():
    return Toast(pg.display.get_surface())


@pytest.mark.parametrize(
    "show_first, expected",
    [
        pytest.param(False, False, id="no_message_is_invisible"),
        pytest.param(True, True, id="show_makes_visible"),
    ],
)
def test_is_visible_tracks_message(toast, show_first, expected):
    if show_first:
        toast.show("PGN copied")
    assert toast.is_visible() is expected


def test_show_records_timestamp(toast):
    before = pg.time.get_ticks()
    toast.show("hello")
    assert toast._shown_at_ms >= before


def test_toast_invisible_after_duration_elapses(toast):
    toast.show("hello", duration_ms=200)
    assert toast.is_visible(now_ms=toast._shown_at_ms) is True
    assert toast.is_visible(now_ms=toast._shown_at_ms + 199) is True
    assert toast.is_visible(now_ms=toast._shown_at_ms + 200) is False
    assert toast.is_visible(now_ms=toast._shown_at_ms + 1000) is False


@pytest.mark.parametrize(
    "offset",
    [
        pytest.param(0, id="full_alpha_right_after_show"),
        pytest.param(DEFAULT_DURATION_MS // 2, id="full_alpha_halfway_before_fade"),
    ],
)
def test_alpha_full_outside_fade_out_window(toast, offset):
    """Alpha holds at 255 until inside the trailing FADE_OUT_MS window."""
    toast.show("hello")
    assert toast._alpha(toast._shown_at_ms + offset) == 255


def test_alpha_decays_during_fade_out_window(toast):
    """Inside the trailing fade-out window the alpha drops linearly below 255."""
    toast.show("hello")
    near_end = toast._shown_at_ms + (DEFAULT_DURATION_MS - FADE_OUT_MS // 2)
    alpha = toast._alpha(near_end)
    assert 0 < alpha < 255


def test_show_replaces_previous_message(toast):
    toast.show("first")
    toast.show("second")
    assert toast.message == "second"


def test_hide_clears_message(toast):
    toast.show("hi")
    toast.hide()
    assert toast.message is None
    assert toast.is_visible() is False


def test_draw_clears_message_after_expiry(toast):
    toast.show("expired", duration_ms=1)
    toast._shown_at_ms = pg.time.get_ticks() - 1000
    toast.draw()
    assert toast.message is None


def _top_centre_painted(window):
    """True if any pixel down the window's centre column (rows 12..50) is non-black.

    The toast rect is horizontally centred at y=TOP_OFFSET_PX, so the centre column
    always intersects it when drawn; an empty draw leaves the cleared black strip.
    """
    cx = window.get_width() // 2
    return any(tuple(window.get_at((cx, y)))[:3] != (0, 0, 0) for y in range(12, 50))


@pytest.mark.parametrize(
    "show_first, expect_painted",
    [
        pytest.param(True, True, id="visible_toast_blits_overlay"),
        pytest.param(False, False, id="invisible_toast_blits_nothing"),
    ],
)
def test_draw_blits_only_when_visible(toast, show_first, expect_painted):
    """draw() must paint the top-centre toast region iff the toast is visible."""
    window = pg.display.get_surface()
    window.fill((0, 0, 0), pg.Rect(0, 0, window.get_width(), 60))
    if show_first:
        toast.show("smoke")
    toast.draw()
    assert _top_centre_painted(window) is expect_painted
