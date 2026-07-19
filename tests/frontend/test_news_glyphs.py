"""Guard: every character in the shipped news.json renders in the bundled news
font. A missing glyph renders as the identical .notdef box, so a char whose
rendered surface matches a known-missing private-use codepoint is a tofu box
(this is how "Options -> Online" shipped a red box for the U+2192 arrow)."""
import json

import pygame as pg

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.frontend.visual.fonts import get_font

_pygame_init = pygame_display(400, 400)

NEWS_FONT_SIZES = (13, 15, 17)


def _surface(font, ch):
    surf = font.render(ch, True, (255, 255, 255), (0, 0, 0))
    return (surf.get_size(), pg.image.tostring(surf, "RGB"))


def test_news_copy_has_no_unrenderable_glyphs():
    data = json.loads(paths.resource_path("news.json").read_text(encoding="utf-8"))
    chars = set()
    for item in data:
        chars.update(item["title"])
        chars.update(item["body"])
    chars.discard("\n")
    chars.discard(" ")
    bad = set()
    for size in NEWS_FONT_SIZES:
        font = get_font(size)
        tofu = _surface(font, "")
        for ch in chars:
            if _surface(font, ch) == tofu:
                bad.add(ch)
    assert not bad, (
        f"news.json uses glyphs the bundled font renders as a box: {sorted(bad)}")
