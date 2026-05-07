import pygame as pg

from backend.utils import Square
from frontend.colors import Colors
from pieces.pieces import PieceType, PieceColor, Piece


class Board:
    SCREEN_FRACTION_X = 0.8
    OFFSET_FRACTION_X = 0.02
    TEXT_PADDING_FRACTION = 0.006
    SIZE = 8

    def __init__(self, window, backend):
        self.window = window
        self.backend = backend
        self.font = pg.font.SysFont("Arial", 18, bold=True)
        self.board_guides_font_factor = 50
        self.board_side_size = self.window.get_size()[0] * self.SCREEN_FRACTION_X

        self.cell_size = 0
        self.board_offset_x = 0
        self.board_offset_y = 0

        self.file_labels = "abcdefgh"
        self.file_labels_rendered = []
        self.rank_labels_rendered = []
        self.text_padding = 0

        self.piece_images_original = {}
        self.piece_images_scaled = {}
        self.selected_square = None
        self.pending_promotion_square = None

    def _render_text(self):
        self.file_labels_rendered = [
            self.font.render(self.file_labels[i], True, Colors.white)
            for i in range(self.SIZE)
        ]
        self.rank_labels_rendered = [
            self.font.render(str(i + 1), True, Colors.white)
            for i in range(self.SIZE)
        ]

    def _load_piece_images(self):
        for piece_color in PieceColor:
            for piece_type in PieceType:
                piece = Piece(piece_type, piece_color)
                self.piece_images_original[(piece_type, piece_color)] = pg.image.load(piece.img_path).convert_alpha()

    def _cell_rect(self, row, col):
        return pg.Rect(
            col * self.cell_size + self.board_offset_x,
            row * self.cell_size + self.board_offset_y,
            self.cell_size,
            self.cell_size
        )

    def _draw_promotion_picker(self):
        if self.pending_promotion_square is None:
            return

        sq = self.pending_promotion_square
        color = self.backend.piece_at(sq).color
        rect = self._cell_rect(sq.row, sq.col)

        options = [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]

        direction = 1 if color == PieceColor.WHITE else -1

        for i, piece_type in enumerate(options):
            cell_rect = pg.Rect(
                rect.left,
                rect.top + i * self.cell_size * direction,
                self.cell_size,
                self.cell_size,
            )
            pg.draw.rect(self.window, Colors.white, cell_rect)
            pg.draw.rect(self.window, Colors.dark_menu, cell_rect, 1)
            surface = self.piece_images_scaled[(piece_type, color)]
            self.window.blit(surface, cell_rect.topleft)

    def load_assets(self):
        self._render_text()
        self._load_piece_images()

    def rescale_pieces(self):
        if self.cell_size <= 0:
            return

        size = int(self.cell_size)
        self.piece_images_scaled = {
            k: pg.transform.smoothscale(surface, (size, size))
            for k, surface in self.piece_images_original.items()
        }

    def draw_cell(self, row, col):
        rect = self._cell_rect(row, col)
        color = Colors.white_tile if (row + col) % 2 == 0 else Colors.black_tile
        pg.draw.rect(self.window, color, rect)

    def _draw_vertical_guides(self):
        for row in range(self.SIZE):
            rect = self._cell_rect(row, 0)
            symbol = self.rank_labels_rendered[row]
            x = rect.left + self.text_padding
            y = rect.top + self.text_padding
            self.window.blit(symbol, (x, y))

    def _draw_horizontal_guides(self):
        bottom_row = self.SIZE - 1
        for col in range(self.SIZE):
            rect = self._cell_rect(bottom_row, col)
            symbol = self.file_labels_rendered[col]
            x = rect.right - symbol.get_width() - self.text_padding
            y = rect.bottom - symbol.get_height() - self.text_padding
            self.window.blit(symbol, (x, y))

    def draw_board(self):
        for row in range(self.SIZE):
            for col in range(self.SIZE):
                self.draw_cell(row, col)
        self._draw_vertical_guides()
        self._draw_horizontal_guides()
        self._draw_selection_highlight()
        self._draw_move_indicators()
        self.draw_pieces()
        self._draw_promotion_picker()

    def draw_pieces(self):
        for row in range(self.SIZE):
            for col in range(self.SIZE):
                piece = self.backend.piece_at(Square(row, col))
                if piece is None:
                    continue

                rect = self._cell_rect(row, col)
                surface = self.piece_images_scaled[(piece.type, piece.color)]
                self.window.blit(surface, rect.topleft)

    def _draw_move_indicators(self):
        if self.selected_square is None:
            return

        legal_moves = self.backend.legal_moves_from(self.selected_square)
        for target in legal_moves:
            rect = self._cell_rect(target.row, target.col)
            target_piece = self.backend.piece_at(target)

            if target_piece is None:
                self._draw_dot(rect)
            else:
                self._draw_capture_ring(rect)

    def _draw_dot(self, rect):
        radius = int(self.cell_size * 0.15)
        overlay = pg.Surface((self.cell_size, self.cell_size), pg.SRCALPHA)
        pg.draw.circle(
            overlay,
            Colors.move_indicator,
            (self.cell_size / 2, self.cell_size / 2),
            radius,
        )
        self.window.blit(overlay, rect.topleft)

    def _draw_capture_ring(self, rect):
        radius = int(self.cell_size * 0.45)
        thickness = max(int(self.cell_size * 0.08), 3)
        overlay = pg.Surface((self.cell_size, self.cell_size), pg.SRCALPHA)
        pg.draw.circle(
            overlay,
            Colors.move_indicator,
            (self.cell_size / 2, self.cell_size / 2),
            radius,
            thickness,
        )
        self.window.blit(overlay, rect.topleft)

    def set_rect(self, rect):
        self.board_offset_x = rect.x
        self.board_offset_y = rect.y
        self.board_side_size = rect.width
        self.cell_size = rect.width // self.SIZE
        self.text_padding = rect.width * self.TEXT_PADDING_FRACTION
        self.rescale_pieces()
        self._render_text()

    def cell_at(self, pos):
        x, y = pos
        col = int((x - self.board_offset_x) / self.cell_size)
        row = int((y - self.board_offset_y) / self.cell_size)
        if 0 <= col < self.SIZE and 0 <= row < self.SIZE:
            return Square(row, col)
        return None

    def handle_click(self, square):
        if self.pending_promotion_square is not None:
            self._handle_promotion_click(square)
            return

        if self.selected_square is None:
            self._try_select(square)
        elif square == self.selected_square:
            self.selected_square = None
        else:
            result = self.backend.try_move(self.selected_square, square)
            self.selected_square = None

            if result.legal and result.promotion_required:
                self.pending_promotion_square = square

    def _handle_promotion_click(self, clicked_sq):
        sq = self.pending_promotion_square
        color = self.backend.piece_at(sq).color
        options = [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]
        direction = 1 if color == PieceColor.WHITE else -1

        if clicked_sq.col != sq.col:
            return
        offset = (clicked_sq.row - sq.row) * direction
        if not (0 <= offset < len(options)):
            return

        chosen = options[offset]
        self.backend.promote(sq, chosen)
        self.pending_promotion_square = None

    def _try_select(self, square):
        piece = self.backend.piece_at(square)
        if piece is None:
            return

        if piece.color != self.backend.current_turn():
            return
        self.selected_square = square

    def _draw_selection_highlight(self):
        if self.selected_square is None:
            return

        rect = self._cell_rect(self.selected_square.row, self.selected_square.col)
        pg.draw.rect(self.window, Colors.selection_red, rect, 4)