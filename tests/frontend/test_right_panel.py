"""RightMenu rendering: plain-text SAN move cells (no figurine images), the
current-move highlight (surface_active fill + inset accent border), click→ply
routing, and the scroll-reveal that fires only on review navigation — never as a
per-frame re-snap that would fight manual scrollback."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.backend.utils import Square, Move, HistoryEntry
from chessshootout.frontend.panels.right import RightMenu, CARD_INSET
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import dashed_hline


_pygame_init = pygame_display(1000, 800)


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
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.surface_active)[:3]), \
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
    _pawn_rows(backend, 120)
    board.review_ply = None
    rm.scroll_offset = 5
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert rm.scroll_offset == 5, "no review nav → offset is left alone"


def test_card_floats_inset_from_menu_rect():
    """The panel is a floating card: 12px inset on top/right/bottom (backdrop shows
    through the gap); the left keeps its inner padding only."""
    rm, _ = _menu()
    rect = pg.Rect(0, 0, 320, 640)
    rm.set_rect(rect, scale=1.0)
    assert rm.outer_rect.top == rect.top + CARD_INSET
    assert rm.outer_rect.right == rect.right - CARD_INSET
    assert rm.outer_rect.bottom == rect.bottom - CARD_INSET


def test_card_top_right_corner_is_cut():
    """The card is a cut-corner (TR) rect: the top-right corner is carved away and
    shows the window backdrop, while the top edge elsewhere is covered by the card."""
    rm, _ = _menu()
    backdrop = (48, 96, 160)
    rm.window.fill(backdrop)
    rm.draw_menu()
    card = rm.outer_rect
    corner = rm.window.get_at((card.right - 2, card.top + 1))
    assert (corner.r, corner.g, corner.b) == backdrop, \
        "the card's top-right corner is cut, revealing the backdrop"
    edge = rm.window.get_at((card.centerx, card.top + 1))
    assert (edge.r, edge.g, edge.b) != backdrop, \
        "the top edge away from the cut is covered by the card"


def test_moves_well_uses_well_deep():
    rm, backend = _menu()
    backend.move_history = []
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    assert _has_color(rm.window, rm.moves_rect, pg.Color(Colors.well_deep)[:3]), \
        "the SHOT LOG well fills with well_deep"


def test_shot_log_header_counts_plies():
    """The micro-header renders SHOT LOG + the live PLY count in text_muted; the
    counter region changes as the history grows."""
    rm, backend = _menu()
    backend.move_history = []
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    zero = pg.image.tobytes(rm.window.subsurface(rm.moves_rect), "RGB")
    backend.move_history = [
        _entry(PieceType.PAWN, PieceColor.WHITE, "e4"),
        _entry(PieceType.PAWN, PieceColor.BLACK, "e5"),
    ]
    rm.window.fill((0, 0, 0))
    rm.draw_menu()
    two = pg.image.tobytes(rm.window.subsurface(rm.moves_rect), "RGB")
    assert zero != two, "the PLY counter changes when the history grows"
    band = pg.Rect(rm.moves_rect.x, rm.moves_rect.y, rm.moves_rect.width, 24)
    assert _has_color(rm.window, band, pg.Color(Colors.text_muted)[:3], tol=40), \
        "the micro-header paints text_muted glyphs"


def test_dashed_hline_alternates_opaque_and_transparent():
    surf = dashed_hline(60, "#ffcc00", dash=6, gap=5)
    alphas = [surf.get_at((x, 0))[3] for x in range(surf.get_width())]
    assert any(a == 0 for a in alphas), "gaps must be fully transparent"
    assert any(a > 0 for a in alphas), "dashes must paint the separator color"


def test_short_window_clips_body_to_card():
    """At a min-height panel the well hits its LOG_MIN_H floor; the clip keeps
    everything inside the card so the inset gap stays pure backdrop."""
    board = _Board()
    rm, backend = _menu(board)
    _pawn_rows(backend, 120)
    rm.set_rect(pg.Rect(0, 0, 300, 200))
    backdrop = (48, 96, 160)
    rm.window.fill(backdrop)
    rm.draw_menu()
    gap = rm.window.get_at((rm.outer_rect.centerx, rm.outer_rect.top - 4))
    assert (gap.r, gap.g, gap.b) == backdrop, "the top inset gap shows only backdrop"
