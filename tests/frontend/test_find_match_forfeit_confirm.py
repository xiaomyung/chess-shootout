"""FIND MATCH while a game is still waiting to be rejoined: a new search would
forfeit that game to the opponent, so the shell asks first through the global
confirm card. Only an explicit yes starts the search; Cancel and Esc leave
everything as it was, and nothing else (a local start, no pending reconnect)
ever asks."""

import os

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.helpers import key_event, make_app
from chessshootout.domain.match import ONLINE, SINGLE_SCREEN
from chessshootout.frontend.frontend import (
    FORFEIT_SEARCH_NO, FORFEIT_SEARCH_SUB, FORFEIT_SEARCH_TITLE, FORFEIT_SEARCH_YES,
)


_pygame_init = pygame_display(1000, 800)


def _config(mode):
    return {"mode": mode, "nickname": "alice", "side": "random",
            "time_minutes": 3, "increment_seconds": 2}


@pytest.fixture
def app(monkeypatch):
    # set_last_mode / set_nickname write os.environ directly; pin both so the
    # monkeypatch teardown restores whatever was there before.
    monkeypatch.setenv("CHESS_LAST_MODE", "before")
    monkeypatch.setenv("CHESS_NICKNAME", "before")
    app = make_app()
    app.draw_frame()
    return app


@pytest.fixture
def searches(app, monkeypatch):
    started = []
    monkeypatch.setattr(app.coordinator, "_begin_online_flow", started.append)
    return started


def _reclaimable(app, monkeypatch, available=True):
    monkeypatch.setattr(app.coordinator, "reconnect_available", lambda: available)


def _click(app, button):
    app.draw_frame()
    rect = app.confirm_modal.button_rects[button]
    assert app.confirm_modal.handle_click(rect.center) is True


def test_online_start_with_a_reclaimable_game_asks_first(app, searches, monkeypatch):
    _reclaimable(app, monkeypatch)

    app._on_start_game(_config(ONLINE))

    modal = app.confirm_modal
    assert modal.is_visible()
    assert modal.title == FORFEIT_SEARCH_TITLE
    assert modal.sub == FORFEIT_SEARCH_SUB
    assert (modal.yes_label, modal.no_label) == (FORFEIT_SEARCH_YES, FORFEIT_SEARCH_NO)
    assert modal.danger is True
    assert modal.on_extra is None
    assert searches == []
    assert app.screen is app.menu
    app.draw_frame()


def test_the_question_is_asked_before_anything_is_remembered(app, searches, monkeypatch):
    _reclaimable(app, monkeypatch)
    app._on_start_game(_config(ONLINE))
    assert os.environ["CHESS_LAST_MODE"] == "before"
    assert os.environ["CHESS_NICKNAME"] == "before"


def test_confirming_starts_the_search_with_the_same_config(app, searches, monkeypatch):
    _reclaimable(app, monkeypatch)
    config = _config(ONLINE)
    app._on_start_game(config)

    _click(app, "yes")

    assert searches == [config]
    assert not app.confirm_modal.is_visible()
    assert os.environ["CHESS_LAST_MODE"] == ONLINE
    assert os.environ["CHESS_NICKNAME"] == "alice"


def test_confirming_starts_exactly_one_search_even_if_still_reclaimable(
        app, searches, monkeypatch):
    """The confirm is the gate, not a loop: the yes path must not re-check and
    ask again just because the coordinator has not retired the offer yet."""
    _reclaimable(app, monkeypatch)
    app._on_start_game(_config(ONLINE))
    _click(app, "yes")
    assert len(searches) == 1
    assert not app.confirm_modal.is_visible()


def test_cancel_leaves_no_search_and_keeps_the_menu(app, searches, monkeypatch):
    _reclaimable(app, monkeypatch)
    app._on_start_game(_config(ONLINE))

    _click(app, "no")

    assert searches == []
    assert not app.confirm_modal.is_visible()
    assert app.screen is app.menu
    assert app.menu.play_view_visible()
    assert os.environ["CHESS_LAST_MODE"] == "before"


def test_escape_cancels_like_the_cancel_button(app, searches, monkeypatch):
    _reclaimable(app, monkeypatch)
    app._on_start_game(_config(ONLINE))
    pg.event.clear()
    pg.event.post(key_event(pg.K_ESCAPE))

    app.input_router.check_events()

    assert searches == []
    assert not app.confirm_modal.is_visible()
    assert app.menu.play_view_visible()


def test_online_start_without_a_reclaimable_game_searches_at_once(app, searches, monkeypatch):
    _reclaimable(app, monkeypatch, available=False)
    config = _config(ONLINE)

    app._on_start_game(config)

    assert searches == [config]
    assert not app.confirm_modal.is_visible()


def test_a_local_start_never_asks_even_with_a_reclaimable_game(app, searches, monkeypatch):
    asked = []
    monkeypatch.setattr(app.coordinator, "reconnect_available",
                        lambda: asked.append(1) or True)

    app._on_start_game(_config(SINGLE_SCREEN))

    assert not app.confirm_modal.is_visible()
    assert app.screen is app.game
    assert searches == []
    assert asked == []


def test_the_real_reconnect_offer_drives_the_question(app, searches):
    """No monkeypatched predicate: a pending reclaim on the coordinator itself
    is what raises the confirm."""
    with app.coordinator._pending_reconnect_lock:
        app.coordinator._pending_reconnect = {"room_id": "r1"}
    try:
        app._on_start_game(_config(ONLINE))
        assert app.confirm_modal.title == FORFEIT_SEARCH_TITLE
        assert searches == []
    finally:
        with app.coordinator._pending_reconnect_lock:
            app.coordinator._pending_reconnect = None
