import math

import pygame as pg

from chessshootout.backend.utils import Square

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
    def __init__(self, board):
        self.board = board
        self._drag = None
        self._drag_cursor = None
        self._press_pos = None

    def begin_press(self, pos):
        self._press_pos = pos

    def _grab_local_for(self, from_sq, press_pos, piece):
        board = self.board
        geom = board._sprite_geom.get((piece.type, piece.color))
        if geom is None:
            return (board.cell_size / 2, board.cell_size / 2)
        if press_pos is None:
            return geom["top_center"]
        rect = board._cell_rect(from_sq.row, from_sq.col)
        local = (press_pos[0] - rect.x, press_pos[1] - rect.y)
        surface = board.piece_images_scaled[(piece.type, piece.color)]
        w, h = surface.get_size()
        inside = 0 <= local[0] < w and 0 <= local[1] < h
        if inside and geom["bbox"].collidepoint(local) and \
                surface.get_at((int(local[0]), int(local[1]))).a > 0:
            return local
        return geom["top_center"]

    def _begin_drag_physics(self, pos, now):
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

    def update_drag_physics(self, now):
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

    def begin_settle(self, target_sq, on_settled):
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

    def _update_settle(self, d, now):
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

    def clear_drag_state(self):
        self._drag = None
        self.board.dragging_from = None
        self._drag_cursor = None

    def cancel_drag_physics(self):
        d = self._drag
        self.clear_drag_state()
        self._press_pos = None
        if d is not None and d["phase"] == "settle" and d["on_settled"] is not None:
            d["on_settled"]()

    def update_drag_motion(self, pos):
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

    def end_press(self):
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

    def is_dragging(self):
        return self._drag is not None or self.board.dragging_from is not None

    def is_settling(self):
        return self._drag is not None and self._drag["phase"] == "settle"

    def is_active(self):
        return self._drag is not None

    def settle_target(self):
        if self._drag is not None and self._drag["phase"] == "settle":
            return self._drag["settle_to_sq"]
        return None

    def draw_drag_overlay(self):
        if self.board.review_ply is not None:
            return
        self._draw_dragged_piece()

    def _blit_lifted(self, surface, pivot_local, screen_pivot, angle_deg, zoom):
        rotated = pg.transform.rotozoom(surface, angle_deg, zoom)
        w, h = surface.get_size()
        sw, sh = w * zoom, h * zoom
        offset = pg.math.Vector2(pivot_local[0] * zoom - sw / 2,
                                 pivot_local[1] * zoom - sh / 2).rotate(-angle_deg)
        center = (screen_pivot[0] - offset.x, screen_pivot[1] - offset.y)
        self.board.window.blit(rotated, rotated.get_rect(center=center))

    def _draw_dragged_piece(self):
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

    def reanchor_for_remote(self, entry, from_sq, to_sq):
        if self._drag is None or entry.move.captured is None:
            return
        victim_sq = (Square(from_sq.row, to_sq.col)
                     if entry.move.is_en_passant else to_sq)
        if victim_sq == self.board.dragging_from:
            self.begin_settle(self.board.dragging_from, None)
