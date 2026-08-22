import copy
from collections.abc import Container

from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import PIECE_VALUES, PieceColor
from chessshootout.backend.utils import Square
from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts
from chessshootout.skillcheck.weights import roll_skillcheck


def total_legal_moves(backend: Backend, color: PieceColor,
                      locked: Container[tuple[Square, Square]] | None = None) -> int:
    """
    Count every move a side can actually play, leaving out the ones locked by
    a lost skill check. It exists to answer a single question -- is this
    player down to one move -- so a forced move can be spared a check

    :param backend: engine holding the position to scan
    :param color: side whose moves are counted
    :param locked: (from, to) pairs fluffed this turn and therefore not
        playable, or None when nothing is locked
    :returns: number of moves the side has left
    """
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


def forced_move(backend: Backend, color: PieceColor | None = None,
                locked: Container[tuple[Square, Square]] | None = None) -> bool:
    """
    Tell whether a side has exactly one playable move left. Skill checks are
    suppressed in that case, because losing one would lock the only move and
    leave the player unable to move at all

    :param backend: engine holding the position to scan
    :param color: side to test, defaulting to whoever is to move
    :param locked: (from, to) pairs already fluffed this turn, which count
        against the total, or None when nothing is locked
    :returns: True when a single legal move remains
    """
    if color is None:
        color = backend.turn
    return total_legal_moves(backend, color, locked) == 1


def compute_facts(backend: Backend, from_sq: Square, to_sq: Square,
                  locked: Container[tuple[Square, Square]] | None = None) -> TriggerFacts | None:
    """
    Work out the handful of things about a candidate move that decide whether
    it fires a skill check: is it a capture, of what and by what, is it a
    promotion, and is it the mover's only move. The move is tried on a copy of
    the engine, so nothing here disturbs the real position

    :param backend: engine holding the position, left untouched
    :param from_sq: square the piece would leave
    :param to_sq: square it would land on
    :param locked: (from, to) pairs fluffed this turn, which the forced-move
        count has to exclude, or None when nothing is locked
    :returns: the trigger facts, or None when the move is not legal at all
    """
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
        captured_value=PIECE_VALUES.get(captured.type, 0) if captured is not None else 0,
        is_promotion=result.promotion_required,
        is_forced=forced_move(backend, mover, locked),
    )


def select_skillcheck(backend: Backend, from_sq: Square, to_sq: Square, roll: float,
                      locked: Container[tuple[Square, Square]] | None = None,
                      facts: TriggerFacts | None = None) -> SkillCheckKind:
    """
    Turn a candidate move and its seeded roll into the kind of check it fires,
    the step both the local coordinator and the server share. A move that is
    not legal quietly answers NONE rather than raising

    :param backend: engine holding the position the move is judged against
    :param from_sq: square the piece would leave
    :param to_sq: square it would land on
    :param roll: seeded float in [0, 1) drawn for this ply and move
    :param locked: (from, to) pairs fluffed this turn, or None when nothing is
        locked
    :param facts: trigger facts when the caller already probed the move, or
        None to probe it here
    :returns: the kind to run, NONE when the move simply lands
    """
    if facts is None:
        facts = compute_facts(backend, from_sq, to_sq, locked)
    if facts is None:
        return SkillCheckKind.NONE
    return roll_skillcheck(facts, roll)
