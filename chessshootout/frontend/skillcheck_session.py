import pygame as pg

from chessshootout.domain.match import ONLINE
from chessshootout.domain.pgn.load import parse_comment
from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.backend.utils import PROMO_LETTER_BY_TYPE, Square, coord_from_square
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.skillcheck.online import skillcheck_deadline_ms
from chessshootout.skillcheck.types import KIND_LABEL, SkillCheckKind, SkillCheckOutcome
from chessshootout.skillcheck.wheel import period_for_diff, placement_square


class SkillcheckSession:

    def __init__(self, frontend):
        self.frontend = frontend
        self._skillcheck_log = []
        self._clear_online_skillcheck_state()

    def _skillcheck_gate(self, from_sq, to_sq, promo_type=None):
        frontend = self.frontend
        if frontend.skillcheck.is_locked(from_sq, to_sq) or self._skillcheck_swallows_input():
            return True
        if frontend.mode == ONLINE:
            return self._online_move_gate(from_sq, to_sq, promo_type)
        kind = frontend.skillcheck.select(frontend.match.backend, from_sq, to_sq)
        if kind == SkillCheckKind.NONE:
            return False
        diff = self._capture_value_diff(from_sq, to_sq, promo_type)
        seed = "{}:{}:{}{}{}{}:{}".format(
            frontend.skillcheck.seed, len(frontend.match.move_history),
            from_sq.row, from_sq.col, to_sq.row, to_sq.col, kind.value)
        return self._open_skillcheck_overlay(
            kind, seed, diff, self._skillcheck_deadline_ms(),
            from_sq, to_sq, promo_type, online=False)

    def _online_move_gate(self, from_sq, to_sq, promo_type=None):
        frontend = self.frontend
        if to_sq not in frontend.match.legal_moves_from(from_sq):
            return False
        piece = frontend.match.piece_at(from_sq)
        is_capture = frontend.board.capture_victim_square(piece, from_sq, to_sq) is not None
        is_promotion = (piece.type == PieceType.PAWN
                        and to_sq.row in (0, frontend.board.SIZE - 1))
        if not (is_capture or is_promotion):
            return False
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type is not None else None
        if frontend.online_client is not None:
            frontend.online_client.send_move(
                coord_from_square(from_sq), coord_from_square(to_sq), promo_letter)
        self._pending_online_move = (from_sq, to_sq, promo_type)
        return True

    def _open_skillcheck_overlay(self, kind, seed, value_diff, deadline_ms,
                                 from_sq, to_sq, promo_type, *, online,
                                 elapsed_ms=0, miss_count=0, passive=False):
        frontend = self.frontend
        target = self._skillcheck_render_square(kind, seed, value_diff, from_sq, to_sq)
        capturer = frontend.match.piece_at(from_sq)
        controller = build_controller(
            kind, seed=seed, cell_rect=frontend.board.cell_rect(target),
            now_ms=pg.time.get_ticks() - int(elapsed_ms), deadline_ms=deadline_ms,
            period_ms=period_for_diff(value_diff), value_diff=value_diff,
            victim_surface=self._victim_surface(target), board_rect=frontend.board.rect,
            geom=lambda sq: frontend.board.cell_rect(sq).center, from_sq=from_sq,
            victim_sq=target, attacker_type=capturer.type.value if capturer else None,
            shot_sound=self._shot_sound_for(capturer),
            on_shot=None if passive else (self._send_skillcheck_shot if online else None),
            miss_count=miss_count, passive=passive, audio=frontend.sound_manager)
        if controller is None:
            return False
        self._skillcheck_target = target
        frontend.board.aim_suppressed_square = target if kind == SkillCheckKind.AIM else None
        on_done = self._on_online_skillcheck_done if online else self._on_skillcheck_done
        frontend.skillcheck_overlay.start(
            controller, (from_sq, to_sq, promo_type, kind), on_done)
        return True

    def _open_spectate_overlay(self, kind, seed, value_diff, deadline_ms,
                               from_sq, to_sq, promo_type, *, elapsed_ms=0, miss_count=0):
        frontend = self.frontend
        frontend.board.jump_to_review_ply(None)
        self._pending_online_move = None
        self._online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self._online_spectate_kind = kind
        self._online_skillcheck_opened_ms = pg.time.get_ticks() - int(elapsed_ms)
        self._open_skillcheck_overlay(
            kind, seed, value_diff, deadline_ms, from_sq, to_sq, promo_type,
            online=True, passive=True, elapsed_ms=elapsed_ms, miss_count=miss_count)

    def _skillcheck_swallows_input(self):
        overlay = self.frontend.skillcheck_overlay
        return overlay.is_active() and not overlay.is_passive()

    def _sync_aim_check_gun(self):
        frontend = self.frontend
        fx = frontend.board.effects
        victim = frontend.board.aim_suppressed_square
        if victim is not None and frontend.skillcheck_overlay.is_active():
            fx.aim_victim = victim
            fx.aim_victim_scale = frontend.skillcheck_overlay.aim_victim_scale()
        else:
            fx.aim_victim = None
            fx.aim_victim_scale = 1.0

    def _send_skillcheck_shot(self, client_elapsed_ms):
        if self.frontend.online_client is not None:
            self.frontend.online_client.send_skill_check_shot(client_elapsed_ms)

    def _clear_online_skillcheck_state(self):
        self._skillcheck_target = None
        self._pending_online_move = None
        self._online_skillcheck = None
        self._online_spectate_kind = None
        self._online_skillcheck_opened_ms = None
        self._online_verdict_action = None

    def _teardown_skillcheck_overlay(self):
        frontend = self.frontend
        frontend.skillcheck_overlay.cancel()
        frontend.board.aim_suppressed_square = None
        self._skillcheck_target = None
        self._online_skillcheck = None
        self._online_spectate_kind = None
        self._online_skillcheck_opened_ms = None
        self._online_verdict_action = None

    def _on_online_skillcheck_done(self, context, landed):
        action = self._online_verdict_action
        self._online_verdict_action = None
        self.frontend.board.aim_suppressed_square = None
        self._skillcheck_target = None
        if action is not None:
            action()

    def _skillcheck_render_square(self, kind, seed, value_diff, from_sq, to_sq):
        frontend = self.frontend
        if kind == SkillCheckKind.AIM:
            capturer = frontend.match.piece_at(from_sq)
            if capturer is not None:
                victim_sq = frontend.board.capture_victim_square(capturer, from_sq, to_sq)
                if victim_sq is not None:
                    return victim_sq
            return to_sq
        square = placement_square(seed, value_diff,
                                  self._placement_exclusions(from_sq, to_sq), frontend.board.SIZE)
        return Square(square[0], square[1]) if square is not None else to_sq

    def _placement_exclusions(self, from_sq, to_sq):
        return {(from_sq.row, from_sq.col), (to_sq.row, to_sq.col)}

    def _victim_surface(self, square):
        frontend = self.frontend
        piece = frontend.match.piece_at(square)
        if piece is None:
            return None
        return frontend.board.piece_images_scaled.get((piece.type, piece.color))

    def _shot_sound_for(self, capturer):
        if capturer is None:
            return None
        piece_type = capturer.type
        return lambda: self.frontend.sound_manager.play_capture(piece_type)

    def _capture_value_diff(self, from_sq, to_sq, promo_type):
        frontend = self.frontend
        if promo_type is not None:
            return PIECE_VALUES[PieceType.PAWN] - PIECE_VALUES.get(promo_type, 0)
        capturer = frontend.match.piece_at(from_sq)
        if capturer is None:
            return 0
        victim_sq = frontend.board.capture_victim_square(capturer, from_sq, to_sq)
        if victim_sq is not None:
            victim = frontend.match.piece_at(victim_sq)
            return PIECE_VALUES.get(capturer.type, 0) - (
                PIECE_VALUES.get(victim.type, 0) if victim is not None else 0)
        return 0

    def _on_skillcheck_done(self, context, landed):
        frontend = self.frontend
        from_sq, to_sq = context[0], context[1]
        promo_type = context[2] if len(context) > 2 else None
        kind = context[3] if len(context) > 3 else None
        aim_victim = frontend.board.aim_suppressed_square
        frontend.board.aim_suppressed_square = None
        if landed:
            frontend.board.apply_gated_move(from_sq, to_sq, promo_type)
            self._record_skillcheck(kind, True, len(frontend.match.move_history))
        else:
            promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
            self._record_skillcheck(
                kind, False, len(frontend.match.move_history) + 1,
                frontend.match.backend.preview_san(from_sq, to_sq, promo_letter))
            frontend.skillcheck.lock(from_sq, to_sq)
            frontend.board.selected_square = None
            if frontend.board.premove_color == frontend.match.current_turn():
                frontend.board.clear_premoves()
            frontend.board.trigger_skillcheck_fail(
                from_sq, to_sq, on_fire=self._on_skillcheck_miss_fire)
            if aim_victim is not None:
                frontend.board.restore_piece(aim_victim)

    def _on_skillcheck_miss_fire(self, piece_type):
        self.frontend.sound_manager.play_capture(piece_type)

    def _record_skillcheck(self, kind, won, ply, san=""):
        if kind is None:
            return
        kind_value = kind.value if isinstance(kind, SkillCheckKind) else kind
        self._skillcheck_log.append(SkillCheckOutcome(ply, kind_value, won, san))

    def _drop_skillcheck_log_from(self, ply):
        self._skillcheck_log = [e for e in self._skillcheck_log if e.ply < ply]

    def _record_online_fail(self, pending, from_sq, to_sq):
        if pending is None:
            return
        promo_type = pending[2]
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
        self._record_skillcheck(
            pending[3], False, len(self.frontend.match.move_history) + 1,
            self.frontend.match.backend.preview_san(from_sq, to_sq, promo_letter))

    def _apply_resumed_skillcheck_log(self, wire):
        self._skillcheck_log = [
            SkillCheckOutcome(e["ply"], e["kind"], e["won"], e.get("san", ""))
            for e in wire]

    def _rebuild_skillcheck_log(self, move_comments):
        self._skillcheck_log = []
        for index, comment in enumerate(move_comments):
            for kind, won, san in parse_comment(comment):
                self._skillcheck_log.append(
                    SkillCheckOutcome(index + 1, kind, won, san))

    def _skillcheck_whiffs(self):
        whiffs = {}
        for outcome in self._skillcheck_log:
            if not outcome.won:
                whiffs.setdefault(outcome.ply, []).append(
                    (KIND_LABEL.get(outcome.kind, outcome.kind), outcome.san))
        return whiffs

    def _skillcheck_deadline_ms(self):
        time_control = self.frontend._time_control
        initial = time_control[0] if time_control and time_control[0] else 0
        return int(skillcheck_deadline_ms(initial))
