import math
from itertools import product

import pygame as pg

from chessshootout.backend.pseudo_legal import piece_can_pseudo_reach, king_square, checking_square
from chessshootout.backend.utils import Square
from chessshootout.frontend.board.annotations import Annotations
from chessshootout.frontend.board.drag import DragPhysics
from chessshootout.frontend.visual.animation import PieceAnimation
from chessshootout.frontend.visual.cache import (
    new_cache, new_size_cache, memoized_surface, render_text,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    supersample, smoothstep, scale_floor, cut_rect_surface,
)
from chessshootout.frontend.visual.effects import EffectManager
from chessshootout.frontend.visual.icons import piece_png_path
from chessshootout.domain.premoves import Premove, speculative_board
from chessshootout.backend.pieces import PieceType, PieceColor, Piece, opponent_of
from chessshootout.frontend.visual.fonts import get_font, DISPLAY


_OVERLAY_CACHE = new_cache()
_PROMO_OPTION_CACHE = new_size_cache()
_MARKER_CACHE = new_cache()
_PIECE_IMAGE_CACHE = new_cache()

CAPTURE_ICON_FRACTION = 0.42

RESTORE_MS = 480
RESTORE_DROP_FRAC = 0.8
RESTORE_FALL_PORTION = 0.46
RESTORE_FADE_PORTION = 0.36
RESTORE_REBOUND_FRAC = 0.13
RESTORE_SETTLE_DECAY = 4.0
RESTORE_SETTLE_WAVES = 1.25
RESTORE_ROCK_DEG = 7.5
RESTORE_ROCK_WAVES = 1.15


def _draw_capsule(surf, p1, p2, width, color):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    bar = pg.Surface((int(length) + width, width), pg.SRCALPHA)
    pg.draw.rect(bar, color, bar.get_rect(), border_radius=width // 2)
    rotated = pg.transform.rotate(bar, -math.degrees(math.atan2(dy, dx)))
    surf.blit(rotated, rotated.get_rect(center=((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)))


class Board:
    SIZE = 8
    PLATE_MARGIN = 26
    PLATE_MARGIN_FLOOR = 18
    PLATE_CUT = 18
    COORD_PAD_FRACTION = 0.6

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
        self.skillcheck_gate = None
        self.skillcheck_armed = None
        self.locked_targets = None

        self.rect = pg.Rect(0, 0, 0, 0)
        self.frame_pad = 0
        self.cell_size = 0
        self.board_offset_x = 0
        self.board_offset_y = 0
        self._promotion_rects = {}
        self._frame_surf = None
        self._checkerboard_surf = None
        self._check_squares_key = None
        self._check_squares = []
        self._shake_dx = 0
        self._shake_dy = 0

        self.file_labels = "abcdefgh"
        self.file_labels_rendered = []
        self.rank_labels_rendered = []

        self.piece_images_original = {}
        self.piece_images_scaled = {}
        self._sprite_geom = {}
        self.selected_square = None
        self.pending_promotion_square = None
        self._promotion_from = None
        self.aim_suppressed_square = None
        self.flipped = False
        self.animations = []
        self._restore_anims = []
        self.effects = EffectManager()
        self.effects.geom = lambda sq: self._cell_rect(sq.row, sq.col).center
        self.animation_duration_ms = 180
        self.last_animation_completed_at_ms = 0
        self.premoves = []
        self.premove_color = None
        self.annotations = Annotations(self)
        self.dragging_from = None
        self.drag = DragPhysics(self)
        self.review_ply = None
        self._target_ply = None
        self.read_only = False
        self._promo_label_font = get_font(
            max(int(self.PROMOTION_LABEL_HEIGHT * 0.8), 12), family=DISPLAY)
        self._promo_hotkey_font = get_font(9, bold=True, mono=True)
        self._promo_tag_font = get_font(8, bold=True)

    @property
    def backend(self):
        inner = getattr(self.match, "backend", None)
        return inner if inner is not None else self.match

    @property
    def highlighted_squares(self):
        return self.annotations.highlighted_squares

    @highlighted_squares.setter
    def highlighted_squares(self, value):
        self.annotations.highlighted_squares = value

    @property
    def arrows(self):
        return self.annotations.arrows

    @arrows.setter
    def arrows(self, value):
        self.annotations.arrows = value

    def reset_for_new_game(self):
        self.flipped = False
        self.selected_square = None
        self.pending_promotion_square = None
        self._promotion_from = None
        self.cancel_animations()
        self.effects.clear()
        self.clear_premoves()
        self.aim_suppressed_square = None
        self.clear_annotations()
        self.end_press()
        self.review_ply = None

    def _render_text(self):
        size = max(int(self.cell_size * 0.30), 11) if self.cell_size else 13
        if self.frame_pad:
            size = min(size, max(int(self.frame_pad * self.COORD_PAD_FRACTION), 8))
        coord_font = get_font(size, bold=True, mono=True)
        self.file_labels_rendered = [
            coord_font.render(self.file_labels[i], True, Colors.text_muted)
            for i in range(self.SIZE)
        ]
        self.rank_labels_rendered = [
            coord_font.render(str(self.SIZE - r), True, Colors.text_muted)
            for r in range(self.SIZE)
        ]

    def _load_piece_images(self):
        for piece_color in PieceColor:
            for piece_type in PieceType:
                piece = Piece(piece_type, piece_color)
                key = (piece_type, piece_color)
                self.piece_images_original[key] = memoized_surface(
                    _PIECE_IMAGE_CACHE, key,
                    lambda p=piece: pg.image.load(piece_png_path(p)).convert_alpha())

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

    def _promo_option_sprite(self, ptype, color, opt):
        key = (ptype, color, opt)
        return memoized_surface(
            _PROMO_OPTION_CACHE, key,
            lambda: pg.transform.smoothscale(
                self.piece_images_original[(ptype, color)], (opt, opt)))

    def _draw_promotion_picker(self):
        self._promotion_rects = {}
        if self.pending_promotion_square is None:
            return
        sq = self.pending_promotion_square
        origin = self._promotion_from if self._promotion_from is not None else sq
        pawn = self.match.piece_at(origin)
        if pawn is None:
            return
        color = pawn.color
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
        label = render_text(self._promo_label_font, "UPGRADE", Colors.accent_hi)
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
            img = self._promo_option_sprite(ptype, color, opt)
            self.window.blit(img, cell.topleft)
            hk = render_text(self._promo_hotkey_font, hotkey, Colors.text_muted)
            self.window.blit(hk, (cell.right - hk.get_width() - 3,
                                  cell.bottom - hk.get_height() - 2))
            if hovered:
                tag_surf = render_text(self._promo_tag_font, tag, Colors.on_accent)
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
        if self._promotion_from is not None:
            from_sq = self._promotion_from
            self.pending_promotion_square = None
            self._promotion_rects = {}
            self._promotion_from = None
            self._resolve_promotion_pick(from_sq, sq, ptype)
            return
        self.match.promote(sq, ptype)
        self.pending_promotion_square = None
        self._promotion_rects = {}
        self._fire_move_landed()

    def _resolve_promotion_pick(self, from_sq, to_sq, ptype):
        if self.skillcheck_gate is not None and self.skillcheck_gate(from_sq, to_sq, ptype):
            return
        self.apply_gated_move(from_sq, to_sq, ptype)

    def cancel_unapplied_promotion(self):
        if self._promotion_from is None:
            return False
        self.pending_promotion_square = None
        self._promotion_rects = {}
        self._promotion_from = None
        return True

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
        self._sprite_geom = {}
        for k, surface in self.piece_images_scaled.items():
            bbox = surface.get_bounding_rect()
            self._sprite_geom[k] = {
                "bbox": bbox,
                "center": bbox.center,
                "top_center": (bbox.centerx, bbox.top),
            }

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
        self.update_drag_physics(now)
        self.effects.update(now)
        if self.review_ply is None:
            self._shake_dx, self._shake_dy = self.effects.shake_offset(now)
        else:
            self._shake_dx = self._shake_dy = 0
        if self._frame_surf is not None:
            self.window.blit(self._frame_surf,
                             (self.rect.x + self._shake_dx, self.rect.y + self._shake_dy))
        if self._checkerboard_surf is not None:
            self.window.blit(self._checkerboard_surf,
                             (self.board_offset_x + self._shake_dx,
                              self.board_offset_y + self._shake_dy))
        if self.review_ply is not None:
            self._draw_last_move_highlight()
            self._draw_annotation_highlights()
            self._draw_vertical_guides()
            self._draw_horizontal_guides()
            self.draw_pieces()
            self._draw_animations()
            self._draw_arrows()
            self._draw_review_cue()
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
        self._draw_restores(now)
        self.effects.draw_over(self.window, now)
        self._draw_arrows()
        self._draw_promotion_picker()

    def draw_drag_overlay(self):
        self.drag.draw_drag_overlay()

    def _cell_overlay(self, color):
        cs = int(self.cell_size)

        def build():
            surf = pg.Surface((cs, cs), pg.SRCALPHA)
            surf.fill(color)
            return surf
        return memoized_surface(_OVERLAY_CACHE, (cs, color), build)

    def _in_check_king_squares(self):
        history = self.match.move_history
        last_move = history[-1].move if history else None
        key = (len(history), last_move)
        if key != self._check_squares_key:
            self._check_squares_key = key
            result = []
            for row, col in product(range(self.SIZE), repeat=2):
                piece = self.match.piece_at(Square(row, col))
                if (piece is not None and piece.type == PieceType.KING
                        and self.match.is_in_check(piece.color)):
                    result.append(Square(row, col))
            self._check_squares = result
        return self._check_squares

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
            self.window.blit(self._cell_overlay(Colors.last_move), rect.topleft)

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
                self.window.blit(self._cell_overlay(Colors.premove), rect.topleft)
        chain_tip = self._active_chain_tip()
        if chain_tip is not None:
            rect = self._cell_rect(chain_tip.row, chain_tip.col)
            self.window.blit(self._cell_overlay(Colors.premove_chain_tip), rect.topleft)

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
        self.annotations.toggle_highlight(sq)

    def toggle_arrow(self, from_sq, to_sq):
        self.annotations.toggle_arrow(from_sq, to_sq)

    def is_square_annotated(self, sq):
        return self.annotations.is_square_annotated(sq)

    def clear_annotations(self):
        self.annotations.clear()

    def begin_right_press(self, pos):
        return self.annotations.begin_right_press(pos)

    def end_right_press(self, pos):
        self.annotations.end_right_press(pos)

    def _draw_annotation_highlights(self):
        self.annotations._draw_annotation_highlights()

    def _draw_review_cue(self):
        if self.read_only or self._frame_surf is None:
            return
        cue = cut_rect_surface(
            self.rect.size, scale_floor(self.PLATE_CUT, self.scale, 12),
            "#00000000", border=Colors.accent, border_width=2, corners=("tr",))
        self.window.blit(cue, self.rect.topleft)

    def _draw_arrows(self):
        self.annotations._draw_arrows()

    def _draw_check_highlight(self):
        for sq in self._in_check_king_squares():
            rect = self._cell_rect(sq.row, sq.col)
            self.window.blit(self._cell_overlay(Colors.check_fill), rect.topleft)
            pg.draw.rect(self.window, Colors.check, rect, 3)

    def _draw_hitmarker(self, rect, size, color, thick):
        def build():
            def render(surf, k):
                u = size * k / 40.0
                tw = max(int(thick * u), 2)
                for (x1, y1), (x2, y2) in (((7, 7), (14.5, 14.5)), ((33, 7), (25.5, 14.5)),
                                           ((7, 33), (14.5, 25.5)), ((33, 33), (25.5, 25.5))):
                    _draw_capsule(surf, (x1 * u, y1 * u), (x2 * u, y2 * u), tw, color)
            return supersample(size, render)
        surf = memoized_surface(_MARKER_CACHE, (size, color, thick, "hit"), build)
        self.window.blit(surf, (rect.centerx - size // 2, rect.centery - size // 2))

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
        hidden = {(a.from_sq if a.bump else a.to_sq) for a in self.animations}
        hidden |= self.effects.held_squares()
        hidden |= {a["sq"] for a in self._restore_anims}
        if self.aim_suppressed_square is not None:
            hidden.add(self.aim_suppressed_square)
        if self.dragging_from is not None:
            hidden.add(self.dragging_from)
        settle_sq = self.drag.settle_target()
        if settle_sq is not None:
            hidden.add(settle_sq)
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
            eased = math.sin(progress * math.pi) if a.bump else 1 - (1 - progress) ** 3
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
        if self.drag.is_settling():
            return True
        return bool(self.animations)

    def is_dragging(self):
        return self.drag.is_dragging()

    def is_restoring(self):
        return bool(self._restore_anims)

    def animation_dirty_rect(self):
        if not self.animations:
            return pg.Rect(self.rect)
        pad = int(self.cell_size)
        region = None
        for a in self.animations:
            span = self._cell_rect(a.from_sq.row, a.from_sq.col).union(
                self._cell_rect(a.to_sq.row, a.to_sq.col)).inflate(pad, pad)
            region = span if region is None else region.union(span)
        return region.clip(self.rect) if region is not None else pg.Rect(self.rect)

    def start_animation(self, from_sq, to_sq, piece, on_complete=None, bump=False):
        self.animations.append(PieceAnimation(
            from_sq=from_sq,
            to_sq=to_sq,
            piece=piece,
            start_ms=pg.time.get_ticks(),
            duration_ms=self.animation_duration_ms,
            on_complete=on_complete,
            bump=bump,
        ))

    def cancel_animations(self):
        self.animations = []
        self._restore_anims = []

    def cancel_drag_physics(self):
        self.drag.cancel_drag_physics()

    def jump_to_review_ply(self, ply):
        self.cancel_animations()
        self.effects.clear_transients()
        self._target_ply = None
        history_len = len(self.match.move_history)
        if ply is None or ply >= history_len:
            self.review_ply = None
        else:
            self.review_ply = max(0, ply)

    def review_anchor(self, history_len):
        if self._target_ply is not None:
            return self._target_ply
        if self.review_ply is not None:
            return self.review_ply
        return history_len

    def step_review(self, delta):
        history_len = len(self.match.move_history)
        if history_len == 0:
            return
        current = self.review_anchor(history_len)
        new_ply = max(0, min(history_len, current + delta))
        if new_ply == current:
            return
        if delta > 0:
            self.animate_review_ply(new_ply)
        else:
            self.jump_to_review_ply(new_ply)

    def reviewed_history(self):
        history = self.match.move_history
        if self.review_ply is None:
            return history
        return history[:self.review_ply]

    def scaled_capture_icons(self, strip_height):
        if not self.piece_images_original:
            return None
        size = max(int(strip_height * CAPTURE_ICON_FRACTION), 1)
        return {
            key: pg.transform.smoothscale(surface, (size, size))
            for key, surface in self.piece_images_original.items()
        }

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
            rook_from, rook_to = self._castle_rook_squares(
                move.from_sq.row, move.to_sq.col)
            rook_piece = Piece(PieceType.ROOK, move.piece.color)
            self.start_animation(rook_from, rook_to, rook_piece)

    def _selected_legal_targets(self):
        if self.selected_square is None:
            return []
        piece = self.match.piece_at(self.selected_square)
        if piece is None or piece.color != self.match.current_turn():
            return []
        return self.match.legal_moves_from(self.selected_square)

    def _is_target_locked(self, target):
        return (self.locked_targets is not None
                and self.selected_square is not None
                and self.locked_targets(self.selected_square, target))

    def _draw_move_indicators(self):
        for target in self._selected_legal_targets():
            if self.match.piece_at(target) is not None:
                continue
            if self._is_target_locked(target):
                self._draw_locked_marker(self._cell_rect(target.row, target.col))
            else:
                self._draw_dot(self._cell_rect(target.row, target.col))

    def _draw_front_markers(self):
        ep = self.match.en_passant_target
        sel = self.selected_square
        for target in self._selected_legal_targets():
            if self.match.piece_at(target) is not None:
                if self._is_target_locked(target):
                    self._draw_locked_marker(self._cell_rect(target.row, target.col))
                else:
                    self._draw_capture_hitmarker(self._cell_rect(target.row, target.col))
            elif ep is not None and target == ep and sel is not None:
                mover = self.match.piece_at(sel)
                if mover is not None and mover.type == PieceType.PAWN and target.col != sel.col:
                    captured = Square(sel.row, target.col)
                    self._draw_capture_hitmarker(self._cell_rect(captured.row, captured.col))
        now = pg.time.get_ticks()
        for sq in self._in_check_king_squares():
            dx, dy = self.effects.piece_offset(sq, now)
            self._draw_hitmarker(
                self._cell_rect(sq.row, sq.col).move(dx, dy),
                max(int(self.cell_size * self.KING_HITMARKER_SIZE_FACTOR),
                    self.HITMARKER_SIZE_MIN),
                Colors.accent, self.KING_HITMARKER_THICKNESS)

    def _marker_dot_surface(self, color):
        s = int(self.cell_size)
        radius = max(int(s * 0.16), 4)
        thickness = max(int(s * 0.05), 3)

        def build():
            def render(surf, k):
                pg.draw.circle(surf, color, (s * k // 2, s * k // 2),
                               radius * k, thickness * k)
            return supersample(s, render)
        return memoized_surface(_MARKER_CACHE, (s, color, "dot"), build)

    def _draw_dot(self, rect):
        self.window.blit(self._marker_dot_surface(Colors.move_indicator), rect.topleft)

    def _draw_locked_marker(self, rect):
        self.window.blit(self._marker_dot_surface(Colors.text_muted), rect.topleft)

    def _draw_capture_hitmarker(self, rect):
        self._draw_hitmarker(
            rect,
            max(int(self.cell_size * self.CAPTURE_HITMARKER_SIZE_FACTOR),
                self.HITMARKER_SIZE_MIN),
            Colors.accent, self.CAPTURE_HITMARKER_THICKNESS)

    def set_rect(self, rect, scale=1.0):
        self.scale = scale
        self.cancel_drag_physics()
        self.rect = pg.Rect(rect)
        self.effects.board_rect = pg.Rect(rect)
        self.frame_pad = scale_floor(self.PLATE_MARGIN, self.scale, self.PLATE_MARGIN_FLOOR)
        inner = rect.width - 2 * self.frame_pad
        cell_size = max(inner // self.SIZE, 1)
        if cell_size != self.cell_size:
            self.effects.clear_weapon_cache()
            opt = max(self.PROMOTION_OPTION_SIZE_MIN,
                      min(int(cell_size), self.PROMOTION_OPTION_SIZE_MAX))
            self._promo_hotkey_font = get_font(max(int(opt * 0.18), 9), bold=True, mono=True)
            self._promo_tag_font = get_font(max(int(opt * 0.14), 8), bold=True)
        self.cell_size = cell_size
        used = self.cell_size * self.SIZE
        free_w = rect.width - 2 * self.frame_pad - used
        free_h = rect.height - 2 * self.frame_pad - used
        self.board_offset_x = rect.x + self.frame_pad + free_w // 2
        self.board_offset_y = rect.y + self.frame_pad + free_h // 2
        self.rescale_pieces()
        self._render_text()
        self._build_frame_surface()
        self._build_checkerboard_surface()

    def _build_checkerboard_surface(self):
        gs = self.cell_size * self.SIZE
        if gs <= 0:
            self._checkerboard_surf = None
            return
        surf = pg.Surface((gs, gs)).convert()
        cs = self.cell_size
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                color = Colors.white_tile if (r + c) % 2 == 0 else Colors.black_tile
                pg.draw.rect(surf, color, pg.Rect(c * cs, r * cs, cs, cs))
        self._checkerboard_surf = surf

    def _build_frame_surface(self):
        if self.rect.width <= 0 or self.rect.height <= 0:
            self._frame_surf = None
            return
        plate = cut_rect_surface(
            self.rect.size, scale_floor(self.PLATE_CUT, self.scale, 12),
            Colors.surface, border=Colors.border, border_width=1, corners=("tr",))
        surf = plate.copy()
        gx = self.board_offset_x - self.rect.x
        gy = self.board_offset_y - self.rect.y
        gs = self.cell_size * self.SIZE
        pg.draw.rect(surf, Colors.border, pg.Rect(gx - 1, gy - 1, gs + 2, gs + 2), 1)
        self._frame_surf = surf

    def begin_press(self, pos):
        self.drag.begin_press(pos)

    def update_drag_physics(self, now):
        self.drag.update_drag_physics(now)

    def update_drag_motion(self, pos):
        self.drag.update_drag_motion(pos)

    def end_press(self):
        return self.drag.end_press()

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
        fcol = (x - self.board_offset_x) / self.cell_size
        frow = (y - self.board_offset_y) / self.cell_size
        if not (0 <= fcol < self.SIZE and 0 <= frow < self.SIZE):
            return None
        col = int(fcol)
        row = int(frow)
        if self.flipped:
            row = self.SIZE - 1 - row
            col = self.SIZE - 1 - col
        return Square(row, col)

    def handle_click(self, square):
        if self.read_only:
            return None
        if self.review_ply is not None:
            if self.highlighted_squares or self.arrows:
                self.clear_annotations()
            else:
                self.jump_to_review_ply(None)
            return None
        if self.is_animating():
            return None

        if self.pending_promotion_square is not None:
            return None

        grid = self._effective_grid()
        piece_at_clicked = grid[square.row][square.col]
        live_at_clicked = self.match.state[square.row][square.col]
        current_turn = self.match.current_turn()
        local_color = getattr(self.match, "local_color", None)

        if self.selected_square is None:
            chain_piece = self._premove_chain_piece(
                piece_at_clicked, live_at_clicked, current_turn, local_color)
            if chain_piece is not None:
                return self._premove_select(square, chain_piece)
            if self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
                return self._select_signal(self._try_select(square))
            if piece_at_clicked is None:
                resolved = self._resolve_chain_tip(square)
                if resolved != square:
                    resolved_piece = grid[resolved.row][resolved.col]
                    if resolved_piece is not None:
                        if resolved_piece.color == current_turn:
                            return self._select_signal(self._try_select(resolved))
                        return self._premove_select(resolved, resolved_piece)
                if self.premoves:
                    self.clear_premoves()
                    return "premove"
                return None
            return self._premove_select(square, piece_at_clicked)

        if square == self.selected_square:
            self.selected_square = None
            return None

        if self._should_switch_focus_to(square, grid, live_at_clicked, current_turn, local_color):
            self.selected_square = None
            if self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
                return self._select_signal(self._try_select(square))
            return self._premove_select(square, live_at_clicked)

        from_sq = self.selected_square
        self.selected_square = None
        live_from_piece = self.match.state[from_sq.row][from_sq.col]
        spec_from_piece = grid[from_sq.row][from_sq.col]
        chain_from_piece = self._premove_chain_piece(
            spec_from_piece, live_from_piece, current_turn, local_color)
        if chain_from_piece is not None:
            return "premove" if self._queue_premove(from_sq, square, chain_from_piece) else None
        if self._is_real_move_eligible(live_from_piece, current_turn, local_color):
            if self._skillcheck_armed() and self._is_promotion_move(from_sq, square):
                if self.locked_targets is not None and self.locked_targets(from_sq, square):
                    return None
                self._begin_promotion_pick(from_sq, square)
                return "promotion"
            if self.skillcheck_gate is not None and self.skillcheck_gate(from_sq, square):
                return "skillcheck"
            result = self.match.try_move(from_sq, square)
            if not result.legal:
                return None
            self._start_move_animation(from_sq, square, result.promotion_required)
            return "move"

        if spec_from_piece is None:
            return None
        return "premove" if self._queue_premove(from_sq, square, spec_from_piece) else None

    @staticmethod
    def _select_signal(selected):
        return "select" if selected else None

    def _premove_select(self, square, piece):
        return "premove" if self._try_select_for_premove(square, piece) else None

    def apply_gated_move(self, from_sq, to_sq, promo_type=None):
        result = self.match.try_move(from_sq, to_sq)
        if not result.legal:
            return result
        if result.promotion_required and promo_type is not None:
            self.match.promote(to_sq, promo_type)
            self._start_move_animation(from_sq, to_sq, promotion_required=False)
        else:
            self._start_move_animation(from_sq, to_sq, result.promotion_required)
        return result

    def _skillcheck_armed(self):
        return self.skillcheck_armed is not None and self.skillcheck_armed()

    def _is_promotion_move(self, from_sq, to_sq):
        piece = self.match.piece_at(from_sq)
        if piece is None or piece.type != PieceType.PAWN:
            return False
        if to_sq.row not in (0, self.SIZE - 1):
            return False
        return to_sq in self.match.legal_moves_from(from_sq)

    def _begin_promotion_pick(self, from_sq, to_sq):
        self.selected_square = None
        self.drag.clear_drag_state()
        self.pending_promotion_square = to_sq
        self._promotion_from = from_sq

    def cell_rect(self, square):
        return self._cell_rect(square.row, square.col)

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
        if not self._is_real_move_eligible(live_at_clicked, current_turn, local_color):
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
            return False
        if self.premove_color is not None and self.premove_color != piece.color:
            self.clear_premoves()
        self.selected_square = square
        return True

    def _queue_premove(self, from_sq, to_sq, piece):
        if from_sq == to_sq:
            return False
        if not piece_can_pseudo_reach(piece, from_sq, to_sq):
            return False
        if self.premove_color is not None and self.premove_color != piece.color:
            self.clear_premoves()
        self.premoves.append(Premove(from_sq, to_sq, piece))
        self.premove_color = piece.color
        if self.on_premove_queued is not None:
            self.on_premove_queued(piece.type)
        return True

    def clear_premoves(self):
        self.premoves = []
        self.premove_color = None

    def try_apply_next_premove(self):
        if (not self.premoves
                or self.premove_color != self.match.current_turn()
                or self.pending_promotion_square is not None
                or self.is_animating()):
            return False
        pm = self.premoves[0]
        if self.skillcheck_gate is not None and self.skillcheck_gate(pm.from_sq, pm.to_sq):
            self._consume_premove()
            return False
        result = self.match.try_move(pm.from_sq, pm.to_sq)
        if not result.legal:
            self.clear_premoves()
            return False
        self._consume_premove()
        self._start_move_animation(pm.from_sq, pm.to_sq, result.promotion_required)
        return True

    def _consume_premove(self):
        self.premoves.pop(0)
        if not self.premoves:
            self.premove_color = None

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

        own_drag = self.dragging_from is not None and from_sq == self.dragging_from
        if self.dragging_from is not None and not own_drag:
            self.drag.reanchor_for_remote(entry, from_sq, to_sq)

        if entry.move.captured is not None and self._capture_choreography(
                entry, from_sq, to_sq, moving_piece, on_complete, clear_drag=own_drag):
            return

        if own_drag:
            self.last_animation_completed_at_ms = pg.time.get_ticks()
            if entry.move.is_castle:
                self.drag.begin_settle(to_sq, None)
                self._start_castle_rook_animation(entry, from_sq, on_complete=on_complete)
            elif self.drag.is_active():
                self.drag.begin_settle(to_sq, on_complete)
            else:
                on_complete()
            return

        self.start_animation(from_sq, to_sq, moving_piece, on_complete=on_complete)

        if entry.move.is_castle:
            self._start_castle_rook_animation(entry, from_sq)

    @staticmethod
    def _castle_rook_squares(home_row, king_to_col):
        if king_to_col == 6:
            return Square(home_row, 7), Square(home_row, 5)
        return Square(home_row, 0), Square(home_row, 3)

    def _start_castle_rook_animation(self, entry, king_from_sq, on_complete=None):
        rook_from, rook_to = self._castle_rook_squares(
            king_from_sq.row, entry.move.to_sq.col)
        rook_piece = self.match.piece_at(rook_to)
        self.start_animation(rook_from, rook_to, rook_piece, on_complete=on_complete)

    def start_undo_animation(self, move):
        self.effects.clear_transients()
        moving_piece = self.match.piece_at(move.from_sq)
        if moving_piece is None:
            return
        self.start_animation(move.to_sq, move.from_sq, moving_piece)
        if move.is_castle:
            rook_home, rook_post = self._castle_rook_squares(
                move.from_sq.row, move.to_sq.col)
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

    def _capture_choreography(self, entry, from_sq, to_sq, moving_piece, on_complete,
                              clear_drag=True):
        captured = entry.move.captured
        color = moving_piece.color.value
        victim_sq = (Square(from_sq.row, to_sq.col)
                     if entry.move.is_en_passant else to_sq)
        attacker = self.piece_images_scaled.get((moving_piece.type, moving_piece.color))
        victim = self.piece_images_scaled.get((captured.type, captured.color))
        if attacker is None or victim is None or self.cell_size <= 0:
            self._on_capture_fire(entry, color, victim_sq)
            return False
        if clear_drag:
            self.drag.clear_drag_state()
        self.effects.capture(
            now_ms=pg.time.get_ticks(),
            attacker_type=moving_piece.type.value,
            attacker_surface=attacker, victim_surface=victim,
            from_sq=from_sq, victim_sq=victim_sq, to_sq=to_sq,
            cell_size=self.cell_size, power=self._capture_power(captured.type),
            occupied=self._occupied_squares(),
            on_fire=lambda: self._on_capture_fire(entry, color, victim_sq),
            on_slide=lambda: self.start_animation(from_sq, to_sq, moving_piece,
                                                  on_complete=on_complete),
        )
        return True

    def _occupied_squares(self):
        return {Square(r, c) for r, c in product(range(self.SIZE), repeat=2)
                if self.match.piece_at(Square(r, c)) is not None}

    def _on_capture_fire(self, entry, color, victim_sq):
        key = self.effects.register_kill(color, victim_sq, self.cell_size, pg.time.get_ticks())
        if self.shot_callback is not None:
            self.shot_callback(entry)
        if self.announce_callback is not None and key is not None:
            self.announce_callback(key, entry.move.captured)

    def trigger_skillcheck_fail(self, from_sq, to_sq, on_fire=None):
        piece = self.match.piece_at(from_sq)
        if piece is None or self.cell_size <= 0:
            return
        now = pg.time.get_ticks()
        victim_sq = self.capture_victim_square(piece, from_sq, to_sq)
        if victim_sq is None:
            self._start_bump_animation(from_sq, to_sq, piece)
            self.effects.swear(now, from_sq, self.cell_size)
            return
        victim = self.match.piece_at(victim_sq)
        power = self._capture_power(victim.type) if victim is not None else "med"
        fire_cb = (lambda: on_fire(piece.type)) if on_fire is not None else None
        self.effects.miss(
            now_ms=now,
            attacker_type=piece.type.value,
            from_sq=from_sq, victim_sq=victim_sq,
            cell_size=self.cell_size, power=power,
            occupied=self._occupied_squares(), on_fire=fire_cb)
        self.effects.swear(now, from_sq, self.cell_size)

    def capture_victim_square(self, piece, from_sq, to_sq):
        if self.match.piece_at(to_sq) is not None:
            return to_sq
        if piece.type == PieceType.PAWN and from_sq.col != to_sq.col:
            return Square(from_sq.row, to_sq.col)
        return None

    def _start_bump_animation(self, from_sq, to_sq, piece):
        self.cancel_animations()
        self.start_animation(from_sq, to_sq, piece, bump=True)

    def restore_piece(self, square):
        piece = self.match.piece_at(square)
        if piece is None or self.cell_size <= 0:
            return
        surface = self.piece_images_scaled.get((piece.type, piece.color))
        if surface is None:
            return
        self._restore_anims.append({"sq": square, "surf": surface,
                                    "start": pg.time.get_ticks(), "dur": RESTORE_MS})

    def _draw_restores(self, now):
        survivors = []
        for a in self._restore_anims:
            t = (now - a["start"]) / a["dur"]
            if t >= 1.0:
                continue
            survivors.append(a)
            self._blit_restore(a, *self._restore_state(t))
        self._restore_anims = survivors

    def _blit_restore(self, a, dy, alpha, angle):
        rect = self._cell_rect(a["sq"].row, a["sq"].col)
        img = a["surf"]
        top = rect.y + dy * self.cell_size
        if angle == 0.0:
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            self.window.blit(img, (rect.x, top))
            return
        base = (rect.x + img.get_width() / 2.0, top + img.get_height())
        rotated = pg.transform.rotozoom(img, angle, 1.0)
        if alpha < 255:
            rotated = rotated.copy()
            rotated.set_alpha(alpha)
        off = pg.math.Vector2(0.0, img.get_height() / 2.0).rotate(-angle)
        self.window.blit(rotated, rotated.get_rect(center=(base[0] - off.x, base[1] - off.y)))

    @staticmethod
    def _restore_state(t):
        alpha = int(255 * smoothstep(min(t / RESTORE_FADE_PORTION, 1.0)))
        if t < RESTORE_FALL_PORTION:
            p = t / RESTORE_FALL_PORTION
            return -RESTORE_DROP_FRAC * (1.0 - p * p), alpha, 0.0
        q = (t - RESTORE_FALL_PORTION) / (1.0 - RESTORE_FALL_PORTION)
        envelope = math.exp(-RESTORE_SETTLE_DECAY * q)
        dy = -RESTORE_REBOUND_FRAC * envelope * math.sin(RESTORE_SETTLE_WAVES * 2.0 * math.pi * q)
        angle = RESTORE_ROCK_DEG * envelope * math.sin(RESTORE_ROCK_WAVES * 2.0 * math.pi * q)
        return dy, alpha, angle

    def show_surrender_flag(self, color):
        if self.cell_size <= 0:
            return
        king_sq = king_square(self.match.state, color)
        if king_sq is not None:
            self.effects.raise_flag(king_sq, self.cell_size, pg.time.get_ticks())

    def show_checkmate_takeover(self, winner_label):
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

    def show_check_gun(self, entry):
        if self.cell_size <= 0 or self.review_ply is not None:
            return
        by_color = entry.move.piece.color
        king_color = opponent_of(by_color)
        king_sq = king_square(self.match.state, king_color)
        if king_sq is None:
            return
        checker = checking_square(self.match.state, king_sq, by_color)
        if checker is None:
            return
        self.effects.check(now_ms=pg.time.get_ticks(),
                           attacker_type=self.match.piece_at(checker).type.value,
                           king_sq=king_sq, from_sq=checker, cell_size=self.cell_size)

    def _try_select(self, square):
        piece = self.match.piece_at(square)
        if piece is None:
            return False
        if piece.color != self.match.current_turn():
            return False
        local_color = getattr(self.match, "local_color", None)
        if local_color is not None and piece.color != local_color:
            return False
        self.selected_square = square
        return True

    def _draw_selection_highlight(self):
        if self.selected_square is None:
            return
        if self.dragging_from is not None and self.selected_square == self.dragging_from:
            return
        if self.selected_square == self._active_chain_tip():
            return

        rect = self._cell_rect(self.selected_square.row, self.selected_square.col)
        wash = pg.Surface((rect.width, rect.height), pg.SRCALPHA)
        wash.fill(Colors.selection_fill)
        self.window.blit(wash, rect.topleft)
        pg.draw.rect(self.window, Colors.accent, rect, 4)
