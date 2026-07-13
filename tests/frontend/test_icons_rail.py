import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.visual.icons import (
    draw_clock, draw_gear, draw_medal, draw_people, draw_play, draw_reticle, draw_swords,
)


_pygame_init = pygame_display(80, 80)

ICON_FNS = [draw_play, draw_clock, draw_medal, draw_swords, draw_people, draw_gear]


def _owned_surface(size=40):
    surf = pg.Surface((size, size), pg.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    return surf


def _nonempty_pixel_count(surface):
    w, h = surface.get_size()
    return sum(1 for x in range(w) for y in range(h) if surface.get_at((x, y))[3] > 0)


@pytest.mark.parametrize("icon_fn", ICON_FNS, ids=[fn.__name__ for fn in ICON_FNS])
def test_icon_renders_at_requested_size_nonempty(icon_fn):
    surface = _owned_surface(40)
    rect = surface.get_rect()
    icon_fn(surface, rect, "#ffcc00")
    assert surface.get_size() == (40, 40)
    assert _nonempty_pixel_count(surface) > 0


def test_reticle_renders_nonempty():
    surface = _owned_surface(40)
    draw_reticle(surface, surface.get_rect(), "#ffffff")
    assert _nonempty_pixel_count(surface) > 0


def test_reticle_alpha_param_changes_output():
    bright = _owned_surface(40)
    dim = _owned_surface(40)
    rect = bright.get_rect()
    draw_reticle(bright, rect, "#ffffff", alpha=255)
    draw_reticle(dim, rect, "#ffffff", alpha=60)
    bright_max = max(bright.get_at((x, y))[3] for x in range(40) for y in range(40))
    dim_max = max(dim.get_at((x, y))[3] for x in range(40) for y in range(40))
    assert bright_max > dim_max
