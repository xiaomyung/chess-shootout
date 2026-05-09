"""Toast widget (M12)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.toast import DEFAULT_DURATION_MS, FADE_OUT_MS, Toast


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def toast():
    return Toast(pg.display.get_surface())


def test_toast_starts_invisible(toast):
    assert toast.is_visible() is False


def test_show_makes_toast_visible(toast):
    toast.show("PGN copied")
    assert toast.is_visible() is True


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


def test_alpha_full_during_steady_phase(toast):
    toast.show("hello")
    # Right after show, alpha = 255.
    assert toast._alpha(toast._shown_at_ms) == 255
    # Halfway through (well outside the fade-out window), still 255.
    halfway = toast._shown_at_ms + DEFAULT_DURATION_MS // 2
    assert toast._alpha(halfway) == 255


def test_alpha_decays_during_fade_out_window(toast):
    toast.show("hello")
    # Inside the fade-out window the alpha drops linearly.
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
    # Force time well past expiry.
    toast._shown_at_ms = pg.time.get_ticks() - 1000
    toast.draw()
    assert toast.message is None


def test_draw_smoke_visible(toast):
    toast.show("smoke")
    toast.draw()  # must not raise
