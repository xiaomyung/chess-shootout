"""The focus snapshot transition + partial present depend on a single-buffered
window. Guard the window flags so a future DOUBLEBUF/SCALED addition can't
silently break snapshots (which would grab garbage from a back buffer)."""

import pygame as pg

from chessshootout.frontend.window_chrome import WINDOW_FLAGS


def test_window_is_single_buffered():
    assert WINDOW_FLAGS & (pg.DOUBLEBUF | pg.SCALED) == 0
