"""Shared helpers for the focus-mode test suite.

The collapse/expand animation is time-driven (pg.time.get_ticks). Tests install
a FakeTicks so a transition can be advanced deterministically frame by frame.
"""

import pygame as pg

from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.focus.transition import FOCUS_TRANSITION_MS


class FakeTicks:
    def __init__(self, start=10_000_000):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, ms):
        self.t += ms


def make_app(w=1000, h=800):
    app = Frontend(w, h)
    app.draw_frame()
    return app


def start_game(app, minutes=5, increment=0):
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": minutes, "increment_seconds": increment})
    app.draw_frame()
    return app


def install_clock(monkeypatch, clock):
    monkeypatch.setattr(pg.time, "get_ticks", clock)


def finish_transition(app, clock, step=40):
    for _ in range(int(FOCUS_TRANSITION_MS // step) + 3):
        clock.advance(step)
        app.draw_frame()


def collapse(app, clock):
    app._toggle_focus(True)
    finish_transition(app, clock)


def expand(app, clock):
    app._toggle_focus(False)
    finish_transition(app, clock)
