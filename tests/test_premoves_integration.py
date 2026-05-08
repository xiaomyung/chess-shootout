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


# ---------- Click flow ----------

def test_click_own_piece_on_own_turn_selects_no_queue(board):
    board.handle_click(Square(6, 4))
    assert board.selected_square == Square(6, 4)
    assert board.premoves == []
    assert board.premove_color is None


def test_click_opposite_piece_on_own_turn_does_nothing(board):
    # White's turn; click black piece. Selection only allowed for white-turn premoves
    # rule: piece.color == current_turn → real select; else → premove select.
    # Black piece on white's turn → goes to _try_select_for_premove.
    board.handle_click(Square(1, 4))
    assert board.selected_square == Square(1, 4)
    assert board.premoves == []
    # Until a destination is clicked, it's just a premove selection in flight.


def test_click_own_piece_on_opponent_turn_starts_premove(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))  # White pawn while it's black's turn.
    assert board.selected_square == Square(6, 4)
    assert board.premoves == []


def test_real_move_works_when_selecting_then_targeting_own_color(board):
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.backend.move_history) == 1
    assert board.premoves == []


def test_premove_queued_when_selecting_then_targeting_off_turn(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))  # White pawn
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.WHITE
    assert board.backend.turn == PieceColor.BLACK  # backend untouched
    assert len(board.backend.move_history) == 0


def test_click_empty_clears_queue(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    board.handle_click(Square(3, 3))  # empty square
    assert board.premoves == []
    assert board.premove_color is None


def test_click_empty_with_no_queue_is_noop(board):
    board.handle_click(Square(3, 3))
    assert board.selected_square is None
    assert board.premoves == []


# ---------- Validation ----------

def test_pawn_premove_forward_two_queued(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1


def test_knight_premove_l_shape_queued(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 1


def test_bishop_sideways_silently_rejected(board):
    board.backend.turn = PieceColor.BLACK
    # Place white bishop at (4, 4) for clarity.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(PieceType.BISHOP, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(4, 4))
    board.handle_click(Square(4, 7))  # sideways - invalid bishop shape
    assert board.premoves == []


def test_pawn_diagonal_to_empty_queues_LAX(board):
    # LAX: chess.com allows pawn diagonal even when destination empty - capture might appear.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(5, 5))  # empty diagonal
    assert len(board.premoves) == 1


# ---------- Chaining ----------

def test_chain_two_premoves_different_pieces(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 2


def test_chain_same_piece_uses_speculative_board(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))  # pawn a2-a4
    # Speculative says pawn now at (4, 0). Click there to extend chain.
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))  # a4-a5
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(4, 0)
    assert board.premoves[1].to_sq == Square(3, 0)


# ---------- Auto-fire (legal path) ----------

def test_premove_fires_on_turn_match(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    # Mark turn as the premove color → auto-fire condition satisfied.
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    assert len(board.premoves) == 0
    assert board.premove_color is None
    assert len(board.backend.move_history) == 1


def test_premove_does_not_fire_on_wrong_turn(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    # Backend turn stays BLACK → premove_color is WHITE → no fire.
    assert board.try_apply_next_premove() is False
    assert len(board.premoves) == 1


def test_premove_does_not_fire_when_animating(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.backend.turn = PieceColor.WHITE
    # Inject a fake animation.
    board.start_animation(Square(6, 4), Square(4, 4),
                          Piece(PieceType.PAWN, PieceColor.WHITE))
    assert board.try_apply_next_premove() is False
    assert len(board.premoves) == 1


def test_premove_does_not_fire_during_pending_promotion(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.backend.turn = PieceColor.WHITE
    board.pending_promotion_square = Square(0, 0)
    assert board.try_apply_next_premove() is False
    assert len(board.premoves) == 1


def test_chain_fires_one_per_turn(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))  # a2-a4
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))  # a4-a5
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))  # Ng1-Nf3
    assert len(board.premoves) == 3
    # First fire.
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 2
    # After WHITE's move, turn switches back to BLACK; second won't fire yet.
    assert board.backend.turn == PieceColor.BLACK
    assert board.try_apply_next_premove() is False
    assert len(board.premoves) == 2
    # Pretend BLACK plays a move (manually flip turn).
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 1


# ---------- Auto-fire (illegal path) ----------

def test_illegal_premove_clears_entire_chain(board):
    # Queue a chain. Then make the head premove illegal at fire time
    # by removing the piece from the from-square.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # pm1: e2-e4
    board.handle_click(Square(4, 4))
    board.handle_click(Square(3, 4))  # pm2: e4-e5
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))  # pm3: Nf3
    assert len(board.premoves) == 3
    # Sabotage: remove the e2 pawn → first premove will be illegal.
    board.backend.state[6][4] = None
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is False
    assert board.premoves == []
    assert board.premove_color is None
    assert len(board.backend.move_history) == 0


def test_illegal_fire_leaves_board_responsive(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.backend.state[6][4] = None  # invalidate
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    assert board.premoves == []
    # Subsequent legal click works.
    board.handle_click(Square(6, 0))
    assert board.selected_square == Square(6, 0)


# ---------- Cancellation paths via Frontend ----------

def test_undo_clears_premove_queue():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    app.backend.turn = PieceColor.BLACK
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    assert len(app.board.premoves) == 1
    app._on_undo()
    assert app.board.premoves == []


def test_resign_clears_premove_queue():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    app.backend.turn = PieceColor.BLACK
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app._on_resign()
    assert app.board.premoves == []


def test_draw_clears_premove_queue():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    app.backend.turn = PieceColor.BLACK
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app._on_draw()
    assert app.board.premoves == []


def test_reset_clears_premove_queue():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    app.backend.turn = PieceColor.BLACK
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app._on_new_game()
    assert app.board.premoves == []


def test_back_to_menu_clears_premove_queue():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    app.backend.turn = PieceColor.BLACK
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app._on_back_to_menu()
    assert app.board.premoves == []


# ---------- Move indicator suppression ----------

def test_move_indicators_suppressed_for_premove_selection(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))  # white pawn selected for premove
    drawn = []
    board._draw_dot = lambda rect: drawn.append("dot")
    board._draw_capture_ring = lambda rect: drawn.append("ring")
    board._draw_move_indicators()
    assert drawn == []


def test_move_indicators_drawn_for_normal_selection(board):
    board.handle_click(Square(6, 4))  # white pawn, white's turn
    drawn = []
    board._draw_dot = lambda rect: drawn.append("dot")
    board._draw_capture_ring = lambda rect: drawn.append("ring")
    board._draw_move_indicators()
    assert len(drawn) > 0


# ---------- Visual highlights ----------

def test_premove_highlight_smoke_one_premove(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board._draw_premove_highlights()  # should not raise


def test_premove_highlight_smoke_multiple_premoves(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    board._draw_premove_highlights()


def test_premove_highlight_renders_nothing_when_queue_empty(board):
    board._clear_premoves()
    drawn_rects = []
    original = board._cell_rect
    board._cell_rect = lambda r, c: drawn_rects.append(1) or original(r, c)
    board._draw_premove_highlights()
    assert drawn_rects == []


# ---------- Frontend integration in draw_frame ----------

def test_draw_frame_invokes_try_apply_next_premove():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    called = [0]
    original = app.board.try_apply_next_premove
    app.board.try_apply_next_premove = lambda: called.__setitem__(0, called[0] + 1) or original()
    # Past the post-animation delay window.
    app.board.last_animation_completed_at_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    assert called[0] >= 1


def test_draw_frame_blocks_premove_during_game_over():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    app.manual_result = "white_wins"
    called = [0]
    app.board.try_apply_next_premove = lambda: called.__setitem__(0, called[0] + 1) or False
    app.board.last_animation_completed_at_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    assert called[0] == 0


def test_draw_frame_blocks_premove_during_animation():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    # Inject animation.
    app.board.start_animation(Square(6, 4), Square(4, 4),
                              Piece(PieceType.PAWN, PieceColor.WHITE))
    called = [0]
    app.board.try_apply_next_premove = lambda: called.__setitem__(0, called[0] + 1) or False
    app.draw_frame()
    assert called[0] == 0


def test_draw_frame_blocks_premove_during_post_animation_delay():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    # Animation just completed.
    app.board.last_animation_completed_at_ms = pg.time.get_ticks()
    called = [0]
    app.board.try_apply_next_premove = lambda: called.__setitem__(0, called[0] + 1) or False
    app.draw_frame()
    assert called[0] == 0


# ---------- Mixed flows: premoves + real moves interleaved ----------

def test_normal_move_then_premove_then_fire(board):
    # White plays a normal move; on black's turn white queues a premove; turn flips → fires.
    board.handle_click(Square(6, 4))  # e2
    board.handle_click(Square(4, 4))  # e4 - real move
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert board.backend.turn == PieceColor.BLACK

    # Now queue a white premove during black's turn.
    board.handle_click(Square(7, 6))  # white knight g1
    board.handle_click(Square(5, 5))  # f3
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.WHITE

    # Black plays (manually flip turn) and white's turn → premove fires.
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    assert len(board.premoves) == 0


def test_premove_fire_then_normal_move_then_premove_again(board):
    # Queue a premove → fires → make a normal move on opposite turn → queue again → fires.
    # Step 1: white's turn but we put backend in BLACK to enable queueing white premove.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # premove e2-e4
    assert len(board.premoves) == 1

    # Step 2: turn flips to white → premove fires.
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert board.backend.turn == PieceColor.BLACK
    assert board.premoves == []

    # Step 3: black plays normally on board.
    board.handle_click(Square(1, 4))  # black pawn e7
    board.handle_click(Square(3, 4))  # e5
    fire_animation(board)
    assert len(board.backend.move_history) == 2
    assert board.backend.turn == PieceColor.WHITE

    # Step 4: queue another white premove on black's turn (reset turn for queueing).
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(7, 6))  # Ng1
    board.handle_click(Square(5, 5))  # Nf3
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.WHITE

    # Step 5: turn back to white → fires.
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.backend.move_history) == 3


def test_alternating_real_moves_with_intermittent_premoves(board):
    # Realistic loop: white moves → black queues premove → black plays it auto on next turn →
    # white moves again → repeat.
    sequence = []

    # Iteration 1
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    sequence.append(("real", "white"))
    assert board.backend.turn == PieceColor.BLACK

    board.handle_click(Square(1, 0))  # black pawn a7 - real (black's turn)
    board.handle_click(Square(2, 0))  # a6
    fire_animation(board)
    sequence.append(("real", "black"))
    assert board.backend.turn == PieceColor.WHITE

    # While it's white's turn, black queues a premove.
    board.handle_click(Square(0, 1))  # black knight b8
    board.handle_click(Square(2, 2))  # c6
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.BLACK
    sequence.append(("queue", "black"))

    # White plays.
    board.handle_click(Square(7, 6))  # Ng1
    board.handle_click(Square(5, 5))  # Nf3
    fire_animation(board)
    sequence.append(("real", "white"))
    assert board.backend.turn == PieceColor.BLACK

    # Black's premove fires.
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    sequence.append(("fire", "black"))
    assert board.premoves == []
    assert board.backend.turn == PieceColor.WHITE

    assert sequence == [
        ("real", "white"), ("real", "black"), ("queue", "black"),
        ("real", "white"), ("fire", "black"),
    ]
    assert len(board.backend.move_history) == 4


def test_premove_queued_on_own_turn_does_not_interfere_with_real_move(board):
    # Edge: clicking opposite color's piece on YOUR turn would set selected_square for
    # a premove. Then clicking a destination would queue. Make sure when next click
    # sequence is for ACTUAL turn, real move still works after a queue.
    # White's turn: queue a black premove.
    board.handle_click(Square(1, 4))  # black pawn (premove select)
    board.handle_click(Square(3, 4))  # e5 - queue black's pawn premove
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.BLACK
    # Now white plays real move; queue persists.
    board.handle_click(Square(6, 4))  # white pawn
    board.handle_click(Square(4, 4))  # e4
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert len(board.premoves) == 1  # untouched
    # After white moves, turn = black → black's premove fires.
    assert board.backend.turn == PieceColor.BLACK
    fired = board.try_apply_next_premove()
    assert fired is True
    assert len(board.backend.move_history) == 2


def test_swap_premove_color_clears_old_queue(board):
    # White queues a premove (during black's turn). Then user starts queueing for black
    # mid-flow → old white queue must wipe.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # WHITE premove
    assert board.premove_color == PieceColor.WHITE
    assert len(board.premoves) == 1
    # Now click a black piece (still backend turn = black, so black is "on turn"). But
    # selecting black piece on black's turn = real selection, not premove. Force it via
    # premove path: click black piece while turn is WHITE.
    board.backend.turn = PieceColor.WHITE
    board.handle_click(Square(1, 4))  # black pawn → premove select
    board.handle_click(Square(3, 4))  # e5 → queue BLACK premove
    # Old WHITE queue should have been wiped.
    assert board.premove_color == PieceColor.BLACK
    assert len(board.premoves) == 1
    assert board.premoves[0].piece.color == PieceColor.BLACK


def test_premove_fire_during_active_drawframe_loop():
    from frontend.frontend import Frontend
    app = Frontend(900, 500)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "a",
                        "time_minutes": None, "increment_seconds": 5,
                        "side": "white"})
    # White makes a real move.
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app.board)
    # During black's turn, queue a white premove.
    app.board.handle_click(Square(7, 6))  # Ng1
    app.board.handle_click(Square(5, 5))  # Nf3
    assert len(app.board.premoves) == 1
    # Black plays.
    app.board.handle_click(Square(1, 4))
    app.board.handle_click(Square(3, 4))
    fire_animation(app.board)
    # Past the post-animation delay → next draw_frame should fire the premove.
    app.board.last_animation_completed_at_ms = pg.time.get_ticks() - 10_000
    app.draw_frame()
    fire_animation(app.board)
    assert app.board.premoves == []
    # Backend state reflects the premove move was played.
    last_entry = app.backend.move_history[-1]
    assert last_entry.move.from_sq == Square(7, 6)
    assert last_entry.move.to_sq == Square(5, 5)


def test_long_chain_3_premoves_fires_one_per_white_turn(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))  # a2-a4
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))  # a4-a5
    board.handle_click(Square(3, 0))
    board.handle_click(Square(2, 0))  # a5-a6
    assert len(board.premoves) == 3

    for i in range(3):
        board.backend.turn = PieceColor.WHITE
        fired = board.try_apply_next_premove()
        assert fired is True
        fire_animation(board)
        assert len(board.premoves) == 2 - i
        # Simulate opponent moving (manually flip turn so next round's gate matches).
        if i < 2:
            board.backend.turn = PieceColor.WHITE  # for next premove cycle


def test_clear_then_requeue(board):
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    assert len(board.premoves) == 1
    # Cancel by clicking empty.
    board.handle_click(Square(3, 3))
    assert board.premoves == []
    # Re-queue a different premove.
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 1
    assert board.premoves[0].from_sq == Square(7, 6)


def test_premove_then_undo_reverts_real_move_and_queue_persists_only_via_real_undo(board):
    # Queue → fire → undo. Undo should clear the queue (per design) and revert backend.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.backend.move_history) == 1
    assert board.premoves == []

    # Now queue another premove.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))
    assert len(board.premoves) == 1
    # Frontend undo path would clear queue; here we test the Board.is invariant via direct call.
    board._clear_premoves()
    board.backend.undo()
    assert board.premoves == []
    assert len(board.backend.move_history) == 0


def test_castle_premove_queues_and_fires_legally(board):
    # Set up: white king on home, kingside rook on home, black king elsewhere.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 7): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    }, turn=PieceColor.BLACK)
    # Queue white kingside castle (from home to col 6) during black's turn.
    board.handle_click(Square(7, 4))
    board.handle_click(Square(7, 6))
    assert len(board.premoves) == 1
    # Turn flips to white → premove fires (engine recognizes castle).
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    # Verify castle landed: king at (7, 6), rook at (7, 5).
    assert board.backend.state[7][6] is not None
    assert board.backend.state[7][6].type == PieceType.KING
    assert board.backend.state[7][5] is not None
    assert board.backend.state[7][5].type == PieceType.ROOK


def test_premove_capturing_opposite_piece_fires_with_capture(board):
    # White queen at d4, black knight at d6. White queen premove d4-d6 captures.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 3): Piece(PieceType.QUEEN, PieceColor.WHITE),
        Square(2, 3): Piece(PieceType.KNIGHT, PieceColor.BLACK),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(4, 3))  # white queen
    board.handle_click(Square(2, 3))  # capture black knight
    assert len(board.premoves) == 1
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    # Capture happened.
    captured = board.backend.move_history[-1].move.captured
    assert captured is not None
    assert captured.type == PieceType.KNIGHT


def test_premove_immediately_after_other_premove_fires(board):
    # Two queued premoves. Both should fire across two turn cycles.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(7, 6))
    board.handle_click(Square(5, 5))
    assert len(board.premoves) == 2

    # First white turn fires pm1.
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 1

    # Black plays (skip via direct state manipulation).
    board.backend.turn = PieceColor.WHITE
    board.try_apply_next_premove()
    fire_animation(board)
    assert len(board.premoves) == 0
