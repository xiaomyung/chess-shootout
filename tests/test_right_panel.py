"""RightMenu rendering: plain-text SAN move cells (no figurine images), the
current-move highlight (button_pressed fill + inset accent border), click→ply
routing, and the scroll-reveal that fires only on review navigation — never as a
per-frame re-snap that would fight manual scrollback."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from backend.backend import Backend
from backend.pieces import Piece, PieceType, PieceColor
from backend.utils import Square, Move, HistoryEntry
from frontend.panels.right import RightMenu
from frontend.visual.colors import Colors


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


class _Board:
    def __init__(self):
        self.review_ply = None
        self.jumped = []

    def jump_to_review_ply(self, ply):
        self.jumped.append(ply)
        self.review_ply = ply


def _entry(piece_type, color, san):
    piece = Piece(piece_type, color)
    move = Move(Square(7, 6), Square(5, 5), piece)
    return HistoryEntry(move=move, prev_castling_rights=(), prev_en_passant_target=None,
                        prev_halfmove_clock=0, position_key_added=("k",), san=san)


def _menu(board=None):
    backend = Backend()
    backend.new_game()
    rm = RightMenu(pg.display.get_surface(), backend, {}, board=board)
    rm.set_rect(pg.Rect(0, 0, 320, 640))
    return rm, backend


def _has_color(win, rect, want_rgb, tol=8):
    rect = rect.clip(win.get_rect())
    for x in range(rect.x, rect.right, 2):
        for y in range(rect.y, rect.bottom, 2):
            c = win.get_at((x, y))
            if (abs(c.r - want_rgb[0]) <= tol and abs(c.g - want_rgb[1]) <= tol
                    and abs(c.b - want_rgb[2]) <= tol):
                return True
    return False


def _pawn_rows(backend, n):
    backend.move_history = [
        _entry(PieceType.PAWN, PieceColor.WHITE, f"a{i % 8 + 1}") for i in range(n)
    ]


def test_move_cell_renders_san_text():
    rm, backend = _menu()
    win = rm.window
    win.fill((0, 0, 0))
    backend.move_history = []
    rm.draw_menu()
    empty = pg.image.tobytes(win.subsurface(rm.moves_rect), "RGB")
    backend.move_history = [_entry(PieceType.KNIGHT, PieceColor.WHITE, "Nf3")]
    win.fill((0, 0, 0))
    rm.draw_menu()
    drawn = pg.image.tobytes(win.subsurface(rm.moves_rect), "RGB")
    assert drawn != empty, "the SAN move text should paint into the move list"
    assert _has_color(win, rm.moves_rect, pg.Color(Colors.text_dim)[:3], tol=45)


def test_current_move_highlight_uses_pressed_bg_and_accent_border():
    board = _Board()
    rm, backend = _menu(board)
    backend.move_history = [
        _entry(PieceType.PAWN, PieceColor.WHITE, "e4"),
        _entry(PieceType.PAWN, PieceColor.BLACK, "e5"),
    ]
    board.review_ply = 1
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.button_pressed)[:3]), \
        "current move cell uses the pressed surface as its background"
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.accent)[:3]), \
        "current move cell has an inset accent border"


def test_move_cell_click_jumps_to_ply():
    board = _Board()
    rm, backend = _menu(board)
    backend.move_history = [_entry(PieceType.PAWN, PieceColor.WHITE, "e4")]
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    cell_rect, ply = rm._move_cell_hits[0]
    assert rm.handle_click(cell_rect.center) is True
    assert board.jumped == [ply]


def test_review_nav_reveals_offscreen_ply():
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 60)
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 0
    board.review_ply = 2
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset > 0, "navigating to an off-screen ply scrolls to reveal it"


def test_no_resnap_when_review_ply_unchanged():
    """Once revealed, manual scrollback must stick: the same review_ply across
    frames does not re-snap the offset."""
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 60)
    board.review_ply = 2
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    rm.scroll_offset = 0
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 0


def test_live_play_does_not_snap_offset():
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 60)
    board.review_ply = None
    rm.scroll_offset = 5
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 5, "no review nav → offset is left alone"
