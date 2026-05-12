import logging

import pygame as pg

from backend.fen import apply_fen
from backend.match import ONLINE
from backend.pieces import PieceColor
from backend.utils import PROMO_TYPE_BY_LETTER, coord_from_square, square_from_coord
from frontend import env


log = logging.getLogger("chess.frontend")


ONLINE_WIN_REASONS = {"checkmate", "timeout", "resignation", "abandonment"}
ONLINE_DRAW_REASONS = {
    "draw_agreement", "draw_stalemate", "draw_repetition",
    "draw_fifty_move", "draw_insufficient_material",
}
ONLINE_STATIC_RESULTS = {"aborted", "server_shutdown"}

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
    "draw_offer": "You can only offer a draw on your own turn",
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
        elif event.type == "draw_offered":
            self._show_opp_offer_modal(
                "Opponent offers a draw", self.online_client.send_draw_response,
            )
        elif event.type == "takeback_offered":
            self._show_opp_offer_modal(
                "Opponent requests a takeback",
                self.online_client.send_takeback_response,
            )
        elif event.type == "takeback_applied":
            self._handle_takeback_applied(event.payload)
        elif event.type == "rematch_request":
            self._show_opp_offer_modal(
                "Opponent wants a rematch",
                self.online_client.send_rematch_response,
            )
        elif event.type == "game_resumed":
            self._handle_game_resumed(event.payload)
        elif event.type == "connection_status":
            return
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
            self.reconnecting_modal.hide()
            self.confirm_modal.show(
                "Server restarted — game ended",
                on_yes=self._restart_online_search,
                on_no=self._abandon_online_game,
                yes_label="New Search", no_label="Cancel",
            )
            return
        if reason in ONLINE_HARD_FAILURE_REASONS or reason.startswith("http_"):
            self.wait_modal.hide()
            label = ONLINE_HARD_FAILURE_LABELS.get(reason, "Server unreachable")
            self.confirm_modal.show(
                label,
                on_yes=lambda: self._on_server_addr_connect(env.get_server_addr()),
                on_no=self._on_online_cancel,
                yes_label="Retry", no_label="Cancel",
            )
            return
        if reason:
            label = ONLINE_TRANSIENT_REASON_LABELS.get(reason, reason)
            self.toast.show(label)
        else:
            self.toast.show("Server error")

    def _show_opp_offer_modal(self, title, send_response):
        self.confirm_modal.show(
            title,
            on_yes=lambda: send_response(True),
            on_no=lambda: send_response(False),
            yes_label="Accept", no_label="Decline",
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
        if self.online_client is not None:
            self.online_client.request_state_sync()

    def _handle_game_resumed(self, payload):
        self.match.new_game()
        for entry in payload.get("move_history", []):
            result = self.match.backend.apply_san(entry["san"])
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
        reason = payload.get("reason", "")
        winner = payload.get("winner_color")
        if reason in ONLINE_WIN_REASONS:
            self.manual_result = "white_wins" if winner == "white" else "black_wins"
            winner_name = self.white_name if winner == "white" else self.black_name
            if winner_name is not None:
                self._series_scores[winner_name] = (
                    self._series_scores.get(winner_name, 0.0) + 1
                )
        elif reason in ONLINE_DRAW_REASONS:
            self.manual_result = "draw_agreement"
            for name in (self.white_name, self.black_name):
                if name is not None:
                    self._series_scores[name] = (
                        self._series_scores.get(name, 0.0) + 0.5
                    )
        elif reason in ONLINE_STATIC_RESULTS:
            self.manual_result = reason
        if self.manual_result is not None:
            if reason == "timeout":
                self.sound_manager.play_flag_fall()
            self._auto_save_pgn()

    def _begin_match_found_transition(self, payload):
        if self._pending_game_start_payload is not None:
            return
        self._pending_game_start_payload = payload
        self._match_found_at_ms = pg.time.get_ticks()
        self.wait_modal.set_subtitle("Match found!")
        self.sound_manager.play_online_game_start()

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
        self._time_control = (payload["time_minutes"] * 60,
                              payload["increment_seconds"])
        self.match.mode = ONLINE
        self.match.local_color = (PieceColor.WHITE if payload["your_color"] == "white"
                                  else PieceColor.BLACK)
        self.match.on_local_move_applied = self._on_local_move_applied
        pair = tuple(sorted([payload["white_name"], payload["black_name"]]))
        if getattr(self, "_series_pair", None) != pair:
            self._series_pair = pair
            self._series_scores = {pair[0]: 0.0, pair[1]: 0.0}
        self._reset_to_new_game()
        self.board.flipped = self._online_initial_flip

    def _on_local_move_applied(self, from_sq, to_sq, promotion):
        if self.online_client is None:
            return
        self.online_client.send_move(
            coord_from_square(from_sq), coord_from_square(to_sq), promotion,
        )
