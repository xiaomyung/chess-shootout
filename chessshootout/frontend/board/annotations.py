import math
from typing import Any, cast

import pygame as pg

from chessshootout.backend.utils import Square
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.server.protocol import MAX_SHARED_ARROWS


class Annotations:
    """
    The marks players draw on the board: highlighted squares and arrows, the
    player's own as well as the copy an opponent is sharing. It owns the
    right-drag gesture that creates them, the moderation flags on marks the
    server refused, and the drawing of all of it under the pieces
    """

    def __init__(self, board: Any) -> None:
        """
        Bind an annotation layer to the board that owns it, with nothing drawn
        yet. Own marks and the opponent's shared ones are kept in separate
        sets, so clearing or hiding one never disturbs the other

        :param board: the Board this belongs to, read for square geometry and
            the window, and told when a repaint is needed
        """
        self.board = board
        self.highlighted_squares: set[Square] = set()
        self.arrows: list[tuple[Square, Square]] = []
        self.opp_highlighted_squares: set[Square] = set()
        self.opp_arrows: list[tuple[Square, Square]] = []
        self.flagged: set[Square | tuple[Square, Square]] = set()
        self._arrow_cache: tuple[tuple[Any, ...], pg.Surface] | None = None
        self._right_drag_start_square: Square | None = None

    def toggle_highlight(self, sq: Square) -> bool:
        """
        Add or remove the highlight a plain right-click puts on a square.
        Taking a highlight away also drops any moderation flag it carried, so
        a re-drawn mark starts clean

        :param sq: square that was right-clicked
        :returns: True when the highlight was added, False when removed
        """
        self.highlighted_squares ^= {sq}
        present = sq in self.highlighted_squares
        if not present:
            self.flagged.discard(sq)
        return present

    def toggle_arrow(self, from_sq: Square, to_sq: Square) -> bool | None:
        """
        Add or remove the arrow a right-drag between two squares draws. Arrows
        are capped at MAX_SHARED_ARROWS, the same limit the server puts on a
        shared set, and hitting that cap is reported apart from an ordinary add
        or remove so the caller sends nothing

        :param from_sq: square the right-drag started on
        :param to_sq: square it ended on
        :returns: True when added, False when removed, None when the cap
            refused it
        """
        arrow = (from_sq, to_sq)
        if arrow in self.arrows:
            self.arrows.remove(arrow)
            self.flagged.discard(arrow)
            return False
        if len(self.arrows) >= MAX_SHARED_ARROWS:
            return None
        self.arrows.append(arrow)
        return True

    def flag_own(self, arrows: list[tuple[Square, Square]],
                 highlights: set[Square]) -> None:
        """
        Mark this player's own shapes as refused by moderation, which redraws
        them in the warning colour. It is the only way the player learns which
        marks stayed on their own screen instead of reaching the opponent

        :param arrows: refused arrows, as from/to square pairs
        :param highlights: refused highlighted squares
        """
        self.flagged.update(arrows)
        self.flagged.update(highlights)
        self.board.mark_needs_present()

    def is_square_annotated(self, sq: Square) -> bool:
        """
        Whether one of this player's own marks touches a square, as a highlight
        or as either end of an arrow. A left click on an unmarked square wipes
        the drawn plan, while a click on a marked one leaves it alone

        :param sq: square being clicked
        :returns: True when the square carries a mark
        """
        return sq in self.highlighted_squares or any(
            sq in (from_sq, to_sq) for from_sq, to_sq in self.arrows
        )

    def clear(self) -> None:
        """
        Wipe this player's own marks, their moderation flags and any right-drag
        in progress. The opponent's shared marks stay, since they are theirs to
        clear
        """
        self.highlighted_squares = set()
        self.arrows = []
        self.flagged = set()
        self._right_drag_start_square = None
        self.board.mark_needs_present()

    def clear_opp(self) -> None:
        """
        Wipe the opponent's shared marks, which happens when they stop sharing
        and the moment this player turns the hide-marks option on
        """
        self.opp_highlighted_squares = set()
        self.opp_arrows = []
        self.board.mark_needs_present()

    def set_opp(self, highlights: set[Square],
                arrows: list[tuple[Square, Square]]) -> None:
        """
        Replace the opponent's shared marks with the whole set they just sent.
        Sharing starts this way and a resume or a resync corrects itself this
        way, so the two boards agree without replaying every gesture

        :param highlights: every square the opponent has highlighted
        :param arrows: every arrow they have drawn, as from/to square pairs
        """
        self.opp_highlighted_squares = set(highlights)
        self.opp_arrows = list(arrows)
        self.board.mark_needs_present()

    def apply_opp_delta(self, action: str, kind: str, square: Square | None = None,
                        arrow: tuple[Square, Square] | None = None) -> None:
        """
        Apply the single mark the opponent just added or removed, the cheap
        update that keeps shared drawings in step between full states. Adding a
        mark that is already there, or removing one that is not, is a no-op, so
        a repeated message cannot corrupt the set

        :param action: "add" or "remove"
        :param kind: "highlight" or "arrow", which of the two sets is meant
        :param square: the square, for a highlight delta
        :param arrow: the from/to square pair, for an arrow delta
        """
        if kind == "highlight":
            if action == "add":
                self.opp_highlighted_squares.add(cast(Square, square))
            else:
                self.opp_highlighted_squares.discard(cast(Square, square))
            self.board.mark_needs_present()
            return
        if action == "add":
            if arrow not in self.opp_arrows:
                self.opp_arrows.append(cast(tuple[Square, Square], arrow))
                self.board.mark_needs_present()
        elif arrow in self.opp_arrows:
            self.opp_arrows.remove(arrow)
            self.board.mark_needs_present()

    def clear_all(self) -> None:
        """
        Take every mark off the board, this player's and the opponent's alike.
        A move landing does this, so each ply starts from a clean board
        """
        self.clear()
        self.clear_opp()

    def begin_right_press(self, pos: tuple[int, int]) -> Square | None:
        """
        Start the right-button gesture that draws a mark, remembering the
        square it began on. Until the button comes up again that square is the
        tail of a live preview arrow following the cursor

        :param pos: press position in window pixels
        :returns: the square the gesture started on, or None when the press
            missed the board
        """
        sq: Square | None = self.board.cell_at(pos)
        if sq is None:
            return None
        self._right_drag_start_square = sq
        return sq

    def end_right_press(self, pos: tuple[int, int]) -> tuple[Any, ...] | None:
        """
        Finish the right-button gesture and commit what it drew: a highlight
        when it started and ended on the same square, otherwise an arrow
        between the two. The report is what the game screen forwards to the
        opponent as a delta when sharing is on

        :param pos: release position in window pixels
        :returns: ("highlight", square, added) or ("arrow", from, to, added),
            where the last item is None when the arrow cap refused it, or None
            when the gesture began or ended off the board
        """
        start = self._right_drag_start_square
        self._right_drag_start_square = None
        if start is None:
            return None
        end = self.board.cell_at(pos)
        if end is None:
            return None
        if end == start:
            return ("highlight", start, self.toggle_highlight(start))
        return ("arrow", start, end, self.toggle_arrow(start, end))

    def _draw_annotation_highlights(self) -> None:
        """
        Fill every highlighted square, this player's in amber (or the warning
        colour when moderation refused them) and the opponent's in their own
        blue, so it is always clear who drew what
        """
        board = self.board
        for sq in self.highlighted_squares:
            rect = board._cell_rect(sq.row, sq.col)
            color = (Colors.annotation_highlight_flagged if sq in self.flagged
                     else Colors.annotation_highlight)
            board.window.blit(board._cell_overlay(color), rect.topleft)
        for sq in self.opp_highlighted_squares:
            rect = board._cell_rect(sq.row, sq.col)
            board.window.blit(board._cell_overlay(Colors.annotation_highlight_opp), rect.topleft)

    def _draw_arrows(self) -> None:
        """
        Draw every arrow on one supersampled layer over the board: this
        player's, the opponent's, and the preview of a right-drag still in
        progress. The layer is cached against the arrows and the board geometry
        and only redrawn when one of them changes
        """
        board = self.board
        if board.cell_size <= 0:
            self._arrow_cache = None
            return
        items = [(fr, to, Colors.annotation_arrow_flagged if (fr, to) in self.flagged
                  else Colors.annotation_arrow) for fr, to in self.arrows]
        items += [(fr, to, Colors.annotation_arrow_opp) for fr, to in self.opp_arrows]
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
            def render(layer: pg.Surface, scale: int) -> None:
                """
                Draw every arrow onto the oversized layer supersample() hands
                over, before it is scaled back down to board size

                :param layer: the oversized drawing surface
                :param scale: how many times larger that surface is
                """
                for fr, to, color in items:
                    self._render_arrow(layer, scale, fr, to, color)
            self._arrow_cache = (key, supersample(board.rect.size, render))
        board.window.blit(self._arrow_cache[1], board.rect.topleft)

    @staticmethod
    def _knight_arrow_corner(from_sq: Square, to_sq: Square) -> Square | None:
        """
        Find the corner square a knight's arrow should bend around, so a knight
        move is drawn as the L it really is instead of a diagonal line. Any
        other pair of squares wants a straight arrow

        :param from_sq: square the arrow starts on
        :param to_sq: square it points at
        :returns: the square to bend at, or None when the arrow is straight
        """
        dr = to_sq.row - from_sq.row
        dc = to_sq.col - from_sq.col
        if {abs(dr), abs(dc)} != {1, 2}:
            return None
        if abs(dr) == 2:
            return Square(to_sq.row, from_sq.col)
        return Square(from_sq.row, to_sq.col)

    def _render_arrow(self, layer: pg.Surface, scale: int, from_sq: Square,
                      to_sq: Square, color: str) -> None:
        """
        Draw one arrow between two squares onto the supersampled layer: a shaft
        that fades in from the tail, a bend for a knight move, and a head that
        the shaft stops just short of. Everything is sized off the cell, so an
        arrow looks the same on any board size

        :param layer: oversized layer being drawn into
        :param scale: how many times larger that layer is than the board
        :param from_sq: square the arrow starts on
        :param to_sq: square it points at
        :param color: hex colour string, which carries the arrow's alpha
        """
        board = self.board

        def pt(sq: Square) -> tuple[float, float]:
            """
            Place a square's centre on the layer, in layer pixels rather than
            window pixels

            :param sq: square to locate
            :returns: the centre point on the supersampled layer
            """
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
    def _gradient_capsule(rgb: tuple[int, int, int], length: float, width: int,
                          a0: float, a1: float) -> pg.Surface:
        """
        Build one rounded segment of an arrow shaft whose alpha ramps from one
        end to the other, which is what gives an arrow its faded tail. It is
        drawn flat and rotated into place by the caller

        :param rgb: shaft colour, without alpha
        :param length: segment length in layer pixels
        :param width: shaft thickness in layer pixels
        :param a0: alpha at the start of the segment, 0 to 255
        :param a1: alpha at its end, 0 to 255
        :returns: the horizontal capsule, ready to rotate
        """
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

    def _draw_shaft(self, surf: pg.Surface, rgb: tuple[int, int, int], max_a: int,
                    pts: list[tuple[float, float]], width: int) -> None:
        """
        Draw the shaft along a run of points, one capsule per segment, with the
        alpha climbing steadily from tail to head across the whole run. Segments
        are overlapped at the joints so a knight's bend has no gap in it

        :param surf: surface to draw the shaft on
        :param rgb: shaft colour, without alpha
        :param max_a: alpha at the head end, which the ramp works back from
        :param pts: shaft points in surface pixels, tail first
        :param width: shaft thickness in layer pixels
        """
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
