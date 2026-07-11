"""ReviewScreen: PGN review is its own screen (legacy_mode="menu"), reached only
via Nav("review", {pgn_path, return_to}). Covers the real history-open entry
point, Esc/Menu-button return routing (both return_to targets), load failure,
self-switch reload cleanliness, arrow/Home/End stepping, the slim per-ply
capture strips, draw smoke at two window sizes, and the per-screen help subset.
GameScreen's own board.review_ply live-game browsing is untouched and stays
covered by test_review.py.
"""

import glob
import os

import pygame as pg

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import PieceType
from chessshootout.domain.pgn.generate import generate_pgn
from chessshootout.frontend.modals.help import HOTKEYS
from chessshootout.frontend.screens.base import Nav
from chessshootout.frontend.screens.review import REVIEW_HOTKEY_KEYS, REVIEW_HOTKEYS
from tests.helpers import make_app as _shared_make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def make_app():
    return _shared_make_app(1000, 800, mock_sound=False)


def _key(key, unicode=""):
    return pg.event.Event(pg.KEYDOWN, key=key, mod=0, unicode=unicode)


def _fire_animation(board):
    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


def _write_pgn(tmp_path, name, *, white="alice", black="bob", result="1-0",
               time_control="600+5", moves="1. e4 e5 2. Nf3 Nc6"):
    path = tmp_path / name
    path.write_text(
        f'[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n'
        f'[TimeControl "{time_control}"]\n\n{moves} {result}\n',
        encoding="utf-8",
    )
    return path


def _captures_pgn(tmp_path, name="captures.pgn"):
    backend = Backend()
    backend.new_game()
    for san in ["e4", "d5", "exd5"]:
        result = backend.apply_san(san)
        assert result.legal
    text = generate_pgn(backend.move_history, "white_wins_by_resignation",
                        white_name="alice", black_name="bob")
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _enter_review(app, path, return_to="history"):
    app.request_nav(Nav("review", {"pgn_path": str(path), "return_to": return_to}))
    app._execute_pending_nav()
    app._execute_pending_nav()
    return app


def test_open_review_from_history_via_real_open_call(tmp_path):
    path = _write_pgn(tmp_path, "local-20260101-120000.pgn")
    app = make_app()
    app._on_open_history()
    app._execute_pending_nav()
    assert app.screen.name == "history"

    app._open_pgn_review(str(path))
    app._execute_pending_nav()

    assert app.screen.name == "review"
    assert app.mode == "menu"
    assert app.review.board.review_ply == 0
    assert app.review.white_name == "alice"
    assert app.review.black_name == "bob"
    assert app.review.right_menu.game_info == {
        "mode": "Review", "time_control": "10+5", "lines": ["1-0"],
    }


def test_review_never_writes_a_pgn(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    app.draw_frame()
    app.review._on_menu()
    app._execute_pending_nav()
    assert glob.glob(os.path.join(str(paths.get_games_dir()), "*.pgn")) == []


def test_esc_on_review_returns_to_history_end_to_end(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    app._on_open_history()
    app._execute_pending_nav()
    _enter_review(app, path, return_to="history")
    assert app.screen.name == "review"

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_ESCAPE, "mod": 0, "unicode": ""}))
    app.input_router.check_events()
    app._execute_pending_nav()

    assert app.screen.name == "history"


def test_menu_button_returns_to_history(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path, return_to="history")
    assert app.screen.name == "review"
    app.review._on_menu()
    app._execute_pending_nav()
    assert app.screen.name == "history"


def test_return_to_menu_variant(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path, return_to="menu")
    assert app.screen.name == "review"
    assert app.review._return_to == "menu"

    app.review._on_menu()
    app._execute_pending_nav()
    assert app.screen.name == "menu"


def test_load_failure_toasts_and_returns_to_history(tmp_path):
    bad = tmp_path / "broken.pgn"
    bad.write_text('[White "x"]\n\n1. e4 zz9 *', encoding="utf-8")
    app = make_app()
    _enter_review(app, bad, return_to="history")
    assert app.screen.name == "history"
    assert app.toast.message == "Could not load PGN"


def test_load_failure_missing_file_returns_to_menu(tmp_path):
    missing = tmp_path / "nope.pgn"
    app = make_app()
    _enter_review(app, missing, return_to="menu")
    assert app.screen.name == "menu"
    assert app.toast.message == "Could not load PGN"


def test_self_switch_reload_shows_the_new_pgn(tmp_path):
    path_a = _write_pgn(tmp_path, "a.pgn", white="alice", black="bob",
                        moves="1. e4 e5")
    path_b = _write_pgn(tmp_path, "b.pgn", white="carol", black="dave",
                        moves="1. d4 d5 2. c4 c6")
    app = make_app()
    _enter_review(app, path_a)
    assert app.review.white_name == "alice"
    assert len(app.review.match.move_history) == 2

    _enter_review(app, path_b)
    assert app.screen.name == "review"
    assert app.review.white_name == "carol"
    assert app.review.black_name == "dave"
    assert len(app.review.match.move_history) == 4
    assert app.review.board.review_ply == 0


def test_arrow_stepping_mirrors_live_review_semantics(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn", moves="1. e4 e5 2. Nf3 Nc6")
    app = make_app()
    _enter_review(app, path)
    review = app.review

    assert review.board.review_ply == 0

    review.handle_key(_key(pg.K_LEFT))
    assert review.board.review_ply == 0
    assert review.board.animations == []

    review.handle_key(_key(pg.K_RIGHT))
    assert review.board.review_ply == 0
    assert len(review.board.animations) >= 1
    _fire_animation(review.board)
    assert review.board.review_ply == 1

    review.handle_key(_key(pg.K_END))
    assert review.board.review_ply is None

    review.handle_key(_key(pg.K_LEFT))
    assert review.board.review_ply == 3
    assert review.board.animations == []

    review.handle_key(_key(pg.K_HOME))
    assert review.board.review_ply == 0


def test_flip_key_flips_the_review_board(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    before = app.review.board.flipped
    app.review.handle_key(_key(pg.K_f))
    assert app.review.board.flipped != before


def test_slim_strip_captures_update_when_stepping(tmp_path):
    path = _captures_pgn(tmp_path)
    app = make_app()
    _enter_review(app, path)
    review = app.review
    review._update_strips()

    assert review.board.flipped is False
    assert review.strip_bottom.player_color.value == "white"
    assert review.strip_bottom.captured == []
    assert review.strip_bottom.advantage == 0

    review.board.jump_to_review_ply(None)
    review._update_strips()
    assert review.strip_bottom.captured == [PieceType.PAWN]
    assert review.strip_bottom.advantage == 1


def test_review_draw_smoke_at_two_window_sizes(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    app.draw_frame()

    app.window = pg.display.set_mode((1600, 1000))
    app.window_width, app.window_height = 1600, 1000
    app._compute_layout()
    app.draw_frame()
    assert app.review.board.rect.width > 0


def test_game_screen_unaffected_by_review_screen_existing(tmp_path):
    """Registering ReviewScreen must not touch GameScreen's own live-game
    board.review_ply browsing (owned entirely by GameScreen/board.py, still
    covered exhaustively in test_review.py)."""
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    assert app.screen.name == "review"

    app._on_start_game({
        "mode": "single_screen", "nickname": "alice",
        "time_minutes": 5, "increment_seconds": 0, "side": "white",
    })
    assert app.screen.name == "game"
    assert app.board.review_ply is None
    assert app.board is not app.review.board
    assert app.match is not app.review.match


def test_review_help_shows_navigation_subset(tmp_path):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    app.review.handle_key(_key(pg.K_SLASH, unicode="?"))
    assert app.help_modal.is_visible() is True
    assert app.help_modal.rows == REVIEW_HOTKEYS
    assert len(REVIEW_HOTKEYS) < len(HOTKEYS)
    shown_keys = {row[0] for row in REVIEW_HOTKEYS}
    assert shown_keys == set(REVIEW_HOTKEY_KEYS)


def test_game_help_shows_the_full_list():
    app = start_single_screen(make_app())
    app.input_router._handle_shortcut_key(_key(pg.K_SLASH, unicode="?"))
    assert app.help_modal.is_visible() is True
    assert app.help_modal.rows == HOTKEYS


def test_open_pgn_button_opens_the_loaded_file(tmp_path, monkeypatch):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    captured = {}
    monkeypatch.setattr(
        "chessshootout.frontend.screens.review.open_with_default_app",
        lambda p: captured.setdefault("path", p) or True,
    )
    app.review._on_open_pgn()
    assert captured["path"] == str(path)


def test_open_pgn_button_toasts_on_failure(tmp_path, monkeypatch):
    path = _write_pgn(tmp_path, "test.pgn")
    app = make_app()
    _enter_review(app, path)
    monkeypatch.setattr(
        "chessshootout.frontend.screens.review.open_with_default_app", lambda p: False,
    )
    app.review._on_open_pgn()
    assert app.toast.message == "Could not open PGN"
