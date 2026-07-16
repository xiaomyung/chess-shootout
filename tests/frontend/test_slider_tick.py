"""Slider drag ticks (v2.4.3): TickGate gates a UI tick on each 1% change,
coalescing rapid crossings. The options volume is discrete notch cells (cp2)
that fire play_ui_tick straight on each cell click.

TickGate is pure (takes now_ms) so its cadence logic is tested without pygame;
the integration tests prove the wiring reaches sound_manager.play_ui_tick.
"""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.visual.slider_tick import (
    TickGate, SLIDER_TICK_MIN_INTERVAL_MS,
)


_pygame_init = pygame_display(400, 300)


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


def test_notch_row_click_emits_ui_tick():
    from chessshootout.frontend.menu.options_rows import NotchRow
    sm = MagicMock()
    store = [0.0]
    row = NotchRow("Vol", "", lambda: store[0], lambda v: store.__setitem__(0, v),
                   on_tick=sm.play_ui_tick)
    row._band = pg.Rect(0, 0, 170, 22)
    assert row.handle_click((row._band.right - 4, row._band.centery)) is True
    assert store[0] == pytest.approx(1.0)
    sm.play_ui_tick.assert_called()


def test_notch_row_without_on_tick_is_silent_and_constructs_positionally():
    from chessshootout.frontend.menu.options_rows import NotchRow
    store = [0.0]
    row = NotchRow("Vol", "", lambda: store[0], lambda v: store.__setitem__(0, v))
    row._band = pg.Rect(0, 0, 170, 22)
    assert row.handle_click((row._band.centerx, row._band.centery)) is True
    assert 0.0 < store[0] <= 1.0
