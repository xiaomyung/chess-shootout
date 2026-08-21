import copy
import re
import time
from collections import Counter
from itertools import product
from typing import Callable

from chessshootout.backend.pieces import (
    BACK_RANK, BISHOP_DIRECTIONS, KING_OFFSETS, KNIGHT_OFFSETS, Piece,
    PieceColor, PieceType, QUEEN_DIRECTIONS, ROOK_DIRECTIONS, king_home_row,
    opponent_of, pawn_forward, pawn_start_row,
)
from chessshootout.backend.clock import Clock
from chessshootout.backend.pseudo_legal import king_square
from chessshootout.backend.utils import (
    BOARD_SIZE, HistoryEntry, Move, MoveResult, PositionKey, Square, on_board,
)


SAN_PIECE_LETTER = {
    PieceType.KNIGHT: "N",
    PieceType.BISHOP: "B",
    PieceType.ROOK: "R",
    PieceType.QUEEN: "Q",
    PieceType.KING: "K",
}

SAN_LETTER_TO_PIECE = {v: k for k, v in SAN_PIECE_LETTER.items()}

SAN_FILES = "abcdefgh"

_SAN_PROMOTION = {
    "Q": PieceType.QUEEN,
    "R": PieceType.ROOK,
    "B": PieceType.BISHOP,
    "N": PieceType.KNIGHT,
}

_SAN_MOVE_RE = re.compile(
    r"^([NBRQK])?"
    r"([a-h])?"
    r"([1-8])?"
    r"(x)?"
    r"([a-h])"
    r"([1-8])"
    r"(=([NBRQ]))?$"
)

CASTLING_KEYS = ("WK", "WQ", "BK", "BQ")
DEFAULT_CASTLING_RIGHTS = {"WK": True, "WQ": True, "BK": True, "BQ": True}
FIFTY_MOVE_HALFMOVES = 100


class Backend:
    """
    The chess engine: one position, the moves that reached it, the clock and the
    repetition count, plus every rule that governs them. Nothing above it -- the
    board on screen, the online room, the PGN writer -- reimplements a rule of
    chess; they ask this object what is legal and what the game's state now is
    """

    SIZE = BOARD_SIZE

    def __init__(self) -> None:
        """
        Build an engine on an empty board with White to move and no clock.
        Callers follow with new_game() for the standard opening setup, or with
        apply_fen() to load a position
        """
        self._reset_state()

    def _reset_state(self) -> None:
        """
        Put every field back to its blank starting value, so a fresh game cannot
        inherit a leftover history, castling right, en-passant target,
        repetition count or fullmove baseline. It is also the one place the
        engine's state fields are listed, which is why construction and
        new_game() both start here
        """
        self.state: list[list[Piece | None]] = [[None] * self.SIZE for _ in range(self.SIZE)]
        self.turn = PieceColor.WHITE
        self.move_history: list[HistoryEntry] = []
        self.en_passant_target: Square | None = None
        self.castling_rights = dict(DEFAULT_CASTLING_RIGHTS)
        self.halfmove_clock = 0
        self.fullmove_baseline = 1
        self.baseline_black_to_move = False
        self.position_counts: Counter[PositionKey] = Counter()
        self.clock: Clock | None = None
        self._legal_move_memo: tuple[int, bool] | None = None

    def new_game(self) -> None:
        """
        Set the board up for a standard game and count the starting position as
        seen once, which is what makes threefold repetition measurable from the
        very first move. A rematch and an online state rebuild both begin here
        too, the rebuild then replaying its moves on top
        """
        self._reset_state()

        for col, piece_type in enumerate(BACK_RANK):
            self.state[0][col] = Piece(piece_type, PieceColor.BLACK)
            self.state[1][col] = Piece(PieceType.PAWN, PieceColor.BLACK)
            self.state[6][col] = Piece(PieceType.PAWN, PieceColor.WHITE)
            self.state[7][col] = Piece(piece_type, PieceColor.WHITE)

        self.position_counts[self._position_key()] = 1

    def setup_clock(self, initial_seconds: float, increment_seconds: float,
                    now_provider: Callable[[], float] = time.monotonic) -> None:
        """
        Give the game a clock at the chosen time control and start it running on
        White. A game with no clock is simply one this was never called on, and
        it then plays untimed

        :param initial_seconds: starting time per side in seconds
        :param increment_seconds: seconds returned to a player after each of
            their moves
        :param now_provider: source of monotonic seconds; the tests and the
            server sweep pass their own so time can be driven deliberately
        """
        self.clock = Clock.create(initial_seconds, increment_seconds, now_provider=now_provider)
        self.clock.start()

    def tick_clock(self) -> None:
        """
        Let the clock count down by the real time since the last tick, which the
        client does once per frame and the server once per sweep step. A game
        that is already over is never charged: a fallen flag returns at once,
        and so does a position whose side to move is mated or stalemated, whose
        clocks freeze where they stood. The costly legal-move scan behind that
        second test is memoized, so it costs one pass per position rather than
        one per tick
        """
        if self.clock is None or self.clock.flagged is not None:
            return
        if self._side_to_move_has_no_legal_moves():
            return
        self.clock.tick()

    def piece_at(self, square: Square) -> Piece | None:
        """
        Read the piece standing on a square of the live position, the lookup the
        board makes for drawing, dragging and capture effects

        :param square: square to read, expected to be on the board
        :returns: the piece standing there, or None when the square is empty
        """
        return self.state[square.row][square.col]

    def current_turn(self) -> PieceColor:
        """
        Say whose turn it is, the fact every gate above the engine checks before
        it lets a player pick a piece up

        :returns: the side to move
        """
        return self.turn

    def legal_moves_from(self, square: Square) -> list[Square]:
        """
        List the squares a piece may legally move to: what its own rule and the
        board allow, minus every move that would leave its own king in check.
        Move highlighting, SAN disambiguation and the mate test all rest on it

        :param square: square the piece stands on; an empty one yields nothing
        :returns: legal destination squares, in generation order
        """
        return [
            to_sq for to_sq in self._pseudo_legal_moves(square)
            if not self._would_leave_king_in_check(square, to_sq)
        ]

    def is_in_check(self, color: PieceColor) -> bool:
        """
        Say whether a side's king is under attack right now, which drives the
        check highlight, the check sound and the checkmate test

        :param color: side whose king is examined
        :returns: True when that king is attacked
        """
        king_sq = self._find_king(color)
        return self._is_square_attacked(king_sq, opponent_of(color))

    def is_game_over(self) -> bool:
        """
        Say whether the game has ended by any rule the engine itself knows.
        Endings that come from the players rather than the position --
        resignation, an agreed draw, an abort -- live above the engine and are
        invisible here

        :returns: True when the position or the clock has already ended it
        """
        return self.game_result() is not None

    def game_result(self) -> str | None:
        """
        Give the code for how the game finished, or None while it is still
        running; this is what the result screen, the PGN result tag and the
        online room all read. The rules are tested in a fixed order -- mate or
        stalemate, then a fallen flag, then insufficient material, threefold
        repetition and the fifty-move rule -- so a position that satisfies two
        of them reports the earlier one. A bare white_wins or black_wins means
        checkmate and nothing else, since every manual ending is spelled out in
        full, as in white_wins_by_resignation

        :returns: result code, or None while the game is still live
        """
        if self._has_no_legal_moves(self.turn):
            if self.is_in_check(self.turn):
                return "black_wins" if self.turn == PieceColor.WHITE else "white_wins"
            return "draw_stalemate"
        if self.clock is not None and self.clock.flagged is not None:
            if self.clock.flagged == PieceColor.WHITE:
                return "black_wins_on_time"
            return "white_wins_on_time"
        if self._has_insufficient_material():
            return "draw_insufficient_material"
        if self.position_counts and max(self.position_counts.values()) >= 3:
            return "draw_repetition"
        if self.halfmove_clock >= FIFTY_MOVE_HALFMOVES:
            return "draw_fifty_move"
        return None

    def try_move(self, from_sq: Square, to_sq: Square) -> MoveResult:
        """
        Play a move for the side to move. Every ply the game ever plays comes
        through here -- a local click, a replayed SAN, a move relayed from the
        server -- and an illegal attempt is refused without the board being
        touched. A ply that lands whole is finished here; a pawn reaching the
        last rank is left half-applied until promote() names its piece, and that
        is the only case where this does not complete the ply

        :param from_sq: square the piece starts on
        :param to_sq: square it is moving to
        :returns: whether the move was legal, what it took, and whether it gave
            check, mate or stalemate or still needs a promotion choice
        """
        if self.is_game_over():
            return MoveResult(legal=False)

        piece = self.state[from_sq.row][from_sq.col]
        if piece is None or piece.color != self.turn:
            return MoveResult(legal=False)
        if to_sq not in self.legal_moves_from(from_sq):
            return MoveResult(legal=False)

        if self._is_castling_move(from_sq, to_sq, piece):
            return self._apply_castle(from_sq, to_sq, piece)
        if self._is_en_passant_move(from_sq, to_sq, piece):
            return self._apply_en_passant(from_sq, to_sq, piece)
        if piece.type == PieceType.PAWN and to_sq.row in (0, 7):
            return self._apply_promotion_pending(from_sq, to_sq, piece)
        return self._apply_normal(from_sq, to_sq, piece)

    def promote(self, square: Square, piece_type: PieceType) -> MoveResult:
        """
        Finish a promotion by putting the chosen piece on the last rank, the
        second half of the ply try_move left pending. The history entry takes a
        freshly built frozen Move and gains its =Q suffix, and only now is the
        ply complete: this is the one other place _finalize_move runs, so the
        position is counted for repetition exactly once

        :param square: last-rank square the promoting pawn reached
        :param piece_type: piece chosen; only queen, rook, bishop and knight
            are accepted
        :returns: the finished move's result, check and mate flags included
        """
        if piece_type not in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
            raise ValueError(f"Cannot promote to {piece_type}")
        if not self.move_history or self.move_history[-1].position_key_added is not None:
            raise ValueError("No promotion pending")

        entry = self.move_history[-1]
        pawn = entry.move.piece
        self.state[square.row][square.col] = Piece(piece_type, pawn.color)
        entry.move = Move(
            from_sq=entry.move.from_sq,
            to_sq=entry.move.to_sq,
            piece=pawn,
            captured=entry.move.captured,
            promoted_to=piece_type,
        )
        entry.san += f"={SAN_PIECE_LETTER[piece_type]}"
        self._finalize_move(entry)
        return self._build_move_result(entry.move.captured)

    def position_at(self, ply: int) -> list[list[Piece | None]]:
        """
        Rebuild the board as it stood after a given number of plies, which is
        what the review browser draws while a player steps back through a game.
        The live position is handed back as it is, while an earlier one is
        rebuilt on a deep copy, so browsing can never disturb the game in play.
        The clock is detached for the length of that copy and put straight back:
        where the pieces stood does not depend on it, and copying a live clock
        would clone its time source once per lookup

        :param ply: number of plies played, 0 being the starting position
        :returns: 8x8 grid of pieces as of that moment
        """
        if ply < 0 or ply > len(self.move_history):
            raise ValueError(f"Ply {ply} out of range 0..{len(self.move_history)}")
        if ply == len(self.move_history):
            return [list(row) for row in self.state]
        clock = self.clock
        self.clock = None
        try:
            snapshot = copy.deepcopy(self)
        finally:
            self.clock = clock
        while len(snapshot.move_history) > ply:
            snapshot.undo()
        return snapshot.state

    def preview_san(self, from_sq: Square, to_sq: Square,
                    promo_letter: str | None = None) -> str:
        """
        Name a move in algebraic notation before it is played, which is how a
        move still waiting on a skill check can already be shown on screen and
        written into the log. It has to be asked on the pre-move position, since
        telling two identical pieces apart depends on the board as it stands

        :param from_sq: square the piece starts on
        :param to_sq: square it would move to
        :param promo_letter: promotion piece letter to append, or None when the
            move promotes nothing
        :returns: SAN for the move, or empty when no piece stands on from_sq
        """
        piece = self.state[from_sq.row][from_sq.col]
        if piece is None:
            return ""
        is_en_passant = self._is_en_passant_move(from_sq, to_sq, piece)
        if is_en_passant:
            captured = self.state[from_sq.row][to_sq.col]
        else:
            captured = self.state[to_sq.row][to_sq.col]
        san = self._build_san(from_sq, to_sq, piece, captured, is_en_passant=is_en_passant)
        if promo_letter is not None:
            san += f"={promo_letter.upper()}"
        return san

    def apply_san(self, san: str) -> MoveResult:
        """
        Play a move written in algebraic notation, the door a whole game is
        rebuilt through -- loading a PGN and replaying an online game after a
        reconnect both come this way. The notation is resolved against the
        current position and a move that matches no single legal move is
        refused rather than guessed at; a promotion with no piece named
        becomes a queen

        :param san: move in standard algebraic notation; !?+# are trimmed off
        :returns: the result of playing it, illegal when the notation resolved
            to no single legal move
        """
        san = san.rstrip("!?+#")
        if not san:
            return MoveResult(legal=False)
        home_row = king_home_row(self.turn)
        if san in ("O-O", "0-0"):
            return self.try_move(Square(home_row, 4), Square(home_row, 6))
        if san in ("O-O-O", "0-0-0"):
            return self.try_move(Square(home_row, 4), Square(home_row, 2))

        match = _SAN_MOVE_RE.match(san)
        if match is None:
            return MoveResult(legal=False)
        (piece_letter, dis_file, dis_rank, _capture,
         tgt_file, tgt_rank, _, promo_letter) = match.groups()

        target = Square(self.SIZE - int(tgt_rank), SAN_FILES.index(tgt_file))
        piece_type = (SAN_LETTER_TO_PIECE[piece_letter]
                      if piece_letter is not None else PieceType.PAWN)

        candidates: list[Square] = []
        for r, c in product(range(self.SIZE), repeat=2):
            piece = self.state[r][c]
            if piece is None or piece.type != piece_type or piece.color != self.turn:
                continue
            if dis_file is not None and c != SAN_FILES.index(dis_file):
                continue
            if dis_rank is not None and r != self.SIZE - int(dis_rank):
                continue
            if target in self.legal_moves_from(Square(r, c)):
                candidates.append(Square(r, c))

        if len(candidates) != 1:
            return MoveResult(legal=False)

        result = self.try_move(candidates[0], target)
        if not result.legal:
            return result
        if result.promotion_required:
            promo_type = (_SAN_PROMOTION[promo_letter]
                          if promo_letter is not None else PieceType.QUEEN)
            return self.promote(target, promo_type)
        return result

    def undo(self) -> None:
        """
        Take the last ply back, putting the board, the castling rights, the
        en-passant target, the halfmove clock, the repetition count and both
        players' times back to what the history entry recorded before that ply.
        A promotion still waiting on a piece choice is dropped without any of
        that being unwound, since it never completed in the first place. The
        remembered legal-move verdict goes too, because a different ply may now
        be played into the very ply count the old one was remembered against
        """
        if not self.move_history:
            return
        entry = self.move_history.pop()
        self._legal_move_memo = None
        m = entry.move

        if entry.position_key_added is not None:
            self.position_counts[entry.position_key_added] -= 1
            if self.position_counts[entry.position_key_added] == 0:
                del self.position_counts[entry.position_key_added]
            self.castling_rights = dict(zip(CASTLING_KEYS, entry.prev_castling_rights))
            self.en_passant_target = entry.prev_en_passant_target
            self.halfmove_clock = entry.prev_halfmove_clock
            if self.clock is not None and entry.prev_clock_snapshot is not None:
                self.clock.restore(entry.prev_clock_snapshot)
            self._switch_turn()

        self.state[m.from_sq.row][m.from_sq.col] = m.piece
        self.state[m.to_sq.row][m.to_sq.col] = m.captured

        if m.is_castle:
            rook_to_col = 5 if m.to_sq.col == 6 else 3
            rook_from_col = 7 if m.to_sq.col == 6 else 0
            self.state[m.from_sq.row][rook_from_col] = self.state[m.from_sq.row][rook_to_col]
            self.state[m.from_sq.row][rook_to_col] = None
        elif m.is_en_passant:
            self.state[m.to_sq.row][m.to_sq.col] = None
            self.state[m.from_sq.row][m.to_sq.col] = m.captured

    def position_key(self) -> PositionKey:
        """
        Hand out the repetition key for the position as it stands, so code
        outside the engine can seed or read a repetition count without reaching
        into its internals -- the FEN loader is the caller that needs it

        :returns: hashable key standing for this position
        """
        return self._position_key()

    def reset_legal_move_memo(self) -> None:
        """
        Forget the remembered verdict on whether the side to move is out of
        legal moves. The FEN loader is the caller that needs it: the verdict is
        remembered against the number of plies played, and loading a position
        leaves that number at zero while replacing every piece on the board, so
        nothing else would tell the new position from the old one
        """
        self._legal_move_memo = None

    def _apply_normal(self, from_sq: Square, to_sq: Square, piece: Piece) -> MoveResult:
        """
        Apply an everyday move: name it in SAN against the board as it still
        stands, carry the piece over, and record the finished ply. Anything that
        is not a castle, an en-passant capture or a promotion lands here

        :param from_sq: square the piece starts on
        :param to_sq: square it moves to
        :param piece: piece being moved, already checked as the mover's own
        :returns: the finished move's result
        """
        captured = self.state[to_sq.row][to_sq.col]
        san = self._build_san(from_sq, to_sq, piece, captured)
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        move = Move(from_sq, to_sq, piece, captured=captured)
        return self._record_and_finalize(move, captured, san)

    def _apply_castle(self, from_sq: Square, to_sq: Square, piece: Piece) -> MoveResult:
        """
        Apply a castle: the king steps two squares and its rook swings to the
        far side of it, recorded as O-O or O-O-O. Whether castling was allowed
        was settled when the move was generated, so only the pieces move here

        :param from_sq: square the king starts on
        :param to_sq: square the king lands on, which also says whether this is
            the kingside or the queenside castle
        :param piece: the castling king
        :returns: the finished move's result
        """
        san = "O-O" if to_sq.col == 6 else "O-O-O"
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        rook_from_col, rook_to_col = (7, 5) if to_sq.col == 6 else (0, 3)
        self.state[from_sq.row][rook_to_col] = self.state[from_sq.row][rook_from_col]
        self.state[from_sq.row][rook_from_col] = None
        move = Move(from_sq, to_sq, piece, is_castle=True)
        return self._record_and_finalize(move, None, san)

    def _apply_en_passant(self, from_sq: Square, to_sq: Square, piece: Piece) -> MoveResult:
        """
        Apply an en-passant capture: the pawn steps diagonally onto an empty
        square and the pawn it just passed, which sits beside its starting
        square, comes off the board. It is recorded as a capture, so the
        halfmove clock resets with it

        :param from_sq: square the capturing pawn starts on
        :param to_sq: empty square it steps onto
        :param piece: the capturing pawn
        :returns: the finished move's result
        """
        captured_sq = Square(from_sq.row, to_sq.col)
        captured = self.state[captured_sq.row][captured_sq.col]
        san = self._build_san(from_sq, to_sq, piece, captured, is_en_passant=True)
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        self.state[captured_sq.row][captured_sq.col] = None
        move = Move(from_sq, to_sq, piece, captured=captured, is_en_passant=True)
        return self._record_and_finalize(move, captured, san)

    def _apply_promotion_pending(self, from_sq: Square, to_sq: Square,
                                 piece: Piece) -> MoveResult:
        """
        Move the pawn onto the last rank but deliberately leave the ply
        unfinished, because the player has not yet said what the pawn becomes.
        The history entry is appended with position_key_added left as None, and
        that None is the marker that a promotion is pending -- it keeps undo
        from unwinding state the ply never applied, and it is what promote()
        checks before it will finish anything

        :param from_sq: square the pawn starts on
        :param to_sq: last-rank square it moves to
        :param piece: the promoting pawn
        :returns: a legal result flagged as needing a promotion choice
        """
        captured = self.state[to_sq.row][to_sq.col]
        san = self._build_san(from_sq, to_sq, piece, captured)
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        move = Move(from_sq, to_sq, piece, captured=captured)
        entry = HistoryEntry(
            move=move,
            prev_castling_rights=tuple(self.castling_rights[k] for k in CASTLING_KEYS),
            prev_en_passant_target=self.en_passant_target,
            prev_halfmove_clock=self.halfmove_clock,
            position_key_added=None,
            san=san,
        )
        self.move_history.append(entry)
        return MoveResult(legal=True, captured=captured, promotion_required=True)

    def _record_and_finalize(self, move: Move, captured: Piece | None,
                             san: str) -> MoveResult:
        """
        Append a ply that landed whole to the history and settle everything it
        implies, the shared tail of every move except a pending promotion. The
        placeholder pre-ply fields written here are overwritten immediately by
        _finalize_move, which reads them off the live state instead

        :param move: the ply just applied to the board
        :param captured: piece taken by it, or None when nothing was
        :param san: notation built before the board changed
        :returns: the finished move's result
        """
        entry = HistoryEntry(
            move=move,
            prev_castling_rights=(),
            prev_en_passant_target=None,
            prev_halfmove_clock=0,
            position_key_added=None,
            san=san,
        )
        self.move_history.append(entry)
        self._finalize_move(entry)
        return self._build_move_result(captured)

    def _build_san(self, from_sq: Square, to_sq: Square, piece: Piece,
                   captured: Piece | None, is_en_passant: bool = False) -> str:
        """
        Build a move's notation from the board as it stands before the move is
        made, which is the only moment two identical pieces can be told apart.
        Check and mate suffixes are not added here -- _finalize_move appends
        them once the consequences are known -- and the PGN code never
        recomputes SAN afterwards, it only reads what was stored

        :param from_sq: square the piece starts on
        :param to_sq: square it moves to
        :param piece: piece being moved
        :param captured: piece being taken, or None; it decides the x
        :param is_en_passant: True for an en-passant capture, whose taken pawn
            does not stand on the destination square
        :returns: SAN for the move, without any check or mate suffix
        """
        target = f"{SAN_FILES[to_sq.col]}{self.SIZE - to_sq.row}"
        if piece.type == PieceType.PAWN:
            if captured is not None or is_en_passant:
                return f"{SAN_FILES[from_sq.col]}x{target}"
            return target
        disambig = self._san_disambiguation(from_sq, to_sq, piece)
        capture = "x" if captured is not None else ""
        return f"{SAN_PIECE_LETTER[piece.type]}{disambig}{capture}{target}"

    def _san_disambiguation(self, from_sq: Square, to_sq: Square, piece: Piece) -> str:
        """
        Work out the extra file or rank a move needs when another piece of the
        same kind could legally reach the same square, which is what tells two
        knights or two rooks apart in the move list. File alone is preferred,
        then rank alone, and both only when neither settles it

        :param from_sq: square of the piece that is actually moving
        :param to_sq: square being moved to
        :param piece: piece being moved, whose kind and side define its rivals
        :returns: the disambiguating fragment, empty when none is needed
        """
        rivals: list[Square] = []
        for r, c in product(range(self.SIZE), repeat=2):
            if r == from_sq.row and c == from_sq.col:
                continue
            other = self.state[r][c]
            if other is None or other.type != piece.type or other.color != piece.color:
                continue
            if to_sq in self.legal_moves_from(Square(r, c)):
                rivals.append(Square(r, c))
        if not rivals:
            return ""
        if all(rv.col != from_sq.col for rv in rivals):
            return SAN_FILES[from_sq.col]
        if all(rv.row != from_sq.row for rv in rivals):
            return str(self.SIZE - from_sq.row)
        return f"{SAN_FILES[from_sq.col]}{self.SIZE - from_sq.row}"

    def _finalize_move(self, entry: HistoryEntry) -> None:
        """
        Settle everything that follows from a ply that has landed, and the only
        place any of it happens: the pre-ply state is stamped onto the history
        entry so undo can rewind, castling rights and the en-passant target are
        updated, the halfmove clock advances or resets, the turn changes, the
        new position is counted towards repetition, the SAN gains its + or #,
        and the clock is charged and handed over or stopped. It runs exactly
        once per completed ply -- from try_move for a move that lands whole, or
        from promote() for one that waited on a piece choice, never from both --
        because counting a position twice would invent a repetition

        :param entry: history entry for the ply that just landed; its pre-ply
            fields, key, check flags and SAN suffix are all filled in here
        """
        entry.prev_castling_rights = tuple(self.castling_rights[k] for k in CASTLING_KEYS)
        entry.prev_en_passant_target = self.en_passant_target
        entry.prev_halfmove_clock = self.halfmove_clock
        entry.prev_clock_snapshot = self.clock.snapshot() if self.clock is not None else None

        m = entry.move

        if m.piece.type == PieceType.KING:
            prefix = "W" if m.piece.color == PieceColor.WHITE else "B"
            self.castling_rights[prefix + "K"] = False
            self.castling_rights[prefix + "Q"] = False
        for sq in (m.from_sq, m.to_sq):
            if sq == Square(7, 0):
                self.castling_rights["WQ"] = False
            elif sq == Square(7, 7):
                self.castling_rights["WK"] = False
            elif sq == Square(0, 0):
                self.castling_rights["BQ"] = False
            elif sq == Square(0, 7):
                self.castling_rights["BK"] = False

        if m.piece.type == PieceType.PAWN and abs(m.to_sq.row - m.from_sq.row) == 2:
            self.en_passant_target = Square(
                (m.from_sq.row + m.to_sq.row) // 2, m.from_sq.col,
            )
        else:
            self.en_passant_target = None

        if m.piece.type == PieceType.PAWN or m.captured is not None:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        mover = m.piece.color
        self._switch_turn()
        key = self._position_key()
        self.position_counts[key] += 1
        entry.position_key_added = key
        in_check = self.is_in_check(self.turn)
        no_moves = self._has_no_legal_moves(self.turn)
        self._legal_move_memo = (len(self.move_history), no_moves)
        entry.gives_checkmate = in_check and no_moves
        entry.gives_check = in_check and not no_moves
        if entry.gives_checkmate:
            entry.san += "#"
        elif entry.gives_check:
            entry.san += "+"

        if self.clock is not None:
            if entry.gives_checkmate or no_moves:
                self.clock.stop()
            else:
                self.clock.on_move_made(mover)

    def _build_move_result(self, captured: Piece | None) -> MoveResult:
        """
        Package what a caller needs to know once a ply has landed: what it took,
        and whether the side now to move is in check, mated or stalemated. It is
        read after the turn has already changed, so the flags describe the
        player who has to answer the move, not the one who made it

        :param captured: piece the move took, or None when it took nothing
        :returns: the move result handed back to the UI and the server
        """
        result = self.game_result()
        is_check = self.is_in_check(self.turn)
        return MoveResult(
            legal=True,
            captured=captured,
            is_check=is_check,
            is_checkmate=result in ("white_wins", "black_wins"),
            is_stalemate=result == "draw_stalemate",
        )

    def _position_key(self) -> PositionKey:
        """
        Reduce the position to the key threefold repetition is counted by: the
        pieces on the board, the side to move, the four castling rights and the
        en-passant target. That target is always part of the key, even when no
        pawn could actually capture en passant -- a deliberate simplification of
        the FIDE rule, and one the tests pin down

        :returns: hashable key standing for this position
        """
        board = tuple(
            tuple((p.type, p.color) if p is not None else None for p in row)
            for row in self.state
        )
        rights = tuple(self.castling_rights[k] for k in CASTLING_KEYS)
        return (board, self.turn, rights, self.en_passant_target)

    def _pseudo_legal_moves(self, square: Square) -> list[Square]:
        """
        List where a piece could move given its own rule and what stands on the
        board, but without asking whether its own king would be left in check.
        A king's castling destinations are generated here too, and
        legal_moves_from is what filters the result down to what is really legal

        :param square: square the piece stands on
        :returns: candidate destination squares, empty when the square is empty
        """
        piece = self.state[square.row][square.col]
        if piece is None:
            return []

        if piece.type == PieceType.KNIGHT:
            return self._knight_and_king_moves(square, piece, KNIGHT_OFFSETS)

        if piece.type == PieceType.KING:
            moves = self._knight_and_king_moves(square, piece, KING_OFFSETS)
            moves.extend(self._castling_moves(square, piece))
            return moves

        if piece.type == PieceType.BISHOP:
            return self._sliding_moves(square, piece, BISHOP_DIRECTIONS)

        if piece.type == PieceType.ROOK:
            return self._sliding_moves(square, piece, ROOK_DIRECTIONS)

        if piece.type == PieceType.QUEEN:
            return self._sliding_moves(square, piece, QUEEN_DIRECTIONS)

        if piece.type == PieceType.PAWN:
            return self._pawn_moves(square, piece)

        return []

    def _has_no_legal_moves(self, color: PieceColor) -> bool:
        """
        Say whether a side has no legal move at all, which paired with
        is_in_check is what separates checkmate from stalemate. It also keeps
        the clock from running on in a position that is already finished

        :param color: side being tested
        :returns: True when that side cannot make a single legal move
        """
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.state[row][col]
            if piece is None or piece.color != color:
                continue
            if self.legal_moves_from(Square(row, col)):
                return False
        return True

    def _side_to_move_has_no_legal_moves(self) -> bool:
        """
        Answer the same question as _has_no_legal_moves for the side to move,
        but from the verdict already reached for this position where there is
        one. The whole-board scan is far too heavy to repeat once a frame, and
        the clock asks exactly that often; every ply that lands leaves its own
        verdict here, and the plies played so far is what tells one position's
        answer from another's

        :returns: True when the side to move cannot make a single legal move
        """
        plies = len(self.move_history)
        if self._legal_move_memo is not None and self._legal_move_memo[0] == plies:
            return self._legal_move_memo[1]
        stuck = self._has_no_legal_moves(self.turn)
        self._legal_move_memo = (plies, stuck)
        return stuck

    def _knight_and_king_moves(self, square: Square, piece: Piece,
                               offsets: list[tuple[int, int]]) -> list[Square]:
        """
        Generate the moves of a piece that steps by fixed offsets -- the knight
        and the king -- keeping the steps that stay on the board and do not land
        on a friendly piece. Castling is not part of this and is added
        separately

        :param square: square the piece stands on
        :param piece: piece being moved, whose side says what is friendly
        :param offsets: row and column steps to try, as (row delta, col delta)
        :returns: squares the piece may step to
        """
        moves = []

        for dr, dc in offsets:
            target = Square(square.row + dr, square.col + dc)
            if not on_board(target):
                continue

            target_piece = self.state[target.row][target.col]
            if target_piece is not None and target_piece.color == piece.color:
                continue

            moves.append(target)

        return moves

    def _sliding_moves(self, square: Square, piece: Piece,
                       directions: list[tuple[int, int]]) -> list[Square]:
        """
        Generate the moves of a piece that slides -- bishop, rook and queen --
        walking each direction until the edge of the board, a friendly piece or
        a capture stops it. The captured square is included, anything past it is
        not

        :param square: square the piece stands on
        :param piece: piece being moved, whose side decides what blocks it
        :param directions: one (row delta, col delta) step per direction to walk
        :returns: squares the piece may slide to
        """
        moves = []

        for dr, dc in directions:
            row, col = square.row + dr, square.col + dc

            while 0 <= row < self.SIZE and 0 <= col < self.SIZE:
                target_piece = self.state[row][col]

                if target_piece is None:
                    moves.append(Square(row, col))

                elif target_piece.color != piece.color:
                    moves.append(Square(row, col))
                    break

                else:
                    break

                row += dr
                col += dc

        return moves

    def _pawn_moves(self, square: Square, piece: Piece) -> list[Square]:
        """
        Generate a pawn's moves: one square forward, two from its own starting
        rank when both squares ahead are clear, a diagonal capture, and the
        en-passant capture when the current target sits on that diagonal.
        Promotion is not decided here -- reaching the last rank is noticed when
        the move is applied

        :param square: square the pawn stands on
        :param piece: the pawn, whose side sets which way it marches
        :returns: squares the pawn may move to
        """
        moves = []

        direction = pawn_forward(piece.color)
        start_row = pawn_start_row(piece.color)

        one_ahead = Square(square.row + direction, square.col)
        if on_board(one_ahead) and self.state[one_ahead.row][one_ahead.col] is None:
            moves.append(one_ahead)

            if square.row == start_row:
                two_ahead = Square(square.row + 2 * direction, square.col)
                if self.state[two_ahead.row][two_ahead.col] is None:
                    moves.append(two_ahead)

        for diag_col in (-1, 1):
            target = Square(square.row + direction, square.col + diag_col)
            if not on_board(target):
                continue

            target_piece = self.state[target.row][target.col]
            if target_piece is not None and target_piece.color != piece.color:
                moves.append(target)
            elif (target_piece is None
                    and self.en_passant_target is not None
                    and target == self.en_passant_target):
                moves.append(target)

        return moves

    def _castling_moves(self, square: Square, piece: Piece) -> list[Square]:
        """
        Generate a king's castling destinations, which are offered only while
        the right survives, the king still stands on its home square, the
        squares between king and rook are empty, and neither the king's square
        nor the ones it crosses are attacked. The crossing squares are tested
        with _is_square_attacked rather than by generating the opponent's
        replies, which is what stops the check test recursing back into here

        :param square: square the king stands on
        :param piece: the king being moved
        :returns: castling destinations, empty when neither castle is available
        """
        if piece.type != PieceType.KING:
            return []
        home_row = king_home_row(piece.color)
        if square != Square(home_row, 4):
            return []
        if self.is_in_check(piece.color):
            return []

        opponent = opponent_of(piece.color)
        prefix = "W" if piece.color == PieceColor.WHITE else "B"
        moves = []

        if self.castling_rights[prefix + "K"]:
            if (self.state[home_row][5] is None
                    and self.state[home_row][6] is None
                    and not self._is_square_attacked(Square(home_row, 5), opponent)
                    and not self._is_square_attacked(Square(home_row, 6), opponent)):
                moves.append(Square(home_row, 6))

        if self.castling_rights[prefix + "Q"]:
            if (self.state[home_row][1] is None
                    and self.state[home_row][2] is None
                    and self.state[home_row][3] is None
                    and not self._is_square_attacked(Square(home_row, 3), opponent)
                    and not self._is_square_attacked(Square(home_row, 2), opponent)):
                moves.append(Square(home_row, 2))

        return moves

    def _is_castling_move(self, from_sq: Square, to_sq: Square, piece: Piece) -> bool:
        """
        Recognise a king stepping two files from its home square as a castle, so
        try_move sends it to the handler that also moves the rook. Whether the
        castle is allowed was already settled by move generation

        :param from_sq: square the piece starts on
        :param to_sq: square it is moving to
        :param piece: piece being moved
        :returns: True when this move is a castle
        """
        if piece.type != PieceType.KING:
            return False
        home_row = king_home_row(piece.color)
        if from_sq != Square(home_row, 4):
            return False
        return abs(to_sq.col - from_sq.col) == 2

    def _is_en_passant_move(self, from_sq: Square, to_sq: Square, piece: Piece) -> bool:
        """
        Recognise a pawn stepping diagonally onto the live en-passant target as
        an en-passant capture, so it goes to the handler that also lifts the
        pawn standing beside it

        :param from_sq: square the piece starts on
        :param to_sq: square it is moving to
        :param piece: piece being moved
        :returns: True when this move is an en-passant capture
        """
        return (
            piece.type == PieceType.PAWN
            and self.en_passant_target is not None
            and to_sq == self.en_passant_target
            and to_sq.col != from_sq.col
        )

    def _has_insufficient_material(self) -> bool:
        """
        Say whether too little material is left for anyone to mate, which draws
        the game. Bare kings, a lone minor piece and one bishop each on
        same-coloured squares all count, and so do knight against knight and two
        knights against a bare king -- those last two are deliberate departures
        from FIDE, which only calls a position dead when mate is truly
        impossible. Two bishops against a bare king are treated as sufficient

        :returns: True when the position is drawn for want of material
        """
        non_kings: list[Piece] = []
        bishops: list[tuple[int, int, Piece]] = []
        by_color: dict[PieceColor, list[Piece]] = {PieceColor.WHITE: [], PieceColor.BLACK: []}
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.state[row][col]
            if piece is None or piece.type == PieceType.KING:
                continue
            non_kings.append(piece)
            by_color[piece.color].append(piece)
            if piece.type == PieceType.BISHOP:
                bishops.append((row, col, piece))

        if not non_kings:
            return True
        if len(non_kings) == 1 and non_kings[0].type in (PieceType.BISHOP, PieceType.KNIGHT):
            return True
        if len(non_kings) == 2:
            white, black = by_color[PieceColor.WHITE], by_color[PieceColor.BLACK]
            if (len(white) == 1 and len(black) == 1
                    and white[0].type == PieceType.KNIGHT
                    and black[0].type == PieceType.KNIGHT):
                return True
            for side in (white, black):
                if len(side) == 2 and all(p.type == PieceType.KNIGHT for p in side):
                    return True
            if len(bishops) == 2:
                bishop_a, bishop_b = bishops
                if bishop_a[2].color != bishop_b[2].color:
                    square_color_a = (bishop_a[0] + bishop_a[1]) % 2
                    square_color_b = (bishop_b[0] + bishop_b[1]) % 2
                    if square_color_a == square_color_b:
                        return True
        return False

    def _is_square_attacked(self, square: Square, by_color: PieceColor) -> bool:
        """
        Say whether a side attacks a given square, the test behind check
        detection and behind the squares a king may not castle across. Pawn and
        king attackers are matched by their own geometry instead of by
        generating their moves, and that special case is a deliberate recursion
        guard: a king's move generation asks about castling, which asks this
        question again -- do not simplify it away

        :param square: square being tested; it need not hold a piece
        :param by_color: side whose attacks are being looked for
        :returns: True when any piece of that side attacks the square
        """
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.state[row][col]
            if piece is None or piece.color != by_color:
                continue

            if piece.type == PieceType.PAWN:
                direction = pawn_forward(by_color)
                for diag_col in (-1, 1):
                    if row + direction == square.row and col + diag_col == square.col:
                        return True
                continue

            if piece.type == PieceType.KING:
                for dr, dc in KING_OFFSETS:
                    if row + dr == square.row and col + dc == square.col:
                        return True
                continue

            attacker_sq = Square(row, col)
            if square in self._pseudo_legal_moves(attacker_sq):
                return True

        return False

    def _would_leave_king_in_check(self, from_sq: Square, to_sq: Square) -> bool:
        """
        Try a move on the real board, ask whether the mover's own king ends up
        attacked, then put everything back; this is the filter that turns
        pseudo-legal moves into legal ones. The board is restored in a finally
        block, the en-passant victim included, so nothing can leave the position
        corrupted part-way through

        :param from_sq: square the piece starts on
        :param to_sq: square it would move to
        :returns: True when the move would leave the mover's own king in check
        """
        piece = self.state[from_sq.row][from_sq.col]
        if piece is None:
            return False

        captured = self.state[to_sq.row][to_sq.col]

        ep = (
            piece.type == PieceType.PAWN
            and self.en_passant_target is not None
            and to_sq == self.en_passant_target
            and from_sq.col != to_sq.col
            and captured is None
        )
        ep_sq = Square(from_sq.row, to_sq.col) if ep else None
        ep_piece = self.state[ep_sq.row][ep_sq.col] if ep_sq is not None else None

        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        if ep_sq is not None:
            self.state[ep_sq.row][ep_sq.col] = None

        try:
            king_sq = self._find_king(piece.color)
            in_check = self._is_square_attacked(king_sq, opponent_of(piece.color))
        finally:
            self.state[from_sq.row][from_sq.col] = piece
            self.state[to_sq.row][to_sq.col] = captured
            if ep_sq is not None:
                self.state[ep_sq.row][ep_sq.col] = ep_piece

        return in_check

    def _find_king(self, color: PieceColor) -> Square:
        """
        Locate a side's king, which every check test needs before it can ask
        whether that square is attacked. The search itself is the shared one
        over a plain board grid; what this adds is the engine's stricter
        reading of a missing king -- a live position without one is broken, so
        it raises rather than quietly reporting an all-clear

        :param color: side whose king is wanted
        :returns: the square that king stands on
        """
        square = king_square(self.state, color)
        if square is None:
            raise ValueError(f"No {color} king on the board")
        return square

    def _switch_turn(self) -> None:
        """
        Hand the move to the other side, done once when a ply completes and once
        more when one is taken back. It is the only place the turn ever changes,
        so it cannot drift out of step with the move history
        """
        self.turn = opponent_of(self.turn)
