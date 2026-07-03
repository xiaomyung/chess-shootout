"""Slider drag ticks (v2.4.3): TickGate gates a UI tick on each 1% change,
coalescing rapid crossings, and both slider widgets fire play_ui_tick on drag.

TickGate is pure (takes now_ms) so its cadence logic is tested without pygame;
the two integration tests prove the wiring reaches sound_manager.play_ui_tick.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.frontend.visual.slider_tick import (
    TickGate, SLIDER_TICK_MIN_INTERVAL_MS,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((400, 300))
    yield
    pg.quit()


def test_tickgate_none_callback_is_inert():
    gate = TickGate(None)
    gate.feed(0.5, 0)
    gate.feed(0.9, 10_000)
    assert gate._last_pct is None


def test_tickgate_fires_on_first_feed():
    calls = []
    TickGate(lambda: calls.append(1)).feed(0.5, 0)
    assert len(calls) == 1


def test_tickgate_no_tick_when_rounded_percent_unchanged():
    calls = []
    gate = TickGate(lambda: calls.append(1))
    gate.feed(0.500, 0)
    gate.feed(0.504, 10_000)
    assert len(calls) == 1


def test_tickgate_ticks_once_per_percent_step():
    calls = []
    gate = TickGate(lambda: calls.append(1))
    now = 0
    for ratio in (0.50, 0.51, 0.52, 0.53):
        now += SLIDER_TICK_MIN_INTERVAL_MS
        gate.feed(ratio, now)
    assert len(calls) == 4


def test_tickgate_throttles_rapid_crossings():
    calls = []
    gate = TickGate(lambda: calls.append(1))
    gate.feed(0.50, 0)
    gate.feed(0.60, 5)
    gate.feed(0.70, 10)
    gate.feed(0.80, SLIDER_TICK_MIN_INTERVAL_MS + 1)
    assert len(calls) == 2


def test_tickgate_reset_reticks_first_move_of_new_drag():
    calls = []
    gate = TickGate(lambda: calls.append(1))
    gate.feed(0.50, 0)
    gate.reset()
    gate.feed(0.50, 5)
    assert len(calls) == 2


def test_tickgate_clamps_out_of_range_ratio():
    calls = []
    gate = TickGate(lambda: calls.append(1))
    gate.feed(1.5, 0)
    gate.feed(2.0, 10_000)
    assert len(calls) == 1


def test_slider_row_drag_emits_ui_tick():
    from chessshootout.frontend.modals.options import SliderRow
    sm = MagicMock()
    store = [0.0]
    row = SliderRow("Vol", "", lambda: store[0], lambda v: store.__setitem__(0, v),
                    on_tick=sm.play_ui_tick)
    row._track = pg.Rect(0, 0, 100, 10)
    row.handle_click((10, 5))
    row._tick_gate._last_ms = -10_000
    row._set_from_x(90)
    assert store[0] == pytest.approx(0.9)
    assert sm.play_ui_tick.call_count >= 2


def test_slider_row_without_on_tick_is_silent_and_constructs_positionally():
    from chessshootout.frontend.modals.options import SliderRow
    store = [0.0]
    row = SliderRow("Vol", "", lambda: store[0], lambda v: store.__setitem__(0, v))
    row._track = pg.Rect(0, 0, 100, 10)
    row._set_from_x(50)
    assert store[0] == pytest.approx(0.5)


def test_audio_panel_drag_emits_ui_tick():
    from chessshootout.frontend.panels.audio import AudioPanel
    sm = MagicMock()
    sm.master_volume = 0.0
    sm.enabled = True
    panel = AudioPanel(pg.Surface((10, 10)), sm)
    panel.slider_rect = pg.Rect(0, 0, 200, 20)
    panel.mute_rect = pg.Rect(500, 0, 10, 10)
    panel.handle_click((100, 10))
    sm.play_ui_tick.assert_called()
