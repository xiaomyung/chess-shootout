import logging
import pathlib

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.helpers import make_app, start_single_screen
from chessshootout.frontend.screens.base import Nav, Screen, assert_plain_payload


_pygame_init = pygame_display(1000, 800)


def test_switch_to_unknown_name_raises_key_error():
    app = make_app()
    with pytest.raises(KeyError):
        app.switch_to("nonexistent")


def test_assert_plain_payload_accepts_nested_plain_data_incl_path():
    assert_plain_payload({
        "a": 1, "b": "text", "c": 1.5, "d": True, "e": None,
        "f": [1, "two", (3, 4)],
        "g": {"nested": pathlib.Path("/tmp/x")},
    })


def test_assert_plain_payload_rejects_match_object():
    from chessshootout.domain.match import Match

    with pytest.raises(TypeError, match="offender"):
        assert_plain_payload({"offender": Match()})


def test_assert_plain_payload_rejects_lambda():
    with pytest.raises(TypeError, match="handler"):
        assert_plain_payload({"handler": lambda: None})


def test_assert_plain_payload_rejects_non_str_dict_key():
    with pytest.raises(TypeError, match="1"):
        assert_plain_payload({1: "value"})


def test_screen_base_contract_defaults():
    app = make_app()
    screen = Screen(app)
    assert screen.app is app
    assert screen.name == ""
    assert screen.uses_battle_backdrop is False
    assert screen.legacy_mode is None
    assert screen.enter() is None
    assert screen.exit() is None
    assert screen.update(0) is None
    assert screen.draw() is None
    assert screen.relayout((100, 100)) is None
    assert screen.on_resize() is None
    assert screen.handle_click((0, 0)) is False
    assert screen.handle_key(None) is False
    assert screen.handle_press((0, 0)) is False
    assert screen.handle_motion((0, 0)) is False
    assert screen.handle_release((0, 0)) is False
    assert screen.active_scrollable() is None
    assert screen.escape() is False
    assert screen.modals() == []
    assert screen.dirty_rects() is None
    assert screen.caption() == ""
    assert screen.debug_state() == {}
    assert screen.on_app_exit() is None


def test_menu_and_game_screen_identity():
    app = make_app()
    assert app.screens["menu"].name == "menu"
    assert app.screens["menu"].uses_battle_backdrop is True
    assert app.screens["game"].name == "game"
    assert app.screens["game"].uses_battle_backdrop is False


def test_switch_to_keeps_mode_and_screen_name_in_sync():
    app = make_app()
    app.switch_to("game")
    assert app.screen is app.screens["game"]
    assert app.mode == app.screen.name == "game"
    app.switch_to("menu")
    assert app.screen is app.screens["menu"]
    assert app.mode == app.screen.name == "menu"


def test_switch_to_game_with_explicit_mode_payload():
    app = make_app()
    app.switch_to("game", mode="single_screen")
    assert app.screen.name == "game"
    assert app.mode == "single_screen"


def test_request_nav_executes_via_pending_nav_step():
    app = make_app()
    app.request_nav(Nav("game", {"mode": "single_screen"}))
    assert app.screen.name == "menu"
    assert app._pending_nav is not None
    app._execute_pending_nav()
    assert app.screen.name == "game"
    assert app.mode == "single_screen"
    assert app._pending_nav is None


def test_request_nav_overwrite_last_wins():
    app = make_app()
    app.request_nav(Nav("game", {"mode": "single_screen"}))
    app.request_nav(Nav("menu"))
    app._execute_pending_nav()
    assert app.screen.name == "menu"
    assert app.mode == "menu"


def test_switch_to_logs_full_lifecycle(caplog):
    app = make_app()
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.switch_to("game", mode="single_screen")
    messages = [r.getMessage() for r in caplog.records]
    assert "screen switch menu -> game mode=single_screen" in messages
    assert "screen exited menu" in messages
    assert "screen entered game payload_keys=['mode']" in messages
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("screen switch" in r.getMessage() for r in infos)


def test_stale_event_drop_logs_count(caplog):
    app = make_app()

    def fake_handle_key(event):
        app.request_nav(Nav("game", {"mode": "single_screen"}))

    app.screen.handle_key = fake_handle_key
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_a, "mod": 0, "unicode": "a"}))
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_b, "mod": 0, "unicode": "b"}))
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_c, "mod": 0, "unicode": "c"}))
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.input_router.check_events()
    assert any("dropped 2 stale events pending nav game" == r.getMessage()
               for r in caplog.records)


def test_request_nav_overwrite_logs_warning(caplog):
    app = make_app()
    with caplog.at_level(logging.WARNING, logger="chess.frontend"):
        app.request_nav(Nav("game", {"mode": "single_screen"}))
        app.request_nav(Nav("menu"))
    assert any("nav intent overwritten" in r.getMessage() for r in caplog.records)


def test_stale_event_dropped_after_nav_queued_mid_frame():
    app = make_app()
    calls = []

    def fake_handle_key(event):
        calls.append(event.key)
        app.request_nav(Nav("game", {"mode": "single_screen"}))

    app.screen.handle_key = fake_handle_key
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_a, "mod": 0, "unicode": "a"}))
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_b, "mod": 0, "unicode": "b"}))
    app.input_router.check_events()
    assert calls == [pg.K_a]
    assert app._pending_nav is not None
    assert app._pending_nav.name == "game"


def test_quit_event_survives_stale_event_drop():
    app = make_app()

    def fake_handle_key(event):
        app.request_nav(Nav("game", {"mode": "single_screen"}))

    app.screen.handle_key = fake_handle_key
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_a, "mod": 0, "unicode": "a"}))
    pg.event.post(pg.event.Event(pg.QUIT, {}))
    app.input_router.check_events()
    assert app._pending_nav is not None
    assert app.running is False


def test_draw_frame_smoke_on_menu_screen():
    app = make_app()
    assert app.screen.name == "menu"
    app.draw_frame()


def test_draw_frame_smoke_on_game_screen():
    app = make_app()
    start_single_screen(app)
    assert app.screen.name == "game"
    app.draw_frame()
