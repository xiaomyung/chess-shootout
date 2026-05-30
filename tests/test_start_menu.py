"""StartMenu selector/layout behavior: clicks mutate the matching selection,
the start button relabels per mode, and state survives a hide/show cycle.

A `menu` is built at a fixed 400x600 rect and drawn once so the per-section
selector rects exist before any click is dispatched.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modals.start import StartMenu


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


@pytest.fixture
def menu():
    callbacks_called = []

    def on_start(config):
        callbacks_called.append(config)

    sm = StartMenu(pg.display.get_surface(), {"start_game": on_start})
    sm.set_rect(pg.Rect(100, 50, 400, 600))
    sm.draw()
    return sm, callbacks_called


def make_key_event(key, unicode=""):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": 0})


def test_defaults(menu):
    sm, _ = menu
    assert sm.selected_mode == "single_screen"
    assert sm.selected_time_minutes == 10
    assert sm.selected_increment_seconds == 5
    assert sm.selected_side == "random"
    assert sm.text_input.text == ""


@pytest.mark.parametrize(
    "rects_attr, selected_attr, preset, key",
    [
        pytest.param("_mode_rects", "selected_mode", "single_screen", "bot",
                     id="mode_bot"),
        pytest.param("_time_rects", "selected_time_minutes", 10, 5,
                     id="time_5_min"),
        pytest.param("_increment_rects", "selected_increment_seconds", 5, 10,
                     id="increment_10"),
        pytest.param("_side_rects", "selected_side", "black", "random",
                     id="side_random_from_black"),
        pytest.param("_side_rects", "selected_side", "random", "black",
                     id="side_black"),
    ],
)
def test_click_selector_sets_selection(menu, rects_attr, selected_attr, preset, key):
    """Clicking a selector cell consumes the click and sets its bound attr.

    Each case preacts to a non-target value so the assertion proves a real
    change, not the unchanged default.
    """
    sm, _ = menu
    setattr(sm, selected_attr, preset)
    target = getattr(sm, rects_attr)[key]
    assert sm.handle_click(target.center) is True
    assert getattr(sm, selected_attr) == key


def test_click_no_clock_sets_time_minutes_to_none(menu):
    """Picking "No clock" nulls the minutes but keeps the increment in config."""
    sm, _ = menu
    target = sm._time_rects[None]
    sm.handle_click(target.center)
    assert sm.selected_time_minutes is None
    config = sm.build_config()
    assert "increment_seconds" in config
    assert config["increment_seconds"] == 5


def test_typing_via_handle_key(menu):
    sm, _ = menu
    sm.text_input.focused = True
    for ch in "alice":
        sm.handle_key(make_key_event(pg.K_a, unicode=ch))
    assert sm.text_input.text == "alice"
    assert sm.build_config()["nickname"] == "alice"


def test_click_text_input_focuses_and_does_not_change_selectors(menu):
    sm, _ = menu
    pre_mode = sm.selected_mode
    sm.handle_click(sm.text_input.rect.center)
    assert sm.text_input.focused is True
    assert sm.selected_mode == pre_mode


def test_click_selector_unfocuses_text_input(menu):
    sm, _ = menu
    sm.text_input.focused = True
    sm.handle_click(sm._mode_rects["single_screen"].center)
    assert sm.text_input.focused is False


def test_start_game_fires_callback_with_config(menu):
    sm, called = menu
    called.clear()
    sm.handle_click(sm._start_rect.center)
    assert len(called) == 1
    cfg = called[0]
    assert set(cfg.keys()) == {"mode", "nickname", "time_minutes",
                                "increment_seconds", "side"}


def test_start_game_fires_even_with_empty_nickname(menu):
    sm, called = menu
    called.clear()
    sm.text_input.text = ""
    sm.handle_click(sm._start_rect.center)
    assert len(called) == 1
    assert called[0]["nickname"] == ""


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param("bot", id="bot"),
        pytest.param("online", id="online"),
    ],
)
def test_start_game_fires_for_mode(menu, mode):
    """Selecting a mode then clicking Start fires with that mode in the config."""
    sm, called = menu
    called.clear()
    sm.selected_mode = mode
    sm.draw()
    sm.handle_click(sm._start_rect.center)
    assert len(called) == 1
    assert called[0]["mode"] == mode


@pytest.mark.parametrize(
    "mode, expected_label",
    [
        pytest.param("single_screen", "Start Game", id="single_screen_start_game"),
        pytest.param("bot", "Start Game", id="bot_start_game"),
        pytest.param("online", "Start Search", id="online_start_search"),
    ],
)
def test_start_button_label_per_mode(menu, mode, expected_label):
    sm, _ = menu
    sm.selected_mode = mode
    assert sm.start_button_label == expected_label


def test_state_preservation_across_hide_show(menu):
    sm, _ = menu
    sm.selected_mode = "bot"
    sm.selected_time_minutes = 15
    sm.selected_increment_seconds = 10
    sm.selected_side = "black"
    sm.text_input.text = "carol"
    sm.hide()
    sm.show()
    sm.draw()
    assert sm.selected_mode == "bot"
    assert sm.selected_time_minutes == 15
    assert sm.selected_increment_seconds == 10
    assert sm.selected_side == "black"
    assert sm.text_input.text == "carol"


def test_handle_click_returns_false_when_hidden(menu):
    sm, _ = menu
    sm.hide()
    consumed = sm.handle_click((0, 0))
    assert consumed is False
