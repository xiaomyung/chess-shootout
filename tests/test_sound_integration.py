import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.utils import Square
from frontend.frontend import Frontend
from backend.pieces import Piece, PieceColor, PieceType


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.mixer.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def base_config(**overrides):
    cfg = {
        "mode": "single_screen",
        "nickname": "alice",
        "time_minutes": 5,
        "increment_seconds": 2,
        "side": "white",
    }
    cfg.update(overrides)
    return cfg


def make_app():
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    return app


# ---------- Game-start hook ----------

def test_start_game_single_screen_plays_game_start():
    app = make_app()
    app._on_start_game(base_config())
    app.sound_manager.play_game_start.assert_called_once()


def test_start_game_calls_stop_all_before_play_game_start():
    app = make_app()
    app._on_start_game(base_config())
    calls = [c[0] for c in app.sound_manager.method_calls]
    assert "stop_all" in calls
    assert "play_game_start" in calls
    assert calls.index("stop_all") < calls.index("play_game_start")


def test_start_game_bot_inert():
    app = make_app()
    app._on_start_game(base_config(mode="bot"))
    app.sound_manager.play_game_start.assert_not_called()
    app.sound_manager.stop_all.assert_not_called()


def test_start_game_online_inert():
    app = make_app()
    app._on_start_game(base_config(mode="online"))
    app.sound_manager.play_game_start.assert_not_called()


def test_new_game_plays_game_start():
    app = make_app()
    app._on_start_game(base_config())
    app.sound_manager.reset_mock()
    app._on_new_game()
    app.sound_manager.stop_all.assert_called()
    app.sound_manager.play_game_start.assert_called_once()


def test_back_to_menu_does_not_play_game_start():
    app = make_app()
    app._on_start_game(base_config())
    app.sound_manager.reset_mock()
    app._on_back_to_menu()
    app.sound_manager.stop_all.assert_called()
    app.sound_manager.play_game_start.assert_not_called()


# ---------- Undo hook ----------

def test_undo_plays_rewind():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app.board.cancel_animations()
    app.sound_manager.reset_mock()
    app._on_undo()
    app.sound_manager.play_undo.assert_called_once()


def test_undo_with_empty_history_does_not_play_undo():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app._on_undo()
    app.sound_manager.play_undo.assert_not_called()


def test_undo_with_manual_result_does_not_play_undo():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.manual_result = "white_wins"
    app.sound_manager.reset_mock()
    app._on_undo()
    app.sound_manager.play_undo.assert_not_called()


def test_takeback_applied_plays_undo_sound():
    # Online flow: opponent accepted our takeback request, server replies
    # with takeback_applied. The sound should play just like a local undo.
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app.board.cancel_animations()
    app.sound_manager.reset_mock()
    app._handle_takeback_applied({"clock": {}})
    app.sound_manager.play_undo.assert_called_once()


def test_takeback_applied_with_empty_history_does_not_play_undo():
    # If somehow takeback_applied arrives with no history (edge case during
    # rapid disconnect), don't fire the rewind sound for nothing.
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app._handle_takeback_applied({"clock": {}})
    app.sound_manager.play_undo.assert_not_called()


# ---------- Move-landed dispatch ----------

def fire_animation(app):
    app.board.animations[0].start_ms = pg.time.get_ticks() - 10_000
    app.board._draw_animations()


def setup_position(app, piece_map, turn=PieceColor.WHITE):
    backend = app.backend
    backend.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        backend.state[sq.row][sq.col] = piece
    backend.turn = turn
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1


def test_normal_move_plays_only_move():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app)
    app.sound_manager.play_move.assert_called_once()
    app.sound_manager.play_capture.assert_not_called()
    app.sound_manager.play_check.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


def test_capture_plays_move_and_capture():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(PieceType.QUEEN, PieceColor.WHITE),
        Square(4, 7): Piece(PieceType.PAWN, PieceColor.BLACK),
    })
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(4, 4))
    app.board.handle_click(Square(4, 7))
    fire_animation(app)
    app.sound_manager.play_move.assert_called_once()
    # Capture sound is keyed on the CAPTURING piece (queen), not the captured (pawn).
    app.sound_manager.play_capture.assert_called_once_with(PieceType.QUEEN)
    app.sound_manager.play_check.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


@pytest.mark.parametrize("attacker_type,target_type", [
    (PieceType.PAWN, PieceType.QUEEN),
    (PieceType.KNIGHT, PieceType.PAWN),
    (PieceType.BISHOP, PieceType.ROOK),
    (PieceType.ROOK, PieceType.BISHOP),
    (PieceType.QUEEN, PieceType.KNIGHT),
])
def test_capture_dispatches_capturing_piece_type(attacker_type, target_type):
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 0): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 0): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(attacker_type, PieceColor.WHITE),
        Square(3, 4): Piece(target_type, PieceColor.BLACK),
    })
    # For pieces that can't move 1 square forward (e.g., pawn captures diagonally),
    # arrange the target so the move is legal: pawn captures diagonally, knight L-shape, etc.
    if attacker_type == PieceType.PAWN:
        # White pawn at (4, 4) captures diagonally to (3, 5).
        app.backend.state[3][4] = None
        app.backend.state[3][5] = Piece(target_type, PieceColor.BLACK)
        from_sq, to_sq = Square(4, 4), Square(3, 5)
    elif attacker_type == PieceType.KNIGHT:
        # Knight at (4, 4) captures at (2, 3).
        app.backend.state[3][4] = None
        app.backend.state[2][3] = Piece(target_type, PieceColor.BLACK)
        from_sq, to_sq = Square(4, 4), Square(2, 3)
    elif attacker_type == PieceType.BISHOP:
        # Bishop at (4, 4) captures diagonally at (2, 6).
        app.backend.state[3][4] = None
        app.backend.state[2][6] = Piece(target_type, PieceColor.BLACK)
        from_sq, to_sq = Square(4, 4), Square(2, 6)
    else:
        # Rook / queen: straight move from (4, 4) to (3, 4).
        from_sq, to_sq = Square(4, 4), Square(3, 4)
    app.sound_manager.reset_mock()
    app.board.handle_click(from_sq)
    app.board.handle_click(to_sq)
    fire_animation(app)
    app.sound_manager.play_capture.assert_called_once_with(attacker_type)


def test_check_plays_move_and_check():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
    })
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(4, 0))
    app.board.handle_click(Square(0, 0))
    fire_animation(app)
    app.sound_manager.play_move.assert_called_once()
    app.sound_manager.play_check.assert_called_once()
    app.sound_manager.play_capture.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


def test_checkmate_plays_only_checkmate_no_move():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(2, 6): Piece(PieceType.KING, PieceColor.WHITE),
        Square(2, 0): Piece(PieceType.QUEEN, PieceColor.WHITE),
        Square(0, 7): Piece(PieceType.KING, PieceColor.BLACK),
    })
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(2, 0))
    app.board.handle_click(Square(0, 0))
    fire_animation(app)
    app.sound_manager.play_checkmate.assert_called_once()
    app.sound_manager.play_move.assert_not_called()
    app.sound_manager.play_capture.assert_not_called()
    # We don't fire play_check on a mate (mate supersedes it).
    app.sound_manager.play_check.assert_not_called()


def test_castle_kingside_plays_castle_sound_not_move():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 7): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    app.backend.castling_rights = {"WK": True, "WQ": False, "BK": False, "BQ": False}
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(7, 4))
    app.board.handle_click(Square(7, 6))
    for a in list(app.board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    app.board._draw_animations()
    app.sound_manager.play_castle.assert_called_once()
    app.sound_manager.play_move.assert_not_called()
    app.sound_manager.play_capture.assert_not_called()
    app.sound_manager.play_check.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


def test_castle_queenside_plays_castle_sound():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    app.backend.castling_rights = {"WK": False, "WQ": True, "BK": False, "BQ": False}
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(7, 4))
    app.board.handle_click(Square(7, 2))
    for a in list(app.board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    app.board._draw_animations()
    app.sound_manager.play_castle.assert_called_once()
    app.sound_manager.play_move.assert_not_called()


def test_castle_with_check_plays_castle_and_check():
    # White castles queenside; the rook lands on d1 attacking the black king on d8.
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 0): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 3): Piece(PieceType.KING, PieceColor.BLACK),
    })
    app.backend.castling_rights = {"WK": False, "WQ": True, "BK": False, "BQ": False}
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(7, 4))
    app.board.handle_click(Square(7, 2))
    for a in list(app.board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    app.board._draw_animations()
    app.sound_manager.play_castle.assert_called_once()
    app.sound_manager.play_check.assert_called_once()
    app.sound_manager.play_move.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


def test_castle_dispatch_fires_only_once_for_two_animations():
    # Castling spawns king + rook animations; only the king's on_complete dispatches.
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(7, 7): Piece(PieceType.ROOK, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
    })
    app.backend.castling_rights = {"WK": True, "WQ": False, "BK": False, "BQ": False}
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(7, 4))
    app.board.handle_click(Square(7, 6))
    assert len(app.board.animations) == 2
    for a in list(app.board.animations):
        a.start_ms = pg.time.get_ticks() - 10_000
    app.board._draw_animations()
    assert app.sound_manager.play_castle.call_count == 1


def test_reverse_animation_does_not_fire_dispatch():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    fire_animation(app)
    app.sound_manager.reset_mock()
    app._on_undo()
    fire_animation(app)
    app.sound_manager.play_move.assert_not_called()
    app.sound_manager.play_capture.assert_not_called()


def test_promotion_lands_no_sound_until_picker_chosen():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 0): Piece(PieceType.PAWN, PieceColor.WHITE),
    })
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(1, 0))
    app.board.handle_click(Square(0, 0))
    fire_animation(app)
    # Picker shown; no move-landed dispatch yet.
    app.sound_manager.play_move.assert_not_called()
    assert app.board.pending_promotion_square == Square(0, 0)
    # User picks queen → fires dispatch.
    app.board.handle_click(Square(0, 0))
    app.sound_manager.play_move.assert_called_once()


# ---------- Heartbeat hook in draw_frame ----------

def test_draw_frame_in_menu_passes_paused_true():
    app = make_app()
    app.draw_frame()
    args, kwargs = app.sound_manager.update_heartbeat.call_args
    assert args == (None, True) or args[1] is True


def test_draw_frame_in_game_with_clock_not_paused():
    app = make_app()
    app._on_start_game(base_config())
    app.sound_manager.reset_mock()
    app.draw_frame()
    args, kwargs = app.sound_manager.update_heartbeat.call_args
    fraction, paused = args
    assert paused is False
    assert 0.0 <= fraction <= 1.0


def test_draw_frame_after_manual_result_paused_true():
    app = make_app()
    app._on_start_game(base_config())
    app.manual_result = "white_wins"
    app.sound_manager.reset_mock()
    app.draw_frame()
    fraction, paused = app.sound_manager.update_heartbeat.call_args[0]
    assert paused is True
    assert fraction is None


def test_draw_frame_after_engine_timeout_paused_true():
    app = make_app()
    app._on_start_game(base_config())
    app.backend.clock.flagged = PieceColor.WHITE
    app.backend.clock.white_remaining = 0
    app.sound_manager.reset_mock()
    app.draw_frame()
    fraction, paused = app.sound_manager.update_heartbeat.call_args[0]
    assert paused is True


def test_draw_frame_no_clock_passes_none_paused_true():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.draw_frame()
    fraction, paused = app.sound_manager.update_heartbeat.call_args[0]
    assert fraction is None
    assert paused is True


def test_draw_frame_fraction_reflects_side_to_move():
    app = make_app()
    app._on_start_game(base_config(time_minutes=5))
    # White's clock starts at 300s; clock runs between events, so allow tolerance.
    app.backend.clock.white_remaining = 60.0
    app.sound_manager.reset_mock()
    app.draw_frame()
    fraction, paused = app.sound_manager.update_heartbeat.call_args[0]
    assert fraction == pytest.approx(0.2, abs=0.01)
