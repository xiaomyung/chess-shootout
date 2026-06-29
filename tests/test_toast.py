"""Toast stacked-queue: dedupe-by-key, independent minimum-duration timers,
newest-on-top stacking, a monotonic single fade-out, and that draw() paints only
visible bubbles. Time is injected via draw(now_ms)/is_visible(now_ms) so the queue
is driven deterministically."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.visual.toast import (
    ENTER_MS, FADE_OUT_MS, MIN_DURATION_MS, Toast,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def toast():
    return Toast(pg.display.get_surface())


def test_no_bubbles_is_invisible(toast):
    assert toast.is_visible() is False


def test_show_makes_visible(toast):
    toast.show("hello")
    assert toast.is_visible() is True


def test_duration_floored_to_minimum(toast):
    toast.show("brief", duration_ms=1000)
    assert toast._bubbles[0]["duration_ms"] == MIN_DURATION_MS


def test_show_respects_longer_duration(toast):
    toast.show("long", duration_ms=9000)
    assert toast._bubbles[0]["duration_ms"] == 9000


def test_bubble_expires_after_duration_plus_fade(toast):
    toast.show("hello")
    b = toast._bubbles[0]
    start = b["shown_at_ms"]
    assert toast.is_visible(start + b["duration_ms"]) is True
    assert toast.is_visible(start + b["duration_ms"] + FADE_OUT_MS - 1) is True
    assert toast.is_visible(start + b["duration_ms"] + FADE_OUT_MS) is False


def test_same_message_refreshes_in_place(toast):
    toast.show("Resyncing…")
    first_at = toast._bubbles[0]["shown_at_ms"]
    toast._bubbles[0]["shown_at_ms"] = first_at - 1000
    toast.show("Resyncing…")
    assert len(toast._bubbles) == 1
    assert toast._bubbles[0]["shown_at_ms"] >= first_at


def test_fresh_bubble_fades_in_then_full(toast, monkeypatch):
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000)
    toast.show("hi")
    b = toast._bubbles[0]
    assert toast._alpha(b, 1000) == 0
    assert toast._alpha(b, 1000 + ENTER_MS // 2) == 127
    assert toast._alpha(b, 1000 + ENTER_MS) == 255


def test_refreshed_keyed_bubble_keeps_completed_fade_in(toast, monkeypatch):
    """A keyed status toast re-shown every frame (e.g. 'Resyncing…') must keep its
    fade-in complete; the regression reset the entrance clock each frame so it
    rendered near-invisible the whole time."""
    clock = [1000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: clock[0])
    toast.show("Resyncing…", key="resync")
    b = toast._bubbles[0]
    clock[0] += ENTER_MS
    for _ in range(20):
        clock[0] += 16
        toast.show("Resyncing…", key="resync")
        assert toast._alpha(b, clock[0]) == 255


def test_fade_out_is_monotonic_no_flicker(toast, monkeypatch):
    """The fade-out must decrease monotonically; the old two-branch alpha dropped to
    ~0 at the end of the shown period, flashed back to full, then faded again."""
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000)
    toast.show("bye")
    bub = toast._bubbles[0]
    start = 1000 + bub["duration_ms"] - FADE_OUT_MS
    end = 1000 + bub["duration_ms"] + FADE_OUT_MS
    alphas = [toast._alpha(bub, t) for t in range(start, end + 1, 10)]
    assert alphas[0] == 255
    assert alphas[-1] == 0
    assert all(x >= y for x, y in zip(alphas, alphas[1:]))


def test_distinct_messages_stack_newest_last(toast):
    toast.show("first")
    toast.show("second")
    assert [b["message"] for b in toast._bubbles] == ["first", "second"]


def test_key_dedupes_independent_of_message(toast):
    toast.show("Opponent reconnecting…", key="rematch_state")
    toast.show("Opponent returned", key="rematch_state")
    assert len(toast._bubbles) == 1
    assert toast._bubbles[0]["message"] == "Opponent returned"


def test_dismiss_removes_keyed_bubble(toast):
    toast.show("waiting", key="wait")
    toast.show("other")
    toast.dismiss("wait")
    assert [b["message"] for b in toast._bubbles] == ["other"]


def test_hide_clears_all(toast):
    toast.show("a")
    toast.show("b")
    toast.hide()
    assert toast._bubbles == []
    assert toast.is_visible() is False


def test_draw_removes_expired(toast):
    toast.show("expired")
    b = toast._bubbles[0]
    toast.draw(b["shown_at_ms"] + b["duration_ms"] + FADE_OUT_MS + 1)
    assert toast._bubbles == []


def test_newest_settles_above_older(toast):
    toast.show("older")
    toast.show("newer")
    now = toast._bubbles[0]["shown_at_ms"] + ENTER_MS
    for step in range(0, 800, 16):
        toast.draw(now + step)
    older = next(b for b in toast._bubbles if b["message"] == "older")
    newer = next(b for b in toast._bubbles if b["message"] == "newer")
    assert newer["y"] < older["y"]


def _top_centre_painted(window):
    cx = window.get_width() // 2
    return any(tuple(window.get_at((cx, y)))[:3] != (0, 0, 0) for y in range(12, 50))


@pytest.mark.parametrize(
    "show_first, expect_painted",
    [
        pytest.param(True, True, id="visible_bubble_paints"),
        pytest.param(False, False, id="empty_paints_nothing"),
    ],
)
def test_draw_paints_only_when_visible(toast, show_first, expect_painted):
    window = pg.display.get_surface()
    window.fill((0, 0, 0), pg.Rect(0, 0, window.get_width(), 60))
    if show_first:
        toast.show("smoke")
        b = toast._bubbles[0]
        now = b["shown_at_ms"] + ENTER_MS + 50
        toast.draw(now)
        toast.draw(now + 16)
    else:
        toast.draw()
    assert _top_centre_painted(window) is expect_painted
