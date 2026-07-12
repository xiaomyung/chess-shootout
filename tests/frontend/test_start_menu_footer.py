import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.frontend.menu.start import (
    FOOTER_SHINE_HOVER_PERIOD_MS, FOOTER_SHINE_HOVER_SWEEP_MS, FOOTER_SHINE_PERIOD_MS,
    FOOTER_SHINE_SWEEP_MS, FOOTER_URL, StartMenu, footer_prefix_text,
)


_pygame_init = pygame_display(900, 700)


def _menu(callbacks=None):
    menu = StartMenu(pg.display.get_surface(), callbacks or {})
    menu.set_rect(pg.Rect(150, 80, 600, 560))
    return menu


def _link_region(menu):
    rect = menu._footer_link_rect
    return pg.image.tobytes(menu.window.subsurface(rect).copy(), "RGBA")


def _link_brightness(menu):
    return sum(pg.transform.average_color(menu.window.subsurface(menu._footer_link_rect))[:3])


def _draw_footer_frame(menu, monkeypatch, *, ticks, hovering):
    rect = menu._footer_link_rect
    menu.window.fill((20, 20, 20), rect.inflate(40, 40))
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
    pos = menu._footer_link_hitbox.center if hovering else (0, 0)
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: pos)
    menu.draw()


@pytest.mark.parametrize(
    "version, expected",
    [
        pytest.param(
            "1.2.3", "Chess Shootout v1.2.3 - Designed and developed by ",
            id="bundled_version_shown",
        ),
        pytest.param(
            "", "Chess Shootout (dev) - Designed and developed by ",
            id="no_version_file_shows_dev",
        ),
    ],
)
def test_footer_prefix_reflects_build_version(monkeypatch, version, expected):
    """CI bundles assets/version.txt; source/local dev has none, so the footer
    says (dev) rather than masquerading as a release."""
    monkeypatch.setattr(paths, "get_app_version", lambda: version)
    assert footer_prefix_text() == expected


def test_footer_builds_and_draws():
    """The footer sits at the bottom of the window, not inside the menu panel."""
    menu = _menu()
    assert menu._footer_prefix_surf is not None
    assert menu._footer_link_rect.width > 0
    assert menu._footer_link_rect.bottom <= 700
    assert menu._footer_link_rect.top > menu._outer.bottom - menu._outer.height
    menu.draw()


def test_clicking_link_opens_github_url():
    opened = []
    menu = _menu({"open_url": lambda url: opened.append(url)})
    menu.draw()
    assert menu.handle_click(menu._footer_link_rect.center) is True
    assert opened == [FOOTER_URL]


def test_link_hitbox_extends_beyond_text():
    """The clickable hitbox is padded around the glyphs, so a near-miss just
    above the small text still opens the link."""
    opened = []
    menu = _menu({"open_url": lambda url: opened.append(url)})
    menu.draw()
    above = (menu._footer_link_rect.centerx, menu._footer_link_rect.top - 4)
    assert menu._footer_link_rect.collidepoint(above) is False
    assert menu._footer_link_hitbox.collidepoint(above) is True
    assert menu.handle_click(above) is True
    assert opened == [FOOTER_URL]


def test_clicking_away_from_link_does_not_open_url():
    opened = []
    menu = _menu({"open_url": lambda url: opened.append(url)})
    menu.draw()
    menu.handle_click((5, 5))
    assert opened == []


def test_link_is_inert_while_menu_hidden():
    opened = []
    menu = _menu({"open_url": lambda url: opened.append(url)})
    menu.hide()
    assert menu.handle_click(menu._footer_link_rect.center) is False
    assert opened == []


def test_link_hover_detection(monkeypatch):
    menu = _menu()
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: menu._footer_link_hitbox.center)
    assert menu._footer_link_hovered() is True
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (0, 0))
    assert menu._footer_link_hovered() is False


def test_hover_makes_the_slide_cycle_quicker():
    """Hover shortens the shine period so the same slide repeats faster."""
    assert FOOTER_SHINE_HOVER_PERIOD_MS < FOOTER_SHINE_PERIOD_MS


def test_draw_runs_while_hovering(monkeypatch):
    """At a tick past the idle sweep but inside the shorter hover sweep, hover
    paints the shine while non-hover stays dark, so the link region brightens."""
    menu = _menu()
    tick = 5550
    assert tick % FOOTER_SHINE_PERIOD_MS >= FOOTER_SHINE_SWEEP_MS
    assert tick % FOOTER_SHINE_HOVER_PERIOD_MS < FOOTER_SHINE_HOVER_SWEEP_MS
    _draw_footer_frame(menu, monkeypatch, ticks=tick, hovering=False)
    idle = _link_region(menu)
    idle_brightness = _link_brightness(menu)
    _draw_footer_frame(menu, monkeypatch, ticks=tick, hovering=True)
    assert _link_region(menu) != idle
    assert _link_brightness(menu) > idle_brightness


def test_shine_phase_draws_in_and_out_of_sweep(monkeypatch):
    """Mid-sweep the white band overlays the link (brighter); past the sweep
    the footer falls back to the static link surface (dimmer, no shine)."""
    menu = _menu()
    in_sweep = FOOTER_SHINE_SWEEP_MS // 2
    out_of_sweep = (FOOTER_SHINE_SWEEP_MS + FOOTER_SHINE_PERIOD_MS) // 2
    _draw_footer_frame(menu, monkeypatch, ticks=in_sweep, hovering=False)
    sweep_region = _link_region(menu)
    sweep_brightness = _link_brightness(menu)
    _draw_footer_frame(menu, monkeypatch, ticks=out_of_sweep, hovering=False)
    assert _link_region(menu) != sweep_region
    assert sweep_brightness > _link_brightness(menu)
