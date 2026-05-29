from collections import Counter

import pytest

from backend.backend import Backend
from backend.fen import export_fen, apply_fen
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square


INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.mark.parametrize(
    "moves, expected",
    [
        pytest.param(
            [],
            INITIAL_FEN,
            id="initial_position",
        ),
        pytest.param(
            [(Square(6, 4), Square(4, 4))],
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            id="after_e4_sets_ep_target",
        ),
        pytest.param(
            [(Square(6, 4), Square(4, 4)), (Square(1, 4), Square(3, 4))],
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
            id="after_e4_e5_fullmove_advances",
        ),
        pytest.param(
            [
                (Square(6, 4), Square(4, 4)),
                (Square(1, 3), Square(3, 3)),
                (Square(4, 4), Square(3, 3)),
            ],
            "rnbqkbnr/ppp1pppp/8/3P4/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2",
            id="exd5_capture_resets_halfmove_clock",
        ),
    ],
)
def test_export_after_moves(moves, expected):
    backend = Backend()
    backend.new_game()
    for from_sq, to_sq in moves:
        backend.try_move(from_sq, to_sq)
    assert export_fen(backend) == expected


def test_export_castling_rights_drop_after_king_move():
    """King move clears that side's rights only; opponent's survive."""
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.ROOK, PieceColor.WHITE)
    backend.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    rights_before = export_fen(backend).split()[2]
    assert "K" in rights_before
    backend.try_move(Square(7, 4), Square(7, 5))
    rights_after = export_fen(backend).split()[2]
    assert "K" not in rights_after
    assert "Q" not in rights_after
    assert "k" in rights_after
    assert "q" in rights_after


def test_apply_fen_initial_round_trips():
    backend = Backend()
    apply_fen(backend, INITIAL_FEN)
    assert export_fen(backend) == INITIAL_FEN


def test_apply_fen_mid_game_round_trips_except_fullmove():
    """apply_fen clears history, so exported fullmove resets to 1; position fields match."""
    loaded = "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    backend = Backend()
    apply_fen(backend, loaded)
    re_exported = export_fen(backend)
    assert re_exported.split()[:5] == loaded.split()[:5]


def test_apply_fen_clears_move_history():
    backend = Backend()
    backend.new_game()
    backend.try_move(Square(6, 4), Square(4, 4))
    assert len(backend.move_history) == 1
    apply_fen(backend, INITIAL_FEN)
    assert backend.move_history == []


def test_apply_fen_initializes_position_counts_with_one_entry():
    backend = Backend()
    apply_fen(backend, INITIAL_FEN)
    assert sum(backend.position_counts.values()) == 1


def test_apply_fen_recovers_en_passant_target():
    fen_with_ep = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    backend = Backend()
    apply_fen(backend, fen_with_ep)
    assert backend.en_passant_target == Square(5, 4)


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param(
            "-",
            {"WK": False, "WQ": False, "BK": False, "BQ": False},
            id="no_castling_rights",
        ),
        pytest.param(
            "q",
            {"WK": False, "WQ": False, "BK": False, "BQ": True},
            id="black_queenside_only",
        ),
        pytest.param(
            "KQkq",
            {"WK": True, "WQ": True, "BK": True, "BQ": True},
            id="all_four_rights",
        ),
    ],
)
def test_apply_fen_parses_castling_rights(field, expected):
    fen = f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w {field} - 0 1"
    backend = Backend()
    apply_fen(backend, fen)
    assert backend.castling_rights == expected


def test_apply_fen_invalid_raises():
    backend = Backend()
    with pytest.raises(ValueError):
        apply_fen(backend, "garbage")


def test_apply_fen_minimal_4_field_form():
    """FEN spec allows omitting halfmove + fullmove; halfmove defaults to 0."""
    fen = "8/8/8/8/8/8/8/4K2k w - -"
    backend = Backend()
    apply_fen(backend, fen)
    assert backend.halfmove_clock == 0


def test_round_trip_preserves_active_side():
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b - - 5 10"
    backend = Backend()
    apply_fen(backend, fen)
    assert backend.turn == PieceColor.BLACK
