import logging

import pygame as pg

from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.backend.utils import PROMO_LETTER_BY_TYPE, Square, coord_from_square
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.skillcheck.online import skillcheck_deadline_ms
from chessshootout.skillcheck.types import KIND_LABEL, SkillCheckKind, SkillCheckOutcome
from chessshootout.skillcheck.wheel import period_for_diff, placement_square


log = logging.getLogger("chess.frontend")


class SkillcheckSession:

    def __init__(self, screen):
        self.screen = screen
        self.app = screen.app
        self._skillcheck_log = []
        self._skillcheck_fired_at_ms = None
        self._clear_online_skillcheck_state()

    def _skillcheck_gate(self, from_sq, to_sq, promo_type=None):
        screen = self.screen
        if screen.skillcheck.is_locked(from_sq, to_sq) or self._skillcheck_swallows_input():
            return True
        if screen.variant == "online":
            return self._online_move_gate(from_sq, to_sq, promo_type)
        kind = screen.skillcheck.select(screen.match.backend, from_sq, to_sq)
        if kind == SkillCheckKind.NONE:
            return False
        diff = self._capture_value_diff(from_sq, to_sq, promo_type)
        seed = "{}:{}:{}{}{}{}:{}".format(
            screen.skillcheck.seed, len(screen.match.move_history),
            from_sq.row, from_sq.col, to_sq.row, to_sq.col, kind.value)
        return self._open_skillcheck_overlay(
            kind, seed, diff, self._skillcheck_deadline_ms(),
            from_sq, to_sq, promo_type, online=False)

    def _online_move_gate(self, from_sq, to_sq, promo_type=None):
        screen = self.screen
        if to_sq not in screen.match.legal_moves_from(from_sq):
            return False
        piece = screen.match.piece_at(from_sq)
        is_capture = screen.board.capture_victim_square(piece, from_sq, to_sq) is not None
        is_promotion = (piece.type == PieceType.PAWN
                        and to_sq.row in (0, screen.board.SIZE - 1))
        if not (is_capture or is_promotion):
            return False
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type is not None else None
        if self.app.coordinator.client is not None:
            self.app.coordinator.client.send_move(
                coord_from_square(from_sq), coord_from_square(to_sq), promo_letter)
        self._pending_online_move = (from_sq, to_sq, promo_type)
        return True

    def _open_skillcheck_overlay(self, kind, seed, value_diff, deadline_ms,
                                 from_sq, to_sq, promo_type, *, online,
                                 elapsed_ms=0, miss_count=0, passive=False):
        screen = self.screen
        target = self._skillcheck_render_square(kind, seed, value_diff, from_sq, to_sq)
        capturer = screen.match.piece_at(from_sq)
        controller = build_controller(
            kind, seed=seed, cell_rect=screen.board.cell_rect(target),
            now_ms=pg.time.get_ticks() - int(elapsed_ms), deadline_ms=deadline_ms,
            period_ms=period_for_diff(value_diff), value_diff=value_diff,
            victim_surface=self._victim_surface(target), board_rect=screen.board.rect,
            geom=lambda sq: screen.board.cell_rect(sq).center, from_sq=from_sq,
            victim_sq=target, attacker_type=capturer.type.value if capturer else None,
            shot_sound=self._shot_sound_for(capturer),
            on_shot=None if passive else (self._send_skillcheck_shot if online else None),
            miss_count=miss_count, passive=passive, audio=self.app.sound_manager)
        if controller is None:
            return False
        ply = len(screen.match.move_history) + 1
        self._skillcheck_fired_at_ms = pg.time.get_ticks() - int(elapsed_ms)
        log.info("skillcheck fired kind=%s ply=%d online=%s passive=%s",
                 kind.value, ply, online, passive)
        self._skillcheck_target = target
        screen.board.aim_suppressed_square = target if kind == SkillCheckKind.AIM else None
        on_done = self._on_online_skillcheck_done if online else self._on_skillcheck_done
        screen.skillcheck_overlay.start(
            controller, (from_sq, to_sq, promo_type, kind), on_done)
        return True

    def _open_spectate_overlay(self, kind, seed, value_diff, deadline_ms,
                               from_sq, to_sq, promo_type, *, elapsed_ms=0, miss_count=0):
        screen = self.screen
        screen.board.jump_to_review_ply(None)
        self._pending_online_move = None
        self._online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self._online_spectate_kind = kind
        self._online_skillcheck_opened_ms = pg.time.get_ticks() - int(elapsed_ms)
        self._open_skillcheck_overlay(
            kind, seed, value_diff, deadline_ms, from_sq, to_sq, promo_type,
            online=True, passive=True, elapsed_ms=elapsed_ms, miss_count=miss_count)

    def _skillcheck_swallows_input(self):
        overlay = self.screen.skillcheck_overlay
        return overlay.is_active() and not overlay.is_passive()

    def _sync_aim_check_gun(self):
        screen = self.screen
        fx = screen.board.effects
        victim = screen.board.aim_suppressed_square
        if victim is not None and screen.skillcheck_overlay.is_active():
            fx.aim_victim = victim
            fx.aim_victim_scale = screen.skillcheck_overlay.aim_victim_scale()
        else:
            fx.aim_victim = None
            fx.aim_victim_scale = 1.0

    def _send_skillcheck_shot(self, client_elapsed_ms):
        if self.app.coordinator.client is not None:
            self.app.coordinator.client.send_skill_check_shot(client_elapsed_ms)

    def _clear_online_skillcheck_state(self):
        self._skillcheck_target = None
        self._pending_online_move = None
        self._online_skillcheck = None
        self._online_spectate_kind = None
        self._online_skillcheck_opened_ms = None
        self._online_verdict_action = None

    def _teardown_skillcheck_overlay(self):
        screen = self.screen
        screen.skillcheck_overlay.cancel()
        screen.board.aim_suppressed_square = None
        self._skillcheck_target = None
        self._online_skillcheck = None
        self._online_spectate_kind = None
        self._online_skillcheck_opened_ms = None
        self._online_verdict_action = None

    def _on_online_skillcheck_done(self, context, landed):
        action = self._online_verdict_action
        self._online_verdict_action = None
        self.screen.board.aim_suppressed_square = None
        self._skillcheck_target = None
        if action is not None:
            action()

    def _skillcheck_render_square(self, kind, seed, value_diff, from_sq, to_sq):
        screen = self.screen
        if kind == SkillCheckKind.AIM:
            capturer = screen.match.piece_at(from_sq)
            if capturer is not None:
                victim_sq = screen.board.capture_victim_square(capturer, from_sq, to_sq)
                if victim_sq is not None:
                    return victim_sq
            return to_sq
        square = placement_square(seed, value_diff,
                                  self._placement_exclusions(from_sq, to_sq), screen.board.SIZE)
        return Square(square[0], square[1]) if square is not None else to_sq

    def _placement_exclusions(self, from_sq, to_sq):
        return {(from_sq.row, from_sq.col), (to_sq.row, to_sq.col)}

    def _victim_surface(self, square):
        screen = self.screen
        piece = screen.match.piece_at(square)
        if piece is None:
            return None
        return screen.board.piece_images_scaled.get((piece.type, piece.color))

    def _shot_sound_for(self, capturer):
        if capturer is None:
            return None
        piece_type = capturer.type
        return lambda: self.app.sound_manager.play_capture(piece_type)

    def _capture_value_diff(self, from_sq, to_sq, promo_type):
        screen = self.screen
        if promo_type is not None:
            return PIECE_VALUES[PieceType.PAWN] - PIECE_VALUES.get(promo_type, 0)
        capturer = screen.match.piece_at(from_sq)
        if capturer is None:
            return 0
        victim_sq = screen.board.capture_victim_square(capturer, from_sq, to_sq)
        if victim_sq is not None:
            victim = screen.match.piece_at(victim_sq)
            return PIECE_VALUES.get(capturer.type, 0) - (
                PIECE_VALUES.get(victim.type, 0) if victim is not None else 0)
        return 0

    def _on_skillcheck_done(self, context, landed):
        screen = self.screen
        from_sq, to_sq = context[0], context[1]
        promo_type = context[2] if len(context) > 2 else None
        kind = context[3] if len(context) > 3 else None
        aim_victim = screen.board.aim_suppressed_square
        screen.board.aim_suppressed_square = None
        if landed:
            screen.board.apply_gated_move(from_sq, to_sq, promo_type)
            self._record_skillcheck(kind, True, len(screen.match.move_history))
        else:
            promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
            self._record_skillcheck(
                kind, False, len(screen.match.move_history) + 1,
                screen.match.backend.preview_san(from_sq, to_sq, promo_letter))
            screen.skillcheck.lock(from_sq, to_sq)
            log.info("skillcheck move locked from=%s to=%s",
                     coord_from_square(from_sq), coord_from_square(to_sq))
            screen.board.selected_square = None
            if screen.board.premove_color == screen.match.current_turn():
                screen.board.clear_premoves()
            screen.board.trigger_skillcheck_fail(
                from_sq, to_sq, on_fire=self._on_skillcheck_miss_fire)
            if aim_victim is not None:
                screen.board.restore_piece(aim_victim)

    def _on_skillcheck_miss_fire(self, piece_type):
        self.app.sound_manager.play_capture(piece_type)

    def _record_skillcheck(self, kind, won, ply, san=""):
        if kind is None:
            return
        kind_value = kind.value if isinstance(kind, SkillCheckKind) else kind
        elapsed_ms = (pg.time.get_ticks() - self._skillcheck_fired_at_ms
                      if self._skillcheck_fired_at_ms is not None else None)
        log.info("skillcheck resolved kind=%s ply=%d won=%s elapsed_ms=%s",
                 kind_value, ply, won, elapsed_ms)
        self._skillcheck_log.append(SkillCheckOutcome(ply, kind_value, won, san))

    def _drop_skillcheck_log_from(self, ply):
        self._skillcheck_log = [e for e in self._skillcheck_log if e.ply < ply]

    def _record_online_fail(self, pending, from_sq, to_sq):
        if pending is None:
            return
        promo_type = pending[2]
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
        self._record_skillcheck(
            pending[3], False, len(self.screen.match.move_history) + 1,
            self.screen.match.backend.preview_san(from_sq, to_sq, promo_letter))

    def _apply_resumed_skillcheck_log(self, wire):
        self._skillcheck_log = [
            SkillCheckOutcome(e["ply"], e["kind"], e["won"], e.get("san", ""))
            for e in wire]

    def _skillcheck_whiffs(self):
        whiffs = {}
        for outcome in self._skillcheck_log:
            if not outcome.won:
                whiffs.setdefault(outcome.ply, []).append(
                    (KIND_LABEL.get(outcome.kind, outcome.kind), outcome.san))
        return whiffs

    def _skillcheck_deadline_ms(self):
        time_control = self.screen._time_control
        initial = time_control[0] if time_control and time_control[0] else 0
        return int(skillcheck_deadline_ms(initial))
