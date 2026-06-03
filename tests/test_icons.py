import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout import paths


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((100, 100))
    yield
    pg.quit()


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("icon.png", id="png"),
        pytest.param("icon.ico", id="ico"),
        pytest.param("icon.icns", id="icns"),
    ],
)
def test_icon_file_present_and_nonempty(name):
    path = paths.resource_path("assets", "icons", name)
    assert path.exists(), name
    assert path.stat().st_size > 0, name


def test_icon_png_loads_as_square_surface():
    """icon.png feeds pg.display.set_icon; it must be a non-empty square bitmap."""
    surf = pg.image.load(str(paths.resource_path("assets", "icons", "icon.png")))
    assert surf.get_width() == 1024
    assert surf.get_height() == 1024
