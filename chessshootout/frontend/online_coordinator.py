import logging
import threading
import uuid

import pygame as pg

from chessshootout.backend.utils import coord_from_square, square_from_coord
from chessshootout.domain.match import ONLINE
from chessshootout.domain.pgn.load import time_category_for_minutes
from chessshootout.frontend.modals.match_found import MatchFoundModal
from chessshootout.frontend.modals.reconnecting import ReconnectingModal
from chessshootout.frontend.modals.wait import WaitModal
from chessshootout.frontend.panels.banners import OfferBanners
from chessshootout.frontend.panels.player_strip import AUTO_END_RED_THRESHOLD_SECONDS
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.screens.base import Nav
from chessshootout.infra import env
from chessshootout.online.client import (
    ClientReason, OnlineClient, RECONNECT_TOTAL_SECONDS, fetch_resume, probe_active_game,
)
from chessshootout.server.protocol import (
    FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, Reason,
)
from chessshootout.skillcheck.online import SKILLCHECK_DEADLINE_MS


log = logging.getLogger("chess.frontend")

MATCH_FOUND_SECONDS = 3
REMATCH_STATE_TOAST_KEY = "rematch_state"

RESYNC_TIMEOUT_MS = 8000
SKILLCHECK_WATCHDOG_SLACK_MS = 4000
RECONNECT_MODAL_DEBOUNCE_MS = 500

ONLINE_DEFAULT_TIME_MINUTES = 5

RECONNECT_PROBE_INTERVAL_MS = 5000
RECONNECT_PROBE_MAX_ATTEMPTS = 3

OFFER_BANNERS = {
    "draw_offered": ("🤝", "offers a draw", "Accept", "Decline", "send_draw_response"),
    "takeback_offered": ("↩️", "wants a takeback", "Allow", "Deny",
                         "send_takeback_response"),
    "rematch_request": ("⚔️", "wants a rematch", "Accept", "Deny",
                        "send_rematch_response"),
}

ONLINE_HARD_FAILURE_LABELS = {
    ClientReason.SERVER_UNREACHABLE: "Server unreachable",
    ClientReason.RECONNECT_FAILED: "Could not reconnect",
    Reason.ROOM_FULL: "Server is full",
}

ONLINE_HARD_FAILURE_REASONS = frozenset(ONLINE_HARD_FAILURE_LABELS)

ONLINE_TRANSIENT_REASON_LABELS = {
    Reason.RATE_LIMITED: "Slow down a bit",
    Reason.NO_TAKEBACK_AVAILABLE: "Nothing to take back",
    Reason.REMATCH_ALREADY_PENDING: "Rematch already requested",
    Reason.ALREADY_IN_GAME: "Already in a game",
    Reason.GAME_ALREADY_OVER: "This game has ended",
}

ONLINE_GAME_STATE_REASONS = {
    Reason.NOT_YOUR_TURN, Reason.INVALID_MOVE_FORMAT, Reason.INVALID_MESSAGE,
    Reason.VERSION_MISMATCH,
}

MOVE_REJECTION_REASONS = {
    Reason.INVALID_MOVE_FORMAT, Reason.NOT_YOUR_TURN, Reason.SKILLCHECK_PENDING,
    Reason.MOVE_LOCKED,
}

NOT_YOUR_TURN_TOASTS = {
    "takeback_request": "Take back is only available right after your move",
}


class OnlineCoordinator:

    def __init__(self, app):
        self.app = app
        self.client = None
        self.wait_modal = WaitModal(app.window)
        self.match_found_modal = MatchFoundModal(app.window)
        self.reconnecting_modal = ReconnectingModal(app.window)
        self.offer_banners = OfferBanners(app.window)
        self._subscriber = None

        self._online_config = None
        self._resyncing = False
        self._resync_started_at_ms = 0
        self._last_heartbeat_sent_ms = 0
        self._wait_started_at_ms = None
        self._match_found_at_ms = None
        self._pending_game_start_payload = None
        self._rematch_offered = False
        self._prev_online_state = None

        self._pending_reconnect = None
        self._pending_reconnect_lock = threading.Lock()
        self._last_reconnect_probe_ms = 0
        self._reconnect_probe_inflight = False
        self._reconnect_probe_gen = 0
        self._reconnect_probe_attempts = 0

    def subscribe(self, subscriber):
        assert self._subscriber is None, "OnlineCoordinator already has a subscriber"
        self._subscriber = subscriber

    def unsubscribe(self, subscriber):
        if self._subscriber is subscriber:
            self._subscriber = None

    def _forward_board_event(self, method_name, payload):
        subscriber = self._subscriber
        if subscriber is None:
            log.error("board-level event %s arrived with no subscriber", method_name)
            return
        getattr(subscriber, method_name)(payload)

    def is_connected(self):
        return self.client is not None

    def opponent_state(self):
        return self.client.opp_state if self.client is not None else None

    def ping_ms(self):
        return self.client.get_ping_ms() if self.client is not None else None

    def send_local_move(self, from_sq, to_sq, promotion):
        if self.client is not None:
            self.client.send_move(coord_from_square(from_sq), coord_from_square(to_sq), promotion)

    def send_move(self, from_coord, to_coord, promo_letter):
        if self.client is not None:
            self.client.send_move(from_coord, to_coord, promo_letter)

    def send_resign(self):
        if self.client is None:
            return False
        self.client.send_resign()
        return True

    def send_draw_offer(self):
        if self.client is None:
            return False
        log.info("draw offer sent")
        self.client.send_draw_offer()
        return True

    def send_takeback_request(self):
        if self.client is None:
            return False
        log.info("takeback requested")
        self.client.send_takeback_request()
        return True

    def send_give_time(self, hold_ms):
        if self.client is not None:
            self.client.send_give_time(hold_ms)

    def send_skill_check_shot(self, client_elapsed_ms):
        if self.client is not None:
            self.client.send_skill_check_shot(client_elapsed_ms)

    def _drain_online_inbound(self):
        if self.client is None:
            return
        for event in self.client.drain_inbound():
            try:
                self._handle_online_event(event)
            except Exception:
                log.exception("online event handler failed")

    def _handle_online_event(self, event):
        if event.type == "game_start":
            self._begin_match_found_transition(event.payload)
        elif event.type == "move_applied":
            self._handle_remote_move_applied(event.payload)
        elif event.type == "result":
            self._handle_online_result(event.payload)
        elif event.type in ("draw_offered", "takeback_offered"):
            self._push_offer_banner(event.type)
        elif event.type == "rematch_request":
            self._handle_rematch_request()
        elif event.type == "rematch_update":
            self._handle_rematch_update(event.payload)
        elif event.type == "takeback_applied":
            self._handle_takeback_applied(event.payload)
        elif event.type == "game_resumed":
            self._handle_game_resumed(event.payload)
        elif event.type == "time_granted":
            self._handle_time_granted(event.payload)
        elif event.type == "connection_status":
            self._handle_connection_status(event.payload)
        elif event.type == "resync_directive":
            self._begin_resync()
        elif event.type == "skill_check_required":
            self._handle_skill_check_required(event.payload)
        elif event.type == "skill_check_result":
            self._handle_skill_check_result(event.payload)
        elif event.type == "skill_check_spectate":
            self._handle_skill_check_spectate(event.payload)
        elif event.type == "skill_check_spectate_shot":
            self._handle_skill_check_spectate_shot(event.payload)
        elif event.type == "error":
            self._handle_online_error(event.payload)

    def _handle_online_error(self, payload):
        reason = payload.get("reason", "")
        game = self.app.game
        pending_move = game.skillcheck_session.pending_online_move
        if pending_move is not None and reason in MOVE_REJECTION_REASONS:
            game.skillcheck_session.pending_online_move = None
            game.board.selected_square = None
            if reason in (Reason.INVALID_MOVE_FORMAT, Reason.NOT_YOUR_TURN):
                self._begin_resync()
            return
        if reason == Reason.NOT_YOUR_TURN:
            label = NOT_YOUR_TURN_TOASTS.get(payload.get("msg_type"))
            if label is not None:
                self.app.toast.show(label)
            return
        if reason in ONLINE_GAME_STATE_REASONS:
            return
        if reason == Reason.REMATCH_UNAVAILABLE:
            self.app.toast.show("Rematch no longer available", key=REMATCH_STATE_TOAST_KEY)
            self._end_rematch_window()
            return
        if reason == ClientReason.ROOM_LOST:
            log.warning("online room lost — server restarted mid-game")
            self._resyncing = False
            game.result_flow.auto_save_pgn()
            self.reconnecting_modal.hide()
            self.offer_banners.clear()
            self.app.confirm_modal.show(
                "Server restarted — game ended",
                on_yes=self._restart_online_search,
                on_no=self._abandon_online_game,
                yes_label="New Search", no_label="Cancel",
            )
            return
        if reason in ONLINE_HARD_FAILURE_REASONS or reason.startswith("http_"):
            log.warning("online hard failure reason=%s", reason)
            self._resyncing = False
            self.wait_modal.hide()
            self.match_found_modal.hide()
            self.offer_banners.clear()
            label = ONLINE_HARD_FAILURE_LABELS.get(reason, "Server unreachable")
            self.app.confirm_modal.show(
                label,
                on_yes=self._restart_online_search,
                on_no=self._on_online_cancel,
                yes_label="New Search", no_label="Cancel",
            )
            return
        if reason:
            label = ONLINE_TRANSIENT_REASON_LABELS.get(reason, reason)
            self.app.toast.show(label)
        else:
            self.app.toast.show("Server error")

    def _opp_name(self):
        game = self.app.game
        opp_color = "black" if game._chosen_side == "white" else "white"
        return game._name_for_color(opp_color)

    def _push_rematch_banner(self):
        self._rematch_offered = True
        icon, verb, ok_label, no_label, _ = OFFER_BANNERS["rematch_request"]
        self.offer_banners.push(
            "rematch_request", icon, self._opp_name(), verb, ok_label, no_label,
            on_ok=self._accept_rematch, on_no=self._decline_rematch)

    def _clear_rematch_offer(self):
        self.offer_banners.dismiss("rematch_request")
        self._rematch_offered = False
        self.app.game.result_menu.set_rematch_offered(False)

    def _handle_rematch_request(self):
        if self.client is None:
            return
        log.info("rematch offer received")
        self._push_rematch_banner()
        self.app.game.on_offer("rematch_request")
        self.app.sound_manager.play_give_time()

    def _reshow_rematch_banner(self):
        if self.client is None:
            return
        self._push_rematch_banner()

    def _accept_rematch(self):
        if self.client is not None:
            log.info("rematch response sent accepted=True")
            self.client.send_rematch_response(True)

    def _decline_rematch(self):
        self._clear_rematch_offer()
        if self.client is not None:
            log.info("rematch response sent accepted=False")
            self.client.send_rematch_response(False)

    def _end_rematch_window(self):
        self._clear_rematch_offer()
        self._tear_down_online_session("rematch_window_closed")
        self._return_to_menu_card()

    def _handle_rematch_update(self, payload):
        event = payload.get("event", "")
        log.info("rematch update event=%s", event)
        opp = self._opp_name()
        if event == "opponent_reconnecting":
            self.app.toast.show(f"{opp} disconnected — waiting…", key=REMATCH_STATE_TOAST_KEY)
            return
        if event == "opponent_returned":
            self.app.toast.show(f"{opp} is back", key=REMATCH_STATE_TOAST_KEY)
            return
        if event == "cancelled":
            self._clear_rematch_offer()
            self.app.toast.show(f"{opp} withdrew the rematch", key=REMATCH_STATE_TOAST_KEY)
            return
        labels = {
            "declined": f"{opp} declined the rematch",
            "opponent_left": f"{opp} left the game",
            "window_expired": "Rematch window closed",
        }
        self.app.toast.show(labels.get(event, "Rematch ended"), key=REMATCH_STATE_TOAST_KEY)
        self._end_rematch_window()

    def _push_offer_banner(self, event_type):
        if self.client is None:
            return
        icon, verb, ok_label, no_label, send_method = OFFER_BANNERS[event_type]
        opp_name = self._opp_name()
        send_response = getattr(self.client, send_method)
        log.info("offer received type=%s from=%s", event_type, opp_name)
        self.app.game.on_offer(event_type)
        self.app.sound_manager.play_toast()

        def respond(value):
            def fire():
                log.info("offer responded type=%s accepted=%s", event_type, value)
                self.app.sound_manager.play_toast()
                send_response(value)
            return fire

        self.offer_banners.push(
            event_type, icon, opp_name, verb, ok_label, no_label,
            on_ok=respond(True), on_no=respond(False),
        )

    def _begin_resync(self):
        if self._resyncing:
            return
        self._resyncing = True
        self.offer_banners.clear()
        self._resync_started_at_ms = pg.time.get_ticks()
        if self.client is not None:
            self.client.request_state_sync()

    def _handle_game_resumed(self, payload):
        game = self.app.game
        if game.variant != Variant.ONLINE:
            log.info("resume ignored — no active online game")
            self._resyncing = False
            return
        target = self._subscriber if self._subscriber is not None else game
        target.on_resume(payload)
        self._resyncing = False

    def _handle_time_granted(self, payload):
        self._forward_board_event("on_give_time", payload)

    def _handle_takeback_applied(self, payload):
        if self._resyncing:
            return
        self._forward_board_event("on_takeback", payload)

    def _handle_skill_check_required(self, payload):
        if self._resyncing:
            return
        self._forward_board_event("on_skillcheck_required", payload)

    def _handle_skill_check_result(self, payload):
        if self._resyncing:
            return
        game = self.app.game
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        if game._is_my_open_check(from_sq, to_sq):
            self._forward_board_event("on_skillcheck_required", payload)
        elif game.skillcheck_session.online_spectate_kind is not None:
            self._forward_board_event("on_spectate", payload)

    def _handle_skill_check_spectate(self, payload):
        if self._resyncing:
            return
        self._forward_board_event("on_spectate", payload)

    def _handle_skill_check_spectate_shot(self, payload):
        if self._resyncing or self.app.game.skillcheck_session.online_spectate_kind is None:
            return
        self._forward_board_event("on_spectate", payload)

    def _handle_remote_move_applied(self, payload):
        if self._resyncing:
            return
        self._forward_board_event("on_remote_move", payload)

    def _handle_online_result(self, payload):
        target = self._subscriber if self._subscriber is not None else self.app.game
        target.on_result(payload)

    def _handle_connection_status(self, payload):
        target = self._subscriber if self._subscriber is not None else self.app.game
        target.on_connection_status(payload)
        if payload.get("opp_state", "connected") == "resyncing":
            self.app.toast.show("Opponent is resyncing…")

    def _begin_match_found_transition(self, payload):
        if self._pending_game_start_payload is not None:
            return
        self._pending_game_start_payload = payload
        now = pg.time.get_ticks()
        self._match_found_at_ms = now
        elapsed = float(payload.get("started_seconds_ago", 0.0))
        self.app.game._first_move_deadline_ms = now + int(
            (FIRST_MOVE_ABORT_SECONDS - elapsed) * 1000
        )
        self.wait_modal.hide()
        room_id = self.client.room_id if self.client is not None else None
        log.info("match found room=%s side=%s", room_id, payload.get("your_color"))
        self.match_found_modal.show(
            payload["white_name"], payload["black_name"], payload["your_color"],
            self._finish_match_found, seconds=MATCH_FOUND_SECONDS,
            white_country=payload.get("white_country") or "",
            black_country=payload.get("black_country") or "",
            rematch=bool(payload.get("rematch")),
        )
        self.app.sound_manager.play_online_game_start()

    def _finish_match_found(self):
        payload = self._pending_game_start_payload
        self._pending_game_start_payload = None
        self._match_found_at_ms = None
        self._wait_started_at_ms = None
        if payload is not None:
            self._start_online_game(payload)

    def _session_id_for_online(self):
        if self.client is not None and self.client.room_id:
            return self.client.room_id
        return str(uuid.uuid4())

    def _start_online_game(self, payload):
        opp_name = (payload.get("white_name") if payload.get("your_color") == "black"
                    else payload.get("black_name"))
        log.info("game start mode=online side=%s vs=%s tc=%s+%s",
                 payload.get("your_color"), opp_name,
                 payload.get("time_minutes"), payload.get("increment_seconds"))
        self.wait_modal.hide()
        self.app.confirm_modal.hide()
        self.app.start_menu.hide()
        nav_payload = {
            "your_color": payload["your_color"],
            "white_name": payload["white_name"],
            "black_name": payload["black_name"],
            "white_country": payload.get("white_country") or "",
            "black_country": payload.get("black_country") or "",
            "time_minutes": payload["time_minutes"],
            "increment_seconds": payload["increment_seconds"],
            "white_score": float(payload.get("white_score", 0.0)),
            "black_score": float(payload.get("black_score", 0.0)),
            "session_id": self._session_id_for_online(),
        }
        self.app.request_nav(Nav("game", nav_payload))
        self.app._execute_pending_nav()

    def _begin_online_flow(self, config):
        log.info("online flow begin tc=%s+%s side=%s",
                 config.get("time_minutes"), config.get("increment_seconds"),
                 config.get("side"))
        self._online_config = config
        self.app.start_menu.hide()
        self._on_server_addr_connect(env.get_server_addr())

    def _on_server_addr_connect(self, addr):
        log.info("connect to %s", addr)
        if not addr:
            self._on_online_cancel()
            return
        if self.client is not None:
            self.client.disconnect()
            self.client = None
        self.offer_banners.dismiss("rematch_request")
        self._rematch_offered = False
        self.client = OnlineClient()
        request = {
            "nickname": (self._online_config.get("nickname") or "").strip() or "Player",
            "client_uuid": env.get_or_create_client_uuid(),
            "time_minutes": self._online_config["time_minutes"] or ONLINE_DEFAULT_TIME_MINUTES,
            "increment_seconds": self._online_config["increment_seconds"],
            "side_preference": self._online_config["side"],
            "country": env.get_country() or None,
        }
        self.client.connect(addr, request)
        mode_label, tc_text = self._search_labels()
        self.wait_modal.show(mode_label, tc_text, self._on_online_cancel)
        self._wait_started_at_ms = pg.time.get_ticks()
        self._match_found_at_ms = None
        self._pending_game_start_payload = None

    def _search_labels(self):
        minutes = self._online_config.get("time_minutes") or ONLINE_DEFAULT_TIME_MINUTES
        incr = self._online_config.get("increment_seconds", 0) or 0
        return time_category_for_minutes(minutes), f"{minutes} + {incr}"

    def _drop_client(self, *, cancel_queue=False):
        self._resyncing = False
        if self.client is None:
            return
        if cancel_queue:
            self.client.cancel_queue()
        else:
            self.client.disconnect()
        self.client = None

    def _clear_search_state(self):
        self.wait_modal.hide()
        self.match_found_modal.hide()
        self._wait_started_at_ms = None
        self._match_found_at_ms = None
        self._pending_game_start_payload = None

    def unbind_game_from_online(self):
        game = self.app.game
        game.variant = Variant.LOCAL
        game.match.local_color = None
        game.match.on_local_move_applied = None
        game.right_menu.set_game_info(None)
        game.result_menu.set_online_mode(False)
        game._first_move_deadline_ms = None
        game._opp_disconnected_at_ms = None
        game._local_disconnected_at_ms = None
        self._prev_online_state = None

    def _on_online_cancel(self):
        log.info("online flow cancel")
        self._drop_client(cancel_queue=True)
        self.unbind_game_from_online()
        self._clear_search_state()
        self.offer_banners.clear()
        self._return_to_menu_card()

    def _on_rematch(self):
        if self.client is None:
            return
        if self._rematch_offered:
            self._rematch_offered = False
            self.app.game.result_menu.set_rematch_offered(False)
            log.info("rematch response sent accepted=True")
            self.client.send_rematch_response(True)
        else:
            log.info("rematch requested")
            self.client.send_rematch_request()
            self.app.toast.show(f"Rematch sent — waiting for {self._opp_name()}…",
                                key=REMATCH_STATE_TOAST_KEY)

    def _drop_post_game_online_session(self):
        if self.client is None:
            return
        self._drop_client()
        self.unbind_game_from_online()

    def _tear_down_online_session(self, reason="unspecified"):
        log.info("online session teardown reason=%s", reason)
        game = self.app.game
        game.result_flow.auto_save_pgn()
        self._drop_client()
        self.reconnecting_modal.hide()
        self._clear_search_state()
        self.offer_banners.clear()
        self.unbind_game_from_online()
        self.app.switch_to("menu")
        game._reset_to_new_game()
        self.app._refresh_load_pgn_availability()

    def _return_to_menu_card(self):
        if self.app.screen is self.app.menu:
            self.app.start_menu.show()
        else:
            self.app.switch_to("menu")
        self._reconnect_probe_attempts = 0

    def _abandon_online_game(self):
        self._tear_down_online_session("reconnect_cancelled")
        self._return_to_menu_card()

    def _restart_online_search(self):
        self._tear_down_online_session("restart_search")
        if self._online_config is not None:
            self._begin_online_flow(self._online_config)
        else:
            self._return_to_menu_card()

    def retain_for_rematch(self, keep_online):
        self._resyncing = False
        if keep_online:
            self.client.send_left_result()
        elif self.client is not None:
            self.client.disconnect()
            self.client = None

    def _track_local_online_state(self):
        current = self.client.state if self.client is not None else None
        prev = self._prev_online_state
        game = self.app.game
        if current == "reconnecting" and prev != "reconnecting":
            game._local_disconnected_at_ms = pg.time.get_ticks()
        elif current != "reconnecting" and prev == "reconnecting":
            game._local_disconnected_at_ms = None
        self._prev_online_state = current

    def _send_heartbeat_if_due(self):
        if self.client is None or not self.client.is_connected():
            return
        if self.client.is_server_silent():
            log.warning("server heartbeat silent; escalating to reconnect")
            self.client.force_reconnect()
            return
        game = self.app.game
        if game.skillcheck_session.online_verdict_action is not None:
            return
        now = pg.time.get_ticks()
        if now - self._last_heartbeat_sent_ms >= self.client.heartbeat_interval() * 1000:
            self._last_heartbeat_sent_ms = now
            self.client.send_ping(len(game.match.move_history))

    def _update_heartbeat(self):
        game = self.app.game
        clock = game.match.clock
        paused = (self.app.screen is not self.app.game or game.current_result() is not None
                  or clock is None)
        if paused or clock.initial_seconds <= 0:
            fraction = None
        else:
            fraction = clock.remaining(game.match.current_turn()) / clock.initial_seconds
        auto_end_fraction = self._auto_end_heartbeat_fraction()
        if auto_end_fraction is not None:
            fraction = (auto_end_fraction if fraction is None
                        else min(fraction, auto_end_fraction))
        self.app.sound_manager.update_heartbeat(fraction, paused)

    def _auto_end_heartbeat_fraction(self):
        game = self.app.game
        if game.variant != Variant.ONLINE:
            return None
        now = pg.time.get_ticks()
        candidates = []
        for snap_ms, total in (
            (game._opp_disconnected_at_ms, GRACE_SECONDS),
            (game._local_disconnected_at_ms, RECONNECT_TOTAL_SECONDS),
        ):
            if snap_ms is None:
                continue
            remaining = total - (now - snap_ms) / 1000.0
            if remaining <= 0:
                continue
            candidates.append((remaining, total))
        if game._first_move_deadline_ms is not None and not game.match.move_history:
            remaining_ms = game._first_move_deadline_ms - now
            if remaining_ms > 0:
                candidates.append((remaining_ms / 1000.0, FIRST_MOVE_ABORT_SECONDS))
        if not candidates:
            return None
        remaining, total = min(candidates, key=lambda r: r[0])
        if remaining < AUTO_END_RED_THRESHOLD_SECONDS:
            return 0.0
        return remaining / total

    def _tick_skillcheck_watchdog(self):
        session = self.app.game.skillcheck_session
        if (session.online_skillcheck is None
                or session.online_skillcheck_opened_ms is None
                or not self.app.game.skillcheck_overlay.is_active()):
            return
        elapsed = pg.time.get_ticks() - session.online_skillcheck_opened_ms
        if elapsed > SKILLCHECK_DEADLINE_MS + SKILLCHECK_WATCHDOG_SLACK_MS:
            log.warning("skillcheck verdict lost; resyncing")
            session.teardown_skillcheck_overlay()
            self._begin_resync()

    def _update_online_phase(self):
        if self.wait_modal.is_visible() and self._match_found_at_ms is None:
            if self._wait_started_at_ms is not None:
                self.wait_modal.set_elapsed(
                    (pg.time.get_ticks() - self._wait_started_at_ms) // 1000)
        self.match_found_modal.update()
        self._track_local_online_state()
        self._send_heartbeat_if_due()
        now = pg.time.get_ticks()
        game = self.app.game
        reconnecting = (game.variant == Variant.ONLINE and game.current_result() is None
                        and self.client is not None
                        and self.client.state == "reconnecting")
        if reconnecting:
            since = game._local_disconnected_at_ms
            if (not self.reconnecting_modal.is_visible() and since is not None
                    and now - since >= RECONNECT_MODAL_DEBOUNCE_MS):
                self.reconnecting_modal.show(
                    since, on_cancel=self._abandon_online_game)
        elif self.reconnecting_modal.is_visible():
            self.reconnecting_modal.hide()
        if self._resyncing:
            if pg.time.get_ticks() - self._resync_started_at_ms > RESYNC_TIMEOUT_MS:
                self._resyncing = False
                if self.client is not None and self.client.state == "connected":
                    log.warning("resync timed out; escalating to reconnect")
                    self.client.force_reconnect()
            else:
                self.app.toast.show("Resyncing…")
        self._tick_skillcheck_watchdog()

    def _spawn_reconnect_probe(self):
        addr = env.get_server_addr()
        client_uuid = env.get_or_create_client_uuid()
        if (not addr or not client_uuid or self._reconnect_probe_inflight
                or self._reconnect_probe_attempts >= RECONNECT_PROBE_MAX_ATTEMPTS):
            return
        with self._pending_reconnect_lock:
            if self._pending_reconnect is not None:
                return
        self._last_reconnect_probe_ms = pg.time.get_ticks()
        self._reconnect_probe_inflight = True
        with self._pending_reconnect_lock:
            self._reconnect_probe_gen += 1
            gen = self._reconnect_probe_gen
        log.debug("reclaim probe attempt addr=%s gen=%d", addr, gen)
        thread = threading.Thread(
            target=self._reconnect_probe_worker,
            args=(addr, client_uuid, gen),
            daemon=True,
        )
        thread.start()

    def _reconnect_probe_worker(self, addr, client_uuid, gen):
        try:
            reclaim = probe_active_game(addr, client_uuid)
            resume = (fetch_resume(addr, reclaim["room_id"], reclaim["session_token"])
                      if reclaim is not None else None)
            with self._pending_reconnect_lock:
                if gen != self._reconnect_probe_gen:
                    return
                if reclaim is None or resume is None:
                    self._pending_reconnect = None
                    self._reconnect_probe_attempts += 1
                else:
                    became_available = self._pending_reconnect is None
                    self._pending_reconnect = {
                        "addr": addr,
                        "room_id": reclaim["room_id"],
                        "session_token": reclaim["session_token"],
                    }
                    if became_available:
                        log.info("reclaim available room=%s", reclaim["room_id"])
        finally:
            self._reconnect_probe_inflight = False

    def _refresh_reconnect_button(self):
        if (self.app.screen is self.app.menu and self.client is None
                and pg.time.get_ticks() - self._last_reconnect_probe_ms
                >= RECONNECT_PROBE_INTERVAL_MS):
            self._spawn_reconnect_probe()
        self.app.start_menu.set_reconnect_available(self.reconnect_available())

    def reconnect_available(self):
        with self._pending_reconnect_lock:
            return self._pending_reconnect is not None

    def reconnect(self):
        self._on_reconnect_active_game()

    def _on_reconnect_active_game(self):
        with self._pending_reconnect_lock:
            self._reconnect_probe_gen += 1
            pending = self._pending_reconnect
            self._pending_reconnect = None
        if pending is None:
            return
        log.info("reconnect: resume begin room=%s", pending["room_id"])
        self.app.start_menu.set_reconnect_available(False)
        resume = fetch_resume(
            pending["addr"], pending["room_id"], pending["session_token"],
        )
        if resume is None:
            log.warning("reconnect: fresh /resume failed; restoring pending entry")
            with self._pending_reconnect_lock:
                self._pending_reconnect = pending
            self.app.start_menu.set_reconnect_available(True)
            self.app.confirm_modal.show(
                ONLINE_HARD_FAILURE_LABELS["reconnect_failed"],
                on_yes=self._on_reconnect_active_game,
                on_no=lambda: None,
                yes_label="Retry", no_label="Cancel",
            )
            return
        log.info("reconnect: resume ok room=%s", pending["room_id"])
        nickname = (resume["white_name"] if resume["your_color"] == "white"
                    else resume["black_name"])
        self.app.start_menu.text_input.text = nickname
        self.app.start_menu.selected_mode = ONLINE
        self.app.start_menu.selected_time_minutes = resume["time_minutes"]
        self.app.start_menu.selected_increment_seconds = resume["increment_seconds"]
        self.app.start_menu.selected_side = resume["your_color"]
        self.client = OnlineClient()
        self._start_online_game(resume)
        self._handle_game_resumed(resume)
        self.client.reconnect_to_existing(
            pending["addr"], pending["room_id"], pending["session_token"], resume,
        )
        self.app.start_menu.hide()

    def update(self, now):
        self._drain_online_inbound()
        self._update_heartbeat()
        self._update_online_phase()
        self._refresh_reconnect_button()

    def on_app_exit(self):
        if self.client is not None:
            self.client.disconnect()
