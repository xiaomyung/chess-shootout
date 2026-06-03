import time
from typing import Optional

from backend.backend import Backend
from backend.pieces import PieceColor
from backend.utils import MoveResult, PROMO_LETTER_BY_TYPE


SINGLE_SCREEN = "single_screen"
BOT = "bot"
ONLINE = "online"


class Match:

    def __init__(self, mode=SINGLE_SCREEN, local_color: Optional[PieceColor] = None):
        self.mode = mode
        self.local_color = local_color
        self.backend = Backend()
        self.backend.new_game()
        self.on_local_move_applied = None

    def try_move(self, from_sq, to_sq) -> MoveResult:
        result = self.backend.try_move(from_sq, to_sq)
        if result.legal and not result.promotion_required:
            self._fire_local_move(from_sq, to_sq, None)
        return result

    def apply_remote_move(self, from_sq, to_sq, promotion=None) -> MoveResult:
        result = self.backend.try_move(from_sq, to_sq)
        if not result.legal:
            return result
        if result.promotion_required and promotion is not None:
            return self.backend.promote(to_sq, promotion)
        return result

    def promote(self, square, piece_type) -> MoveResult:
        result = self.backend.promote(square, piece_type)
        if result.legal:
            promo_letter = PROMO_LETTER_BY_TYPE.get(piece_type)
            entry = self.backend.move_history[-1] if self.backend.move_history else None
            from_sq = entry.move.from_sq if entry else None
            if from_sq is not None:
                self._fire_local_move(from_sq, square, promo_letter)
        return result

    def _fire_local_move(self, from_sq, to_sq, promotion):
        if self.on_local_move_applied is not None:
            self.on_local_move_applied(from_sq, to_sq, promotion)

    def undo(self) -> None:
        self.backend.undo()

    def new_game(self) -> None:
        self.backend.new_game()

    def setup_clock(self, initial_seconds, increment_seconds, now_provider=time.monotonic):
        self.backend.setup_clock(initial_seconds, increment_seconds, now_provider)

    def tick_clock(self):
        self.backend.tick_clock()

    def current_turn(self):
        return self.backend.current_turn()

    def game_result(self):
        return self.backend.game_result()

    def is_game_over(self):
        return self.backend.is_game_over()

    def is_in_check(self, color):
        return self.backend.is_in_check(color)

    def piece_at(self, square):
        return self.backend.piece_at(square)

    def legal_moves_from(self, square):
        return self.backend.legal_moves_from(square)

    def position_at(self, ply):
        return self.backend.position_at(ply)

    def apply_san(self, san) -> MoveResult:
        return self.backend.apply_san(san)

    @property
    def state(self):
        return self.backend.state

    @property
    def move_history(self):
        return self.backend.move_history

    @property
    def clock(self):
        return self.backend.clock

    @property
    def position_counts(self):
        return self.backend.position_counts

    @property
    def castling_rights(self):
        return self.backend.castling_rights

    @property
    def en_passant_target(self):
        return self.backend.en_passant_target

    @property
    def halfmove_clock(self):
        return self.backend.halfmove_clock
