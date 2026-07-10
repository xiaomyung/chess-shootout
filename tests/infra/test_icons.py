import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout import paths


_pygame_init = pygame_display(100, 100)


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
