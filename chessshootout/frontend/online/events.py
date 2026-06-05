import logging

import pygame as pg

from chessshootout.backend.fen import apply_fen
from chessshootout.domain.match import ONLINE
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import PROMO_TYPE_BY_LETTER, coord_from_square, square_from_coord
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS


log = logging.getLogger("chess.frontend")

MATCH_FOUND_SECONDS = 3

OFFER_BANNERS = {
    "draw_offered": ("🤝", "offers a draw", "Accept", "Decline", "send_draw_response"),
    "takeback_offered": ("↩️", "wants a takeback", "Allow", "Deny",
                         "send_takeback_response"),
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
}

ONLINE_GAME_STATE_REASONS = {
    "not_your_turn", "invalid_move_format", "invalid_message",
    "version_mismatch",
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
        elif event.type == "error":
            self._handle_online_error(event.payload)

    def _handle_online_error(self, payload):
        reason = payload.get("reason", "")
        if reason == "not_your_turn":
            label = NOT_YOUR_TURN_TOASTS.get(payload.get("msg_type"))
            if label is not None:
                self.toast.show(label)
            return
        if reason in ONLINE_GAME_STATE_REASONS:
            return
        if reason == "room_lost":
            self._resyncing = False
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

    def _handle_rematch_request(self):
        self._rematch_offered = True
        self.result_menu.set_rematch_offered(True)
        self.toast.show("Opponent wants a rematch")

    def _push_offer_banner(self, event_type):
        if self.online_client is None:
            return
        icon, verb, ok_label, no_label, send_method = OFFER_BANNERS[event_type]
        opp_color = "black" if self._chosen_side == "white" else "white"
        opp_name = self._name_for_color(opp_color)
        send_response = getattr(self.online_client, send_method)
        self.offer_banners.push(
            event_type, icon, opp_name, verb, ok_label, no_label,
            on_ok=lambda: send_response(True),
            on_no=lambda: send_response(False),
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
        self.board._clear_premoves()
        self.board.clear_annotations()
        self._resyncing = False

    def _handle_time_granted(self, payload):
        self._apply_clock_snap(payload, default_to_existing=False)
        added = float(payload.get("seconds_added", 0))
        granted_by = payload.get("granted_by")
        recipient_color = "black" if granted_by == "white" else "white"
        if granted_by == self._chosen_side:
            self._give_time_toast_for_giver(recipient_color, added)
        else:
            self._give_time_toast_for_receiver(granted_by, added)

    def _handle_takeback_applied(self, payload):
        if self._resyncing:
            return
        server_ply = payload.get("ply")
        expected = len(self.match.move_history) - 1
        if server_ply is not None and server_ply != expected:
            self._begin_resync()
            return
        if self.match.move_history:
            last = self.match.move_history[-1].move
            self.match.undo()
            self.board.start_undo_animation(last)
            self.sound_manager.play_undo()
        self._apply_clock_snap(payload, default_to_existing=True)

    def _handle_remote_move_applied(self, payload):
        if self._resyncing:
            return
        san = payload.get("san")
        last = self.match.move_history[-1] if self.match.move_history else None
        if last is not None and last.san == san:
            self._apply_clock_snap(payload, default_to_existing=True)
            return
        server_ply = payload.get("ply")
        expected = len(self.match.move_history) + 1
        if server_ply is not None and server_ply != expected:
            self._begin_resync()
            return
        self._apply_clock_snap(payload, default_to_existing=True)
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        promo = payload.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        result = self.match.apply_remote_move(from_sq, to_sq, promo_type)
        if result.legal:
            self.board.animate_remote_move(from_sq, to_sq)
        else:
            self._begin_resync()

    def _handle_online_result(self, payload):
        self.offer_banners.clear()
        reason = payload.get("reason", "")
        winner = payload.get("winner_color")
        if reason in ONLINE_WIN_REASONS:
            white_code, black_code = ONLINE_WIN_RESULT_BY_REASON[reason]
            self.manual_result = white_code if winner == "white" else black_code
            winner_name = self._name_for_color(winner)
            self._series_scores[winner_name] = (
                self._series_scores.get(winner_name, 0.0) + 1
            )
        elif reason in ONLINE_DRAW_REASONS:
            self.manual_result = "draw_agreement"
            for name in (self.white_name, self.black_name):
                self._series_scores[name] = (
                    self._series_scores.get(name, 0.0) + 0.5
                )
        elif reason in ONLINE_STATIC_RESULTS:
            self.manual_result = reason
        if self.manual_result is not None:
            self._result_first_seen_at_ms = None
            self._first_move_deadline_ms = None
            self._opp_disconnected_at_ms = None
            self._local_disconnected_at_ms = None
            if reason == "timeout":
                self.sound_manager.play_flag_fall()
            if reason not in ONLINE_STATIC_RESULTS:
                self._auto_save_pgn()

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
        self.match_found_modal.show(
            payload["white_name"], payload["black_name"], payload["your_color"],
            self._finish_match_found, seconds=MATCH_FOUND_SECONDS,
            white_country=payload.get("white_country") or "",
            black_country=payload.get("black_country") or "",
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
        log.info("game start as %s vs %s", payload.get("your_color"), opp_name)
        pg.display.set_caption(f"Chess — vs {opp_name}")
        self.wait_modal.hide()
        self.confirm_modal.hide()
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
        self._series_scores = {
            payload["white_name"]: float(payload.get("white_score", 0.0)),
            payload["black_name"]: float(payload.get("black_score", 0.0)),
        }
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self._reset_to_new_game()
        self.board.flipped = self._online_initial_flip

    def _on_local_move_applied(self, from_sq, to_sq, promotion):
        if self.online_client is None:
            return
        self.online_client.send_move(
            coord_from_square(from_sq), coord_from_square(to_sq), promotion,
        )
