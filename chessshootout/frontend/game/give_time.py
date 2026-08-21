import logging
from typing import Any

import pygame as pg

from chessshootout.frontend.game.variant import Variant

from chessshootout.backend.clock import Clock
from chessshootout.backend.pieces import PieceColor, opponent_of
from chessshootout.server.protocol import GIVE_TIME_SECONDS, GIVE_TIME_TICK_MS


log = logging.getLogger("chess.frontend")

GIVE_TIME_DEBOUNCE_MS = 500
GIVE_TIME_RATCHET_MS_SLOW = 150
GIVE_TIME_RATCHET_MS_FAST = 55


class GiveTimeHold:
    """
    The give-time button on the game rail, which hands seconds from your own
    generosity to the other clock: a tap gives one chunk, holding the button
    keeps ratcheting chunks out until it is let go. Offline the clock is
    changed here and now; online only the length of the hold is sent, and the
    server's clock snapshot is what actually counts
    """

    def __init__(self, screen: Any) -> None:
        """
        Set the control up for the life of the game screen, with nothing held
        and the cooldown already elapsed so the first press is accepted

        :param screen: the GameScreen this control belongs to, and its only
            route to the match clock, the strips, the rail and the coordinator
        """
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

    def on_cooldown(self) -> bool:
        """
        Whether the button is still resting after the last gift, which the rail
        reads to grey it out. The pause is what stops a mashed button from
        emptying your own clock

        :returns: True while another gift would be refused
        """
        return pg.time.get_ticks() - self._last_give_time_at_ms < GIVE_TIME_DEBOUNCE_MS

    def on_give_time(self) -> None:
        """
        Begin a give-time press, the entry point for both the rail button and
        the G hotkey. It is refused on a dead board, during the cooldown and on
        a clock with no room left, which is toasted rather than silently
        ignored so the player knows why nothing happened
        """
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

    def tap_give_time(self) -> None:
        """
        Give one chunk of time and finish immediately, which is what the G
        hotkey does since a key press has no hold for the mouse to follow
        """
        self.on_give_time()
        if self.holding:
            self._end_give_time_hold()

    def update_give_time_hold(self) -> None:
        """
        Advance a hold that is under way, once per frame: every tick of the
        hold hands over another chunk and the ratchet clicks along with it. The
        hold ends by itself when the button or the cursor is let go, and is
        called off outright when the game stops accepting it -- a result, a
        resync, a skill check, a modal or a flag
        """
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

    def _maybe_play_give_ratchet(self, now: int, recipient: PieceColor,
                                 clock: Clock) -> None:
        """
        Click the ratchet while time is being wound over, speeding up as the
        receiving clock fills so the sound tells the player how much room is
        left without them looking away from the board

        :param now: current pygame tick count in milliseconds
        :param recipient: side receiving the time, whose clock sets the pace
        :param clock: the game clock both sides are read from
        """
        fill = 1.0
        if clock.initial_seconds > 0:
            fill = min(1.0, clock.remaining(recipient) / clock.initial_seconds)
        interval = (GIVE_TIME_RATCHET_MS_SLOW
                    + (GIVE_TIME_RATCHET_MS_FAST - GIVE_TIME_RATCHET_MS_SLOW) * fill)
        if now - self._give_time_last_ratchet_ms >= interval:
            self._give_time_last_ratchet_ms = now
            self.app.sound_manager.play_give_ratchet()

    def _end_give_time_hold(self) -> None:
        """
        Close a hold that the player let go of and report the gift. A press too
        short to reach its first tick still gives one chunk, so a quick click
        always counts. Online the server is told only how long the button was
        held and answers with the clocks it decided on, so the toast is left to
        that reply; offline the toast is raised right here
        """
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

    def cancel_give_time_hold(self) -> None:
        """
        Abandon a hold without reporting anything, used when the game stops
        accepting it mid-press and when a new game is set up. The seconds
        already handed over stay handed over -- only the hold itself is dropped
        """
        self.holding = False
        self._give_time_hold_recipient = None
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0

    def _pointer_over_give_button(self) -> bool:
        """
        Whether the cursor is still on the give-time button, which is what
        keeps a hold alive: sliding off the button ends it just like releasing

        :returns: True while the cursor sits over the button
        """
        rect = self.screen.right_menu.button_rects.get("give_time")
        return rect is not None and rect.collidepoint(pg.mouse.get_pos())

    def _give_time_recipient(self) -> PieceColor:
        """
        Decide whose clock the time goes on. Online it is always the opponent,
        since a player giving to themselves would be an exploit; offline both
        sides sit here, so the gift goes to whoever is to move

        :returns: the side that receives the seconds
        """
        screen = self.screen
        if screen.variant == "online" and screen.match.local_color is not None:
            return opponent_of(screen.match.local_color)
        return screen.match.current_turn()

    def toast_for_giver(self, recipient_color: PieceColor | str, added: float) -> None:
        """
        Tell the giver what their generosity came to, flashing the increment on
        the receiving strip as well. A clock already full accepts nothing, and
        says so instead of pretending time changed hands

        :param recipient_color: side that received the seconds, as a piece
            colour or as white or black
        :param added: seconds actually given, zero when the clock was full
        """
        screen = self.screen
        name = screen._name_for_color(recipient_color)
        if added <= 0:
            self.app.toast.show(f"{name} already at maximum time")
        else:
            log.info("give time granted seconds=%.1f", added)
            screen._strip_for_color(recipient_color).flash_increment(added)
            self.app.toast.show(f"Gave {int(round(added))} sec to {name}")
            self.app.sound_manager.play_give_time()

    def toast_for_receiver(self, giver_color: PieceColor | str, added: float) -> None:
        """
        Tell this player that the opponent just handed them time, flashing the
        increment on their own strip so the clock jump is not a mystery. Only
        reached online, where the server reports what it granted

        :param giver_color: side that gave the seconds, as a piece colour or as
            white or black
        :param added: seconds granted; nothing is shown when none were
        """
        screen = self.screen
        if added <= 0:
            return
        log.info("give time received seconds=%.1f", added)
        if screen.match.local_color is not None:
            screen._strip_for_color(screen.match.local_color).flash_increment(added)
        name = screen._name_for_color(giver_color)
        self.app.toast.show(f"{name} gave you {int(round(added))} seconds")
        self.app.sound_manager.play_give_time()
