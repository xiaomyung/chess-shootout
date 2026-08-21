from collections import Counter

import pytest

from chessshootout.backend.backend import Backend
from chessshootout.backend.fen import export_fen, apply_fen
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square


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


@pytest.mark.parametrize(
    "loaded",
    [
        pytest.param(
            "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
            id="black_to_move_move_2",
        ),
        pytest.param(
            "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
            id="white_to_move_move_4",
        ),
        pytest.param(
            "8/8/4k3/8/8/4K3/8/8 b - - 12 47",
            id="black_to_move_deep_endgame",
        ),
    ],
)
def test_apply_fen_mid_game_round_trips_including_fullmove(loaded):
    """apply_fen clears the move history, so the fullmove number can only survive
    a round trip if the engine keeps the loaded number as a baseline -- exporting
    from len(move_history) alone would reset every loaded position to move 1."""
    backend = Backend()
    apply_fen(backend, loaded)
    assert export_fen(backend) == loaded


@pytest.mark.parametrize(
    "loaded, moves, expected_fullmoves",
    [
        pytest.param(
            "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 3 3",
            [(Square(0, 6), Square(2, 5)), (Square(7, 5), Square(4, 2))],
            [4, 4],
            id="black_to_move_advances_on_black_ply",
        ),
        pytest.param(
            "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 4 4",
            [(Square(7, 5), Square(4, 2)), (Square(0, 6), Square(2, 5))],
            [4, 5],
            id="white_to_move_advances_on_black_ply",
        ),
    ],
)
def test_fullmove_advances_from_a_loaded_position(loaded, moves, expected_fullmoves):
    """The move number climbs once per completed move-pair counted from the side
    that was to move at load, so a position loaded with Black to move reaches the
    next number one ply sooner than one loaded with White to move."""
    backend = Backend()
    apply_fen(backend, loaded)
    seen = []
    for from_sq, to_sq in moves:
        assert backend.try_move(from_sq, to_sq).legal
        seen.append(int(export_fen(backend).split()[5]))
    assert seen == expected_fullmoves


def test_fullmove_returns_to_the_loaded_number_after_undo():
    """Undo walks the move number back down the same baseline it climbed, so a
    browse-and-take-back cycle cannot leave the exported FEN a move ahead."""
    loaded = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 3 3"
    backend = Backend()
    apply_fen(backend, loaded)
    assert backend.try_move(Square(0, 6), Square(2, 5)).legal
    assert export_fen(backend).split()[5] == "4"
    backend.undo()
    assert export_fen(backend) == loaded


def test_new_game_resets_the_fullmove_baseline_of_a_loaded_engine():
    """A rematch reuses the same Backend object, so new_game() must clear the
    baseline a previously loaded FEN left behind or the fresh game would start
    numbering at the old position's move number."""
    backend = Backend()
    apply_fen(backend, "8/8/4k3/8/8/4K3/8/8 b - - 12 47")
    backend.new_game()
    assert export_fen(backend) == INITIAL_FEN


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


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("W", id="uppercase_white"),
        pytest.param("B", id="uppercase_black"),
        pytest.param("white", id="spelled_out_side"),
        pytest.param("x", id="junk_letter"),
        pytest.param("-", id="dash"),
    ],
)
def test_apply_fen_rejects_a_side_to_move_that_is_not_w_or_b(token):
    """Every other FEN field raises on junk; the side to move used to fall through
    to Black, so a mistyped token silently handed the move to the wrong player."""
    backend = Backend()
    backend.new_game()
    fen = f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR {token} KQkq - 0 1"
    with pytest.raises(ValueError):
        apply_fen(backend, fen)


@pytest.mark.parametrize(
    "token, expected",
    [
        pytest.param("w", PieceColor.WHITE, id="white_to_move"),
        pytest.param("b", PieceColor.BLACK, id="black_to_move"),
    ],
)
def test_apply_fen_accepts_both_legal_side_tokens(token, expected):
    """The tightened validation must still let the two spellings the FEN standard
    defines straight through."""
    backend = Backend()
    fen = f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR {token} KQkq - 0 1"
    apply_fen(backend, fen)
    assert backend.turn == expected


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
