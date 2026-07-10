"""Series-score chip: the name | score | name pill (dim names, amber-hi mono score
with an en-dash). Rendered on the online result modal. Verifies the palette, the
en-dash formatting, and that the result modal only paints it in online mode with a
series set."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font, get_mono_font
from chessshootout.frontend.visual.widgets import draw_series_chip
from chessshootout.frontend.modals.result import ResultMenu


_pg = pygame_display(620, 520)


def _stats():
    return {"kos": (3, 2), "material": 1, "streak": 2, "checks": 1,
            "moves": 30, "clock_left": 120.0, "play_of_the_game": None}


def _count(win, rect, color, tol=20):
    c = pg.Color(color)[:3]
    return sum(
        1
        for x in range(rect.x, rect.right)
        for y in range(rect.y, rect.bottom)
        if max(abs(win.get_at((x, y))[i] - c[i]) for i in range(3)) <= tol
    )


def test_series_chip_paints_amber_score_and_dim_names():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    rect = draw_series_chip(win, (310, 260), "alice", "bob", "2–1",
                            get_font(13, bold=True), get_mono_font(16))
    assert _count(win, rect, Colors.amber_hi) > 0
    assert _count(win, rect, Colors.text_dim) > 0


def test_set_series_formats_with_en_dash():
    menu = ResultMenu(pg.display.get_surface(), callbacks={})
    menu.set_series("alice", "bob", "2", "1")
    assert menu.series == ("alice", "bob", "2–1")
    menu.set_series(None, None, None, None)
    assert menu.series is None


def test_result_modal_paints_series_only_when_online():
    win = pg.display.get_surface()
    menu = ResultMenu(win, callbacks={})
    menu.set_rect(pg.Rect(80, 40, 440, 420))
    menu.set_result("VICTORY", "win", "Checkmate · 30 moves", _stats())
    menu.set_series("alice", "bob", "2", "1")
    region = pg.Rect(80, 40, 440, 420)

    win.fill((0, 0, 0))
    menu.set_online_mode(False)
    menu.draw()
    without = _count(win, region, Colors.amber_hi, tol=12)

    win.fill((0, 0, 0))
    menu.set_online_mode(True)
    menu.draw()
    with_series = _count(win, region, Colors.amber_hi, tol=12)

    assert without == 0
    assert with_series > 0
