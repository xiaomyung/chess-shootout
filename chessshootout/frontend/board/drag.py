import math
from collections.abc import Callable
from typing import Any, cast

import pygame as pg

from chessshootout.backend.pieces import Piece
from chessshootout.backend.utils import HistoryEntry, Square

DRAG_THRESHOLD_PX = 6
DRAG_GHOST_ALPHA_FRACTION = 0.30
LIFT_SCALE = 0.2
SHADOW_ALPHA = 90
SHADOW_OFFSET_FRACTION = 0.04

DRAG_K_SPRING = 90.0
DRAG_C_DAMP = 6.0
DRAG_K_FORCE = 0.22
DRAG_RG_FRACTION = 0.20
DRAG_TAU_ACC = 0.025
DRAG_TAU_LIFT = 0.10
DRAG_TAU_ENTRY = 0.06
DRAG_DT_MAX = 0.05
DRAG_SUBSTEP = 1.0 / 240.0
DRAG_OMEGA_MAX = 150.0
DRAG_SETTLE_K = 400.0
DRAG_SETTLE_C = 40.0
DRAG_SETTLE_MAX_T = 2.0


class DragPhysics:
    """
    The weight and swing of a piece the player is dragging. It owns the grab
    point on the sprite, the torsional spring that tilts the piece as the hand
    moves and the settle glide that drops it onto a square; the Board hands it
    every press, motion and release. The DRAG_K_* and LIFT_SCALE constants above
    are approved feel-tuning knobs, not derived quantities
    """

    def __init__(self, board: Any) -> None:
        """
        Bind the drag physics to the board that owns it. Nothing is being
        dragged yet -- drag state appears only once a press has travelled far
        enough to count as a drag

        :param board: the Board this belongs to, read for square geometry,
            piece sprites and the match, and written back through dragging_from
        """
        self.board = board
        self._drag: dict[str, Any] | None = None
        self._drag_cursor: tuple[int, int] | None = None
        self._press_pos: tuple[int, int] | None = None

    def begin_press(self, pos: tuple[int, int]) -> None:
        """
        Remember where the left button went down. That point is both the grab
        point on the sprite and the origin the drag threshold is measured from,
        so a click and a drag start out identically

        :param pos: press position in window pixels
        """
        self._press_pos = pos

    def _grab_local_for(self, from_sq: Square, press_pos: tuple[int, int] | None,
                        piece: Piece) -> tuple[float, float]:
        """
        Work out where on the sprite the player took hold, which decides how far
        the piece swings while it is carried. A press on visible art grabs
        exactly there; a press on a transparent corner, or no press at all,
        falls back to the top of the art so the piece hangs by its head

        :param from_sq: square the piece is being lifted from
        :param press_pos: press position in window pixels, or None when the drag
            did not start from a press
        :param piece: piece being lifted, which selects the sprite geometry
        :returns: grab point in sprite-local pixels
        """
        board = self.board
        geom = board._sprite_geom.get((piece.type, piece.color))
        if geom is None:
            return (board.cell_size / 2, board.cell_size / 2)
        if press_pos is None:
            return cast(tuple[float, float], geom["top_center"])
        rect = board._cell_rect(from_sq.row, from_sq.col)
        local = (press_pos[0] - rect.x, press_pos[1] - rect.y)
        surface = board.piece_images_scaled[(piece.type, piece.color)]
        w, h = surface.get_size()
        inside = 0 <= local[0] < w and 0 <= local[1] < h
        if inside and geom["bbox"].collidepoint(local) and \
                surface.get_at((int(local[0]), int(local[1]))).a > 0:
            return local
        return cast(tuple[float, float], geom["top_center"])

    def _begin_drag_physics(self, pos: tuple[int, int], now: int) -> None:
        """
        Turn a press on the selected square into a live drag, capturing the grab
        point, the lever arm from it to the sprite's centre of mass and the
        entry glide that pulls the piece from its home square to the cursor. A
        square with no piece on it leaves no state behind

        :param pos: cursor position in window pixels
        :param now: pygame tick count in milliseconds
        """
        board = self.board
        piece = board.match.piece_at(board.selected_square)
        if piece is None:
            return
        board.dragging_from = board.selected_square
        self._drag_cursor = pos
        geom = board._sprite_geom.get((piece.type, piece.color))
        com = geom["center"] if geom else (board.cell_size / 2, board.cell_size / 2)
        grab = self._grab_local_for(board.dragging_from, self._press_pos, piece)
        rect = board._cell_rect(board.dragging_from.row, board.dragging_from.col)
        entry_from = (rect.x + grab[0], rect.y + grab[1])
        self._drag = {
            "piece": piece,
            "grab_local": grab,
            "com_local": com,
            "r_local": (com[0] - grab[0], com[1] - grab[1]),
            "theta": 0.0,
            "omega": 0.0,
            "cursor": pos,
            "anchor": entry_from,
            "entry_from": entry_from,
            "entry": 0.0,
            "vel": (0.0, 0.0),
            "accel": (0.0, 0.0),
            "last_cursor": pos,
            "last_tick": now,
            "lift": 0.0,
            "phase": "drag",
        }

    def update_drag_physics(self, now: int) -> None:
        """
        Step the carried piece one frame: ease the lift and the entry glide,
        measure how fast the hand is moving and accelerating, then integrate the
        torsional spring that tilts the piece. A piece already dropping onto a
        square goes to the settle integrator instead, and a read-only board or a
        browsed position freezes the whole thing

        :param now: pygame tick count in milliseconds
        """
        board = self.board
        if board.read_only or board.review_ply is not None:
            return
        d = self._drag
        if d is None:
            return
        if d["phase"] == "settle":
            self._update_settle(d, now)
            return
        dt = (now - d["last_tick"]) / 1000.0
        d["last_tick"] = now
        if dt <= 0:
            return
        dt = min(dt, DRAG_DT_MAX)

        al = 1.0 - math.exp(-dt / DRAG_TAU_LIFT)
        d["lift"] += (1.0 - d["lift"]) * al
        ae = 1.0 - math.exp(-dt / DRAG_TAU_ENTRY)
        d["entry"] += (1.0 - d["entry"]) * ae
        ef, cur, e = d["entry_from"], d["cursor"], d["entry"]
        d["anchor"] = (ef[0] + (cur[0] - ef[0]) * e, ef[1] + (cur[1] - ef[1]) * e)

        cursor = d["cursor"]
        last = d["last_cursor"]
        raw_vx = (cursor[0] - last[0]) / dt
        raw_vy = (cursor[1] - last[1]) / dt
        d["last_cursor"] = cursor
        prev_vx, prev_vy = d["vel"]
        raw_ax = (raw_vx - prev_vx) / dt
        raw_ay = (raw_vy - prev_vy) / dt
        d["vel"] = (raw_vx, raw_vy)
        aa = 1.0 - math.exp(-dt / DRAG_TAU_ACC)
        ax = d["accel"][0] + (raw_ax - d["accel"][0]) * aa
        ay = d["accel"][1] + (raw_ay - d["accel"][1]) * aa
        d["accel"] = (ax, ay)

        rlx, rly = d["r_local"]
        rg = DRAG_RG_FRACTION * board.cell_size
        inertia = rg * rg + rlx * rlx + rly * rly
        k_force = DRAG_K_FORCE
        n = max(1, math.ceil(dt / DRAG_SUBSTEP))
        h = dt / n
        theta = d["theta"]
        omega = d["omega"]
        for _ in range(n):
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            rx = rlx * cos_t - rly * sin_t
            ry = rlx * sin_t + rly * cos_t
            torque = rx * (-ay) - ry * (-ax)
            forcing = k_force * torque / inertia
            alpha = -DRAG_K_SPRING * sin_t - DRAG_C_DAMP * omega + forcing
            omega += alpha * h
            omega = max(-DRAG_OMEGA_MAX, min(DRAG_OMEGA_MAX, omega))
            theta += omega * h
        d["theta"] = theta
        d["omega"] = omega

    def begin_settle(self, target_sq: Square,
                     on_settled: Callable[[], None] | None) -> None:
        """
        Start the glide that drops the carried piece onto a square and rocks it
        upright. Both endings come through here: a move that landed glides to
        its destination, and a drag that landed nothing glides home. The
        callback is what a landed move waits on, so the drop is seen before the
        move is announced

        :param target_sq: square the piece glides onto
        :param on_settled: called once when the piece has come to rest, or None
            when nothing is waiting on the drop
        """
        d = self._drag
        if d is None:
            return
        now = pg.time.get_ticks()
        theta = d["theta"]
        zoom = 1.0 + LIFT_SCALE * d["lift"]
        rlx, rly = d["r_local"]
        off = pg.math.Vector2(zoom * rlx, zoom * rly).rotate(math.degrees(theta))
        anchor = d["anchor"]
        d["phase"] = "settle"
        d["settle_to_sq"] = target_sq
        d["start_center"] = (anchor[0] + off.x, anchor[1] + off.y)
        d["screen_center"] = d["start_center"]
        d["theta_target"] = round(theta / (2 * math.pi)) * (2 * math.pi)
        d["settle_start_ms"] = now
        d["last_tick"] = now
        d["settle_dur_ms"] = self.board.animation_duration_ms
        d["on_settled"] = on_settled

    def _update_settle(self, d: dict[str, Any], now: int) -> None:
        """
        Step the drop glide: ease the piece toward the centre of its target
        square while a stiff spring brings the tilt back upright. It finishes
        when both are done, or once DRAG_SETTLE_MAX_T times the glide duration
        has passed, so a piece can never be left hanging. Drag state is cleared
        before the settle callback runs

        :param d: the live drag state, already known to be in the settle phase
        :param now: pygame tick count in milliseconds
        """
        board = self.board
        dt = max(0.0, min((now - d["last_tick"]) / 1000.0, DRAG_DT_MAX))
        d["last_tick"] = now
        dur = d["settle_dur_ms"]
        raw_t = 1.0 if dur <= 0 else (now - d["settle_start_ms"]) / dur
        t = min(max(raw_t, 0.0), 1.0)
        e = 1.0 - (1.0 - t) ** 3
        target = board._cell_rect(d["settle_to_sq"].row, d["settle_to_sq"].col).center
        sc = d["start_center"]
        d["screen_center"] = (sc[0] + (target[0] - sc[0]) * e,
                              sc[1] + (target[1] - sc[1]) * e)
        tt = d["theta_target"]
        if dt > 0:
            n = max(1, math.ceil(dt / DRAG_SUBSTEP))
            h = dt / n
            theta = d["theta"]
            omega = d["omega"]
            for _ in range(n):
                alpha = -DRAG_SETTLE_K * (theta - tt) - DRAG_SETTLE_C * omega
                omega += alpha * h
                theta += omega * h
            d["theta"] = theta
            d["omega"] = omega
            al = 1.0 - math.exp(-dt / DRAG_TAU_LIFT)
            d["lift"] += (0.0 - d["lift"]) * al
        settled = abs(d["theta"] - tt) < 0.02 and abs(d["omega"]) < 0.1
        full = raw_t >= DRAG_SETTLE_MAX_T
        if (t >= 1.0 and settled) or full:
            d["theta"] = tt
            cb = d["on_settled"]
            self.clear_drag_state()
            board.last_animation_completed_at_ms = now
            if cb is not None:
                cb()

    def clear_drag_state(self) -> None:
        """
        Drop every trace of the current drag, the board's dragging_from
        included, so that square goes back to being drawn by the ordinary piece
        pass
        """
        self._drag = None
        self.board.dragging_from = None
        self._drag_cursor = None

    def cancel_drag_physics(self) -> None:
        """
        Abandon a drag outright, which is what a resize, a new game or a screen
        being left does. A settle that was already running still fires its
        callback, so a move waiting on the drop is never lost
        """
        d = self._drag
        self.clear_drag_state()
        self._press_pos = None
        if d is not None and d["phase"] == "settle" and d["on_settled"] is not None:
            d["on_settled"]()

    def update_drag_motion(self, pos: tuple[int, int]) -> None:
        """
        Follow the cursor for a press that is becoming a drag or already is one.
        The press only turns into a drag once it has moved DRAG_THRESHOLD_PX,
        which is what keeps a plain click from lifting the piece; a read-only
        board, an open promotion picker and a browsed position all refuse

        :param pos: cursor position in window pixels
        """
        board = self.board
        if board.read_only:
            return
        if self._press_pos is None or board.selected_square is None:
            return
        if board.pending_promotion_square is not None:
            return
        if board.review_ply is not None:
            return
        if board.dragging_from is not None:
            self._drag_cursor = pos
            if self._drag is not None:
                self._drag["cursor"] = pos
            return
        dx = pos[0] - self._press_pos[0]
        dy = pos[1] - self._press_pos[1]
        if dx * dx + dy * dy < DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX:
            return
        self._begin_drag_physics(pos, pg.time.get_ticks())

    def end_press(self) -> bool:
        """
        Finish a left press. A drag whose move already landed is left to the
        settle it is running; a drag that landed nothing is sent gliding back to
        the square it came from, so a piece is never left stuck to the cursor

        :returns: True when a piece really was being dragged, which the screen
            uses to decide whether to play the drop sound
        """
        board = self.board
        was_dragging = board.dragging_from is not None
        self._press_pos = None
        if self._drag is not None and self._drag["phase"] == "settle":
            return was_dragging
        if (was_dragging and self._drag is not None
                and self._drag["phase"] == "drag"):
            self.begin_settle(board.dragging_from, None)
            return was_dragging
        self.clear_drag_state()
        return was_dragging

    def is_dragging(self) -> bool:
        """
        Whether a piece is off its square in the player's hand right now, the
        drop glide included. The board asks before it decides which squares to
        draw pieces on

        :returns: True while a piece is being carried or dropped
        """
        return self._drag is not None or self.board.dragging_from is not None

    def is_settling(self) -> bool:
        """
        Whether the carried piece is in its closing glide onto a square. The
        board counts this as animating, so a fresh click cannot cut the drop
        short

        :returns: True while the settle glide is running
        """
        return self._drag is not None and self._drag["phase"] == "settle"

    def is_active(self) -> bool:
        """
        Whether any drag state is held at all, carrying or settling. The move
        choreography asks this before handing a landing move over to a settle
        rather than to a normal piece animation

        :returns: True while drag state exists
        """
        return self._drag is not None

    def settle_target(self) -> Square | None:
        """
        The square a settling piece is heading for. The ordinary piece pass
        leaves that square empty until the glide is over, so the piece is never
        drawn twice at once

        :returns: the destination square, or None when nothing is settling
        """
        if self._drag is not None and self._drag["phase"] == "settle":
            return cast(Square, self._drag["settle_to_sq"])
        return None

    def draw_drag_overlay(self) -> None:
        """
        Draw the carried piece on top of everything else on the board. Nothing
        is drawn while the player is browsing the move history, where the board
        belongs to a past position rather than to the cursor
        """
        if self.board.review_ply is not None:
            return
        self._draw_dragged_piece()

    def _blit_lifted(self, surface: pg.Surface, pivot_local: tuple[float, float],
                     screen_pivot: tuple[float, float], angle_deg: float,
                     zoom: float) -> None:
        """
        Blit a rotated and scaled sprite so one chosen point of it lands exactly
        on a chosen point on screen. That is what keeps the grab point glued to
        the cursor however far the piece has swung

        :param surface: sprite to draw, either the piece or its shadow
        :param pivot_local: pivot in sprite-local pixels, the grab point while
            carrying and the centre of mass while settling
        :param screen_pivot: where that pivot must land, in window pixels
        :param angle_deg: rotation in degrees, counter-clockwise as pygame
            counts them
        :param zoom: scale factor, above 1 while the piece is lifted
        """
        rotated = pg.transform.rotozoom(surface, angle_deg, zoom)
        w, h = surface.get_size()
        sw, sh = w * zoom, h * zoom
        offset = pg.math.Vector2(pivot_local[0] * zoom - sw / 2,
                                 pivot_local[1] * zoom - sh / 2).rotate(-angle_deg)
        center = (screen_pivot[0] - offset.x, screen_pivot[1] - offset.y)
        self.board.window.blit(rotated, rotated.get_rect(center=center))

    def _draw_dragged_piece(self) -> None:
        """
        Draw the piece in hand: a faded ghost left behind on its home square, a
        shadow dropped below it and the piece itself tilted and enlarged by the
        lift. A settling piece pivots about its centre of mass instead of the
        grab point, so it lands squarely, and leaves no ghost behind
        """
        d = self._drag
        if d is None:
            return
        board = self.board
        piece = d["piece"]
        surface = board.piece_images_scaled[(piece.type, piece.color)]
        angle_deg = -math.degrees(d["theta"])
        zoom = 1.0 + LIFT_SCALE * d["lift"]
        if d["phase"] == "settle":
            pivot_local = d["com_local"]
            anchor = d["screen_center"]
        else:
            pivot_local = d["grab_local"]
            anchor = d["anchor"]
            ghost = surface.copy()
            ghost.set_alpha(int(255 * DRAG_GHOST_ALPHA_FRACTION))
            origin_rect = board._cell_rect(board.dragging_from.row, board.dragging_from.col)
            board.window.blit(ghost, origin_rect.topleft)
        shadow = surface.copy()
        shadow.fill((0, 0, 0, SHADOW_ALPHA), special_flags=pg.BLEND_RGBA_MULT)
        shadow_anchor = (anchor[0], anchor[1] + SHADOW_OFFSET_FRACTION * board.cell_size)
        self._blit_lifted(shadow, pivot_local, shadow_anchor, angle_deg, zoom)
        self._blit_lifted(surface, pivot_local, anchor, angle_deg, zoom)

    def reanchor_for_remote(self, entry: HistoryEntry, from_sq: Square,
                            to_sq: Square) -> None:
        """
        Handle the opponent capturing the very piece this player is holding. The
        piece is about to be shot off the board, so its drag is sent straight
        into a settle onto its own square and the capture choreography plays on
        a piece that is standing still. Any other remote move is left alone

        :param entry: history entry of the remote move that just landed
        :param from_sq: square that move came from
        :param to_sq: square it went to
        """
        if self._drag is None or entry.move.captured is None:
            return
        victim_sq = (Square(from_sq.row, to_sq.col)
                     if entry.move.is_en_passant else to_sq)
        if victim_sq == self.board.dragging_from:
            self.begin_settle(self.board.dragging_from, None)
