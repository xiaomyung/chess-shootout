from collections import Counter

from pieces.pieces import PieceType, PieceColor, Piece, BACK_RANK
from backend.utils import Move, MoveResult, Square, HistoryEntry


class Backend:
    SIZE = 8

    KNIGHT_OFFSETS = [
        (-2, -1), (-2, 1), (-1, -2), (-1, 2),
        (1, -2), (1, 2), (2, -1), (2, 1)
    ]

    KING_OFFSETS = [
        (-1, -1), (-1, 0), (-1, 1), (0, -1),
        (0, 1), (1, -1), (1, 0), (1, 1)
    ]

    BISHOP_DIRECTIONS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    ROOK_DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    QUEEN_DIRECTIONS = BISHOP_DIRECTIONS + ROOK_DIRECTIONS

    def __init__(self):
        self.state = [[None] * self.SIZE for _ in range(self.SIZE)]
        self.turn = PieceColor.WHITE
        self.move_history = []
        self.en_passant_target = None
        self.castling_rights = {'WK': True, 'WQ': True, 'BK': True, 'BQ': True}
        self.halfmove_clock = 0
        self.position_counts = Counter()

    def new_game(self):
        self.state = [[None] * self.SIZE for _ in range(self.SIZE)]
        self.turn = PieceColor.WHITE
        self.move_history = []
        self.en_passant_target = None
        self.castling_rights = {'WK': True, 'WQ': True, 'BK': True, 'BQ': True}
        self.halfmove_clock = 0
        self.position_counts = Counter()

        for col, piece_type in enumerate(BACK_RANK):
            self.state[0][col] = Piece(piece_type, PieceColor.BLACK)
            self.state[1][col] = Piece(PieceType.PAWN, PieceColor.BLACK)
            self.state[6][col] = Piece(PieceType.PAWN, PieceColor.WHITE)
            self.state[7][col] = Piece(piece_type, PieceColor.WHITE)

        self.position_counts[self._position_key()] = 1

    def piece_at(self, square):
        return self.state[square.row][square.col]

    def current_turn(self):
        return self.turn

    def legal_moves_from(self, square):
        return [
            to_sq for to_sq in self._pseudo_legal_moves(square)
            if not self._would_leave_king_in_check(square, to_sq)
        ]

    def is_in_check(self, color):
        king_sq = self._find_king(color)
        opponent = PieceColor.BLACK if color == PieceColor.WHITE else PieceColor.WHITE
        return self._is_square_attacked(king_sq, opponent)

    def is_game_over(self):
        return self.game_result() is not None

    def game_result(self):
        if self._has_no_legal_moves(self.turn):
            if self.is_in_check(self.turn):
                return 'black_wins' if self.turn == PieceColor.WHITE else 'white_wins'
            return 'draw_stalemate'
        if self._has_insufficient_material():
            return 'draw_insufficient_material'
        if self.position_counts and max(self.position_counts.values()) >= 3:
            return 'draw_repetition'
        if self.halfmove_clock >= 100:
            return 'draw_fifty_move'
        return None

    def try_move(self, from_sq, to_sq):
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

    def promote(self, square, piece_type):
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
        self._finalize_move(entry)
        return self._build_move_result(entry.move.captured)

    def undo(self):
        if not self.move_history:
            return
        entry = self.move_history.pop()
        m = entry.move

        if entry.position_key_added is not None:
            self.position_counts[entry.position_key_added] -= 1
            if self.position_counts[entry.position_key_added] == 0:
                del self.position_counts[entry.position_key_added]
            self.castling_rights = dict(zip(
                ('WK', 'WQ', 'BK', 'BQ'),
                entry.prev_castling_rights,
            ))
            self.en_passant_target = entry.prev_en_passant_target
            self.halfmove_clock = entry.prev_halfmove_clock
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

    def _apply_normal(self, from_sq, to_sq, piece):
        captured = self.state[to_sq.row][to_sq.col]
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        move = Move(from_sq, to_sq, piece, captured=captured)
        return self._record_and_finalize(move, captured)

    def _apply_castle(self, from_sq, to_sq, piece):
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        if to_sq.col == 6:
            rook_from_col, rook_to_col = 7, 5
        else:
            rook_from_col, rook_to_col = 0, 3
        self.state[from_sq.row][rook_to_col] = self.state[from_sq.row][rook_from_col]
        self.state[from_sq.row][rook_from_col] = None
        move = Move(from_sq, to_sq, piece, is_castle=True)
        return self._record_and_finalize(move, None)

    def _apply_en_passant(self, from_sq, to_sq, piece):
        captured_sq = Square(from_sq.row, to_sq.col)
        captured = self.state[captured_sq.row][captured_sq.col]
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        self.state[captured_sq.row][captured_sq.col] = None
        move = Move(from_sq, to_sq, piece, captured=captured, is_en_passant=True)
        return self._record_and_finalize(move, captured)

    def _apply_promotion_pending(self, from_sq, to_sq, piece):
        captured = self.state[to_sq.row][to_sq.col]
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        move = Move(from_sq, to_sq, piece, captured=captured)
        entry = HistoryEntry(
            move=move,
            prev_castling_rights=tuple(self.castling_rights.values()),
            prev_en_passant_target=self.en_passant_target,
            prev_halfmove_clock=self.halfmove_clock,
            position_key_added=None,
        )
        self.move_history.append(entry)
        return MoveResult(legal=True, captured=captured, promotion_required=True)

    def _record_and_finalize(self, move, captured):
        entry = HistoryEntry(
            move=move,
            prev_castling_rights=(),
            prev_en_passant_target=None,
            prev_halfmove_clock=0,
            position_key_added=None,
        )
        self.move_history.append(entry)
        self._finalize_move(entry)
        return self._build_move_result(captured)

    def _finalize_move(self, entry):
        entry.prev_castling_rights = (
            self.castling_rights['WK'], self.castling_rights['WQ'],
            self.castling_rights['BK'], self.castling_rights['BQ'],
        )
        entry.prev_en_passant_target = self.en_passant_target
        entry.prev_halfmove_clock = self.halfmove_clock

        m = entry.move

        if m.piece.type == PieceType.KING:
            if m.piece.color == PieceColor.WHITE:
                self.castling_rights['WK'] = False
                self.castling_rights['WQ'] = False
            else:
                self.castling_rights['BK'] = False
                self.castling_rights['BQ'] = False
        for sq in (m.from_sq, m.to_sq):
            if sq == Square(7, 0):
                self.castling_rights['WQ'] = False
            elif sq == Square(7, 7):
                self.castling_rights['WK'] = False
            elif sq == Square(0, 0):
                self.castling_rights['BQ'] = False
            elif sq == Square(0, 7):
                self.castling_rights['BK'] = False

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

        self._switch_turn()
        key = self._position_key()
        self.position_counts[key] += 1
        entry.position_key_added = key

    def _build_move_result(self, captured):
        result = self.game_result()
        is_check = self.is_in_check(self.turn)
        return MoveResult(
            legal=True,
            captured=captured,
            is_check=is_check,
            is_checkmate=result in ('white_wins', 'black_wins'),
            is_stalemate=result == 'draw_stalemate',
        )

    def _position_key(self):
        board = tuple(
            tuple((p.type, p.color) if p is not None else None for p in row)
            for row in self.state
        )
        rights = (
            self.castling_rights['WK'], self.castling_rights['WQ'],
            self.castling_rights['BK'], self.castling_rights['BQ'],
        )
        return (board, self.turn, rights, self.en_passant_target)

    def _pseudo_legal_moves(self, square):
        piece = self.state[square.row][square.col]
        if piece is None:
            return []

        if piece.type == PieceType.KNIGHT:
            return self._knight_and_king_moves(square, piece, self.KNIGHT_OFFSETS)

        if piece.type == PieceType.KING:
            moves = self._knight_and_king_moves(square, piece, self.KING_OFFSETS)
            moves.extend(self._castling_moves(square, piece))
            return moves

        if piece.type == PieceType.BISHOP:
            return self._sliding_moves(square, piece, self.BISHOP_DIRECTIONS)

        if piece.type == PieceType.ROOK:
            return self._sliding_moves(square, piece, self.ROOK_DIRECTIONS)

        if piece.type == PieceType.QUEEN:
            return self._sliding_moves(square, piece, self.QUEEN_DIRECTIONS)

        if piece.type == PieceType.PAWN:
            return self._pawn_moves(square, piece)

        return []

    def _has_no_legal_moves(self, color):
        for row in range(self.SIZE):
            for col in range(self.SIZE):
                piece = self.state[row][col]
                if piece is None or piece.color != color:
                    continue
                if self.legal_moves_from(Square(row, col)):
                    return False
        return True

    def _knight_and_king_moves(self, square, piece, offsets):
        moves = []

        for dest_r, dest_c in offsets:
            target = Square(square.row + dest_r, square.col + dest_c)
            if not self._in_bounds(target):
                continue

            target_piece = self.state[target.row][target.col]
            if target_piece is not None and target_piece.color == piece.color:
                continue

            moves.append(target)

        return moves

    def _sliding_moves(self, square, piece, directions):
        moves = []

        for dest_r, dest_c in directions:
            row, col = square.row + dest_r, square.col + dest_c

            while 0 <= row < self.SIZE and 0 <= col < self.SIZE:
                target_piece = self.state[row][col]

                if target_piece is None:
                    moves.append(Square(row, col))

                elif target_piece.color != piece.color:
                    moves.append(Square(row, col))
                    break

                else:
                    break

                row += dest_r
                col += dest_c

        return moves

    def _pawn_moves(self, square, piece):
        moves = []

        direction = -1 if piece.color == PieceColor.WHITE else 1
        start_row = 6 if piece.color == PieceColor.WHITE else 1

        one_ahead = Square(square.row + direction, square.col)
        if self._in_bounds(one_ahead) and self.state[one_ahead.row][one_ahead.col] is None:
            moves.append(one_ahead)

            if square.row == start_row:
                two_ahead = Square(square.row + 2 * direction, square.col)
                if self.state[two_ahead.row][two_ahead.col] is None:
                    moves.append(two_ahead)

        for diag_col in (-1, 1):
            target = Square(square.row + direction, square.col + diag_col)
            if not self._in_bounds(target):
                continue

            target_piece = self.state[target.row][target.col]
            if target_piece is not None and target_piece.color != piece.color:
                moves.append(target)
            elif (target_piece is None
                    and self.en_passant_target is not None
                    and target == self.en_passant_target):
                moves.append(target)

        return moves

    def _castling_moves(self, square, piece):
        if piece.type != PieceType.KING:
            return []
        home_row = 7 if piece.color == PieceColor.WHITE else 0
        if square != Square(home_row, 4):
            return []
        if self.is_in_check(piece.color):
            return []

        opponent = PieceColor.BLACK if piece.color == PieceColor.WHITE else PieceColor.WHITE
        prefix = 'W' if piece.color == PieceColor.WHITE else 'B'
        moves = []

        if self.castling_rights[prefix + 'K']:
            if (self.state[home_row][5] is None
                    and self.state[home_row][6] is None
                    and not self._is_square_attacked(Square(home_row, 5), opponent)
                    and not self._is_square_attacked(Square(home_row, 6), opponent)):
                moves.append(Square(home_row, 6))

        if self.castling_rights[prefix + 'Q']:
            if (self.state[home_row][1] is None
                    and self.state[home_row][2] is None
                    and self.state[home_row][3] is None
                    and not self._is_square_attacked(Square(home_row, 3), opponent)
                    and not self._is_square_attacked(Square(home_row, 2), opponent)):
                moves.append(Square(home_row, 2))

        return moves

    def _is_castling_move(self, from_sq, to_sq, piece):
        if piece.type != PieceType.KING:
            return False
        home_row = 7 if piece.color == PieceColor.WHITE else 0
        if from_sq != Square(home_row, 4):
            return False
        return abs(to_sq.col - from_sq.col) == 2

    def _is_en_passant_move(self, from_sq, to_sq, piece):
        return (
            piece.type == PieceType.PAWN
            and self.en_passant_target is not None
            and to_sq == self.en_passant_target
            and to_sq.col != from_sq.col
        )

    def _has_insufficient_material(self):
        non_kings = []
        bishops = []
        for row in range(self.SIZE):
            for col in range(self.SIZE):
                piece = self.state[row][col]
                if piece is None or piece.type == PieceType.KING:
                    continue
                non_kings.append(piece)
                if piece.type == PieceType.BISHOP:
                    bishops.append((row, col, piece))

        if not non_kings:
            return True
        if len(non_kings) == 1 and non_kings[0].type in (PieceType.BISHOP, PieceType.KNIGHT):
            return True
        if len(non_kings) == 2 and len(bishops) == 2:
            b1, b2 = bishops
            if b1[2].color != b2[2].color:
                if (b1[0] + b1[1]) % 2 == (b2[0] + b2[1]) % 2:
                    return True
        return False

    def _is_square_attacked(self, square, by_color):
        for row in range(self.SIZE):
            for col in range(self.SIZE):
                piece = self.state[row][col]
                if piece is None or piece.color != by_color:
                    continue

                if piece.type == PieceType.PAWN:
                    direction = -1 if by_color == PieceColor.WHITE else 1
                    for diag_col in (-1, 1):
                        if row + direction == square.row and col + diag_col == square.col:
                            return True
                    continue

                if piece.type == PieceType.KING:
                    for dr, dc in self.KING_OFFSETS:
                        if row + dr == square.row and col + dc == square.col:
                            return True
                    continue

                attacker_sq = Square(row, col)
                if square in self._pseudo_legal_moves(attacker_sq):
                    return True

        return False

    def _would_leave_king_in_check(self, from_sq, to_sq):
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
        ep_piece = self.state[ep_sq.row][ep_sq.col] if ep else None

        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        if ep:
            self.state[ep_sq.row][ep_sq.col] = None

        try:
            king_sq = self._find_king(piece.color)
            opponent = PieceColor.BLACK if piece.color == PieceColor.WHITE else PieceColor.WHITE
            in_check = self._is_square_attacked(king_sq, opponent)
        finally:
            self.state[from_sq.row][from_sq.col] = piece
            self.state[to_sq.row][to_sq.col] = captured
            if ep:
                self.state[ep_sq.row][ep_sq.col] = ep_piece

        return in_check

    def _find_king(self, color):
        for row in range(self.SIZE):
            for col in range(self.SIZE):
                piece = self.state[row][col]
                if piece is not None and piece.type == PieceType.KING and piece.color == color:
                    return Square(row, col)
        raise ValueError(f"No {color} king on the board")

    def _switch_turn(self):
        self.turn = (
            PieceColor.BLACK if self.turn == PieceColor.WHITE else PieceColor.WHITE
        )

    def _in_bounds(self, square):
        return 0 <= square.row < self.SIZE and 0 <= square.col < self.SIZE
