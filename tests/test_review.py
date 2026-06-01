import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.backend import Backend
from backend.pieces import PieceColor, PieceType
from backend.utils import Square
from frontend.board import Board


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1500, 800))
    yield
    pg.quit()


@pytest.fixture
def board():
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def _new_app():
    from frontend.frontend import Frontend
    app = Frontend(1500, 800)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


def _play_e4_e5_nf3(app):
    for from_sq, to_sq in [
        (Square(6, 4), Square(4, 4)),
        (Square(1, 4), Square(3, 4)),
        (Square(7, 6), Square(5, 5)),
    ]:
        app.backend.try_move(from_sq, to_sq)


def fire_animation(board):
    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


def test_position_at_zero_returns_starting_layout():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    grid = backend.position_at(0)
    assert grid[6][4].type == PieceType.PAWN
    assert grid[4][4] is None


def test_position_at_full_history_returns_live_state():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 4), Square(3, 4))
    grid = backend.position_at(2)
    assert grid[4][4].type == PieceType.PAWN
    assert grid[3][4].type == PieceType.PAWN


def test_position_at_intermediate():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 4), Square(3, 4))
    backend.try_move(Square(7, 6), Square(5, 5))
    grid = backend.position_at(1)
    assert grid[4][4].type == PieceType.PAWN
    assert grid[1][4].type == PieceType.PAWN
    assert grid[7][6].type == PieceType.KNIGHT


def test_position_at_does_not_mutate_live_state():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 4), Square(3, 4))
    live_before = [[(p.type, p.color) if p else None for p in row]
                   for row in backend.state]
    backend.position_at(0)
    backend.position_at(1)
    live_after = [[(p.type, p.color) if p else None for p in row]
                  for row in backend.state]
    assert live_before == live_after
    assert len(backend.move_history) == 2


def test_position_at_out_of_range_raises():
    backend = Backend()
    backend.new_game()
    with pytest.raises(ValueError):
        backend.position_at(-1)
    with pytest.raises(ValueError):
        backend.position_at(99)


def test_review_ply_default_is_none(board):
    assert board.review_ply is None


def test_draw_pieces_uses_historical_grid_in_review_mode():
    """At review ply 0 draw_pieces blits the starting layout, not live state.

    draw_pieces calls _cell_rect exactly once per occupied historical cell, so
    spying on it yields the set of squares blitted. At ply 0 the starting layout
    has rows 0,1,6,7 full and rows 2-5 empty — the e4 cell the live game moved a
    pawn to must NOT be blitted, while e2 (the pawn's home) must be.
    """
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 4), Square(3, 4))
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    bd.review_ply = 0
    visited = []
    original = bd._cell_rect
    bd._cell_rect = lambda r, c: visited.append((r, c)) or original(r, c)
    bd.draw_pieces()
    bd._cell_rect = original
    blitted = set(visited)
    expected = {(r, c) for r in (0, 1, 6, 7) for c in range(8)}
    assert blitted == expected
    assert (4, 4) not in blitted
    assert (6, 4) in blitted


def test_review_disables_handle_click(board):
    board.review_ply = 0
    board.handle_click(Square(6, 4))
    assert board.selected_square is None


def test_review_disables_drag_motion(board):
    board.review_ply = 0
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from is None


def test_premove_fire_resets_review_ply():
    """A premove queued before review fires on turn match and clears review_ply."""
    app = _new_app()
    _play_e4_e5_nf3(app)
    assert app.backend.current_turn() == PieceColor.BLACK
    app.board.handle_click(Square(6, 3))
    app.board.handle_click(Square(4, 3))
    assert len(app.board.premoves) == 1
    app.board.review_ply = 1
    app.backend.turn = PieceColor.WHITE
    fired = app.board.try_apply_next_premove()
    assert fired is True
    assert app.board.review_ply is None


def test_start_move_animation_clears_review_ply():
    """The _start_move_animation seam always clears review_ply."""
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    backend.try_move(Square(6, 4), Square(4, 4))
    bd.review_ply = 0
    bd._start_move_animation(Square(6, 4), Square(4, 4), False)
    assert bd.review_ply is None


def test_undo_resets_review_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    app._on_undo()
    assert app.board.review_ply is None


def test_new_game_resets_review_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 0
    app._on_new_game()
    assert app.board.review_ply is None


def test_left_arrow_steps_back_no_animation():
    """Backward step jumps instantly (no animation)."""
    app = _new_app()
    _play_e4_e5_nf3(app)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_LEFT, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply == 2
    assert app.board.animations == []


def test_right_arrow_steps_forward_with_animation():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_RIGHT, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply == 1
    assert len(app.board.animations) >= 1
    fire_animation(app.board)
    assert app.board.review_ply == 2


def test_right_arrow_to_last_ply_animates_to_live():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 2
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_RIGHT, mod=0)
    app._handle_shortcut_key(event)
    assert len(app.board.animations) >= 1
    fire_animation(app.board)
    assert app.board.review_ply is None


def test_spamming_right_arrow_advances_each_press():
    """Bug guard: forward-arrow spam advances one ply per press while animating."""
    app = _new_app()
    for from_sq, to_sq in [
        (Square(6, 4), Square(4, 4)),
        (Square(1, 4), Square(3, 4)),
        (Square(7, 6), Square(5, 5)),
        (Square(0, 1), Square(2, 2)),
        (Square(7, 5), Square(4, 2)),
    ]:
        app.backend.try_move(from_sq, to_sq)
    app.board.review_ply = 0
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_RIGHT, mod=0)
    app._handle_shortcut_key(event)
    assert app.board._target_ply == 1
    app._handle_shortcut_key(event)
    assert app.board._target_ply == 2
    app._handle_shortcut_key(event)
    assert app.board._target_ply == 3
    fire_animation(app.board)
    assert app.board.review_ply == 3


def test_spamming_animate_review_ply_snaps_previous():
    """animate_review_ply(N) while animating to M snaps M before starting toward N."""
    app = _new_app()
    for from_sq, to_sq in [
        (Square(6, 4), Square(4, 4)),
        (Square(1, 4), Square(3, 4)),
        (Square(7, 6), Square(5, 5)),
        (Square(0, 1), Square(2, 2)),
    ]:
        app.backend.try_move(from_sq, to_sq)
    app.board.animate_review_ply(2)
    assert app.board._target_ply == 2
    app.board.animate_review_ply(3)
    assert app.board.review_ply == 2
    assert app.board._target_ply == 3


def test_home_jumps_to_ply_zero():
    app = _new_app()
    _play_e4_e5_nf3(app)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_HOME, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply == 0


def test_end_returns_to_live():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 0
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_END, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply is None


def test_esc_does_not_modify_review_ply():
    """Esc closes the window; it must NOT affect review state."""
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_ESCAPE, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply == 1


def test_left_does_not_overflow():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 0
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_LEFT, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply == 0


def test_arrows_noop_when_history_empty():
    app = _new_app()
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_LEFT, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.review_ply is None


@pytest.mark.parametrize(
    "hit_index, expected_ply",
    [
        pytest.param(0, 1, id="white_cell_jumps_to_white_ply"),
        pytest.param(1, 2, id="black_cell_jumps_to_black_ply"),
    ],
)
def test_clicking_move_cell_jumps_directly_to_that_ply(hit_index, expected_ply):
    """Clicks land the selector on the clicked ply: no animation, no ply-1 flash."""
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.draw_frame()
    hits = app.right_menu._move_cell_hits
    cell_rect, ply = hits[hit_index]
    assert ply == expected_ply
    app.right_menu.handle_click(cell_rect.center)
    assert app.board.review_ply == expected_ply
    assert app.board._target_ply is None
    assert app.board.animations == []


def test_clicking_latest_move_returns_to_live():
    """Clicking the last move cell snaps directly to live (review_ply=None)."""
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    app.draw_frame()
    hits = app.right_menu._move_cell_hits
    cell_rect, ply = hits[-1]
    assert ply == len(app.backend.move_history)
    app.right_menu.handle_click(cell_rect.center)
    assert app.board.review_ply is None
    assert app.board.animations == []


def test_clicking_a_distant_move_never_transiently_lands_on_predecessor():
    """Regression: clicks never touch ply-1; the selector lands on the chosen move."""
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 0
    app.draw_frame()
    hits = app.right_menu._move_cell_hits
    cell_rect, ply = hits[-1]
    app.right_menu.handle_click(cell_rect.center)
    assert app.board.animations == []
    assert app.board._target_ply is None
    assert app.board.review_ply == ply or app.board.review_ply is None


def test_animate_review_ply_starts_animation_from_correct_squares():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.animate_review_ply(3)
    assert len(app.board.animations) == 1
    a = app.board.animations[0]
    assert a.from_sq == Square(7, 6)
    assert a.to_sq == Square(5, 5)


def test_animate_to_ply_zero_jumps_no_animation():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.animate_review_ply(0)
    assert app.board.review_ply == 0
    assert app.board.animations == []


def test_animate_to_latest_ply_animates_then_lands_live():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    app.board.animate_review_ply(len(app.backend.move_history))
    assert app.board.review_ply == len(app.backend.move_history) - 1
    assert len(app.board.animations) >= 1
    fire_animation(app.board)
    assert app.board.review_ply is None


def test_animate_review_ply_past_history_jumps_to_live():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    app.board.animate_review_ply(len(app.backend.move_history) + 1)
    assert app.board.review_ply is None
    assert app.board.animations == []


def test_strip_state_captures_track_review_ply():
    """Player-strip material reflects the reviewed ply, not the final position.

    1.e4 d5 2.exd5: white captures a black pawn at ply 3. Live and ply-3 strips
    show the capture; reviewing ply 2 (before it) shows none.
    """
    app = _new_app()
    app.backend.try_move(Square(6, 4), Square(4, 4))
    app.backend.try_move(Square(1, 3), Square(3, 3))
    app.backend.try_move(Square(4, 4), Square(3, 3))

    state = app._strip_state(PieceColor.WHITE, app.backend.current_turn(), False)
    assert len(state["captured"]) == 1
    assert state["advantage"] == 1

    app.board.review_ply = 2
    state = app._strip_state(PieceColor.WHITE, app.backend.current_turn(), False)
    assert state["captured"] == []
    assert state["advantage"] == 0

    app.board.review_ply = 3
    state = app._strip_state(PieceColor.WHITE, app.backend.current_turn(), False)
    assert len(state["captured"]) == 1
    assert state["advantage"] == 1


def test_last_move_highlight_in_review_targets_reviewed_move():
    """At review ply N the highlight marks move N (history[N-1]); at ply 0 nothing."""
    app = _new_app()
    app.backend.try_move(Square(6, 4), Square(4, 4))
    app.backend.try_move(Square(1, 3), Square(3, 3))
    app.backend.try_move(Square(4, 4), Square(3, 3))
    app.board.review_ply = 1
    move = app.match.move_history[app.board.review_ply - 1].move
    assert move.from_sq == Square(6, 4)
    assert move.to_sq == Square(4, 4)

    visited = []
    original = app.board._cell_rect
    app.board._cell_rect = lambda r, c: visited.append((r, c)) or original(r, c)
    app.board._draw_last_move_highlight()
    assert set(visited) == {(6, 4), (4, 4)}

    visited.clear()
    app.board.review_ply = 0
    app.board._draw_last_move_highlight()
    app.board._cell_rect = original
    assert visited == []


def test_active_row_highlight_in_live_mode_is_last_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.draw_frame()
    assert app.right_menu._active_ply(len(app.backend.move_history)) == 3


def test_active_row_highlight_follows_review_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    assert app.right_menu._active_ply(3) == 1


def test_load_pgn_button_disabled_when_no_pgn(tmp_path, monkeypatch):
    """An empty data dir leaves the Load PGN button disabled."""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = _new_app_in_isolated_root(tmp_path)
    app.start_menu.show()
    app._refresh_load_pgn_availability()
    assert app.start_menu.load_pgn_available is False


def test_load_pgn_button_enabled_when_pgn_exists(tmp_path, monkeypatch):
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "game-20250101-120000.pgn").write_text(
        '[White "A"]\n[Black "B"]\n\n1. e4 e5 *\n'
    )
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = _new_app_in_isolated_root(tmp_path)
    app._refresh_load_pgn_availability()
    assert app.start_menu.load_pgn_available is True


def test_load_pgn_picks_most_recent_by_mtime(tmp_path, monkeypatch):
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    older = games_dir / "game-old.pgn"
    older.write_text('[White "A"]\n\n1. e4 e5 *\n')
    newer = games_dir / "game-new.pgn"
    newer.write_text('[White "A"]\n\n1. d4 d5 *\n')
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = _new_app_in_isolated_root(tmp_path)
    path = app._latest_pgn_path()
    assert path is not None
    assert path.endswith("game-new.pgn")


def test_history_and_fen_ghosts_below_start():
    app = _new_app()
    app.start_menu.show()
    app.start_menu.draw()
    sm = app.start_menu
    assert sm._history_rect.x < sm._fen_rect.x
    assert abs(sm._history_rect.width - sm._fen_rect.width) <= 2
    assert sm._history_rect.top >= sm._start_rect.bottom


def test_load_pgn_from_path_loads_game(tmp_path):
    pgn_path = tmp_path / "test.pgn"
    pgn_path.write_text('[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 Nc6 *\n')
    app = _new_app()
    app._load_pgn_from_path(str(pgn_path))
    assert len(app.backend.move_history) == 4
    assert app.board.review_ply == 0
    assert app.mode == "single_screen"
    assert app.pgn_review is True


def test_load_pgn_populates_names_and_time_control(tmp_path):
    pgn_path = tmp_path / "named.pgn"
    pgn_path.write_text(
        '[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n[TimeControl "600+5"]\n\n'
        "1. e4 e5 1-0\n"
    )
    app = _new_app()
    app._load_pgn_from_path(str(pgn_path))
    assert app.white_name == "alice"
    assert app.black_name == "bob"
    assert app._time_control == (600, 5)
    assert app._name_for_color(PieceColor.WHITE) == "alice"
    assert app._name_for_color(PieceColor.BLACK) == "bob"
    assert app._compute_game_info() == {
        "mode": "Review", "time_control": "10+5", "round": 1, "lines": ["1-0"],
    }


def test_load_pgn_without_time_control_shows_infinity(tmp_path):
    pgn_path = tmp_path / "noclock.pgn"
    pgn_path.write_text(
        '[White "A"]\n[Black "B"]\n[Result "0-1"]\n\n1. e4 e5 0-1\n'
    )
    app = _new_app()
    app._load_pgn_from_path(str(pgn_path))
    assert app._time_control is None
    assert app._compute_game_info() == {
        "mode": "Review", "time_control": "∞", "round": 1, "lines": ["0-1"],
    }


def _load_test_pgn(app, tmp_path):
    pgn_path = tmp_path / "test.pgn"
    pgn_path.write_text('[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 Nc6 *\n')
    app._load_pgn_from_path(str(pgn_path))


def test_undo_disabled_in_pgn_review(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    history_before = len(app.backend.move_history)
    app._on_undo()
    assert len(app.backend.move_history) == history_before


def test_resign_disabled_in_pgn_review(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    app._on_resign()
    assert app.confirm_modal.is_visible() is False
    assert app.manual_result is None


def test_draw_disabled_in_pgn_review(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    app._on_draw()
    assert app.confirm_modal.is_visible() is False
    assert app.manual_result is None


def test_pgn_load_marks_board_read_only(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    assert app.board.read_only is True


def test_read_only_blocks_handle_click(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    app.board.review_ply = None
    app.board.handle_click(Square(6, 4))
    assert app.board.selected_square is None


def test_read_only_blocks_drag(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    app.board.review_ply = None
    app.board.begin_press((50, 50))
    app.board.update_drag_motion((100, 100))
    assert app.board.dragging_from is None


def test_new_game_clears_read_only(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    app._on_new_game()
    assert app.board.read_only is False


def _flat_button_keys(rows):
    return {key for row in rows for _, key in row}


def test_pgn_review_shows_only_menu_and_flip_buttons(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    assert _flat_button_keys(app._right_menu_buttons()) == {"menu", "flip", "help"}


def test_timed_mode_shows_full_buttons():
    app = _new_timed_app()
    assert _flat_button_keys(app._right_menu_buttons()) == {
        "undo", "resign", "draw", "give_time", "flip", "help",
    }


def test_timed_mode_buttons_are_two_rows_of_three():
    """Layout pin: two rows of three buttons so the audio slider grid lines up."""
    app = _new_timed_app()
    rows = app._right_menu_buttons()
    assert len(rows) == 2
    assert [key for _, key in rows[0]] == ["undo", "resign", "draw"]
    assert [key for _, key in rows[1]] == ["give_time", "flip", "help"]


def test_untimed_mode_hides_give_time():
    """No clock → no give-time button; row two collapses to Flip / Help."""
    app = _new_app()
    rows = app._right_menu_buttons()
    assert len(rows) == 2
    assert [key for _, key in rows[0]] == ["undo", "resign", "draw"]
    assert [key for _, key in rows[1]] == ["flip", "help"]


def test_review_mode_is_one_row():
    app = _new_app()
    app.pgn_review = True
    rows = app._right_menu_buttons()
    assert len(rows) == 1
    assert [key for _, key in rows[0]] == ["menu", "flip", "help"]


def test_pgn_review_menu_button_returns_to_start_menu(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    app.draw_frame()
    menu_rect = app.right_menu.button_rects.get("menu")
    assert menu_rect is not None
    app.right_menu.handle_click(menu_rect.center)
    assert app.mode == "menu"
    assert app.pgn_review is False
    assert app.start_menu.is_visible() is True


def test_flip_still_works_in_pgn_review(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    initial = app.board.flipped
    app._on_flip()
    assert app.board.flipped != initial


def test_new_game_clears_pgn_review_flag(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    assert app.pgn_review is True
    app._on_new_game()
    assert app.pgn_review is False
    assert _flat_button_keys(app._right_menu_buttons()) == {
        "undo", "resign", "draw", "flip", "help",
    }


def test_ctrl_z_does_not_undo_in_pgn_review(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    history_before = len(app.backend.move_history)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=pg.KMOD_CTRL)
    app._handle_shortcut_key(event)
    assert len(app.backend.move_history) == history_before


def _new_timed_app():
    from frontend.frontend import Frontend
    app = Frontend(1500, 800)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": 5, "increment_seconds": 0,
                        "side": "white"})
    return app


def _new_app_in_isolated_root(tmp_path):
    from frontend.frontend import Frontend
    app = Frontend(1500, 800)
    app.sound_manager = MagicMock()
    return app
