import logging
import threading

import pygame as pg

from chessshootout.domain.match import ONLINE
from chessshootout.infra import env
from chessshootout.online.client import OnlineClient, fetch_resume, probe_active_game
from chessshootout.frontend.online.events import ONLINE_HARD_FAILURE_LABELS


log = logging.getLogger("chess.frontend")

RECONNECT_PROBE_INTERVAL_MS = 5000
RECONNECT_PROBE_MAX_ATTEMPTS = 3


class ReconnectProbe:

    def __init__(self, frontend):
        self.frontend = frontend
        self._pending_reconnect = None
        self._pending_reconnect_lock = threading.Lock()
        self._last_reconnect_probe_ms = 0
        self._reconnect_probe_inflight = False
        self._reconnect_probe_gen = 0
        self._reconnect_probe_attempts = 0

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
                    self._pending_reconnect = {
                        "addr": addr,
                        "room_id": reclaim["room_id"],
                        "session_token": reclaim["session_token"],
                    }
        finally:
            self._reconnect_probe_inflight = False

    def _refresh_reconnect_button(self):
        frontend = self.frontend
        if (frontend.mode == "menu" and frontend.online_client is None
                and pg.time.get_ticks() - self._last_reconnect_probe_ms
                >= RECONNECT_PROBE_INTERVAL_MS):
            self._spawn_reconnect_probe()
        with self._pending_reconnect_lock:
            available = self._pending_reconnect is not None
        frontend.start_menu.set_reconnect_available(available)

    def _on_reconnect_active_game(self):
        frontend = self.frontend
        with self._pending_reconnect_lock:
            self._reconnect_probe_gen += 1
            pending = self._pending_reconnect
            self._pending_reconnect = None
        if pending is None:
            return
        frontend.start_menu.set_reconnect_available(False)
        resume = fetch_resume(
            pending["addr"], pending["room_id"], pending["session_token"],
        )
        if resume is None:
            log.warning("reconnect: fresh /resume failed; restoring pending entry")
            with self._pending_reconnect_lock:
                self._pending_reconnect = pending
            frontend.start_menu.set_reconnect_available(True)
            frontend.confirm_modal.show(
                ONLINE_HARD_FAILURE_LABELS["reconnect_failed"],
                on_yes=self._on_reconnect_active_game,
                on_no=lambda: None,
                yes_label="Retry", no_label="Cancel",
            )
            return
        nickname = (resume["white_name"] if resume["your_color"] == "white"
                    else resume["black_name"])
        frontend.start_menu.text_input.text = nickname
        frontend.start_menu.selected_mode = ONLINE
        frontend.start_menu.selected_time_minutes = resume["time_minutes"]
        frontend.start_menu.selected_increment_seconds = resume["increment_seconds"]
        frontend.start_menu.selected_side = resume["your_color"]
        frontend.online_client = OnlineClient()
        frontend.match.on_local_move_applied = frontend._on_local_move_applied
        frontend._start_online_game(resume)
        frontend._handle_game_resumed(resume)
        frontend.online_client.reconnect_to_existing(
            pending["addr"], pending["room_id"], pending["session_token"], resume,
        )
        frontend.start_menu.hide()
