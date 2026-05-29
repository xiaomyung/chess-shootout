import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

import paths
from frontend.modals.start import (
    FOOTER_PREFIX, FOOTER_SHINE_HOVER_PERIOD_MS, FOOTER_SHINE_PERIOD_MS,
    FOOTER_SHINE_SWEEP_MS, FOOTER_URL, StartMenu,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((900, 700))
    yield
    pg.quit()


def _menu(callbacks=None):
    menu = StartMenu(pg.display.get_surface(), callbacks or {})
    menu.set_rect(pg.Rect(150, 80, 600, 560))
    return menu


def test_footer_text_is_versioned_credit_line():
    # The displayed prefix is built from the live build version, so a bump
    # to paths.APP_VERSION flows straight into the menu footer.
    assert FOOTER_PREFIX.format(version=paths.APP_VERSION) == (
        f"Chess Shootout v{paths.APP_VERSION} - Designed and developed by "
    )


def test_footer_builds_and_draws():
    menu = _menu()
    assert menu._footer_prefix_surf is not None
    assert menu._footer_link_rect.width > 0
    # Footer sits at the bottom of the window, not inside the menu panel.
    assert menu._footer_link_rect.bottom <= 700
    assert menu._footer_link_rect.top > menu._outer.bottom - menu._outer.height
    menu.draw()  # must not raise


def test_clicking_link_opens_github_url():
    opened = []
    menu = _menu({"open_url": lambda url: opened.append(url)})
    menu.draw()
    assert menu.handle_click(menu._footer_link_rect.center) is True
    assert opened == [FOOTER_URL]


def test_link_hitbox_extends_beyond_text():
    # The clickable hitbox is padded around the glyphs, so a near-miss just
    # above the small text still opens the link.
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
    # Hover shortens the shine period so the same slide repeats faster.
    assert FOOTER_SHINE_HOVER_PERIOD_MS < FOOTER_SHINE_PERIOD_MS


def test_draw_runs_while_hovering(monkeypatch):
    menu = _menu()
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: menu._footer_link_hitbox.center)
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 100)
    menu.draw()  # hovered (quick) shine branch renders without error


def test_shine_phase_draws_in_and_out_of_sweep(monkeypatch):
    menu = _menu()
    in_sweep = FOOTER_SHINE_SWEEP_MS // 2
    out_of_sweep = (FOOTER_SHINE_SWEEP_MS + FOOTER_SHINE_PERIOD_MS) // 2
    monkeypatch.setattr(pg.time, "get_ticks", lambda: in_sweep)
    menu.draw()  # shine band visible this frame
    monkeypatch.setattr(pg.time, "get_ticks", lambda: out_of_sweep)
    menu.draw()  # shine idle this frame
