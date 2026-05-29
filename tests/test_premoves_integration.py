"""Premove click-flow + auto-fire integration against the pygame Board.

Strategy: drive Board.handle_click / queue_premove_from_drag exactly as the
event loop does, then assert the resulting queue, premove_color, and backend
state. Premove validation is intentionally LAX — a queue entry only has to be
pseudo-legal from the chain tip (chess.com-style); the engine stays the final
authority at fire time. Multi-step chains, queue->fire cycles, and the
drag/online narratives are kept whole so a regression points at the exact step.
"""

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

WHITE = PieceColor.WHITE
BLACK = PieceColor.BLACK


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


def _highlighted_squares(board):
    captured = []
    original = board._cell_rect
    board._cell_rect = lambda r, c: captured.append(Square(r, c)) or original(r, c)
    try:
        board._draw_premove_highlights()
    finally:
        board._cell_rect = original
    return set(captured)


def _new_app():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    return app


# ---------- Click flow: single click sets selection, never queues ----------

@pytest.mark.parametrize(
    "turn, click_sq, expected_selected",
    [
        pytest.param(WHITE, Square(6, 4), Square(6, 4), id="own_piece_own_turn_selects"),
        pytest.param(WHITE, Square(1, 4), Square(1, 4), id="opp_piece_own_turn_premove_select"),
        pytest.param(BLACK, Square(6, 4), Square(6, 4), id="own_piece_opp_turn_premove_select"),
    ],
)
def test_single_click_selects_without_queueing(board, turn, click_sq, expected_selected):
    board.backend.turn = turn
    board.handle_click(click_sq)
    assert board.selected_square == expected_selected
    assert board.premoves == []
    assert board.premove_color is None


def test_real_move_works_when_selecting_then_targeting_own_color(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.backend.move_history) == 1
    assert board.premoves == []


def test_click_empty_clears_queue(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.handle_click(Square(3, 3))
    assert board.premoves == []
    assert board.premove_color is None


def test_click_empty_with_no_queue_is_noop(board):
    board.handle_click(Square(3, 3))
    assert board.selected_square is None
    assert board.premoves == []


# ---------- Validation: LAX pseudo-legal queueing from the default board ----------

@pytest.mark.parametrize(
    "from_sq, to_sq",
    [
        pytest.param(Square(6, 4), Square(4, 4), id="pawn_forward_two"),
        pytest.param(Square(7, 6), Square(5, 5), id="knight_l_shape"),
        pytest.param(Square(6, 4), Square(5, 5), id="pawn_diagonal_to_empty_lax"),
    ],
)
def test_white_premove_queued_off_turn(board, from_sq, to_sq):
    """Pawn diagonal to an empty square still queues (a capture might appear)."""
    board.backend.turn = BLACK
    board.handle_click(from_sq)
    board.handle_click(to_sq)
    assert len(board.premoves) == 1
    assert board.premove_color == WHITE
    assert board.backend.turn == BLACK
    assert len(board.backend.move_history) == 0


def test_bishop_sideways_rejected_pseudo_legal(board):
    """Off-shape premove (bishop along a rank) is rejected by the pseudo-legal gate."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(4, 4): Piece(PieceType.BISHOP, WHITE),
    }, turn=BLACK)
    board.handle_click(Square(4, 4))
    board.handle_click(Square(4, 7))
    assert board.premoves == []


# ---------- Chaining ----------

def test_chain_two_premoves_different_pieces(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 2


def test_chain_same_piece_uses_speculative_board(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(4, 0)
    assert board.premoves[1].to_sq == Square(3, 0)


# ---------- Auto-fire (legal path) ----------

def test_premove_fires_on_turn_match(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    assert len(board.premoves) == 0
    assert board.premove_color is None
    assert len(board.backend.move_history) == 1


@pytest.mark.parametrize(
    "flip_to_white, block",
    [
        pytest.param(False, lambda b: None, id="wrong_turn_backend_stays_black"),
        pytest.param(
            True,
            lambda b: b.start_animation(
                Square(6, 4), Square(4, 4), Piece(PieceType.PAWN, WHITE)),
            id="animation_in_flight",
        ),
        pytest.param(
            True,
            lambda b: setattr(b, "pending_promotion_square", Square(0, 0)),
            id="pending_promotion",
        ),
    ],
)
def test_premove_does_not_fire_when_blocked(board, flip_to_white, block):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    if flip_to_white:
        board.backend.turn = WHITE
    block(board)
    assert board.try_apply_next_premove() is False
    assert len(board.premoves) == 1


def test_chain_fires_one_per_turn(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 3
    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 2
    assert board.backend.turn == BLACK
    assert board.try_apply_next_premove() is False
    assert len(board.premoves) == 2
    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 1


# ---------- Auto-fire (illegal path) ----------

def test_illegal_premove_clears_entire_chain(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(3, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 3
    board.backend.state[6][4] = None
    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is False
    assert board.premoves == []
    assert board.premove_color is None
    assert len(board.backend.move_history) == 0


def test_illegal_fire_leaves_board_responsive(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.backend.state[6][4] = None
    board.backend.turn = WHITE
    board.try_apply_next_premove()
    assert board.premoves == []
    board.handle_click(Square(6, 0))
    assert board.selected_square == Square(6, 0)


# ---------- Cancellation paths via Frontend ----------

@pytest.mark.parametrize(
    "action",
    [
        pytest.param("_on_undo", id="undo"),
        pytest.param("_perform_resign", id="resign"),
        pytest.param("_perform_draw", id="draw"),
        pytest.param("_on_new_game", id="reset"),
        pytest.param("_on_back_to_menu", id="back_to_menu"),
    ],
)
def test_frontend_action_clears_premove_queue(action):
    app = _new_app()
    app.backend.turn = BLACK
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    assert len(app.board.premoves) == 1
    getattr(app, action)()
    assert app.board.premoves == []


# ---------- Move indicator suppression ----------

def test_move_indicators_suppressed_for_premove_selection(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    drawn = []
    board._draw_dot = lambda rect: drawn.append("dot")
    board._draw_capture_ring = lambda rect: drawn.append("ring")
    board._draw_move_indicators()
    assert drawn == []


def test_move_indicators_drawn_for_normal_selection(board):
    board.handle_click(Square(6, 4))
    drawn = []
    board._draw_dot = lambda rect: drawn.append("dot")
    board._draw_capture_ring = lambda rect: drawn.append("ring")
    board._draw_move_indicators()
    assert len(drawn) > 0


# ---------- Visual highlights ----------

def test_premove_highlight_renders_from_and_to_for_one_premove(board):
    """_draw_premove_highlights overlays both endpoint squares of the queued ply."""
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert _highlighted_squares(board) == {Square(6, 4), Square(4, 4)}


def test_premove_highlight_renders_every_square_for_chained_premoves(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert _highlighted_squares(board) == {
        Square(6, 4), Square(4, 4), Square(7, 6), Square(5, 5),
    }


def test_premove_highlight_renders_nothing_when_queue_empty(board):
    board._clear_premoves()
    assert _highlighted_squares(board) == set()


# ---------- Frontend integration in draw_frame ----------

def test_draw_frame_invokes_try_apply_next_premove():
    app = _new_app()
    called = [0]
    original = app.board.try_apply_next_premove
    app.board.try_apply_next_premove = lambda: called.__setitem__(0, called[0] + 1) or original()
    app.board.last_animation_completed_at_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    assert called[0] >= 1


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(
            lambda app: setattr(app, "manual_result", "white_wins"),
            id="game_over",
        ),
        pytest.param(
            lambda app: app.board.start_animation(
                Square(6, 4), Square(4, 4), Piece(PieceType.PAWN, WHITE)),
            id="animation_in_flight",
        ),
        pytest.param(
            lambda app: setattr(
                app.board, "last_animation_completed_at_ms", pg.time.get_ticks()),
            id="post_animation_delay",
        ),
    ],
)
def test_draw_frame_blocks_premove(setup):
    app = _new_app()
    setup(app)
    called = [0]
    app.board.try_apply_next_premove = lambda: called.__setitem__(0, called[0] + 1) or False
    app.draw_frame()
    assert called[0] == 0


# ---------- Mixed flows: premoves + real moves interleaved ----------

def test_normal_move_then_premove_then_fire(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert board.backend.turn == BLACK

    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 1
    assert board.premove_color == WHITE

    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    assert len(board.premoves) == 0


def test_premove_fire_then_normal_move_then_premove_again(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1

    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert board.backend.turn == BLACK
    assert board.premoves == []

    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))
    fire_animation(board)
    assert len(board.backend.move_history) == 2
    assert board.backend.turn == WHITE

    board.backend.turn = BLACK
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 1
    assert board.premove_color == WHITE

    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.backend.move_history) == 3


def test_alternating_real_moves_with_intermittent_premoves(board):
    sequence = []

    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    sequence.append(("real", "white"))
    assert board.backend.turn == BLACK

    board.handle_click(Square(1, 0))
    board.handle_click(Square(2, 0))
    fire_animation(board)
    sequence.append(("real", "black"))
    assert board.backend.turn == WHITE

    board.handle_click(Square(0, 1))
    board.handle_click(Square(2, 2))
    assert len(board.premoves) == 1
    assert board.premove_color == BLACK
    sequence.append(("queue", "black"))

    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    fire_animation(board)
    sequence.append(("real", "white"))
    assert board.backend.turn == BLACK

    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    sequence.append(("fire", "black"))
    assert board.premoves == []
    assert board.backend.turn == WHITE

    assert sequence == [
        ("real", "white"), ("real", "black"), ("queue", "black"),
        ("real", "white"), ("fire", "black"),
    ]
    assert len(board.backend.move_history) == 4


def test_premove_queued_on_own_turn_does_not_interfere_with_real_move(board):
    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))
    assert len(board.premoves) == 1
    assert board.premove_color == BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert len(board.premoves) == 1
    assert board.backend.turn == BLACK
    fired = board.try_apply_next_premove()
    assert fired is True
    assert len(board.backend.move_history) == 2


def test_swap_premove_color_clears_old_queue(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert board.premove_color == WHITE
    assert len(board.premoves) == 1
    board.backend.turn = WHITE
    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))
    assert board.premove_color == BLACK
    assert len(board.premoves) == 1
    assert board.premoves[0].piece.color == BLACK


def test_premove_fire_during_active_drawframe_loop():
    app = _new_app()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    app.board.handle_click(Square(7, 6))
    app.board.handle_click(Square(5, 5))
    assert len(app.board.premoves) == 1
    app.board.handle_click(Square(1, 4))
    app.board.handle_click(Square(3, 4))
    fire_animation(app.board)
    app.board.last_animation_completed_at_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    fire_animation(app.board)
    assert app.board.premoves == []
    last_entry = app.backend.move_history[-1]
    assert last_entry.move.from_sq == Square(7, 6)
    assert last_entry.move.to_sq == Square(5, 5)


def test_long_chain_3_premoves_fires_one_per_white_turn(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))
    board.handle_click(Square(3, 0))
    board.handle_click(Square(2, 0))
    assert len(board.premoves) == 3

    for i in range(3):
        board.backend.turn = WHITE
        fired = board.try_apply_next_premove()
        assert fired is True
        fire_animation(board)
        assert len(board.premoves) == 2 - i
        if i < 2:
            board.backend.turn = WHITE


def test_clear_then_requeue(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.handle_click(Square(3, 3))
    assert board.premoves == []
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 1
    assert board.premoves[0].from_sq == Square(7, 6)


def test_premove_then_undo_reverts_real_move_and_queue_persists_only_via_real_undo(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert board.premoves == []

    board.backend.turn = BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    assert len(board.premoves) == 1
    board._clear_premoves()
    board.backend.undo()
    assert board.premoves == []
    assert len(board.backend.move_history) == 0


def test_castle_premove_queues_and_fires_legally(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(7, 7): Piece(PieceType.ROOK, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
    }, turn=BLACK)
    board.handle_click(Square(7, 4))
    board.handle_click(Square(7, 6))
    assert len(board.premoves) == 1
    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    assert board.backend.state[7][6] is not None
    assert board.backend.state[7][6].type == PieceType.KING
    assert board.backend.state[7][5] is not None
    assert board.backend.state[7][5].type == PieceType.ROOK


def test_premove_capturing_opposite_piece_fires_with_capture(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(4, 3): Piece(PieceType.QUEEN, WHITE),
        Square(2, 3): Piece(PieceType.KNIGHT, BLACK),
    }, turn=BLACK)
    board.handle_click(Square(4, 3))
    board.handle_click(Square(2, 3))
    assert len(board.premoves) == 1
    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    captured = board.backend.move_history[-1].move.captured
    assert captured is not None
    assert captured.type == PieceType.KNIGHT


def test_chain_clicking_original_from_square_resolves_to_tip(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.handle_click(Square(6, 4))
    assert board.selected_square == Square(4, 4)
    board.handle_click(Square(3, 4))
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(4, 4)
    assert board.premoves[1].to_sq == Square(3, 4)


def test_chain_three_deep_clicking_original_resolves_to_final_tip(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(5, 0))
    board.handle_click(Square(5, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))
    assert len(board.premoves) == 3
    board.handle_click(Square(6, 0))
    assert board.selected_square == Square(3, 0)
    board.handle_click(Square(2, 0))
    assert len(board.premoves) == 4
    assert board.premoves[3].from_sq == Square(3, 0)


def test_chain_clicking_intermediate_square_resolves_to_tip(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    board.handle_click(Square(4, 0))
    assert board.selected_square == Square(4, 0)
    board.handle_click(Square(3, 0))
    assert len(board.premoves) == 2
    board.handle_click(Square(4, 0))
    assert board.selected_square == Square(3, 0)


def test_capture_target_of_opponent_premove_with_my_threatened_piece(board):
    """White's live d4 rook must stay selectable despite a queued black Rd2xd4."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(4, 3): Piece(PieceType.ROOK, WHITE),
        Square(6, 3): Piece(PieceType.ROOK, BLACK),
    }, turn=WHITE)
    board.handle_click(Square(6, 3))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 1
    assert board.premove_color == BLACK
    board.handle_click(Square(4, 3))
    assert board.selected_square == Square(4, 3)
    board.handle_click(Square(6, 3))
    assert len(board.backend.move_history) == 1
    last = board.backend.move_history[-1].move
    assert last.from_sq == Square(4, 3)
    assert last.to_sq == Square(6, 3)
    assert last.captured is not None
    assert last.captured.type == PieceType.ROOK


def test_move_threatened_piece_away_from_opponent_premove(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(4, 3): Piece(PieceType.ROOK, WHITE),
        Square(6, 3): Piece(PieceType.ROOK, BLACK),
    }, turn=WHITE)
    board.handle_click(Square(6, 3))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 1
    board.handle_click(Square(4, 3))
    board.handle_click(Square(4, 0))
    assert len(board.backend.move_history) == 1
    last = board.backend.move_history[-1].move
    assert last.from_sq == Square(4, 3)
    assert last.to_sq == Square(4, 0)
    assert last.captured is None


def test_clicking_truly_empty_square_still_cancels(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.handle_click(Square(3, 3))
    assert board.premoves == []


def test_chain_resolution_does_not_trigger_when_no_relevant_premove(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(5, 4))
    assert board.premoves == []
    assert board.selected_square is None


def test_chain_via_resolution_then_fire(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(6, 4))
    board.handle_click(Square(3, 4))
    assert len(board.premoves) == 2

    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    assert len(board.premoves) == 1

    board.backend.turn = WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    assert len(board.premoves) == 0
    assert len(board.backend.move_history) == 2


def test_scholars_mate_via_premove_chain(board):
    """1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6?? 4. Qxf7#, queued [Bc4, Qh5, Qxf7]."""
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))
    fire_animation(board)

    board.backend.turn = BLACK
    board.handle_click(Square(7, 5))
    board.handle_click(Square(4, 2))
    board.handle_click(Square(7, 3))
    board.handle_click(Square(3, 7))
    board.handle_click(Square(7, 3))
    board.handle_click(Square(1, 5))
    assert len(board.premoves) == 3

    board.backend.turn = WHITE
    assert board.try_apply_next_premove() is True
    fire_animation(board)
    board.handle_click(Square(0, 1))
    board.handle_click(Square(2, 2))
    fire_animation(board)
    assert board.try_apply_next_premove() is True
    fire_animation(board)
    board.handle_click(Square(0, 6))
    board.handle_click(Square(2, 5))
    fire_animation(board)
    assert board.try_apply_next_premove() is True
    fire_animation(board)

    assert board.backend.game_result() == "white_wins"
    assert board.premoves == []


def test_scholars_mate_chain_aborts_when_queen_captured_mid_chain(board):
    """Qh5 fires (a legal blunder); after Nxh5, Qxf7 is illegal and wipes the queue."""
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))
    fire_animation(board)

    board.backend.turn = BLACK
    board.handle_click(Square(7, 3))
    board.handle_click(Square(3, 7))
    board.handle_click(Square(7, 3))
    board.handle_click(Square(1, 5))
    assert len(board.premoves) == 2

    board.backend.turn = BLACK
    board.handle_click(Square(0, 6))
    board.handle_click(Square(2, 5))
    fire_animation(board)

    assert board.try_apply_next_premove() is True
    fire_animation(board)
    assert board.backend.state[3][7] is not None
    assert board.backend.state[3][7].type == PieceType.QUEEN

    board.handle_click(Square(2, 5))
    board.handle_click(Square(3, 7))
    fire_animation(board)
    assert board.backend.state[3][7].type == PieceType.KNIGHT

    fired = board.try_apply_next_premove()
    assert fired is False
    assert board.premoves == []
    assert board.premove_color is None
    history_len_before = len(board.backend.move_history)
    fired_again = board.try_apply_next_premove()
    assert fired_again is False
    assert len(board.backend.move_history) == history_len_before


def test_chain_capture_continues_with_local_color(board):
    """Online (local_color=WHITE): a chain extension off a live-black square still queues."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(1, 5): Piece(PieceType.ROOK, WHITE),
        Square(1, 6): Piece(PieceType.PAWN, BLACK),
        Square(1, 7): Piece(PieceType.PAWN, BLACK),
    }, turn=BLACK)
    board.match.local_color = WHITE
    board.handle_click(Square(1, 5))
    board.handle_click(Square(1, 6))
    assert len(board.premoves) == 1
    board.handle_click(Square(1, 6))
    assert board.selected_square == Square(1, 6)
    board.handle_click(Square(1, 7))
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(1, 6)
    assert board.premoves[1].to_sq == Square(1, 7)


def test_real_move_still_wins_when_local_piece_is_side_to_move(board):
    """Online: local white must grab the live white rook, not the speculative black one."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(4, 3): Piece(PieceType.ROOK, WHITE),
        Square(6, 3): Piece(PieceType.ROOK, BLACK),
    }, turn=WHITE)
    board.handle_click(Square(6, 3))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 1
    board.match.local_color = WHITE
    board.handle_click(Square(4, 3))
    assert board.selected_square == Square(4, 3)
    board.handle_click(Square(6, 3))
    assert len(board.backend.move_history) == 1
    last = board.backend.move_history[-1].move
    assert last.from_sq == Square(4, 3)
    assert last.to_sq == Square(6, 3)
    assert last.captured is not None and last.captured.type == PieceType.ROOK


def test_online_opponent_turn_click_on_opp_piece_does_nothing_when_no_chain(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(1, 5): Piece(PieceType.ROOK, WHITE),
        Square(1, 6): Piece(PieceType.PAWN, BLACK),
    }, turn=BLACK)
    board.match.local_color = WHITE
    board.handle_click(Square(1, 6))
    assert board.selected_square is None
    assert board.premoves == []


def _start_drag(board, sq):
    board.handle_click(sq)
    board.begin_press((0, 0))
    cell = board.cell_size
    cx = sq.col * cell + board.board_offset_x + cell // 2
    cy = sq.row * cell + board.board_offset_y + cell // 2
    board._press_pos = (cx - 50, cy - 50)
    board.update_drag_motion((cx, cy))


def test_right_click_during_drag_queues_premove(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(6, 4): Piece(PieceType.PAWN, WHITE),
    }, turn=BLACK)
    _start_drag(board, Square(6, 4))
    assert board.dragging_from == Square(6, 4)
    assert board.queue_premove_from_drag(Square(4, 4)) is True
    assert len(board.premoves) == 1
    assert board.premoves[0].from_sq == Square(6, 4)
    assert board.premoves[0].to_sq == Square(4, 4)


def test_right_click_during_drag_keeps_dragging_for_chain(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(6, 4): Piece(PieceType.PAWN, WHITE),
    }, turn=BLACK)
    _start_drag(board, Square(6, 4))
    board.queue_premove_from_drag(Square(4, 4))
    assert board.dragging_from == Square(6, 4)
    assert board._drag_cursor is not None
    assert board._resolve_chain_tip(board.dragging_from) == Square(4, 4)


def test_right_click_during_drag_chains_inside_single_hold(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(1, 5): Piece(PieceType.ROOK, WHITE),
        Square(1, 6): Piece(PieceType.PAWN, BLACK),
        Square(1, 7): Piece(PieceType.PAWN, BLACK),
    }, turn=BLACK)
    board.match.local_color = WHITE
    _start_drag(board, Square(1, 5))
    board.queue_premove_from_drag(Square(1, 6))
    assert len(board.premoves) == 1
    assert board.dragging_from == Square(1, 5)
    assert board._resolve_chain_tip(board.dragging_from) == Square(1, 6)
    board.queue_premove_from_drag(Square(1, 7))
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(1, 6)
    assert board.premoves[1].to_sq == Square(1, 7)
    assert board._resolve_chain_tip(board.dragging_from) == Square(1, 7)


def test_right_click_during_drag_off_shape_rejected_pseudo_legal(board):
    """Drag-release on an off-shape target (rook diagonal) hits the pseudo-legal gate."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(7, 0): Piece(PieceType.ROOK, WHITE),
    }, turn=BLACK)
    _start_drag(board, Square(7, 0))
    assert board.queue_premove_from_drag(Square(5, 2)) is False
    assert board.premoves == []


def test_drag_right_click_on_own_turn_does_not_queue_premove(board):
    """Real-turn drag goes through try_move; queueing would fire a spurious sound."""
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(7, 0): Piece(PieceType.ROOK, WHITE),
        Square(6, 0): Piece(PieceType.KNIGHT, WHITE),
    }, turn=WHITE)
    _start_drag(board, Square(7, 0))
    assert board.queue_premove_from_drag(Square(5, 0)) is False
    assert board.premoves == []


def test_right_click_during_drag_same_square_no_queue(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(6, 4): Piece(PieceType.PAWN, WHITE),
    }, turn=BLACK)
    _start_drag(board, Square(6, 4))
    assert board.queue_premove_from_drag(Square(6, 4)) is False
    assert board.premoves == []
    assert board.dragging_from == Square(6, 4)


def test_right_click_drag_premove_skipped_when_not_dragging(board):
    assert board.queue_premove_from_drag(Square(4, 4)) is False
    assert board.premoves == []


def test_right_click_drag_premove_blocked_for_opp_piece_in_online(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(1, 4): Piece(PieceType.PAWN, BLACK),
    }, turn=BLACK)
    board.match.local_color = WHITE
    board.dragging_from = Square(1, 4)
    board.selected_square = Square(1, 4)
    assert board.queue_premove_from_drag(Square(2, 4)) is False
    assert board.premoves == []


def test_right_click_drag_premove_chain_clears_when_drag_ends(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, WHITE),
        Square(0, 4): Piece(PieceType.KING, BLACK),
        Square(6, 4): Piece(PieceType.PAWN, WHITE),
    }, turn=BLACK)
    _start_drag(board, Square(6, 4))
    board.queue_premove_from_drag(Square(4, 4))
    board.end_press()
    assert board.dragging_from is None
    assert board._drag_cursor is None


def test_premove_immediately_after_other_premove_fires(board):
    board.backend.turn = BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 2

    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 1

    board.backend.turn = WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 0
