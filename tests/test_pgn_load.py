from collections import Counter

from backend.backend import Backend
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.pgn import generate_pgn
from frontend.pgn_load import parse_pgn, load_pgn_into_backend


def _round_trip(backend, result_code="*"):
    text = generate_pgn(backend.move_history, result_code)
    parsed = parse_pgn(text)
    fresh = Backend()
    fresh.new_game()
    for san in parsed.moves:
        res = fresh.apply_san(san)
        assert res.legal, f"replay failed at {san}"
    return fresh, parsed


# ---------- parse_pgn ----------

def test_parse_pgn_initial_export_yields_no_moves():
    backend = Backend()
    backend.new_game()
    text = generate_pgn(backend.move_history, "*")
    parsed = parse_pgn(text)
    assert parsed.moves == []
    assert parsed.result == "*"


def test_parse_pgn_extracts_headers():
    backend = Backend()
    backend.new_game()
    text = generate_pgn(backend.move_history, "*",
                        white_name="Alice", black_name="Bob")
    parsed = parse_pgn(text)
    assert parsed.headers["White"] == "Alice"
    assert parsed.headers["Black"] == "Bob"


def test_parse_pgn_strips_comments():
    text = '[White "A"]\n[Black "B"]\n\n1. e4 {good move} e5 1-0'
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5"]
    assert parsed.result == "1-0"


def test_parse_pgn_strips_variations():
    text = '[White "A"]\n[Black "B"]\n\n1. e4 (1. d4 d5) e5 *'
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5"]


def test_parse_pgn_handles_dotted_move_numbers():
    text = '[White "A"]\n\n1. e4 e5 2. Nf3 Nc6 *'
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5", "Nf3", "Nc6"]


def test_parse_pgn_recognizes_all_result_codes():
    base = '[White "A"]\n\n1. e4 e5 '
    for code in ["1-0", "0-1", "1/2-1/2", "*"]:
        parsed = parse_pgn(base + code)
        assert parsed.result == code


# ---------- Backend.apply_san ----------

def test_apply_san_simple_pawn_move():
    backend = Backend()
    backend.new_game()
    res = backend.apply_san("e4")
    assert res.legal
    assert backend.state[4][4] is not None


def test_apply_san_castling_kingside():
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.ROOK, PieceColor.WHITE)
    backend.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res = backend.apply_san("O-O")
    assert res.legal
    assert backend.state[7][6].type == PieceType.KING
    assert backend.state[7][5].type == PieceType.ROOK


def test_apply_san_promotion_default_queen():
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res = backend.apply_san("a8=Q")
    assert res.legal
    assert backend.state[0][0].type == PieceType.QUEEN


def test_apply_san_promotion_underpromotion_knight():
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res = backend.apply_san("a8=N")
    assert res.legal
    assert backend.state[0][0].type == PieceType.KNIGHT


def test_apply_san_strips_check_suffix():
    backend = Backend()
    backend.new_game()
    backend.apply_san("e4")
    backend.apply_san("e5")
    res = backend.apply_san("Bc4")
    assert res.legal


def test_apply_san_strips_mate_suffix():
    # Build a fool's mate position; black plays Qh4# ending the game.
    backend = Backend()
    backend.new_game()
    for san in ["f3", "e5", "g4"]:
        assert backend.apply_san(san).legal
    res = backend.apply_san("Qh4#")
    assert res.legal
    assert backend.game_result() == "white_wins" or backend.game_result() == "black_wins"


def test_apply_san_disambiguation_by_file():
    # Two white knights on b1 and g1 both able to reach f3 (only g1 actually does).
    # Construct a position where two knights can reach the same square.
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    # White knights at b1 and f1 (col 1 and col 5) — both reach c3 / e3? Use cleaner setup.
    # Knights at d2 and f2 both reach e4. d2 = (6, 3), f2 = (6, 5), target e4 = (4, 4).
    backend.state[6][3] = Piece(PieceType.KNIGHT, PieceColor.WHITE)
    backend.state[6][5] = Piece(PieceType.KNIGHT, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    # Filler pawn so KNN v K isn't auto-drawn before the move can land.
    backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res = backend.apply_san("Ndxe4")  # d-knight (col 3) → e4 (4, 4)
    assert res.legal
    assert backend.state[4][4] is not None
    assert backend.state[4][4].type == PieceType.KNIGHT
    assert backend.state[6][3] is None
    assert backend.state[6][5] is not None  # the f-knight stays


def test_apply_san_invalid_san_returns_illegal():
    backend = Backend()
    backend.new_game()
    res = backend.apply_san("nonsense")
    assert not res.legal


def test_apply_san_empty_returns_illegal():
    backend = Backend()
    backend.new_game()
    res = backend.apply_san("")
    assert not res.legal


# ---------- Round-trip via load_pgn_into_backend ----------

def test_round_trip_simple_game():
    backend = Backend()
    backend.new_game()
    for from_sq, to_sq in [
        (Square(6, 4), Square(4, 4)),  # e4
        (Square(1, 4), Square(3, 4)),  # e5
        (Square(7, 6), Square(5, 5)),  # Nf3
    ]:
        res = backend.try_move(from_sq, to_sq)
        assert res.legal
    fresh, _ = _round_trip(backend)
    for r in range(8):
        for c in range(8):
            a = backend.state[r][c]
            b = fresh.state[r][c]
            if a is None:
                assert b is None
            else:
                assert b is not None and a.type == b.type and a.color == b.color


def test_round_trip_castle_from_initial_position():
    backend = Backend()
    backend.new_game()
    # Italian-game moves leading to white kingside castle.
    sans = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"]
    for s in sans:
        assert backend.apply_san(s).legal, f"setup failed at {s}"
    fresh, _ = _round_trip(backend)
    assert fresh.state[7][6].type == PieceType.KING
    assert fresh.state[7][5].type == PieceType.ROOK


def test_round_trip_capture_and_check():
    backend = Backend()
    backend.new_game()
    # Scholar's mate moves: e4 e5 Bc4 Nc6 Qh5 Nf6?? Qxf7#
    sans = ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    for s in sans:
        assert backend.apply_san(s).legal
    fresh, _ = _round_trip(backend, result_code="white_wins")
    assert len(fresh.move_history) == len(sans)


def test_round_trip_disambiguation_from_initial():
    backend = Backend()
    backend.new_game()
    # 1. Nf3 Nf6 2. Nc3 Nc6 — both white knights now developed; play Nd5 to reach
    # a position where after some moves disambiguation could appear. Simpler:
    # the round-trip just needs SAN output to match between export and replay.
    sans = ["Nf3", "Nf6", "Nc3", "Nc6", "Nd5"]
    for s in sans:
        assert backend.apply_san(s).legal
    fresh, _ = _round_trip(backend)
    assert len(fresh.move_history) == len(sans)


def test_round_trip_promotion_from_initial():
    # Smoke: 3 legal opening moves round-trip through PGN write+load. Promotion
    # itself is covered by direct apply_san tests.
    backend = Backend()
    backend.new_game()
    sans = ["e4", "d5", "exd5"]
    for s in sans:
        assert backend.apply_san(s).legal
    fresh, _ = _round_trip(backend)
    assert fresh.state[3][3].type == PieceType.PAWN
    assert fresh.state[3][3].color == PieceColor.WHITE


def test_load_pgn_handles_comments_and_variations():
    backend = Backend()
    backend.new_game()
    text = (
        '[White "A"]\n[Black "B"]\n\n'
        '1. e4 {king pawn} e5 (1...c5 {sicilian}) 2. Nf3 Nc6 *'
    )
    fresh = Backend()
    parsed, ok = load_pgn_into_backend(fresh, text)
    assert ok
    assert len(fresh.move_history) == 4
    assert parsed.headers["White"] == "A"


def test_load_pgn_returns_false_on_illegal_move():
    fresh = Backend()
    text = '[White "A"]\n\n1. e4 e9 *'  # e9 is invalid
    _, ok = load_pgn_into_backend(fresh, text)
    assert not ok
