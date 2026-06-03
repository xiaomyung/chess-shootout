import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from backend.match import Match
from backend.pieces import PieceType, PieceColor
from backend.utils import Square
from frontend.board import Board
from frontend.visual.colors import Colors


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((780, 780))
    yield
    pg.quit()


def _board(position_moves=()):
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    for fr, to in position_moves:
        match.try_move(Square(*fr), Square(*to))
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 680, 680))
    return board, win


def _cell_has(win, rect, predicate):
    return any(
        predicate(win.get_at((x, y)))
        for x in range(rect.x, rect.right) for y in range(rect.y, rect.bottom)
    )


def test_arena_frame_insets_grid_and_caches_surface():
    board, _ = _board()
    assert board.board_offset_x >= board.rect.x + board.frame_pad - 2
    assert board.board_offset_y >= board.rect.y + board.frame_pad - 2
    assert board.cell_size > 0
    assert board._frame_surf is not None
    grid_px = board.cell_size * board.SIZE
    assert board.board_offset_x + grid_px <= board.rect.right
    assert board.board_offset_y + grid_px <= board.rect.bottom


def test_gutter_coords_rendered():
    board, _ = _board()
    assert len(board.rank_labels_rendered) == 8
    assert len(board.file_labels_rendered) == 8


def test_selection_ring_is_opaque_accent():
    board, win = _board()
    board.selected_square = Square(6, 4)
    board.draw_board()
    rect = board._cell_rect(6, 4)
    assert win.get_at((rect.centerx, rect.top + 1))[:3] == pg.Color(Colors.accent)[:3]


def test_legal_move_ring_drawn_on_empty_target():
    board, win = _board()
    board.selected_square = Square(6, 4)
    board.draw_board()
    target = board._cell_rect(4, 4)

    def reddish(c):
        return c[0] - c[1] > 40 and c[0] - c[2] > 40 and c[0] > 120

    assert _cell_has(win, target, reddish), "legal-move ring (accent) should appear on e4"


def test_capture_shows_orange_hitmarker_on_piece():
    board, win = _board([((6, 4), (4, 4)), ((1, 3), (3, 3))])
    board.selected_square = Square(4, 4)
    board.draw_board()
    target = board._cell_rect(3, 3)

    def orange(c):
        return c[0] - c[1] > 60 and c[0] - c[2] > 60 and c[0] > 150

    assert _cell_has(win, target, orange), "orange capture hitmarker should appear on d5"


def test_en_passant_marks_captured_pawn_and_landing_square():
    board, win = _board([((6, 4), (4, 4)), ((1, 0), (2, 0)),
                         ((4, 4), (3, 4)), ((1, 3), (3, 3))])
    assert board.backend.en_passant_target == Square(2, 3)
    board.selected_square = Square(3, 4)
    board.draw_board()
    captured = board._cell_rect(3, 3)
    landing = board._cell_rect(2, 3)

    def orange(c):
        return c[0] - c[1] > 60 and c[0] - c[2] > 60 and c[0] > 150

    def reddish(c):
        return c[0] - c[1] > 40 and c[0] - c[2] > 40 and c[0] > 120

    assert _cell_has(win, captured, orange), "hitmarker should mark the en-passant pawn"
    assert _cell_has(win, landing, reddish), "ring should mark the en-passant landing square"


def test_check_shows_red_flash_ring_and_orange_hitmarker():
    board, win = _board([((6, 5), (5, 5)), ((1, 4), (3, 4)),
                         ((6, 6), (4, 6)), ((0, 3), (4, 7))])
    assert board.match.is_in_check(PieceColor.WHITE)
    board.draw_board()
    king = board._cell_rect(7, 4)
    assert win.get_at((king.centerx, king.top + 1))[:3] == pg.Color(Colors.check)[:3]

    def orange(c):
        return c[0] - c[1] > 60 and c[0] - c[2] > 60 and c[0] > 150

    assert _cell_has(win, king, orange), "orange hitmarker should appear on the checked king"


def test_promotion_popover_has_four_options_and_routes_click(monkeypatch):
    board, _ = _board()
    board.pending_promotion_square = Square(1, 4)
    board.draw_board()
    assert set(board._promotion_rects) == {
        PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT,
    }
    picked = []
    monkeypatch.setattr(board, "pick_promotion", picked.append)
    board.pick_promotion_at(board._promotion_rects[PieceType.ROOK].center)
    assert picked == [PieceType.ROOK]


def test_promotion_popover_flips_left_and_stays_within_board_right_edge():
    """A small board leaves a panel-sized gap to its right; the popover must flip and stay
    within the board, measured against the board rect, not the whole window."""
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 360, 360))
    board.pending_promotion_square = Square(1, 7)
    board.draw_board()
    sq_rect = board._cell_rect(1, 7)
    cells = board._promotion_rects.values()
    assert min(r.left for r in cells) < sq_rect.left, \
        "popover must flip to the left of a right-edge square"
    assert max(r.right for r in cells) <= board.rect.right, \
        "popover must not spill past the board's right edge into the panel area"


def test_promotion_popover_stays_within_board_left_edge():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 360, 360))
    board.pending_promotion_square = Square(1, 0)
    board.draw_board()
    sq_rect = board._cell_rect(1, 0)
    cells = board._promotion_rects.values()
    assert max(r.right for r in cells) > sq_rect.right, \
        "popover must sit to the right of a left-edge square"
    assert min(r.left for r in cells) >= board.rect.x, \
        "popover must not spill past the board's left edge"


def test_flipped_cell_rect_mirrors():
    board, _ = _board()
    normal = board._cell_rect(0, 0)
    board.flipped = True
    flipped = board._cell_rect(0, 0)
    assert normal.topleft != flipped.topleft
