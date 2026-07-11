"""Frontend -> SoundManager dispatch contract.

The Frontend's sound_manager is replaced with a MagicMock so each test asserts
*which* play_* method the game-event plumbing invokes (and with what argument),
not the underlying pygame playback. Move-landed sounds fire from animation
on_complete callbacks, so tests drive animations to completion via fire_animation
before asserting.
"""

from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.backend.utils import Square
from chessshootout.domain.match import ONLINE
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from tests.helpers import make_app as _shared_make_app


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
    return _shared_make_app(1000, 800)


@pytest.mark.parametrize("mode, plays_start, stops_all", [
    pytest.param("single_screen", True, True, id="single_screen_resets_and_plays"),
    pytest.param("bot", False, False, id="bot_returns_inert_no_reset"),
    pytest.param("online", False, False, id="online_defers_to_flow_inert"),
])
def test_start_game_mode_dispatch(mode, plays_start, stops_all):
    """Only single_screen runs _reset_to_new_game (stop_all) + play_game_start;
    bot returns before any reset, online hands off to the connect modal."""
    app = make_app()
    app._on_start_game(base_config(mode=mode))
    if plays_start:
        app.sound_manager.play_game_start.assert_called_once()
    else:
        app.sound_manager.play_game_start.assert_not_called()
    if stops_all:
        app.sound_manager.stop_all.assert_called()
    else:
        app.sound_manager.stop_all.assert_not_called()


def test_start_game_calls_stop_all_before_play_game_start():
    app = make_app()
    app._on_start_game(base_config())
    calls = [c[0] for c in app.sound_manager.method_calls]
    assert "stop_all" in calls
    assert "play_game_start" in calls
    assert calls.index("stop_all") < calls.index("play_game_start")


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
    """Online opponent-accepted takeback: takeback_applied fires the rewind sound,
    same as a local undo."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    app.board.cancel_animations()
    app.sound_manager.reset_mock()
    app.game.on_takeback({"clock": {}})
    app.sound_manager.play_undo.assert_called_once()


def test_takeback_applied_with_empty_history_does_not_play_undo():
    """takeback_applied with no history (rapid-disconnect edge) must not fire the
    rewind sound for nothing."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.game.on_takeback({"clock": {}})
    app.sound_manager.play_undo.assert_not_called()


def fire_animation(app):
    em = app.board.effects
    for c in list(em.captures):
        c["fire_at"] = 0
    now = pg.time.get_ticks()
    for i in range(300):
        em.update(now + i * 16)
        if not em.captures:
            break
    if app.board.animations:
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
    app.sound_manager.play_move.assert_called_once_with(PieceType.PAWN)
    app.sound_manager.play_capture.assert_not_called()
    app.sound_manager.play_check.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


def test_capture_plays_move_and_capture():
    """A capture fires play_move + play_capture and nothing else; play_capture is
    keyed on the CAPTURING piece (queen), not the captured (pawn)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.skillcheck.enabled = False
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
    app.sound_manager.play_capture.assert_called_once_with(PieceType.QUEEN)
    app.sound_manager.play_check.assert_not_called()
    app.sound_manager.play_checkmate.assert_not_called()


@pytest.mark.parametrize("attacker_type,target_type", [
    pytest.param(PieceType.PAWN, PieceType.QUEEN, id="pawn_captures_diagonally"),
    pytest.param(PieceType.KNIGHT, PieceType.PAWN, id="knight_captures_l_shape"),
    pytest.param(PieceType.BISHOP, PieceType.ROOK, id="bishop_captures_diagonally"),
    pytest.param(PieceType.ROOK, PieceType.BISHOP, id="rook_captures_straight"),
    pytest.param(PieceType.QUEEN, PieceType.KNIGHT, id="queen_captures_straight"),
])
def test_capture_dispatches_capturing_piece_type(attacker_type, target_type):
    """play_capture is dispatched with the attacker's type across every move
    geometry; the target square is arranged so each attacker's capture is legal."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.skillcheck.enabled = False
    setup_position(app, {
        Square(7, 0): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 0): Piece(PieceType.KING, PieceColor.BLACK),
        Square(4, 4): Piece(attacker_type, PieceColor.WHITE),
        Square(3, 4): Piece(target_type, PieceColor.BLACK),
    })
    if attacker_type == PieceType.PAWN:
        app.backend.state[3][4] = None
        app.backend.state[3][5] = Piece(target_type, PieceColor.BLACK)
        from_sq, to_sq = Square(4, 4), Square(3, 5)
    elif attacker_type == PieceType.KNIGHT:
        app.backend.state[3][4] = None
        app.backend.state[2][3] = Piece(target_type, PieceColor.BLACK)
        from_sq, to_sq = Square(4, 4), Square(2, 3)
    elif attacker_type == PieceType.BISHOP:
        app.backend.state[3][4] = None
        app.backend.state[2][6] = Piece(target_type, PieceColor.BLACK)
        from_sq, to_sq = Square(4, 4), Square(2, 6)
    else:
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
    """Mate fires only play_checkmate; play_check is suppressed (mate supersedes it)."""
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
    """White castles queenside; the rook lands on d1 giving check to the black
    king on d8, so both play_castle and play_check fire."""
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
    """Castling spawns king + rook animations but only the king's on_complete
    dispatches, so play_castle fires exactly once."""
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
    """The move-landed dispatch defers until the promotion picker is resolved:
    no play_move while the picker is open, one play_move after queen is chosen."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.skillcheck.enabled = False
    setup_position(app, {
        Square(7, 4): Piece(PieceType.KING, PieceColor.WHITE),
        Square(0, 4): Piece(PieceType.KING, PieceColor.BLACK),
        Square(1, 0): Piece(PieceType.PAWN, PieceColor.WHITE),
    })
    app.sound_manager.reset_mock()
    app.board.handle_click(Square(1, 0))
    app.board.handle_click(Square(0, 0))
    fire_animation(app)
    app.sound_manager.play_move.assert_not_called()
    assert app.board.pending_promotion_square == Square(0, 0)
    app.board.pick_promotion(PieceType.QUEEN)
    app.sound_manager.play_move.assert_called_once()


def test_draw_frame_in_menu_passes_paused_true():
    """In menu mode there is no live game, so the heartbeat is paused with no
    clock fraction: update_heartbeat(None, True)."""
    app = make_app()
    app.draw_frame()
    fraction, paused = app.sound_manager.update_heartbeat.call_args[0]
    assert paused is True
    assert fraction is None


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
    """Fraction is the side-to-move's remaining over the 300s initial; 60s -> 0.2,
    with tolerance for the clock running between events."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=5))
    app.backend.clock.white_remaining = 60.0
    app.sound_manager.reset_mock()
    app.draw_frame()
    fraction, paused = app.sound_manager.update_heartbeat.call_args[0]
    assert fraction == pytest.approx(0.2, abs=0.01)


def test_draw_result_plays_draw_not_you_win():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.current_result = lambda: "draw_stalemate"
    app._trigger_result_effects()
    app.sound_manager.play_draw.assert_called_once()
    app.sound_manager.play_you_win.assert_not_called()


def test_mate_win_plays_you_win_not_draw():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.current_result = lambda: "white_wins"
    app._trigger_result_effects()
    app.sound_manager.play_you_win.assert_called_once()
    app.sound_manager.play_draw.assert_not_called()


def test_resign_win_plays_you_win_not_surrender():
    """Single-screen resign plays exactly one result voice (you_win), never the
    defeat/surrender voice on top of it (the both-sounds-at-once bug)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.current_result = lambda: "white_wins_by_resignation"
    app._trigger_result_effects()
    app.sound_manager.play_you_win.assert_called_once()
    app.sound_manager.play_surrender.assert_not_called()


def test_flag_result_plays_no_result_voice():
    """A time-flag is neither mate nor resign, so _trigger_result_effects plays no
    you_win/surrender — the loser's you_lose comes from _maybe_play_flag_fall only
    (no defeat+winner double)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.current_result = lambda: "black_wins_on_time"
    app._trigger_result_effects()
    app.sound_manager.play_you_win.assert_not_called()
    app.sound_manager.play_surrender.assert_not_called()


def test_kill_announcer_suppressed_once_game_over():
    """A capturing move that ends the game must not stack the kill-streak voice on
    top of the you_win result voice (first-blood + mate overlap)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.current_result = lambda: "white_wins"
    app._on_kill_announced("first_blood")
    app.sound_manager.play_announcer.assert_not_called()


def test_kill_announcer_plays_while_game_live():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app._on_kill_announced("first_blood")
    app.sound_manager.play_announcer.assert_called_once_with("first_blood")


def test_hit_oof_still_plays_when_game_over():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.current_result = lambda: "white_wins"
    app._on_kill_announced("hit", Piece(PieceType.PAWN, PieceColor.BLACK))
    app.sound_manager.play_hit.assert_called_once()


def test_online_resigner_hears_surrender_not_you_win():
    """The online player who lost by resignation hears the surrender/defeat voice
    only; the winner hears you_win only (never both to one listener)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.mode = ONLINE
    app.match.local_color = PieceColor.BLACK
    app.sound_manager.reset_mock()
    app.current_result = lambda: "white_wins_by_resignation"
    app._trigger_result_effects()
    app.sound_manager.play_surrender.assert_called_once()
    app.sound_manager.play_you_win.assert_not_called()


def test_local_won_local_mode_is_always_true():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    assert app._local_won(PieceColor.WHITE) is True
    assert app._local_won(PieceColor.BLACK) is True


def test_local_won_online_matches_local_color():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    assert app._local_won(PieceColor.WHITE) is True
    assert app._local_won(PieceColor.BLACK) is False


def test_online_mate_loser_plays_you_lose_not_you_win():
    """The online player who is checkmated hears the defeat voice (you_lose), not
    you_win; on a resign the loser hears surrender instead."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.mode = ONLINE
    app.match.local_color = PieceColor.BLACK
    app.sound_manager.reset_mock()
    app.current_result = lambda: "white_wins"
    app._trigger_result_effects()
    app.sound_manager.play_you_win.assert_not_called()
    app.sound_manager.play_you_lose.assert_called_once()
    app.sound_manager.play_surrender.assert_not_called()


def test_online_flag_loser_hears_you_lose():
    app = make_app()
    app._on_start_game(base_config(time_minutes=1))
    app.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    app.match.clock.flagged = PieceColor.WHITE
    app._flag_fall_played = False
    app.sound_manager.reset_mock()
    app._maybe_play_flag_fall()
    app.sound_manager.play_flag_fall.assert_called_once()
    app.sound_manager.play_you_win.assert_not_called()


def test_online_flag_winner_hears_you_win_not_defeat():
    app = make_app()
    app._on_start_game(base_config(time_minutes=1))
    app.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    app.match.clock.flagged = PieceColor.BLACK
    app._flag_fall_played = False
    app.sound_manager.reset_mock()
    app._maybe_play_flag_fall()
    app.sound_manager.play_you_win.assert_called_once()
    app.sound_manager.play_flag_fall.assert_not_called()


def test_single_screen_flag_plays_flag_fall():
    app = make_app()
    app._on_start_game(base_config(time_minutes=1))
    app.match.clock.flagged = PieceColor.WHITE
    app._flag_fall_played = False
    app.sound_manager.reset_mock()
    app._maybe_play_flag_fall()
    app.sound_manager.play_flag_fall.assert_called_once()


def test_manual_flip_plays_flip():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app._on_flip()
    app.sound_manager.play_flip.assert_called_once()


def test_new_toast_plays_toast():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.toast.show("hello")
    app.sound_manager.play_toast.assert_called_once()


def test_keyed_toast_reshow_is_silent():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.toast.show("first", key="k")
    app.sound_manager.reset_mock()
    app.toast.show("updated", key="k")
    app.sound_manager.play_toast.assert_not_called()


def _px(app, sq):
    return app.board.cell_rect(sq).center


def test_click_select_plays_pickup_no_ui_click():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(_px(app, Square(6, 4)))
    app.sound_manager.play_pickup.assert_called_once()
    app.sound_manager.play_ui_click.assert_not_called()


def test_click_empty_square_plays_ui_click():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(_px(app, Square(4, 4)))
    app.sound_manager.play_ui_click.assert_called_once()
    app.sound_manager.play_pickup.assert_not_called()


def test_click_move_target_no_ui_click_plays_move():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.input_router.mouse_left_clicked(_px(app, Square(6, 4)))
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(_px(app, Square(4, 4)))
    app.sound_manager.play_ui_click.assert_not_called()
    fire_animation(app)
    app.sound_manager.play_move.assert_called_once()


def test_click_deselect_plays_ui_click():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.input_router.mouse_left_clicked(_px(app, Square(6, 4)))
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(_px(app, Square(6, 4)))
    app.sound_manager.play_ui_click.assert_called_once()


def test_menu_click_plays_ui_click():
    app = make_app()
    app.mode = "menu"
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked((500, 400))
    app.sound_manager.play_ui_click.assert_called_once()


def test_click_during_promotion_no_ui_click():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.pending_promotion_square = Square(0, 4)
    app.board.pick_promotion_at = lambda pos: None
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(_px(app, Square(0, 4)))
    app.sound_manager.play_ui_click.assert_not_called()


def test_drag_release_plays_drop():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.selected_square = Square(6, 4)
    app.board.dragging_from = Square(6, 4)
    app.sound_manager.reset_mock()
    app.input_router._mouse_left_released(_px(app, Square(4, 4)))
    app.sound_manager.play_drop.assert_called_once()
    app.sound_manager.play_ui_click.assert_not_called()


def test_drag_release_cancel_suppresses_ui_click_still_drops():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.board.selected_square = Square(6, 4)
    app.board.dragging_from = Square(6, 4)
    app.sound_manager.reset_mock()
    app.input_router._mouse_left_released(_px(app, Square(6, 4)))
    app.sound_manager.play_ui_click.assert_not_called()
    app.sound_manager.play_drop.assert_called_once()


def test_non_drag_release_does_not_drop():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    app.input_router._mouse_left_released(_px(app, Square(4, 4)))
    app.sound_manager.play_drop.assert_not_called()


def test_premove_making_and_chaining_is_silent():
    """Premoves are speculative — making/chaining/clearing them plays neither the
    typewriter nor the pickup (disturbing during rapid premove setup)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.input_router.mouse_left_clicked(_px(app, Square(6, 4)))
    app.input_router.mouse_left_clicked(_px(app, Square(4, 4)))
    app.board.cancel_animations()
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(_px(app, Square(7, 6)))   # premove-select knight g1
    app.input_router.mouse_left_clicked(_px(app, Square(5, 5)))   # premove-queue g1-f3
    app.input_router.mouse_left_clicked(_px(app, Square(5, 5)))   # chain-select f3
    app.input_router.mouse_left_clicked(_px(app, Square(3, 4)))   # chain-queue f3-e5
    app.input_router.mouse_left_clicked(_px(app, Square(3, 0)))   # empty click clears premoves
    app.sound_manager.play_ui_click.assert_not_called()
    app.sound_manager.play_pickup.assert_not_called()


def test_illegal_premove_target_plays_ui_click():
    """A premove onto a square the piece can't reach is an invalid attempt — that
    one plays the typewriter (legal premoves stay silent)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.input_router.mouse_left_clicked(_px(app, Square(6, 4)))
    app.input_router.mouse_left_clicked(_px(app, Square(4, 4)))
    app.board.cancel_animations()
    app.sound_manager.reset_mock()
    # premove-select knight g1 (silent)
    app.input_router.mouse_left_clicked(_px(app, Square(7, 6)))
    # illegal target e4 -> typewriter
    app.input_router.mouse_left_clicked(_px(app, Square(4, 4)))
    app.sound_manager.play_ui_click.assert_called_once()


def test_click_opponent_piece_online_plays_ui_click():
    """Clicking an opponent's piece in an online game selects nothing; that no-op
    must still play the typewriter click, not be mistaken for a real premove-select
    and silenced (_premove_select propagates the failed selection as None)."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.match.local_color = PieceColor.WHITE
    app.sound_manager.reset_mock()
    # black pawn e7 (opponent, no chain)
    app.input_router.mouse_left_clicked(_px(app, Square(1, 4)))
    assert app.board.selected_square is None
    app.sound_manager.play_ui_click.assert_called_once()


def test_right_click_press_plays_ui_click():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN,
                                 {"button": 3, "pos": _px(app, Square(4, 4))}))
    app.input_router.check_events()
    app.sound_manager.play_ui_click.assert_called_once()


def test_right_click_in_menu_plays_ui_click():
    app = make_app()
    app.mode = "menu"
    app.sound_manager.reset_mock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 3, "pos": (500, 400)}))
    app.input_router.check_events()
    app.sound_manager.play_ui_click.assert_called_once()


def test_any_keyboard_press_plays_ui_click():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_a, "mod": 0, "unicode": "a"}))
    app.input_router.check_events()
    app.sound_manager.play_ui_click.assert_called_once()


def test_keyboard_during_skillcheck_is_silent():
    """While a skill-check swallows input it owns its own audio (tick/beep/verdict);
    a keydown must not layer the universal typewriter click over it — matching the
    mouse path, which is already silent during a check. The event still reaches the
    overlay."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.skillcheck_session._skillcheck_swallows_input = lambda: True
    app.skillcheck_overlay.handle_event = MagicMock()
    app.sound_manager.reset_mock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_SPACE, "mod": 0, "unicode": " "}))
    app.input_router.check_events()
    app.sound_manager.play_ui_click.assert_not_called()
    app.skillcheck_overlay.handle_event.assert_called_once()


def test_keyboard_flip_plays_click_and_flip():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    app.sound_manager.reset_mock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_f, "mod": 0, "unicode": "f"}))
    app.input_router.check_events()
    app.sound_manager.play_ui_click.assert_called_once()
    app.sound_manager.play_flip.assert_called_once()
