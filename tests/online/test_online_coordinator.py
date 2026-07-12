"""OnlineCoordinator: the client-side service owning the online connection
lifecycle end-to-end (step 5 of the screen-architecture refactor).

Covers the subscriber protocol (subscribe/unsubscribe, the double-subscribe
guard, the assert on a board-level event arriving with no subscriber), the
no-subscriber RESULT fallback straight to app.game (the menu rematch-window
save pin), the match-found -> Nav("game", plain payload) -> subscribed
GameScreen flow, the full back-to-menu rematch window, the menu Reconnect
button glue, the coordinator.update-before-screen.update frame ordering, and
the on_app_exit teardown fan-out."""

import logging
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def _online_start_payload(**overrides):
    payload = {
        "your_color": "white", "white_name": "alice", "black_name": "bob",
        "time_minutes": 5, "increment_seconds": 0,
    }
    payload.update(overrides)
    return payload


def _wired_app(**overrides):
    app = make_app(1000, 800)
    client = MagicMock()
    client.room_id = "room-1"
    app.coordinator.client = client
    app.coordinator._start_online_game(_online_start_payload(**overrides))
    return app


def test_game_screen_subscribes_on_online_entry_and_unsubscribes_on_exit():
    app = make_app(1000, 800)
    assert app.coordinator._subscriber is None

    app.coordinator.client = MagicMock()
    app.coordinator.client.room_id = "room-1"
    app.coordinator._start_online_game(_online_start_payload())
    assert app.coordinator._subscriber is app.game

    app.switch_to("menu")
    assert app.coordinator._subscriber is None


def test_local_game_entry_never_subscribes():
    app = start_single_screen(make_app(1000, 800))
    assert app.screen.name == "game"
    assert app.coordinator._subscriber is None


def test_double_subscribe_asserts():
    app = make_app(1000, 800)
    app.coordinator.subscribe(app.game)
    with pytest.raises(AssertionError):
        app.coordinator.subscribe(app.game)


def test_unsubscribe_is_always_safe():
    app = make_app(1000, 800)
    app.coordinator.unsubscribe(app.game)
    assert app.coordinator._subscriber is None
    app.coordinator.subscribe(app.game)
    app.coordinator.unsubscribe(app.game)
    app.coordinator.unsubscribe(app.game)
    assert app.coordinator._subscriber is None


def test_board_level_event_with_no_subscriber_is_dropped_and_logged(caplog):
    """A board-level event with nobody listening is impossible by design, so it is
    an ERROR — but it must not take the frame down with it. _drain_online_inbound
    already swallows every handler exception, so raising here only ever degraded
    into "log it and carry on" anyway; doing that explicitly is the same behavior
    with one strategy instead of two."""
    app = make_app(1000, 800)
    assert app.coordinator._subscriber is None
    with caplog.at_level(logging.ERROR, logger="chess.frontend"):
        app.coordinator._forward_board_event("on_remote_move", {"from": "e2", "to": "e4"})
    assert any("no subscriber" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("method_name", [
    "on_remote_move", "on_skillcheck_required", "on_takeback",
    "on_give_time", "on_spectate",
])
def test_every_board_level_method_is_gated_by_the_subscriber_check(method_name, caplog):
    app = make_app(1000, 800)
    with caplog.at_level(logging.ERROR, logger="chess.frontend"):
        app.coordinator._forward_board_event(method_name, {})
    assert any("no subscriber" in r.getMessage() for r in caplog.records)


def test_result_with_no_subscriber_still_saves_and_scores(tmp_path, monkeypatch):
    """The no-subscriber RESULT pin: forwarding must land on the persistent
    GameScreen object directly, so the real save choke point (_on_result_final,
    which also awards the series score) still fires even though nobody
    subscribed to receive it."""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = _wired_app()
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    app.coordinator.unsubscribe(app.game)
    assert app.coordinator._subscriber is None

    app.coordinator._handle_online_result({"reason": "resignation", "winner_color": "white"})

    assert app.game.manual_result == "white_wins_by_resignation"
    assert app.game.result_flow._last_saved_pgn_path is not None
    assert app.game.result_flow.series_scores["alice"] == 1.0


def test_offer_and_connection_status_never_require_a_subscriber():
    app = _wired_app()
    app.switch_to("menu")
    assert app.coordinator._subscriber is None
    app.coordinator._push_offer_banner("draw_offered")
    app.coordinator._handle_connection_status({"opp_state": "reconnecting"})
    assert app.game._opp_disconnected_at_ms is not None


def test_match_found_transition_ends_with_a_subscribed_online_game_screen():
    app = make_app(1000, 800)
    app.coordinator.client = MagicMock()
    app.coordinator.client.room_id = "room-1"
    payload = _online_start_payload(
        your_color="black", white_name="alice", black_name="bob",
        started_seconds_ago=0.0,
    )

    app.coordinator._begin_match_found_transition(payload)
    assert app.coordinator.match_found_modal.is_visible()
    assert app.coordinator._pending_game_start_payload == payload

    app.coordinator._finish_match_found()

    assert app.screen.name == "game"
    assert app.game.variant == "online"
    assert app.game._chosen_side == "black"
    assert app.game.white_name == "alice"
    assert app.game.black_name == "bob"
    assert app.coordinator._subscriber is app.game


def test_rematch_from_menu_window_end_to_end():
    app = _wired_app(white_name="alice", black_name="bob", your_color="white")
    client = app.coordinator.client
    app.game.manual_result = "white_wins_by_resignation"

    app._on_back_to_menu()
    assert app.screen.name == "menu"
    assert app.coordinator.client is client, "session retained for the rematch window"
    client.send_left_result.assert_called_once()
    assert app.coordinator._subscriber is None

    app.coordinator._handle_rematch_request()
    assert not app.coordinator.offer_banners.is_empty(), "rematch banner shows on the menu"
    assert app.game.result_menu.rematch_offered is True

    app.coordinator._accept_rematch()
    client.send_rematch_response.assert_called_once_with(True)

    fresh_payload = _online_start_payload(
        your_color="black", white_name="bob", black_name="alice",
        started_seconds_ago=0.0, rematch=True,
    )
    app.coordinator._begin_match_found_transition(fresh_payload)
    app.coordinator._finish_match_found()

    assert app.screen.name == "game"
    assert app.game.variant == "online"
    assert app.game._chosen_side == "black"
    assert app.coordinator._subscriber is app.game


def test_reconnect_available_reflects_the_pending_probe_result():
    app = make_app(1000, 800)
    assert app.coordinator.reconnect_available() is False
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000", "room_id": "room-1", "session_token": "tok",
    }
    assert app.coordinator.reconnect_available() is True


def test_reconnect_delegates_to_the_probe_glue(monkeypatch):
    app = make_app(1000, 800)
    called = []
    monkeypatch.setattr(app.coordinator, "_on_reconnect_active_game",
                        lambda: called.append(True))
    app.coordinator.reconnect()
    assert called == [True]


def test_coordinator_update_runs_before_screen_update(monkeypatch):
    app = start_single_screen(make_app(1000, 800))
    order = []

    real_coordinator_update = app.coordinator.update

    def coordinator_spy(now):
        order.append("coordinator")
        real_coordinator_update(now)

    real_screen_update = app.screen.update

    def screen_spy(now):
        order.append("screen")
        return real_screen_update(now)

    monkeypatch.setattr(app.coordinator, "update", coordinator_spy)
    monkeypatch.setattr(app.screen, "update", screen_spy)

    app.draw_frame()

    assert order == ["coordinator", "screen"]


def test_game_screen_on_app_exit_flushes_a_pending_result(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = start_single_screen(make_app(1000, 800))
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    app.game.manual_result = "white_wins_by_resignation"
    assert app.game.result_flow._last_saved_pgn_path is None

    app.game.on_app_exit()

    assert app.game.result_flow._last_saved_pgn_path is not None


def test_game_screen_on_app_exit_is_a_no_op_without_a_pending_result(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = start_single_screen(make_app(1000, 800))
    app.game.on_app_exit()
    assert app.game.result_flow._last_saved_pgn_path is None


def test_coordinator_on_app_exit_disconnects_the_client():
    app = make_app(1000, 800)
    client = MagicMock()
    app.coordinator.client = client
    app.coordinator.on_app_exit()
    client.disconnect.assert_called_once()


def test_coordinator_on_app_exit_is_a_no_op_with_no_client():
    app = make_app(1000, 800)
    app.coordinator.client = None
    app.coordinator.on_app_exit()
    assert app.coordinator.client is None


def test_run_teardown_fans_out_on_app_exit_to_every_screen_and_the_coordinator(monkeypatch):
    app = make_app(1000, 800)
    app.running = False
    calls = []
    for name, screen in app.screens.items():
        monkeypatch.setattr(screen, "on_app_exit", lambda name=name: calls.append(name))
    monkeypatch.setattr(app.coordinator, "on_app_exit", lambda: calls.append("coordinator"))
    monkeypatch.setattr(app.chrome, "shutdown", lambda: None)
    monkeypatch.setattr(pg, "quit", lambda: None)

    app.run()

    assert set(calls) == {"menu", "game", "history", "review", "coordinator"}


def test_search_cancel_on_menu_does_not_self_switch(caplog):
    """Cancelling matchmaking happens ON the menu screen (the wait modal covers
    it) — _return_to_menu_card must re-show the start card without a pointless
    menu -> menu exit/enter cycle polluting the lifecycle log."""
    app = make_app(1000, 800)
    app.start_menu.hide()
    menu = app.screen
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.coordinator._return_to_menu_card()
    assert app.screen is menu
    assert app.start_menu.is_visible() is True
    assert not any("screen switch" in r.getMessage() for r in caplog.records)


def test_return_to_menu_from_game_still_switches():
    app = start_single_screen(make_app(1000, 800))
    app.coordinator._return_to_menu_card()
    assert app.screen is app.menu
    assert app.start_menu.is_visible() is True
