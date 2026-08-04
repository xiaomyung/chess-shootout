import logging

import pygame as pg

from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.backend.utils import PROMO_LETTER_BY_TYPE, Square, coord_from_square
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.skillcheck import mole
from chessshootout.skillcheck.online import skillcheck_deadline_ms
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome, whiffs_by_ply
from chessshootout.skillcheck.wheel import period_for_diff, placement_square


log = logging.getLogger("chess.frontend")

SUPPRESSING_KINDS = frozenset(
    {SkillCheckKind.AIM, SkillCheckKind.WHACK, SkillCheckKind.COMBO})


class SkillCheckSession:

    def __init__(self, screen):
        self.screen = screen
        self.app = screen.app
        self.skillcheck_log = []
        self._skillcheck_fired_at_ms = None
        self.clear_online_skillcheck_state()

    def skillcheck_gate(self, from_sq, to_sq, promo_type=None):
        screen = self.screen
        if screen.skillcheck.is_locked(from_sq, to_sq) or self.skillcheck_swallows_input():
            return True
        if screen.variant == Variant.ONLINE:
            return self._online_move_gate(from_sq, to_sq, promo_type)
        kind = screen.skillcheck.select(screen.match.backend, from_sq, to_sq)
        if kind == SkillCheckKind.NONE:
            return False
        diff = self._capture_value_diff(from_sq, to_sq, promo_type)
        seed = "{}:{}:{}{}{}{}:{}".format(
            screen.skillcheck.seed, len(screen.match.move_history),
            from_sq.row, from_sq.col, to_sq.row, to_sq.col, kind.value)
        return self.open_skillcheck_overlay(
            kind, seed, diff, self._skillcheck_deadline_ms(),
            from_sq, to_sq, promo_type, self._captured_value(from_sq, to_sq), online=False)

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
        self.app.coordinator.send_move(
            coord_from_square(from_sq), coord_from_square(to_sq), promo_letter)
        self.pending_online_move = (from_sq, to_sq, promo_type)
        return True

    def open_skillcheck_overlay(self, kind, seed, value_diff, deadline_ms,
                                from_sq, to_sq, promo_type, captured_value=0, *, online,
                                elapsed_ms=0, miss_count=0, progress=0, passive=False):
        screen = self.screen
        target = self._skillcheck_render_square(kind, seed, value_diff, from_sq, to_sq)
        capturer = screen.match.piece_at(from_sq)
        hole_squares = None
        if kind == SkillCheckKind.WHACK:
            hole_squares = mole.hole_squares(
                seed, captured_value, (to_sq.row, to_sq.col),
                self._occupied_squares(), screen.board.SIZE)
        attacker_surface = (self._piece_surface(capturer)
                            if kind == SkillCheckKind.COMBO else None)
        controller = build_controller(
            kind, seed=seed, cell_rect=screen.board.cell_rect(target),
            now_ms=pg.time.get_ticks() - int(elapsed_ms), deadline_ms=deadline_ms,
            period_ms=period_for_diff(value_diff), value_diff=value_diff,
            victim_surface=self._victim_surface(target), board_rect=screen.board.rect,
            geom=lambda sq: screen.board.cell_rect(sq).center, from_sq=from_sq,
            victim_sq=target, attacker_type=capturer.type.value if capturer else None,
            shot_sound=self._shot_sound_for(capturer),
            on_shot=None if passive else (self._send_skillcheck_shot if online else None),
            miss_count=miss_count, passive=passive, audio=self.app.sound_manager,
            hole_squares=hole_squares, captured_value=captured_value, progress=progress,
            attacker_surface=attacker_surface, on_hit_px=self._on_whack_hit_px)
        if controller is None:
            return False
        ply = len(screen.match.move_history) + 1
        self._skillcheck_fired_at_ms = pg.time.get_ticks() - int(elapsed_ms)
        log.info("skillcheck fired kind=%s ply=%d online=%s passive=%s",
                 kind.value, ply, online, passive)
        self.skillcheck_target = target
        self.active_kind = kind
        self.active_seed = seed
        if kind == SkillCheckKind.WHACK:
            self._whack_gun_from = from_sq
            self._whack_gun_type = capturer.type.value if capturer is not None else None
        screen.board.aim_suppressed_square = target if kind in SUPPRESSING_KINDS else None
        on_done = self._on_online_skillcheck_done if online else self._on_skillcheck_done
        screen.skillcheck_overlay.start(
            controller, (from_sq, to_sq, promo_type, kind), on_done)
        return True

    def open_spectate_overlay(self, kind, seed, value_diff, deadline_ms,
                              from_sq, to_sq, promo_type, captured_value=0, *,
                              elapsed_ms=0, miss_count=0, progress=0):
        screen = self.screen
        screen.board.jump_to_review_ply(None)
        self.pending_online_move = None
        self.online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self.online_spectate_kind = kind
        self.online_was_spectator = True
        self.online_skillcheck_opened_ms = pg.time.get_ticks() - int(elapsed_ms)
        self.open_skillcheck_overlay(
            kind, seed, value_diff, deadline_ms, from_sq, to_sq, promo_type, captured_value,
            online=True, passive=True, elapsed_ms=elapsed_ms, miss_count=miss_count,
            progress=progress)

    def skillcheck_swallows_input(self):
        overlay = self.screen.skillcheck_overlay
        return overlay.is_active() and not overlay.is_passive()

    def sync_aim_check_gun(self):
        screen = self.screen
        fx = screen.board.effects
        victim = screen.board.aim_suppressed_square
        if (victim is not None and self.active_kind == SkillCheckKind.AIM
                and screen.skillcheck_overlay.is_active()):
            fx.aim_victim = victim
            fx.aim_victim_scale = screen.skillcheck_overlay.aim_victim_scale()
        else:
            fx.aim_victim = None
            fx.aim_victim_scale = 1.0

    def sync_whack_gun(self):
        screen = self.screen
        overlay = screen.skillcheck_overlay
        if (self.active_kind != SkillCheckKind.WHACK or not overlay.is_active()
                or self._whack_gun_from is None):
            self.release_whack_gun()
            return
        fx = screen.board.effects
        now = pg.time.get_ticks()
        target_px = self._whack_aim_px(overlay)
        if not fx.has_gun_px():
            fx.hold_gun_px(now_ms=now, attacker_type=self._whack_gun_type,
                           from_sq=self._whack_gun_from, cell_size=screen.board.cell_size,
                           target_px=target_px)
        fx.aim_gun_px(target_px, now)

    def _whack_aim_px(self, overlay):
        if not overlay.is_passive():
            return pg.mouse.get_pos()
        if self._whack_impact_px is not None:
            return self._whack_impact_px
        if self.skillcheck_target is None:
            return None
        return self.screen.board.cell_rect(self.skillcheck_target).center

    def _on_whack_hit_px(self, px):
        self._whack_impact_px = px
        self.screen.board.effects.fire_gun_px(pg.time.get_ticks(), px)

    def release_whack_gun(self):
        self._clear_whack_gun_context()
        self.screen.board.effects.release_gun_px(pg.time.get_ticks())

    def _end_whack_gun(self, kind, landed):
        if kind != SkillCheckKind.WHACK or not landed:
            self.release_whack_gun()
            return
        self._clear_whack_gun_context()
        self.screen.board.effects.hand_off_gun_px()

    def _clear_whack_gun_context(self):
        self._whack_gun_from = None
        self._whack_gun_type = None
        self._whack_impact_px = None

    def _send_skillcheck_shot(self, client_elapsed_ms, direction=None, target=None):
        target_row, target_col = target if target is not None else (None, None)
        self.app.coordinator.send_skill_check_shot(
            client_elapsed_ms, direction=direction,
            target_row=target_row, target_col=target_col)

    def clear_online_skillcheck_state(self):
        self.skillcheck_target = None
        self.active_kind = None
        self.active_seed = None
        self.pending_online_move = None
        self.online_skillcheck = None
        self.online_spectate_kind = None
        self.online_was_spectator = False
        self.online_skillcheck_opened_ms = None
        self.online_verdict_action = None
        self._clear_whack_gun_context()

    def teardown_skillcheck_overlay(self):
        screen = self.screen
        screen.skillcheck_overlay.cancel()
        self.release_whack_gun()
        screen.board.aim_suppressed_square = None
        self.skillcheck_target = None
        self.active_kind = None
        self.active_seed = None
        self.online_skillcheck = None
        self.online_spectate_kind = None
        self.online_was_spectator = False
        self.online_skillcheck_opened_ms = None
        self.online_verdict_action = None

    def _on_online_skillcheck_done(self, context, landed):
        kind = context[3] if len(context) > 3 else None
        target = self.skillcheck_target
        seed = self.active_seed
        was_spectator = self.online_was_spectator
        self.online_was_spectator = False
        action = self.online_verdict_action
        self.online_verdict_action = None
        self._end_whack_gun(kind, landed)
        self.screen.board.aim_suppressed_square = None
        self.skillcheck_target = None
        self.active_kind = None
        self.active_seed = None
        if action is not None:
            action()
        if kind == SkillCheckKind.WHACK and landed is False and target is not None:
            self._show_whack_taunt(target, seed, not was_spectator)

    def _show_whack_taunt(self, square, seed, play_sound):
        self.screen.show_taunt(square, mole.pick_taunt(seed))
        if play_sound:
            self.app.sound_manager.play_mole_taunt()

    def _skillcheck_render_square(self, kind, seed, value_diff, from_sq, to_sq):
        screen = self.screen
        if kind in SUPPRESSING_KINDS:
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
        return self._piece_surface(self.screen.match.piece_at(square))

    def _piece_surface(self, piece):
        if piece is None:
            return None
        return self.screen.board.piece_images_scaled.get((piece.type, piece.color))

    def _occupied_squares(self):
        return mole.occupied_squares(self.screen.match.state, self.screen.board.SIZE)

    def _shot_sound_for(self, capturer):
        if capturer is None:
            return None
        piece_type = capturer.type
        return lambda: self.app.sound_manager.play_capture(piece_type)

    def _victim_piece(self, from_sq, to_sq):
        screen = self.screen
        capturer = screen.match.piece_at(from_sq)
        if capturer is None:
            return None
        victim_sq = screen.board.capture_victim_square(capturer, from_sq, to_sq)
        return screen.match.piece_at(victim_sq) if victim_sq is not None else None

    def _capture_value_diff(self, from_sq, to_sq, promo_type):
        if promo_type is not None:
            return PIECE_VALUES[PieceType.PAWN] - PIECE_VALUES.get(promo_type, 0)
        victim = self._victim_piece(from_sq, to_sq)
        if victim is None:
            return 0
        capturer = self.screen.match.piece_at(from_sq)
        return PIECE_VALUES.get(capturer.type, 0) - PIECE_VALUES.get(victim.type, 0)

    def _captured_value(self, from_sq, to_sq):
        victim = self._victim_piece(from_sq, to_sq)
        return PIECE_VALUES.get(victim.type, 0) if victim is not None else 0

    def _on_skillcheck_done(self, context, landed):
        screen = self.screen
        from_sq, to_sq = context[0], context[1]
        promo_type = context[2] if len(context) > 2 else None
        kind = context[3] if len(context) > 3 else None
        seed = self.active_seed
        aim_victim = screen.board.aim_suppressed_square
        self._end_whack_gun(kind, landed)
        screen.board.aim_suppressed_square = None
        self.active_kind = None
        self.active_seed = None
        if landed:
            screen.board.apply_gated_move(from_sq, to_sq, promo_type)
            self.record_skillcheck(kind, True, len(screen.match.move_history))
        else:
            promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
            self.record_skillcheck(
                kind, False, len(screen.match.move_history) + 1,
                screen.match.backend.preview_san(from_sq, to_sq, promo_letter))
            screen.skillcheck.lock(from_sq, to_sq)
            log.info("skillcheck move locked from=%s to=%s",
                     coord_from_square(from_sq), coord_from_square(to_sq))
            screen.board.selected_square = None
            if screen.board.premove_color == screen.match.current_turn():
                screen.board.clear_premoves()
            screen.board.trigger_skillcheck_fail(
                from_sq, to_sq, on_fire=self.on_skillcheck_miss_fire)
            if aim_victim is not None:
                screen.board.restore_piece(aim_victim, drop=kind != SkillCheckKind.WHACK)
            if kind == SkillCheckKind.WHACK:
                self._show_whack_taunt(aim_victim, seed, True)

    def on_skillcheck_miss_fire(self, piece_type):
        self.app.sound_manager.play_capture(piece_type)

    def record_skillcheck(self, kind, won, ply, san=""):
        if kind is None:
            return
        kind_value = kind.value if isinstance(kind, SkillCheckKind) else kind
        elapsed_ms = (pg.time.get_ticks() - self._skillcheck_fired_at_ms
                      if self._skillcheck_fired_at_ms is not None else None)
        log.info("skillcheck resolved kind=%s ply=%d won=%s elapsed_ms=%s",
                 kind_value, ply, won, elapsed_ms)
        self.skillcheck_log.append(SkillCheckOutcome(ply, kind_value, won, san))

    def drop_skillcheck_log_from(self, ply):
        self.skillcheck_log = [e for e in self.skillcheck_log if e.ply < ply]

    def record_online_fail(self, pending, from_sq, to_sq):
        if pending is None:
            return
        promo_type = pending[2]
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
        self.record_skillcheck(
            pending[3], False, len(self.screen.match.move_history) + 1,
            self.screen.match.backend.preview_san(from_sq, to_sq, promo_letter))

    def apply_resumed_skillcheck_log(self, wire):
        self.skillcheck_log = [
            SkillCheckOutcome(e["ply"], e["kind"], e["won"], e.get("san", ""))
            for e in wire]

    def skillcheck_whiffs(self):
        return whiffs_by_ply(self.skillcheck_log)

    def _skillcheck_deadline_ms(self):
        time_control = self.screen._time_control
        initial = time_control[0] if time_control and time_control[0] else 0
        return int(skillcheck_deadline_ms(initial))
