import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from backend.match import Match, ONLINE
from backend.pieces import PieceColor
from backend.utils import Square
from frontend.board import Board


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1500, 800))
    yield
    pg.quit()


def _make_board(local_color=None):
    match = Match(mode=ONLINE, local_color=local_color) if local_color else Match()
    bd = Board(pg.display.get_surface(), match)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def test_local_color_none_allows_white_to_select_white_piece():
    bd = _make_board(None)
    bd.handle_click(Square(6, 4))
    assert bd.selected_square == Square(6, 4)


def test_local_color_white_allows_white_select_on_white_turn():
    bd = _make_board(PieceColor.WHITE)
    bd.handle_click(Square(6, 4))
    assert bd.selected_square == Square(6, 4)


def test_local_color_white_blocks_black_premove_select():
    # User is white (online). On white's turn, clicking a black piece would
    # normally select it for premove — gating must prevent that.
    bd = _make_board(PieceColor.WHITE)
    # Backend starts at white's turn; black piece click would go to premove path.
    bd.handle_click(Square(1, 4))  # black pawn
    assert bd.selected_square is None


def test_local_color_black_blocks_white_select_on_white_turn():
    bd = _make_board(PieceColor.BLACK)
    bd.handle_click(Square(6, 4))  # white pawn on white's turn (real-select normally)
    # But local_color=BLACK → blocked at _try_select.
    assert bd.selected_square is None


def test_local_color_black_blocks_white_premove_select():
    bd = _make_board(PieceColor.BLACK)
    # Force black's turn so that white piece clicks would hit the premove path.
    bd.match.backend.turn = PieceColor.BLACK
    bd.handle_click(Square(6, 4))  # white pawn
    assert bd.selected_square is None


def test_local_color_none_allows_both_sides_to_select():
    # Hot-seat regression: opposite-color piece selection still goes via premove.
    bd = _make_board(None)
    # Force black's turn → white piece click goes to premove path.
    bd.match.backend.turn = PieceColor.BLACK
    bd.handle_click(Square(6, 4))
    assert bd.selected_square == Square(6, 4)
