from dataclasses import dataclass

from chessshootout.backend.pieces import PieceType

DUEL_SIZES = (4, 3, 2)
DUEL_PLIES_PER_SIZE = 4

RANGE_ANY = 99
RANGE_BY_TYPE = {
    PieceType.PAWN: 1,
    PieceType.KNIGHT: 2,
    PieceType.BISHOP: 2,
    PieceType.ROOK: 3,
    PieceType.QUEEN: RANGE_ANY,
    PieceType.KING: RANGE_ANY,
}
SHOTGUN_TYPES = frozenset({PieceType.ROOK, PieceType.QUEEN})

ATTACKER = "attacker"
DEFENDER = "defender"


def fighter_range(piece_type):
    return RANGE_BY_TYPE.get(piece_type, 1)


def is_shotgun(piece_type):
    return piece_type in SHOTGUN_TYPES


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


@dataclass(frozen=True)
class DuelIntent:
    step: tuple = None
    fire: tuple = None


class DuelEngine:

    def __init__(self, attacker_type, defender_type):
        self.attacker_type = attacker_type
        self.defender_type = defender_type
        self.size_index = 0
        self.ply_in_size = 0
        self.to_move = ATTACKER
        self.winner = None
        size = self.size
        self.attacker_pos = (size - 1, 0)
        self.defender_pos = (0, size - 1)

    @property
    def size(self):
        return DUEL_SIZES[self.size_index]

    def type_of(self, side):
        return self.attacker_type if side == ATTACKER else self.defender_type

    def pos_of(self, side):
        return self.attacker_pos if side == ATTACKER else self.defender_pos

    def opponent_of(self, side):
        return DEFENDER if side == ATTACKER else ATTACKER

    def is_over(self):
        return self.winner is not None

    def capture_succeeds(self):
        return self.winner == ATTACKER

    def legal_steps(self, side):
        pos = self.pos_of(side)
        blocked = self.pos_of(self.opponent_of(side))
        steps = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                cell = (pos[0] + dr, pos[1] + dc)
                if not (0 <= cell[0] < self.size and 0 <= cell[1] < self.size):
                    continue
                if cell == blocked:
                    continue
                steps.append(cell)
        return steps

    def in_range(self, side, shooter_pos, fire):
        if not (0 <= fire[0] < self.size and 0 <= fire[1] < self.size):
            return False
        return chebyshev(shooter_pos, fire) <= fighter_range(self.type_of(side))

    def fire_hits(self, side, fire):
        target = self.pos_of(self.opponent_of(side))
        if is_shotgun(self.type_of(side)):
            return chebyshev(fire, target) <= 1
        return fire == target

    def can_hit_from(self, side, shooter_pos):
        target = self.pos_of(self.opponent_of(side))
        reach = fighter_range(self.type_of(side)) + (1 if is_shotgun(self.type_of(side)) else 0)
        return chebyshev(shooter_pos, target) <= reach

    def _resolve_position(self, side, intent):
        pos = self.pos_of(side)
        if intent.step is not None:
            if intent.step not in self.legal_steps(side):
                raise ValueError("illegal step")
            pos = intent.step
        if intent.fire is not None and not self.in_range(side, pos, intent.fire):
            raise ValueError("fire out of range")
        return pos

    def apply(self, intent):
        if self.is_over():
            raise ValueError("duel already decided")
        side = self.to_move
        pos = self._resolve_position(side, intent)
        if side == ATTACKER:
            self.attacker_pos = pos
        else:
            self.defender_pos = pos
        if intent.fire is not None and self.fire_hits(side, intent.fire):
            self.winner = side
            return
        self._advance_turn()

    def _advance_turn(self):
        self.to_move = self.opponent_of(self.to_move)
        self.ply_in_size += 1
        if self.ply_in_size < DUEL_PLIES_PER_SIZE:
            return
        self.ply_in_size = 0
        if self.size_index + 1 < len(DUEL_SIZES):
            self.size_index += 1
            self._reclamp()
        else:
            self.winner = DEFENDER

    def _reclamp(self):
        size = self.size
        self.attacker_pos = (min(self.attacker_pos[0], size - 1),
                             min(self.attacker_pos[1], size - 1))
        self.defender_pos = (min(self.defender_pos[0], size - 1),
                             min(self.defender_pos[1], size - 1))
        if self.defender_pos == self.attacker_pos:
            self.defender_pos = self._farthest_cell(self.attacker_pos)

    def _farthest_cell(self, occupied):
        best = None
        best_distance = -1
        for r in range(self.size):
            for c in range(self.size):
                if (r, c) == occupied:
                    continue
                distance = chebyshev((r, c), occupied)
                if distance > best_distance:
                    best_distance = distance
                    best = (r, c)
        return best
