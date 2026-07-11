import math

import pygame as pg

from chessshootout.backend.utils import Square
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample


class Annotations:
    def __init__(self, board):
        self.board = board
        self.highlighted_squares = set()
        self.arrows = []
        self._arrow_cache = None
        self._right_drag_start_square = None

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

    def clear(self):
        self.highlighted_squares = set()
        self.arrows = []
        self._right_drag_start_square = None

    def begin_right_press(self, pos):
        sq = self.board.cell_at(pos)
        if sq is None:
            return None
        self._right_drag_start_square = sq
        return sq

    def end_right_press(self, pos):
        start = self._right_drag_start_square
        self._right_drag_start_square = None
        if start is None:
            return
        end = self.board.cell_at(pos)
        if end is None:
            return
        if end == start:
            self.toggle_highlight(start)
        else:
            self.toggle_arrow(start, end)

    def _draw_annotation_highlights(self):
        board = self.board
        for sq in self.highlighted_squares:
            rect = board._cell_rect(sq.row, sq.col)
            board.window.blit(board._cell_overlay(Colors.annotation_highlight), rect.topleft)

    def _draw_arrows(self):
        board = self.board
        if board.cell_size <= 0:
            self._arrow_cache = None
            return
        items = [(fr, to, Colors.annotation_arrow) for fr, to in self.arrows]
        if self._right_drag_start_square is not None:
            end_sq = board.cell_at(pg.mouse.get_pos())
            if end_sq is not None and end_sq != self._right_drag_start_square:
                items.append((self._right_drag_start_square, end_sq,
                              Colors.annotation_arrow_preview))
        if not items:
            self._arrow_cache = None
            return
        key = (tuple(items), board.cell_size, board.board_offset_x,
               board.board_offset_y, board.flipped, board.rect.size)
        if self._arrow_cache is None or self._arrow_cache[0] != key:
            def render(layer, scale):
                for fr, to, color in items:
                    self._render_arrow(layer, scale, fr, to, color)
            self._arrow_cache = (key, supersample(board.rect.size, render))
        board.window.blit(self._arrow_cache[1], board.rect.topleft)

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
        board = self.board

        def pt(sq):
            r = board._cell_rect_base(sq.row, sq.col)
            return ((r.centerx - board.rect.x) * scale, (r.centery - board.rect.y) * scale)

        from_pos = pt(from_sq)
        to_pos = pt(to_sq)
        width = max(int(board.cell_size * 0.16), 5) * scale
        head_size = max(int(board.cell_size * 0.38), 8) * scale
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
