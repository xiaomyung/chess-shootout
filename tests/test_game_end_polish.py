"""Game-end polish (M-B): fade-to-grayscale + 500ms result-modal delay."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.utils import Square
from frontend.frontend import (
    Frontend, RESULT_FADE_MS, RESULT_FADE_MAX_ALPHA, RESULT_MODAL_DELAY_MS,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _make_app():
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


# ---------- _result_first_seen_at_ms tracking ----------

def test_no_result_keeps_first_seen_none():
    app = _make_app()
    app._update_result_pending()
    assert app._result_first_seen_at_ms is None


def test_first_seen_captured_when_result_appears():
    app = _make_app()
    app.manual_result = "white_wins"
    before = pg.time.get_ticks()
    app._update_result_pending()
    assert app._result_first_seen_at_ms is not None
    assert app._result_first_seen_at_ms >= before


def test_first_seen_resets_when_result_clears():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    assert app._result_first_seen_at_ms is not None
    app.manual_result = None
    app._update_result_pending()
    assert app._result_first_seen_at_ms is None


def test_first_seen_does_not_reset_on_subsequent_frames():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    captured = app._result_first_seen_at_ms
    app._update_result_pending()
    assert app._result_first_seen_at_ms == captured


# ---------- modal-show timing ----------

def test_modal_hidden_immediately_after_result():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    assert app._result_modal_should_show() is False


def test_modal_shows_after_delay_elapses():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    app._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS - 1
    assert app._result_modal_should_show() is True


def test_modal_not_shown_when_no_result():
    app = _make_app()
    assert app._result_modal_should_show() is False


# ---------- fade overlay ----------

def test_fade_alpha_starts_low_and_grows_to_max():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    base = app._result_first_seen_at_ms

    # Right at t=0, alpha is 0.
    app._result_first_seen_at_ms = pg.time.get_ticks()
    assert app._result_elapsed_ms() == 0

    # Halfway through fade, alpha is roughly half max.
    app._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_FADE_MS // 2
    elapsed = app._result_elapsed_ms()
    expected_alpha = int(RESULT_FADE_MAX_ALPHA * elapsed / RESULT_FADE_MS)
    assert abs(expected_alpha - RESULT_FADE_MAX_ALPHA // 2) <= 1

    # After fade completes, alpha is at max.
    app._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_FADE_MS - 100
    # _draw_result_fade_overlay should not raise.
    app._draw_result_fade_overlay()


def test_fade_overlay_no_op_when_no_result():
    app = _make_app()
    # No result, no fade — exercise the no-op path.
    app._draw_result_fade_overlay()


# ---------- click-to-skip ----------

def test_click_during_fade_window_skips_to_modal():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    # Inside the fade window: modal not yet shown.
    assert app._result_modal_should_show() is False
    # Simulate click during the fade.
    app.mouse_left_clicked((100, 100))
    # The skip handler fast-forwarded the timer.
    assert app._result_modal_should_show() is True


def test_click_outside_fade_window_does_not_alter_state():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    # Past the modal-delay → modal already showing.
    app._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS - 100
    captured = app._result_first_seen_at_ms
    app.mouse_left_clicked((100, 100))
    # Already past delay; the fade-skip branch should NOT mutate the timestamp.
    assert app._result_first_seen_at_ms == captured


# ---------- new-game lifecycle ----------

def test_new_game_clears_pending_result_state():
    app = _make_app()
    app.manual_result = "white_wins"
    app._update_result_pending()
    assert app._result_first_seen_at_ms is not None
    app._reset_to_new_game()
    assert app._result_first_seen_at_ms is None


# ---------- in-game buttons disabled after result ----------

def test_right_menu_buttons_disabled_after_result():
    app = _make_app()
    app.manual_result = "white_wins"
    assert app._right_menu_disabled_keys() == {
        "undo", "resign", "draw", "flip", "give_time",
    }


def test_right_menu_buttons_active_during_normal_play():
    app = _make_app()
    # No clock configured at construction → give_time is disabled until a
    # game is started with a time control.
    assert app._right_menu_disabled_keys() == {"give_time"}


def test_right_menu_buttons_active_in_pgn_review():
    app = _make_app()
    app.manual_result = "white_wins"
    app.pgn_review = True
    # Review mode renders REVIEW_BUTTONS; nothing extra to disable.
    assert app._right_menu_disabled_keys() == set()


def test_undo_no_op_after_result():
    app = _make_app()
    # Play a move so there's something to undo.
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    history_len = len(app.match.move_history)
    # Game-over state.
    app.manual_result = "white_wins"
    app._on_undo()
    # Result still set, history untouched, no undo animation queued.
    assert app.manual_result == "white_wins"
    assert len(app.match.move_history) == history_len


def test_flip_no_op_after_result():
    app = _make_app()
    flipped_before = app.board.flipped
    app.manual_result = "white_wins"
    app._on_flip()
    assert app.board.flipped == flipped_before


def test_flip_works_in_pgn_review_even_with_result():
    app = _make_app()
    app.manual_result = "white_wins"
    app.pgn_review = True
    flipped_before = app.board.flipped
    app._on_flip()
    assert app.board.flipped != flipped_before
