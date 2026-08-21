"""
Shared helpers for the focus-mode test suite. The collapse/expand animation is
time-driven off pg.time.get_ticks(), so tests install a FakeTicks and advance it
by hand to step a transition frame by frame instead of sleeping
"""

from typing import TYPE_CHECKING

import pygame as pg

from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.focus.transition import FOCUS_TRANSITION_MS

if TYPE_CHECKING:
    import pytest


class FakeTicks:
    """
    A stand-in for pg.time.get_ticks that only moves when a test says so.
    Instances are callable, so one can be patched straight over the real
    function and every widget reading the tick count follows the test's pace
    """

    def __init__(self, start: int = 10_000_000) -> None:
        """
        Start the fake tick count high enough that code subtracting a duration
        from it never goes negative

        :param start: initial reading in milliseconds
        """
        self.t = start

    def __call__(self) -> int:
        """
        Report the current reading, which is what lets an instance stand in for
        pg.time.get_ticks itself

        :returns: current fake tick count in milliseconds
        """
        return self.t

    def advance(self, ms: int) -> None:
        """
        Move the fake clock on, the way a test says a frame or two went by

        :param ms: milliseconds to add to the current reading
        """
        self.t += ms


def make_app(w: int = 1000, h: int = 800) -> Frontend:
    """
    Boot the app shell at a given window size and draw one frame, so every rect
    the focus tests measure has been laid out

    :param w: window width in pixels
    :param h: window height in pixels
    :returns: the booted app shell, sitting on the menu screen
    """
    app = Frontend(w, h)
    app.draw_frame()
    return app


def start_game(app: Frontend, minutes: int = 5, increment: int = 0) -> Frontend:
    """
    Start a local single-screen game through the real start-menu callback, then
    draw a frame so the game screen is laid out and ready to collapse

    :param app: app shell to start the game on
    :param minutes: starting time per side in minutes
    :param increment: seconds added to a player's clock after each move
    :returns: the same app, now on a live game screen
    """
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": minutes, "increment_seconds": increment})
    app.draw_frame()
    return app


def install_clock(monkeypatch: "pytest.MonkeyPatch", clock: FakeTicks) -> None:
    """
    Put a fake tick source in place of pygame's, so the whole app reads the time
    the test hands it

    :param monkeypatch: the test's monkeypatch fixture, which undoes this after
        the test
    :param clock: the fake tick source to install
    """
    monkeypatch.setattr(pg.time, "get_ticks", clock)


def finish_transition(app: Frontend, clock: FakeTicks, step: int = 40) -> None:
    """
    Drive frames until a focus transition has certainly ended, which is what
    lets a test assert on the settled layout rather than on a moving one. A few
    frames past the duration are drawn so the screen has dropped the transition

    :param app: app shell to draw
    :param clock: the installed fake tick source, advanced per frame
    :param step: milliseconds each drawn frame takes
    """
    for _ in range(int(FOCUS_TRANSITION_MS // step) + 3):
        clock.advance(step)
        app.draw_frame()


def collapse(app: Frontend, clock: FakeTicks) -> None:
    """
    Enter focus mode the way the H hotkey does and let the animation finish, so
    the test is looking at the settled board-only layout

    :param app: app shell sitting on a live game
    :param clock: the installed fake tick source
    """
    app.game._toggle_focus(True)
    finish_transition(app, clock)


def expand(app: Frontend, clock: FakeTicks) -> None:
    """
    Leave focus mode and let the animation finish, so the test is looking at
    the settled full game layout

    :param app: app shell sitting on a live game in focus mode
    :param clock: the installed fake tick source
    """
    app.game._toggle_focus(False)
    finish_transition(app, clock)
