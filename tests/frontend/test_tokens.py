import os

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.helpers import read_source_without_docstrings
from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.paths import PIECES_PNG_DIR
from chessshootout.frontend.visual import fonts
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import (
    DISPLAY, SANS, MONO, get_font, get_display_font, get_mono_font,
)
from chessshootout import paths


_pygame_init = pygame_display(400, 300)


def test_base_palette_hex_values():
    """The base palette is the theming surface: every themeable knob pinned to its hex."""
    expected = {
        "bg": "#0c0e12", "surface": "#16191f", "surface_raised": "#1d212a",
        "surface_hover": "#272d38", "surface_active": "#333a47", "titlebar_bg": "#14161b",
        "well_deep": "#0f1218",
        "text": "#f3f5f8", "text_dim": "#9aa4b2", "text_muted": "#5c6573",
        "on_accent": "#1a0b06", "rail_icon": "#cfd6e0",
        "border": "#313947", "border_strong": "#475064",
        "accent": "#ff5a36", "accent_hi": "#ff7a5c", "accent_press": "#e6431f",
        "amber": "#ffb020", "amber_hi": "#ffc34d",
        "win": "#46d17f", "loss": "#ff5a4f", "check": "#ff3b3b",
        "white_tile": "#828b99", "black_tile": "#2e333b", "rim_light": "#e9e2d4",
    }
    for attr, hexval in expected.items():
        assert pg.Color(getattr(Colors, attr))[:3] == pg.Color(hexval)[:3], attr


def test_rail_icon_matches_bubble_pawn_text():
    """rail_icon deliberately shares its hex with bubble_pawn_text."""
    assert Colors.rail_icon == Colors.bubble_pawn_text


@pytest.mark.parametrize("state", ["connected", "reconnecting", "resyncing", "unknown"])
def test_connection_dot_color_is_opaque_hex(state):
    assert pg.Color(getattr(Colors, "dot_" + state)).a == 255


@pytest.mark.parametrize(
    "attr", ["move_indicator", "last_move", "selection_fill", "check_fill", "premove"])
def test_alpha_token_carries_transparency(attr):
    assert pg.Color(getattr(Colors, attr)).a < 255


@pytest.mark.parametrize("token, base, alpha", [
    pytest.param("overlay_scrim", "bg", "d9", id="overlay_scrim_from_bg"),
    pytest.param("accent_glow", "accent", "8c", id="accent_glow_from_accent"),
    pytest.param("text_selection", "accent", "66", id="text_selection_from_accent"),
    pytest.param("selection_fill", "accent", "38", id="selection_fill_from_accent"),
    pytest.param("move_indicator", "accent", "d9", id="move_indicator_from_accent"),
    pytest.param("amber_glow", "amber", "73", id="amber_glow_from_amber"),
    pytest.param("annotation_highlight", "amber", "57", id="annotation_highlight_from_amber"),
    pytest.param("annotation_arrow", "amber", "c7", id="annotation_arrow_from_amber"),
    pytest.param("annotation_arrow_preview", "amber", "80", id="annot_arrow_preview_from_amber"),
    pytest.param("annotation_highlight_opp", "avatar_blue", "57",
                 id="annotation_highlight_opp_from_avatar_blue"),
    pytest.param("annotation_arrow_opp", "avatar_blue", "c7",
                 id="annotation_arrow_opp_from_avatar_blue"),
    pytest.param("last_move", "amber", "47", id="last_move_from_amber"),
    pytest.param("mode_pill_bg", "amber", "1f", id="mode_pill_bg_from_amber"),
    pytest.param("mode_pill_border", "amber", "66", id="mode_pill_border_from_amber"),
    pytest.param("potg_bg", "amber", "1a", id="potg_bg_from_amber"),
    pytest.param("potg_border", "amber", "52", id="potg_border_from_amber"),
    pytest.param("check_fill", "check", "6b", id="check_fill_from_check"),
])
def test_alpha_token_is_base_plus_alpha(token, base, alpha):
    """Tints derive as base + alpha so swapping a base knob propagates to its tints."""
    assert getattr(Colors, token) == getattr(Colors, base) + alpha


def test_resyncing_dot_tracks_amber():
    """The resyncing dot reuses the amber knob (single source of truth)."""
    assert Colors.dot_resyncing == Colors.amber


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
    assert get_font(20) is not None
    assert get_mono_font(20) is not None
    assert get_display_font(20) is not None


def test_fonts_are_not_cached():
    """Caching Font objects across pg.quit() segfaults; get_font must return fresh objects."""
    assert get_font(20) is not get_font(20)


def test_fonts_py_has_no_cache_decorator():
    src = read_source_without_docstrings(fonts.__file__)
    assert "lru_cache" not in src and "@cache" not in src


def test_missing_font_falls_back_to_sysfont(monkeypatch):
    monkeypatch.setattr(fonts, "resource_path",
                        lambda *parts: paths.resource_path("does", "not", "exist.ttf"))
    f = get_font(18, family=SANS)
    assert isinstance(f, pg.font.Font)


def test_all_twelve_piece_pngs_load_at_512():
    for ptype in PieceType:
        for color in PieceColor:
            path = os.path.join(PIECES_PNG_DIR, f"{ptype.value}_{color.value}.png")
            assert os.path.exists(path), path
            img = pg.image.load(path)
            assert img.get_size() == (512, 512), (ptype, color, img.get_size())


def test_app_icon_and_brand_mark_exist():
    icons = paths.resource_path("assets", "icons")
    assert os.path.exists(os.path.join(icons, "icon.png"))
    assert os.path.exists(os.path.join(icons, "brand_mark.png"))
    mark = pg.image.load(os.path.join(icons, "brand_mark.png"))
    assert mark.get_width() > 0
