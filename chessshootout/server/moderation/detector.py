import math
from collections import defaultdict
from dataclasses import dataclass, field

from chessshootout.backend.utils import BOARD_SIZE, square_from_coord

from chessshootout.server.moderation import geometry, library


HEURISTIC_MIN_EDGES = 8
HEURISTIC_MAX_SPAN = 6
HEURISTIC_SUBSET_MAX_EDGES = 80
HEURISTIC_TIGHT_MIN_EDGES = 12
HEURISTIC_TIGHT_MAX_SPAN = 4
HEURISTIC_TIGHT_MIN_TIPS = 4
RASTER_HIGHLIGHT_SHARE = 0.3
COMPLEMENT_SCAN_MIN_CELLS = (BOARD_SIZE * BOARD_SIZE) // 2
CACHE_LIMIT = 512

CLEAN = "clean"
SUSPECT = "suspect"
BLOCKED = "blocked"

HEURISTIC_ID = "heuristic_c4"

_FLOORS = None
_CACHE = {}
_CACHE_ORDER = []


@dataclass
class Verdict:
    kind: str
    pattern_id: object = None
    matched_arrows: list = field(default_factory=list)
    matched_highlights: list = field(default_factory=list)


def union_sides(arrows_a, highlights_a, arrows_b, highlights_b):
    arrows = list(dict.fromkeys(list(arrows_a) + list(arrows_b)))
    highlights = list(dict.fromkeys(list(highlights_a) + list(highlights_b)))
    return arrows, highlights


def _square(coord):
    return square_from_coord(coord)


def _cell(coord):
    sq = square_from_coord(coord)
    return (sq.col, sq.row)


def _ensure_floors():
    global _FLOORS
    if _FLOORS is not None:
        return _FLOORS
    patterns = library.enabled_patterns()
    vector_floor = min(
        (_needed(len(variant.edges), pattern.coverage_threshold)
         for pattern in patterns for variant in pattern.vector_variants),
        default=1)
    raster_floor = min(
        (_needed(variant.ink, pattern.coverage_threshold)
         for pattern in patterns for variant in pattern.raster_variants),
        default=1)
    _FLOORS = (vector_floor, raster_floor)
    return _FLOORS


def _needed(size, threshold):
    return max(math.ceil(size * threshold), 1)


def _normalize_inputs(arrows, highlights):
    arrows = list(arrows)
    highlights = list(highlights)
    arrow_edges = []
    drawn_edges = set()
    for arrow in arrows:
        edges = geometry.arrow_unit_edges(_square(arrow[0]), _square(arrow[1]))
        arrow_edges.append((arrow, edges))
        drawn_edges |= edges
    cells = [_cell(coord) for coord in highlights]
    return arrows, highlights, arrow_edges, drawn_edges, cells


def _changed_edges_cells(changed):
    if changed is None:
        return None, None
    if isinstance(changed, str):
        return set(), {_cell(changed)}
    from_sq = _square(changed[0])
    to_sq = _square(changed[1])
    edges = geometry.arrow_unit_edges(from_sq, to_sq)
    cells = geometry.traversed_cells(geometry.arrow_segments(from_sq, to_sq))
    return edges, cells


def detect(arrows, highlights, changed=None, context=()):
    library.preload()
    arrows, highlights, arrow_edges, drawn_edges, cells = _normalize_inputs(arrows, highlights)
    context_cells = [_cell(coord) for coord in context]
    changed_edges, changed_cells = _changed_edges_cells(changed)
    key = (tuple(arrows), tuple(highlights), frozenset(context_cells),
           _changed_key(changed_edges, changed_cells))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    verdict = _run(arrows, highlights, arrow_edges, drawn_edges, cells, context_cells,
                   changed_edges, changed_cells)
    _cache_put(key, verdict)
    return verdict


def _changed_key(changed_edges, changed_cells):
    if changed_edges is None:
        return None
    return (frozenset(changed_edges), frozenset(changed_cells))


def _cache_put(key, verdict):
    if key in _CACHE:
        return
    _CACHE[key] = verdict
    _CACHE_ORDER.append(key)
    if len(_CACHE_ORDER) > CACHE_LIMIT:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)


def _run(arrows, highlights, arrow_edges, drawn_edges, cells, context_cells,
         changed_edges, changed_cells):
    if not arrows and not cells:
        return Verdict(CLEAN)

    supersample = geometry.DEFAULT_SUPERSAMPLE
    side = geometry.board_width(supersample)
    segments = []
    for arrow in arrows:
        segments.extend(geometry.arrow_segments(_square(arrow[0]), _square(arrow[1])))
    context = set(context_cells)
    cells_set = set(cells)
    base_cells = cells_set | context
    shape_cells = base_cells | geometry.traversed_cells(segments)
    board = geometry.rasterize_board([], shape_cells, supersample)
    highlight_board = geometry.rasterize_board([], base_cells, supersample)
    drawn_bbox = geometry.bitmap_bbox(board, side)
    board_ink = geometry.popcount(board)

    vector_floor, raster_floor = _ensure_floors()
    heuristic = _heuristic_center(drawn_edges)
    if (changed_edges is None and len(drawn_edges) < vector_floor
            and board_ink < raster_floor and heuristic is None):
        return Verdict(CLEAN)

    anchor_edges = drawn_edges if changed_edges is None else changed_edges
    vector = _stage_vector(drawn_edges, anchor_edges, arrow_edges, arrows)
    if vector is not None:
        return Verdict(BLOCKED, pattern_id=vector[0].id, matched_arrows=vector[2],
                       matched_highlights=[])

    window = _changed_pixels(changed_edges, changed_cells, supersample) \
        if changed_edges is not None else None
    raster = _stage_raster(board, highlight_board, side, drawn_bbox, window)
    if raster is not None:
        pattern, placed = raster
        matched_a, matched_h = _map_pixels(placed, arrows, highlights, cells, supersample)
        return Verdict(BLOCKED, pattern_id=pattern.id, matched_arrows=matched_a,
                       matched_highlights=matched_h)

    if len(cells_set) > COMPLEMENT_SCAN_MIN_CELLS:
        complement = _complement_board(cells, supersample)
        comp_bbox = geometry.bitmap_bbox(complement, side)
        comp = _stage_raster(complement, complement, side, comp_bbox, None)
        if comp is not None:
            return Verdict(BLOCKED, pattern_id=comp[0].id,
                           matched_arrows=[], matched_highlights=list(highlights))

    if heuristic is not None and heuristic[2]:
        matched = [arrow for arrow, edges in arrow_edges
                   if {_double_edge(edge) for edge in edges} & heuristic[3]]
        return Verdict(BLOCKED, pattern_id=HEURISTIC_ID, matched_arrows=matched,
                       matched_highlights=[])

    if heuristic is not None:
        return Verdict(SUSPECT, pattern_id=HEURISTIC_ID)

    return Verdict(CLEAN)


def _stage_vector(drawn_edges, anchor_edges, arrow_edges, arrows):
    if not drawn_edges or not anchor_edges:
        return None
    by_delta = defaultdict(list)
    for edge in anchor_edges:
        by_delta[_delta(edge)].append(edge)
    for pattern in library.enabled_patterns():
        if pattern.channel not in (library.VECTOR, library.BOTH):
            continue
        for variant in pattern.vector_variants:
            match = _match_variant(variant, drawn_edges, by_delta,
                                   pattern.coverage_threshold)
            if match is None:
                continue
            hit, placed = match
            matched = [arrow for arrow, edges in arrow_edges if edges & hit]
            if _fan_suppressed(matched, placed, drawn_edges):
                continue
            return (pattern, hit, matched)
    return None


def _match_variant(variant, drawn_edges, anchor_by_delta, threshold):
    translations = set()
    for pedge in variant.edges:
        delta = _delta(pedge)
        for dedge in anchor_by_delta.get(delta, ()):
            translations.add((dedge[0][0] - pedge[0][0], dedge[0][1] - pedge[0][1]))
    for dx, dy in translations:
        placed = geometry.translate_edges(variant.edges, dx, dy)
        hit = placed & drawn_edges
        if len(hit) >= _needed(len(variant.edges), threshold):
            return (hit, placed)
    return None


def _delta(edge):
    a, b = edge
    return (b[0] - a[0], b[1] - a[1])


def _is_knight(arrow):
    from_sq = _square(arrow[0])
    to_sq = _square(arrow[1])
    return {abs(to_sq.row - from_sq.row), abs(to_sq.col - from_sq.col)} == {1, 2}


def _fan_suppressed(matched, placed, drawn_edges):
    if not matched or not all(_is_knight(arrow) for arrow in matched):
        return False
    return _mirror_present(placed, drawn_edges)


def _mirror_present(placed_edges, drawn_edges):
    placed_doubled = {_double_edge(edge) for edge in placed_edges}
    drawn_doubled = {_double_edge(edge) for edge in drawn_edges}
    box = geometry.edges_bbox(placed_doubled)
    if box is None:
        return False
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    for axis in ("x", "y", "d", "a"):
        reflected = _transform_edges_about(
            placed_doubled, cx, cy, lambda p, gx, gy, ax=axis: _reflect(p, gx, gy, ax))
        if reflected != placed_doubled and reflected <= drawn_doubled:
            return True
    return False


def _complement_board(cells, supersample):
    filled = set(cells)
    complement = [(cx, cy) for cx in range(BOARD_SIZE) for cy in range(BOARD_SIZE)
                  if (cx, cy) not in filled]
    return geometry.rasterize_board([], complement, supersample)


def _stage_raster(board, highlight_board, side, drawn_bbox, window):
    for pattern in library.enabled_patterns():
        if pattern.channel not in (library.RASTER, library.BOTH):
            continue
        best = _match_raster(pattern, board, highlight_board, side, drawn_bbox, window)
        if best is not None:
            return (pattern, best)
    return None


def _match_raster(pattern, board, highlight_board, side, drawn_bbox, window):
    region = window if window is not None else drawn_bbox
    if region is None:
        return None
    rminx, rminy, rmaxx, rmaxy = region
    for variant in pattern.raster_variants:
        width = variant.width
        height = variant.height
        x0 = max(0, rminx - (width - 1))
        x1 = min(side - width, rmaxx)
        y0 = max(0, rminy - (height - 1))
        y1 = min(side - height, rmaxy)
        rows = list(variant.rows)
        margin = pattern.supersample
        need_inter = _needed(variant.ink, pattern.coverage_threshold)
        need_lit = _needed(variant.ink, RASTER_HIGHLIGHT_SHARE)
        for offy in range(y0, y1 + 1):
            for offx in range(x0, x1 + 1):
                inter = 0
                for y, row in enumerate(rows):
                    inter += ((board[y + offy] >> offx) & row).bit_count()
                if inter < need_inter:
                    continue
                lit_h = 0
                for y, row in enumerate(rows):
                    lit_h += ((highlight_board[y + offy] >> offx) & row).bit_count()
                if lit_h < need_lit:
                    continue
                placed = geometry.embed(rows, offx, offy, side, side)
                lx0 = max(0, offx - margin)
                ly0 = max(0, offy - margin)
                lx1 = min(side, offx + width + margin)
                ly1 = min(side, offy + height + margin)
                nearby = geometry.local_ink(board, lx0, ly0, lx1, ly1)
                union = variant.ink + nearby - inter
                if union <= 0 or inter / union < pattern.iou_threshold:
                    continue
                return placed
    return None


def _map_pixels(placed_rows, arrows, highlights, cells, supersample):
    placed = set()
    for y, row in enumerate(placed_rows):
        bit = row
        while bit:
            low = bit & -bit
            x = low.bit_length() - 1
            placed.add((x, y))
            bit ^= low
    matched_arrows = []
    for arrow in arrows:
        segments = geometry.arrow_segments(_square(arrow[0]), _square(arrow[1]))
        pixels = geometry.lit_pixels_from_segments(segments, supersample)
        if pixels & placed:
            matched_arrows.append(arrow)
    matched_highlights = []
    for coord, cell in zip(highlights, cells):
        pixels = geometry.lit_pixels_from_cells({cell}, supersample)
        if pixels & placed:
            matched_highlights.append(coord)
    return matched_arrows, matched_highlights


def _changed_pixels(changed_edges, changed_cells, supersample):
    cells = set(changed_cells) if changed_cells else set()
    if changed_edges:
        for a, b in changed_edges:
            cells.add(a)
            cells.add(b)
    if not cells:
        return None
    return geometry.pixels_bbox(geometry.lit_pixels_from_cells(cells, supersample))


def _heuristic_center(drawn_edges):
    if len(drawn_edges) < HEURISTIC_MIN_EDGES:
        return None
    doubled = frozenset(_double_edge(edge) for edge in drawn_edges)
    box = geometry.edges_bbox(doubled)
    if box is None:
        return None
    if len(doubled) > HEURISTIC_SUBSET_MAX_EDGES:
        return _heuristic_whole_set(doubled, box)
    minx, miny, maxx, maxy = box
    for cx in range(minx, maxx + 1):
        for cy in range(miny, maxy + 1):
            core = _c4_chiral_core(doubled, cx, cy)
            if core is not None:
                return (cx, cy, _core_tight(core), core)
    return None


def _heuristic_whole_set(doubled, box):
    minx, miny, maxx, maxy = box
    if (maxx - minx) // 2 > HEURISTIC_MAX_SPAN or (maxy - miny) // 2 > HEURISTIC_MAX_SPAN:
        return None
    for cx in range(minx, maxx + 1):
        for cy in range(miny, maxy + 1):
            if _is_c4_chiral(doubled, cx, cy):
                return (cx, cy, False, doubled)
    return None


def _c4_chiral_core(doubled, cx, cy):
    half = {edge for edge in doubled
            if _transform_edge(edge, cx, cy, _rotate180) in doubled}
    if len(half) < HEURISTIC_MIN_EDGES:
        return None
    core = frozenset(edge for edge in half
                     if _transform_edge(edge, cx, cy, _rotate90) in doubled
                     and _transform_edge(edge, cx, cy, _rotate270) in doubled)
    if len(core) < HEURISTIC_MIN_EDGES:
        return None
    cminx, cminy, cmaxx, cmaxy = geometry.edges_bbox(core)
    if (cmaxx - cminx) // 2 > HEURISTIC_MAX_SPAN or (cmaxy - cminy) // 2 > HEURISTIC_MAX_SPAN:
        return None
    for axis in ("x", "y", "d", "a"):
        reflected = _transform_edges_about(
            core, cx, cy, lambda p, gx, gy, ax=axis: _reflect(p, gx, gy, ax))
        if reflected == core:
            return None
        if reflected <= doubled:
            return None
    return core


def _core_tight(core):
    if len(core) < HEURISTIC_TIGHT_MIN_EDGES:
        return False
    minx, miny, maxx, maxy = geometry.edges_bbox(core)
    if (maxx - minx) // 2 > HEURISTIC_TIGHT_MAX_SPAN:
        return False
    if (maxy - miny) // 2 > HEURISTIC_TIGHT_MAX_SPAN:
        return False
    return _bent_tip_count(core) >= HEURISTIC_TIGHT_MIN_TIPS


def _bent_tip_count(core):
    adjacency = defaultdict(list)
    for a, b in core:
        adjacency[a].append(b)
        adjacency[b].append(a)
    bent = 0
    for vertex, neighbors in adjacency.items():
        if len(neighbors) != 1:
            continue
        corner = neighbors[0]
        tip_dir = (geometry.sign(corner[0] - vertex[0]),
                   geometry.sign(corner[1] - vertex[1]))
        for onward in adjacency[corner]:
            if onward == vertex:
                continue
            arm_dir = (geometry.sign(onward[0] - corner[0]),
                       geometry.sign(onward[1] - corner[1]))
            if arm_dir != (0, 0) and arm_dir != tip_dir:
                bent += 1
                break
    return bent


def _transform_edge(edge, cx, cy, fn):
    a, b = edge
    return geometry.canonical_edge(fn(a, cx, cy), fn(b, cx, cy))


def _double_edge(edge):
    a, b = edge
    return geometry.canonical_edge((a[0] * 2, a[1] * 2), (b[0] * 2, b[1] * 2))


def _rotate90(point, cx, cy):
    x, y = point
    return (cx - (y - cy), cy + (x - cx))


def _rotate180(point, cx, cy):
    x, y = point
    return (2 * cx - x, 2 * cy - y)


def _rotate270(point, cx, cy):
    x, y = point
    return (cx + (y - cy), cy - (x - cx))


def _reflect(point, cx, cy, axis):
    x, y = point
    if axis == "x":
        return (2 * cx - x, y)
    if axis == "y":
        return (x, 2 * cy - y)
    if axis == "d":
        return (cx + (y - cy), cy + (x - cx))
    return (cx - (y - cy), cy - (x - cx))


def _transform_edges_about(edges, cx, cy, fn):
    out = set()
    for a, b in edges:
        na = fn(a, cx, cy)
        nb = fn(b, cx, cy)
        out.add(geometry.canonical_edge(na, nb))
    return out


def _is_c4_chiral(doubled, cx, cy):
    rotated = _transform_edges_about(doubled, cx, cy, _rotate90)
    if rotated != doubled:
        return False
    for axis in ("x", "y", "d", "a"):
        reflected = _transform_edges_about(
            doubled, cx, cy, lambda p, gx, gy, ax=axis: _reflect(p, gx, gy, ax))
        if reflected == doubled:
            return False
    return True
