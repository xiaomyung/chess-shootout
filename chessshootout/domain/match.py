import time
from collections import Counter
from collections.abc import Callable

from chessshootout.backend.backend import Backend
from chessshootout.backend.clock import Clock
from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.backend.utils import (
    HistoryEntry, MoveResult, PROMO_LETTER_BY_TYPE, PositionKey, Square,
)


SINGLE_SCREEN = "single_screen"
BOT = "bot"
ONLINE = "online"


class Match:
    """
    The game object the screens hold: a thin wrapper around the chess engine
    that also knows which mode is being played and, online, which colour this
    client is. Board, panels, premoves and the result flow all read the game
    through it instead of reaching for the engine themselves
    """

    def __init__(self, mode: str = SINGLE_SCREEN,
                 local_color: PieceColor | None = None) -> None:
        """
        Start a fresh game in the given mode. A screen builds one Match when it
        is created and reuses it for the whole run, calling new_game() between
        games rather than replacing it

        :param mode: how the game is played, one of SINGLE_SCREEN, BOT, ONLINE
        :param local_color: side this client plays online; None when both sides
            are played on this machine
        """
        self.mode = mode
        self.local_color = local_color
        self.backend = Backend()
        self.backend.new_game()
        self.on_local_move_applied: Callable[[Square, Square, str | None], None] | None = None

    def try_move(self, from_sq: Square, to_sq: Square) -> MoveResult:
        """
        Play a move for the side to move -- the local player's way into the
        engine. A move that lands whole announces itself to the local-move
        listener, which online is what puts it on the wire; a move that still
        needs a promotion piece stays silent until promote() finishes it

        :param from_sq: square the piece leaves
        :param to_sq: square it lands on
        :returns: the engine's verdict, including whether a promotion is
            pending
        """
        result = self.backend.try_move(from_sq, to_sq)
        if result.legal and not result.promotion_required:
            self._fire_local_move(from_sq, to_sq, None)
        return result

    def apply_remote_move(self, from_sq: Square, to_sq: Square,
                          promotion: PieceType | None = None) -> MoveResult:
        """
        Play the move the server reported for the opponent, promotion and all.
        It deliberately does not announce the move locally -- a move that came
        off the wire must never be sent back out

        :param from_sq: square the piece leaves
        :param to_sq: square it lands on
        :param promotion: piece a promoting pawn becomes, None when the move is
            not a promotion
        :returns: the engine's verdict; an illegal verdict means this client is
            out of step and needs a resync
        """
        result = self.backend.try_move(from_sq, to_sq)
        if not result.legal:
            return result
        if result.promotion_required and promotion is not None:
            return self.backend.promote(to_sq, promotion)
        return result

    def promote(self, square: Square, piece_type: PieceType) -> MoveResult:
        """
        Finish a promotion that try_move left pending by naming the piece,
        which completes the ply. This is the one place a local promotion is
        announced to the local-move listener, so the ply is reported exactly
        once

        :param square: square the promoting pawn stands on
        :param piece_type: piece the pawn turns into
        :returns: the engine's verdict for the now completed ply
        """
        result = self.backend.promote(square, piece_type)
        if result.legal:
            promo_letter = PROMO_LETTER_BY_TYPE.get(piece_type)
            entry = self.backend.move_history[-1] if self.backend.move_history else None
            from_sq = entry.move.from_sq if entry else None
            if from_sq is not None:
                self._fire_local_move(from_sq, square, promo_letter)
        return result

    def _fire_local_move(self, from_sq: Square, to_sq: Square,
                         promotion: str | None) -> None:
        """
        Tell the listener, if there is one, that the local player has just
        completed a ply. Online the game screen hooks this up to the send path,
        so it fires once per locally played ply and never for a remote one

        :param from_sq: square the piece left
        :param to_sq: square it landed on
        :param promotion: promotion piece letter (q, r, b or n), None when the
            move was not a promotion
        """
        if self.on_local_move_applied is not None:
            self.on_local_move_applied(from_sq, to_sq, promotion)

    def undo(self) -> None:
        """
        Take the last ply back, used by the local undo button and by an online
        takeback once the server has agreed to it
        """
        self.backend.undo()

    def new_game(self) -> None:
        """
        Reset to the starting position, clearing history, clock and repetition
        counts. Screens call this between games, and it is also the first half
        of rebuilding a game from the server's move list
        """
        self.backend.new_game()

    def setup_clock(self, initial_seconds: float, increment_seconds: float,
                    now_provider: Callable[[], float] = time.monotonic) -> None:
        """
        Give the game a chess clock, done when a timed game starts or is
        resumed. An untimed game simply never calls this and keeps no clock

        :param initial_seconds: starting time for each side, in seconds
        :param increment_seconds: seconds added to a side after each of its
            moves
        :param now_provider: source of monotonic seconds, swapped out in tests
        """
        self.backend.setup_clock(initial_seconds, increment_seconds, now_provider)

    def tick_clock(self) -> None:
        """
        Charge the side to move for the time that has passed, called once per
        frame while the game is live. It does nothing once a side has flagged
        or the position itself has ended the game
        """
        self.backend.tick_clock()

    def current_turn(self) -> PieceColor:
        """
        Say whose turn it is, the answer the board, the strips and every
        premove check gate on

        :returns: side to move
        """
        return self.backend.current_turn()

    def game_result(self) -> str | None:
        """
        Ask the engine whether the position itself has ended the game, which is
        how mate, stalemate, flag-fall, repetition and the fifty-move rule
        reach the screen. Endings a player declares, such as resignation, are
        held by the screen instead

        :returns: the result code, or None while the game is still on
        """
        return self.backend.game_result()

    def is_game_over(self) -> bool:
        """
        Say whether the engine considers the game finished

        :returns: True once the position itself ends the game
        """
        return self.backend.is_game_over()

    def is_in_check(self, color: PieceColor) -> bool:
        """
        Say whether one side's king is under attack right now, which drives the
        check highlight and the check sound

        :param color: side whose king is examined
        :returns: True when that king is in check
        """
        return self.backend.is_in_check(color)

    def piece_at(self, square: Square) -> Piece | None:
        """
        Read the piece standing on a square of the live position

        :param square: board square to read
        :returns: the piece there, or None when the square is empty
        """
        return self.backend.piece_at(square)

    def legal_moves_from(self, square: Square) -> list[Square]:
        """
        List every legal destination for the piece on a square -- the set the
        board paints as move hints and checks a drop against

        :param square: square the piece stands on
        :returns: squares it may legally move to, empty when it has none
        """
        return self.backend.legal_moves_from(square)

    def position_at(self, ply: int) -> list[list[Piece | None]]:
        """
        Rebuild the board as it stood after a given ply, which is what lets a
        player browse a game without disturbing the one being played

        :param ply: half-move to rewind to, 0 being the starting position
        :returns: an 8x8 grid of pieces, None where a square is empty
        """
        return self.backend.position_at(ply)

    def apply_san(self, san: str) -> MoveResult:
        """
        Play a move written in algebraic notation. Replaying a saved PGN and
        rebuilding a game from the server's move list after a reconnect both
        run through here

        :param san: the move in standard algebraic notation
        :returns: the engine's verdict; an illegal verdict stops the replay
        """
        return self.backend.apply_san(san)

    @property
    def state(self) -> list[list[Piece | None]]:
        """
        The live position as an 8x8 grid, read by the board renderer and by
        premove projection

        :returns: rows of pieces, None where a square is empty
        """
        return self.backend.state

    @property
    def move_history(self) -> list[HistoryEntry]:
        """
        Every ply played so far. Each entry carries the SAN built at move time,
        which the move list and the PGN writer reuse verbatim rather than
        working the notation out again

        :returns: history entries in play order
        """
        return self.backend.move_history

    @property
    def clock(self) -> Clock | None:
        """
        The game clock, shared by the player strips, the flag-fall check and
        the give-time flow

        :returns: the clock, or None in an untimed game
        """
        return self.backend.clock

    @property
    def position_counts(self) -> Counter[PositionKey]:
        """
        How often each position has been reached, the tally threefold
        repetition is judged from

        :returns: position key to the number of times it has occurred
        """
        return self.backend.position_counts

    @property
    def castling_rights(self) -> dict[str, bool]:
        """
        Which castles each side may still play, part of what a position is
        written out as FEN with

        :returns: right key (WK, WQ, BK, BQ) to whether it survives
        """
        return self.backend.castling_rights

    @property
    def en_passant_target(self) -> Square | None:
        """
        The square a pawn may capture en passant on this turn. It is part of
        both the FEN and the repetition key, so two otherwise identical
        positions with different en-passant rights count as different

        :returns: the target square, or None when there is none
        """
        return self.backend.en_passant_target

    @property
    def halfmove_clock(self) -> int:
        """
        Plies since the last capture or pawn move, the counter the fifty-move
        draw is drawn from

        :returns: number of halfmoves since the last reset
        """
        return self.backend.halfmove_clock
