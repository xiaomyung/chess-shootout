"""Emoji are shipped as pre-rendered PNG sprites (assets/emoji_png/), not rendered
from a color font at runtime -- pygame's Windows SDL2_ttf has no libpng and cannot
decode Noto Color Emoji's CBDT bitmaps, so font rendering is blank there. These tests
pin: the path scheme, that every flag + UI glyph the client uses has a sprite that
loads and scales, graceful handling of unknown/empty chars, and a drift guard that
fails if any emoji literal in the source lacks a sprite."""

import re
from pathlib import Path

import pygame as pg
import pytest

import chessshootout
from tests.conftest import pygame_display
from chessshootout.frontend.visual.emoji import blit_emoji, emoji_png_path, emoji_surface
from chessshootout.infra.countries import CODES, flag_emoji

UI_EMOJI = ["⚔️", "🎲", "📁", "📄", "🏳️", "🤝", "↩️", "🎉", "✨", "🔥"]

# Arrows rendered as plain text via get_font, never through the emoji helper -- they
# are not color emoji and intentionally have no sprite. The check/cross marks are
# PGN-text only: written verbatim into saved .pgn comments and drawn in-app as line
# shapes (the move-list marker), never sprite-rendered.
TEXT_GLYPHS = {"→", "←", "↑", "↓", "✓", "✗"}

_SRC_ROOT = Path(chessshootout.__file__).resolve().parent

_EMOJI_RUN = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U00002300-\U000023FF"
    "\U0001F1E6-\U0001F1FF\U00002190-\U000021FF]"
    "[\U0000FE0F\U0000200D\U0001F1E6-\U0001F1FF\U0001F3FB-\U0001F3FF\U00002190-\U000021FF]*"
)


_pygame_init = pygame_display(128, 128)


def _distinct_colours(surf):
    seen = set()
    for y in range(0, surf.get_height(), 2):
        for x in range(0, surf.get_width(), 2):
            seen.add(tuple(surf.get_at((x, y))))
    return len(seen)


def test_flag_path_uses_lowercase_iso_under_countries():
    p = emoji_png_path("🇷🇴")
    assert p.parent.name == "countries"
    assert p.name == "ro.png"


def test_ui_emoji_path_uses_hex_codepoints_under_emoji():
    assert emoji_png_path("🎲").as_posix().endswith("emoji_png/emoji/1f3b2.png")
    assert emoji_png_path("🏳️").as_posix().endswith("emoji_png/emoji/1f3f3-fe0f.png")
    assert emoji_png_path("⚔️").as_posix().endswith("emoji_png/emoji/2694-fe0f.png")


@pytest.mark.parametrize("code", sorted(CODES))
def test_every_country_flag_has_a_sprite_that_loads(code):
    assert emoji_png_path(flag_emoji(code)).exists()
    surf = emoji_surface(flag_emoji(code), 32)
    assert surf is not None
    assert surf.get_width() > 0 and surf.get_height() == 32


@pytest.mark.parametrize("char", UI_EMOJI)
def test_every_ui_emoji_has_a_sprite_that_loads(char):
    assert emoji_png_path(char).exists()
    surf = emoji_surface(char, 32)
    assert surf is not None
    assert surf.get_size()[0] > 0


def test_emoji_surface_scales_to_requested_height():
    surf = emoji_surface("📁", 40)
    assert surf is not None
    assert surf.get_height() == 40
    assert surf.get_width() > 0


def test_flags_render_in_colour_not_monochrome():
    surf = emoji_surface("🇷🇴", 64)
    assert surf is not None
    assert _distinct_colours(surf) > 4


def test_blit_emoji_paints_pixels():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    assert blit_emoji(win, "📁", (64, 64), 48) is True
    painted = sum(1 for y in range(0, 128, 4) for x in range(0, 128, 4)
                  if win.get_at((x, y))[:3] != (0, 0, 0))
    assert painted > 0


def test_unknown_emoji_returns_none_gracefully():
    assert emoji_surface("😀", 32) is None
    assert blit_emoji(pg.display.get_surface(), "😀", (10, 10), 32) is False


def test_empty_string_returns_none():
    assert emoji_surface("", 32) is None
    assert flag_emoji("ZZ") == ""


def _source_emoji_literals():
    assert _SRC_ROOT.is_dir(), f"expected a walkable package dir at {_SRC_ROOT}"
    found = set()
    scanned = 0
    for path in _SRC_ROOT.rglob("*.py"):
        scanned += 1
        text = path.read_text(encoding="utf-8")
        for run in _EMOJI_RUN.findall(text):
            if run and not all(ch in TEXT_GLYPHS for ch in run):
                found.add(run)
    assert scanned > 50, f"only scanned {scanned} files, guard root is likely wrong"
    return found


def test_every_source_emoji_literal_has_a_sprite():
    missing = sorted(ch for ch in _source_emoji_literals()
                     if not emoji_png_path(ch).exists())
    assert not missing, f"emoji literals in source without a sprite: {missing}"


def test_ui_emoji_list_matches_source():
    literals = _source_emoji_literals()
    flags = {flag_emoji(c) for c in CODES}
    assert literals - flags == set(UI_EMOJI), (
        "UI emoji used in source diverged from the rendered set; "
        "update packaging/render_emoji.py and regenerate"
    )
