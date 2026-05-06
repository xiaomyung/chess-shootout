from pieces.pieces import PieceType, PieceColor, Piece, BACK_RANK
from backend.utils import Move, MoveResult, Square


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

    def new_game(self):
        self.state = [[None] * self.SIZE for _ in range(self.SIZE)]
        self.turn = PieceColor.WHITE
        self.move_history = []

        for col, piece_type in enumerate(BACK_RANK):
            self.state[0][col] = Piece(piece_type, PieceColor.BLACK)
            self.state[1][col] = Piece(PieceType.PAWN, PieceColor.BLACK)
            self.state[6][col] = Piece(PieceType.PAWN, PieceColor.WHITE)
            self.state[7][col] = Piece(piece_type, PieceColor.WHITE)

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
        return self._has_no_legal_moves(self.turn)

    def game_result(self):
        if not self._has_no_legal_moves(self.turn):
            return None
        if self.is_in_check(self.turn):
            return 'black_wins' if self.turn == PieceColor.WHITE else 'white_wins'
        return 'draw'

    def try_move(self, from_sq, to_sq):
        piece = self.state[from_sq.row][from_sq.col]
        if piece is None:
            return MoveResult(legal=False)
        if piece.color != self.turn:
            return MoveResult(legal=False)
        if to_sq not in self.legal_moves_from(from_sq):
            return MoveResult(legal=False)

        captured = self.state[to_sq.row][to_sq.col]
        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None
        self.move_history.append(Move(from_sq, to_sq, piece, captured=captured))

        if self._is_promotion(piece, to_sq):
            return MoveResult(legal=True, captured=captured, promotion_required=True)

        self._switch_turn()

        is_check = self.is_in_check(self.turn)
        no_moves = self._has_no_legal_moves(self.turn)
        is_checkmate = is_check and no_moves
        is_stalemate = (not is_check) and no_moves

        return MoveResult(
            legal=True,
            captured=captured,
            is_check=is_check,
            is_checkmate=is_checkmate,
            is_stalemate=is_stalemate,
        )

    def _is_promotion(self, piece, to_sq):
        if piece.type != PieceType.PAWN:
            return False
        if piece.color == PieceColor.WHITE and to_sq.row == 0:
            return True
        if piece.color == PieceColor.BLACK and to_sq.row == 7:
            return True
        return False

    def promote(self, square, piece_type):
        if piece_type not in (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT):
            raise ValueError(f"Cannot promote to {piece_type}")

        piece = self.state[square.row][square.col]
        if piece is None or piece.type != PieceType.PAWN:
            raise ValueError(f"No pawn at {square} to promote")

        self.state[square.row][square.col] = Piece(piece_type, piece.color)

        last_move = self.move_history[-1]
        self.move_history[-1] = Move(
            from_sq=last_move.from_sq,
            to_sq=last_move.to_sq,
            piece=last_move.piece,
            captured=last_move.captured,
            is_castle=last_move.is_castle,
            is_en_passant=last_move.is_en_passant,
            promoted_to=piece_type,
        )

        self._switch_turn()
        is_check = self.is_in_check(self.turn)
        no_moves = self._has_no_legal_moves(self.turn)

        return MoveResult(
            legal=True,
            is_check=is_check,
            is_checkmate=is_check and no_moves,
            is_stalemate=(not is_check) and no_moves,
        )

    def undo(self):
        pass

    def _pseudo_legal_moves(self, square):
        piece = self.state[square.row][square.col]
        if piece is None:
            return []

        if piece.type == PieceType.KNIGHT:
            return self._knight_and_king_moves(square, piece, self.KNIGHT_OFFSETS)

        if piece.type == PieceType.KING:
            return self._knight_and_king_moves(square, piece, self.KING_OFFSETS)

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

        return moves

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

                attacker_sq = Square(row, col)
                if square in self._pseudo_legal_moves(attacker_sq):
                    return True

        return False

    def _would_leave_king_in_check(self, from_sq, to_sq):
        piece = self.state[from_sq.row][from_sq.col]
        if piece is None:
            return False

        captured = self.state[to_sq.row][to_sq.col]

        self.state[to_sq.row][to_sq.col] = piece
        self.state[from_sq.row][from_sq.col] = None

        try:
            king_sq = self._find_king(piece.color)
            opponent = PieceColor.BLACK if piece.color == PieceColor.WHITE else PieceColor.WHITE
            in_check = self._is_square_attacked(king_sq, opponent)
        finally:
            self.state[from_sq.row][from_sq.col] = piece
            self.state[to_sq.row][to_sq.col] = captured

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

    def _apply_move(self, move):
        pass

    def _in_bounds(self, square):
        return 0 <= square.row < self.SIZE and 0 <= square.col < self.SIZE