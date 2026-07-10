import logging

import pygame as pg

from chessshootout.backend.fen import apply_fen
from chessshootout.domain.match import ONLINE
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import PROMO_TYPE_BY_LETTER, coord_from_square, square_from_coord
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS
from chessshootout.skillcheck.types import SkillCheckKind


log = logging.getLogger("chess.frontend")

MATCH_FOUND_SECONDS = 3
REMATCH_STATE_TOAST_KEY = "rematch_state"

OFFER_BANNERS = {
    "draw_offered": ("🤝", "offers a draw", "Accept", "Decline", "send_draw_response"),
    "takeback_offered": ("↩️", "wants a takeback", "Allow", "Deny",
                         "send_takeback_response"),
    "rematch_request": ("⚔️", "wants a rematch", "Accept", "Deny",
                        "send_rematch_response"),
}


ONLINE_WIN_RESULT_BY_REASON = {
    "checkmate":   ("white_wins",                  "black_wins"),
    "timeout":     ("white_wins_on_time",          "black_wins_on_time"),
    "resignation": ("white_wins_by_resignation",   "black_wins_by_resignation"),
    "abandonment": ("white_wins_by_abandonment",   "black_wins_by_abandonment"),
}
ONLINE_WIN_REASONS = frozenset(ONLINE_WIN_RESULT_BY_REASON)
ONLINE_DRAW_REASONS = {
    "draw_agreement", "draw_stalemate", "draw_repetition",
    "draw_fifty_move", "draw_insufficient_material",
}
ONLINE_STATIC_RESULTS = {"aborted", "aborted_disconnect", "server_shutdown"}

ONLINE_HARD_FAILURE_REASONS = {
    "server_unreachable", "reconnect_failed", "room_full",
}

ONLINE_HARD_FAILURE_LABELS = {
    "server_unreachable": "Server unreachable",
    "reconnect_failed": "Could not reconnect",
    "room_full": "Server is full",
}

ONLINE_TRANSIENT_REASON_LABELS = {
    "rate_limited": "Slow down a bit",
    "draw_offer_already_pending": "Draw offer already pending",
    "takeback_already_pending": "Takeback already pending",
    "no_takeback_available": "Nothing to take back",
    "rematch_already_pending": "Rematch already requested",
    "already_in_game": "Already in a game",
    "game_already_over": "This game has ended",
}

ONLINE_GAME_STATE_REASONS = {
    "not_your_turn", "invalid_move_format", "invalid_message",
    "version_mismatch",
}

MOVE_REJECTION_REASONS = {
    "invalid_move_format", "not_your_turn", "skillcheck_pending", "move_locked",
}

NOT_YOUR_TURN_TOASTS = {
    "takeback_request": "Take back is only available right after your move",
}


class OnlineEventsMixin:

    def _drain_online_inbound(self):
        if self.online_client is None:
            return
        for event in self.online_client.drain_inbound():
            try:
                self._handle_online_event(event)
            except Exception:
                log.exception("online event handler failed")

    def _handle_online_event(self, event):
        if event.type == "matchmake_response":
            return
        elif event.type == "game_start":
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
        pending_move = self.skillcheck_session._pending_online_move
        if pending_move is not None and reason in MOVE_REJECTION_REASONS:
            self.skillcheck_session._pending_online_move = None
            self.board.selected_square = None
            if reason in ("invalid_move_format", "not_your_turn"):
                self._begin_resync()
            return
        if reason == "not_your_turn":
            label = NOT_YOUR_TURN_TOASTS.get(payload.get("msg_type"))
            if label is not None:
                self.toast.show(label)
            return
        if reason in ONLINE_GAME_STATE_REASONS:
            return
        if reason == "rematch_unavailable":
            self.toast.show("Rematch no longer available", key=REMATCH_STATE_TOAST_KEY)
            self._end_rematch_window()
            return
        if reason == "room_lost":
            log.warning("online room lost — server restarted mid-game")
            self._resyncing = False
            self.result_flow._auto_save_pgn()
            self.reconnecting_modal.hide()
            self.offer_banners.clear()
            self.confirm_modal.show(
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
            self.confirm_modal.show(
                label,
                on_yes=self._restart_online_search,
                on_no=self._on_online_cancel,
                yes_label="New Search", no_label="Cancel",
            )
            return
        if reason:
            label = ONLINE_TRANSIENT_REASON_LABELS.get(reason, reason)
            self.toast.show(label)
        else:
            self.toast.show("Server error")

    def _opp_name(self):
        opp_color = "black" if self._chosen_side == "white" else "white"
        return self._name_for_color(opp_color)

    def _push_rematch_banner(self):
        self._rematch_offered = True
        icon, verb, ok_label, no_label, _ = OFFER_BANNERS["rematch_request"]
        self.offer_banners.push(
            "rematch_request", icon, self._opp_name(), verb, ok_label, no_label,
            on_ok=self._accept_rematch, on_no=self._decline_rematch)

    def _clear_rematch_offer(self):
        self.offer_banners.dismiss("rematch_request")
        self._rematch_offered = False
        self.result_menu.set_rematch_offered(False)

    def _handle_rematch_request(self):
        if self.online_client is None:
            return
        log.info("rematch offer received")
        self._push_rematch_banner()
        self.result_menu.set_rematch_offered(True)
        self.sound_manager.play_give_time()

    def _reshow_rematch_banner(self):
        if self.online_client is None:
            return
        self._push_rematch_banner()

    def _accept_rematch(self):
        if self.online_client is not None:
            log.info("rematch response sent accepted=True")
            self.online_client.send_rematch_response(True)

    def _decline_rematch(self):
        self._clear_rematch_offer()
        if self.online_client is not None:
            log.info("rematch response sent accepted=False")
            self.online_client.send_rematch_response(False)

    def _end_rematch_window(self):
        self._clear_rematch_offer()
        self._tear_down_online_session("rematch_window_closed")
        self._return_to_menu_card()

    def _handle_rematch_update(self, payload):
        event = payload.get("event", "")
        log.info("rematch update event=%s", event)
        opp = self._opp_name()
        if event == "opponent_reconnecting":
            self.toast.show(f"{opp} disconnected — waiting…", key=REMATCH_STATE_TOAST_KEY)
            return
        if event == "opponent_returned":
            self.toast.show(f"{opp} is back", key=REMATCH_STATE_TOAST_KEY)
            return
        if event == "cancelled":
            self._clear_rematch_offer()
            self.toast.show(f"{opp} withdrew the rematch", key=REMATCH_STATE_TOAST_KEY)
            return
        labels = {
            "declined": f"{opp} declined the rematch",
            "opponent_left": f"{opp} left the game",
            "window_expired": "Rematch window closed",
        }
        self.toast.show(labels.get(event, "Rematch ended"), key=REMATCH_STATE_TOAST_KEY)
        self._end_rematch_window()

    def _push_offer_banner(self, event_type):
        if self.online_client is None:
            return
        icon, verb, ok_label, no_label, send_method = OFFER_BANNERS[event_type]
        opp_name = self._opp_name()
        send_response = getattr(self.online_client, send_method)
        log.info("offer received type=%s from=%s", event_type, opp_name)
        self.sound_manager.play_toast()

        def respond(value):
            def fire():
                log.info("offer responded type=%s accepted=%s", event_type, value)
                self.sound_manager.play_toast()
                send_response(value)
            return fire

        self.offer_banners.push(
            event_type, icon, opp_name, verb, ok_label, no_label,
            on_ok=respond(True), on_no=respond(False),
        )

    def _apply_clock_snap(self, payload, *, default_to_existing):
        clock_snap = payload.get("clock") or {}
        if self.match.clock is None:
            return
        if default_to_existing:
            white_default = self.match.clock.white_remaining
            black_default = self.match.clock.black_remaining
        else:
            white_default = 0.0
            black_default = 0.0
        self.match.clock.restore_from_server(
            clock_snap.get("white_remaining", white_default),
            clock_snap.get("black_remaining", black_default),
            clock_snap.get("running_for"),
        )

    def _begin_resync(self):
        if self._resyncing:
            return
        self._resyncing = True
        self.offer_banners.clear()
        self._resync_started_at_ms = pg.time.get_ticks()
        if self.online_client is not None:
            self.online_client.request_state_sync()

    def _handle_game_resumed(self, payload):
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
        self.skillcheck_session._apply_resumed_skillcheck_log(payload.get("skillcheck_log", []))
        self._restore_online_skillcheck_state(payload)
        self._resyncing = False

    def _restore_online_skillcheck_state(self, payload):
        self.skillcheck_session._teardown_skillcheck_overlay()
        self.skillcheck_session._pending_online_move = None
        self.skillcheck.clear_locks()
        for lock in payload.get("skillcheck_locks", []):
            self.skillcheck.lock(square_from_coord(lock["from_sq"]),
                                 square_from_coord(lock["to_sq"]))
        pending = payload.get("pending_skillcheck")
        if pending is not None:
            self._restore_pending_skillcheck(pending)

    def _handle_time_granted(self, payload):
        self._apply_clock_snap(payload, default_to_existing=False)
        added = float(payload.get("seconds_added", 0))
        granted_by = payload.get("granted_by")
        recipient_color = "black" if granted_by == "white" else "white"
        if granted_by == self._chosen_side:
            self.give_time._give_time_toast_for_giver(recipient_color, added)
        else:
            self.give_time._give_time_toast_for_receiver(granted_by, added)

    def _handle_takeback_applied(self, payload):
        if self._resyncing:
            return
        server_ply = payload.get("ply")
        expected = len(self.match.move_history) - 1
        if server_ply is not None and server_ply != expected:
            self._begin_resync()
            return
        if self.match.move_history:
            self.skillcheck_session._drop_skillcheck_log_from(len(self.match.move_history))
            last = self.match.move_history[-1].move
            self.match.undo()
            self.board.start_undo_animation(last)
            self.sound_manager.play_undo()
            log.info("takeback applied ply=%d", len(self.match.move_history))
        self._apply_clock_snap(payload, default_to_existing=True)

    def _handle_skill_check_required(self, payload):
        if self._resyncing:
            return
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        promo = payload.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        kind = SkillCheckKind(payload["kind"])
        self.skillcheck_session._pending_online_move = None
        self.skillcheck_session._online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self.skillcheck_session._online_skillcheck_opened_ms = pg.time.get_ticks()
        self.skillcheck_session._open_skillcheck_overlay(
            kind, payload["seed"], int(payload["value_diff"]),
            float(payload["deadline_ms"]), from_sq, to_sq, promo_type, online=True,
            elapsed_ms=float(payload.get("elapsed_ms", 0.0)),
            miss_count=int(payload.get("miss_count", 0)))

    def _handle_skill_check_result(self, payload):
        if self._resyncing:
            return
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        pending = self.skillcheck_session._online_skillcheck
        if self._is_my_open_check(from_sq, to_sq):
            self.skillcheck_session._record_online_fail(pending, from_sq, to_sq)
            aim_victim = self.board.aim_suppressed_square
            self.board.selected_square = None
            self._begin_online_verdict(
                False, lambda: self._apply_online_fail(from_sq, to_sq, aim_victim))
            return
        if self.skillcheck_session._online_spectate_kind is not None:
            self.skillcheck_session._record_online_fail(pending, from_sq, to_sq)
            aim_victim = self.board.aim_suppressed_square
            self.toast.show("Opponent missed!")
            self._begin_online_verdict(
                False, lambda: self._apply_spectate_fail(from_sq, to_sq, aim_victim))

    def _is_my_open_check(self, from_sq, to_sq):
        return (self.skillcheck_session._online_skillcheck is not None
                and self.skillcheck_session._online_spectate_kind is None
                and self.skillcheck_session._online_skillcheck[:2] == (from_sq, to_sq))

    def _begin_online_verdict(self, won, action):
        self.skillcheck_session._online_skillcheck = None
        self.skillcheck_session._online_spectate_kind = None
        self.skillcheck_session._online_verdict_action = action
        self.skillcheck_overlay.resolve_online(won)

    def _apply_online_fail(self, from_sq, to_sq, aim_victim):
        self.skillcheck.lock(from_sq, to_sq)
        log.info("skillcheck move locked from=%s to=%s online=True",
                 coord_from_square(from_sq), coord_from_square(to_sq))
        self._apply_spectate_fail(from_sq, to_sq, aim_victim)

    def _apply_spectate_fail(self, from_sq, to_sq, aim_victim):
        self.board.trigger_skillcheck_fail(
            from_sq, to_sq, on_fire=self.skillcheck_session._on_skillcheck_miss_fire)
        if aim_victim is not None:
            self.board.restore_piece(aim_victim)

    def _handle_skill_check_spectate(self, payload):
        if self._resyncing:
            return
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        promo = payload.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        kind = SkillCheckKind(payload["kind"])
        self.skillcheck_session._open_spectate_overlay(
            kind, payload["seed"], int(payload["value_diff"]),
            float(payload["deadline_ms"]), from_sq, to_sq, promo_type)
        self.toast.show("Opponent is lining up a shot…")

    def _handle_skill_check_spectate_shot(self, payload):
        if self._resyncing or self.skillcheck_session._online_spectate_kind is None:
            return
        self.skillcheck_overlay.spectate_shot(
            float(payload["elapsed_ms"]), int(payload["miss_count"]),
            bool(payload["won"]))

    def _restore_pending_skillcheck(self, pending):
        kind = SkillCheckKind(pending["kind"])
        from_sq = square_from_coord(pending["from_sq"])
        to_sq = square_from_coord(pending["to_sq"])
        promo = pending.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        elapsed_ms = float(pending.get("elapsed_ms", 0.0))
        miss_count = int(pending.get("miss_count", 0))
        if pending["color"] != self._chosen_side:
            self.skillcheck_session._open_spectate_overlay(
                kind, pending["seed"], int(pending["value_diff"]),
                float(pending["deadline_ms"]), from_sq, to_sq, promo_type,
                elapsed_ms=elapsed_ms, miss_count=miss_count)
            self.toast.show("Opponent is lining up a shot…")
            return
        self.skillcheck_session._online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self.skillcheck_session._online_skillcheck_opened_ms = pg.time.get_ticks() - int(elapsed_ms)
        self.skillcheck_session._open_skillcheck_overlay(
            kind, pending["seed"], int(pending["value_diff"]),
            float(pending["deadline_ms"]), from_sq, to_sq, promo_type, online=True,
            elapsed_ms=elapsed_ms, miss_count=miss_count)

    def _clear_online_move_locks(self, from_sq, to_sq):
        if self.mode != ONLINE:
            return
        self.skillcheck.clear_locks()
        if (self.skillcheck_session._pending_online_move is not None
                and self.skillcheck_session._pending_online_move[:2] == (from_sq, to_sq)):
            self.skillcheck_session._pending_online_move = None

    def _handle_remote_move_applied(self, payload):
        if self._resyncing:
            return
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        if payload.get("skill_check_kind") is not None:
            if self._is_my_open_check(from_sq, to_sq):
                self._begin_online_verdict(
                    True, lambda: self._apply_remote_move_payload(payload))
                return
            if self.skillcheck_session._online_spectate_kind is not None:
                self.toast.show("Opponent nailed it!")
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
            self._begin_resync()
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
                self.skillcheck_session._record_skillcheck(
                    kind, bool(payload.get("skill_check_won")),
                    payload.get("ply") or len(self.match.move_history))
        else:
            self._begin_resync()

    def _apply_online_result(self, reason, winner):
        if self.manual_result is not None:
            return False
        if reason in ONLINE_WIN_REASONS:
            white_code, black_code = ONLINE_WIN_RESULT_BY_REASON[reason]
            self.manual_result = white_code if winner == "white" else black_code
        elif reason in ONLINE_DRAW_REASONS:
            self.manual_result = reason
        elif reason in ONLINE_STATIC_RESULTS:
            self.manual_result = reason
        else:
            return False
        self.result_flow._on_result_final(self.manual_result)
        return True

    def _adopt_resumed_result(self, payload):
        reason = payload.get("result_reason") or ""
        self._apply_online_result(reason, payload.get("result_winner"))

    def _handle_online_result(self, payload):
        if self.manual_result is not None:
            return
        reason = payload.get("reason", "")
        if not self._apply_online_result(reason, payload.get("winner_color")):
            return
        self._first_move_deadline_ms = None
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self.offer_banners.clear()
        self.skillcheck_session._pending_online_move = None
        pending_action = self.skillcheck_session._online_verdict_action
        self.skillcheck_session._online_verdict_action = None
        try:
            if pending_action is not None:
                pending_action()
            self.skillcheck_session._teardown_skillcheck_overlay()
        except Exception:
            log.exception("online result verdict/teardown failed")
            self._begin_resync()
        if reason == "timeout" and not self._flag_fall_played:
            self._flag_fall_played = True
            self.sound_manager.play_flag_fall()

    def _begin_match_found_transition(self, payload):
        if self._pending_game_start_payload is not None:
            return
        self._pending_game_start_payload = payload
        now = pg.time.get_ticks()
        self._match_found_at_ms = now
        elapsed = float(payload.get("started_seconds_ago", 0.0))
        self._first_move_deadline_ms = now + int(
            (FIRST_MOVE_ABORT_SECONDS - elapsed) * 1000
        )
        self.wait_modal.hide()
        room_id = self.online_client.room_id if self.online_client is not None else None
        log.info("match found room=%s side=%s", room_id, payload.get("your_color"))
        self.match_found_modal.show(
            payload["white_name"], payload["black_name"], payload["your_color"],
            self._finish_match_found, seconds=MATCH_FOUND_SECONDS,
            white_country=payload.get("white_country") or "",
            black_country=payload.get("black_country") or "",
            rematch=bool(payload.get("rematch")),
        )
        self.sound_manager.play_online_game_start()

    def _finish_match_found(self):
        payload = self._pending_game_start_payload
        self._pending_game_start_payload = None
        self._match_found_at_ms = None
        self._wait_started_at_ms = None
        if payload is not None:
            self._start_online_game(payload)

    def _handle_connection_status(self, payload):
        opp_state = payload.get("opp_state", "connected")
        if opp_state == "reconnecting":
            if self._opp_disconnected_at_ms is None:
                self._opp_disconnected_at_ms = pg.time.get_ticks()
        else:
            self._opp_disconnected_at_ms = None
        if opp_state == "resyncing":
            self.toast.show("Opponent is resyncing…")

    def _start_online_game(self, payload):
        opp_name = (payload.get("white_name") if payload.get("your_color") == "black"
                    else payload.get("black_name"))
        log.info("game start mode=online side=%s vs=%s tc=%s+%s",
                 payload.get("your_color"), opp_name,
                 payload.get("time_minutes"), payload.get("increment_seconds"))
        pg.display.set_caption(f"Chess — vs {opp_name}")
        self.wait_modal.hide()
        self.confirm_modal.hide()
        self.start_menu.hide()
        self.manual_result = None
        self.result_menu.set_online_mode(True)
        self.mode = ONLINE
        self._online_initial_flip = (payload["your_color"] == "black")
        self._chosen_side = payload["your_color"]
        self.white_name = payload["white_name"]
        self.black_name = payload["black_name"]
        self.white_country = payload.get("white_country") or ""
        self.black_country = payload.get("black_country") or ""
        self._time_control = (payload["time_minutes"] * 60,
                              payload["increment_seconds"])
        self.match.mode = ONLINE
        self.match.local_color = (PieceColor.WHITE if payload["your_color"] == "white"
                                  else PieceColor.BLACK)
        self.match.on_local_move_applied = self._on_local_move_applied
        self._match_session_id = self._session_id_for_online()
        self._series_pair = tuple(sorted([payload["white_name"], payload["black_name"]]))
        self.result_flow._series_scores = {
            payload["white_name"]: float(payload.get("white_score", 0.0)),
            payload["black_name"]: float(payload.get("black_score", 0.0)),
        }
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self.skillcheck.reset(enabled=True, seed="online")
        self._reset_to_new_game()
        self.board.flipped = self._online_initial_flip

    def _on_local_move_applied(self, from_sq, to_sq, promotion):
        if self.online_client is None:
            return
        self.online_client.send_move(
            coord_from_square(from_sq), coord_from_square(to_sq), promotion,
        )
