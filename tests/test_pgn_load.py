from collections import Counter

import pytest

from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.domain.pgn.generate import generate_pgn
from chessshootout.domain.pgn.load import (
    PgnSummary, extract_csmatchid, format_relative_time, group_by_csmatchid,
    load_pgn_into_backend, parse_comment, parse_pgn, scan_pgn_summaries,
    summarize_pgn_file, termination_reason, time_category,
)
from tests.helpers import fake_uuid4


def _summary(path, match_id=None, result="1-0", type_="Local"):
    return PgnSummary(
        path=path, time="t", type=type_, time_control="5+2",
        white="alice", black="bob", result_code=result, sort_key=1.0,
        match_id=match_id,
    )


def _round_trip(backend, result_code="*"):
    text = generate_pgn(backend.move_history, result_code)
    parsed = parse_pgn(text)
    fresh = Backend()
    fresh.new_game()
    for san in parsed.moves:
        res = fresh.apply_san(san)
        assert res.legal, f"replay failed at {san}"
    return fresh, parsed


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


@pytest.mark.parametrize(
    "text, expected_moves, expected_result",
    [
        pytest.param(
            '[White "A"]\n[Black "B"]\n\n1. e4 {good move} e5 1-0',
            ["e4", "e5"], "1-0", id="strips_brace_comments",
        ),
        pytest.param(
            '[White "A"]\n[Black "B"]\n\n1. e4 (1. d4 d5) e5 *',
            ["e4", "e5"], "*", id="strips_paren_variations",
        ),
        pytest.param(
            '[White "A"]\n\n1. e4 e5 2. Nf3 Nc6 *',
            ["e4", "e5", "Nf3", "Nc6"], "*", id="handles_dotted_move_numbers",
        ),
    ],
)
def test_parse_pgn_extracts_moves_and_result(text, expected_moves, expected_result):
    parsed = parse_pgn(text)
    assert parsed.moves == expected_moves
    assert parsed.result == expected_result


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("1-0", id="white_win"),
        pytest.param("0-1", id="black_win"),
        pytest.param("1/2-1/2", id="draw"),
        pytest.param("*", id="ongoing"),
    ],
)
def test_parse_pgn_recognizes_result_code(code):
    parsed = parse_pgn('[White "A"]\n\n1. e4 e5 ' + code)
    assert parsed.result == code


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


@pytest.mark.parametrize(
    "san, expected_type",
    [
        pytest.param("a8=Q", PieceType.QUEEN, id="default_queen"),
        pytest.param("a8=N", PieceType.KNIGHT, id="underpromote_knight"),
    ],
)
def test_apply_san_promotion_lands_chosen_piece(san, expected_type):
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res = backend.apply_san(san)
    assert res.legal
    assert backend.state[0][0].type == expected_type


def test_apply_san_strips_check_suffix():
    """A '+'-suffixed SAN is matched, lands a real check, and re-stamps the '+'."""
    backend = Backend()
    backend.new_game()
    for san in ["e4", "e5", "Bc4", "Nc6", "Qh5", "g6"]:
        assert backend.apply_san(san).legal
    res = backend.apply_san("Qxe5+")
    assert res.legal
    assert backend.is_in_check(PieceColor.BLACK)
    assert backend.move_history[-1].san == "Qxe5+"


def test_apply_san_strips_mate_suffix():
    """Fool's mate: '#'-suffixed Qh4# is matched, wins for black, re-stamps '#'."""
    backend = Backend()
    backend.new_game()
    for san in ["f3", "e5", "g4"]:
        assert backend.apply_san(san).legal
    res = backend.apply_san("Qh4#")
    assert res.legal
    assert backend.game_result() == "black_wins"
    assert backend.move_history[-1].san == "Qh4#"


def test_apply_san_disambiguation_by_file():
    backend = Backend()
    backend.state = [[None] * 8 for _ in range(8)]
    backend.state[6][3] = Piece(PieceType.KNIGHT, PieceColor.WHITE)
    backend.state[6][5] = Piece(PieceType.KNIGHT, PieceColor.WHITE)
    backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.BLACK)
    backend.turn = PieceColor.WHITE
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1
    res = backend.apply_san("Ndxe4")
    assert res.legal
    assert backend.state[4][4] is not None
    assert backend.state[4][4].type == PieceType.KNIGHT
    assert backend.state[6][3] is None
    assert backend.state[6][5] is not None


@pytest.mark.parametrize(
    "san",
    [
        pytest.param("nonsense", id="garbage_token"),
        pytest.param("", id="empty_string"),
    ],
)
def test_apply_san_invalid_returns_illegal(san):
    backend = Backend()
    backend.new_game()
    res = backend.apply_san(san)
    assert not res.legal


def test_round_trip_simple_game():
    backend = Backend()
    backend.new_game()
    for from_sq, to_sq in [
        (Square(6, 4), Square(4, 4)),
        (Square(1, 4), Square(3, 4)),
        (Square(7, 6), Square(5, 5)),
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
    sans = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"]
    for s in sans:
        assert backend.apply_san(s).legal, f"setup failed at {s}"
    fresh, _ = _round_trip(backend)
    assert fresh.state[7][6].type == PieceType.KING
    assert fresh.state[7][5].type == PieceType.ROOK


def test_round_trip_capture_and_check():
    backend = Backend()
    backend.new_game()
    sans = ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    for s in sans:
        assert backend.apply_san(s).legal
    fresh, _ = _round_trip(backend, result_code="white_wins")
    assert len(fresh.move_history) == len(sans)


def test_round_trip_disambiguation_from_initial():
    backend = Backend()
    backend.new_game()
    sans = ["Nf3", "Nf6", "Nc3", "Nc6", "Nd5"]
    for s in sans:
        assert backend.apply_san(s).legal
    fresh, _ = _round_trip(backend)
    assert len(fresh.move_history) == len(sans)


def test_round_trip_promotion_from_initial():
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
    text = '[White "A"]\n\n1. e4 e9 *'
    _, ok = load_pgn_into_backend(fresh, text)
    assert not ok


def test_extract_csmatchid_valid():
    mid = fake_uuid4(42)
    assert extract_csmatchid({"CSMatchId": mid}) == mid


@pytest.mark.parametrize("headers", [
    pytest.param({}, id="missing"),
    pytest.param({"CSMatchId": ""}, id="empty"),
    pytest.param({"CSMatchId": "not-a-uuid"}, id="garbage"),
    pytest.param({"CSMatchId": "12345678-1234-1234-1234-123456789abc"}, id="not_v4"),
])
def test_extract_csmatchid_rejects_non_uuid4(headers):
    assert extract_csmatchid(headers) is None


def test_group_by_csmatchid_merges_shared_id():
    mid = fake_uuid4(1)
    summaries = [_summary("a", mid), _summary("b", fake_uuid4(2)), _summary("c", mid)]
    groups = group_by_csmatchid(summaries)
    assert len(groups) == 2
    shared = next(games for gid, games in groups if gid == mid)
    assert [s.path for s in shared] == ["a", "c"]


def test_group_by_csmatchid_legacy_each_solo():
    groups = group_by_csmatchid([_summary("a", None), _summary("b", None)])
    assert len(groups) == 2
    assert all(gid is None for gid, _ in groups)


def test_group_by_csmatchid_preserves_first_appearance_order():
    mid = fake_uuid4(3)
    groups = group_by_csmatchid([_summary("a", None), _summary("b", mid), _summary("c", mid)])
    assert [gid for gid, _ in groups] == [None, mid]


def test_scan_pgn_summaries_sorts_newest_first(tmp_path):
    (tmp_path / "local-20260101-100000.pgn").write_text('[White "a"]\n\n1. e4 *', encoding="utf-8")
    (tmp_path / "local-20260101-200000.pgn").write_text('[White "b"]\n\n1. d4 *', encoding="utf-8")
    summaries = scan_pgn_summaries(str(tmp_path), "*.pgn")
    assert [s.white for s in summaries] == ["b", "a"]


def test_scan_pgn_summaries_excludes_non_pgn(tmp_path):
    (tmp_path / "local-20260101-100000.pgn").write_text('[White "a"]\n\n1. e4 *', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a game", encoding="utf-8")
    assert len(scan_pgn_summaries(str(tmp_path), "*.pgn")) == 1


def test_scan_pgn_summaries_includes_glyph_and_nonascii_pgn(tmp_path):
    """A skill-check online PGN carries {Wheel ✓} glyphs and may have a non-ASCII
    nickname. The scan open at :314 declares encoding='utf-8'; on Windows a bare read
    hit UnicodeDecodeError, got swallowed, and the game silently vanished from History."""
    (tmp_path / "online-20260101-100000.pgn").write_text(
        '[White "Щ"]\n[Black "b"]\n\n1. e4 e5 {Wheel ✓} *\n', encoding="utf-8")
    summaries = scan_pgn_summaries(str(tmp_path), "*.pgn")
    assert len(summaries) == 1
    assert summaries[0].white == "Щ"


def test_summarize_counts_captures_per_color():
    text = generate_pgn(_played_capture_game().move_history, "white_wins")
    summary = summarize_pgn_file("/games/local-20260101-000000.pgn", text, 1.0)
    assert summary.white_captures == 1
    assert summary.black_captures == 1


def _played_capture_game():
    fresh = Backend()
    fresh.new_game()
    for san in ["e4", "d5", "exd5", "Qxd5"]:
        assert fresh.apply_san(san).legal
    return fresh


@pytest.mark.parametrize("code,termination,last_san,expected", [
    pytest.param("1-0", None, "Qxf7#", "Checkmate", id="checkmate"),
    pytest.param("0-1", "Time forfeit", "Kg1", "Flagged", id="flagged"),
    pytest.param("1-0", None, "Rd8", "Resigned", id="resigned"),
    pytest.param("1/2-1/2", None, "Kf1", "Draw", id="draw"),
    pytest.param("*", None, "", "Unfinished", id="unfinished"),
])
def test_termination_reason(code, termination, last_san, expected):
    assert termination_reason(code, termination, last_san) == expected


@pytest.mark.parametrize("tc,expected", [
    pytest.param("1+0", "Bullet", id="bullet"),
    pytest.param("3+2", "Blitz", id="blitz_3"),
    pytest.param("5+0", "Blitz", id="blitz_5"),
    pytest.param("10+5", "Rapid", id="rapid"),
    pytest.param("No clock", "Casual", id="no_clock"),
])
def test_time_category(tc, expected):
    assert time_category(tc) == expected


@pytest.mark.parametrize("delta,expected", [
    pytest.param(30, "just now", id="just_now"),
    pytest.param(120, "2m ago", id="minutes"),
    pytest.param(7200, "2h ago", id="hours"),
    pytest.param(90000, "Yesterday", id="yesterday"),
])
def test_format_relative_time(delta, expected):
    now = 1_700_000_000.0
    assert format_relative_time(now - delta, now) == expected


def test_parse_pgn_preserves_move_comments_aligned_to_moves():
    text = ('[White "A"]\n[Black "B"]\n\n'
            "1. e4 {Wheel ✓} e5 2. Nf3 {Wheel ✗ Rxe5 · Steady-Aim ✓} Nc6 3. Bb5 1-0")
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5", "Nf3", "Nc6", "Bb5"]
    assert parsed.move_comments == [
        "Wheel ✓", "", "Wheel ✗ Rxe5 · Steady-Aim ✓", "", ""]
    assert parsed.result == "1-0"


def test_parse_pgn_no_comments_yields_all_empty_aligned():
    parsed = parse_pgn('[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 1-0')
    assert parsed.moves == ["e4", "e5", "Nf3"]
    assert parsed.move_comments == ["", "", ""]


def test_multiword_comment_does_not_leak_into_moves_or_captures():
    text = '[White "A"]\n[Black "B"]\n\n1. d4 {Wheel ✗ Rxe5} d5 *'
    parsed = parse_pgn(text)
    assert parsed.moves == ["d4", "d5"]
    summary = summarize_pgn_file("local-x.pgn", text, 0.0, filename="local-x.pgn")
    assert summary.white_captures == 0
    assert summary.black_captures == 0


def test_parse_pgn_strips_variations_but_keeps_real_comments():
    text = '[White "A"]\n\n1. e4 {kept} (1. d4 {dropped} d5) e5 *'
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5"]
    assert parsed.move_comments == ["kept", ""]


def test_parse_comment_round_trips_format_annotations():
    assert parse_comment("Wheel ✓") == [("wheel", True, "")]
    assert parse_comment("Steady-Aim ✗ Nxe5") == [("aim", False, "Nxe5")]
    assert parse_comment("Wheel ✗ Rxe5 · Steady-Aim ✓") == [
        ("wheel", False, "Rxe5"), ("aim", True, "")]


def test_parse_comment_ignores_free_text():
    assert parse_comment("good move") == []
    assert parse_comment("") == []


def test_whiffed_san_lives_in_a_comment_and_keeps_the_pgn_legal():
    """The "stays legal in chess.com/lichess" guarantee: a check that FAILED writes its whiffed
    SAN into the ply's {comment} — the move that actually landed (Nc6) stays in the sequence.
    The whiffed SAN (Nxe5) must be in move_comments but absent from the move list, and the whole
    movetext must still replay legally as a standard game."""
    backend = Backend()
    backend.new_game()
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        assert backend.apply_san(san).legal
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations={4: "Steady-Aim ✗ Nxe5"})
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5", "Nf3", "Nc6"]
    assert "Nxe5" not in parsed.moves, "the whiffed move never landed in the move sequence"
    assert any("Nxe5" in comment for comment in parsed.move_comments), \
        "but the whiffed SAN is preserved in the ply comment"
    fresh = Backend()
    reparsed, ok = load_pgn_into_backend(fresh, text)
    assert ok is True, "a whiff-annotated PGN replays cleanly as standard chess"
    assert [e.san for e in fresh.move_history] == ["e4", "e5", "Nf3", "Nc6"]
