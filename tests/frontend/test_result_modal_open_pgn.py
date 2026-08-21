"""Result-modal Open PGN availability (v2.12.1).

The old modal always offered Open PGN and let the click fall through to a
toast when nothing was ever saved (silent save-failure latch, zero-ply static
results, the finalize-after-modal ordering hole). These tests pin the new
semantics end-to-end through the real screen: the button exists exactly when
an on-disk, non-empty PGN exists; a game whose saves hard-failed re-toasts a
distinct "not saved" line once at result time; and while the match-found
modal is up the InputRouter hands every click to that global modal, so the
result menu's stale button rects never see it.
"""

import os

import pytest

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.frontend.game.result_flow import GAME_NOT_SAVED_MESSAGE, SAVE_FAILED_MESSAGE
from tests.helpers import (
    BLACK, K, P, R, WHITE, make_app, make_backend, piece, sq, start_single_screen,
)


_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Every test here writes PGNs, so the data dir must be redirected BEFORE the
    shell boots -- paths resolves the games dir off the env at construction."""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    return make_app()


@pytest.fixture
def local_app(app):
    start_single_screen(app)
    return app


def _back_rank_mate_board(app):
    """White Ra1, Ke1; Black Kh8 boxed in by its own g7/h7 pawns. Ra8# is a
    non-capture mate, so no skill-check machinery and no capture effects get
    between the move and the result modal."""
    app.game.match.backend = make_backend({
        sq(0, 7): piece(K, BLACK), sq(1, 6): piece(P, BLACK), sq(1, 7): piece(P, BLACK),
        sq(7, 0): piece(R, WHITE), sq(7, 4): piece(K, WHITE),
    }, turn=WHITE)


def _finish_game_and_show_modal(app):
    _back_rank_mate_board(app)
    app.game.match.try_move(sq(7, 0), sq(0, 0))
    assert app.game.current_result() == "white_wins"
    app.draw_frame()
    app.game._skip_result_fade()
    app.draw_frame()
    return app.game.result_menu.button_rects


def test_normal_game_offers_open_pgn_and_click_opens_the_saved_file(local_app, monkeypatch):
    app = local_app
    rects = _finish_game_and_show_modal(app)
    assert "open_pgn" in rects, "a saved game's modal must offer Open PGN"
    opened = []
    monkeypatch.setattr("chessshootout.frontend.pgn_open.open_with_default_app",
                        lambda path, on_failure=None: opened.append(path) or True)
    app.game.handle_click(rects["open_pgn"].center)
    assert opened == [app.game.result_flow._last_saved_pgn_path]
    assert os.path.getsize(opened[0]) > 0, "the opener received a real, non-empty file"


def test_save_failure_game_hides_open_pgn(local_app, tmp_path, monkeypatch):
    app = local_app
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: tmp_path / "fallback")
    app.game.result_flow._write_pgn_atomic = lambda path, text: "hard_failure"
    rects = _finish_game_and_show_modal(app)
    assert app.game.result_flow._last_saved_pgn_path is None
    assert "open_pgn" not in rects, "nothing on disk, no Open PGN button"
    assert "new_game" in rects and "menu" in rects


def test_zero_ply_static_result_hides_open_pgn(app):
    """A first-move abort arrives as a server result on an online game -- the
    only variant where a static zero-ply result is reachable. Delivered through
    the same _apply_online_result path production uses, nothing is on disk and
    the modal must not offer Open PGN."""
    app.coordinator._start_online_game({
        "white_name": "alice", "black_name": "bob", "your_color": "white",
        "time_minutes": 5, "increment_seconds": 0,
        "white_country": "", "black_country": "",
        "white_score": 0.0, "black_score": 0.0,
    })
    app.coordinator._handle_online_result({"reason": "aborted"})
    assert app.game.manual_result == "aborted"
    assert app.game.match.move_history == []
    app.game.result_flow.feed_result_menu()
    app.game.result_menu.draw()
    assert "open_pgn" not in app.game.result_menu.button_rects
    assert "menu" in app.game.result_menu.button_rects


def test_match_found_modal_intercepts_clicks_before_the_result_menu(local_app, monkeypatch):
    """The draw path hides the result modal while the match-found modal is up,
    but button_rects from the last drawn frame survive. The protection is the
    InputRouter: it hands every click to the topmost visible global modal, so
    the click lands in the match-found modal and the stale rects never fire."""
    app = local_app
    rects = _finish_game_and_show_modal(app)
    opened = []
    monkeypatch.setattr("chessshootout.frontend.pgn_open.open_with_default_app",
                        lambda path, on_failure=None: opened.append(path) or True)
    app.coordinator.match_found_modal.show("alice", "bob", "white", on_done=lambda: None)
    top = app.input_router._top_visible_modal()
    assert top is not None and top.modal is app.coordinator.match_found_modal
    landed = []
    monkeypatch.setattr(app.coordinator.match_found_modal, "handle_click",
                        lambda pos: landed.append(pos) or False)
    app.input_router.mouse_left_clicked(rects["open_pgn"].center)
    assert landed == [rects["open_pgn"].center], "the router routed it to the modal"
    assert opened == [], "the suppressed result menu never saw the click"
    app.coordinator.match_found_modal.hide()
    app.input_router.mouse_left_clicked(rects["open_pgn"].center)
    assert opened != [], "the same click works again once the modal is gone"


def test_finalize_failure_retoasts_once_at_result(local_app, tmp_path, monkeypatch):
    """The mid-game save-error toast latch fires once ~1s into the game and
    then goes quiet; the player who plays on deserves a second, distinct toast
    at result time saying the finished game is not on disk -- exactly once,
    however many frames repeat on_result_final afterwards."""
    app = local_app
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: tmp_path / "fallback")
    app.game.result_flow._write_pgn_atomic = lambda path, text: "hard_failure"
    shown = []
    monkeypatch.setattr(app.toast, "show", lambda msg, *a, **k: shown.append(msg))
    app.game.match.try_move(sq(6, 4), sq(4, 4))
    app.game.result_flow._update_incremental_autosave()
    assert SAVE_FAILED_MESSAGE in shown, "the mid-game latch toast fired"
    assert GAME_NOT_SAVED_MESSAGE not in shown

    app.game.manual_result = "white_wins_by_resignation"
    app.game.result_flow.update_result_pending()
    assert shown.count(GAME_NOT_SAVED_MESSAGE) == 1, "distinct re-toast despite the latch"
    app.game.result_flow.update_result_pending()
    app.game.result_flow.on_result_final("white_wins_by_resignation")
    assert shown.count(GAME_NOT_SAVED_MESSAGE) == 1, "the re-toast fires exactly once"
