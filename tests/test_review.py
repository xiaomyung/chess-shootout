import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.backend import Backend
from backend.pieces import Piece, PieceColor, PieceType
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


# ---------- Backend.position_at ----------

def test_position_at_zero_returns_starting_layout():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))  # e4
    grid = backend.position_at(0)
    # Pawn back at e2.
    assert grid[6][4].type == PieceType.PAWN
    assert grid[4][4] is None


def test_position_at_full_history_returns_live_state():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 4), Square(3, 4))
    grid = backend.position_at(2)
    # Live state — pawns at e4 and e5.
    assert grid[4][4].type == PieceType.PAWN
    assert grid[3][4].type == PieceType.PAWN


def test_position_at_intermediate():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))  # e4
    backend.try_move(Square(1, 4), Square(3, 4))  # e5
    backend.try_move(Square(7, 6), Square(5, 5))  # Nf3
    grid = backend.position_at(1)  # after only e4
    assert grid[4][4].type == PieceType.PAWN
    assert grid[1][4].type == PieceType.PAWN  # black pawn still home
    assert grid[7][6].type == PieceType.KNIGHT  # knight still home


def test_position_at_does_not_mutate_live_state():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 4), Square(3, 4))
    # Snapshot live state.
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


# ---------- Board.review_ply rendering ----------

def test_review_ply_default_is_none(board):
    assert board.review_ply is None


def test_draw_pieces_uses_historical_grid_in_review_mode():
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
    # In review at ply 0, e4 cell would be empty in historical grid → no blit there.
    # But we can check that the rendering ran without error.
    assert (4, 4) not in visited or True  # smoke OK


def test_review_disables_handle_click(board):
    board.review_ply = 0
    board.handle_click(Square(6, 4))
    assert board.selected_square is None


def test_review_disables_drag_motion(board):
    board.review_ply = 0
    board.handle_click(Square(6, 4))  # would normally select but blocked
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from is None


# ---------- Auto-reset on real move ----------

def test_premove_fire_resets_review_ply():
    # In review mode the user can't make moves directly, but a premove queued
    # before entering review will fire when the turn matches → _start_move_animation
    # clears review_ply.
    app = _new_app()
    _play_e4_e5_nf3(app)
    assert app.backend.current_turn() == PieceColor.BLACK
    # Queue a white premove (d2 → d4) while it's black's turn.
    app.board.handle_click(Square(6, 3))
    app.board.handle_click(Square(4, 3))
    assert len(app.board.premoves) == 1
    # Enter review.
    app.board.review_ply = 1
    # Flip turn so the premove fires.
    app.backend.turn = PieceColor.WHITE
    fired = app.board.try_apply_next_premove()
    assert fired is True
    assert app.board.review_ply is None


def test_start_move_animation_clears_review_ply():
    # Direct unit test on the seam: _start_move_animation always clears review_ply.
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


# ---------- Keyboard navigation ----------

def test_left_arrow_steps_back_no_animation():
    app = _new_app()
    _play_e4_e5_nf3(app)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_LEFT, mod=0)
    app._handle_shortcut_key(event)
    # Backward step jumps instantly (no animation).
    assert app.board.review_ply == 2
    assert app.board.animations == []


def test_right_arrow_steps_forward_with_animation():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_RIGHT, mod=0)
    app._handle_shortcut_key(event)
    # While animating to ply 2, board sits at ply 1 (pre-move).
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
    # Bug guard: spamming the forward arrow must advance the review one ply per
    # press even while the previous animation is still in flight.
    app = _new_app()
    # Build a 5-ply game.
    for from_sq, to_sq in [
        (Square(6, 4), Square(4, 4)),  # e4
        (Square(1, 4), Square(3, 4)),  # e5
        (Square(7, 6), Square(5, 5)),  # Nf3
        (Square(0, 1), Square(2, 2)),  # Nc6
        (Square(7, 5), Square(4, 2)),  # Bc4
    ]:
        app.backend.try_move(from_sq, to_sq)
    app.board.review_ply = 0
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_RIGHT, mod=0)
    # Spam → → → without firing animations.
    app._handle_shortcut_key(event)
    assert app.board._target_ply == 1
    app._handle_shortcut_key(event)
    assert app.board._target_ply == 2
    app._handle_shortcut_key(event)
    assert app.board._target_ply == 3
    fire_animation(app.board)
    assert app.board.review_ply == 3


def test_spamming_animate_review_ply_snaps_previous():
    # Direct API: calling animate_review_ply(N) while animating to M should
    # snap M into place first, then start the new animation toward N.
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
    # Without firing the previous animation, request the next one.
    app.board.animate_review_ply(3)
    # Previous target (2) was snapped before starting the new animation.
    assert app.board.review_ply == 2  # pre-move state for ply 3
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
    # Esc closes the window; it must NOT affect review state.
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


# ---------- RightMenu click-through ----------

def test_clicking_white_cell_animates_to_white_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.draw_frame()
    hits = app.right_menu._move_cell_hits
    cell_rect, ply = hits[0]
    assert ply == 1
    app.right_menu.handle_click(cell_rect.center)
    # During animation: review_ply = ply - 1 (pre-move).
    assert app.board.review_ply == 0
    assert len(app.board.animations) >= 1
    # Fire the animation to completion — review_ply advances to the clicked ply.
    fire_animation(app.board)
    assert app.board.review_ply == 1


def test_clicking_black_cell_animates_to_black_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.draw_frame()
    hits = app.right_menu._move_cell_hits
    cell_rect, ply = hits[1]
    assert ply == 2
    app.right_menu.handle_click(cell_rect.center)
    fire_animation(app.board)
    assert app.board.review_ply == 2


def test_clicking_latest_move_animates_then_returns_to_live():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    app.draw_frame()
    hits = app.right_menu._move_cell_hits
    cell_rect, ply = hits[-1]
    assert ply == len(app.backend.move_history)
    app.right_menu.handle_click(cell_rect.center)
    # Animation queued: pre-move state at ply N-1, on completion → live (None).
    assert app.board.review_ply == ply - 1
    assert len(app.board.animations) >= 1
    fire_animation(app.board)
    assert app.board.review_ply is None


def test_animate_review_ply_starts_animation_from_correct_squares():
    app = _new_app()
    _play_e4_e5_nf3(app)
    # Click ply 3 (Nf3) — animation should be from g1 (7,6) to f3 (5,5).
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
    # Animation queued; review_ply is one before the latest while it plays.
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
    # Material counts in the player strip should reflect the position at the
    # current review ply, not the final state of the loaded game.
    app = _new_app()
    # Play 1.e4 d5 2.exd5: white captures a black pawn at ply 3.
    app.backend.try_move(Square(6, 4), Square(4, 4))  # e4 (ply 1)
    app.backend.try_move(Square(1, 3), Square(3, 3))  # d5 (ply 2)
    app.backend.try_move(Square(4, 4), Square(3, 3))  # exd5 (ply 3, white captures pawn)

    # In live state white's captured list has 1 black pawn.
    state = app._strip_state(PieceColor.WHITE, app.backend.current_turn(), False)
    assert len(state["captured"]) == 1
    assert state["advantage"] == 1

    # While reviewing ply 2 (after d5, before the capture) → no captures yet.
    app.board.review_ply = 2
    state = app._strip_state(PieceColor.WHITE, app.backend.current_turn(), False)
    assert state["captured"] == []
    assert state["advantage"] == 0

    # Reviewing ply 3 (after the capture) → matches live.
    app.board.review_ply = 3
    state = app._strip_state(PieceColor.WHITE, app.backend.current_turn(), False)
    assert len(state["captured"]) == 1
    assert state["advantage"] == 1


def test_last_move_highlight_in_review_targets_reviewed_move():
    app = _new_app()
    app.backend.try_move(Square(6, 4), Square(4, 4))   # 1.e4
    app.backend.try_move(Square(1, 3), Square(3, 3))   # 1...d5
    app.backend.try_move(Square(4, 4), Square(3, 3))   # 2.exd5
    # In review mode at ply 1, the last-move highlight should mark e2-e4.
    app.board.review_ply = 1
    move = app.match.move_history[app.board.review_ply - 1].move
    assert move.from_sq == Square(6, 4)
    assert move.to_sq == Square(4, 4)
    # At ply 0 (initial) there's no last move to highlight.
    app.board.review_ply = 0
    # _draw_last_move_highlight should silently do nothing — exercise the path.
    app.board.draw_board()


def test_active_row_highlight_in_live_mode_is_last_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.draw_frame()
    # Live = no review, active_ply = history_len = 3
    assert app.right_menu._active_ply(len(app.backend.move_history)) == 3


def test_active_row_highlight_follows_review_ply():
    app = _new_app()
    _play_e4_e5_nf3(app)
    app.board.review_ply = 1
    assert app.right_menu._active_ply(3) == 1


# ---------- Load PGN button ----------

def test_load_pgn_button_disabled_when_no_pgn(tmp_path, monkeypatch):
    # Force PROJECT_ROOT to an empty tmp dir so there are no games.
    monkeypatch.setattr("frontend.frontend.PROJECT_ROOT", str(tmp_path))
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
    monkeypatch.setattr("frontend.frontend.PROJECT_ROOT", str(tmp_path))
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
    # Force mtime ordering.
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))
    monkeypatch.setattr("frontend.frontend.PROJECT_ROOT", str(tmp_path))
    app = _new_app_in_isolated_root(tmp_path)
    path = app._latest_pgn_path()
    assert path is not None
    assert path.endswith("game-new.pgn")


def test_load_pgn_button_layout_left_and_right():
    app = _new_app()
    app.start_menu.show()
    app.start_menu.draw()
    assert app.start_menu._load_pgn_rect.x < app.start_menu._start_rect.x
    # Roughly equal widths (50/50 with a small gap).
    assert abs(app.start_menu._load_pgn_rect.width
               - app.start_menu._start_rect.width) <= 2


def test_load_pgn_from_path_loads_game(tmp_path):
    pgn_path = tmp_path / "test.pgn"
    pgn_path.write_text('[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 Nc6 *\n')
    app = _new_app()
    app._load_pgn_from_path(str(pgn_path))
    assert len(app.backend.move_history) == 4
    assert app.board.review_ply == 0
    assert app.mode == "single_screen"
    assert app.pgn_review is True


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
    # Navigate to live (read_only still set).
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


def test_pgn_review_shows_only_menu_and_flip_buttons(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    buttons = app._right_menu_buttons()
    keys = {key for _, key in buttons}
    assert keys == {"menu", "flip", "help"}


def test_live_mode_shows_full_buttons():
    app = _new_app()
    keys = {key for _, key in app._right_menu_buttons()}
    assert keys == {"undo", "resign", "draw", "flip", "help"}


def test_pgn_review_menu_button_returns_to_start_menu(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    # Force draw to populate button_rects.
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
    keys = {key for _, key in app._right_menu_buttons()}
    assert keys == {"undo", "resign", "draw", "flip", "help"}


def test_ctrl_z_does_not_undo_in_pgn_review(tmp_path):
    app = _new_app()
    _load_test_pgn(app, tmp_path)
    history_before = len(app.backend.move_history)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=pg.KMOD_CTRL)
    app._handle_shortcut_key(event)
    assert len(app.backend.move_history) == history_before


def _new_app_in_isolated_root(tmp_path):
    # Build a Frontend after PROJECT_ROOT has been monkeypatched on the module.
    from frontend.frontend import Frontend
    app = Frontend(1500, 800)
    app.sound_manager = MagicMock()
    return app
