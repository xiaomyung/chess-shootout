import copy

from chessshootout.backend.pieces import PIECE_VALUES
from chessshootout.backend.utils import Square
from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts
from chessshootout.skillcheck.weights import roll_skillcheck


def total_legal_moves(backend, color, locked=None):
    total = 0
    for row in range(backend.SIZE):
        for col in range(backend.SIZE):
            piece = backend.state[row][col]
            if piece is None or piece.color != color:
                continue
            origin = Square(row, col)
            for target in backend.legal_moves_from(origin):
                if locked is not None and (origin, target) in locked:
                    continue
                total += 1
    return total


def forced_move(backend, color=None, locked=None):
    if color is None:
        color = backend.turn
    return total_legal_moves(backend, color, locked) == 1


def compute_facts(backend, from_sq, to_sq, locked=None):
    origin_piece = backend.state[from_sq.row][from_sq.col]
    if origin_piece is None:
        return None
    mover = backend.turn
    capturer_value = PIECE_VALUES.get(origin_piece.type, 0)

    probe = copy.deepcopy(backend)
    result = probe.try_move(from_sq, to_sq)
    if not result.legal:
        return None

    captured = result.captured
    is_capture = captured is not None

    return TriggerFacts(
        is_capture=is_capture,
        capturer_value=capturer_value,
        captured_value=PIECE_VALUES.get(captured.type, 0) if is_capture else 0,
        is_promotion=result.promotion_required,
        is_forced=forced_move(backend, mover, locked),
    )


def select_skillcheck(backend, from_sq, to_sq, roll, locked=None, facts=None):
    if facts is None:
        facts = compute_facts(backend, from_sq, to_sq, locked)
    if facts is None:
        return SkillCheckKind.NONE
    return roll_skillcheck(facts, roll)
