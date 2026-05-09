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


def test_bishop_sideways_queues_lax(board):
    # Premove queueing is now lax: any shape is queued, legality is verified at
    # execution time (when the engine refuses, the chain is wiped).
    board.backend.turn = PieceColor.BLACK
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(PieceType.BISHOP, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    board.handle_click(Square(4, 4))
    board.handle_click(Square(4, 7))
    assert len(board.premoves) == 1


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
    app._perform_resign()
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
    app._perform_draw()
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


def test_chain_clicking_original_from_square_resolves_to_tip(board):
    # User queues e2-e4. Then clicks e2 (the visual location) to chain — should
    # resolve to e4 (the speculative tip) and let them queue e4-e5.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # premove e2-e4
    assert len(board.premoves) == 1
    # Click the ORIGINAL e2 square — the pawn is visually still there, but speculatively
    # at e4. Should resolve to e4.
    board.handle_click(Square(6, 4))
    assert board.selected_square == Square(4, 4)
    # Now extend the chain.
    board.handle_click(Square(3, 4))  # e4-e5
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(4, 4)
    assert board.premoves[1].to_sq == Square(3, 4)


def test_chain_three_deep_clicking_original_resolves_to_final_tip(board):
    # Queue a3 -> a4 -> a5. Click a2 (original) -> resolves to a5, allow a5-a6.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(5, 0))  # a2-a3
    board.handle_click(Square(5, 0))
    board.handle_click(Square(4, 0))  # a3-a4
    board.handle_click(Square(4, 0))
    board.handle_click(Square(3, 0))  # a4-a5
    assert len(board.premoves) == 3
    # Click ORIGINAL a2 → should resolve to a5.
    board.handle_click(Square(6, 0))
    assert board.selected_square == Square(3, 0)
    # Continue the chain.
    board.handle_click(Square(2, 0))  # a5-a6
    assert len(board.premoves) == 4
    assert board.premoves[3].from_sq == Square(3, 0)


def test_chain_clicking_intermediate_square_resolves_to_tip(board):
    # Chain a2->a4->a5. Click a4 (intermediate) → resolves to a5.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 0))
    board.handle_click(Square(4, 0))  # a2-a4
    # Click a4 (this IS the speculative tip; no resolution needed).
    board.handle_click(Square(4, 0))
    assert board.selected_square == Square(4, 0)
    # Queue a4-a5.
    board.handle_click(Square(3, 0))
    assert len(board.premoves) == 2
    # Now click an intermediate square (a4) — speculatively that's still empty (piece is at a5).
    # Should resolve forward through chain to a5.
    board.handle_click(Square(4, 0))
    assert board.selected_square == Square(3, 0)


def test_capture_target_of_opponent_premove_with_my_threatened_piece(board):
    # Bug repro: black queues Rd2xd4 (would capture white rook at d4) during
    # white's turn. Then white plays Rxd2 — the white rook on d4, despite the
    # speculative state showing a black rook on d4, must remain selectable as
    # white's own piece based on the LIVE state.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 3): Piece(PieceType.ROOK, PieceColor.WHITE),  # d4
        Square(6, 3): Piece(PieceType.ROOK, PieceColor.BLACK),  # d2
    }, turn=PieceColor.WHITE)
    # Black queues Rd2xd4 (during white's turn).
    board.handle_click(Square(6, 3))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 1
    assert board.premove_color == PieceColor.BLACK
    # White plays Rxd2 — selecting d4 should grab the white rook (live state),
    # not the speculative black rook.
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
    # Variant: white moves the rook elsewhere instead of capturing.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 3): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(6, 3): Piece(PieceType.ROOK, PieceColor.BLACK),
    }, turn=PieceColor.WHITE)
    board.handle_click(Square(6, 3))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 1
    # White moves the rook sideways to a4.
    board.handle_click(Square(4, 3))
    board.handle_click(Square(4, 0))
    assert len(board.backend.move_history) == 1
    last = board.backend.move_history[-1].move
    assert last.from_sq == Square(4, 3)
    assert last.to_sq == Square(4, 0)
    assert last.captured is None


def test_clicking_truly_empty_square_still_cancels(board):
    # Make sure resolution doesn't break the cancel-on-empty behavior.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # premove
    assert len(board.premoves) == 1
    # Click a square that has no piece in either backend state OR queued premove paths.
    board.handle_click(Square(3, 3))
    assert board.premoves == []


def test_chain_resolution_does_not_trigger_when_no_relevant_premove(board):
    # Click an empty square that isn't a from_sq of any premove → should cancel queue (or noop).
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))  # premove e2-e4
    # Click e3 (NOT a from_sq of any premove).
    board.handle_click(Square(5, 4))
    # Should cancel (no resolution found).
    assert board.premoves == []
    assert board.selected_square is None


def test_chain_via_resolution_then_fire(board):
    # Full path: queue, chain via original-square click, then fire both.
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    board.handle_click(Square(6, 4))  # click original to chain
    board.handle_click(Square(3, 4))
    assert len(board.premoves) == 2

    # Fire first.
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    assert len(board.premoves) == 1

    # Fire second.
    board.backend.turn = PieceColor.WHITE
    fired = board.try_apply_next_premove()
    assert fired is True
    fire_animation(board)
    assert len(board.premoves) == 0
    assert len(board.backend.move_history) == 2


def test_scholars_mate_via_premove_chain(board):
    # 1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6?? 4. Qxf7#
    # White plays move 1 normally, then queues [Bc4, Qh5, Qxf7] during black's turn,
    # then plays out — each premove fires on white's successive turns and Qxf7 mates.

    # 1. e4
    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))
    fire_animation(board)
    # ... e5
    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))
    fire_animation(board)

    # Queue [Bc4, Qh5, Qxf7] (force black turn so white's piece-clicks become premoves).
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(7, 5))   # Bf1
    board.handle_click(Square(4, 2))   # Bc4 - premove 1
    board.handle_click(Square(7, 3))   # Qd1
    board.handle_click(Square(3, 7))   # Qh5 - premove 2
    board.handle_click(Square(7, 3))   # Qd1 (original) → resolves to Qh5
    board.handle_click(Square(1, 5))   # Qxf7 - premove 3
    assert len(board.premoves) == 3

    # Fire Bc4 (white's turn).
    board.backend.turn = PieceColor.WHITE
    assert board.try_apply_next_premove() is True
    fire_animation(board)
    # 2... Nc6
    board.handle_click(Square(0, 1))
    board.handle_click(Square(2, 2))
    fire_animation(board)
    # Fire Qh5
    assert board.try_apply_next_premove() is True
    fire_animation(board)
    # 3... Nf6 (the blunder)
    board.handle_click(Square(0, 6))
    board.handle_click(Square(2, 5))
    fire_animation(board)
    # Fire Qxf7 — checkmate.
    assert board.try_apply_next_premove() is True
    fire_animation(board)

    assert board.backend.game_result() == "white_wins"
    assert board.premoves == []


def test_scholars_mate_chain_aborts_when_queen_captured_mid_chain(board):
    # White queues [Qh5, Qxf7]. Black plays Nf6 (attacks h5). Qh5 fires anyway —
    # engine accepts the move (it's a blunder, not illegal). Black then captures the
    # queen with Nxh5. White's turn → Qxf7 has no queen on h5 → illegal → queue wiped.

    board.handle_click(Square(6, 4))
    board.handle_click(Square(4, 4))   # 1. e4
    fire_animation(board)
    board.handle_click(Square(1, 4))
    board.handle_click(Square(3, 4))   # 1... e5
    fire_animation(board)

    # Queue [Qh5, Qxf7] during black's turn (manually flipped).
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(7, 3))
    board.handle_click(Square(3, 7))   # premove Qd1-h5
    board.handle_click(Square(7, 3))   # original d1 → resolves to h5 via chain
    board.handle_click(Square(1, 5))   # premove Qh5xf7
    assert len(board.premoves) == 2

    # 2... Nf6 (black knight attacks h5).
    board.backend.turn = PieceColor.BLACK
    board.handle_click(Square(0, 6))
    board.handle_click(Square(2, 5))
    fire_animation(board)

    # White's turn → Qh5 fires (legal, just a blunder).
    assert board.try_apply_next_premove() is True
    fire_animation(board)
    assert board.backend.state[3][7] is not None
    assert board.backend.state[3][7].type == PieceType.QUEEN

    # 3... Nxh5 (black captures queen).
    board.handle_click(Square(2, 5))
    board.handle_click(Square(3, 7))
    fire_animation(board)
    assert board.backend.state[3][7].type == PieceType.KNIGHT

    # White's turn → Qxf7 fails (no queen on h5) → queue cleared entirely.
    fired = board.try_apply_next_premove()
    assert fired is False
    assert board.premoves == []
    assert board.premove_color is None
    # White's queen is gone, no third move was played.
    history_len_before = len(board.backend.move_history)
    fired_again = board.try_apply_next_premove()
    assert fired_again is False
    assert len(board.backend.move_history) == history_len_before


def test_chain_capture_continues_with_local_color(board):
    # Same scenario but in online mode (Match.local_color = WHITE). The bug
    # was that during black's turn _try_select silently rejected the click
    # because the live g7 piece is black, so the chain extension got swallowed.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 5): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(1, 6): Piece(PieceType.PAWN, PieceColor.BLACK),
        Square(1, 7): Piece(PieceType.PAWN, PieceColor.BLACK),
    }, turn=PieceColor.BLACK)
    board.match.local_color = PieceColor.WHITE
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
    # Online-mode equivalent of test_capture_target_of_opponent_premove_with_my_threatened_piece:
    # white-with-local_color=WHITE must grab the LIVE white rook on its turn,
    # NOT the speculative black rook parked there by a leftover black premove
    # that was queued before local_color was set.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 3): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(6, 3): Piece(PieceType.ROOK, PieceColor.BLACK),
    }, turn=PieceColor.WHITE)
    # Queue black's Rd2xd4 with local_color cleared (simulating a queue that
    # was built before the local-color guard kicked in, or in a different mode).
    board.handle_click(Square(6, 3))
    board.handle_click(Square(4, 3))
    assert len(board.premoves) == 1
    board.match.local_color = PieceColor.WHITE
    # White (local) selects d4 → must hit the live white rook, not the spec.
    board.handle_click(Square(4, 3))
    assert board.selected_square == Square(4, 3)
    board.handle_click(Square(6, 3))
    assert len(board.backend.move_history) == 1
    last = board.backend.move_history[-1].move
    assert last.from_sq == Square(4, 3)
    assert last.to_sq == Square(6, 3)
    assert last.captured is not None and last.captured.type == PieceType.ROOK


def test_online_opponent_turn_click_on_opp_piece_does_nothing_when_no_chain(board):
    # With local_color set and no premoves queued, clicking an opp piece on
    # opp's turn should be a noop (no select, no phantom premove).
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 5): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(1, 6): Piece(PieceType.PAWN, PieceColor.BLACK),
    }, turn=PieceColor.BLACK)
    board.match.local_color = PieceColor.WHITE
    board.handle_click(Square(1, 6))
    assert board.selected_square is None
    assert board.premoves == []


def _start_drag(board, sq):
    """Simulate the click-then-drag sequence the frontend produces for a left-press."""
    board.handle_click(sq)
    board.begin_press((0, 0))
    cell = board.cell_size
    cx = sq.col * cell + board.board_offset_x + cell // 2
    cy = sq.row * cell + board.board_offset_y + cell // 2
    board._press_pos = (cx - 50, cy - 50)
    board.update_drag_motion((cx, cy))


def test_right_click_during_drag_queues_premove(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    _start_drag(board, Square(6, 4))
    assert board.dragging_from == Square(6, 4)
    assert board.queue_premove_from_drag(Square(4, 4)) is True
    assert len(board.premoves) == 1
    assert board.premoves[0].from_sq == Square(6, 4)
    assert board.premoves[0].to_sq == Square(4, 4)


def test_right_click_during_drag_keeps_dragging_for_chain(board):
    # Drag stays active so the user can chain more premoves with the same hold.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    _start_drag(board, Square(6, 4))
    board.queue_premove_from_drag(Square(4, 4))
    assert board.dragging_from == Square(6, 4)
    assert board._drag_cursor is not None
    # Chain tip resolves dynamically via _resolve_chain_tip(dragging_from).
    assert board._resolve_chain_tip(board.dragging_from) == Square(4, 4)


def test_right_click_during_drag_chains_inside_single_hold(board):
    # Same drag, two right-clicks: chain head advances along the queued tips.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 5): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(1, 6): Piece(PieceType.PAWN, PieceColor.BLACK),
        Square(1, 7): Piece(PieceType.PAWN, PieceColor.BLACK),
    }, turn=PieceColor.BLACK)
    board.match.local_color = PieceColor.WHITE
    _start_drag(board, Square(1, 5))
    board.queue_premove_from_drag(Square(1, 6))
    assert len(board.premoves) == 1
    # Still dragging — second right-click queues from the new tip g7 to h7.
    assert board.dragging_from == Square(1, 5)
    assert board._resolve_chain_tip(board.dragging_from) == Square(1, 6)
    board.queue_premove_from_drag(Square(1, 7))
    assert len(board.premoves) == 2
    assert board.premoves[1].from_sq == Square(1, 6)
    assert board.premoves[1].to_sq == Square(1, 7)
    assert board._resolve_chain_tip(board.dragging_from) == Square(1, 7)


def test_right_click_during_drag_lax_shape_still_queues(board):
    # Simplified premove logic: queueing accepts any shape — legality verified
    # only at execution. A rook moving diagonally still gets queued.
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    _start_drag(board, Square(7, 0))
    assert board.queue_premove_from_drag(Square(5, 2)) is True
    assert len(board.premoves) == 1


def test_right_click_during_drag_same_square_no_queue(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    _start_drag(board, Square(6, 4))
    assert board.queue_premove_from_drag(Square(6, 4)) is False
    assert board.premoves == []
    assert board.dragging_from == Square(6, 4)


def test_right_click_drag_premove_skipped_when_not_dragging(board):
    assert board.queue_premove_from_drag(Square(4, 4)) is False
    assert board.premoves == []


def test_right_click_drag_premove_blocked_for_opp_piece_in_online(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 4): Piece(PieceType.PAWN, PieceColor.BLACK),
    }, turn=PieceColor.BLACK)
    board.match.local_color = PieceColor.WHITE
    # Online client cannot drag opponent's piece in the first place, but if
    # somehow the drag started, the queue helper must reject it.
    board.dragging_from = Square(1, 4)
    board.selected_square = Square(1, 4)
    assert board.queue_premove_from_drag(Square(2, 4)) is False
    assert board.premoves == []


def test_right_click_drag_premove_chain_clears_when_drag_ends(board):
    setup_position(board, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(6, 4): Piece(PieceType.PAWN, PieceColor.WHITE),
    }, turn=PieceColor.BLACK)
    _start_drag(board, Square(6, 4))
    board.queue_premove_from_drag(Square(4, 4))
    board.end_press()
    assert board.dragging_from is None
    assert board._drag_cursor is None


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
