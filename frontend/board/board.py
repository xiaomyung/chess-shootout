import math
from itertools import product

import pygame as pg

from backend.pseudo_legal import piece_can_pseudo_reach
from backend.utils import Square
from infra import env
from frontend.visual.animation import PieceAnimation
from frontend.visual.colors import Colors
from frontend.visual.draw import supersample
from frontend.visual.effects import EffectManager
from frontend.premoves import Premove, speculative_board
from backend.pieces import PieceType, PieceColor, Piece, opponent_of
from frontend.visual.fonts import get_font, DISPLAY


DRAG_THRESHOLD_PX = 6
DRAG_GHOST_ALPHA_FRACTION = 0.30


def _draw_capsule(surf, p1, p2, width, color):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    bar = pg.Surface((int(length) + width, width), pg.SRCALPHA)
    pg.draw.rect(bar, color, bar.get_rect(), border_radius=width // 2)
    rotated = pg.transform.rotate(bar, -math.degrees(math.atan2(dy, dx)))
    surf.blit(rotated, rotated.get_rect(center=((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)))


class Board:
    TEXT_PADDING_FRACTION = 0.006
    SIZE = 8
    FRAME_PAD_FRACTION = 0.055
    FRAME_PAD_MIN = 16
    FRAME_RADIUS = 14
    GRID_RADIUS = 4

    PROMOTION_OPTION_SIZE_MIN = 48
    PROMOTION_OPTION_SIZE_MAX = 72
    PROMOTION_PANEL_PAD = 10
    PROMOTION_OPTION_GAP = 8
    PROMOTION_LABEL_HEIGHT = 20
    PROMOTION_LABEL_OPTION_GAP = 6
    PROMOTION_SCREEN_MARGIN = 8

    HITMARKER_SIZE_MIN = 8
    KING_HITMARKER_SIZE_FACTOR = 1.0
    KING_HITMARKER_THICKNESS = 3.4
    CAPTURE_HITMARKER_SIZE_FACTOR = 0.55
    CAPTURE_HITMARKER_THICKNESS = 4.2

    def __init__(self, window, match, move_landed_callback=None,
                 on_premove_queued=None, shot_callback=None, announce_callback=None):
        self.window = window
        self.match = match
        self.move_landed_callback = move_landed_callback
        self.shot_callback = shot_callback
        self.announce_callback = announce_callback
        self.on_premove_queued = on_premove_queued
        self.font = get_font(18, bold=True)
        self.board_guides_font_factor = 50

        self.rect = pg.Rect(0, 0, 0, 0)
        self.frame_pad = 0
        self.cell_size = 0
        self.board_offset_x = 0
        self.board_offset_y = 0
        self._promotion_rects = {}
        self._frame_surf = None
        self._arrow_cache = None
        self._shake_dx = 0
        self._shake_dy = 0

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
        self.effects = EffectManager()
        self.effects.geom = lambda sq: self._cell_rect(sq.row, sq.col).center
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
        size = max(int(self.cell_size * 0.30), 11) if self.cell_size else 13
        coord_font = get_font(size, bold=True, mono=True)
        self.file_labels_rendered = [
            coord_font.render(self.file_labels[i], True, Colors.coord)
            for i in range(self.SIZE)
        ]
        self.rank_labels_rendered = [
            coord_font.render(str(self.SIZE - r), True, Colors.coord)
            for r in range(self.SIZE)
        ]

    def _load_piece_images(self):
        for piece_color in PieceColor:
            for piece_type in PieceType:
                piece = Piece(piece_type, piece_color)
                image = pg.image.load(piece.img_path).convert_alpha()
                self.piece_images_original[(piece_type, piece_color)] = image

    def _cell_rect_base(self, row, col):
        if self.flipped:
            row = self.SIZE - 1 - row
            col = self.SIZE - 1 - col
        return pg.Rect(
            col * self.cell_size + self.board_offset_x,
            row * self.cell_size + self.board_offset_y,
            self.cell_size,
            self.cell_size
        )

    def _cell_rect(self, row, col):
        return self._cell_rect_base(row, col).move(self._shake_dx, self._shake_dy)

    PROMOTION_OPTIONS = [
        (PieceType.QUEEN, "Q", "BOSS"), (PieceType.ROOK, "R", "TANK"),
        (PieceType.BISHOP, "B", "SNIPER"), (PieceType.KNIGHT, "N", "WILDCARD"),
    ]

    def _draw_promotion_picker(self):
        self._promotion_rects = {}
        if self.pending_promotion_square is None:
            return
        sq = self.pending_promotion_square
        color = self.match.piece_at(sq).color
        opt = max(self.PROMOTION_OPTION_SIZE_MIN,
                  min(int(self.cell_size), self.PROMOTION_OPTION_SIZE_MAX))
        pad, gap, label_h = (self.PROMOTION_PANEL_PAD, self.PROMOTION_OPTION_GAP,
                             self.PROMOTION_LABEL_HEIGHT)
        panel_w = pad * 2 + 4 * opt + 3 * gap
        panel_h = pad * 2 + label_h + self.PROMOTION_LABEL_OPTION_GAP + opt
        sq_rect = self._cell_rect_base(sq.row, sq.col)
        win_w, win_h = self.window.get_size()
        left_bound = max(self.rect.x, self.PROMOTION_SCREEN_MARGIN)
        right_bound = min(self.rect.right, win_w - self.PROMOTION_SCREEN_MARGIN)
        x = sq_rect.right + self.PROMOTION_PANEL_PAD
        if x + panel_w > right_bound:
            x = sq_rect.left - panel_w - self.PROMOTION_PANEL_PAD
        x = max(left_bound, min(x, right_bound - panel_w))
        y = max(self.rect.y,
                min(sq_rect.centery - panel_h // 2,
                    win_h - panel_h - self.PROMOTION_SCREEN_MARGIN))
        panel = pg.Rect(x, y, panel_w, panel_h)
        pg.draw.rect(self.window, Colors.surface_raised, panel, border_radius=12)
        pg.draw.rect(self.window, Colors.accent, panel, 1, border_radius=12)
        label = get_font(max(int(label_h * 0.8), 12), family=DISPLAY).render(
            "UPGRADE", True, Colors.accent_hi)
        self.window.blit(label, (panel.centerx - label.get_width() // 2, panel.y + pad - 2))
        mouse = pg.mouse.get_pos()
        cells_y = panel.y + pad + label_h + self.PROMOTION_LABEL_OPTION_GAP
        for i, (ptype, hotkey, tag) in enumerate(self.PROMOTION_OPTIONS):
            cell = pg.Rect(panel.x + pad + i * (opt + gap), cells_y, opt, opt)
            hovered = cell.collidepoint(mouse)
            pg.draw.rect(self.window, Colors.surface_hover if hovered else Colors.surface,
                         cell, border_radius=11)
            pg.draw.rect(self.window, Colors.accent if hovered else Colors.border,
                         cell, 1, border_radius=11)
            img = pg.transform.smoothscale(self.piece_images_original[(ptype, color)], (opt, opt))
            self.window.blit(img, cell.topleft)
            hk = get_font(max(int(opt * 0.18), 9), bold=True, mono=True).render(
                hotkey, True, Colors.text_muted)
            self.window.blit(hk, (cell.right - hk.get_width() - 3,
                                  cell.bottom - hk.get_height() - 2))
            if hovered:
                tag_surf = get_font(max(int(opt * 0.14), 8), bold=True).render(
                    tag, True, Colors.on_accent)
                tag_rect = pg.Rect(0, 0, tag_surf.get_width() + 8, tag_surf.get_height() + 4)
                tag_rect.center = (cell.centerx, cell.y - 6)
                pg.draw.rect(self.window, Colors.amber, tag_rect, border_radius=7)
                self.window.blit(tag_surf, (tag_rect.centerx - tag_surf.get_width() // 2,
                                            tag_rect.centery - tag_surf.get_height() // 2))
            self._promotion_rects[ptype] = cell

    def pick_promotion(self, ptype):
        if self.pending_promotion_square is None:
            return
        sq = self.pending_promotion_square
        self.match.promote(sq, ptype)
        self.pending_promotion_square = None
        self._promotion_rects = {}
        self._fire_move_landed()

    def pick_promotion_at(self, pos):
        if self.pending_promotion_square is None:
            return
        for ptype, cell in self._promotion_rects.items():
            if cell.collidepoint(pos):
                self.pick_promotion(ptype)
                return

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
        gutter_cx = (self.rect.x + self.board_offset_x) // 2
        for visual_row in range(self.SIZE):
            array_row = (self.SIZE - 1 - visual_row) if self.flipped else visual_row
            label = self.rank_labels_rendered[array_row]
            cy = self.board_offset_y + visual_row * self.cell_size + self.cell_size // 2
            self.window.blit(label, (gutter_cx - label.get_width() // 2 + self._shake_dx,
                                     cy - label.get_height() // 2 + self._shake_dy))

    def _draw_horizontal_guides(self):
        grid_bottom = self.board_offset_y + self.cell_size * self.SIZE
        gutter_cy = (grid_bottom + self.rect.bottom) // 2
        for visual_col in range(self.SIZE):
            array_col = (self.SIZE - 1 - visual_col) if self.flipped else visual_col
            label = self.file_labels_rendered[array_col]
            cx = self.board_offset_x + visual_col * self.cell_size + self.cell_size // 2
            self.window.blit(label, (cx - label.get_width() // 2 + self._shake_dx,
                                     gutter_cy - label.get_height() // 2 + self._shake_dy))

    def draw_board(self):
        now = pg.time.get_ticks()
        self.effects.update(now)
        if self.review_ply is None:
            self._shake_dx, self._shake_dy = self.effects.shake_offset(now)
        else:
            self._shake_dx = self._shake_dy = 0
        if self._frame_surf is not None:
            self.window.blit(self._frame_surf,
                             (self.rect.x + self._shake_dx, self.rect.y + self._shake_dy))
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
        self.effects.draw_holes(self.window, now)
        self.draw_pieces()
        self._draw_front_markers()
        self._draw_animations()
        self.effects.draw_over(self.window, now)
        self._draw_dragged_piece()
        self._draw_arrows()
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
        ghost.set_alpha(int(255 * DRAG_GHOST_ALPHA_FRACTION))
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
        if self.cell_size <= 0:
            self._arrow_cache = None
            return
        items = [(fr, to, Colors.annotation_arrow) for fr, to in self.arrows]
        if self._right_drag_start_square is not None:
            end_sq = self.cell_at(pg.mouse.get_pos())
            if end_sq is not None and end_sq != self._right_drag_start_square:
                items.append((self._right_drag_start_square, end_sq,
                              Colors.annotation_arrow_preview))
        if not items:
            self._arrow_cache = None
            return
        key = (tuple(items), self.cell_size, self.board_offset_x,
               self.board_offset_y, self.flipped, self.rect.size)
        if self._arrow_cache is None or self._arrow_cache[0] != key:
            def render(layer, scale):
                for fr, to, color in items:
                    self._render_arrow(layer, scale, fr, to, color)
            self._arrow_cache = (key, supersample(self.rect.size, render))
        self.window.blit(self._arrow_cache[1], self.rect.topleft)

    @staticmethod
    def _knight_arrow_corner(from_sq, to_sq):
        dr = to_sq.row - from_sq.row
        dc = to_sq.col - from_sq.col
        if {abs(dr), abs(dc)} != {1, 2}:
            return None
        if abs(dr) == 2:
            return Square(to_sq.row, from_sq.col)
        return Square(from_sq.row, to_sq.col)

    def _render_arrow(self, layer, scale, from_sq, to_sq, color):
        def pt(sq):
            r = self._cell_rect_base(sq.row, sq.col)
            return ((r.centerx - self.rect.x) * scale, (r.centery - self.rect.y) * scale)

        from_pos = pt(from_sq)
        to_pos = pt(to_sq)
        width = max(int(self.cell_size * 0.16), 5) * scale
        head_size = max(int(self.cell_size * 0.38), 8) * scale
        base = pg.Color(color)
        rgb = (base.r, base.g, base.b)
        max_a = base.a

        corner_sq = self._knight_arrow_corner(from_sq, to_sq)
        shaft_origin = pt(corner_sq) if corner_sq is not None else from_pos

        angle = math.atan2(to_pos[1] - shaft_origin[1], to_pos[0] - shaft_origin[0])
        shaft_end = (
            to_pos[0] - head_size * 0.55 * math.cos(angle),
            to_pos[1] - head_size * 0.55 * math.sin(angle),
        )
        head_half = math.radians(150)
        head_left = (to_pos[0] + head_size * math.cos(angle + head_half),
                     to_pos[1] + head_size * math.sin(angle + head_half))
        head_right = (to_pos[0] + head_size * math.cos(angle - head_half),
                      to_pos[1] + head_size * math.sin(angle - head_half))

        pts = [from_pos] + ([shaft_origin] if corner_sq is not None else []) + [shaft_end]
        head = [to_pos, head_left, head_right]
        pad = width + 4
        xs = [p[0] for p in pts + head]
        ys = [p[1] for p in pts + head]
        ox, oy = min(xs) - pad, min(ys) - pad
        w = max(int(max(xs) + pad - ox), 1)
        h = max(int(max(ys) + pad - oy), 1)
        arrow = pg.Surface((w, h), pg.SRCALPHA)
        self._draw_shaft(arrow, rgb, max_a, [(x - ox, y - oy) for x, y in pts], width)
        pg.draw.polygon(arrow, (*rgb, max_a), [(x - ox, y - oy) for x, y in head])
        layer.blit(arrow, (int(ox), int(oy)))

    @staticmethod
    def _gradient_capsule(rgb, length, width, a0, a1):
        length = max(int(length), 1)
        width = max(int(width), 1)
        cols = min(length, 64)
        strip = pg.Surface((cols, width), pg.SRCALPHA)
        for x in range(cols):
            t = x / max(cols - 1, 1)
            pg.draw.line(strip, (*rgb, int(a0 + (a1 - a0) * t)), (x, 0), (x, width - 1))
        bar = pg.transform.smoothscale(strip, (length, width))
        mask = pg.Surface((length, width), pg.SRCALPHA)
        pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=width // 2)
        bar.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        return bar

    def _draw_shaft(self, surf, rgb, max_a, pts, width):
        seglens = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                   for i in range(len(pts) - 1)]
        total = sum(seglens) or 1
        n = len(pts)
        done = 0.0
        ext = width / 2
        for i in range(n - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            seg = seglens[i] or 1
            dx, dy = (bx - ax) / seg, (by - ay) / seg
            if i > 0:
                ax, ay = ax - dx * ext, ay - dy * ext
            if i < n - 2:
                bx, by = bx + dx * ext, by + dy * ext
            a0 = max_a * (0.45 + 0.5 * (done / total))
            a1 = max_a * (0.45 + 0.5 * ((done + seglens[i]) / total))
            cap = self._gradient_capsule(rgb, math.hypot(bx - ax, by - ay), width, a0, a1)
            rotated = pg.transform.rotate(cap, -math.degrees(math.atan2(by - ay, bx - ax)))
            surf.blit(rotated, rotated.get_rect(center=((ax + bx) / 2, (ay + by) / 2)),
                      special_flags=pg.BLEND_RGBA_MAX)
            done += seglens[i]

    def _draw_check_highlight(self):
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.match.piece_at(Square(row, col))
            if piece is None or piece.type != PieceType.KING:
                continue
            if self.match.is_in_check(piece.color):
                rect = self._cell_rect(row, col)
                wash = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
                wash.fill(Colors.check_fill)
                self.window.blit(wash, rect.topleft)
                pg.draw.rect(self.window, Colors.check, rect, 3)

    def _draw_hitmarker(self, rect, size, color, thick):
        def render(surf, k):
            u = size * k / 40.0
            tw = max(int(thick * u), 2)
            for (x1, y1), (x2, y2) in (((7, 7), (14.5, 14.5)), ((33, 7), (25.5, 14.5)),
                                       ((7, 33), (14.5, 25.5)), ((33, 33), (25.5, 25.5))):
                _draw_capsule(surf, (x1 * u, y1 * u), (x2 * u, y2 * u), tw, color)
        self.window.blit(supersample(size, render),
                         (rect.centerx - size // 2, rect.centery - size // 2))

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

        now = pg.time.get_ticks()
        hidden = {a.to_sq for a in self.animations}
        hidden |= self.effects.held_squares()
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
            dx, dy = self.effects.piece_offset(sq, now)
            self.window.blit(surface, (rect.x + dx, rect.y + dy))

    def _draw_animations(self):
        if not self.animations:
            return
        now = pg.time.get_ticks()
        completed = []
        for a in self.animations:
            progress = a.progress(now)
            eased = 1 - (1 - progress) ** 3
            fr = self._cell_rect(a.from_sq.row, a.from_sq.col)
            to = self._cell_rect(a.to_sq.row, a.to_sq.col)
            x = fr.x + (to.x - fr.x) * eased
            y = fr.y + (to.y - fr.y) * eased
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
        self.effects.clear()
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

    def _selected_legal_targets(self):
        if self.selected_square is None:
            return []
        piece = self.match.piece_at(self.selected_square)
        if piece is None or piece.color != self.match.current_turn():
            return []
        return self.match.legal_moves_from(self.selected_square)

    def _draw_move_indicators(self):
        for target in self._selected_legal_targets():
            if self.match.piece_at(target) is None:
                self._draw_dot(self._cell_rect(target.row, target.col))

    def _draw_front_markers(self):
        ep = self.match.en_passant_target
        sel = self.selected_square
        for target in self._selected_legal_targets():
            if self.match.piece_at(target) is not None:
                self._draw_capture_hitmarker(self._cell_rect(target.row, target.col))
            elif ep is not None and target == ep and sel is not None:
                mover = self.match.piece_at(sel)
                if mover is not None and mover.type == PieceType.PAWN and target.col != sel.col:
                    captured = Square(sel.row, target.col)
                    self._draw_capture_hitmarker(self._cell_rect(captured.row, captured.col))
        now = pg.time.get_ticks()
        for row, col in product(range(self.SIZE), repeat=2):
            sq = Square(row, col)
            piece = self.match.piece_at(sq)
            if (piece is not None and piece.type == PieceType.KING
                    and self.match.is_in_check(piece.color)):
                dx, dy = self.effects.piece_offset(sq, now)
                self._draw_hitmarker(
                    self._cell_rect(row, col).move(dx, dy),
                    max(int(self.cell_size * self.KING_HITMARKER_SIZE_FACTOR),
                        self.HITMARKER_SIZE_MIN),
                    Colors.accent, self.KING_HITMARKER_THICKNESS)

    def _draw_dot(self, rect):
        s = int(self.cell_size)
        radius = max(int(s * 0.16), 4)
        thickness = max(int(s * 0.05), 3)

        def render(surf, k):
            pg.draw.circle(surf, Colors.move_indicator, (s * k // 2, s * k // 2),
                           radius * k, thickness * k)

        self.window.blit(supersample(s, render), rect.topleft)

    def _draw_capture_hitmarker(self, rect):
        self._draw_hitmarker(
            rect,
            max(int(self.cell_size * self.CAPTURE_HITMARKER_SIZE_FACTOR),
                self.HITMARKER_SIZE_MIN),
            Colors.accent, self.CAPTURE_HITMARKER_THICKNESS)

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self.effects.board_rect = pg.Rect(rect)
        self.frame_pad = max(int(rect.width * self.FRAME_PAD_FRACTION), self.FRAME_PAD_MIN)
        inner = rect.width - 2 * self.frame_pad
        self.cell_size = max(inner // self.SIZE, 1)
        used = self.cell_size * self.SIZE
        free_w = rect.width - 2 * self.frame_pad - used
        free_h = rect.height - 2 * self.frame_pad - used
        self.board_offset_x = rect.x + self.frame_pad + free_w // 2
        self.board_offset_y = rect.y + self.frame_pad + free_h // 2
        self.text_padding = rect.width * self.TEXT_PADDING_FRACTION
        self.rescale_pieces()
        self._render_text()
        self._build_frame_surface()

    def _build_frame_surface(self):
        if self.rect.width <= 0 or self.rect.height <= 0:
            self._frame_surf = None
            return
        w, h = self.rect.width, self.rect.height
        top, bot = pg.Color(Colors.board_frame_inner), pg.Color(Colors.board_frame)
        column = pg.Surface((1, h))
        for y in range(h):
            t = y / max(h - 1, 1)
            column.set_at((0, y), (round(top.r + (bot.r - top.r) * t),
                                   round(top.g + (bot.g - top.g) * t),
                                   round(top.b + (bot.b - top.b) * t)))
        bezel = pg.transform.scale(column, (w, h)).convert_alpha()
        mask = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.FRAME_RADIUS)
        bezel.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        surf = pg.Surface((w, h), pg.SRCALPHA)
        surf.blit(bezel, (0, 0))
        pg.draw.rect(surf, Colors.border_strong, surf.get_rect(), 2,
                     border_radius=self.FRAME_RADIUS)
        self._draw_corner_ticks(surf)
        gx = self.board_offset_x - self.rect.x
        gy = self.board_offset_y - self.rect.y
        gs = self.cell_size * self.SIZE
        pg.draw.rect(surf, "#000000", pg.Rect(gx - 1, gy - 1, gs + 2, gs + 2),
                     border_radius=self.GRID_RADIUS)
        self._frame_surf = surf

    def _draw_corner_ticks(self, surf):
        w, h = surf.get_size()
        inset, length, thick = 8, 18, 2
        color = pg.Color(Colors.accent)
        color.a = 107
        ticks = pg.Surface((w, h), pg.SRCALPHA)
        corners = (((inset, inset), (1, 1)), ((w - inset, inset), (-1, 1)),
                   ((inset, h - inset), (1, -1)), ((w - inset, h - inset), (-1, -1)))
        for (cx, cy), (sx, sy) in corners:
            pg.draw.line(ticks, color, (cx, cy), (cx + sx * length, cy), thick)
            pg.draw.line(ticks, color, (cx, cy), (cx, cy + sy * length), thick)
        surf.blit(ticks, (0, 0))

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
        self.effects.cut(pg.time.get_ticks())
        self.clear_annotations()
        entry = self.match.move_history[-1]
        moving_piece = entry.move.piece

        on_complete = (
            (lambda: self._set_pending_promotion(to_sq))
            if promotion_required
            else self._fire_move_landed
        )

        if entry.move.captured is not None and self._capture_choreography(
                entry, from_sq, to_sq, moving_piece, on_complete):
            return

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
        self.effects.clear()
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

    def _capture_choreography(self, entry, from_sq, to_sq, moving_piece, on_complete):
        captured = entry.move.captured
        color = moving_piece.color.value
        victim_sq = (Square(from_sq.row, to_sq.col)
                     if entry.move.is_en_passant else to_sq)
        self.effects.configure(env.get_reduce_motion(), env.get_effect_intensity())
        attacker = self.piece_images_scaled.get((moving_piece.type, moving_piece.color))
        victim = self.piece_images_scaled.get((captured.type, captured.color))
        if attacker is None or victim is None or self.cell_size <= 0:
            self._on_capture_fire(entry, color, victim_sq)
            return False
        self.dragging_from = None
        self._drag_cursor = None
        occupied = {Square(r, c) for r, c in product(range(self.SIZE), repeat=2)
                    if self.match.piece_at(Square(r, c)) is not None}
        self.effects.capture(
            now_ms=pg.time.get_ticks(),
            attacker_type=moving_piece.type.value,
            attacker_surface=attacker, victim_surface=victim,
            from_sq=from_sq, victim_sq=victim_sq, to_sq=to_sq,
            cell_size=self.cell_size, power=self._capture_power(captured.type),
            occupied=occupied,
            on_fire=lambda: self._on_capture_fire(entry, color, victim_sq),
            on_slide=lambda: self.start_animation(from_sq, to_sq, moving_piece,
                                                  on_complete=on_complete),
        )
        return True

    def _on_capture_fire(self, entry, color, victim_sq):
        key = self.effects.register_kill(color, victim_sq, self.cell_size, pg.time.get_ticks())
        if self.shot_callback is not None:
            self.shot_callback(entry)
        if self.announce_callback is not None and key is not None:
            self.announce_callback(key)

    def show_surrender_flag(self, color):
        if self.cell_size <= 0:
            return
        king_sq = self._king_square(color)
        if king_sq is not None:
            self.effects.raise_flag(king_sq, self.cell_size, pg.time.get_ticks())

    def show_checkmate_takeover(self, winner_label):
        self.effects.configure(env.get_reduce_motion(), env.get_effect_intensity())
        now = pg.time.get_ticks()
        self.effects.start_takeover("CHECKMATE", winner_label, now)
        self.effects.trigger_shake(now, "hard")

    @staticmethod
    def _capture_power(victim_type):
        if victim_type in (PieceType.QUEEN, PieceType.ROOK):
            return "hard"
        if victim_type == PieceType.PAWN:
            return "soft"
        return "med"

    SLIDERS = (PieceType.BISHOP, PieceType.ROOK, PieceType.QUEEN)

    def show_check_gun(self, entry):
        if self.cell_size <= 0 or self.review_ply is not None:
            return
        by_color = entry.move.piece.color
        king_color = opponent_of(by_color)
        king_sq = self._king_square(king_color)
        if king_sq is None:
            return
        checker = self._checking_square(king_sq, by_color)
        if checker is None:
            return
        self.effects.configure(env.get_reduce_motion(), env.get_effect_intensity())
        self.effects.check(now_ms=pg.time.get_ticks(),
                           attacker_type=self.match.piece_at(checker).type.value,
                           king_sq=king_sq, from_sq=checker, cell_size=self.cell_size)

    def _king_square(self, color):
        for row, col in product(range(self.SIZE), repeat=2):
            piece = self.match.piece_at(Square(row, col))
            if piece is not None and piece.type == PieceType.KING and piece.color == color:
                return Square(row, col)
        return None

    def _checking_square(self, king_sq, by_color):
        grid = self.match.state
        for row, col in product(range(self.SIZE), repeat=2):
            piece = grid[row][col]
            if piece is None or piece.color != by_color:
                continue
            sq = Square(row, col)
            if not piece_can_pseudo_reach(piece, sq, king_sq):
                continue
            if piece.type in self.SLIDERS and not self._segment_empty(grid, sq, king_sq):
                continue
            return sq
        return None

    @staticmethod
    def _segment_empty(grid, a, b):
        dr = (b.row > a.row) - (b.row < a.row)
        dc = (b.col > a.col) - (b.col < a.col)
        r, c = a.row + dr, a.col + dc
        while (r, c) != (b.row, b.col):
            if grid[r][c] is not None:
                return False
            r, c = r + dr, c + dc
        return True

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
        wash = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
        wash.fill(Colors.selection_fill)
        self.window.blit(wash, rect.topleft)
        pg.draw.rect(self.window, Colors.accent, rect, 4)
