"""Emit the multi-format app icons (.ico/.icns) from the design icon.png.

Run `.venv/bin/python tools/render_pieces.py` first (it renders the queen-on-dark
icon master to assets/icons/icon.png from the SVG sources), then run this:
`.venv/bin/python tools/make_icons.py`. Outputs land in assets/icons/ and are
committed. The .icns is produced here when Pillow supports it; CI regenerates it
via iconutil on macOS if not.
"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "icons")
SRC = os.path.join(OUT, "icon.png")


def main():
    master = Image.open(SRC).convert("RGBA")
    master.save(
        os.path.join(OUT, "icon.ico"),
        sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)],
    )
    try:
        master.save(os.path.join(OUT, "icon.icns"))
        print("wrote icon.ico, icon.icns")
    except Exception as exc:
        print("wrote icon.ico; icon.icns skipped:", exc)


if __name__ == "__main__":
    main()
