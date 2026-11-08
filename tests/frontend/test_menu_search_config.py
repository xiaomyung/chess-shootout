"""MenuScreen.online_search_config(): the live read of the Play panel the
online coordinator's New Search starts from. It must always ask for an online
game and otherwise carry exactly what the panel shows right now."""

import pytest

from chessshootout.domain.match import BOT, ONLINE, SINGLE_SCREEN
from tests.conftest import pygame_display
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)

_MODE_ENV = ("CHESS_DEFAULT_TC", "CHESS_DEFAULT_INCREMENT", "CHESS_LAST_MODE", "CHESS_NICKNAME")


@pytest.fixture
def app(monkeypatch):
    for var in _MODE_ENV:
        monkeypatch.delenv(var, raising=False)
    application = make_app(1000, 800)
    application.draw_frame()
    return application


@pytest.mark.parametrize("mode", [SINGLE_SCREEN, BOT, ONLINE])
def test_online_search_config_forces_online_mode(app, mode):
    hero = app.menu.play_view
    hero.selected_mode = mode
    config = app.menu.online_search_config()
    assert config["mode"] == ONLINE
    expected = hero.build_config()
    assert expected["mode"] == mode, "the panel itself is left on its own mode"
    assert {k: v for k, v in config.items() if k != "mode"} == \
        {k: v for k, v in expected.items() if k != "mode"}
    assert set(config) == set(expected)


def test_online_search_config_reads_the_panel_live(app):
    """No snapshot: a side or time control changed after an earlier read shows
    up in the next one."""
    hero = app.menu.play_view
    first = app.menu.online_search_config()
    hero.selected_side = "black"
    hero.selected_time_minutes = 3
    hero.selected_increment_seconds = 2
    second = app.menu.online_search_config()
    assert second["side"] == "black"
    assert second["time_minutes"] == 3
    assert second["increment_seconds"] == 2
    assert first is not second


def test_online_search_config_returns_a_fresh_dict_each_time(app):
    config = app.menu.online_search_config()
    config["side"] = "tampered"
    assert app.menu.online_search_config()["side"] != "tampered"
