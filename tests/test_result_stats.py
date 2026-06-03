"""Result-modal stat derivations over move history: KO counts, the same-side
capture streak (resets on a non-capture or opponent recapture), checks, moves,
material, clock-left, and the PLAY OF THE GAME pick."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square, Move, HistoryEntry
from frontend.panels.result_stats import compute_result_stats, _best_streak

W, B = PieceColor.WHITE, PieceColor.BLACK


def _entry(color, san, captured_type=None, gives_check=False, gives_checkmate=False):
    captured = Piece(captured_type, B if color == W else W) if captured_type else None
    move = Move(Square(6, 4), Square(4, 4), Piece(PieceType.PAWN, color),
                captured=captured)
    return HistoryEntry(move=move, prev_castling_rights=(), prev_en_passant_target=None,
                        prev_halfmove_clock=0, position_key_added=("k",), san=san,
                        gives_check=gives_check, gives_checkmate=gives_checkmate)


class _Clock:
    def remaining(self, color):
        return 242.0 if color == W else 100.0


def test_ko_counts_per_side():
    history = [
        _entry(W, "exd5", PieceType.PAWN),
        _entry(B, "Nxe4", PieceType.KNIGHT),
        _entry(W, "Qxe4", PieceType.QUEEN),
    ]
    stats = compute_result_stats(history, None, W)
    assert stats["kos"] == (2, 1)


def test_streak_counts_consecutive_same_side_captures():
    history = [
        _entry(W, "xa", PieceType.PAWN),
        _entry(W, "xb", PieceType.PAWN),
        _entry(W, "xc", PieceType.PAWN),
    ]
    assert _best_streak(history)[0] == 3
    assert compute_result_stats(history, None, W)["streak"] == 3


def test_streak_resets_on_non_capture():
    history = [
        _entry(W, "xa", PieceType.PAWN),
        _entry(W, "Nf3"),
        _entry(W, "xb", PieceType.PAWN),
    ]
    assert _best_streak(history)[0] == 1


def test_streak_resets_on_opponent_recapture():
    history = [
        _entry(W, "xa", PieceType.PAWN),
        _entry(W, "xb", PieceType.PAWN),
        _entry(B, "xc", PieceType.PAWN),
    ]
    best_len, best_start = _best_streak(history)
    assert best_len == 2 and best_start == 0


def test_checks_and_moves():
    history = [
        _entry(W, "e4"),
        _entry(B, "e5"),
        _entry(W, "Qh5+", gives_check=True),
        _entry(B, "Nc6"),
        _entry(W, "Qxf7#", PieceType.PAWN, gives_checkmate=True),
    ]
    stats = compute_result_stats(history, None, W)
    assert stats["checks"] == 2
    assert stats["moves"] == 3


def test_material_and_clock_left():
    history = [_entry(W, "Qxd8", PieceType.QUEEN)]
    stats = compute_result_stats(history, _Clock(), W)
    assert stats["material"] == 9
    assert stats["clock_left"] == 242.0


def test_clock_left_none_when_untimed():
    stats = compute_result_stats([_entry(W, "e4")], None, W)
    assert stats["clock_left"] is None


def test_play_of_the_game_picks_streak_start():
    history = [
        _entry(W, "Nf3"),
        _entry(W, "Bxf7", PieceType.PAWN),
        _entry(W, "Bxg8", PieceType.KNIGHT),
    ]
    potg = compute_result_stats(history, None, W)["play_of_the_game"]
    assert "Bxf7" in potg and "2-KO" in potg


def test_play_of_the_game_none_without_captures():
    history = [_entry(W, "e4"), _entry(B, "e5")]
    assert compute_result_stats(history, None, W)["play_of_the_game"] is None
