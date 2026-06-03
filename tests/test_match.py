import pytest

from chessshootout.domain.match import Match, SINGLE_SCREEN, BOT, ONLINE
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import Square


@pytest.mark.parametrize(
    "kwargs, expected_mode, expected_color",
    [
        pytest.param({}, SINGLE_SCREEN, None, id="default_single_screen_no_color"),
        pytest.param(
            {"mode": ONLINE, "local_color": PieceColor.WHITE},
            ONLINE,
            PieceColor.WHITE,
            id="online_white_local_color",
        ),
        pytest.param(
            {"mode": BOT, "local_color": PieceColor.BLACK},
            BOT,
            PieceColor.BLACK,
            id="bot_black_local_color",
        ),
    ],
)
def test_match_construction_sets_mode_and_local_color(kwargs, expected_mode, expected_color):
    m = Match(**kwargs)
    assert m.mode == expected_mode
    assert m.local_color == expected_color


def test_match_starts_with_initial_position():
    m = Match()
    assert m.move_history == []
    assert m.current_turn() == PieceColor.WHITE


def test_match_try_move_delegates():
    m = Match()
    res = m.try_move(Square(6, 4), Square(4, 4))
    assert res.legal
    assert len(m.move_history) == 1


def test_match_undo_delegates():
    m = Match()
    m.try_move(Square(6, 4), Square(4, 4))
    m.undo()
    assert m.move_history == []


def test_match_state_is_backend_state():
    """state is a live view of backend.state, not a copy made at init."""
    m = Match()
    assert m.state is m.backend.state
    sentinel = Piece(PieceType.QUEEN, PieceColor.BLACK)
    m.backend.state[4][4] = sentinel
    assert m.state[4][4] is sentinel


def test_match_clock_property():
    m = Match()
    assert m.clock is None
    m.setup_clock(60, 0)
    assert m.clock is not None


def test_match_apply_san_delegates():
    m = Match()
    res = m.apply_san("e4")
    assert res.legal
    assert m.move_history[-1].san == "e4"


def test_match_position_at_delegates():
    m = Match()
    m.try_move(Square(6, 4), Square(4, 4))
    grid = m.position_at(0)
    assert grid[6][4] is not None
    assert grid[4][4] is None


def test_match_castling_rights_delegate():
    m = Match()
    assert m.castling_rights["WK"] is True


def test_match_position_counts_delegate():
    """position_counts is the backend's live Counter; each ply hashes a new position."""
    m = Match()
    assert m.position_counts is m.backend.position_counts
    assert sum(m.position_counts.values()) == 1
    m.try_move(Square(6, 4), Square(4, 4))
    assert sum(m.position_counts.values()) == 2
    m.try_move(Square(1, 4), Square(3, 4))
    assert sum(m.position_counts.values()) == 3


def test_match_promote_delegates():
    m = Match()
    m.backend.state = [[None] * 8 for _ in range(8)]
    m.backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    m.backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    m.backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    m.backend.turn = PieceColor.WHITE
    m.backend.move_history = []
    from collections import Counter
    m.backend.position_counts = Counter()
    m.backend.position_counts[m.backend._position_key()] = 1
    m.try_move(Square(1, 0), Square(0, 0))
    m.promote(Square(0, 0), PieceType.QUEEN)
    assert m.state[0][0].type == PieceType.QUEEN
