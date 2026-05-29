"""Generate the app icons (.png/.ico/.icns) from the white queen on a tile.

Run from the repo root: `.venv/bin/python tools/make_icons.py`
Outputs land in assets/icons/ and are committed. The .icns is also produced
here when Pillow supports it; CI regenerates it via iconutil on macOS if not.
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "pieces_img", "queen_white.png")
OUT = os.path.join(ROOT, "assets", "icons")

SIZE = 1024
TILE_COLOR = (58, 125, 68, 255)   # chess green so the white queen reads on any dock
RADIUS = int(SIZE * 0.22)
MARGIN = int(SIZE * 0.05)
PIECE_SCALE = 0.82


def build_master():
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        [MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN],
        radius=RADIUS, fill=TILE_COLOR,
    )
    queen = Image.open(SRC).convert("RGBA")
    side = int(SIZE * PIECE_SCALE)
    queen = queen.resize((side, side), Image.LANCZOS)
    canvas.alpha_composite(queen, ((SIZE - side) // 2, (SIZE - side) // 2))
    return canvas


def main():
    os.makedirs(OUT, exist_ok=True)
    master = build_master()
    master.save(os.path.join(OUT, "icon.png"))
    master.save(
        os.path.join(OUT, "icon.ico"),
        sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)],
    )
    try:
        master.save(os.path.join(OUT, "icon.icns"))
        print("wrote icon.png, icon.ico, icon.icns")
    except Exception as exc:
        print("wrote icon.png, icon.ico; icon.icns skipped:", exc)


if __name__ == "__main__":
    main()
