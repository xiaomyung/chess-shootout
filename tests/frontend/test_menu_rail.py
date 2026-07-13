"""Left nav rail: row hit-tests, active-row visual state (real pixels on the
owned surface), the crosshair reticle sliding on a view change (tween retarget),
the footer version line + credit link callback, and the Options row opening the
global options modal through the MenuScreen."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.frontend.menu.layout import compute_menu_layout
from chessshootout.frontend.menu.rail import (
    CREDIT_URL, ICON_X, LABEL_X, MenuRail, OPTIONS_ROW, RETICLE_INSET, ROWS,
)
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
    assert_pixel_color(surf, inactive.x + 5, inactive.y + 4, Colors.surface, tol=4), \
        "an inactive row paints no box of its own, just the rail's own panel fill"


def test_active_row_border_is_neutral_not_accent():
    rail, _ = _rail()
    rail.set_active("history", 0)
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 10_000)

    active = rail._row_rects["history"]
    r, g, b = surf.get_at((active.right - 2, active.centery))[:3]
    assert not (r > 40 and r > b + 15 and r >= g), \
        "the active row's own border must not carry the accent's warm tint"


def test_rail_panel_is_a_solid_opaque_column():
    rail, _ = _rail()
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 0)

    below_last_row = rail._row_rects["history"].bottom + 20
    assert_pixel_color(surf, rail.rect.centerx, below_last_row, Colors.surface, tol=4)
    assert_pixel_color(surf, rail.rect.right - 1, rail.rect.centery, Colors.border, tol=12)


def test_reticle_slides_from_the_old_row_to_the_new_one():
    rail, _ = _rail()
    play_cy = rail._row_rects["play"].centery
    history_cy = rail._row_rects["history"].centery
    assert abs(rail.reticle_y(0) - play_cy) < 1

    rail.set_active("history", 0)
    midway = rail.reticle_y(130)
    assert play_cy < midway < history_cy, "the reticle slides down toward the new row"
    assert abs(rail.reticle_y(5000) - history_cy) < 1, "and settles on it"


def test_reticle_starts_from_the_current_row_not_the_centre_on_switch():
    """cp2 regression: goto_view = set_active then relayout (set_rect + set_active).
    The slide must BEGIN at the old row, never at a stale mid/centre y. set_rect no
    longer retargets with its own clock, so the double call can't shove it forward."""
    rail, _ = _rail()  # active = play
    layout = compute_menu_layout(1000, 800, 36)
    play_cy = rail._row_rects["play"].centery
    rail.set_active("history", 1000)
    rail.set_rect(layout.rail_rect, layout.scale)
    rail.set_active("history", 1000)
    assert abs(rail.reticle_y(1000) - play_cy) < 1.5, "the slide begins at the play row"


def test_reticle_slide_stays_continuous_across_a_mid_slide_switch():
    """cp2: switching tabs mid-slide retargets from the CURRENT interpolated
    position — the y at the switch instant is unchanged (no jump)."""
    rail, _ = _rail()
    play_cy = rail._row_rects["play"].centery
    history_cy = rail._row_rects["history"].centery
    social_cy = rail._row_rects["social"].centery
    rail.set_active("history", 0)
    mid = rail.reticle_y(130)
    assert play_cy < mid < history_cy
    rail.set_active("social", 130)
    assert abs(rail.reticle_y(130) - mid) < 1.0, "no jump at the mid-slide switch"
    assert abs(rail.reticle_y(5000) - social_cy) < 1, "settles on the newly-picked row"


def test_reticle_survives_a_mid_slide_relayout():
    """cp2: a same-geometry relayout mid-slide remaps position without restarting
    the animation from elsewhere."""
    rail, _ = _rail()
    layout = compute_menu_layout(1000, 800, 36)
    rail.set_active("history", 0)
    mid = rail.reticle_y(130)
    rail.set_rect(layout.rail_rect, layout.scale)
    assert abs(rail.reticle_y(130) - mid) < 1.0


def test_double_set_active_same_row_is_a_noop():
    rail, _ = _rail()
    rail.set_active("history", 0)
    y1 = rail.reticle_y(60)
    rail.set_active("history", 60)
    assert rail.reticle_y(60) == y1, "re-selecting the active row must not perturb the slide"


def _has_warm_tint(surf, rect):
    for x in range(rect.x, rect.right):
        for y in range(rect.y, rect.bottom, 2):
            if not surf.get_rect().collidepoint((x, y)):
                continue
            r, g, b = surf.get_at((x, y))[:3]
            if r > 40 and r > b + 15 and r >= g:
                return True
    return False


def test_reticle_sits_inside_the_row_near_its_left_edge():
    """cp1: the crosshair now sits FULLY inside the active row, anchored just in
    from its left edge, so it can never be clipped by the rail/window edge. The
    guard checks it paints inside the row but past neither edge."""
    rail, _ = _rail()
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 0)

    row = rail._row_rects["play"]
    outside_left = pg.Rect(row.x - 10, row.y, 9, row.height)
    inside_left = pg.Rect(row.x + 2, row.y, 30, row.height)
    outside_right = pg.Rect(row.right + 1, row.y, 10, row.height)
    assert not _has_warm_tint(surf, outside_left), \
        "the reticle must not paint past the row's left edge anymore"
    assert _has_warm_tint(surf, inside_left), \
        "the reticle sits just inside the row's own left edge"
    assert not _has_warm_tint(surf, outside_right), \
        "nothing should paint past the row's right edge"


def test_reticle_is_a_visible_crosshair_not_a_tiny_dot():
    rail, _ = _rail()
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 0)

    row = rail._row_rects["play"]
    cx = row.x + max(int(RETICLE_INSET * rail.scale), 12)
    band = pg.Rect(cx - 16, row.y, 32, row.height)
    warm_pixels = 0
    for x in range(band.x, band.right):
        for y in range(band.y, band.bottom):
            if not surf.get_rect().collidepoint((x, y)):
                continue
            r, g, b = surf.get_at((x, y))[:3]
            if r > 40 and r > b + 15 and r >= g:
                warm_pixels += 1
    assert warm_pixels > 28, \
        "the reticle must read as a clearly visible crosshair, not a clipped dot"


def test_icon_and_label_share_the_same_x_active_or_not():
    rail, _ = _rail()
    rail.set_active("history", 0)
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    rail.draw(surf, 0)

    icon_x = rail.rect.x + max(int(ICON_X * rail.scale), 40)
    label_x = rail.rect.x + max(int(LABEL_X * rail.scale), 62)

    def painted(row_key, x):
        row = rail._row_rects[row_key]
        return any(
            surf.get_at((x, y))[:3] != (0, 0, 0)
            for y in range(row.y, row.bottom)
        )

    for key in ("history", "play", "battlepass", "social"):
        assert painted(key, icon_x + 1), f"icon column empty for {key}"
        assert painted(key, label_x + 1), f"label column empty for {key}"


def test_footer_shows_the_display_version_on_one_line():
    rail, _ = _rail()
    version = paths.get_app_version()
    expected = f"v{version} · by " if version else "dev · by "
    assert rail._footer_prefix == expected
    assert rail._footer_prefix_surf is not None


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
