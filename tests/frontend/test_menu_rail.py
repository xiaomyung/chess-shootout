"""Left nav rail: row hit-tests, active-row visual state (real pixels on the
owned surface), the crosshair reticle sliding on a view change (tween retarget),
the footer version line + credit link callback, and the Options row opening the
global options modal through the MenuScreen."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.frontend.menu.layout import compute_menu_layout
from chessshootout.frontend.menu.rail import CREDIT_URL, MenuRail, OPTIONS_ROW, ROWS
from chessshootout.frontend.visual.colors import Colors
from tests.helpers import assert_pixel_color, make_app


_pygame_init = pygame_display(1000, 800)


def _rail():
    surf = pg.display.get_surface()
    layout = compute_menu_layout(1000, 800, 36)
    opened = []
    rail = MenuRail(surf, {"open_url": lambda url: opened.append(url)})
    rail.set_rect(layout.rail_rect, layout.scale)
    return rail, opened


def test_hit_test_returns_every_row_key():
    rail, _ = _rail()
    for key, _, _ in ROWS + (OPTIONS_ROW,):
        assert rail.hit_test(rail._row_rects[key].center) == key


def test_hit_test_between_rows_returns_none():
    rail, _ = _rail()
    play = rail._row_rects["play"]
    assert rail.hit_test((play.centerx, play.bottom + 2)) is None


def test_active_row_fills_raised_and_stays_flat_when_inactive():
    rail, _ = _rail()
    rail.set_active("history", 0)
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 10_000)

    active = rail._row_rects["history"]
    assert_pixel_color(surf, active.x + 5, active.y + 5, Colors.surface_raised, tol=8)

    inactive = rail._row_rects["armory"]
    assert surf.get_at((inactive.x + 5, inactive.y + 4))[:3] == (0, 0, 0), \
        "an inactive row paints no fill"


def test_reticle_slides_from_the_old_row_to_the_new_one():
    rail, _ = _rail()
    play_cy = rail._row_rects["play"].centery
    history_cy = rail._row_rects["history"].centery
    assert abs(rail.reticle_y(0) - play_cy) < 1

    rail.set_active("history", 0)
    midway = rail.reticle_y(130)
    assert play_cy < midway < history_cy, "the reticle slides down toward the new row"
    assert abs(rail.reticle_y(5000) - history_cy) < 1, "and settles on it"


def _has_warm_tint(surf, rect):
    for x in range(rect.x, rect.right):
        for y in range(rect.y, rect.bottom, 2):
            if not surf.get_rect().collidepoint((x, y)):
                continue
            r, g, b = surf.get_at((x, y))[:3]
            if r > 40 and r > b + 15 and r >= g:
                return True
    return False


def test_reticle_sits_at_the_row_left_edge_not_the_right():
    """v2.9.0: the crosshair moved from a right-edge dot to a left-edge
    reticle that straddles the row's own left boundary. The row's own accent
    border also paints warm pixels at its right edge, so the regression guard
    checks the margin strictly outside the row (where only a reticle, never
    the row itself, can paint) rather than fighting that overlap."""
    rail, _ = _rail()
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 0)

    row = rail._row_rects["play"]
    outside_left = pg.Rect(row.x - 9, row.y, 8, row.height)
    outside_right = pg.Rect(row.right + 1, row.y, 10, row.height)
    assert _has_warm_tint(surf, outside_left), \
        "the reticle must straddle and paint past the row's left edge"
    assert not _has_warm_tint(surf, outside_right), \
        "nothing should paint past the row's right edge anymore"


def test_footer_shows_the_display_version():
    rail, _ = _rail()
    version = paths.get_app_version()
    label = ("v" + version) if version else "(dev)"
    assert rail._version_text == "Chess Shootout " + label
    assert rail._version_surf is not None


def test_credit_link_click_opens_the_site():
    rail, opened = _rail()
    assert rail.handle_footer_click(rail._credit_hitbox.center) is True
    assert opened == [CREDIT_URL]


def test_footer_click_off_the_link_is_ignored():
    rail, opened = _rail()
    assert rail.handle_footer_click((rail.rect.centerx, rail.rect.y + 4)) is False
    assert opened == []


def test_options_row_opens_the_options_modal_via_the_menu_screen():
    app = make_app()
    app.draw_frame()
    options_rect = app.menu.rail._row_rects["options"]
    app.menu.handle_click(options_rect.center)
    assert app.options_modal.is_visible() is True
