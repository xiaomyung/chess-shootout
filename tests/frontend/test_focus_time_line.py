"""TimeLine (focus/time_line.py) paints the depleting per-clock bar with the
right state color: orange for the mover, gray for the waiter, red under 10%.

Drawn onto an owned Surface with a stub board + real Clock so the color guard is
deterministic on any platform — pixel-sampling the shared app display surface is
xdist-order-fragile (a neighbor can leave it in a polluted state)."""

import pygame as pg
import pytest

from chessshootout.backend.clock import Clock
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import BOARD_SIZE
from chessshootout.frontend.focus.time_line import TimeLine
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    yield
    pg.quit()


class _Board:
    def __init__(self, rect, flipped=False):
        self.rect = rect
        self.cell_size = rect.width / BOARD_SIZE
        self.board_offset_x = rect.left
        self.board_offset_y = rect.top
        self.flipped = flipped


def _rgb(color):
    c = pg.Color(color)
    return (c.r, c.g, c.b)


def _clock(white=300.0, black=300.0, initial=300.0):
    clk = Clock.create(initial, 0, now_provider=lambda: 0.0)
    clk.white_remaining = white
    clk.black_remaining = black
    return clk


def _draw(board, clock, mover, fill=(9, 9, 9)):
    surf = pg.Surface((400, 400))
    surf.fill(fill)
    TimeLine().draw(surf, board, clock, mover, board.rect)
    return surf


def _sample(surf, rect):
    return tuple(surf.get_at((rect.centerx, rect.centery)))[:3]


def test_mover_line_is_accent_waiter_is_muted():
    board = _Board(pg.Rect(0, 10, 380, 380))
    top, bottom = TimeLine().rects_for(board, board.rect)
    surf = _draw(board, _clock(), PieceColor.WHITE)
    assert _sample(surf, bottom) == _rgb(Colors.accent)
    assert _sample(surf, top) == _rgb(Colors.text_muted)


def test_low_time_line_turns_red():
    board = _Board(pg.Rect(0, 10, 380, 380))
    low = 300.0 * (LOW_TIME_FRACTION / 2)
    _top, bottom = TimeLine().rects_for(board, board.rect)
    surf = _draw(board, _clock(white=low), PieceColor.WHITE)
    assert _sample(surf, bottom) == _rgb(Colors.check)


def test_flip_swaps_which_edge_is_the_mover():
    board = _Board(pg.Rect(0, 10, 380, 380), flipped=True)
    top, _bottom = TimeLine().rects_for(board, board.rect)
    surf = _draw(board, _clock(), PieceColor.WHITE)
    assert _sample(surf, top) == _rgb(Colors.accent)
