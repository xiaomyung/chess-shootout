import json
import os
import xml.etree.ElementTree as ET

import cairosvg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_DIR = os.path.join(ROOT, "assets", "battle_svg")
GUNS_SVG = os.path.join(SVG_DIR, "guns_svg")
FLASHES_SVG = os.path.join(SVG_DIR, "flashes_svg")
PNG_DIR = os.path.join(ROOT, "assets", "battle_png")
GUNS_PNG = os.path.join(PNG_DIR, "guns")
FLASHES_PNG = os.path.join(PNG_DIR, "flashes")
MANIFEST = os.path.join(PNG_DIR, "battle_manifest.json")

PX_PER_UNIT = 2.0


def _rasterize(svg_path, png_path):
    root = ET.parse(svg_path).getroot()
    minx, miny, w, h = (float(v) for v in root.attrib["viewBox"].split())
    ax = float(root.attrib["data-anchor-x"])
    ay = float(root.attrib["data-anchor-y"])
    gx = float(root.attrib.get("data-grip-x", ax))
    gy = float(root.attrib.get("data-grip-y", ay))
    out_w = max(round(w * PX_PER_UNIT), 1)
    out_h = max(round(h * PX_PER_UNIT), 1)
    cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=out_w, output_height=out_h)
    kx, ky = out_w / w, out_h / h
    return {"w": out_w, "h": out_h,
            "ax": round((ax - minx) * kx, 2), "ay": round((ay - miny) * ky, 2),
            "gx": round((gx - minx) * kx, 2), "gy": round((gy - miny) * ky, 2)}


def main():
    os.makedirs(GUNS_PNG, exist_ok=True)
    os.makedirs(FLASHES_PNG, exist_ok=True)
    manifest = {"scale": PX_PER_UNIT, "guns": {}, "flashes": {}}

    for fname in sorted(os.listdir(GUNS_SVG)):
        if not fname.endswith(".svg"):
            continue
        gun = fname[:-4]
        manifest["guns"][gun] = _rasterize(os.path.join(GUNS_SVG, fname),
                                           os.path.join(GUNS_PNG, gun + ".png"))

    for dname in sorted(os.listdir(FLASHES_SVG)):
        src = os.path.join(FLASHES_SVG, dname)
        if not os.path.isdir(src) or not dname.startswith("flashes_"):
            continue
        gun = dname[len("flashes_"):]
        out_dir = os.path.join(FLASHES_PNG, dname)
        os.makedirs(out_dir, exist_ok=True)
        variants = []
        for fname in sorted(f for f in os.listdir(src) if f.endswith(".svg")):
            stem = fname[:-4]
            variants.append(_rasterize(os.path.join(src, fname),
                                       os.path.join(out_dir, stem + ".png")))
        manifest["flashes"][gun] = variants

    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print(f"rendered {len(manifest['guns'])} guns + "
          f"{sum(len(v) for v in manifest['flashes'].values())} flashes")


if __name__ == "__main__":
    main()
