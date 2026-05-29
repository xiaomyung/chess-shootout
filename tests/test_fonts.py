from pathlib import Path

import pygame as pg
import pytest

import paths
from frontend.visual import fonts


@pytest.fixture(autouse=True)
def _font_init():
    pg.font.init()


def test_get_font_returns_font():
    assert isinstance(fonts.get_font(20), pg.font.Font)


def test_get_font_is_not_cached():
    # Deliberately NOT cached: a cached pygame Font holds an SDL_ttf handle that
    # is freed by pg.quit(); reusing it after a re-init segfaults. A fresh font
    # per call avoids the use-after-free (and fonts are built on resize, not per frame).
    assert fonts.get_font(20) is not fonts.get_font(20)


def test_all_variants_construct():
    plain = fonts.get_font(20)
    bold = fonts.get_font(20, bold=True)
    mono = fonts.get_font(20, mono=True)
    mono_bold = fonts.get_font(20, mono=True, bold=True)
    assert all(isinstance(f, pg.font.Font) for f in (plain, bold, mono, mono_bold))


def test_size_is_floored_to_one():
    assert isinstance(fonts.get_font(0), pg.font.Font)
    assert isinstance(fonts.get_font(-5), pg.font.Font)


def test_font_file_mapping_sans_and_mono():
    assert fonts._FONT_FILES[(False, False)] == "DejaVuSans.ttf"
    assert fonts._FONT_FILES[(False, True)] == "DejaVuSans-Bold.ttf"
    assert fonts._FONT_FILES[(True, False)] == "DejaVuSansMono.ttf"
    assert fonts._FONT_FILES[(True, True)] == "DejaVuSansMono-Bold.ttf"


def test_bundled_font_files_exist():
    for name in fonts._FONT_FILES.values():
        assert paths.resource_path("assets", "fonts", name).exists(), name


def test_falls_back_to_sysfont_when_bundled_missing(monkeypatch):
    # When the bundled TTF can't be loaded, get_font falls back to SysFont
    # (SysFont uses the real pg.font.Font internally, so it still returns a Font).
    monkeypatch.setattr(fonts, "resource_path", lambda *p: Path("/no/such/font.ttf"))
    assert isinstance(fonts.get_font(18), pg.font.Font)
