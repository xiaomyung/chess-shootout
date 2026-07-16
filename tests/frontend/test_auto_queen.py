"""Auto-queen (CHESS_AUTO_QUEEN): when on, promotions skip the piece picker and
land a queen straight away — the skill check still fires (the armed path routes
through the same skillcheck gate the picker would). The board reads the setting
through an injected `auto_queen_provider` so it stays env-free; GameScreen wires
`env.get_auto_queen` into it. Every path (armed manual, non-armed post-move,
premove) must promote to queen exactly once — the single-`_finalize_move`
invariant for promotion plies must hold."""

from collections import Counter

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import Square
from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.frontend.board import Board
from tests.helpers import fire_animation


_pygame_init = pygame_display(800, 600)


def _promo_board(turn=PieceColor.WHITE, bk=Square(7, 0)):
    """A white pawn one push from promotion on e-file. The black king sits where
    the promoted queen does NOT check it, so the SAN tail is a clean '=Q'."""
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[1][4] = Piece(PieceType.PAWN, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[bk.row][bk.col] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.turn = turn
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    board = Board(pg.display.get_surface(), backend)
    board.load_assets()
    board.set_rect(pg.Rect(0, 0, 400, 400))
    return backend, board


def test_armed_promotion_auto_queen_skips_picker_and_gates_queen():
    """With auto-queen on and the skill check armed, a promotion click never arms
    the picker: it routes straight to the skillcheck gate carrying QUEEN, exactly
    as if the player had instantly picked the queen from the picker."""
    backend, board = _promo_board()
    captured = []
    board.skillcheck_armed = lambda: True
    board.locked_targets = lambda f, t: False

    def gate(f, t, promo=None):
        captured.append((f, t, promo))
        return True

    board.skillcheck_gate = gate
    board.auto_queen_provider = lambda: True

    board.handle_click(Square(1, 4))
    signal = board.handle_click(Square(0, 4))

    assert signal == "promotion"
    assert captured == [(Square(1, 4), Square(0, 4), PieceType.QUEEN)]
    assert board.pending_promotion_square is None, "the picker never arms under auto-queen"
    assert board._promotion_from is None
    assert backend.piece_at(Square(1, 4)).type == PieceType.PAWN, \
        "the gate held the move; nothing applied yet"


def test_non_armed_promotion_auto_queen_lands_queen_once():
    """No skill check armed: the pawn slides to the last rank, and when the slide
    lands the auto-queen guard promotes to queen directly instead of arming the
    picker — one finalize, SAN tail '=Q'."""
    backend, board = _promo_board()
    landed = []
    board.move_landed_callback = landed.append
    board.auto_queen_provider = lambda: True

    board.handle_click(Square(1, 4))
    signal = board.handle_click(Square(0, 4))
    assert signal == "move"
    assert board.pending_promotion_square is None, "no picker while the pawn is still sliding"

    fire_animation(board)

    assert board.pending_promotion_square is None, "the picker never arms under auto-queen"
    assert len(backend.move_history) == 1
    assert backend.move_history[-1].san.endswith("=Q")
    assert len(landed) == 1, "the promotion ply finalizes/lands exactly once"
    assert backend.piece_at(Square(0, 4)).type == PieceType.QUEEN


def test_premove_promotion_auto_queen_lands_queen_once():
    """A queued promotion premove that fires on the opponent's move flows through
    `_set_pending_promotion`; auto-queen promotes it to queen once."""
    backend, board = _promo_board(turn=PieceColor.BLACK)
    landed = []
    board.move_landed_callback = landed.append
    board.auto_queen_provider = lambda: True

    queued = board._queue_premove(
        Square(1, 4), Square(0, 4), Piece(PieceType.PAWN, PieceColor.WHITE))
    assert queued is True

    backend.try_move(Square(7, 0), Square(6, 0))  # black moves; white is to move now
    assert board.try_apply_next_premove() is True

    fire_animation(board)

    assert board.pending_promotion_square is None
    assert backend.move_history[-1].san.endswith("=Q")
    assert len(landed) == 1, "move_landed fires exactly once for the auto-queened premove"


def test_auto_queen_off_arms_the_picker_as_before():
    """The behaviour pin: with the provider off, both the armed and the post-move
    promotion paths arm the piece picker exactly as they do today."""
    backend, board = _promo_board()
    board.skillcheck_armed = lambda: True
    board.locked_targets = lambda f, t: False
    board.skillcheck_gate = lambda f, t, promo=None: False
    board.auto_queen_provider = lambda: False
    board.handle_click(Square(1, 4))
    signal = board.handle_click(Square(0, 4))
    assert signal == "promotion"
    assert board.pending_promotion_square == Square(0, 4), "armed path arms the picker"
    assert board._promotion_from == Square(1, 4)

    backend2, board2 = _promo_board()
    board2.auto_queen_provider = lambda: False
    board2.handle_click(Square(1, 4))
    board2.handle_click(Square(0, 4))
    fire_animation(board2)
    assert board2.pending_promotion_square == Square(0, 4), \
        "post-move path arms the picker once the slide lands"
    assert len(backend2.move_history) == 1
    assert not backend2.move_history[-1].san.endswith("=Q"), "nothing is promoted yet"
