"""Pre-render the emoji set used by the client into PNG sprites.

Why this exists: pygame's Windows SDL2_ttf wheel bundles a FreeType built without
libpng, so it cannot decode Noto Color Emoji's PNG-compressed CBDT bitmaps -> every
color glyph renders blank on Windows. Linux/macOS wheels include libpng and render
fine. Rather than depend on that at runtime, we render every glyph once here (on a
libpng-enabled platform) and ship the PNGs; the app blits those instead.

Run from the repo root on Linux/macOS:  python packaging/render_emoji.py

Output (consumed by chessshootout/frontend/visual/emoji.py::emoji_png_path):
  assets/emoji_png/countries/<iso2>.png   one per country flag
  assets/emoji_png/emoji/<hex-cps>.png     one per UI emoji

Source font (build-time only, NOT shipped): packaging/emoji/NotoColorEmoji.ttf
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pygame as pg

from chessshootout.frontend.visual.emoji import emoji_png_path
from chessshootout.infra.countries import CODES, flag_emoji

# Noto Color Emoji's bitmap strike tops out at 128px; rendering larger only
# upscales the same bitmap, so 128 is the native ceiling. The app downscales.
BASE_SIZE = 128

FONT_PATH = REPO_ROOT / "packaging" / "emoji" / "NotoColorEmoji.ttf"

# Every emoji the client passes to emoji_surface/blit_emoji that is NOT a flag.
# Keep in sync with the call sites (tests/test_emoji.py guards against drift):
#   match_found ROUND  -> "⚔️"
#   play hero side pick -> "\U0001f3b2"
#   directory browser  -> "\U0001f4c1" "\U0001f4c4"
#   confirm modal      -> "\U0001f4c1" "\U0001f3f3️" "\U0001f91d"
#   resign effect      -> "\U0001f3f3️"
#   online banners     -> "\U0001f91d" "↩️"
UI_EMOJI = (
    "⚔️",   # crossed swords
    "🎲",   # game die
    "📁",   # folder
    "📄",   # page
    "🏳️",   # white flag
    "🤝",   # handshake
    "↩️",   # left-hook arrow
    "🎉",   # party popper (combo confetti)
    "✨",   # sparkles (combo confetti)
    "🔥",   # fire (combo confetti)
)


def render_char(font, char):
    surf = font.render(char, True, (255, 255, 255))
    return surf.convert_alpha()


def main():
    pg.init()
    pg.display.set_mode((1, 1))
    font = pg.font.Font(str(FONT_PATH), BASE_SIZE)

    chars = [flag_emoji(code) for code in sorted(CODES)] + list(UI_EMOJI)
    blank = []
    for char in chars:
        surf = render_char(font, char)
        if surf.get_width() == 0 or surf.get_height() == 0:
            blank.append(char)
            continue
        path = emoji_png_path(char)
        path.parent.mkdir(parents=True, exist_ok=True)
        pg.image.save(surf, str(path))

    print(f"rendered {len(chars) - len(blank)} emoji PNGs at {BASE_SIZE}px")
    if blank:
        print(f"WARNING: {len(blank)} glyphs rendered blank: {blank}", file=sys.stderr)
        sys.exit(1)
    pg.quit()


if __name__ == "__main__":
    main()
