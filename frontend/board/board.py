import math
from itertools import product

import pygame as pg

from backend.pseudo_legal import piece_can_pseudo_reach
from backend.utils import Square
from frontend.visual.animation import PieceAnimation
from frontend.visual.colors import Colors
from frontend.premoves import Premove, speculative_board
from backend.pieces import PieceType, PieceColor, Piece


DRAG_THRESHOLD_PX = 6


class Board:
    SCREEN_FRACTION_X = 0.8
    OFFSET_FRACTION_X = 0.02
    TEXT_PADDING_FRACTION = 0.006
    SIZE = 8

    def __init__(self, window, match, move_landed_callback=None,
                 on_premove_queued=None):
        self.window = window
        self.match = match
        self.move_landed_callback = move_landed_callback
        self.on_premove_queued = on_premove_queued
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
        self._press_pos = None
        self.dragging_from = None
        self._drag_cursor = None
        self.review_ply = None
        self._target_ply = None
        self.read_only = False

    @property
    def backend(self):
        inner = getattr(self.match, "backend", None)
        return inner if inner is not None else self.match

    def _render_text(self):
        self.file_labels_rendered = [
            self.font.render(self.file_labels[i], True, Colors.white)
            for i in range(self.SIZE)
        ]
        self.rank_labels_rendered = [
            self.font.render(str(self.SIZE - r), True, Colors.white)
            for r in range(self.SIZE)
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
        color = self.match.piece_at(sq).color

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
        for visual_row in range(self.SIZE):
            array_row = (self.SIZE - 1 - visual_row) if self.flipped else visual_row
            x = self.board_offset_x + self.text_padding
            y = visual_row * self.cell_size + self.board_offset_y + self.text_padding
            self.window.blit(self.rank_labels_rendered[array_row], (x, y))

    def _draw_horizontal_guides(self):
        bottom_y = (self.SIZE - 1) * self.cell_size + self.board_offset_y
        for visual_col in range(self.SIZE):
            array_col = (self.SIZE - 1 - visual_col) if self.flipped else visual_col
            symbol = self.file_labels_rendered[array_col]
            x = (visual_col * self.cell_size + self.board_offset_x
                 + self.cell_size - symbol.get_width() - self.text_padding)
            y = bottom_y + self.cell_size - symbol.get_height() - self.text_padding
            self.window.blit(symbol, (x, y))

    def draw_board(self):
        for row, col in product(range(self.SIZE), repeat=2):
            self.draw_cell(row, col)
        if self.review_ply is not None:
            self._draw_last_move_highlight()
            self._draw_vertical_guides()
            self._draw_horizontal_guides()
            self.draw_pieces()
            self._draw_animations()
            return
        self._draw_check_highlight()
        self._draw_premove_highlights()
        self._draw_last_move_highlight()
        self._draw_annotation_highlights()
        self._draw_vertical_guides()
        self._draw_horizontal_guides()
        self._draw_selection_highlight()
        self._draw_move_indicators()
        self.draw_pieces()
        self._draw_animations()
        self._draw_dragged_piece()
        self._draw_arrows()
        self._draw_drag_preview_arrow()
        self._draw_promotion_picker()

    def _draw_last_move_highlight(self):
        history = self.match.move_history
        if not history:
            return
        if self.review_ply is not None:
            if self.review_ply == 0:
                return
            move = history[self.review_ply - 1].move
        else:
            move = history[-1].move
        for sq in (move.from_sq, move.to_sq):
            rect = self._cell_rect(sq.row, sq.col)
            overlay = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
            overlay.fill(Colors.last_move)
            self.window.blit(overlay, rect.topleft)

    def _draw_dragged_piece(self):
        if self.dragging_from is None or self._drag_cursor is None:
            return
        piece = self.match.piece_at(self.dragging_from)
        if piece is None:
            return
        surface = self.piece_images_scaled[(piece.type, piece.color)]
        ghost = surface.copy()
        ghost.set_alpha(int(255 * 0.30))
        origin_rect = self._cell_rect(self.dragging_from.row, self.dragging_from.col)
        self.window.blit(ghost, origin_rect.topleft)
        x = self._drag_cursor[0] - self.cell_size / 2
        y = self._drag_cursor[1] - self.cell_size / 2
        self.window.blit(surface, (x, y))

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
        chain_tip = self._active_chain_tip()
        if chain_tip is not None:
            rect = self._cell_rect(chain_tip.row, chain_tip.col)
            overlay = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
            overlay.fill(Colors.premove_chain_tip)
            self.window.blit(overlay, rect.topleft)

    def _active_chain_tip(self):
        active_sq = self.dragging_from or self.selected_square
        if active_sq is None or not self.premoves:
            return None
        tip = self._resolve_chain_tip(active_sq)
        if tip != active_sq:
            return tip
        for pm in self.premoves:
            if pm.to_sq == active_sq:
                return active_sq
        return None

    def toggle_highlight(self, sq):
        self.highlighted_squares ^= {sq}

    def toggle_arrow(self, from_sq, to_sq):
        arrow = (from_sq, to_sq)
        if arrow in self.arrows:
            self.arrows.remove(arrow)
        else:
            self.arrows.append(arrow)

    def is_square_annotated(self, sq):
        return sq in self.highlighted_squares or any(
            sq in (from_sq, to_sq) for from_sq, to_sq in self.arrows
        )

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

    @staticmethod
    def _knight_arrow_corner(from_sq, to_sq):
        dr = to_sq.row - from_sq.row
        dc = to_sq.col - from_sq.col
        if {abs(dr), abs(dc)} != {1, 2}:
            return None
        if abs(dr) == 2:
            return Square(to_sq.row, from_sq.col)
        return Square(from_sq.row, to_sq.col)

    def _render_arrow(self, from_sq, to_sq, color):
        if self.cell_size <= 0:
            return
        from_rect = self._cell_rect(from_sq.row, from_sq.col)
        to_rect = self._cell_rect(to_sq.row, to_sq.col)
        from_pos = (from_rect.centerx, from_rect.centery)
        to_pos = (to_rect.centerx, to_rect.centery)
        width = max(int(self.cell_size * 0.18), 5)
        if width % 2 == 0:
            width -= 1
        head_size = max(int(self.cell_size * 0.35), 8)
        cap_radius = width // 2

        corner_sq = self._knight_arrow_corner(from_sq, to_sq)
        if corner_sq is not None:
            corner_rect = self._cell_rect(corner_sq.row, corner_sq.col)
            shaft_origin = (corner_rect.centerx, corner_rect.centery)
        else:
            shaft_origin = from_pos

        angle = math.atan2(to_pos[1] - shaft_origin[1], to_pos[0] - shaft_origin[0])
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

        if corner_sq is not None:
            pg.draw.line(overlay, color, from_pos, shaft_origin, width)
            pg.draw.circle(overlay, color, shaft_origin, cap_radius)

        pg.draw.line(overlay, color, shaft_origin, shaft_end, width)
        pg.draw.circle(overlay, color, from_pos, cap_radius)
        pg.draw.polygon(overlay, color, [to_pos, head_left, head_right])
        self.window.blit(overlay, (0, 0))

    def _draw_check_highlight(self):
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.match.piece_at(Square(row, col))
            if piece is None or piece.type != PieceType.KING:
                continue
            if self.match.is_in_check(piece.color):
                rect = self._cell_rect(row, col)
                pg.draw.rect(self.window, Colors.selection_red, rect)

    def draw_pieces(self):
        if self.review_ply is not None:
            grid = self.match.position_at(self.review_ply)
            hidden = {a.from_sq for a in self.animations}
            for row, col in product(range(self.SIZE), repeat=2):
                sq = Square(row, col)
                if sq in hidden:
                    continue
                piece = grid[row][col]
                if piece is None:
                    continue
                rect = self._cell_rect(row, col)
                surface = self.piece_images_scaled[(piece.type, piece.color)]
                self.window.blit(surface, rect.topleft)
            return

        hidden = {a.to_sq for a in self.animations}
        if self.dragging_from is not None:
            hidden.add(self.dragging_from)
        for row, col in product(range(self.SIZE), repeat=2):
            sq = Square(row, col)
            if sq in hidden:
                continue
            piece = self.match.piece_at(sq)
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

    def jump_to_review_ply(self, ply):
        self.cancel_animations()
        self._target_ply = None
        history_len = len(self.match.move_history)
        if ply is None or ply >= history_len:
            self.review_ply = None
        else:
            self.review_ply = max(0, ply)

    def _snap_in_flight_review_animation(self):
        if self._target_ply is None:
            self.cancel_animations()
            return
        history_len = len(self.match.move_history)
        if self._target_ply >= history_len:
            self.review_ply = None
        else:
            self.review_ply = self._target_ply
        self._target_ply = None
        self.cancel_animations()

    def animate_review_ply(self, ply):
        self._snap_in_flight_review_animation()
        history_len = len(self.match.move_history)
        if ply is None or ply > history_len:
            self.review_ply = None
            self._target_ply = None
            return
        if ply <= 0:
            self.review_ply = 0
            self._target_ply = None
            return
        entry = self.match.move_history[ply - 1]
        move = entry.move
        self.review_ply = ply - 1
        self._target_ply = ply
        target_ply = ply
        end_ply = None if ply == history_len else ply

        def finish():
            self.review_ply = end_ply
            if self._target_ply == target_ply:
                self._target_ply = None

        self.start_animation(move.from_sq, move.to_sq, move.piece,
                             on_complete=finish)
        if move.is_castle:
            home_row = move.from_sq.row
            rook_from, rook_to = (
                (Square(home_row, 7), Square(home_row, 5))
                if move.to_sq.col == 6
                else (Square(home_row, 0), Square(home_row, 3))
            )
            rook_piece = Piece(PieceType.ROOK, move.piece.color)
            self.start_animation(rook_from, rook_to, rook_piece)

    def _draw_move_indicators(self):
        if self.selected_square is None:
            return

        piece = self.match.piece_at(self.selected_square)
        if piece is None or piece.color != self.match.current_turn():
            return

        legal_moves = self.match.legal_moves_from(self.selected_square)
        for target in legal_moves:
            rect = self._cell_rect(target.row, target.col)
            target_piece = self.match.piece_at(target)

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

    def begin_press(self, pos):
        self._press_pos = pos

    def update_drag_motion(self, pos):
        if self.read_only:
            return
        if self._press_pos is None or self.selected_square is None:
            return
        if self.pending_promotion_square is not None:
            return
        if self.review_ply is not None:
            return
        if self.dragging_from is not None:
            self._drag_cursor = pos
            return
        dx = pos[0] - self._press_pos[0]
        dy = pos[1] - self._press_pos[1]
        if dx * dx + dy * dy < DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX:
            return
        self.dragging_from = self.selected_square
        self._drag_cursor = pos

    def end_press(self):
        was_dragging = self.dragging_from is not None
        self._press_pos = None
        self.dragging_from = None
        self._drag_cursor = None
        return was_dragging

    def queue_premove_from_drag(self, target_sq):
        if self.read_only or self.review_ply is not None:
            return False
        if self.dragging_from is None:
            return False
        chain_tip = self._resolve_chain_tip(self.dragging_from)
        if target_sq == chain_tip:
            return False
        if self.pending_promotion_square is not None:
            return False
        grid = self._effective_grid()
        piece = grid[chain_tip.row][chain_tip.col]
        if piece is None:
            return False
        local_color = getattr(self.match, "local_color", None)
        if local_color is not None and piece.color != local_color:
            return False
        if piece.color == self.match.current_turn():
            return False
        if not piece_can_pseudo_reach(piece, chain_tip, target_sq):
            return False
        self._queue_premove(chain_tip, target_sq, piece)
        return True

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
        if self.read_only:
            return
        if self.review_ply is not None:
            return
        if self.is_animating():
            return

        if self.pending_promotion_square is not None:
            self._handle_promotion_click(square)
            return

        grid = self._effective_grid()
        piece_at_clicked = grid[square.row][square.col]
        live_at_clicked = self.match.state[square.row][square.col]
        current_turn = self.match.current_turn()
        local_color = getattr(self.match, "local_color", None)

        if self.selected_square is None:
            chain_piece = self._premove_chain_piece(
                piece_at_clicked, live_at_clicked, current_turn, local_color)
            if chain_piece is not None:
                self._try_select_for_premove(square, chain_piece)
                return
            if self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
                self._try_select(square)
                return
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
            self._try_select_for_premove(square, piece_at_clicked)
            return

        if square == self.selected_square:
            self.selected_square = None
            return

        if self._should_switch_focus_to(square, grid, live_at_clicked, current_turn, local_color):
            self.selected_square = None
            if self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
                self._try_select(square)
            else:
                self._try_select_for_premove(square, live_at_clicked)
            return

        from_sq = self.selected_square
        self.selected_square = None
        live_from_piece = self.match.state[from_sq.row][from_sq.col]
        spec_from_piece = grid[from_sq.row][from_sq.col]
        chain_from_piece = self._premove_chain_piece(
            spec_from_piece, live_from_piece, current_turn, local_color)
        if chain_from_piece is not None:
            self._queue_premove(from_sq, square, chain_from_piece)
            return
        if self._is_real_move_eligible(live_from_piece, current_turn, local_color):
            result = self.match.try_move(from_sq, square)
            if not result.legal:
                return
            self._start_move_animation(from_sq, square, result.promotion_required)
            return

        if spec_from_piece is None:
            return
        self._queue_premove(from_sq, square, spec_from_piece)

    @staticmethod
    def _is_real_move_eligible(live_piece, current_turn, local_color):
        if live_piece is None or live_piece.color != current_turn:
            return False
        if local_color is not None and live_piece.color != local_color:
            return False
        return True

    def _should_switch_focus_to(self, square, grid, live_at_clicked, current_turn, local_color):
        """A click on another own-side piece switches focus instead of attempting a move.

        Both the previously-selected piece and the clicked square must hold pieces
        of the same own color (online: local_color; offline: current_turn). Cross-color
        clicks fall through to the original move/capture/premove path.
        """
        if self.selected_square is None:
            return False
        own_color = local_color if local_color is not None else current_turn
        selected_piece = grid[self.selected_square.row][self.selected_square.col]
        if selected_piece is None or selected_piece.color != own_color:
            return False
        if live_at_clicked is None or live_at_clicked.color != own_color:
            return False
        return True

    def _premove_chain_piece(self, spec_piece, live_piece, current_turn, local_color):
        if self.premove_color is None or spec_piece is None:
            return None
        if local_color is None or local_color != self.premove_color:
            return None
        if current_turn == local_color:
            return None
        if spec_piece.color != self.premove_color:
            return None
        if live_piece is not None and live_piece.color == self.premove_color:
            return None
        return spec_piece

    def _effective_grid(self):
        if not self.premoves:
            return self.match.state
        return speculative_board(self.match, self.premoves)

    def _resolve_chain_tip(self, square):
        sq = square
        for pm in self.premoves:
            if pm.from_sq == sq:
                sq = pm.to_sq
        return sq

    def _try_select_for_premove(self, square, piece):
        local_color = getattr(self.match, "local_color", None)
        if local_color is not None and piece.color != local_color:
            return
        if self.premove_color is not None and self.premove_color != piece.color:
            self._clear_premoves()
        self.selected_square = square

    def _queue_premove(self, from_sq, to_sq, piece):
        if from_sq == to_sq:
            return
        if not piece_can_pseudo_reach(piece, from_sq, to_sq):
            return
        if self.premove_color is not None and self.premove_color != piece.color:
            self._clear_premoves()
        self.premoves.append(Premove(from_sq, to_sq, piece))
        self.premove_color = piece.color
        if self.on_premove_queued is not None:
            self.on_premove_queued()

    def _clear_premoves(self):
        self.premoves = []
        self.premove_color = None

    def try_apply_next_premove(self):
        if (not self.premoves
                or self.premove_color != self.match.current_turn()
                or self.pending_promotion_square is not None
                or self.is_animating()):
            return False
        pm = self.premoves[0]
        result = self.match.try_move(pm.from_sq, pm.to_sq)
        if not result.legal:
            self._clear_premoves()
            return False
        self.premoves.pop(0)
        if not self.premoves:
            self.premove_color = None
        self._start_move_animation(pm.from_sq, pm.to_sq, result.promotion_required)
        return True

    def animate_remote_move(self, from_sq, to_sq):
        self._start_move_animation(from_sq, to_sq, promotion_required=False)

    def _start_move_animation(self, from_sq, to_sq, promotion_required):
        self.review_ply = None
        self._target_ply = None
        self.cancel_animations()
        self.clear_annotations()
        entry = self.match.move_history[-1]
        moving_piece = entry.move.piece

        on_complete = (
            (lambda: self._set_pending_promotion(to_sq))
            if promotion_required
            else self._fire_move_landed
        )

        if self.dragging_from is not None:
            if entry.move.is_castle:
                self._start_castle_rook_animation(entry, from_sq, on_complete=on_complete)
            else:
                on_complete()
                self.last_animation_completed_at_ms = pg.time.get_ticks()
            return

        self.start_animation(from_sq, to_sq, moving_piece, on_complete=on_complete)

        if entry.move.is_castle:
            self._start_castle_rook_animation(entry, from_sq)

    def _start_castle_rook_animation(self, entry, king_from_sq, on_complete=None):
        home_row = king_from_sq.row
        king_to_col = entry.move.to_sq.col
        rook_from, rook_to = (
            (Square(home_row, 7), Square(home_row, 5))
            if king_to_col == 6
            else (Square(home_row, 0), Square(home_row, 3))
        )
        rook_piece = self.match.piece_at(rook_to)
        self.start_animation(rook_from, rook_to, rook_piece, on_complete=on_complete)

    def start_undo_animation(self, move):
        moving_piece = self.match.piece_at(move.from_sq)
        if moving_piece is None:
            return
        self.start_animation(move.to_sq, move.from_sq, moving_piece)
        if move.is_castle:
            home_row = move.from_sq.row
            rook_post, rook_home = (
                (Square(home_row, 5), Square(home_row, 7))
                if move.to_sq.col == 6
                else (Square(home_row, 3), Square(home_row, 0))
            )
            rook_piece = self.match.piece_at(rook_home)
            self.start_animation(rook_post, rook_home, rook_piece)

    def _set_pending_promotion(self, sq):
        self.pending_promotion_square = sq

    def _fire_move_landed(self):
        if self.move_landed_callback is None or not self.match.move_history:
            return
        entry = self.match.move_history[-1]
        if entry.position_key_added is None:
            return
        self.move_landed_callback(entry)

    def _handle_promotion_click(self, clicked_sq):
        sq = self.pending_promotion_square
        color = self.match.piece_at(sq).color
        options = [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]
        direction = 1 if color == PieceColor.WHITE else -1

        if clicked_sq.col != sq.col:
            return
        offset = (clicked_sq.row - sq.row) * direction
        if not (0 <= offset < len(options)):
            return

        chosen = options[offset]
        self.match.promote(sq, chosen)
        self.pending_promotion_square = None
        self._fire_move_landed()

    def _try_select(self, square):
        piece = self.match.piece_at(square)
        if piece is None:
            return
        if piece.color != self.match.current_turn():
            return
        local_color = getattr(self.match, "local_color", None)
        if local_color is not None and piece.color != local_color:
            return
        self.selected_square = square

    def _draw_selection_highlight(self):
        if self.selected_square is None:
            return
        if self.selected_square == self._active_chain_tip():
            return

        rect = self._cell_rect(self.selected_square.row, self.selected_square.col)
        pg.draw.rect(self.window, Colors.selection_red, rect, 4)