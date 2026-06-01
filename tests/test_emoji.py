"""Bundled color-emoji rendering: Noto Color Emoji loads, renders in colour at a
fixed strike, and emoji_surface scales it to the requested height."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.visual.emoji import blit_emoji, emoji_surface, has_emoji
from frontend.visual.fonts import get_emoji_font


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((128, 128))
    yield
    pg.quit()


def _distinct_colours(surf):
    seen = set()
    for y in range(0, surf.get_height(), 2):
        for x in range(0, surf.get_width(), 2):
            seen.add(tuple(surf.get_at((x, y))))
    return len(seen)


def test_emoji_font_is_bundled():
    assert get_emoji_font() is not None
    assert has_emoji() is True


def test_emoji_surface_scales_to_requested_height():
    surf = emoji_surface("📁", 40)
    assert surf is not None
    assert surf.get_height() == 40
    assert surf.get_width() > 0


def test_emoji_renders_in_colour_not_monochrome():
    surf = emoji_surface("🤝", 48)
    assert surf is not None
    assert _distinct_colours(surf) > 4


@pytest.mark.parametrize("char", ["📁", "📄", "🏳️", "🤝"])
def test_known_emoji_all_render(char):
    surf = emoji_surface(char, 32)
    assert surf is not None
    assert surf.get_size()[0] > 0


def test_blit_emoji_paints_pixels():
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    assert blit_emoji(win, "📁", (64, 64), 48) is True
    painted = sum(1 for y in range(0, 128, 4) for x in range(0, 128, 4)
                  if win.get_at((x, y))[:3] != (0, 0, 0))
    assert painted > 0
