from collections.abc import Callable
from typing import Any

import pygame as pg

from chessshootout.frontend.skillcheck.controller import SkillCheckController


class SkillCheckOverlay:
    """
    The game screen's slot for the one skill check that may be running: it
    holds whichever kind's controller was built, hands it the frame and the
    input, and calls back exactly once when the check has been fought to a
    finish so the session can land or lock the move. The shell updates and
    draws it after everything else on the frame, which is what puts a check
    above the board and the panels
    """

    def __init__(self) -> None:
        """
        Start with the slot empty and no check running. One overlay is built
        with the game screen and reused for every check the game ever fires
        """
        self._controller = None
        self._context = None
        self._on_done = None
        self._last_draw_controller = None

    def start(self, controller: SkillCheckController, context: Any,
              on_done: Callable[[Any, bool | None], None]) -> None:
        """
        Put a check on screen. Anything still running is closed first, so a
        check that arrives while another is up -- a resync, a fresh server
        directive -- replaces it cleanly instead of stacking on top of it

        :param controller: the kind's controller, already built by the registry
        :param context: opaque token handed straight back to on_done; the
            session passes the move being fought over
        :param on_done: called once with that context and the verdict when the
            check has finished playing out
        """
        if self._controller is not None and self._controller is not controller:
            self._controller.close()
        self._controller = controller
        self._context = context
        self._on_done = on_done

    def is_active(self) -> bool:
        """
        Whether a check is on screen, which the rest of the game treats as a
        hold on everything else: no resign, no give-time, no board browsing
        while a shootout is being fought

        :returns: True while a check is running
        """
        return self._controller is not None

    def is_passive(self) -> bool:
        """
        Whether what is on screen is the read-only mirror of the opponent's
        check rather than one this player is shooting, which decides whether
        input is swallowed and whether the gun is drawn

        :returns: True while the mirror is up
        """
        return self._controller is not None and self._controller.passive

    def aim_victim_scale(self) -> float:
        """
        Report how far a steady-aim check has shrunk the piece it is shooting
        at, so the board draws the victim at the same size the check does

        :returns: scale factor for the victim sprite, 1.0 with nothing running
        """
        if self._controller is None:
            return 1.0
        return self._controller.victim_scale()

    def spectate_shot(self, elapsed: float, miss_count: int, won: bool, progress: int = 0,
                      direction: str | None = None,
                      target: tuple[float, float] | None = None) -> None:
        """
        Pass a shot the server relayed on to the mirror, so both players watch
        the same shootout. A relay that arrives with nothing running is
        dropped, since there is no check left to replay it in

        :param elapsed: milliseconds into the check the shot was fired at
        :param miss_count: shots the shooter had already missed before it
        :param won: True when that shot decided the check in their favour
        :param progress: hits or prompts they have answered in total
        :param direction: combo prompt they answered, None for other kinds
        :param target: aim point in board space as (row, column), None when the
            kind does not aim
        """
        if self._controller is not None:
            self._controller.spectate_shot(elapsed, miss_count, won, progress=progress,
                                           direction=direction, target=target)

    def handle_event(self, event: pg.event.Event) -> bool:
        """
        Offer an event to the live check first, before the board or the panels
        see it. A check being fought takes the clicks and keys it uses; the
        mirror takes nothing

        :param event: pygame event handed down by the router
        :returns: True when the check took the event
        """
        if self._controller is None:
            return False
        return self._controller.handle_event(event)

    def update(self, now_ms: int) -> None:
        """
        Run the live check's frame and retire it the moment it reports that it
        has finished showing its verdict. The callback fires here, inside the
        update, which is why the retiring controller is kept for one last draw

        :param now_ms: pygame tick count in milliseconds for this frame
        """
        if self._controller is None:
            return
        self._controller.update(now_ms)
        if self._controller.done:
            self._finish()

    def draw(self, window: pg.Surface) -> None:
        """
        Paint the live check, or -- on the frame it retired -- its final
        standing frame. The shell draws the screen before it updates the
        overlay, so on the handover frame the board has already stopped drawing
        the suppressed victim; that one extra frame is what stops the piece
        blinking as a check ends

        :param window: surface to draw on, the app window
        """
        controller = (self._controller if self._controller is not None
                      else self._last_draw_controller)
        self._last_draw_controller = None
        if controller is not None:
            controller.draw(window)

    def relayout(self, cell_rect: pg.Rect) -> None:
        """
        Move a live check onto its square's new rect after a resize or a board
        flip, so a check survives the window changing under it

        :param cell_rect: the square's new rect in window pixels
        """
        if self._controller is not None:
            self._controller.relayout(cell_rect)

    def set_board_rect(self, board_rect: pg.Rect | None) -> None:
        """
        Tell a live check where the board has moved to, which the kinds that
        dim everything around their target need to keep covering the right area

        :param board_rect: the board's rect in window pixels, None when there
            is no board area to dim
        """
        if self._controller is not None:
            self._controller.set_board_rect(board_rect)

    def resolve_online(self, won: bool) -> None:
        """
        Deliver the server's verdict to the check on screen, the only way an
        online check is ever decided. The overlay keeps showing it until the
        controller has held the outcome long enough to be read

        :param won: the server's answer, True when the move landed
        """
        if self._controller is not None:
            self._controller.resolve(won)

    def cancel(self) -> None:
        """
        Tear a check down without a verdict -- the game ended, the screen is
        leaving, a resync is about to rebuild everything. The pending last
        frame goes too, so an explicit teardown paints nothing more, and the
        controller is closed so anything it borrowed comes back
        """
        controller = self._controller
        self._controller = None
        self._context = None
        self._on_done = None
        self._last_draw_controller = None
        if controller is not None:
            controller.close()

    def _finish(self) -> None:
        """
        Retire a check that has played itself out and report it exactly once.
        The slot is emptied before the callback runs, so a callback that starts
        another check or leaves the screen finds the overlay free, and the
        retiring controller is parked for its single last draw
        """
        context = self._context
        controller = self._controller
        landed = controller.landed
        on_done = self._on_done
        self.cancel()
        self._last_draw_controller = controller
        if on_done is not None:
            on_done(context, landed)
