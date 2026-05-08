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
from frontend.board import Board, DRAG_THRESHOLD_PX
from frontend.capture_summary import captured_by, material_advantage
from frontend.confirm_modal import ConfirmModal


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
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
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


def setup_position(board, piece_map, turn=PieceColor.WHITE):
    bk = board.backend
    bk.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        bk.state[sq.row][sq.col] = piece
    bk.turn = turn
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1


def fire_animation(board):
    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


# ---------- A1: Last-move highlight ----------

def test_last_move_highlight_renders_when_history_nonempty(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    # Should render without raising; covers from + to overlay paths.
    board._draw_last_move_highlight()


def test_last_move_highlight_skipped_when_history_empty(board):
    rects = []
    original_cell_rect = board._cell_rect
    board._cell_rect = lambda r, c: rects.append((r, c)) or original_cell_rect(r, c)
    try:
        board._draw_last_move_highlight()
    finally:
        board._cell_rect = original_cell_rect
    # No history → highlight path never queries cell rects.
    assert rects == []


def test_last_move_highlight_uses_both_squares(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    rects = []
    original = board._cell_rect

    def capture(row, col):
        rects.append((row, col))
        return original(row, col)

    board._cell_rect = capture
    board._draw_last_move_highlight()
    board._cell_rect = original
    assert (6, 4) in rects
    assert (4, 4) in rects


# ---------- A2: Resign confirmation modal ----------

def test_confirm_modal_hidden_by_default():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    assert modal.is_visible() is False


def test_confirm_modal_show_makes_visible():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    modal.show("Resign?", on_yes=lambda: None)
    assert modal.is_visible() is True


def test_confirm_modal_yes_invokes_callback_and_hides():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    fired = [False]
    modal.show("Resign?", on_yes=lambda: fired.__setitem__(0, True),
               yes_label="Resign", no_label="Cancel")
    modal.draw()  # populates button_rects
    yes_rect = modal.button_rects["yes"]
    consumed = modal.handle_click(yes_rect.center)
    assert consumed is True
    assert fired[0] is True
    assert modal.is_visible() is False


def test_confirm_modal_no_dismisses_without_callback_change():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    fired = [False]
    modal.show("Resign?", on_yes=lambda: fired.__setitem__(0, True),
               yes_label="Resign", no_label="Cancel")
    modal.draw()
    no_rect = modal.button_rects["no"]
    modal.handle_click(no_rect.center)
    assert fired[0] is False
    assert modal.is_visible() is False


def test_confirm_modal_click_outside_buttons_does_nothing():
    modal = ConfirmModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(0, 0, 200, 100))
    modal.show("Q?", on_yes=lambda: None)
    modal.draw()
    # A point outside both buttons (top of modal).
    assert modal.handle_click((10, 5)) is False
    assert modal.is_visible() is True


def test_resign_button_shows_modal_and_does_not_resign():
    app = _new_app()
    app._on_resign()
    assert app.confirm_modal.is_visible() is True
    assert app.manual_result is None


def test_resign_modal_yes_completes_resign():
    app = _new_app()
    app._on_resign()
    app.draw_frame()  # populates button_rects
    yes_rect = app.confirm_modal.button_rects["yes"]
    app.mouse_left_clicked(yes_rect.center)
    assert app.confirm_modal.is_visible() is False
    assert app.manual_result == "black_wins"  # white was on turn → loses


def test_resign_modal_no_keeps_game_active():
    app = _new_app()
    app._on_resign()
    app.draw_frame()
    no_rect = app.confirm_modal.button_rects["no"]
    app.mouse_left_clicked(no_rect.center)
    assert app.confirm_modal.is_visible() is False
    assert app.manual_result is None


def test_resign_blocks_other_clicks_while_modal_open():
    # While the modal is up, clicks on the board should not select pieces.
    app = _new_app()
    app._on_resign()
    app.draw_frame()
    # Click on a board square; modal is up so this should be ignored.
    target = (50, 50)
    app.mouse_left_clicked(target)
    assert app.board.selected_square is None


def test_draw_button_shows_modal_and_does_not_draw():
    app = _new_app()
    app._on_draw()
    assert app.confirm_modal.is_visible() is True
    assert app.manual_result is None


def test_draw_modal_yes_completes_draw():
    app = _new_app()
    app._on_draw()
    app.draw_frame()
    yes_rect = app.confirm_modal.button_rects["yes"]
    app.mouse_left_clicked(yes_rect.center)
    assert app.manual_result == "draw_agreement"


# ---------- A3: Drag-and-drop ----------

def test_drag_threshold_constant_is_six():
    assert DRAG_THRESHOLD_PX == 6


def test_begin_press_records_position(board):
    board.begin_press((100, 100))
    assert board._press_pos == (100, 100)


def test_motion_below_threshold_does_not_start_drag(board):
    board.handle_click(Square(6, 4))  # select white pawn
    board.begin_press((10, 10))
    board.update_drag_motion((11, 11))
    assert board.dragging_from is None


def test_motion_past_threshold_starts_drag(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from == Square(6, 4)


def test_drag_ignores_motion_when_no_selection(board):
    board.begin_press((10, 10))
    # No piece was selected on press.
    board.update_drag_motion((50, 50))
    assert board.dragging_from is None


def test_drag_blocked_during_pending_promotion(board):
    board.handle_click(Square(6, 4))
    board.pending_promotion_square = Square(0, 0)
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from is None


def test_end_press_clears_state(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    assert board.dragging_from == Square(6, 4)
    was_dragging = board.end_press()
    assert was_dragging is True
    assert board.dragging_from is None
    assert board._press_pos is None


def test_drag_skips_origin_in_draw_pieces(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((50, 50))
    # Spy by replacing piece_images_scaled values with a sentinel surface and
    # tracking which (row, col) the cell_rect is queried for in draw_pieces.
    visited = []
    original_cell_rect = board._cell_rect
    board._cell_rect = lambda r, c: visited.append((r, c)) or original_cell_rect(r, c)
    try:
        board.draw_pieces()
    finally:
        board._cell_rect = original_cell_rect
    assert (6, 4) not in visited


def test_dragged_piece_renders_at_cursor(board):
    board.handle_click(Square(6, 4))
    board.begin_press((10, 10))
    board.update_drag_motion((123, 234))
    # Smoke test: drawing at a cursor position must not raise.
    board._draw_dragged_piece()
    # Internal state holds the cursor pixel exactly.
    assert board._drag_cursor == (123, 234)


def test_dragged_piece_no_op_without_drag_state(board):
    # Without dragging_from set, draw is a no-op even if cursor is set.
    assert board.dragging_from is None
    board._drag_cursor = (10, 10)
    board._draw_dragged_piece()  # must not raise


def test_drag_and_drop_executes_legal_move():
    app = _new_app()
    # Board geometry — find pixel for white e2 pawn and e4 destination.
    e2_rect = app.board._cell_rect(6, 4)
    e4_rect = app.board._cell_rect(4, 4)
    app._mouse_left_pressed(e2_rect.center)
    # Move past threshold to a midpoint, then release on e4.
    midpoint = (e4_rect.centerx, e2_rect.centery - DRAG_THRESHOLD_PX * 4)
    app.board.update_drag_motion(midpoint)
    app._mouse_left_released(e4_rect.center)
    fire_animation(app.board)
    assert len(app.backend.move_history) == 1
    last = app.backend.move_history[-1].move
    assert last.from_sq == Square(6, 4)
    assert last.to_sq == Square(4, 4)


def test_drag_drop_skips_slide_animation():
    # When a move lands via drag, we should NOT queue a slide animation —
    # the drag motion already showed the piece arriving at the target.
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    e4_rect = app.board._cell_rect(4, 4)
    app._mouse_left_pressed(e2_rect.center)
    app.board.update_drag_motion(e4_rect.center)
    app._mouse_left_released(e4_rect.center)
    # Move applied to the backend.
    assert len(app.backend.move_history) == 1
    # No animation queued — drag-drop is instant.
    assert app.board.animations == []


def test_click_click_still_animates():
    # Sanity counter-test: a non-drag move (just two clicks) DOES animate.
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    e4_rect = app.board._cell_rect(4, 4)
    app.mouse_left_clicked(e2_rect.center)  # click1: select
    app.mouse_left_clicked(e4_rect.center)  # click2: move
    assert len(app.backend.move_history) == 1
    assert len(app.board.animations) == 1


def test_drag_below_threshold_falls_back_to_click_click():
    app = _new_app()
    e2_rect = app.board._cell_rect(6, 4)
    app._mouse_left_pressed(e2_rect.center)
    app.board.update_drag_motion((e2_rect.centerx + 1, e2_rect.centery))
    app._mouse_left_released((e2_rect.centerx + 1, e2_rect.centery))
    # No drag fired → no move yet, but the press selected the pawn.
    assert app.board.selected_square == Square(6, 4)
    assert len(app.backend.move_history) == 0


# ---------- A4: Captured pieces + material balance ----------

def test_captured_by_empty_at_start():
    backend = Backend()
    backend.new_game()
    assert captured_by(backend.move_history, PieceColor.WHITE) == []
    assert captured_by(backend.move_history, PieceColor.BLACK) == []


def test_captured_by_after_pawn_capture():
    backend = Backend()
    backend.new_game()
    # 1. e4 d5 2. exd5
    backend.try_move(Square(6, 4), Square(4, 4))  # e4
    backend.try_move(Square(1, 3), Square(3, 3))  # d5
    backend.try_move(Square(4, 4), Square(3, 3))  # exd5
    assert captured_by(backend.move_history, PieceColor.WHITE) == [PieceType.PAWN]
    assert captured_by(backend.move_history, PieceColor.BLACK) == []


def test_material_advantage_zero_at_start():
    backend = Backend()
    backend.new_game()
    assert material_advantage(backend.move_history, PieceColor.WHITE) == 0
    assert material_advantage(backend.move_history, PieceColor.BLACK) == 0


def test_material_advantage_after_pawn_capture():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    backend.try_move(Square(1, 3), Square(3, 3))
    backend.try_move(Square(4, 4), Square(3, 3))
    assert material_advantage(backend.move_history, PieceColor.WHITE) == 1
    assert material_advantage(backend.move_history, PieceColor.BLACK) == -1


def test_material_advantage_after_queen_trade():
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[0][0] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[4][4] = Piece(PieceType.QUEEN, PieceColor.WHITE)
    backend.state[3][4] = Piece(PieceType.QUEEN, PieceColor.BLACK)
    # Black pawn one rank above the white queen's destination (4,4) —
    # actually black pawn moves down (row index increases). After WxQ at (3,4),
    # a black pawn at (2,3) captures forward-diagonally to (3,4).
    backend.state[2][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res1 = backend.try_move(Square(4, 4), Square(3, 4))
    assert res1.legal
    res2 = backend.try_move(Square(2, 3), Square(3, 4))
    assert res2.legal
    # Two queens captured (one each side) → net zero material.
    assert material_advantage(backend.move_history, PieceColor.WHITE) == 0
    assert material_advantage(backend.move_history, PieceColor.BLACK) == 0


def test_player_strip_set_state_accepts_captures(board):
    from frontend.player_strip import PlayerStrip
    strip = PlayerStrip(pg.display.get_surface())
    strip.set_rect(pg.Rect(0, 0, 400, 40))
    strip.set_state("Alice", 100, True,
                    captured=[PieceType.PAWN], advantage=1,
                    captured_color=PieceColor.BLACK)
    assert strip.captured == [PieceType.PAWN]
    assert strip.advantage == 1
    assert strip.captured_color == PieceColor.BLACK


def test_player_strip_draws_with_captures_smoke(board):
    from frontend.player_strip import PlayerStrip
    strip = PlayerStrip(pg.display.get_surface())
    strip.set_rect(pg.Rect(0, 0, 400, 40))
    strip.set_piece_icons(board.piece_images_scaled)
    strip.set_state("Alice", 100, True,
                    captured=[PieceType.PAWN, PieceType.KNIGHT],
                    advantage=4,
                    captured_color=PieceColor.BLACK)
    strip.draw()


def test_player_strip_advantage_negative_not_rendered(board):
    # Only the leading side shows "+N"; the trailing side renders no number.
    from frontend.player_strip import PlayerStrip
    strip = PlayerStrip(pg.display.get_surface())
    strip.set_rect(pg.Rect(0, 0, 400, 40))
    strip.set_state("Alice", 100, True, captured=[],
                    advantage=-3, captured_color=PieceColor.WHITE)
    strip.draw()  # smoke


# ---------- A5: Keyboard shortcuts ----------

def test_f_key_flips_board():
    app = _new_app()
    initial = app.board.flipped
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_f, mod=0)
    app._handle_shortcut_key(event)
    assert app.board.flipped != initial


def test_ctrl_z_undoes_last_move():
    app = _new_app()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    assert len(app.backend.move_history) == 1
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=pg.KMOD_CTRL)
    app._handle_shortcut_key(event)
    assert len(app.backend.move_history) == 0


def test_z_without_ctrl_does_not_undo():
    app = _new_app()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=0)
    handled = app._handle_shortcut_key(event)
    assert handled is False
    assert len(app.backend.move_history) == 1


def test_shortcuts_blocked_while_confirm_modal_open():
    app = _new_app()
    app._on_resign()  # opens modal
    initial_flipped = app.board.flipped
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_f, mod=0)
    handled = app._handle_shortcut_key(event)
    assert handled is False
    assert app.board.flipped == initial_flipped


def test_unrelated_key_returns_false():
    app = _new_app()
    event = pg.event.Event(pg.KEYDOWN, key=pg.K_q, mod=0)
    assert app._handle_shortcut_key(event) is False
