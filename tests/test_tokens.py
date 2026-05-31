import os
import pathlib

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from backend.pieces import PieceColor, PieceType
from backend.paths import PIECES_IMG_DIR
from frontend.visual import fonts
from frontend.visual.colors import Colors
from frontend.visual.fonts import (
    DISPLAY, SANS, MONO, get_font, get_display_font, get_body_font, get_mono_font,
)
import paths


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((400, 300))
    yield
    pg.quit()


# ----- colors --------------------------------------------------------------

def test_new_palette_hex_values():
    expected = {
        "white_tile": "#828b99", "black_tile": "#2e333b", "white": "#f3f5f8",
        "dark_menu": "#16191f", "light_grey_menu": "#1d212a", "button_border": "#313947",
        "accent": "#ff5a36", "amber": "#ffb020", "app_bg": "#0c0e12",
        "result_win": "#46d17f", "result_loss": "#ff5a4f", "border_strong": "#475064",
    }
    for attr, hexval in expected.items():
        assert pg.Color(getattr(Colors, attr))[:3] == pg.Color(hexval)[:3], attr


def test_connection_dots_keys_intact():
    assert set(Colors.connection_dots) == {
        "connected", "reconnecting", "disconnected", "unknown",
    }


def test_alpha_tokens_carry_transparency():
    # move indicator + washes are 8-digit hex with non-opaque alpha
    for attr in ("move_indicator", "last_move", "selection_fill", "check_fill", "premove"):
        assert pg.Color(getattr(Colors, attr)).a < 255, attr


# ----- fonts ---------------------------------------------------------------

def test_each_family_and_weight_loads():
    for family in (DISPLAY, SANS, MONO):
        for bold in (False, True):
            f = get_font(24, bold=bold, family=family)
            surf = f.render("Ag1", True, (255, 255, 255))
            assert surf.get_width() > 0 and surf.get_height() > 0


def test_get_font_default_family_follows_mono_flag():
    sans_name = fonts._FONT_FILES[(SANS, False)]
    mono_name = fonts._FONT_FILES[(MONO, False)]
    assert sans_name != mono_name
    # default (no family) picks sans; mono=True picks the mono family
    assert get_font(20) is not None
    assert get_mono_font(20) is not None
    assert get_display_font(20) is not None
    assert get_body_font(20, bold=True) is not None


def test_fonts_are_not_cached():
    # caching Font objects across pg.quit() segfaults; get_font must return fresh objects
    assert get_font(20) is not get_font(20)


def test_fonts_py_has_no_cache_decorator():
    src = pathlib.Path("frontend/visual/fonts.py").read_text()
    assert "lru_cache" not in src and "@cache" not in src


def test_missing_font_falls_back_to_sysfont(monkeypatch):
    monkeypatch.setattr(fonts, "resource_path",
                        lambda *parts: paths.resource_path("does", "not", "exist.ttf"))
    f = get_font(18, family=SANS)
    assert isinstance(f, pg.font.Font)


# ----- generated piece + icon assets ---------------------------------------

def test_all_twelve_piece_pngs_load_at_512():
    for ptype in PieceType:
        for color in PieceColor:
            path = os.path.join(PIECES_IMG_DIR, f"{ptype.value}_{color.value}.png")
            assert os.path.exists(path), path
            img = pg.image.load(path)
            assert img.get_size() == (512, 512), (ptype, color, img.get_size())


def test_app_icon_and_brand_mark_exist():
    icons = paths.resource_path("assets", "icons")
    assert os.path.exists(os.path.join(icons, "icon.png"))
    assert os.path.exists(os.path.join(icons, "brand_mark.png"))
    mark = pg.image.load(os.path.join(icons, "brand_mark.png"))
    assert mark.get_width() > 0
