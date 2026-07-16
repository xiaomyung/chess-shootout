import logging
import random
import uuid
from typing import NamedTuple

import pygame as pg

from chessshootout.backend.fen import apply_fen
from chessshootout.domain.match import Match, SINGLE_SCREEN, BOT, ONLINE
from chessshootout.domain.capture_summary import captured_by, material_advantage
from chessshootout.domain.pgn.load import format_time_control
from chessshootout.backend.pieces import PieceColor, PieceType, opponent_of
from chessshootout.backend.utils import (
    PROMO_TYPE_BY_LETTER, Square, coord_from_square, square_from_coord,
)
from chessshootout.infra import countries, env
from chessshootout.frontend.board import Board
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.help import HOTKEYS
from chessshootout.frontend.screens.base import Screen
from chessshootout.frontend.skillcheck.overlay import SkillCheckOverlay
from chessshootout.skillcheck.coordinator import SkillCheckCoordinator
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.frontend.panels.right import (
    RightMenu,
    CAPS as RIGHT_MENU_CAPS,
    UNTIMED_CAPS as RIGHT_MENU_UNTIMED_CAPS,
)
from chessshootout.frontend.panels.player_strip import (
    PlayerStrip, is_white, top_strip_color, refresh_capture_icons,
)
from chessshootout.frontend.modals.result import ResultMenu
from chessshootout.frontend.focus.arrow import (
    FocusArrow, FOCUS_EDGE_ZONE_PX, FOCUS_ARROW_D, LONG_AGO_MS,
)
from chessshootout.frontend.focus.time_line import TimeLine
from chessshootout.frontend.focus.transition import FocusTransition
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.visual import cache
from chessshootout.frontend.visual.backdrop import ArenaBackdrop
from chessshootout.frontend.visual.effects import TAKEOVER_TOTAL_MS
from chessshootout.frontend.game.result_flow import ResultFlow, score_str
from chessshootout.frontend.game.skillcheck_session import SkillCheckSession
from chessshootout.frontend.game.give_time import GiveTimeHold
from chessshootout.frontend.game.variant import MATCH_MODE_BY_VARIANT, Variant
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, Reason
from chessshootout.online.client import RECONNECT_TOTAL_SECONDS


log = logging.getLogger("chess.frontend")

OPPONENT_NAME_FOR_MODE = {
    SINGLE_SCREEN: "Player 2",
    BOT: "Bot",
}

PLACEHOLDER_RATING = "1500"

VARIANT_PILL_LABELS = {
    Variant.LOCAL: "Local",
    Variant.BOT: "Bot",
    Variant.ONLINE: "Online",
}

PROMOTION_KEYS = {
    pg.K_q: PieceType.QUEEN,
    pg.K_r: PieceType.ROOK,
    pg.K_b: PieceType.BISHOP,
    pg.K_n: PieceType.KNIGHT,
}

FOCUS_OFF_LINGER_MS = 2000
FOCUS_EDGE_ARROW_MARGIN = 16
FOCUS_ARROW_OFF_GAP = 6
FOCUS_HINT_MS = 1600
PRESENT_SETTLE_MS = 120

AUTO_FLIP_DELAY_MS = 200
RESULT_FADE_MS = 400
RESULT_MODAL_DELAY_MS = 500
RESULT_TAKEOVER_MS = TAKEOVER_TOTAL_MS
RESULT_FADE_MAX_ALPHA = 140

AUTO_END_GATE_FRACTION = 0.1

ONLINE_WIN_RESULT_BY_REASON = {
    Reason.CHECKMATE:   ("white_wins",                "black_wins"),
    Reason.TIMEOUT:     ("white_wins_on_time",        "black_wins_on_time"),
    Reason.RESIGNATION: ("white_wins_by_resignation", "black_wins_by_resignation"),
    Reason.ABANDONMENT: ("white_wins_by_abandonment", "black_wins_by_abandonment"),
}
ONLINE_WIN_REASONS = frozenset(ONLINE_WIN_RESULT_BY_REASON)
ONLINE_DRAW_REASONS = {
    Reason.DRAW_AGREEMENT, Reason.DRAW_STALEMATE, Reason.DRAW_REPETITION,
    Reason.DRAW_FIFTY_MOVE, Reason.DRAW_INSUFFICIENT_MATERIAL,
}
ONLINE_STATIC_RESULTS = {
    Reason.ABORTED, Reason.ABORTED_DISCONNECT, Reason.SERVER_SHUTDOWN,
}

ANIM_MS_DEFAULT = 180
ANIM_MS_MIN = 140
ANIM_MS_MAX = 280
ANIM_MS_PER_SECOND = 0.5

_RESULT_FADE_CACHE = cache.new_size_cache()


class OnlineCheck(NamedTuple):
    kind: SkillCheckKind
    seed: str
    value_diff: int
    deadline_ms: float
    from_sq: Square
    to_sq: Square
    promo_type: PieceType | None


def compute_animation_ms(initial_seconds):
    if initial_seconds is None or initial_seconds <= 0:
        return ANIM_MS_DEFAULT
    return max(ANIM_MS_MIN, min(ANIM_MS_MAX, int(initial_seconds * ANIM_MS_PER_SECOND)))


class GameScreen(Screen):

    name = "game"

    def __init__(self, app):
        super().__init__(app)
        window = app.window

        self.variant = Variant.LOCAL
        self.manual_result = None
        self.white_name = "Player 1"
        self.black_name = "Player 2"
        self.white_country = ""
        self.black_country = ""
        self._chosen_side = "white"
        self._time_control = None
        self._flag_fall_played = False
        self._strip_memo = {}
        self._result_first_seen_at_ms = None
        self._match_session_id = None
        self.backdrop = ArenaBackdrop()
        self._last_turn_for_flip = None
        self._first_move_deadline_ms = None
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self._focus_click_consumed = False

        self.match = Match()
        self.board = Board(window, self.match,
                           move_landed_callback=self._on_move_landed,
                           on_premove_queued=app.sound_manager.play_premove_queued,
                           shot_callback=self._on_shot_fired,
                           announce_callback=self._on_kill_announced)
        self.skillcheck = SkillCheckCoordinator()
        self.skillcheck_overlay = SkillCheckOverlay()
        self.skillcheck_session = SkillCheckSession(self)
        self.board.skillcheck_gate = self.skillcheck_session.skillcheck_gate
        self.board.skillcheck_armed = lambda: self.skillcheck.enabled
        self.board.locked_targets = self.skillcheck.is_locked

        self.result_flow = ResultFlow(self)
        self.give_time = GiveTimeHold(self)

        self.result_menu = ResultMenu(window, {
            "new_game": app._on_new_game,
            "open_pgn": self.result_flow.on_open_pgn,
            "menu": app._on_back_to_menu,
            "rematch": app.coordinator._on_rematch,
        })
        self.right_menu = RightMenu(window, self.match, {
            "undo": self._on_undo,
            "resign": self._on_resign,
            "draw": self._on_draw,
            "flip": self._on_flip,
            "menu": app._on_back_to_menu,
            "help": app._on_help,
            "give_time": self.give_time.on_give_time,
        }, board=self.board, buttons_provider=self._right_menu_buttons,
            disabled_keys_provider=self._right_menu_disabled_keys,
            whiffs_provider=self.skillcheck_session.skillcheck_whiffs,
            sounds=app.sound_manager)
        self.player_strip_top = PlayerStrip(window)
        self.player_strip_bottom = PlayerStrip(window)

        self.focus_mode = False
        self.focus_transition = None
        self.focus_arrow = FocusArrow()
        self.time_line = TimeLine()
        self._focus_panel_hover_ms = LONG_AGO_MS
        self._focus_hint_until_ms = 0

        self.result_flow.probe_games_dir_writable()

    @property
    def window(self):
        return self.app.window

    def _compute_layout(self):
        self.app._compute_layout()

    def enter(self, **payload):
        fen = payload.get("fen")
        side = payload.get("side")
        your_color = payload.get("your_color")
        self.variant = payload.get("variant") or (
            Variant.ONLINE if your_color is not None else Variant.LOCAL)
        if side is not None or fen is not None:
            self._chosen_side = "white"
            self.white_name = "Player 1"
            self.black_name = "Player 2"
            self.white_country = env.get_country()
            self.black_country = countries.random_code()
            self._time_control = None
            self._ensure_local_session()
        if side is not None:
            self._apply_start_config(payload)
        if your_color is not None:
            self._apply_online_start_config(payload)
        self._reset_to_new_game()
        if fen is not None:
            apply_fen(self.match.backend, fen)
        if your_color is not None:
            self.board.flipped = (your_color == "black")
            self.app.coordinator.subscribe(self)
        self._focus_hint_until_ms = pg.time.get_ticks() + FOCUS_HINT_MS
        log.info("game enter variant=%s tc=%s side=%s",
                 self.variant, self._time_control, self._chosen_side)

    def _apply_start_config(self, payload):
        self._chosen_side = payload["side"]
        nickname = (payload.get("nickname") or "").strip() or "Player 1"
        opponent_name = OPPONENT_NAME_FOR_MODE[SINGLE_SCREEN]
        self.white_name, self.black_name = (
            (nickname, opponent_name) if self._chosen_side == "white"
            else (opponent_name, nickname)
        )
        my_country = env.get_country()
        opp_country = countries.random_code()
        self.white_country, self.black_country = (
            (my_country, opp_country) if self._chosen_side == "white"
            else (opp_country, my_country)
        )
        time_minutes = payload.get("time_minutes")
        increment_seconds = payload.get("increment_seconds")
        self._time_control = (
            (time_minutes * 60, increment_seconds) if time_minutes is not None else None
        )
        self.skillcheck.reset(
            enabled=True,
            seed=f"local-{pg.time.get_ticks()}-{random.randint(0, 1 << 30)}")

    def _apply_online_start_config(self, payload):
        self._chosen_side = payload["your_color"]
        self.white_name = payload["white_name"]
        self.black_name = payload["black_name"]
        self.white_country = payload.get("white_country") or ""
        self.black_country = payload.get("black_country") or ""
        self._time_control = (payload["time_minutes"] * 60, payload["increment_seconds"])
        self.match.mode = ONLINE
        self.match.local_color = (PieceColor.WHITE if payload["your_color"] == "white"
                                  else PieceColor.BLACK)
        self.match.on_local_move_applied = self._on_local_move_applied
        self._match_session_id = payload.get("session_id") or str(uuid.uuid4())
        self.result_flow.series_scores = {
            payload["white_name"]: float(payload.get("white_score", 0.0)),
            payload["black_name"]: float(payload.get("black_score", 0.0)),
        }
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self.skillcheck.reset(enabled=True, seed="online")
        self.result_menu.set_online_mode(True)

    def _on_local_move_applied(self, from_sq, to_sq, promotion):
        self.app.coordinator.send_local_move(from_sq, to_sq, promotion)

    def on_app_exit(self):
        if self.current_result() is not None:
            self.result_flow.auto_save_pgn()

    def on_offer(self, kind):
        if kind == "rematch_request":
            self.result_menu.set_rematch_offered(True)

    def on_connection_status(self, payload):
        opp_state = payload.get("opp_state", "connected")
        if opp_state == "reconnecting":
            if self._opp_disconnected_at_ms is None:
                self._opp_disconnected_at_ms = pg.time.get_ticks()
        else:
            self._opp_disconnected_at_ms = None

    def on_give_time(self, payload):
        self._apply_clock_snap(payload, default_to_existing=False)
        added = float(payload.get("seconds_added", 0))
        granted_by = payload.get("granted_by")
        recipient_color = "black" if granted_by == "white" else "white"
        if granted_by == self._chosen_side:
            self.give_time.toast_for_giver(recipient_color, added)
        else:
            self.give_time.toast_for_receiver(granted_by, added)

    def on_resume(self, payload):
        self.match.new_game()
        for entry in payload.get("move_history", []):
            result = self.match.apply_san(entry["san"])
            if not result.legal:
                log.warning("resume: SAN replay failed at %r", entry.get("san"))
                apply_fen(self.match.backend, payload["fen"])
                break
        if self._time_control is not None:
            initial, incr = self._time_control
            self.match.setup_clock(initial, incr)
            self._apply_clock_snap(payload, default_to_existing=False)
        self.board.cancel_animations()
        self.board.selected_square = None
        self.board.clear_premoves()
        self.board.clear_annotations()
        self._adopt_resumed_result(payload)
        self.skillcheck_session.apply_resumed_skillcheck_log(payload.get("skillcheck_log", []))
        self._restore_online_skillcheck_state(payload)

    def on_takeback(self, payload):
        server_ply = payload.get("ply")
        expected = len(self.match.move_history) - 1
        if server_ply is not None and server_ply != expected:
            self.app.coordinator._begin_resync()
            return
        if self.match.move_history:
            self.skillcheck_session.drop_skillcheck_log_from(len(self.match.move_history))
            last = self.match.move_history[-1].move
            self.match.undo()
            self.board.start_undo_animation(last)
            self.app.sound_manager.play_undo()
            log.info("takeback applied ply=%d", len(self.match.move_history))
        self._apply_clock_snap(payload, default_to_existing=True)

    def _apply_clock_snap(self, payload, *, default_to_existing):
        clock_snap = payload.get("clock") or {}
        if self.match.clock is None:
            return
        white_default = self.match.clock.white_remaining if default_to_existing else 0.0
        black_default = self.match.clock.black_remaining if default_to_existing else 0.0
        self.match.clock.restore_from_server(
            clock_snap.get("white_remaining", white_default),
            clock_snap.get("black_remaining", black_default),
            clock_snap.get("running_for"),
        )

    def _is_my_open_check(self, from_sq, to_sq):
        return (self.skillcheck_session.online_skillcheck is not None
                and self.skillcheck_session.online_spectate_kind is None
                and self.skillcheck_session.online_skillcheck[:2] == (from_sq, to_sq))

    def _begin_online_verdict(self, won, action):
        self.skillcheck_session.online_skillcheck = None
        self.skillcheck_session.online_spectate_kind = None
        self.skillcheck_session.online_verdict_action = action
        self.skillcheck_overlay.resolve_online(won)

    def _apply_online_fail(self, from_sq, to_sq, aim_victim):
        self.skillcheck.lock(from_sq, to_sq)
        log.info("skillcheck move locked from=%s to=%s online=True",
                 coord_from_square(from_sq), coord_from_square(to_sq))
        self._apply_spectate_fail(from_sq, to_sq, aim_victim)

    def _apply_spectate_fail(self, from_sq, to_sq, aim_victim):
        self.board.trigger_skillcheck_fail(
            from_sq, to_sq, on_fire=self.skillcheck_session.on_skillcheck_miss_fire)
        if aim_victim is not None:
            self.board.restore_piece(aim_victim)

    def on_skillcheck_required(self, payload):
        if "kind" in payload:
            self._open_my_skillcheck(payload)
        else:
            self._resolve_my_skillcheck_failure(payload)

    @staticmethod
    def _decode_squares(payload):
        return square_from_coord(payload["from"]), square_from_coord(payload["to"])

    @staticmethod
    def _decode_check(payload):
        promo = payload.get("promotion")
        from_sq, to_sq = GameScreen._decode_squares(payload)
        return OnlineCheck(
            kind=SkillCheckKind(payload["kind"]),
            seed=payload["seed"],
            value_diff=int(payload["value_diff"]),
            deadline_ms=float(payload["deadline_ms"]),
            from_sq=from_sq,
            to_sq=to_sq,
            promo_type=PROMO_TYPE_BY_LETTER.get(promo) if promo else None,
        )

    def _open_my_skillcheck(self, payload):
        check = self._decode_check(payload)
        session = self.skillcheck_session
        session.pending_online_move = None
        session.online_skillcheck = (
            check.from_sq, check.to_sq, check.promo_type, check.kind)
        session.online_skillcheck_opened_ms = pg.time.get_ticks()
        session.open_skillcheck_overlay(
            *check, online=True,
            elapsed_ms=float(payload.get("elapsed_ms", 0.0)),
            miss_count=int(payload.get("miss_count", 0)))

    def _prepare_online_fail(self, payload):
        from_sq, to_sq = self._decode_squares(payload)
        pending = self.skillcheck_session.online_skillcheck
        self.skillcheck_session.record_online_fail(pending, from_sq, to_sq)
        aim_victim = self.board.aim_suppressed_square
        return from_sq, to_sq, aim_victim

    def _resolve_my_skillcheck_failure(self, payload):
        from_sq, to_sq, aim_victim = self._prepare_online_fail(payload)
        self.board.selected_square = None
        self._begin_online_verdict(
            False, lambda: self._apply_online_fail(from_sq, to_sq, aim_victim))

    def on_spectate(self, payload):
        if "kind" in payload:
            self._open_spectated_skillcheck(payload)
        elif "from" in payload:
            self._resolve_spectated_skillcheck_failure(payload)
        else:
            self._spectate_shot(payload)

    def _open_spectated_skillcheck(self, payload):
        self.skillcheck_session.open_spectate_overlay(*self._decode_check(payload))
        self.app.toast.show("Opponent is lining up a shot…")

    def _resolve_spectated_skillcheck_failure(self, payload):
        from_sq, to_sq, aim_victim = self._prepare_online_fail(payload)
        self.app.toast.show("Opponent missed!")
        self._begin_online_verdict(
            False, lambda: self._apply_spectate_fail(from_sq, to_sq, aim_victim))

    def _spectate_shot(self, payload):
        self.skillcheck_overlay.spectate_shot(
            float(payload["elapsed_ms"]), int(payload["miss_count"]), bool(payload["won"]))

    def _clear_online_move_locks(self, from_sq, to_sq):
        if self.variant != Variant.ONLINE:
            return
        self.skillcheck.clear_locks()
        if (self.skillcheck_session.pending_online_move is not None
                and self.skillcheck_session.pending_online_move[:2] == (from_sq, to_sq)):
            self.skillcheck_session.pending_online_move = None

    def on_remote_move(self, payload):
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        if payload.get("skill_check_kind") is not None:
            if self._is_my_open_check(from_sq, to_sq):
                self._begin_online_verdict(
                    True, lambda: self._apply_remote_move_payload(payload))
                return
            if self.skillcheck_session.online_spectate_kind is not None:
                self.app.toast.show("Opponent nailed it!")
                self._begin_online_verdict(
                    True, lambda: self._apply_remote_move_payload(payload))
                return
        self._apply_remote_move_payload(payload)

    def _apply_remote_move_payload(self, payload):
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        san = payload.get("san")
        last = self.match.move_history[-1] if self.match.move_history else None
        if last is not None and last.san == san:
            self._apply_clock_snap(payload, default_to_existing=True)
            self._clear_online_move_locks(from_sq, to_sq)
            return
        server_ply = payload.get("ply")
        expected = len(self.match.move_history) + 1
        if server_ply is not None and server_ply != expected:
            self.app.coordinator._begin_resync()
            return
        self._apply_clock_snap(payload, default_to_existing=True)
        promo = payload.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        result = self.match.apply_remote_move(from_sq, to_sq, promo_type)
        if result.legal:
            self._first_move_deadline_ms = None
            self.board.animate_remote_move(from_sq, to_sq)
            self._clear_online_move_locks(from_sq, to_sq)
            kind = payload.get("skill_check_kind")
            if kind is not None:
                self.skillcheck_session.record_skillcheck(
                    kind, bool(payload.get("skill_check_won")),
                    payload.get("ply") or len(self.match.move_history))
        else:
            self.app.coordinator._begin_resync()

    def on_result(self, payload):
        if self.manual_result is not None:
            return
        reason = payload.get("reason", "")
        if not self._apply_online_result(reason, payload.get("winner_color")):
            return
        coordinator = self.app.coordinator
        self._first_move_deadline_ms = None
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        coordinator.offer_banners.clear()
        self.skillcheck_session.pending_online_move = None
        pending_action = self.skillcheck_session.online_verdict_action
        self.skillcheck_session.online_verdict_action = None
        try:
            if pending_action is not None:
                pending_action()
            self.skillcheck_session.teardown_skillcheck_overlay()
        except Exception:
            log.exception("online result verdict/teardown failed")
            coordinator._begin_resync()
        if reason == "timeout" and not self._flag_fall_played:
            self._flag_fall_played = True
            self.app.sound_manager.play_flag_fall()

    def _apply_online_result(self, reason, winner):
        if self.manual_result is not None:
            return False
        if reason in ONLINE_WIN_REASONS:
            white_code, black_code = ONLINE_WIN_RESULT_BY_REASON[reason]
            self.manual_result = white_code if winner == "white" else black_code
        elif reason in ONLINE_DRAW_REASONS or reason in ONLINE_STATIC_RESULTS:
            self.manual_result = reason
        else:
            return False
        self.result_flow.on_result_final(self.manual_result)
        return True

    def _adopt_resumed_result(self, payload):
        reason = payload.get("result_reason") or ""
        self._apply_online_result(reason, payload.get("result_winner"))

    def _restore_online_skillcheck_state(self, payload):
        self.skillcheck_session.teardown_skillcheck_overlay()
        self.skillcheck_session.pending_online_move = None
        self.skillcheck.clear_locks()
        for lock in payload.get("skillcheck_locks", []):
            self.skillcheck.lock(square_from_coord(lock["from_sq"]),
                                 square_from_coord(lock["to_sq"]))
        pending = payload.get("pending_skillcheck")
        if pending is not None:
            self._restore_pending_skillcheck(pending)

    def _restore_pending_skillcheck(self, pending):
        kind = SkillCheckKind(pending["kind"])
        from_sq = square_from_coord(pending["from_sq"])
        to_sq = square_from_coord(pending["to_sq"])
        promo = pending.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        elapsed_ms = float(pending.get("elapsed_ms", 0.0))
        miss_count = int(pending.get("miss_count", 0))
        if pending["color"] != self._chosen_side:
            self.skillcheck_session.open_spectate_overlay(
                kind, pending["seed"], int(pending["value_diff"]),
                float(pending["deadline_ms"]), from_sq, to_sq, promo_type,
                elapsed_ms=elapsed_ms, miss_count=miss_count)
            self.app.toast.show("Opponent is lining up a shot…")
            return
        self.skillcheck_session.online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self.skillcheck_session.online_skillcheck_opened_ms = pg.time.get_ticks() - int(elapsed_ms)
        self.skillcheck_session.open_skillcheck_overlay(
            kind, pending["seed"], int(pending["value_diff"]),
            float(pending["deadline_ms"]), from_sq, to_sq, promo_type, online=True,
            elapsed_ms=elapsed_ms, miss_count=miss_count)

    def exit(self):
        super().exit()
        self.app.coordinator.unsubscribe(self)
        did_focus = self.focus_mode or self.focus_transition is not None
        if did_focus:
            self._force_focus_off_instant()
        was_dragging = self.board.is_dragging()
        self.board.cancel_drag_physics()
        self.board.end_press()
        had_premoves = bool(self.board.premoves)
        self.board.clear_premoves()
        had_annotations = bool(self.board.highlighted_squares or self.board.arrows)
        self.board.clear_annotations()
        overlay_active = self.skillcheck_overlay.is_active()
        if overlay_active:
            self.skillcheck_session.teardown_skillcheck_overlay()
        if did_focus or was_dragging or had_premoves or had_annotations or overlay_active:
            log.debug(
                "game exit teardown focus=%s drag=%s premoves=%s annotations=%s skillcheck=%s",
                did_focus, was_dragging, had_premoves, had_annotations, overlay_active)

    def update(self, now):
        if self.skillcheck_overlay.is_active() and self.current_result() is not None:
            self.skillcheck_session.teardown_skillcheck_overlay()
        self._maybe_play_flag_fall()
        if self.game_live():
            self.match.tick_clock()
        post_animation_settled = (
            not self.board.is_animating()
            and not self.board.effects.captures
            and now - self.board.last_animation_completed_at_ms >= AUTO_FLIP_DELAY_MS
        )
        if (self.variant == Variant.LOCAL
                and self.current_result() is None
                and post_animation_settled):
            current = self.match.current_turn()
            if current != self._last_turn_for_flip:
                self.board.flipped = (current == PieceColor.BLACK)
                self._last_turn_for_flip = current
        if (self.game_live()
                and post_animation_settled
                and self.skillcheck_session.pending_online_move is None
                and not self.skillcheck_session.skillcheck_swallows_input()):
            self.board.try_apply_next_premove()
        return None

    def _maybe_play_flag_fall(self):
        if self._flag_fall_played:
            return
        clock = self.match.clock
        if clock is None or clock.flagged is None:
            return
        self._flag_fall_played = True
        local = self.match.local_color
        if self.variant == Variant.ONLINE and local is not None and clock.flagged != local:
            self.app.sound_manager.play_you_win()
        else:
            self.app.sound_manager.play_flag_fall()

    def relayout(self, size):
        window_width, window_height = size
        r = compute_layout(
            window_width, window_height, mode=self.name, focus_mode=self.focus_mode,
            focus_show=self._focus_show(), board_size=self.board.SIZE)
        self.board.set_rect(r.board_rect, scale=r.scale)
        self.right_menu.set_rect(r.menu_rect, scale=r.scale)
        self.player_strip_top.set_rect(r.top_strip_rect, scale=r.scale)
        self.player_strip_bottom.set_rect(r.bottom_strip_rect, scale=r.scale)
        self.result_menu.set_rect(r.result_rect)
        skillcheck_target = self.skillcheck_session.skillcheck_target
        if self.skillcheck_overlay.is_active() and skillcheck_target is not None:
            self.skillcheck_overlay.relayout(self.board.cell_rect(skillcheck_target))
            self.skillcheck_overlay.set_board_rect(self.board.rect)
        refresh_capture_icons(self.board, r.strip_height,
                              (self.player_strip_top, self.player_strip_bottom))

    def draw(self):
        app = self.app
        now = pg.time.get_ticks()
        if self.current_result() is not None and self.focus_mode:
            if self.focus_transition is None:
                self._toggle_focus(False)
            elif self.focus_transition.collapsing:
                self._force_focus_off_instant()
        if self.focus_transition is not None:
            tr = self.focus_transition
            tr.draw(now)
            if self._focus_show() == "line" and tr.cur_board_rect is not None:
                alpha = tr.cur_e if tr.collapsing else 1.0 - tr.cur_e
                self._draw_time_lines(tr.cur_board_rect, alpha)
            if tr.done(now):
                self._finalize_focus_transition()
        elif self.focus_mode:
            show = self._focus_show()
            self._draw_game_scene(
                show_panel=False, show_strips=(show == "strips"),
                arrow_hook=lambda: self._draw_focus_edge_arrow(now),
                after_board=self._draw_time_lines if show == "line" else None)
            self.board.draw_drag_overlay()
            if self.board.effects.has_takeover():
                self.board.effects.draw_takeover(self.window, now)
            self.result_flow.update_result_pending()
        else:
            self._draw_game_scene(
                show_panel=True, show_strips=True,
                arrow_hook=lambda: self._update_focus_arrow_off(now))
            self.board.draw_drag_overlay()
            self.result_flow.update_result_pending()
            if not app.coordinator.match_found_modal.is_visible():
                show_modal = self._result_menu_should_show()
                if not show_modal and self.board.effects.has_takeover():
                    self.board.effects.draw_takeover(self.window, now)
                else:
                    self._draw_result_fade_overlay()
                if show_modal:
                    self.board.effects.clear_takeover()
                    self.result_flow.feed_result_menu()
                    self.result_menu.draw()

    def current_result(self):
        return self.result_flow.current_result()

    def game_live(self):
        return self.current_result() is None

    def board_interactive(self):
        return self.current_result() is None

    def swallows_input(self):
        return self.skillcheck_session.skillcheck_swallows_input()

    def forward_swallowed_event(self, event):
        self.skillcheck_overlay.handle_event(event)

    def modals(self):
        return [ModalSpec(self.app.help_modal)]

    def scrollables(self):
        return [self.right_menu]

    def caption(self):
        if self.variant == Variant.ONLINE:
            opp_name = self.white_name if self._chosen_side == "black" else self.black_name
            return f"Chess — vs {opp_name}"
        return ""

    def debug_state(self):
        return {
            "move_history_len": len(self.match.move_history),
            "result": self.current_result(),
            "variant": self.variant,
            "review_ply": self.board.review_ply,
            "focus_mode": self.focus_mode,
            "match_session_id": self._match_session_id,
        }

    def _forces_full_redraw(self):
        return (self.focus_transition is not None
                or self.skillcheck_overlay.is_active()
                or self.current_result() is not None
                or self.give_time.holding
                or self.board.is_dragging()
                or self.board.effects.is_active()
                or self.board.is_restoring()
                or self.board.pending_promotion_square is not None)

    def dirty_rects(self):
        if self._forces_full_redraw():
            return None
        rects = [
            self.player_strip_top.rect,
            self.player_strip_bottom.rect,
            self.right_menu.outer_rect,
        ]
        now = pg.time.get_ticks()
        if (self.board.is_animating()
                or now - self.board.last_animation_completed_at_ms < PRESENT_SETTLE_MS):
            rects.append(self.board.animation_dirty_rect())
        if self.focus_arrow.is_visible():
            rects.append(self.focus_arrow.dirty_rect())
        if self.focus_mode and self._focus_show() == "line":
            top_line, bottom_line = self.time_line.rects_for(self.board, self.board.rect)
            rects.extend([top_line, bottom_line])
        return rects

    def escape(self):
        if self.swallows_input():
            return True
        if not self.board_interactive():
            self.app._on_back_to_menu()
            return True
        if self.focus_mode or self.focus_transition is not None:
            self._toggle_focus(False)
            return True
        self._on_resign()
        return True

    def active_scrollable(self):
        if self._result_menu_should_show():
            return None
        if self.focus_mode or self.focus_transition is not None:
            return None
        return self.right_menu

    def handle_key(self, event):
        if self._handle_promotion_key(event):
            return True
        if event.key == pg.K_h:
            self._toggle_focus(not self.focus_mode)
            return True
        if getattr(event, "unicode", "") == "?":
            self.app.help_modal.show(HOTKEYS)
            return True
        if event.key == pg.K_f:
            self._on_flip()
            return True
        if event.key == pg.K_r:
            self._on_resign()
            return True
        if event.key == pg.K_d:
            self._on_draw()
            return True
        if event.key == pg.K_z:
            self._on_undo()
            return True
        if event.key == pg.K_g:
            self.give_time.tap_give_time()
            return True
        if event.key == pg.K_a:
            self.right_menu.toggle_section("actions")
            return True
        if event.key == pg.K_s:
            self.right_menu.toggle_section("signals")
            return True
        if event.key == pg.K_c and self.right_menu.chat_visible_provider():
            self.right_menu.toggle_section("chat")
            return True
        if event.key == pg.K_LEFT:
            self.board.step_review(-1)
            return True
        if event.key == pg.K_RIGHT:
            self.board.step_review(1)
            return True
        if event.key == pg.K_HOME:
            self.board.jump_to_review_ply(0)
            return True
        if event.key == pg.K_END:
            self.board.jump_to_review_ply(None)
            return True
        return False

    def _handle_promotion_key(self, event):
        if self.board.pending_promotion_square is None:
            return False
        chosen = PROMOTION_KEYS.get(event.key)
        if chosen is None:
            return False
        self.board.pick_promotion(chosen)
        return True

    def handle_click(self, pos):
        self._focus_click_consumed = False
        if self.focus_transition is not None:
            return False
        if (self.current_result() is not None
                and self._result_first_seen_at_ms is not None
                and not self._result_menu_should_show()):
            self._skip_result_fade()
            return False
        if (self.focus_arrow.is_visible() and self._focus_arrow_allowed()
                and self.focus_arrow.handle_click(pos)):
            self._toggle_focus(not self.focus_mode)
            self._focus_click_consumed = True
            self.app.input_router.suppress_click_sound()
            return True
        if not self.focus_mode and self.result_menu.handle_click(pos):
            return True
        if not self.focus_mode and self.right_menu.handle_click(pos):
            return True
        if self.current_result() is not None:
            return False
        if self.board.pending_promotion_square is not None:
            self.board.pick_promotion_at(pos)
            self.app.input_router.suppress_click_sound()
            return True
        square = self.board.cell_at(pos)
        if square is None:
            return False
        if self.board.review_ply is None and not self.board.is_square_annotated(square):
            self.board.clear_annotations()
        signal = self.board.handle_click(square)
        if signal:
            self.app.input_router.suppress_click_sound()
            if signal == "select":
                self.app.sound_manager.play_pickup()
            return True
        return False

    def handle_press(self, pos):
        if (self.current_result() is None
                and self.board.pending_promotion_square is None
                and not self._focus_click_consumed
                and self.focus_transition is None):
            self.board.begin_press(pos)
            return True
        return False

    def handle_motion(self, pos):
        self.board.update_drag_motion(pos)
        return True

    def handle_release(self, pos):
        was_dragging = self.board.dragging_from is not None
        if was_dragging and self.current_result() is None:
            self.app.input_router.mouse_left_clicked(pos, ui_click=False)
        self.board.end_press()
        if was_dragging and self.current_result() is None:
            self.app.sound_manager.play_drop()
        return True

    def handle_right_press(self, pos):
        if self.current_result() is not None:
            self.app.sound_manager.play_ui_click()
            return True
        sq = self.board.cell_at(pos)
        if sq is None:
            self.app.sound_manager.play_ui_click()
            return True
        if self.board.dragging_from is not None:
            if not self.board.queue_premove_from_drag(sq):
                self.app.sound_manager.play_ui_click()
            return True
        self.board.begin_right_press(pos)
        self.app.sound_manager.play_ui_click()
        return True

    def handle_right_release(self, pos):
        self.board.end_right_press(pos)
        return True

    def _draw_game_scene(self, *, show_panel, show_strips, arrow_hook=None, after_board=None):
        self.skillcheck_session.sync_aim_check_gun()
        self._draw_game_background()
        self.board.draw_board()
        if after_board is not None:
            after_board()
        if show_strips:
            self._update_player_strips()
            self.player_strip_top.draw()
            self.player_strip_bottom.draw()
        if show_panel:
            self._refresh_game_info()
        if arrow_hook is not None:
            arrow_hook()
        if show_panel:
            self.right_menu.draw_menu()

    def _draw_game_background(self):
        self.backdrop.draw(self.window, self.board.rect)

    def _refresh_game_info(self):
        info = self._compute_game_info()
        if info != self.right_menu.game_info:
            self.right_menu.set_game_info(info)

    def _compute_game_info(self):
        if self.app.screen is not self:
            return None
        tc = format_time_control(self._time_control) or "∞"
        rnd = self._current_round()
        pill = VARIANT_PILL_LABELS[self.variant]
        info = {"mode": pill, "time_control": tc, "round": rnd, "lines": []}
        if self.variant == Variant.ONLINE:
            white_score = self.result_flow.series_scores.get(self.white_name, 0.0)
            black_score = self.result_flow.series_scores.get(self.black_name, 0.0)
            info["lines"] = [
                f"{self.white_name}  {score_str(white_score)} – "
                f"{score_str(black_score)}  {self.black_name}",
            ]
        return info

    def _current_round(self):
        total = (self.result_flow.series_scores.get(self.white_name, 0.0)
                 + self.result_flow.series_scores.get(self.black_name, 0.0))
        return int(total) + 1

    def _result_elapsed_ms(self):
        if self._result_first_seen_at_ms is None:
            return None
        return pg.time.get_ticks() - self._result_first_seen_at_ms

    def _result_menu_should_show(self):
        elapsed = self._result_elapsed_ms()
        if elapsed is None:
            return False
        delay = RESULT_TAKEOVER_MS if self.board.effects.has_takeover() else RESULT_MODAL_DELAY_MS
        return elapsed >= delay

    def _result_fade_surface(self, size):
        def build():
            surf = pg.Surface(size)
            surf.fill((0, 0, 0))
            return surf
        return cache.memoized_surface(_RESULT_FADE_CACHE, size, build)

    def _draw_result_fade_overlay(self):
        elapsed = self._result_elapsed_ms()
        if elapsed is None:
            return
        alpha = min(RESULT_FADE_MAX_ALPHA,
                    int(RESULT_FADE_MAX_ALPHA * elapsed / RESULT_FADE_MS))
        if alpha <= 0:
            return
        overlay = self._result_fade_surface(self.window.get_size())
        overlay.set_alpha(alpha)
        self.window.blit(overlay, (0, 0))

    def _skip_result_fade(self):
        if self._result_first_seen_at_ms is None:
            return
        self.board.effects.clear_takeover()
        self._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS

    def _trigger_result_effects(self):
        code = self.current_result()
        if code is None:
            return
        if code.startswith("draw"):
            self.app.sound_manager.play_draw()
            return
        if code.startswith("white_wins"):
            winner, loser = PieceColor.WHITE, PieceColor.BLACK
        elif code.startswith("black_wins"):
            winner, loser = PieceColor.BLACK, PieceColor.WHITE
        else:
            return
        is_mate = code in ("white_wins", "black_wins")
        is_resign = code.endswith("_by_resignation")
        if is_mate or is_resign:
            self.board.show_surrender_flag(loser)
        if is_mate:
            self.board.show_checkmate_takeover(winner.value.upper())
        if is_mate or is_resign:
            if self._local_won(winner):
                self.app.sound_manager.play_you_win()
            elif is_resign:
                self.app.sound_manager.play_resign()
            elif is_mate:
                self.app.sound_manager.play_you_lose()

    def _local_won(self, winner):
        return self.variant != Variant.ONLINE or self.match.local_color == winner

    def _on_flip(self):
        if self.current_result() is not None:
            return
        self.board.cancel_drag_physics()
        self.board.flipped = not self.board.flipped
        self.app.sound_manager.play_flip()

    def _on_resign(self):
        if not self.board_interactive():
            return
        self.app.confirm_modal.show(
            "Tap out?", on_yes=self._perform_resign,
            sub="The pieces are watching.",
            yes_label="I'm done", no_label="Keep fighting", danger=True, emoji="🏳️",
        )

    def _perform_resign(self):
        if self.current_result() is not None:
            return
        if self.variant == Variant.ONLINE and self.app.coordinator.send_resign():
            return
        loser = self.match.current_turn()
        self._auto_complete_pending_promotion()
        self.manual_result = (
            "black_wins_by_resignation" if loser == PieceColor.WHITE
            else "white_wins_by_resignation"
        )
        self.board.clear_premoves()
        self.board.clear_annotations()
        self.result_flow.on_result_final(self.manual_result)

    def _on_draw(self):
        if not self.board_interactive():
            return
        self.app.confirm_modal.show(
            "Offer a draw?", on_yes=self._perform_draw,
            sub="Propose splitting the point. No shots fired, no glory either.",
            yes_label="Offer draw", no_label="Nevermind", emoji="🤝",
        )

    def _perform_draw(self):
        if self.current_result() is not None:
            return
        if self.variant == Variant.ONLINE and self.app.coordinator.send_draw_offer():
            return
        self._auto_complete_pending_promotion()
        self.manual_result = "draw_agreement"
        self.board.clear_premoves()
        self.board.clear_annotations()
        self.result_flow.on_result_final(self.manual_result)

    def _auto_complete_pending_promotion(self):
        if self.board.pending_promotion_square is None:
            return
        if self.board.cancel_unapplied_promotion():
            return
        self.match.promote(self.board.pending_promotion_square, PieceType.QUEEN)
        self.board.pending_promotion_square = None

    def _on_undo(self):
        if not self.board_interactive():
            return
        if self.variant == Variant.ONLINE and self.app.coordinator.send_takeback_request():
            return
        self.board.selected_square = None
        self.board.clear_premoves()
        self.skillcheck.clear_locks()
        self.board.clear_annotations()
        self.board.review_ply = None
        self.board.cancel_animations()
        if not self.match.move_history:
            return
        log.info("undo ply=%d", len(self.match.move_history))
        self.app.sound_manager.play_undo()
        self.skillcheck_session.drop_skillcheck_log_from(len(self.match.move_history))
        move = self.match.move_history[-1].move
        self.match.undo()
        self.board.start_undo_animation(move)

    def _on_move_landed(self, entry):
        self._first_move_deadline_ms = None
        if entry.gives_checkmate:
            self.app.sound_manager.play_checkmate()
        elif entry.move.is_castle:
            self.app.sound_manager.play_castle()
        else:
            self.app.sound_manager.play_move(entry.move.piece.type)
        if entry.gives_check and not entry.gives_checkmate:
            self.app.sound_manager.play_check()
            self.board.show_check_gun(entry)
        self._maybe_flash_increment_for(entry.move.piece.color)
        self.skillcheck.clear_locks()

    def _on_shot_fired(self, entry):
        self.app.sound_manager.play_capture(entry.move.piece.type)

    def _on_kill_announced(self, key, victim=None):
        if key == "hit":
            self.app.sound_manager.play_hit(victim.type if victim is not None else None)
        elif self.current_result() is None:
            self.app.sound_manager.play_announcer(key)

    def _maybe_flash_increment_for(self, mover_color):
        clock = self.match.clock
        if clock is None or clock.increment_seconds <= 0:
            return
        self._strip_for_color(mover_color).flash_increment()

    def _name_for_color(self, color):
        return self.white_name if is_white(color) else self.black_name

    def _country_for_color(self, color):
        return self.white_country if is_white(color) else self.black_country

    def _strip_for_color(self, color):
        top_is_white = top_strip_color(self.board.flipped) == PieceColor.WHITE
        return (self.player_strip_top if is_white(color) == top_is_white
                else self.player_strip_bottom)

    def _update_player_strips(self):
        top_color = top_strip_color(self.board.flipped)
        bottom_color = opponent_of(top_color)
        turn = self.match.current_turn()
        over = self.current_result() is not None
        self.player_strip_top.set_state(**self._strip_state(top_color, turn, over))
        self.player_strip_bottom.set_state(**self._strip_state(bottom_color, turn, over))

    def _strip_capture_summary(self, color):
        key = (len(self.match.move_history), self.board.review_ply, color)
        cached = self._strip_memo.get(color)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        history = self.board.reviewed_history()
        captured = captured_by(history, color)
        advantage = material_advantage(history, color)
        self._strip_memo[color] = (key, captured, advantage)
        return captured, advantage

    def _strip_state(self, color, turn, over):
        name = self._name_for_color(color)
        seconds = (self.match.clock.remaining(color)
                   if self.match.clock is not None else None)
        initial_seconds = (self.match.clock.initial_seconds
                           if self.match.clock is not None else None)
        active = (color == turn) and not over
        captured, advantage = self._strip_capture_summary(color)
        connection_state = None
        app = self.app
        if (self.variant == Variant.ONLINE and app.coordinator.is_connected()
                and self.match.local_color is not None
                and color != self.match.local_color):
            connection_state = app.coordinator.opponent_state()
        auto_end_label, auto_end_seconds = self._compute_auto_end(color, over)
        is_bot = self.variant == Variant.BOT and name == OPPONENT_NAME_FOR_MODE[BOT]
        return {
            "name": name,
            "player_color": color,
            "is_bot": is_bot,
            "rating": PLACEHOLDER_RATING,
            "clock_seconds": seconds,
            "active": active,
            "captured": captured,
            "advantage": advantage,
            "captured_color": opponent_of(color),
            "ko_count": len(captured),
            "connection_state": connection_state,
            "country": self._country_for_color(color),
            "clock_initial_seconds": initial_seconds,
            "auto_end_label": auto_end_label,
            "auto_end_seconds": auto_end_seconds,
        }

    def _compute_auto_end(self, color, over):
        if (self.variant != Variant.ONLINE or over or self.match.local_color is None):
            return None, None
        now = pg.time.get_ticks()
        is_local = (color == self.match.local_color)
        if is_local and self._local_disconnected_at_ms is not None:
            return self._auto_end_remaining(
                "Aborting in", self._local_disconnected_at_ms,
                RECONNECT_TOTAL_SECONDS, now,
            )
        if (not is_local
                and self._opp_disconnected_at_ms is not None):
            return self._auto_end_remaining(
                "Abandon in", self._opp_disconnected_at_ms, GRACE_SECONDS, now,
            )
        if (color == self.match.current_turn()
                and not self.match.move_history
                and self._first_move_deadline_ms is not None):
            remaining_ms = self._first_move_deadline_ms - now
            if remaining_ms <= 0:
                return None, None
            remaining = remaining_ms / 1000.0
            elapsed = FIRST_MOVE_ABORT_SECONDS - remaining
            if elapsed < AUTO_END_GATE_FRACTION * FIRST_MOVE_ABORT_SECONDS:
                return None, None
            return "Abort in", remaining
        return None, None

    def _auto_end_remaining(self, label, snap_ms, total_seconds, now_ms):
        elapsed = (now_ms - snap_ms) / 1000.0
        if elapsed < AUTO_END_GATE_FRACTION * total_seconds:
            return None, None
        remaining = total_seconds - elapsed
        if remaining <= 0:
            return None, None
        return label, remaining

    def _right_menu_buttons(self):
        if self.match.clock is None:
            return RIGHT_MENU_UNTIMED_CAPS
        return RIGHT_MENU_CAPS

    def _right_menu_disabled_keys(self):
        if self.current_result() is not None:
            return {"undo", "resign", "draw", "flip", "give_time"}
        disabled = set()
        clock = self.match.clock
        if clock is None or clock.flagged is not None:
            disabled.add("give_time")
        if self.give_time.on_cooldown():
            disabled.add("give_time")
        return disabled

    def _ensure_local_session(self):
        if self._match_session_id is None:
            self._match_session_id = str(uuid.uuid4())

    def _reset_to_new_game(self):
        app = self.app
        coordinator = app.coordinator
        self._force_focus_off_instant()
        coordinator.offer_banners.clear()
        coordinator._rematch_offered = False
        self.result_menu.reset()
        app.sound_manager.stop_all()
        self.give_time.cancel_give_time_hold()
        self.manual_result = None
        self._flag_fall_played = False
        self._strip_memo = {}
        self._result_first_seen_at_ms = None
        self.result_flow.reset_for_new_game()
        self.right_menu.reset_for_new_game()
        self.match.new_game()
        self.match.mode = MATCH_MODE_BY_VARIANT[self.variant]
        if self._time_control is not None:
            initial, incr = self._time_control
            self.match.setup_clock(initial, incr)
            self.board.animation_duration_ms = compute_animation_ms(initial)
        else:
            self.board.animation_duration_ms = ANIM_MS_DEFAULT
        self.board.reset_for_new_game()
        self.skillcheck_overlay.cancel()
        self.skillcheck.clear_locks()
        self.skillcheck_session.clear_online_skillcheck_state()
        self.skillcheck_session.skillcheck_log = []
        app.confirm_modal.hide()
        self._last_turn_for_flip = None

    def _focus_show(self):
        return env.get_focus_show()

    def _focus_available(self):
        return (self.app.screen is self
                and self.board_interactive()
                and not self.skillcheck_overlay.is_active()
                and not self.board.is_dragging()
                and self.board.pending_promotion_square is None
                and not self.app._blocking_modal_visible())

    def _focus_arrow_allowed(self):
        return (self.board_interactive()
                and not self.skillcheck_overlay.is_active()
                and not self.app._blocking_modal_visible())

    def _toggle_focus(self, on):
        if self.focus_transition is not None:
            return
        if self.skillcheck_overlay.is_active() and self.current_result() is None:
            return
        if on == self.focus_mode:
            return
        if on and not self._focus_available():
            return
        log.info("focus mode toggled on=%s", on)
        self.app.sound_manager.play_focus_action()
        self.board.cancel_drag_physics()
        self.focus_transition = FocusTransition(self)
        if on:
            self.focus_transition.begin_collapse(self._focus_show())
        else:
            self.focus_transition.begin_expand(self._focus_show())
        self.focus_arrow.reset()
        self.app._needs_full_present = True

    def _finalize_focus_transition(self):
        self.focus_transition = None
        self.app._needs_full_present = True

    def on_resize(self):
        self._abort_transition_for_resize()

    def _abort_transition_for_resize(self):
        if self.focus_transition is not None:
            self.focus_transition.cancel()
            self.focus_transition = None
            self.app._needs_full_present = True

    def _force_focus_off_instant(self):
        if not self.focus_mode and self.focus_transition is None:
            return
        if self.focus_transition is not None:
            self.focus_transition.cancel()
            self.focus_transition = None
        self.focus_mode = False
        self.focus_arrow.reset()
        self._focus_panel_hover_ms = LONG_AGO_MS
        self._focus_hint_until_ms = 0
        self.app._compute_layout()
        self.app._needs_full_present = True

    def _focus_edge_zone_rect(self):
        board_r = self.board.rect
        w = self.window.get_width()
        return pg.Rect(w - FOCUS_EDGE_ZONE_PX, board_r.top, FOCUS_EDGE_ZONE_PX, board_r.height)

    def _focus_arrow_off_anchor(self):
        x = self.right_menu.outer_rect.x - FOCUS_ARROW_D // 2 - FOCUS_ARROW_OFF_GAP
        return (x, self.board.rect.centery)

    def _update_focus_arrow_off(self, now):
        if not self._focus_arrow_allowed():
            self.focus_arrow.reset()
            return
        mp = pg.mouse.get_pos()
        if self.right_menu.outer_rect.collidepoint(mp):
            self._focus_panel_hover_ms = now
        anchor = self._focus_arrow_off_anchor()
        shown = (now < self._focus_hint_until_ms
                 or now - self._focus_panel_hover_ms < FOCUS_OFF_LINGER_MS)
        self.focus_arrow.update(now, shown, anchor, mp, False)
        self.focus_arrow.draw(self.window)

    def _draw_focus_edge_arrow(self, now):
        mp = pg.mouse.get_pos()
        zone = self._focus_edge_zone_rect()
        reveal = self._focus_arrow_allowed() and zone.collidepoint(mp)
        anchor = (self.window.get_width() - FOCUS_EDGE_ARROW_MARGIN - FOCUS_ARROW_D // 2,
                  self.board.rect.centery)
        self.focus_arrow.update(now, reveal, anchor, mp, True)
        self.focus_arrow.draw(self.window)

    def _draw_time_lines(self, board_rect=None, alpha=1.0):
        if self._focus_show() != "line" or self._time_control is None:
            return
        self.time_line.draw(self.window, self.board, self.match.clock,
                            self.match.current_turn(), board_rect or self.board.rect, alpha)
