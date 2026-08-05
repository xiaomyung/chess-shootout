import json
import random
from importlib import resources

from chessshootout.backend.utils import Square, coord_from_square
from chessshootout.server.moderation import geometry


DENSE_CLEAN_SEED = 0
DENSE_CLEAN_COUNT = 80
DENSE_STEPS = ((1, 0), (0, 1), (1, 1), (1, -1),
               (-1, 0), (0, -1), (-1, -1), (-1, 1))


def coord(x, y):
    return coord_from_square(Square(row=y, col=x))


def dense_clean_arrows():
    """The cost worst case a hostile client can hold in one legal store: 80
    single-square arrows (~70 distinct unit edges) scattered over the whole
    board in all eight directions, verdict CLEAN.

    Why this shape and not "many long arrows": every stage stays in its
    expensive branch. The vector stage enumerates a translation per
    (pattern edge, drawn edge) pair sharing a delta, and eight directions
    keep every delta bucket populated; the heuristic stays under
    HEURISTIC_SUBSET_MAX_EDGES so it runs the per-centre C4 subset scan
    instead of the cheap whole-set test; and CLEAN means nothing
    short-circuits early the way a blocked verdict does. Long random arrows
    (the input the other timing pin uses) fall out of the vector stage almost
    immediately and cost ~20x less, which is exactly why they hid this.

    detect() memoises on the exact arrow tuple, so rotating the list is a
    free cache bust for the attacker -- tests that time this input must
    rotate between samples or they measure the memo, not the detector."""
    rng = random.Random(DENSE_CLEAN_SEED)
    arrows = []
    seen = set()
    while len(arrows) < DENSE_CLEAN_COUNT:
        x, y = rng.randrange(8), rng.randrange(8)
        dx, dy = rng.choice(DENSE_STEPS)
        tx, ty = x + dx, y + dy
        if not (0 <= tx < 8 and 0 <= ty < 8):
            continue
        if ((x, y), (tx, ty)) in seen:
            continue
        seen.add(((x, y), (tx, ty)))
        arrows.append((coord(x, y), coord(tx, ty)))
    return arrows


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


SWASTIKA_SCREENSHOTS = {
    "v1_hooks_only_pinwheel": [
        [[3, 3], [4, 1]], [[3, 3], [5, 4]], [[3, 3], [2, 5]], [[3, 3], [1, 2]],
    ],
    "v2_cross_plus_tip_hooks": [
        [[3, 3], [3, 1]], [[3, 3], [5, 3]], [[3, 3], [3, 5]], [[3, 3], [1, 3]],
        [[3, 1], [5, 1]], [[5, 3], [5, 5]], [[3, 5], [1, 5]], [[1, 3], [1, 1]],
    ],
    "v3_overlapping_straight_arrow_pinwheel": [
        [[3, 1], [3, 3]], [[3, 3], [3, 5]], [[1, 3], [3, 3]], [[3, 3], [5, 3]],
        [[3, 1], [4, 1]], [[5, 3], [5, 4]], [[3, 5], [2, 5]], [[1, 3], [1, 2]],
    ],
    "v4_cross_plus_partial_hooks": [
        [[3, 1], [3, 5]], [[1, 3], [5, 3]],
        [[3, 1], [5, 1]], [[5, 3], [5, 5]], [[3, 5], [1, 5]],
    ],
}


# Long axis arms with rotationally-consistent DIAGONAL hooks: C4-chiral but
# matching no library template (the axis-hook long-arm form is now the
# swastika_axis7 template and hard-blocks; this stays the heuristic's case).
NOVEL_PINWHEEL = [
    [[3, 3], [3, 0]], [[3, 0], [5, 2]], [[3, 3], [6, 3]], [[6, 3], [4, 5]],
    [[3, 3], [3, 6]], [[3, 6], [1, 4]], [[3, 3], [0, 3]], [[0, 3], [2, 1]],
]
