import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

import paths


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((100, 100))
    yield
    pg.quit()


def test_icon_files_present():
    for name in ("icon.png", "icon.ico", "icon.icns"):
        assert paths.resource_path("assets", "icons", name).exists(), name


def test_icon_png_loads_as_surface():
    surf = pg.image.load(str(paths.resource_path("assets", "icons", "icon.png")))
    assert surf.get_width() > 0 and surf.get_height() > 0
