"""Speech-bubble widget (rendering only): the timed lifecycle, the pop-in /
fade-out animation, and GameScreen anchor resolution against the DISPLAYED grid
(live state, or the reviewed position while browsing). Anchor prefers the first
row-major queen of the color and falls back to the king; placement clamps inside
the board and flips below the piece near the top edge. The board draw path gates
bubbles under a blocking modal / result menu, and both reset + reset-to-new-game
clear them."""

import pygame as pg

from tests.conftest import pygame_display
from tests.frontend.focus_helpers import FakeTicks, install_clock
from tests.helpers import make_app as _make_app_at, start_single_screen
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.board.speech_bubble import (
    SpeechBubble, BUBBLE_MS, POP_STEPS,
)


_pygame_init = pygame_display(1000, 800)

WHITE_QUEEN_START = Square(7, 3)
WHITE_KING_START = Square(7, 4)


def _win():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    return win


def _bounds():
    return pg.Rect(40, 40, 700, 700)


def _game(monkeypatch, clock):
    install_clock(monkeypatch, clock)
    app = _make_app_at(1000, 800)
    start_single_screen(app)
    return app.game


def _clear_board(game):
    for row in range(8):
        for col in range(8):
            game.match.state[row][col] = None


def test_lifecycle_active_window_and_clear():
    bubble = SpeechBubble()
    assert not bubble.active(0)
    bubble.show("GG", 1000)
    assert bubble.active(1000)
    assert bubble.active(1100)
    assert not bubble.active(1000 + BUBBLE_MS + 1)
    bubble.clear()
    assert not bubble.active(1100)
    assert bubble.last_rect is None


def test_show_uppercases_and_replaces_text():
    bubble = SpeechBubble()
    bubble.show("nice try", 0)
    assert bubble.text == "NICE TRY"
    bubble.show("Good Game", 500)
    assert bubble.text == "GOOD GAME"
    assert bubble.shown_at == 500


def test_pop_grows_footprint_then_reaches_full_size():
    win, bounds = _win(), _bounds()
    bubble = SpeechBubble()
    bubble.show("HELLO", 0)
    anchor = pg.Rect(300, 400, 60, 60)
    bubble.draw(win, anchor, bounds, 40)
    popped = bubble.last_rect
    bubble.draw(win, anchor, bounds, 200)
    full = bubble.last_rect
    assert popped.width < full.width
    assert popped.height < full.height


def test_fade_out_lowers_alpha_on_owned_copy():
    win, bounds = _win(), _bounds()
    bubble = SpeechBubble()
    bubble.show("HELLO", 0)
    anchor = pg.Rect(300, 400, 60, 60)
    bubble.draw(win, anchor, bounds, 200)
    assert not bubble._owned, "steady frame blits the shared surface, no owned copy"
    bubble.draw(win, anchor, bounds, BUBBLE_MS - 100)
    owned = bubble._owned.get(False)
    assert owned is not None
    assert owned.get_alpha() < 255


def test_pop_variants_are_cached_and_bounded():
    win, bounds = _win(), _bounds()
    bubble = SpeechBubble()
    bubble.show("HELLO", 0)
    anchor = pg.Rect(300, 400, 60, 60)
    for ms in range(0, 160, 10):
        bubble.draw(win, anchor, bounds, ms)
    assert 0 < len(bubble._pop_variants) <= POP_STEPS


def test_anchor_prefers_first_queen_and_sits_above_it(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    game.board.flipped = False
    d1 = game.board.cell_rect(WHITE_QUEEN_START)
    anchor = game._speech_anchor("white")
    assert anchor.center == d1.center
    game.show_speech_bubble("white", "GG")
    game._draw_speech_bubbles()
    last = game.speech_bubbles["white"].last_rect
    assert last is not None
    assert abs(last.centerx - d1.centerx) <= 2
    assert last.bottom <= d1.top


def test_flip_mirrors_anchor_x(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    game.board.flipped = False
    upright = game._speech_anchor("white").centerx
    game.board.flipped = True
    mirrored = game._speech_anchor("white").centerx
    assert upright != mirrored
    grid_center = game.board.board_offset_x + game.board.cell_size * 4
    assert abs((upright + mirrored) - 2 * grid_center) <= 2


def test_anchor_falls_back_to_king_without_a_queen(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    game.match.state[WHITE_QUEEN_START.row][WHITE_QUEEN_START.col] = None
    anchor = game._speech_anchor("white")
    king = game.board.cell_rect(WHITE_KING_START)
    assert anchor.center == king.center


def test_clamp_keeps_corner_bubble_in_board_and_flips_below(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    game.board.flipped = False
    _clear_board(game)
    game.match.state[0][0] = Piece(PieceType.QUEEN, PieceColor.WHITE)
    corner = game.board.cell_rect(Square(0, 0))
    game.show_speech_bubble("white", "NICE TRY")
    game._draw_speech_bubbles()
    last = game.speech_bubbles["white"].last_rect
    assert last is not None
    assert game.board.rect.left <= last.left
    assert last.right <= game.board.rect.right
    assert last.top >= corner.bottom


def test_bubble_suppressed_under_blocking_modal(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    app = game.app
    app.confirm_modal.show("Sure?", lambda: None)
    game.show_speech_bubble("white", "HELLO")
    game._draw_speech_bubbles()
    assert game.speech_bubbles["white"].last_rect is None


def test_bubble_anchors_reviewed_grid_while_browsing(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    game.match.apply_san("e4")
    game.board.review_ply = 0
    d1 = game.board.cell_rect(WHITE_QUEEN_START)
    game.show_speech_bubble("white", "REVIEW")
    game._draw_speech_bubbles()
    last = game.speech_bubbles["white"].last_rect
    assert last is not None
    assert abs(last.centerx - d1.centerx) <= 2


def test_reset_to_new_game_clears_bubbles(monkeypatch):
    clock = FakeTicks()
    game = _game(monkeypatch, clock)
    game.show_speech_bubble("white", "GG")
    assert game.speech_bubbles["white"].active(clock())
    game._reset_to_new_game()
    assert not game.speech_bubbles["white"].active(clock())
    assert game.speech_bubbles["black"].shown_at is None


def test_dirty_rects_include_active_bubble(monkeypatch):
    game = _game(monkeypatch, FakeTicks())
    game.show_speech_bubble("white", "GG")
    game._draw_speech_bubbles()
    last = game.speech_bubbles["white"].last_rect
    assert last is not None
    assert last in game.dirty_rects()
