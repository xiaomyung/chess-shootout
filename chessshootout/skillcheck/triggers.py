import copy

from chessshootout.backend.pieces import PIECE_VALUES, PieceType
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


def compute_facts(backend, from_sq, to_sq, promo_type=None, locked=None):
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
    is_promotion = result.promotion_required
    if is_promotion:
        if promo_type is None:
            promo_type = PieceType.QUEEN
        result = probe.promote(to_sq, promo_type)
        if captured is None:
            captured = result.captured

    is_capture = captured is not None
    is_checkmate = bool(result.is_checkmate)
    is_check = bool(result.is_check) and not is_checkmate
    landed = probe.piece_at(to_sq)

    return TriggerFacts(
        is_capture=is_capture,
        capturer_value=capturer_value,
        captured_value=PIECE_VALUES.get(captured.type, 0) if is_capture else 0,
        is_check=is_check,
        is_checkmate=is_checkmate,
        checker_value=PIECE_VALUES.get(landed.type, 0) if landed is not None else 0,
        is_promotion=is_promotion,
        promo_value=PIECE_VALUES.get(promo_type, 0) if is_promotion else 0,
        is_forced=forced_move(backend, mover, locked),
    )


def select_skillcheck(backend, from_sq, to_sq, roll, promo_type=None, locked=None):
    facts = compute_facts(backend, from_sq, to_sq, promo_type, locked)
    if facts is None:
        return SkillCheckKind.NONE
    return roll_skillcheck(facts, roll)
