from backend.match import Match, SINGLE_SCREEN, BOT, ONLINE
from backend.pieces import PieceColor
from backend.utils import Square


def test_match_default_is_single_screen_hot_seat():
    m = Match()
    assert m.mode == SINGLE_SCREEN
    assert m.local_color is None


def test_match_online_with_local_color():
    m = Match(mode=ONLINE, local_color=PieceColor.WHITE)
    assert m.mode == ONLINE
    assert m.local_color == PieceColor.WHITE


def test_match_bot_with_local_color():
    m = Match(mode=BOT, local_color=PieceColor.BLACK)
    assert m.mode == BOT
    assert m.local_color == PieceColor.BLACK


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
    m = Match()
    assert m.state is m.backend.state


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
    # Pawn back at e2.
    assert grid[6][4] is not None
    assert grid[4][4] is None


def test_match_castling_rights_delegate():
    m = Match()
    assert m.castling_rights["WK"] is True


def test_match_position_counts_delegate():
    m = Match()
    assert sum(m.position_counts.values()) == 1


def test_match_promote_delegates():
    from collections import Counter
    from backend.pieces import Piece, PieceType
    m = Match()
    m.backend.state = [[None] * 8 for _ in range(8)]
    m.backend.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    m.backend.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    m.backend.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    m.backend.turn = PieceColor.WHITE
    m.backend.move_history = []
    m.backend.position_counts = Counter()
    m.backend.position_counts[m.backend._position_key()] = 1
    m.try_move(Square(1, 0), Square(0, 0))
    m.promote(Square(0, 0), PieceType.QUEEN)
    assert m.state[0][0].type == PieceType.QUEEN
