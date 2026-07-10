import logging

import pygame as pg

from chessshootout.domain.match import ONLINE
from chessshootout.backend.pieces import opponent_of
from chessshootout.server.protocol import GIVE_TIME_SECONDS, GIVE_TIME_TICK_MS


log = logging.getLogger("chess.frontend")

GIVE_TIME_DEBOUNCE_MS = 500
GIVE_TIME_RATCHET_MS_SLOW = 150
GIVE_TIME_RATCHET_MS_FAST = 55


class GiveTimeHold:

    def __init__(self, frontend):
        self.frontend = frontend
        self._last_give_time_at_ms = -GIVE_TIME_DEBOUNCE_MS
        self._give_time_holding = False
        self._give_time_hold_start_ms = 0
        self._give_time_hold_last_tick_ms = 0
        self._give_time_last_ratchet_ms = 0
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0
        self._give_time_hold_recipient = None

    def _give_time_on_cooldown(self):
        return pg.time.get_ticks() - self._last_give_time_at_ms < GIVE_TIME_DEBOUNCE_MS

    def _on_give_time(self):
        frontend = self.frontend
        if self._give_time_holding:
            return
        if not frontend.board_interactive():
            return
        if self._give_time_on_cooldown():
            return
        clock = frontend.match.clock
        if clock is None or clock.flagged is not None:
            return
        recipient = self._give_time_recipient()
        if clock.initial_seconds - clock.remaining(recipient) <= 0:
            self._give_time_toast_for_giver(recipient, 0)
            return
        now = pg.time.get_ticks()
        self._give_time_holding = True
        self._give_time_hold_start_ms = now
        self._give_time_hold_last_tick_ms = now
        self._give_time_last_ratchet_ms = now
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0
        self._give_time_hold_recipient = recipient

    def _update_give_time_hold(self):
        frontend = self.frontend
        if not self._give_time_holding:
            return
        clock = frontend.match.clock
        if (frontend.pgn_review or frontend.current_result() is not None
                or frontend._resyncing or frontend.skillcheck_overlay.is_active()
                or frontend._menu_overlay_active()
                or clock is None or clock.flagged is not None):
            self._cancel_give_time_hold()
            return
        if not pg.mouse.get_pressed()[0] or not self._pointer_over_give_button():
            self._end_give_time_hold()
            return
        now = pg.time.get_ticks()
        recipient = self._give_time_hold_recipient
        while now - self._give_time_hold_last_tick_ms >= GIVE_TIME_TICK_MS:
            self._give_time_hold_last_tick_ms += GIVE_TIME_TICK_MS
            added = clock.add_time(recipient, GIVE_TIME_SECONDS)
            if added <= 0:
                self._end_give_time_hold()
                return
            self._give_time_hold_added += added
            self._give_time_hold_ticks += 1
        self._maybe_play_give_ratchet(now, recipient, clock)

    def _maybe_play_give_ratchet(self, now, recipient, clock):
        fill = 1.0
        if clock.initial_seconds > 0:
            fill = min(1.0, clock.remaining(recipient) / clock.initial_seconds)
        interval = (GIVE_TIME_RATCHET_MS_SLOW
                    + (GIVE_TIME_RATCHET_MS_FAST - GIVE_TIME_RATCHET_MS_SLOW) * fill)
        if now - self._give_time_last_ratchet_ms >= interval:
            self._give_time_last_ratchet_ms = now
            self.frontend.sound_manager.play_give_ratchet()

    def _end_give_time_hold(self):
        frontend = self.frontend
        if not self._give_time_holding:
            return
        recipient = self._give_time_hold_recipient
        now = pg.time.get_ticks()
        hold_ms = now - self._give_time_hold_start_ms
        clock = frontend.match.clock
        if self._give_time_hold_ticks == 0 and clock is not None:
            added = clock.add_time(recipient, GIVE_TIME_SECONDS)
            if added > 0:
                self._give_time_hold_added += added
                self._give_time_hold_ticks = 1
        total = self._give_time_hold_added
        self._give_time_holding = False
        self._give_time_hold_recipient = None
        self._last_give_time_at_ms = now
        if frontend.mode == ONLINE and frontend.online_client is not None:
            frontend.online_client.send_give_time(hold_ms)
            return
        self._give_time_toast_for_giver(recipient, total)

    def _cancel_give_time_hold(self):
        self._give_time_holding = False
        self._give_time_hold_recipient = None
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0

    def _pointer_over_give_button(self):
        rect = self.frontend.right_menu.button_rects.get("give_time")
        return rect is not None and rect.collidepoint(pg.mouse.get_pos())

    def _give_time_recipient(self):
        frontend = self.frontend
        if frontend.mode == ONLINE and frontend.match.local_color is not None:
            return opponent_of(frontend.match.local_color)
        return frontend.match.current_turn()

    def _give_time_toast_for_giver(self, recipient_color, added):
        frontend = self.frontend
        name = frontend._name_for_color(recipient_color)
        if added <= 0:
            frontend.toast.show(f"{name} already at maximum time")
        else:
            log.info("give time granted seconds=%.1f", added)
            frontend._strip_for_color(recipient_color).flash_increment(added)
            frontend.toast.show(f"Gave {int(round(added))} sec to {name}")
            frontend.sound_manager.play_give_time()

    def _give_time_toast_for_receiver(self, giver_color, added):
        frontend = self.frontend
        if added <= 0:
            return
        log.info("give time received seconds=%.1f", added)
        if frontend.match.local_color is not None:
            frontend._strip_for_color(frontend.match.local_color).flash_increment(added)
        name = frontend._name_for_color(giver_color)
        frontend.toast.show(f"{name} gave you {int(round(added))} seconds")
        frontend.sound_manager.play_give_time()
