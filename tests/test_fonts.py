"""fonts.get_font must return a fresh, usable pygame Font per call.

Invariant: Fonts are deliberately NOT cached. A cached pygame Font holds an
SDL_ttf handle freed by pg.quit(); reusing it after a re-init segfaults. Fonts
are rebuilt on resize, not per frame, so a fresh font per call is cheap.
"""

from pathlib import Path

import pygame as pg
import pytest

import paths
from frontend.visual import fonts


@pytest.fixture(autouse=True)
def _font_init():
    pg.font.init()


@pytest.mark.parametrize(
    "bold, mono",
    [
        pytest.param(False, False, id="sans"),
        pytest.param(True, False, id="sans_bold"),
        pytest.param(False, True, id="mono"),
        pytest.param(True, True, id="mono_bold"),
    ],
)
def test_get_font_renders_usable_text(bold, mono):
    """Every variant returns a Font that renders nonzero-size text."""
    font = fonts.get_font(20, bold=bold, mono=mono)
    assert isinstance(font, pg.font.Font)
    surface = font.render("Hg", True, (255, 255, 255))
    assert surface.get_width() > 0
    assert surface.get_height() > 0


@pytest.mark.parametrize(
    "small, large",
    [pytest.param(12, 40, id="height_scales_with_size")],
)
def test_get_font_honors_requested_size(small, large):
    """The size argument is honored: a larger size yields a taller Font."""
    assert fonts.get_font(small).get_height() < fonts.get_font(large).get_height()


def test_get_font_is_not_cached():
    assert fonts.get_font(20) is not fonts.get_font(20)


@pytest.mark.parametrize(
    "size",
    [pytest.param(0, id="zero"), pytest.param(-5, id="negative")],
)
def test_size_is_floored_to_one(size):
    """Non-positive sizes floor to 1, matching the size-1 font exactly."""
    assert fonts.get_font(size).get_height() == fonts.get_font(1).get_height()


def test_bundled_font_files_exist():
    for name in fonts._FONT_FILES.values():
        assert paths.resource_path("assets", "fonts", name).exists(), name


def test_falls_back_to_sysfont_when_bundled_missing(monkeypatch):
    """When the bundled TTF can't load, get_font returns a SysFont Font instead."""
    monkeypatch.setattr(fonts, "resource_path", lambda *p: Path("/no/such/font.ttf"))
    assert isinstance(fonts.get_font(18), pg.font.Font)
