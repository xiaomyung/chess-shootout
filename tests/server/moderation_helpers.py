import json
from importlib import resources

from chessshootout.backend.utils import Square, coord_from_square
from chessshootout.server.moderation import detector, geometry


def coord(x, y):
    return coord_from_square(Square(row=y, col=x))


def arrows_from_segments(segments):
    return [(coord(a[0], a[1]), coord(b[0], b[1])) for a, b in segments]


def highlights_from_cells(cells):
    return [coord(x, y) for x, y in cells]


def grid_cells(rows):
    return [(cx, cy) for cy, row in enumerate(rows)
            for cx, ch in enumerate(row) if ch == "#"]


def _load(name):
    resource = resources.files("chessshootout.server.moderation").joinpath(name)
    with resource.open(encoding="utf-8") as source:
        return json.load(source)


def pattern_entries():
    return _load("patterns.json")["patterns"]


def enabled_entries():
    return [entry for entry in pattern_entries() if entry["action"] != "DISABLED"]


def entry_by_id(pattern_id):
    for entry in pattern_entries():
        if entry["id"] == pattern_id:
            return entry
    raise KeyError(pattern_id)


def word_entries():
    return _load("words.json")["words"]


def letter_atlas():
    return _load("words.json")["letters"]


def letter_segment_atlas():
    return _load("words.json")["letter_segments"]


def digit_segment_atlas():
    return _load("words.json")["digit_segments"]


def digit_code_segments(text, step=None):
    atlas = digit_segment_atlas()
    if step is None:
        step = 2 if len(text) >= 4 else 3
    segments = []
    x = 0
    for ch in text:
        for a, b in atlas[ch][0]:
            segments.append([[a[0] + x, a[1]], [b[0] + x, b[1]]])
        x += step
    return segments


def spell_arrows(text, x0=0, y0=0):
    atlas = letter_segment_atlas()
    arrows = []
    x = x0
    for ch in text.upper():
        construction = atlas[ch][0]
        width = max(max(a[0], b[0]) for a, b in construction)
        depth = max(max(a[1], b[1]) for a, b in construction)
        if x + width > 7 or y0 + depth > 7:
            return None
        for a, b in construction:
            arrows.append((coord(a[0] + x, a[1] + y0), coord(b[0] + x, b[1] + y0)))
        x += width + 1
    return arrows


def canonical_arrows(entry):
    return arrows_from_segments(entry["segments"])


def canonical_highlights(entry):
    return highlights_from_cells(grid_cells(entry["grid"]))


def _scale_point(point, factor):
    return (point[0] * factor, point[1] * factor)


def _transform_cells(cells, op_key, factor):
    scaled = set()
    for cx, cy in cells:
        for i in range(factor):
            for j in range(factor):
                scaled.add((cx * factor + i, cy * factor + j))
    return [geometry.apply_op(p, op_key) for p in scaled]


def _transform_segments(segments, op_key, factor):
    out = []
    for a, b in segments:
        sa = geometry.apply_op(_scale_point(tuple(a), factor), op_key)
        sb = geometry.apply_op(_scale_point(tuple(b), factor), op_key)
        out.append((sa, sb))
    return out


def _shift_to_board(points, dx=0, dy=0):
    minx = min(p[0] for p in points)
    miny = min(p[1] for p in points)
    return [(p[0] - minx + dx, p[1] - miny + dy) for p in points]


def _fits(points):
    return all(0 <= x < 8 and 0 <= y < 8 for x, y in points)


def transformed_vector_arrows(segments, op_key, factor, dx=0, dy=0):
    seg = _transform_segments(segments, op_key, factor)
    flat = []
    for a, b in seg:
        flat.append(a)
        flat.append(b)
    shifted = _shift_to_board(flat, dx, dy)
    if not _fits(shifted):
        return None
    arrows = []
    for i in range(0, len(shifted), 2):
        arrows.append((coord(*shifted[i]), coord(*shifted[i + 1])))
    return arrows


def transformed_raster_highlights(cells, op_key, factor, dx=0, dy=0):
    transformed = _transform_cells(cells, op_key, factor)
    shifted = _shift_to_board(transformed, dx, dy)
    if not _fits(shifted):
        return None
    return [coord(x, y) for x, y in shifted]


def spell_cells(text, atlas, gap=2, x0=0, y0=0):
    cells = set()
    x = x0
    for ch in text:
        rows = atlas[ch.upper()]
        width = max(len(row) for row in rows)
        for cy, row in enumerate(rows):
            for cx, glyph_ch in enumerate(row):
                if glyph_ch == "#":
                    cells.add((x + cx, y0 + cy))
        x += width + gap
    return cells


def ocr_scan(cells):
    for op_key in geometry.D4_ALL:
        transformed = [geometry.apply_op(point, op_key) for point in cells]
        found = detector._scan_line(transformed)
        if found is not None:
            return found
    return None
