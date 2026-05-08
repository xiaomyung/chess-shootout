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


def make_app():
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
    if not board.animations:
        return
    for a in list(board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    board._draw_animations()


# ---------- State primitives ----------

def test_toggle_highlight_adds(board):
    board.toggle_highlight(Square(4, 4))
    assert Square(4, 4) in board.highlighted_squares


def test_toggle_highlight_removes(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_highlight(Square(4, 4))
    assert Square(4, 4) not in board.highlighted_squares


def test_toggle_arrow_adds(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    assert (Square(6, 0), Square(4, 0)) in board.arrows


def test_toggle_arrow_removes_on_second_call(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    assert (Square(6, 0), Square(4, 0)) not in board.arrows


def test_toggle_arrow_direction_specific(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(4, 0), Square(6, 0))
    assert len(board.arrows) == 2
    assert (Square(6, 0), Square(4, 0)) in board.arrows
    assert (Square(4, 0), Square(6, 0)) in board.arrows


def test_is_square_annotated_via_highlight(board):
    board.toggle_highlight(Square(4, 4))
    assert board.is_square_annotated(Square(4, 4)) is True
    assert board.is_square_annotated(Square(0, 0)) is False


def test_is_square_annotated_via_arrow_endpoints(board):
    board.toggle_arrow(Square(6, 4), Square(4, 4))
    assert board.is_square_annotated(Square(6, 4)) is True
    assert board.is_square_annotated(Square(4, 4)) is True
    assert board.is_square_annotated(Square(5, 4)) is False


def test_is_square_annotated_neutral_returns_false(board):
    assert board.is_square_annotated(Square(3, 3)) is False


def test_clear_annotations_empties_state(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board._right_drag_start_square = Square(2, 2)
    board.clear_annotations()
    assert board.highlighted_squares == set()
    assert board.arrows == []
    assert board._right_drag_start_square is None


# ---------- Right-click event flow ----------

def post_event(event_type, **kwargs):
    pg.event.post(pg.event.Event(event_type, kwargs))


def test_right_click_down_on_board_sets_drag_start():
    app = make_app()
    sq = Square(6, 4)
    rect = app.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    app.check_events()
    assert app.board._right_drag_start_square == sq


def test_right_click_down_off_board_no_drag_start():
    app = make_app()
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=(2000, 2000))
    app.check_events()
    assert app.board._right_drag_start_square is None


def test_right_click_release_same_square_toggles_highlight():
    app = make_app()
    sq = Square(6, 4)
    rect = app.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.check_events()
    assert sq in app.board.highlighted_squares
    assert app.board._right_drag_start_square is None


def test_right_click_release_different_square_creates_arrow():
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    a_rect = app.board._cell_rect(a.row, a.col)
    b_rect = app.board._cell_rect(b.row, b.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=a_rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=b_rect.center)
    app.check_events()
    assert (a, b) in app.board.arrows
    assert app.board._right_drag_start_square is None


def test_right_click_release_off_board_cancels():
    app = make_app()
    a = Square(6, 4)
    a_rect = app.board._cell_rect(a.row, a.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=a_rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=(2000, 2000))
    app.check_events()
    assert app.board.highlighted_squares == set()
    assert app.board.arrows == []
    assert app.board._right_drag_start_square is None


def test_right_click_on_already_highlighted_removes_it():
    app = make_app()
    sq = Square(6, 4)
    app.board.toggle_highlight(sq)
    assert sq in app.board.highlighted_squares
    rect = app.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.check_events()
    assert sq not in app.board.highlighted_squares


def test_right_click_drag_twice_toggles_arrow_off():
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    a_rect = app.board._cell_rect(a.row, a.col)
    b_rect = app.board._cell_rect(b.row, b.col)
    for _ in range(2):
        post_event(pg.MOUSEBUTTONDOWN, button=3, pos=a_rect.center)
        post_event(pg.MOUSEBUTTONUP, button=3, pos=b_rect.center)
        app.check_events()
    assert (a, b) not in app.board.arrows


def test_right_click_in_menu_mode_is_noop():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    # Still in menu mode.
    rect = app.board._cell_rect(0, 0)
    post_event(pg.MOUSEBUTTONDOWN, button=3, pos=rect.center)
    post_event(pg.MOUSEBUTTONUP, button=3, pos=rect.center)
    app.check_events()
    assert app.board.highlighted_squares == set()


# ---------- Left-click clear-on-neutral ----------

def test_left_click_neutral_square_clears_annotations():
    app = make_app()
    app.board.toggle_highlight(Square(4, 4))
    rect = app.board._cell_rect(7, 7)  # h1 - empty in initial position, no annotation
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.check_events()
    assert app.board.highlighted_squares == set()


def test_left_click_on_highlighted_square_preserves_annotations():
    app = make_app()
    sq = Square(4, 4)
    app.board.toggle_highlight(sq)
    rect = app.board._cell_rect(sq.row, sq.col)
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.check_events()
    assert sq in app.board.highlighted_squares


def test_left_click_on_arrow_from_endpoint_preserves():
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    app.board.toggle_arrow(a, b)
    rect = app.board._cell_rect(a.row, a.col)
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.check_events()
    assert (a, b) in app.board.arrows


def test_left_click_on_arrow_to_endpoint_preserves():
    app = make_app()
    a = Square(6, 4)
    b = Square(4, 4)
    app.board.toggle_arrow(a, b)
    rect = app.board._cell_rect(b.row, b.col)
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    app.check_events()
    assert (a, b) in app.board.arrows


def test_left_click_off_board_does_not_clear():
    app = make_app()
    app.board.toggle_highlight(Square(4, 4))
    post_event(pg.MOUSEBUTTONDOWN, button=1, pos=(2000, 2000))
    app.check_events()
    assert Square(4, 4) in app.board.highlighted_squares


# ---------- Auto-clear on real move ----------

def test_normal_move_clears_annotations(board):
    board.toggle_highlight(Square(0, 0))
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert board.highlighted_squares == set()


def test_capture_move_clears_annotations(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(PieceType.QUEEN, PieceColor.WHITE),
        Square(2, 4): Piece(PieceType.PAWN, PieceColor.BLACK),
    })
    board.toggle_highlight(Square(7, 7))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(2, 4))
    assert board.highlighted_squares == set()
    assert board.arrows == []


def test_castle_move_clears_annotations(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 7): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    board.backend.castling_rights = {"WK": True, "WQ": False, "BK": False, "BQ": False}
    board.toggle_highlight(Square(0, 0))
    board.handle_click(Square(7, 4))
    board.handle_click(Square(7, 6))
    assert board.highlighted_squares == set()


def test_promotion_pending_clears_annotations(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 0): Piece(PieceType.PAWN, PieceColor.WHITE),
    })
    board.toggle_highlight(Square(4, 4))
    board.handle_click(Square(1, 0))
    board.handle_click(Square(0, 0))
    # Cleared at _start_move_animation, before picker shows.
    assert board.highlighted_squares == set()


def test_premove_fire_clears_annotations(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # premove e2-e4
    assert len(board.premoves) == 1
    board.toggle_highlight(Square(0, 0))
    board.toggle_arrow(Square(7, 7), Square(0, 7))
    # Fire premove.
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    assert board.highlighted_squares == set()
    assert board.arrows == []


# ---------- Auto-clear on undo / game transitions ----------

def test_undo_clears_annotations():
    app = make_app()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    app.board.toggle_highlight(Square(0, 0))
    app.board.toggle_arrow(Square(6, 0), Square(4, 0))
    app._on_undo()
    assert app.board.highlighted_squares == set()
    assert app.board.arrows == []


def test_resign_clears_annotations():
    app = make_app()
    app.board.toggle_highlight(Square(0, 0))
    app._on_resign()
    assert app.board.highlighted_squares == set()


def test_draw_clears_annotations():
    app = make_app()
    app.board.toggle_arrow(Square(6, 0), Square(4, 0))
    app._on_draw()
    assert app.board.arrows == []


def test_new_game_clears_annotations():
    app = make_app()
    app.board.toggle_highlight(Square(4, 4))
    app.board.toggle_arrow(Square(6, 0), Square(4, 0))
    app._on_new_game()
    assert app.board.highlighted_squares == set()
    assert app.board.arrows == []


def test_back_to_menu_clears_annotations():
    app = make_app()
    app.board.toggle_highlight(Square(4, 4))
    app._on_back_to_menu()
    assert app.board.highlighted_squares == set()


# ---------- Drawing path smoke ----------

def test_draw_annotation_highlights_does_not_crash(board):
    board.toggle_highlight(Square(4, 4))
    board._draw_annotation_highlights()


def test_draw_arrows_does_not_crash(board):
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(7, 0), Square(0, 7))  # diagonal
    board.toggle_arrow(Square(4, 0), Square(4, 7))  # horizontal
    board._draw_arrows()


def test_draw_drag_preview_arrow_no_drag_is_noop(board):
    board._right_drag_start_square = None
    board._draw_drag_preview_arrow()  # must not raise


def test_draw_drag_preview_arrow_with_active_drag(board):
    board._right_drag_start_square = Square(6, 4)
    board._draw_drag_preview_arrow()  # uses pg.mouse.get_pos


def test_draw_full_board_with_annotations_no_crash(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_highlight(Square(3, 3))
    board.toggle_arrow(Square(6, 4), Square(4, 4))
    board._right_drag_start_square = Square(0, 0)
    board.draw_board()


# ---------- Combined scenarios ----------

def test_highlights_and_arrows_coexist(board):
    board.toggle_highlight(Square(4, 4))
    board.toggle_highlight(Square(3, 3))
    board.toggle_arrow(Square(6, 0), Square(4, 0))
    board.toggle_arrow(Square(6, 7), Square(4, 7))
    assert len(board.highlighted_squares) == 2
    assert len(board.arrows) == 2


def test_can_re_annotate_after_clear(board):
    board.toggle_highlight(Square(4, 4))
    board.clear_annotations()
    board.toggle_highlight(Square(4, 4))
    assert Square(4, 4) in board.highlighted_squares


def test_selection_only_does_not_clear_annotations(board):
    board.toggle_highlight(Square(4, 4))
    board.handle_click(Square(6, 4))  # select pawn, no move yet
    assert Square(4, 4) in board.highlighted_squares


def test_premove_queueing_does_not_clear_annotations(board):
    board.backend.turn = PieceColor.BLACK
    board.toggle_highlight(Square(4, 4))
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # premove (4,4) IS highlighted but we don't fire animation
    # The premove queue happens, the highlighted_squares should stay since no _start_move_animation ran.
    assert len(board.premoves) == 1
    assert Square(4, 4) in board.highlighted_squares
