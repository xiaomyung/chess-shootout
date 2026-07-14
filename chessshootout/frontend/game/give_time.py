import logging

import pygame as pg

from chessshootout.frontend.game.variant import Variant

from chessshootout.backend.pieces import opponent_of
from chessshootout.server.protocol import GIVE_TIME_SECONDS, GIVE_TIME_TICK_MS


log = logging.getLogger("chess.frontend")

GIVE_TIME_DEBOUNCE_MS = 500
GIVE_TIME_RATCHET_MS_SLOW = 150
GIVE_TIME_RATCHET_MS_FAST = 55


class GiveTimeHold:

    def __init__(self, screen):
        self.screen = screen
        self.app = screen.app
        self._last_give_time_at_ms = -GIVE_TIME_DEBOUNCE_MS
        self.holding = False
        self._give_time_hold_start_ms = 0
        self._give_time_hold_last_tick_ms = 0
        self._give_time_last_ratchet_ms = 0
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0
        self._give_time_hold_recipient = None

    def on_cooldown(self):
        return pg.time.get_ticks() - self._last_give_time_at_ms < GIVE_TIME_DEBOUNCE_MS

    def on_give_time(self):
        screen = self.screen
        if self.holding:
            return
        if not screen.board_interactive():
            return
        if self.on_cooldown():
            return
        clock = screen.match.clock
        if clock is None or clock.flagged is not None:
            return
        recipient = self._give_time_recipient()
        if clock.initial_seconds - clock.remaining(recipient) <= 0:
            self.toast_for_giver(recipient, 0)
            return
        now = pg.time.get_ticks()
        self.holding = True
        self._give_time_hold_start_ms = now
        self._give_time_hold_last_tick_ms = now
        self._give_time_last_ratchet_ms = now
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0
        self._give_time_hold_recipient = recipient

    def update_give_time_hold(self):
        screen = self.screen
        if not self.holding:
            return
        clock = screen.match.clock
        if (screen.current_result() is not None
                or self.app.coordinator._resyncing or screen.skillcheck_overlay.is_active()
                or self.app._blocking_modal_visible()
                or clock is None or clock.flagged is not None):
            self.cancel_give_time_hold()
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
            self.app.sound_manager.play_give_ratchet()

    def _end_give_time_hold(self):
        screen = self.screen
        if not self.holding:
            return
        recipient = self._give_time_hold_recipient
        now = pg.time.get_ticks()
        hold_ms = now - self._give_time_hold_start_ms
        clock = screen.match.clock
        if self._give_time_hold_ticks == 0 and clock is not None:
            added = clock.add_time(recipient, GIVE_TIME_SECONDS)
            if added > 0:
                self._give_time_hold_added += added
                self._give_time_hold_ticks = 1
        total = self._give_time_hold_added
        self.holding = False
        self._give_time_hold_recipient = None
        self._last_give_time_at_ms = now
        if self.screen.variant == Variant.ONLINE and self.app.coordinator.is_connected():
            self.app.coordinator.send_give_time(hold_ms)
            return
        self.toast_for_giver(recipient, total)

    def cancel_give_time_hold(self):
        self.holding = False
        self._give_time_hold_recipient = None
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0

    def _pointer_over_give_button(self):
        rect = self.screen.right_menu.button_rects.get("give_time")
        return rect is not None and rect.collidepoint(pg.mouse.get_pos())

    def _give_time_recipient(self):
        screen = self.screen
        if screen.variant == "online" and screen.match.local_color is not None:
            return opponent_of(screen.match.local_color)
        return screen.match.current_turn()

    def toast_for_giver(self, recipient_color, added):
        screen = self.screen
        name = screen._name_for_color(recipient_color)
        if added <= 0:
            self.app.toast.show(f"{name} already at maximum time")
        else:
            log.info("give time granted seconds=%.1f", added)
            screen._strip_for_color(recipient_color).flash_increment(added)
            self.app.toast.show(f"Gave {int(round(added))} sec to {name}")
            self.app.sound_manager.play_give_time()

    def toast_for_receiver(self, giver_color, added):
        screen = self.screen
        if added <= 0:
            return
        log.info("give time received seconds=%.1f", added)
        if screen.match.local_color is not None:
            screen._strip_for_color(screen.match.local_color).flash_increment(added)
        name = screen._name_for_color(giver_color)
        self.app.toast.show(f"{name} gave you {int(round(added))} seconds")
        self.app.sound_manager.play_give_time()
