"""ResultMenu render invariants: the intent accent rail, perspective-coloured
Anton outcome word, the 6-stat grid, the PLAY OF THE GAME strip, a primary-first
button row, and click routing."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.modals.result import BUTTONS, ResultMenu
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.widgets import BUTTON_LABEL_PADDING_PX, fit_text_to_rect


_pygame_init = pygame_display(900, 700)


def _no_op():
    pass


def _make_menu(pgn_available=True):
    callbacks = {key: _no_op for _, key in BUTTONS}
    return ResultMenu(pg.display.get_surface(), callbacks, lambda: pgn_available)


def _stats(kos=(5, 3), streak=4, checks=7, moves=31, clock_left=242.0, material=6,
           potg="Bxf7 kicked off a 3-KO streak"):
    return {
        "kos": kos, "streak": streak, "checks": checks, "moves": moves,
        "clock_left": clock_left, "material": material, "play_of_the_game": potg,
    }


def _has_color(win, rect, hexcolor, tol=24):
    want = pg.Color(hexcolor)
    rect = rect.clip(win.get_rect())
    for x in range(rect.x, rect.right, 2):
        for y in range(rect.y, rect.bottom, 2):
            c = win.get_at((x, y))
            if (abs(c.r - want.r) <= tol and abs(c.g - want.g) <= tol
                    and abs(c.b - want.b) <= tol):
                return True
    return False


def test_not_visible_until_result_set():
    menu = _make_menu()
    menu.set_rect(pg.Rect(0, 0, 440, 418))
    assert menu.is_visible() is False
    menu.set_result("VICTORY", "win", "Checkmate · 31 moves", _stats())
    assert menu.is_visible() is True


@pytest.mark.parametrize(
    "intent, rail_hex",
    [
        pytest.param("win", Colors.win, id="win_green_rail"),
        pytest.param("loss", Colors.loss, id="loss_red_rail"),
        pytest.param("draw", Colors.text_dim, id="draw_neutral_rail"),
    ],
)
def test_intent_accent_rail(intent, rail_hex):
    menu = _make_menu()
    rect = pg.Rect(60, 60, 440, 418)
    menu.set_rect(rect)
    menu.set_result("DRAW" if intent == "draw" else "VICTORY", intent, "x", _stats())
    menu.window.fill((0, 0, 0))
    menu.draw()
    rail_band = pg.Rect(rect.x + 24, rect.y + 1, 120, 4)
    assert _has_color(menu.window, rail_band, rail_hex, tol=40), \
        "the top accent rail should carry the intent colour"


def test_win_outcome_is_green():
    menu = _make_menu()
    rect = pg.Rect(60, 60, 440, 418)
    menu.set_rect(rect)
    menu.set_result("VICTORY", "win", "Checkmate · 31 moves", _stats())
    menu.window.fill((0, 0, 0))
    menu.draw()
    band = pg.Rect(rect.x, rect.y + 30, rect.width, int(rect.height * 0.22))
    assert _has_color(menu.window, band, Colors.win, tol=60)


def test_stats_grid_and_potg_render():
    menu = _make_menu()
    rect = pg.Rect(60, 60, 440, 418)
    menu.set_rect(rect)
    menu.set_result("VICTORY", "win", "Checkmate · 31 moves", _stats())
    menu.window.fill((0, 0, 0))
    menu.draw()
    assert _has_color(menu.window, rect, Colors.amber_hi, tol=40), "POTG label is amber"
    lower = pg.Rect(rect.x, rect.centery, rect.width, rect.height // 2)
    assert _has_color(menu.window, lower, Colors.surface, tol=10), "stat cells drawn"


def test_potg_absent_when_no_highlight():
    menu = _make_menu()
    rect = pg.Rect(60, 60, 440, 418)
    menu.set_rect(rect)
    menu.set_result("DRAW", "draw", "Stalemate · 20 moves", _stats(potg=None))
    menu.window.fill((0, 0, 0))
    menu.draw()
    assert not _has_color(menu.window, rect, Colors.potg_border, tol=10), \
        "no PLAY OF THE GAME strip when there is no highlight"


def test_primary_button_is_accent():
    menu = _make_menu()
    rect = pg.Rect(60, 60, 440, 418)
    menu.set_rect(rect)
    menu.set_result("VICTORY", "win", "x", _stats())
    menu.window.fill((0, 0, 0))
    menu.draw()
    primary = menu.button_rects["new_game"]
    assert _has_color(menu.window, primary.inflate(-8, -8), Colors.accent, tol=20), \
        "the first (New Game) button is the primary accent button"


@pytest.mark.parametrize(
    "size",
    [pytest.param((240, 230), id="tight"), pytest.param((440, 418), id="normal")],
)
def test_buttons_fit_and_stay_inside_modal(size):
    menu = _make_menu()
    rect = pg.Rect(50, 50, *size)
    menu.set_rect(rect)
    menu.set_result("VICTORY", "win", "Checkmate · 31 moves", _stats())
    menu.draw()
    for label, key in BUTTONS:
        br = menu.button_rects[key]
        assert rect.contains(br)
        fitted = fit_text_to_rect(menu.button_font.render(label, True, (255, 255, 255)), br)
        assert fitted.get_width() <= br.width - 2 * BUTTON_LABEL_PADDING_PX


def test_handle_click_fires_callback():
    fired = []
    cbs = {key: (lambda k=key: fired.append(k)) for _, key in BUTTONS}
    menu = ResultMenu(pg.display.get_surface(), cbs, lambda: True)
    menu.set_rect(pg.Rect(0, 0, 440, 418))
    menu.set_result("VICTORY", "win", "x", _stats())
    menu.draw()
    assert menu.handle_click(menu.button_rects["new_game"].center) is True
    assert fired == ["new_game"]


def test_reset_hides_menu_and_clears_buttons():
    """reset() returns the menu to its pristine, non-interactive state so stale
    buttons from a finished game can never be clicked in the next game."""
    menu = _make_menu()
    menu.set_rect(pg.Rect(0, 0, 440, 418))
    menu.set_result("VICTORY", "win", "Checkmate · 31 moves", _stats())
    menu.set_rematch_offered(True)
    menu.draw()
    assert menu.is_visible() is True
    assert menu.button_rects
    menu_center = menu.button_rects["menu"].center
    menu.reset()
    assert menu.is_visible() is False
    assert menu.button_rects == {}
    assert menu.rematch_offered is False
    assert menu.handle_click(menu_center) is False


def test_open_pgn_button_absent_when_provider_reports_unavailable():
    """The modal-level filter itself: whatever the flow behind the provider,
    a False answer removes Open PGN from the drawn row (and its click rect)
    while the remaining buttons keep their places."""
    menu = _make_menu(pgn_available=False)
    rect = pg.Rect(60, 60, 440, 418)
    menu.set_rect(rect)
    menu.set_result("VICTORY", "win", "Checkmate · 31 moves", _stats())
    menu.window.fill((0, 0, 0))
    menu.draw()
    assert "open_pgn" not in menu.button_rects
    assert "new_game" in menu.button_rects and "menu" in menu.button_rects


def test_online_rematch_offered_hides_initiate_button():
    """An incoming rematch request hides the result modal's initiate button; the
    drop-in banner carries Accept/Deny instead, avoiding a duplicate affordance."""
    callbacks = {"rematch": _no_op, "open_pgn": _no_op, "menu": _no_op}
    menu = ResultMenu(pg.display.get_surface(), callbacks, lambda: True)
    menu.set_rect(pg.Rect(0, 0, 440, 418))
    menu.set_online_mode(True)
    menu.set_result("DRAW", "draw", "By agreement · 20 moves", _stats(potg=None))
    menu.set_rematch_offered(True)
    assert menu.rematch_offered is True
    menu.window.fill((0, 0, 0))
    menu.draw()
    assert "rematch" not in menu.button_rects
    assert "menu" in menu.button_rects
