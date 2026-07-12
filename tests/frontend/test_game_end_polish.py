"""Game-end polish (M-B): fade-to-grayscale + 500ms result-modal delay.

The fade tests block-diff a known-bright window region: _draw_result_fade_overlay
blits a black (0,0,0,alpha) SRCALPHA overlay, so a white pixel darkens to exactly
255 - alpha. alpha ramps 0 -> RESULT_FADE_MAX_ALPHA over RESULT_FADE_MS.
"""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.screens.game import (
    RESULT_FADE_MS, RESULT_FADE_MAX_ALPHA, RESULT_MODAL_DELAY_MS,
)
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def _make_app():
    return start_single_screen(make_app(1000, 800), nickname="a",
                               time_minutes=None, increment_seconds=5, side="white")


_PROBE = (10, 10)


def _fade_probe_after_white(app):
    app.window.fill((255, 255, 255))
    app.game._draw_result_fade_overlay()
    return app.window.get_at(_PROBE)


def test_no_result_keeps_first_seen_none():
    app = _make_app()
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is None


def test_first_seen_captured_when_result_appears():
    app = _make_app()
    app.game.manual_result = "white_wins"
    before = pg.time.get_ticks()
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is not None
    assert app.game._result_first_seen_at_ms >= before


def test_first_seen_resets_when_result_clears():
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is not None
    app.game.manual_result = None
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is None


def test_first_seen_does_not_reset_on_subsequent_frames():
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()
    captured = app.game._result_first_seen_at_ms
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms == captured


def test_online_result_defers_first_seen_until_board_settles():
    """An online result arriving mid-animation must not stamp the modal clock until the
    final move visually settles, so the modal never pops over a still-moving board."""
    app = _make_app()
    app.game.variant = "online"
    app.game.white_name, app.game.black_name = "alice", "bob"
    app.game.board.effects.captures = [object()]
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.game.manual_result == "white_wins"
    assert app.game._result_first_seen_at_ms is None
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is None
    app.game.board.effects.captures = []
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is not None


def test_modal_hidden_immediately_after_result():
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()
    assert app.game._result_modal_should_show() is False


def test_modal_shows_after_delay_elapses():
    app = _make_app()
    app.game.manual_result = "white_wins_on_time"
    app.game.result_flow.update_result_pending()
    app.game._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS - 1
    assert app.game._result_modal_should_show() is True


def test_modal_not_shown_when_no_result():
    app = _make_app()
    assert app.game._result_modal_should_show() is False


def test_fade_alpha_starts_low_and_grows_to_max(monkeypatch):
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 10_000_000)
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()

    app.game._result_first_seen_at_ms = pg.time.get_ticks()
    assert app.game._result_elapsed_ms() == 0
    assert tuple(_fade_probe_after_white(app)) == (255, 255, 255, 255)

    app.game._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_FADE_MS // 2
    elapsed = app.game._result_elapsed_ms()
    expected_alpha = int(RESULT_FADE_MAX_ALPHA * elapsed / RESULT_FADE_MS)
    assert abs(expected_alpha - RESULT_FADE_MAX_ALPHA // 2) <= 1
    half = _fade_probe_after_white(app)
    assert half.r == half.g == half.b == 255 - expected_alpha

    app.game._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_FADE_MS - 100
    maxed = _fade_probe_after_white(app)
    assert maxed.r == maxed.g == maxed.b == 255 - RESULT_FADE_MAX_ALPHA


def test_fade_overlay_no_op_when_no_result():
    """No result: the overlay must not paint and first-seen stays None;
    once a result lands and the fade completes it darkens the window."""
    app = _make_app()

    assert app.game._result_first_seen_at_ms is None
    assert _fade_probe_after_white(app) == pg.Color(255, 255, 255, 255)
    assert app.game._result_first_seen_at_ms is None

    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()
    app.game._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_FADE_MS - 100
    darkened = _fade_probe_after_white(app)
    assert darkened.r == darkened.g == darkened.b == 255 - RESULT_FADE_MAX_ALPHA
    assert darkened.r < 255


def test_click_during_fade_window_skips_to_modal():
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()
    assert app.game._result_modal_should_show() is False
    app.input_router.mouse_left_clicked((100, 100))
    assert app.game._result_modal_should_show() is True


def test_click_outside_fade_window_does_not_alter_state():
    app = _make_app()
    app.game.manual_result = "white_wins_on_time"
    app.game.result_flow.update_result_pending()
    app.game._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS - 100
    captured = app.game._result_first_seen_at_ms
    app.input_router.mouse_left_clicked((100, 100))
    assert app.game._result_first_seen_at_ms == captured


def test_new_game_clears_pending_result_state():
    app = _make_app()
    app.game.manual_result = "white_wins"
    app.game.result_flow.update_result_pending()
    assert app.game._result_first_seen_at_ms is not None
    app.game._reset_to_new_game()
    assert app.game._result_first_seen_at_ms is None


def _show_result_with_menu_center(app, result="white_wins"):
    app.game.manual_result = result
    app.game.result_flow.update_result_pending()
    app.game.board.effects.clear_takeover()
    app.game._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS - 1
    assert app.game._result_modal_should_show() is True
    app._compute_layout()
    app.game.result_flow.feed_result_menu()
    app.game.result_menu.draw()
    assert app.game.result_menu.is_visible() is True
    assert app.game.result_menu.button_rects
    return app.game.result_menu.button_rects["menu"].center


def test_stale_result_menu_not_clickable_after_new_game():
    """RC1: result-modal buttons must not survive into the next game. After finishing a
    game and resetting, a board click landing on the old 'Menu' rect must not quit."""
    app = _make_app()
    menu_center = _show_result_with_menu_center(app)
    app.game._reset_to_new_game()
    assert app.game.result_menu.is_visible() is False
    app.input_router.mouse_left_clicked(menu_center)
    assert app.screen is not app.menu


def test_drag_release_after_game_over_skips_router():
    """RC2: a drag whose release lands after the game ended must not re-dispatch the
    click into the UI router (which would hit the result modal's Menu button)."""
    app = _make_app()
    app.game.board.dragging_from = Square(6, 4)
    app.game.manual_result = "white_wins"
    calls = []
    app.input_router.mouse_left_clicked = lambda pos, **kwargs: calls.append(pos)
    app.input_router._mouse_left_released((100, 100))
    assert calls == []
    assert app.game.board.dragging_from is None


def test_drag_release_during_live_game_routes_click():
    """RC2 guard must not regress a normal drag-move: with no result the release still
    re-dispatches so a drag that delivers the game-ending move completes."""
    app = _make_app()
    app.game.board.dragging_from = Square(6, 4)
    calls = []
    app.input_router.mouse_left_clicked = lambda pos, **kwargs: calls.append(pos)
    app.input_router._mouse_left_released((100, 100))
    assert calls == [(100, 100)]


def test_drag_release_after_game_over_does_not_quit_to_menu():
    """RC2 end-to-end: releasing a dragged piece over the result modal's Menu button
    right after a mid-drag game-end must not quit to menu."""
    app = _make_app()
    menu_center = _show_result_with_menu_center(app)
    app.game.board.dragging_from = Square(6, 4)
    app.input_router._mouse_left_released(menu_center)
    assert app.screen is not app.menu


def test_legit_result_menu_button_still_quits():
    """Regression: an intentional click on the visible result modal's Menu button must
    still return to the menu."""
    app = _make_app()
    menu_center = _show_result_with_menu_center(app)
    assert app.game.result_menu.is_visible() is True
    app.input_router.mouse_left_clicked(menu_center)
    assert app.screen is app.menu


def test_result_modal_reappears_in_next_game():
    """Regression: clearing the menu on new-game must not stop the modal showing when the
    next game actually ends."""
    app = _make_app()
    _show_result_with_menu_center(app)
    app.game._reset_to_new_game()
    assert app.game.result_menu.is_visible() is False
    _show_result_with_menu_center(app, result="black_wins")
    assert app.game.result_menu.is_visible() is True
    assert app.game.result_menu.button_rects


def test_right_menu_buttons_disabled_after_result():
    app = _make_app()
    app.game.manual_result = "white_wins"
    assert app.game._right_menu_disabled_keys() == {
        "undo", "resign", "draw", "flip", "give_time",
    }


def test_right_menu_buttons_active_during_normal_play():
    """No clock at construction, so only give_time stays disabled."""
    app = _make_app()
    assert app.game._right_menu_disabled_keys() == {"give_time"}


def test_undo_no_op_after_result():
    app = _make_app()
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    history_len = len(app.game.match.move_history)
    app.game.manual_result = "white_wins"
    app.game._on_undo()
    assert app.game.manual_result == "white_wins"
    assert len(app.game.match.move_history) == history_len


def test_flip_no_op_after_result():
    app = _make_app()
    flipped_before = app.game.board.flipped
    app.game.manual_result = "white_wins"
    app.game._on_flip()
    assert app.game.board.flipped == flipped_before
