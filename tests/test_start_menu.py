import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.start_menu import StartMenu


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
    sm.draw()  # Build internal rects.
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


def test_click_time_5_min_updates_selection(menu):
    sm, _ = menu
    target = sm._time_rects[5]
    assert sm.handle_click(target.center) is True
    assert sm.selected_time_minutes == 5


def test_click_no_clock_sets_time_minutes_to_none(menu):
    sm, _ = menu
    target = sm._time_rects[None]
    sm.handle_click(target.center)
    assert sm.selected_time_minutes is None
    # Increment selection still present (stable dict shape).
    config = sm.build_config()
    assert "increment_seconds" in config
    assert config["increment_seconds"] == 5


def test_click_increment_updates_selection(menu):
    sm, _ = menu
    target = sm._increment_rects[10]
    sm.handle_click(target.center)
    assert sm.selected_increment_seconds == 10


def test_click_side_random(menu):
    sm, _ = menu
    target = sm._side_rects["random"]
    sm.handle_click(target.center)
    assert sm.selected_side == "random"


def test_click_side_black(menu):
    sm, _ = menu
    target = sm._side_rects["black"]
    sm.handle_click(target.center)
    assert sm.selected_side == "black"


def test_click_mode_bot(menu):
    sm, _ = menu
    target = sm._mode_rects["bot"]
    sm.handle_click(target.center)
    assert sm.selected_mode == "bot"


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


def test_start_game_fires_for_bot_mode(menu):
    sm, called = menu
    called.clear()
    sm.selected_mode = "bot"
    sm.draw()
    sm.handle_click(sm._start_rect.center)
    assert len(called) == 1
    assert called[0]["mode"] == "bot"


def test_start_game_fires_for_online_mode(menu):
    sm, called = menu
    called.clear()
    sm.selected_mode = "online"
    sm.draw()
    sm.handle_click(sm._start_rect.center)
    assert len(called) == 1
    assert called[0]["mode"] == "online"


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
