import os

import cairosvg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_DIR = os.path.join(ROOT, "assets", "pieces_svg")
PNG_DIR = os.path.join(ROOT, "assets", "pieces_png")
ICON_DIR = os.path.join(ROOT, "assets", "icons")

PIECE_PX = 512
ICON_PX = 1024

ACCENT = "#ff5a36"
AMBER = "#ffb020"
DEEP = "#e6431f"
CREAM = "#efe7d6"
CHAR = "#2b313b"
BRAND_DARK = "#1a0b06"

PALETTE = {
    "white": {"body": CREAM, "feat": "#231a10", "rim": "#2e333b", "eye_white": "#ffffff"},
    "black": {"body": CHAR, "feat": "#e9e2d4", "rim": "#828b99", "eye_white": "#e9e2d4"},
}

OUTLINE = 0.8


def _attr(fill, stroke=None, sw=0):
    out = f'fill="{fill}"'
    if stroke:
        out += f' stroke="{stroke}" stroke-width="{sw}"'
    return out


def _outlined(shape, p):
    rim = shape(p["rim"], p["rim"], OUTLINE * 2)
    return (f'<g stroke-linejoin="round" stroke-linecap="round">{rim}</g>'
            f'{shape(p["body"])}')


def _pawn_shape(fill, stroke=None, sw=0):
    a = _attr(fill, stroke, sw)
    return (f'<circle cx="50" cy="40" r="22" {a}/>'
            f'<ellipse cx="50" cy="63" rx="19" ry="7" {a}/>'
            f'<path d="M37,67 L31,103 L69,103 L63,67 Z" {a}/>'
            f'<rect x="22" y="99" width="56" height="16" rx="7" {a}/>')


def _pawn_face(p):
    f = p["feat"]
    return (f'<path d="M28,30 Q50,21 72,30 L72,38 Q50,30 28,38 Z" fill="{ACCENT}"/>'
            f'<circle cx="71" cy="34" r="4.5" fill="{ACCENT}"/>'
            f'<path d="M70,34 l9,-4 M70,35 l9,4" stroke="{ACCENT}" stroke-width="3" '
            f'stroke-linecap="round"/>'
            f'<path d="M38,40 L48,43" stroke="{f}" stroke-width="3.4" stroke-linecap="round"/>'
            f'<path d="M62,40 L52,43" stroke="{f}" stroke-width="3.4" stroke-linecap="round"/>'
            f'<circle cx="44" cy="47" r="3" fill="{f}"/>'
            f'<circle cx="56" cy="47" r="3" fill="{f}"/>')


def _queen_shape(fill, stroke=None, sw=0):
    a = _attr(fill, stroke, sw)
    return (f'<rect x="22" y="100" width="56" height="15" rx="7" {a}/>'
            f'<ellipse cx="50" cy="97" rx="22" ry="7" {a}/>'
            f'<path d="M34,100 Q32,78 44,66 L56,66 Q68,78 66,100 Z" {a}/>'
            f'<ellipse cx="50" cy="57" rx="13" ry="9.5" {a}/>'
            f'<ellipse cx="50" cy="37" rx="14.5" ry="16.5" {a}/>'
            f'<path d="M35,24 Q34,15 38,11 Q41,15 44,18 Q47,12 50,7 Q53,12 56,18 '
            f'Q59,15 62,11 Q66,15 65,24 Q50,27.5 35,24 Z" {a}/>')


def _queen_face(p):
    f = p["feat"]
    return (f'<circle cx="38" cy="11" r="2.2" fill="{ACCENT}"/>'
            f'<circle cx="50" cy="7.5" r="2.6" fill="{ACCENT}"/>'
            f'<circle cx="62" cy="11" r="2.2" fill="{ACCENT}"/>'
            f'<ellipse cx="43.5" cy="37" rx="3" ry="2.3" fill="{f}"/>'
            f'<ellipse cx="56.5" cy="37" rx="3" ry="2.3" fill="{f}"/>'
            f'<path d="M39,35.2 Q37,33.8 35.6,34.2" stroke="{f}" stroke-width="1.1" '
            f'fill="none" stroke-linecap="round"/>'
            f'<path d="M40,34.6 Q38.6,33.1 37.6,33" stroke="{f}" stroke-width="1" '
            f'fill="none" stroke-linecap="round"/>'
            f'<path d="M61,35.2 Q63,33.8 64.4,34.2" stroke="{f}" stroke-width="1.1" '
            f'fill="none" stroke-linecap="round"/>'
            f'<path d="M60,34.6 Q61.4,33.1 62.4,33" stroke="{f}" stroke-width="1" '
            f'fill="none" stroke-linecap="round"/>'
            f'<path d="M46,46 Q50,43.5 54,46 Q50,50 46,46 Z" fill="{ACCENT}"/>'
            f'<path d="M46,46 Q50,47 54,46" stroke="{DEEP}" stroke-width="0.8" fill="none"/>'
            f'<circle cx="41" cy="46" r="1" fill="{f}"/>')


def _king_shape(fill, stroke=None, sw=0):
    a = _attr(fill, stroke, sw)
    return (f'<rect x="22" y="100" width="56" height="15" rx="7" {a}/>'
            f'<ellipse cx="50" cy="97" rx="22" ry="7" {a}/>'
            f'<path d="M33,98 L36,58 L64,58 L67,98 Z" {a}/>'
            f'<ellipse cx="50" cy="59" rx="17" ry="7" {a}/>'
            f'<ellipse cx="50" cy="44" rx="16" ry="15.5" {a}/>'
            f'<rect x="34" y="23" width="32" height="10" rx="3" {a}/>')


def _king_face(p):
    f = p["feat"]
    return (f'<rect x="47.5" y="4" width="5" height="16" rx="1.5" fill="{ACCENT}"/>'
            f'<rect x="42.5" y="8.5" width="15" height="4.8" rx="1.5" fill="{ACCENT}"/>'
            f'<rect x="35.5" y="25.5" width="29" height="4.5" rx="2" fill="{ACCENT}"/>'
            f'<path d="M40,43 L48,45" stroke="{f}" stroke-width="3.2" stroke-linecap="round"/>'
            f'<path d="M60,43 L52,45" stroke="{f}" stroke-width="3.2" stroke-linecap="round"/>'
            f'<circle cx="45" cy="50" r="3" fill="{f}"/>'
            f'<circle cx="55" cy="50" r="3" fill="{f}"/>')


GENERATED = {
    "pawn": (_pawn_shape, _pawn_face),
    "queen": (_queen_shape, _queen_face),
    "king": (_king_shape, _king_face),
}

HANDCRAFTED = ("bishop", "knight", "rook")

PIECE_TYPES = ("pawn", "knight", "bishop", "rook", "queen", "king")


def piece_svg(piece_type, color):
    shape, face = GENERATED[piece_type]
    p = PALETTE[color]
    return (f'<svg viewBox="0 0 100 124" xmlns="http://www.w3.org/2000/svg">'
            f'{_outlined(shape, p)}{face(p)}</svg>')


def app_icon_svg():
    body = _outlined(_queen_shape, PALETTE["white"]) + _queen_face(PALETTE["white"])
    return (
        '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#1a1d24"/><stop offset="1" stop-color="#0c0e12"/>'
        '</linearGradient></defs>'
        '<rect x="1" y="1" width="98" height="98" rx="22" fill="url(#bg)" '
        'stroke="#475064" stroke-width="1"/>'
        f'<g transform="translate(15,6.6) scale(0.70)">{body}</g>'
        '</svg>'
    )


def brand_mark_svg():
    silhouette = _queen_shape(BRAND_DARK)
    return (
        '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
        '<defs><radialGradient id="hot" cx="0.32" cy="0.26" r="0.85">'
        f'<stop offset="0" stop-color="{AMBER}"/>'
        f'<stop offset="0.72" stop-color="{ACCENT}"/></radialGradient></defs>'
        '<rect x="0" y="0" width="100" height="100" rx="22" fill="url(#hot)"/>'
        f'<g transform="translate(15,6.6) scale(0.70)">{silhouette}</g>'
        '</svg>'
    )


def main():
    os.makedirs(SVG_DIR, exist_ok=True)
    os.makedirs(PNG_DIR, exist_ok=True)
    os.makedirs(ICON_DIR, exist_ok=True)
    for piece_type in PIECE_TYPES:
        for color in PALETTE:
            stem = f"{piece_type}_{color}"
            svg_path = os.path.join(SVG_DIR, stem + ".svg")
            if piece_type in HANDCRAFTED:
                with open(svg_path, encoding="utf-8") as fh:
                    svg = fh.read()
            else:
                svg = piece_svg(piece_type, color)
                with open(svg_path, "w", encoding="utf-8") as fh:
                    fh.write(svg)
            cairosvg.svg2png(bytestring=svg.encode(), write_to=os.path.join(PNG_DIR, stem + ".png"),
                             output_width=PIECE_PX, output_height=PIECE_PX)
    with open(os.path.join(SVG_DIR, "app_icon.svg"), "w", encoding="utf-8") as fh:
        fh.write(app_icon_svg())
    cairosvg.svg2png(bytestring=app_icon_svg().encode(),
                     write_to=os.path.join(ICON_DIR, "icon.png"),
                     output_width=ICON_PX, output_height=ICON_PX)
    with open(os.path.join(SVG_DIR, "brand_mark.svg"), "w", encoding="utf-8") as fh:
        fh.write(brand_mark_svg())
    cairosvg.svg2png(bytestring=brand_mark_svg().encode(),
                     write_to=os.path.join(ICON_DIR, "brand_mark.png"),
                     output_width=256, output_height=256)
    print("rendered 12 pieces + icon + brand mark")


if __name__ == "__main__":
    main()
