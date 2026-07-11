"""Unit tests for the shared ScrollView gesture engine: grab-direction content
drag, the 6px click-vs-drag threshold, kinetic fling decay across an injected
timeline, scrollbar thumb-drag (no momentum), wheel stepping, clamping, and the
activity timestamp. All timing is injected via now_ms so the fling is
deterministic and no real clock is read."""

import math

import pygame as pg
import pytest

from chessshootout.frontend.visual.scroll_view import (
    FLING_FRICTION_TAU, FLING_MIN_VELOCITY, FLING_STOP_VELOCITY, ScrollView,
)
from chessshootout.frontend.visual.widgets import (
    SCROLL_THUMB_MIN_HEIGHT, scroll_thumb_rect,
)


class _Fake:
    def __init__(self, content_px, viewport=(0, 0, 100, 200)):
        self.offset = 0.0
        self.viewport = pg.Rect(viewport)
        self.content_px = content_px

    def view(self, wheel_step_px=10.0):
        return ScrollView(
            lambda: self.offset,
            lambda v: setattr(self, "offset", v),
            lambda: (self.viewport, self.content_px),
            wheel_step_px=wheel_step_px,
        )


def test_scrollable_and_max_px():
    f = _Fake(content_px=1000)
    sv = f.view()
    assert sv.scrollable() is True
    assert sv._max_px() == 800


def test_not_scrollable_when_content_fits():
    f = _Fake(content_px=120)
    sv = f.view()
    assert sv.scrollable() is False
    assert sv.handle_press((50, 100)) is None


def test_threshold_tap_does_not_drag():
    f = _Fake(content_px=1000)
    sv = f.view()
    assert sv.handle_press((50, 100), now_ms=0) == "content"
    sv.handle_motion((50, 103), now_ms=10)
    assert sv.handle_release(now_ms=20) is False
    assert f.offset == 0.0


def test_threshold_crossed_is_a_drag():
    f = _Fake(content_px=1000)
    f.offset = 400.0
    sv = f.view()
    sv.handle_press((50, 100), now_ms=0)
    sv.handle_motion((50, 112), now_ms=10)
    assert sv.handle_release(now_ms=20) is True


def test_grab_direction_is_natural():
    f = _Fake(content_px=1000)
    f.offset = 400.0
    sv = f.view()
    sv.handle_press((50, 100), now_ms=0)
    sv.handle_motion((50, 150), now_ms=10)
    assert f.offset == 350.0
    sv.handle_motion((50, 60), now_ms=20)
    assert f.offset == 440.0


def test_drag_clamps_at_both_ends():
    f = _Fake(content_px=1000)
    sv = f.view()
    sv.handle_press((50, 100), now_ms=0)
    sv.handle_motion((50, 400), now_ms=10)
    assert f.offset == 0.0
    f.offset = 800.0
    sv.cancel()
    sv.handle_press((50, 100), now_ms=20)
    sv.handle_motion((50, 0), now_ms=30)
    assert f.offset == 800.0


def _fling(sv, now0=0):
    sv.handle_press((50, 180), now_ms=now0)
    sv.handle_motion((50, 170), now_ms=now0 + 16)
    sv.handle_motion((50, 120), now_ms=now0 + 32)
    return sv.handle_release(now_ms=now0 + 32)


def test_fling_launches_and_decays_and_stops():
    f = _Fake(content_px=100000)
    sv = f.view()
    assert _fling(sv) is True
    assert sv._flinging is True
    offsets = []
    t = 48
    for _ in range(400):
        sv.tick(now_ms=t)
        offsets.append(f.offset)
        t += 16
        if not sv._flinging:
            break
    assert sv._flinging is False
    assert offsets == sorted(offsets)
    assert abs(sv._vel) < FLING_STOP_VELOCITY


def test_fling_velocity_decays_exponentially():
    f = _Fake(content_px=100000)
    sv = f.view()
    _fling(sv)
    v0 = sv._vel
    sv.tick(now_ms=48)
    dt = 0.016
    assert sv._vel == pytest.approx(v0 * math.exp(-dt / FLING_FRICTION_TAU), rel=1e-6)


def test_slow_release_does_not_fling():
    f = _Fake(content_px=100000)
    sv = f.view()
    sv.handle_press((50, 180), now_ms=0)
    sv.handle_motion((50, 168), now_ms=16)
    sv.handle_motion((50, 167), now_ms=216)
    assert abs(sv._vel) < FLING_MIN_VELOCITY
    assert sv.handle_release(now_ms=216) is True
    assert sv._flinging is False
    before = f.offset
    sv.tick(now_ms=232)
    assert f.offset == before


def test_thumb_rect_geometry():
    viewport = pg.Rect(0, 0, 100, 200)
    top = scroll_thumb_rect(viewport, 1000, 200, 0.0)
    bottom = scroll_thumb_rect(viewport, 1000, 200, 1.0)
    assert top.height == 40
    assert top.y == 0
    assert bottom.bottom == 200
    assert scroll_thumb_rect(viewport, 200, 200, 0.0) is None


def test_thumb_min_height_enforced():
    viewport = pg.Rect(0, 0, 100, 200)
    thumb = scroll_thumb_rect(viewport, 100000, 200, 0.0)
    assert thumb.height == SCROLL_THUMB_MIN_HEIGHT


def test_thumb_drag_maps_to_offset_without_fling():
    f = _Fake(content_px=1000)
    sv = f.view()
    thumb = sv.thumb_rect()
    travel = f.viewport.height - thumb.height
    sv.handle_press(thumb.center, now_ms=0)
    sv.handle_motion((thumb.centerx, thumb.centery + travel), now_ms=10)
    assert f.offset == pytest.approx(800.0)
    assert sv.handle_release(now_ms=20) is True
    assert sv._flinging is False


def test_wheel_steps_and_direction():
    f = _Fake(content_px=1000)
    f.offset = 100.0
    sv = f.view(wheel_step_px=10.0)
    assert sv.handle_wheel((50, 100), 1) is True
    assert f.offset == 90.0
    sv.handle_wheel((50, 100), -1)
    assert f.offset == 100.0


def test_wheel_outside_viewport_ignored():
    f = _Fake(content_px=1000)
    sv = f.view()
    assert sv.handle_wheel((500, 100), 1) is False


def test_wheel_kills_active_fling():
    f = _Fake(content_px=100000)
    sv = f.view()
    _fling(sv)
    assert sv._flinging is True
    sv.handle_wheel((50, 100), 1)
    assert sv._flinging is False


def test_activity_timestamp_updates_on_drag():
    f = _Fake(content_px=1000)
    sv = f.view()
    sv.handle_press((50, 100), now_ms=0)
    sv.handle_motion((50, 140), now_ms=123)
    assert sv.last_activity_ms == 123


def test_is_active_and_cancel():
    f = _Fake(content_px=100000)
    sv = f.view()
    _fling(sv)
    assert sv.is_active() is True
    sv.cancel()
    assert sv.is_active() is False
    assert sv._flinging is False
    assert sv._vel == 0.0
