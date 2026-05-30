"""Color gating for board selection.

Online (local_color set) restricts selection to the local player's pieces at
both the real-select and premove-select paths; hot-seat (local_color=None)
lets either side be selected. Gating lives in _try_select / _try_select_for_premove
(both guard `local_color is not None and piece.color != local_color`), so an
opponent click is dropped before it can ever set selected_square.
"""

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


def _assert_select(bd, square, expected_can_select):
    if expected_can_select:
        assert bd.selected_square == square
    else:
        assert bd.selected_square is None


@pytest.mark.parametrize(
    "local_color, square, expected_can_select",
    [
        pytest.param(
            None, Square(6, 4), True,
            id="hotseat_allows_white_real_select",
        ),
        pytest.param(
            PieceColor.WHITE, Square(6, 4), True,
            id="white_allows_own_real_select",
        ),
        pytest.param(
            PieceColor.WHITE, Square(1, 4), False,
            id="white_blocks_black_premove_select",
        ),
        pytest.param(
            PieceColor.BLACK, Square(6, 4), False,
            id="black_blocks_white_real_select",
        ),
    ],
)
def test_select_gating_on_white_turn(local_color, square, expected_can_select):
    """At the backend's default white turn: own-color clicks select, opponent clicks drop."""
    bd = _make_board(local_color)
    bd.handle_click(square)
    _assert_select(bd, square, expected_can_select)


@pytest.mark.parametrize(
    "local_color, expected_can_select",
    [
        pytest.param(
            PieceColor.BLACK, False,
            id="black_blocks_white_premove_select",
        ),
        pytest.param(
            None, True,
            id="hotseat_allows_opposite_side_premove_select",
        ),
    ],
)
def test_select_gating_white_piece_on_black_turn(local_color, expected_can_select):
    """Turn flipped to black so a white-piece click takes the premove path: gating still applies."""
    bd = _make_board(local_color)
    bd.match.backend.turn = PieceColor.BLACK
    bd.handle_click(Square(6, 4))
    _assert_select(bd, Square(6, 4), expected_can_select)
