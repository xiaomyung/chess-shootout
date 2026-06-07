"""StartMenu setup-card behavior: clicks mutate the bound selection, the time
chips paginate (10/15/30/∞ ⇄ 1/2/3/5) without losing the selection, Start fires
build_config, and env defaults apply on launch.

The `menu` is built at a fixed rect and drawn once so the chip/segment rects
exist before any click is dispatched.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.modals.start import StartMenu


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _clean_env(monkeypatch):
    for var in ("CHESS_DEFAULT_TC", "CHESS_DEFAULT_INCREMENT", "CHESS_LAST_MODE",
                "CHESS_NICKNAME"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def menu(monkeypatch):
    _clean_env(monkeypatch)
    callbacks_called = []

    def on_start(config):
        callbacks_called.append(config)

    sm = StartMenu(pg.display.get_surface(), {"start_game": on_start})
    sm.set_rect(pg.Rect(100, 50, 440, 620))
    sm.draw()
    return sm, callbacks_called


def make_key_event(key, unicode=""):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": 0})


def test_applies_mappable_env_default_time(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "15")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None})
    assert sm.selected_time_minutes == 15
    assert sm.selected_increment_seconds == 10


def test_expanded_menu_now_applies_one_minute_and_plus_fifteen(monkeypatch):
    """The card's chips cover the whole default set now, so 1-min / +15 defaults
    that the old menu couldn't show do apply."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "1")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "15")
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None})
    assert sm.selected_time_minutes == 1
    assert sm.selected_increment_seconds == 15


def test_infinity_env_default_maps_to_no_clock(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "∞")
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None})
    assert sm.selected_time_minutes is None


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
        pytest.param("_mode_rects", "selected_mode", "single_screen", "bot", id="mode_bot"),
        pytest.param("_mode_rects", "selected_mode", "single_screen", "online", id="mode_online"),
        pytest.param("_incr_rects", "selected_increment_seconds", 5, 10, id="incr_10"),
        pytest.param("_incr_rects", "selected_increment_seconds", 5, 15, id="incr_15"),
        pytest.param("_side_rects", "selected_side", "black", "random", id="side_random"),
        pytest.param("_side_rects", "selected_side", "random", "black", id="side_black"),
    ],
)
def test_click_selector_sets_selection(menu, rects_attr, selected_attr, preset, key):
    sm, _ = menu
    setattr(sm, selected_attr, preset)
    target = getattr(sm, rects_attr)[key]
    assert sm.handle_click(target.center) is True
    assert getattr(sm, selected_attr) == key


def test_time_chip_selects_on_first_page(menu):
    sm, _ = menu
    sm.selected_time_minutes = 10
    assert sm.handle_click(sm._time_rects[15].center) is True
    assert sm.selected_time_minutes == 15


def test_infinity_chip_sets_no_clock(menu):
    sm, _ = menu
    sm.handle_click(sm._time_rects[None].center)
    assert sm.selected_time_minutes is None
    assert sm.build_config()["increment_seconds"] == 0


def test_time_pagination_reveals_second_page_and_selects(menu):
    sm, _ = menu
    assert set(sm._time_rects) == {10, 15, 30, None, "__next__"}
    sm.handle_click(sm._time_rects["__next__"].center)
    sm.draw()
    assert set(sm._time_rects) == {1, 2, 3, 5, "__prev__"}
    sm.handle_click(sm._time_rects[3].center)
    assert sm.selected_time_minutes == 3
    assert sm.build_config()["time_minutes"] == 3


def test_infinity_zeros_and_locks_increment(menu):
    sm, _ = menu
    sm.selected_increment_seconds = 10
    sm.handle_click(sm._time_rects[None].center)
    assert sm.selected_time_minutes is None
    assert sm.selected_increment_seconds == 0
    sm.draw()
    sm.handle_click(sm._incr_rects[5].center)
    assert sm.selected_increment_seconds == 0, "increment is locked while untimed"
    sm.handle_click(sm._time_rects[15].center)
    sm.draw()
    sm.handle_click(sm._incr_rects[5].center)
    assert sm.selected_increment_seconds == 5, "picking a clock re-enables increment"


def test_infinity_default_forces_zero_increment(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "∞")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None})
    assert sm.selected_time_minutes is None
    assert sm.selected_increment_seconds == 0


def test_pagination_nav_does_not_change_selection(menu):
    sm, _ = menu
    sm.selected_time_minutes = 10
    sm.handle_click(sm._time_rects["__next__"].center)
    assert sm.selected_time_minutes == 10
    sm.draw()
    assert sm.build_config()["time_minutes"] == 10


def test_typing_via_handle_key(menu):
    sm, _ = menu
    sm.text_input.focused = True
    for ch in "alice":
        sm.handle_key(make_key_event(pg.K_a, unicode=ch))
    assert sm.text_input.text == "alice"
    assert sm.build_config()["nickname"] == "alice"


def test_click_text_input_focuses(menu):
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


def test_start_fires_callback_with_full_config(menu):
    sm, called = menu
    called.clear()
    sm.handle_click(sm._start_rect.center)
    assert len(called) == 1
    assert set(called[0]) == {"mode", "nickname", "time_minutes",
                              "increment_seconds", "side", "variant"}


@pytest.mark.parametrize("mode", [pytest.param("bot", id="bot"),
                                  pytest.param("online", id="online")])
def test_start_fires_for_selected_mode(menu, mode):
    sm, called = menu
    called.clear()
    sm.selected_mode = mode
    sm.draw()
    sm.handle_click(sm._start_rect.center)
    assert called and called[0]["mode"] == mode


def test_gear_opens_options():
    opened = []
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None,
                                              "options": lambda: opened.append(True)})
    sm.set_rect(pg.Rect(100, 50, 440, 620))
    sm.draw()
    assert sm.handle_click(sm._gear_rect.center) is True
    assert opened == [True]


def test_reconnect_banner_button_fires_callback():
    fired = []
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None,
                                              "reconnect": lambda: fired.append(True)})
    sm.set_reconnect_available(True)
    sm.set_rect(pg.Rect(100, 50, 440, 620))
    sm.draw()
    assert sm._recon_button_rect.width > 0
    assert sm.handle_click(sm._recon_button_rect.center) is True
    assert fired == [True]


def test_history_disabled_until_available(menu):
    sm, _ = menu
    fired = []
    sm.callbacks["load_pgn"] = lambda: fired.append(True)
    sm.handle_click(sm._history_rect.center)
    assert fired == []
    sm.load_pgn_available = True
    sm.handle_click(sm._history_rect.center)
    assert fired == [True]


def test_paste_fen_blocked_in_online_mode(menu):
    sm, _ = menu
    fired = []
    sm.callbacks["fen"] = lambda: fired.append(True)
    sm.selected_mode = "online"
    sm.handle_click(sm._fen_rect.center)
    assert fired == []
    sm.selected_mode = "single_screen"
    sm.handle_click(sm._fen_rect.center)
    assert fired == [True]


def _has_non_bg(win, rect):
    rect = rect.clip(win.get_rect())
    bg = win.get_at((win.get_rect().right - 1, win.get_rect().bottom - 1))[:3]
    return any(win.get_at((x, y))[:3] != bg
               for x in range(rect.x, rect.right, 2)
               for y in range(rect.y, rect.bottom, 2))


def test_side_cells_render_icons(menu):
    sm, _ = menu
    win = sm.window
    win.fill((0, 0, 0))
    sm.draw()
    for key in ("white", "random", "black"):
        assert _has_non_bg(win, sm._side_rects[key]), f"side cell {key} drew nothing"


def test_card_fits_min_window_rect():
    """At the 900x500 min-window card rect the whole card stays within bounds."""
    sm = StartMenu(pg.display.get_surface(), {"start_game": lambda c: None})
    sm.set_reconnect_available(True)
    card = pg.Rect(0, 0, 440, 440)
    sm.set_rect(card)
    sm.draw()
    assert sm._fen_rect.bottom <= card.bottom
    assert sm._start_rect.bottom <= card.bottom
    assert sm._tile_rect.top >= card.top


def test_state_preservation_across_hide_show(menu):
    sm, _ = menu
    sm.selected_mode = "bot"
    sm.selected_time_minutes = 15
    sm.selected_side = "black"
    sm.text_input.text = "carol"
    sm.hide()
    sm.show()
    sm.draw()
    assert sm.selected_mode == "bot"
    assert sm.selected_time_minutes == 15
    assert sm.selected_side == "black"
    assert sm.text_input.text == "carol"


def test_handle_click_returns_false_when_hidden(menu):
    sm, _ = menu
    sm.hide()
    assert sm.handle_click((0, 0)) is False
