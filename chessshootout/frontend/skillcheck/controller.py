from collections.abc import Callable
from typing import Any

import pygame as pg

from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.visual.colors import Colors

SKILLCHECK_RESULT_HOLD_MS = 200


class EdgeTrigger:
    """
    A one-bit memory that fires only on the frame a condition turns true. The
    check views use it for cues that must sound once per crossing -- the
    wheel's tick as the needle enters the arc, the aim beep as the crosshair
    reaches the victim -- rather than on every frame the condition holds
    """

    def __init__(self) -> None:
        """
        Start with the condition remembered as false, so a condition that is
        already true on the very first update still counts as a rising edge
        """
        self._prev = False

    def update(self, inside: bool) -> bool:
        """
        Report this frame's state and say whether it just crossed into being
        true. Callers feed it once per frame; a condition that stays true
        reports its edge only on the frame it arrived

        :param inside: whether the condition holds this frame, normally the
            needle or crosshair being on target
        :returns: True only on the frame the condition turned true
        """
        inside = bool(inside)
        rising = inside and not self._prev
        self._prev = inside
        return rising


class SkillCheckController:
    """
    The half of every shootout mini-game that is the same whichever kind is
    running: the check's clock, the verdict and how long it is held on screen,
    the audio cues, and the read-only spectate behaviour. Wheel, steady-aim,
    whack and combo each subclass it to add their own drawing and shooting --
    the passive mirror is a MODE any of them can run in, never a class of its
    own
    """

    _audio = None
    _passive = False
    _landed = None

    def _init_common(self, challenge: Any, now_ms: int, deadline_ms: float, *,
                     on_shot: Callable[..., None] | None, passive: bool,
                     audio: SoundManager | None) -> None:
        """
        Lay down the state one check shares with every other, which each kind's
        constructor does before anything of its own. Handing in a shot hook, or
        arming the mirror, puts the controller in online mode: there the server
        owns the verdict and the view never decides one for itself, offline the
        view is the judge

        :param challenge: the kind's own pygame-free engine, holding the
            geometry and the hit tests the view draws and asks
        :param now_ms: pygame ticks in milliseconds the check counts from,
            already backdated by whatever of the deadline has gone
        :param deadline_ms: how long the whole check may run, in milliseconds
        :param on_shot: reports one shot to the server, None in a local game
        :param passive: True for the read-only mirror of the opponent's check
        :param audio: sound manager for this check's cues, None for silence
        """
        self.challenge = challenge
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self._on_shot = on_shot
        self._passive = passive
        self._online = on_shot is not None or passive
        self._audio = audio
        self._committed_at = None
        self._resolved_at = None
        self._landed = None

    def _init_victim(self, victim_surface: pg.Surface | None, cell_rect: pg.Rect) -> None:
        """
        Adopt the sprite of the piece being shot at, which the check draws
        itself while the board keeps that square suppressed. The sprite arrives
        at the board's current cell size, remembered here so a later resize
        rescales the original rather than an already scaled copy

        :param victim_surface: the victim's sprite, None when nothing stands
            on the square
        :param cell_rect: the square's rect in window pixels, whose width is
            the cell size the sprite was handed in at
        """
        self._victim_orig = victim_surface
        self._victim_orig_cell = max(int(cell_rect.width), 1)
        self._victim = victim_surface
        self._victim_cache = {}

    def _scaled_victim(self, new_cell: int) -> pg.Surface:
        """
        Give the victim's sprite at a new board cell size, resampling from the
        original once per distinct size and keeping it. Scaling an already
        scaled copy would smear the piece over a few resizes, so every size is
        derived from the sprite that was handed in

        :param new_cell: board cell width in pixels to fit the sprite to
        :returns: the sprite at that size, shared with earlier calls for it
        """
        if new_cell == self._victim_orig_cell:
            return self._victim_orig
        cached = self._victim_cache.get(new_cell)
        if cached is not None:
            return cached
        scale = new_cell / self._victim_orig_cell
        w = max(round(self._victim_orig.get_width() * scale), 1)
        h = max(round(self._victim_orig.get_height() * scale), 1)
        surf = pg.transform.smoothscale(self._victim_orig, (w, h))
        self._victim_cache[new_cell] = surf
        return surf

    def _frozen_elapsed(self) -> float:
        """
        Give the point in the check the view should draw at, which stops
        advancing the moment a shot is committed. Freezing it is what leaves
        the final needle, crosshair or prompt standing still while the verdict
        is held, instead of sliding on underneath it

        :returns: milliseconds into the check to draw
        """
        frozen = self._committed_at if self._committed_at is not None else self._now
        return frozen - self.start_ms

    def _done_after(self, hold_ms: int) -> bool:
        """
        Say whether the check has been shown for long enough to be retired,
        which is what the overlay waits for before the move lands or locks.
        Offline the hold runs from the player's own commit; online it runs from
        the server's verdict, so a shot is never wiped away before the answer
        to it arrives

        :param hold_ms: how long this kind lingers on its own verdict offline
        :returns: True once the view has nothing left to show
        """
        if self._online:
            return (self._resolved_at is not None
                    and self._now - self._resolved_at >= SKILLCHECK_RESULT_HOLD_MS)
        return (self._committed_at is not None
                and self._now - self._committed_at >= hold_ms)

    def _signal_color(self, live: str) -> str:
        """
        Pick the colour for whatever the check uses to signal danger and
        progress. The mirror is drawn in the neutral spectate colour instead,
        so a watcher never reads the opponent's check as one of their own

        :param live: colour token used while this player is shooting
        :returns: that token, or the spectate token in the passive mirror
        """
        return Colors.spectate if self._passive else live

    def _cue(self, method: str) -> None:
        """
        Play one of the sound manager's cues by name, the single route all
        check audio takes. The mirror stays silent, since every shot in it
        belongs to the opponent

        :param method: name of the play_* method to call on the sound manager
        """
        if self._audio is not None and not self._passive:
            getattr(self._audio, method)()

    def _emit_verdict(self) -> None:
        """
        Sound the win or miss sting the instant a check is decided, so the
        player hears the outcome as the view begins holding it
        """
        self._cue("play_skillcheck_win" if self.landed else "play_skillcheck_miss")

    def handle_event(self, event: pg.event.Event) -> bool:
        """
        Take the player's shot -- a left click or Space/Enter fires the check.
        Saying an event was taken is also what stops it reaching the board
        underneath, and once a shot is committed everything is taken, so a
        second tap can neither re-fire the check nor leak through to the game

        :param event: pygame event handed down by the router
        :returns: True when the event belongs to the check
        """
        if self._passive:
            return False
        if self._committed_at is not None:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._fire()
            return True
        if event.type == pg.KEYDOWN and event.key in (pg.K_SPACE, pg.K_RETURN):
            self._fire()
            return True
        return False

    def resolve(self, won: bool) -> None:
        """
        Take the server's verdict on an online check and start holding it on
        screen. This is the only way a live online check is ever decided -- the
        view never judges its own shot -- and it stamps the moment the shorter
        online hold runs from

        :param won: the server's answer, True when the move landed
        """
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        self._emit_verdict()

    def spectate_shot(self, elapsed: float, miss_count: int, won: bool, progress: int = 0,
                      direction: str | None = None,
                      target: tuple[float, float] | None = None) -> None:
        """
        Replay one shot the opponent fired, which is how the mirror keeps step
        with a check it is not playing. The kinds that show shots override
        this; the base does nothing, so a relay a kind has no use for is
        simply ignored

        :param elapsed: milliseconds into the check the shot was fired at, as
            the server reported it
        :param miss_count: shots the opponent had already missed before it
        :param won: True when that shot decided the check in their favour
        :param progress: hits or prompts they have answered in total
        :param direction: combo prompt they answered, None for other kinds
        :param target: aim point in board space as (row, column), None when the
            kind does not aim
        """
        pass

    def update(self, now_ms: int) -> None:
        """
        Advance the check by one frame, which is where a kind ticks its cues
        and, offline, notices its deadline has run out. The base does nothing,
        so a kind with no clock of its own needs no override

        :param now_ms: pygame tick count in milliseconds for this frame
        """
        pass

    def draw(self, window: pg.Surface) -> None:
        """
        Paint the check over the board. The shell draws the overlay after
        everything else, so whatever a check paints sits above the board, the
        panels, the banners and the toasts

        :param window: surface to draw on, the app window
        """
        pass

    def relayout(self, cell_rect: pg.Rect) -> None:
        """
        Re-anchor a live check after the window was resized or the board
        flipped, so it stays on the square it belongs to. Every kind rebuilds
        its whole geometry from the new cell size rather than scaling what it
        had

        :param cell_rect: the square's new rect in window pixels
        """
        self._apply_geometry(cell_rect)

    def close(self) -> None:
        """
        Give back anything the check borrowed from the rest of the app. Whack
        hides the mouse cursor while it runs and puts it back here; the other
        kinds borrow nothing, so the base does nothing
        """
        pass

    def set_board_rect(self, board_rect: pg.Rect | None) -> None:
        """
        Tell the check where the board is, which the kinds that dim everything
        around their target need in order to know what to cover. The base
        ignores it, since most kinds draw only on their own square

        :param board_rect: the board's rect in window pixels, None when there
            is no board area to dim
        """
        pass

    def victim_scale(self) -> float:
        """
        Say how big the piece being shot at should be drawn, so the board can
        keep the victim in step with a check that is shrinking it. Only
        steady-aim shrinks anything, so the base answers full size

        :returns: scale factor for the victim sprite, 1.0 when untouched
        """
        return 1.0

    @property
    def passive(self) -> bool:
        """
        Whether this is the read-only mirror of the opponent's check. Passive
        is a mode of every kind rather than a class of its own: the same view
        runs, but it takes no input and reports no shots

        :returns: True in the spectate mirror
        """
        return self._passive

    @property
    def done(self) -> bool:
        """
        Whether the check has finished and the overlay may hand its outcome to
        the game. Each kind decides when its verdict has been shown for long
        enough; the base is never done, so a kind must answer for itself

        :returns: True once the check is over and fully played out
        """
        return False

    @property
    def landed(self) -> bool | None:
        """
        The verdict: True when the move was won, False when it was fluffed,
        None while the check is still being fought. The overlay passes this
        back to the session, which lands or locks the move on the strength of
        it

        :returns: the outcome, None while it is undecided
        """
        return self._landed
