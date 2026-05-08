import math
from itertools import product

import pygame as pg

from backend.utils import Square
from frontend.animation import PieceAnimation
from frontend.colors import Colors
from frontend.premoves import Premove, is_premove_shape_valid, speculative_board
from backend.pieces import PieceType, PieceColor, Piece


class Board:
    SCREEN_FRACTION_X = 0.8
    OFFSET_FRACTION_X = 0.02
    TEXT_PADDING_FRACTION = 0.006
    SIZE = 8

    def __init__(self, window, backend, move_landed_callback=None):
        self.window = window
        self.backend = backend
        self.move_landed_callback = move_landed_callback
        self.font = pg.font.SysFont("Arial", 18, bold=True)
        self.board_guides_font_factor = 50

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
        self.flipped = False
        self.animations = []
        self.animation_duration_ms = 180
        self.last_animation_completed_at_ms = 0
        self.premoves = []
        self.premove_color = None
        self.highlighted_squares = set()
        self.arrows = []
        self._right_drag_start_square = None

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
        if self.flipped:
            row = self.SIZE - 1 - row
            col = self.SIZE - 1 - col
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

        options = [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]

        direction = 1 if color == PieceColor.WHITE else -1

        for i, piece_type in enumerate(options):
            cell_rect = self._cell_rect(sq.row + i * direction, sq.col)
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
        for row, col in product(range(self.SIZE), repeat=2):
            self.draw_cell(row, col)
        self._draw_check_highlight()
        self._draw_premove_highlights()
        self._draw_annotation_highlights()
        self._draw_vertical_guides()
        self._draw_horizontal_guides()
        self._draw_selection_highlight()
        self._draw_move_indicators()
        self.draw_pieces()
        self._draw_animations()
        self._draw_arrows()
        self._draw_drag_preview_arrow()
        self._draw_promotion_picker()

    def _draw_premove_highlights(self):
        if not self.premoves:
            return
        seen = set()
        for pm in self.premoves:
            for sq in (pm.from_sq, pm.to_sq):
                if sq in seen:
                    continue
                seen.add(sq)
                rect = self._cell_rect(sq.row, sq.col)
                overlay = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
                overlay.fill(Colors.premove)
                self.window.blit(overlay, rect.topleft)

    def toggle_highlight(self, sq):
        if sq in self.highlighted_squares:
            self.highlighted_squares.remove(sq)
        else:
            self.highlighted_squares.add(sq)

    def toggle_arrow(self, from_sq, to_sq):
        arrow = (from_sq, to_sq)
        if arrow in self.arrows:
            self.arrows.remove(arrow)
        else:
            self.arrows.append(arrow)

    def is_square_annotated(self, sq):
        if sq in self.highlighted_squares:
            return True
        for from_sq, to_sq in self.arrows:
            if sq == from_sq or sq == to_sq:
                return True
        return False

    def clear_annotations(self):
        self.highlighted_squares = set()
        self.arrows = []
        self._right_drag_start_square = None

    def _draw_annotation_highlights(self):
        for sq in self.highlighted_squares:
            rect = self._cell_rect(sq.row, sq.col)
            overlay = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
            overlay.fill(Colors.annotation_highlight)
            self.window.blit(overlay, rect.topleft)

    def _draw_arrows(self):
        for from_sq, to_sq in self.arrows:
            self._render_arrow(from_sq, to_sq, Colors.annotation_arrow)

    def _draw_drag_preview_arrow(self):
        if self._right_drag_start_square is None:
            return
        end_sq = self.cell_at(pg.mouse.get_pos())
        if end_sq is None or end_sq == self._right_drag_start_square:
            return
        self._render_arrow(self._right_drag_start_square, end_sq,
                           Colors.annotation_arrow_preview)

    def _render_arrow(self, from_sq, to_sq, color):
        if self.cell_size <= 0:
            return
        from_rect = self._cell_rect(from_sq.row, from_sq.col)
        to_rect = self._cell_rect(to_sq.row, to_sq.col)
        from_pos = (from_rect.centerx, from_rect.centery)
        to_pos = (to_rect.centerx, to_rect.centery)
        width = max(int(self.cell_size * 0.18), 4)
        head_size = max(int(self.cell_size * 0.35), 8)

        angle = math.atan2(to_pos[1] - from_pos[1], to_pos[0] - from_pos[0])
        shaft_end = (
            to_pos[0] - head_size * 0.55 * math.cos(angle),
            to_pos[1] - head_size * 0.55 * math.sin(angle),
        )
        head_half = math.radians(150)
        head_left = (
            to_pos[0] + head_size * math.cos(angle + head_half),
            to_pos[1] + head_size * math.sin(angle + head_half),
        )
        head_right = (
            to_pos[0] + head_size * math.cos(angle - head_half),
            to_pos[1] + head_size * math.sin(angle - head_half),
        )

        surface_size = self.window.get_size()
        overlay = pg.Surface(surface_size, pg.SRCALPHA)
        pg.draw.line(overlay, color, from_pos, shaft_end, width)
        pg.draw.polygon(overlay, color, [to_pos, head_left, head_right])
        self.window.blit(overlay, (0, 0))

    def _draw_check_highlight(self):
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.backend.piece_at(Square(row, col))
            if piece is None or piece.type != PieceType.KING:
                continue
            if self.backend.is_in_check(piece.color):
                rect = self._cell_rect(row, col)
                pg.draw.rect(self.window, Colors.selection_red, rect)

    def draw_pieces(self):
        hidden = {a.to_sq for a in self.animations}
        for row, col in product(range(self.SIZE), repeat=2):
            sq = Square(row, col)
            if sq in hidden:
                continue
            piece = self.backend.piece_at(sq)
            if piece is None:
                continue

            rect = self._cell_rect(row, col)
            surface = self.piece_images_scaled[(piece.type, piece.color)]
            self.window.blit(surface, rect.topleft)

    def _draw_animations(self):
        if not self.animations:
            return
        now = pg.time.get_ticks()
        completed = []
        for a in self.animations:
            progress = a.progress(now)
            fr = self._cell_rect(a.from_sq.row, a.from_sq.col)
            to = self._cell_rect(a.to_sq.row, a.to_sq.col)
            x = fr.x + (to.x - fr.x) * progress
            y = fr.y + (to.y - fr.y) * progress
            surface = self.piece_images_scaled[(a.piece.type, a.piece.color)]
            self.window.blit(surface, (x, y))
            if a.is_done(now):
                completed.append(a)
        for a in completed:
            self.animations.remove(a)
        if completed and not self.animations:
            self.last_animation_completed_at_ms = now
        for a in completed:
            if a.on_complete is not None:
                a.on_complete()

    def is_animating(self):
        return bool(self.animations)

    def start_animation(self, from_sq, to_sq, piece, on_complete=None):
        self.animations.append(PieceAnimation(
            from_sq=from_sq,
            to_sq=to_sq,
            piece=piece,
            start_ms=pg.time.get_ticks(),
            duration_ms=self.animation_duration_ms,
            on_complete=on_complete,
        ))

    def cancel_animations(self):
        self.animations = []

    def _draw_move_indicators(self):
        if self.selected_square is None:
            return

        piece = self.backend.piece_at(self.selected_square)
        if piece is None or piece.color != self.backend.current_turn():
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
        self.cell_size = rect.width // self.SIZE
        self.text_padding = rect.width * self.TEXT_PADDING_FRACTION
        self.rescale_pieces()
        self._render_text()

    def cell_at(self, pos):
        x, y = pos
        col = int((x - self.board_offset_x) / self.cell_size)
        row = int((y - self.board_offset_y) / self.cell_size)
        if not (0 <= col < self.SIZE and 0 <= row < self.SIZE):
            return None
        if self.flipped:
            row = self.SIZE - 1 - row
            col = self.SIZE - 1 - col
        return Square(row, col)

    def handle_click(self, square):
        if self.is_animating():
            return

        if self.pending_promotion_square is not None:
            self._handle_promotion_click(square)
            return

        grid = self._effective_grid()
        piece_at_clicked = grid[square.row][square.col]
        current_turn = self.backend.current_turn()

        if self.selected_square is None:
            if piece_at_clicked is None:
                resolved = self._resolve_chain_tip(square)
                if resolved != square:
                    resolved_piece = grid[resolved.row][resolved.col]
                    if resolved_piece is not None:
                        if resolved_piece.color == current_turn:
                            self._try_select(resolved)
                        else:
                            self._try_select_for_premove(resolved, resolved_piece)
                        return
                if self.premoves:
                    self._clear_premoves()
                return
            if piece_at_clicked.color == current_turn:
                self._try_select(square)
            else:
                self._try_select_for_premove(square, piece_at_clicked)
            return

        if square == self.selected_square:
            self.selected_square = None
            return

        from_sq = self.selected_square
        self.selected_square = None
        selected_piece = grid[from_sq.row][from_sq.col]
        if selected_piece is None:
            return

        if selected_piece.color == current_turn:
            result = self.backend.try_move(from_sq, square)
            if not result.legal:
                return
            self._start_move_animation(from_sq, square, result.promotion_required)
        else:
            self._queue_premove(from_sq, square, selected_piece)

    def _effective_grid(self):
        if not self.premoves:
            return self.backend.state
        return speculative_board(self.backend, self.premoves)

    def _resolve_chain_tip(self, square):
        sq = square
        visited = {sq}
        for _ in range(len(self.premoves)):
            next_sq = None
            for pm in self.premoves:
                if pm.from_sq == sq:
                    next_sq = pm.to_sq
                    break
            if next_sq is None or next_sq in visited:
                break
            sq = next_sq
            visited.add(sq)
        return sq

    def _try_select_for_premove(self, square, piece):
        if self.premove_color is not None and self.premove_color != piece.color:
            self._clear_premoves()
        self.selected_square = square

    def _queue_premove(self, from_sq, to_sq, piece):
        if not is_premove_shape_valid(piece, from_sq, to_sq):
            return
        if self.premove_color is not None and self.premove_color != piece.color:
            self._clear_premoves()
        self.premoves.append(Premove(from_sq, to_sq, piece))
        self.premove_color = piece.color

    def _clear_premoves(self):
        self.premoves = []
        self.premove_color = None

    def try_apply_next_premove(self):
        if (not self.premoves
                or self.premove_color != self.backend.current_turn()
                or self.pending_promotion_square is not None
                or self.is_animating()):
            return False
        pm = self.premoves[0]
        result = self.backend.try_move(pm.from_sq, pm.to_sq)
        if not result.legal:
            self._clear_premoves()
            return False
        self.premoves.pop(0)
        if not self.premoves:
            self.premove_color = None
        self._start_move_animation(pm.from_sq, pm.to_sq, result.promotion_required)
        return True

    def _start_move_animation(self, from_sq, to_sq, promotion_required):
        self.clear_annotations()
        entry = self.backend.move_history[-1]
        moving_piece = entry.move.piece

        if promotion_required:
            promotion_sq = to_sq
            on_complete = lambda: self._set_pending_promotion(promotion_sq)
        else:
            on_complete = self._fire_move_landed

        self.start_animation(from_sq, to_sq, moving_piece, on_complete=on_complete)

        if entry.move.is_castle:
            home_row = from_sq.row
            if to_sq.col == 6:
                rook_from = Square(home_row, 7)
                rook_to = Square(home_row, 5)
            else:
                rook_from = Square(home_row, 0)
                rook_to = Square(home_row, 3)
            rook_piece = self.backend.piece_at(rook_to)
            self.start_animation(rook_from, rook_to, rook_piece)

    def start_undo_animation(self, move):
        moving_piece = self.backend.piece_at(move.from_sq)
        if moving_piece is None:
            return
        self.start_animation(move.to_sq, move.from_sq, moving_piece)
        if move.is_castle:
            home_row = move.from_sq.row
            if move.to_sq.col == 6:
                rook_post, rook_home = Square(home_row, 5), Square(home_row, 7)
            else:
                rook_post, rook_home = Square(home_row, 3), Square(home_row, 0)
            rook_piece = self.backend.piece_at(rook_home)
            self.start_animation(rook_post, rook_home, rook_piece)

    def _set_pending_promotion(self, sq):
        self.pending_promotion_square = sq

    def _fire_move_landed(self):
        if self.move_landed_callback is None or not self.backend.move_history:
            return
        entry = self.backend.move_history[-1]
        if entry.position_key_added is None:
            return
        self.move_landed_callback(entry)

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
        self._fire_move_landed()

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