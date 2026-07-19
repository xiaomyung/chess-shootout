import json
from collections import defaultdict
from dataclasses import dataclass, field
from importlib import resources

from chessshootout.backend.utils import BOARD_SIZE, Square, square_from_coord

from chessshootout.server.moderation import geometry, library


HEURISTIC_MIN_EDGES = 8
HEURISTIC_MAX_SPAN = 6
HEURISTIC_SUBSET_MAX_EDGES = 80
HEURISTIC_TIGHT_MIN_EDGES = 12
HEURISTIC_TIGHT_MAX_SPAN = 4
HEURISTIC_TIGHT_MIN_TIPS = 4
RASTER_HIGHLIGHT_SHARE = 0.3
GLYPH_NORM_HEIGHT = 14
GLYPH_STRETCH = ((1, 1), (2, 1), (3, 1), (4, 1), (2, 2), (4, 4), (6, 6))
LETTER_IOU = 0.7
LONE_COVERAGE = 0.94
DIGIT_IOU = 0.75
MIN_WORD_GLYPHS = 3
MIN_GENERIC_LETTERS = 2
LINE_LETTERS = frozenset({"I", "L", "J"})
LONE_LETTERS = frozenset("ABEFGHKMNPRSWZ") | {"И", "Й", "Ж"}
LONE_MIN_SPAN = 10
LONE_INK_RATIO = 1.6
LETTER_INK_FLOOR = 24
CODE_INK_FLOOR = 16
MIN_CODE_DIGITS = 2
DIGIT_GAP_FACTOR = 1.6
DIGIT_VOVERLAP = 0.6
DIGIT_ALPHABET = "0123456789"
OCR_READING_OPS = geometry.D4_ALL
CACHE_LIMIT = 512

HOMOGLYPHS = {
    "Х": "X", "У": "Y", "Й": "N", "А": "A", "В": "B", "С": "C",
    "Е": "E", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
    "0": "O", "1": "I", "3": "E", "4": "A", "5": "S", "7": "T", "8": "B",
}

CLEAN = "clean"
SUSPECT = "suspect"
BLOCKED = "blocked"

CODE_COOCCURRENCE_ID = "code_cooccurrence"
HEURISTIC_ID = "heuristic_c4"
GENERIC_LETTER_ID = "letters"

_FLOORS = None
_WORD_FOLDED = None
_LETTER_TEMPLATES = None
_DIGIT_TEMPLATES = None
_CODE_TABLE = None
_CACHE = {}
_CACHE_ORDER = []


@dataclass
class Verdict:
    kind: str
    pattern_id: object = None
    matched_arrows: list = field(default_factory=list)
    matched_highlights: list = field(default_factory=list)
    codes_seen_out: frozenset = frozenset()
    suspect_ids: tuple = ()


def union_sides(arrows_a, highlights_a, arrows_b, highlights_b):
    arrows = list(arrows_a)
    seen = {_arrow_key(a) for a in arrows}
    for arrow in arrows_b:
        key = _arrow_key(arrow)
        if key not in seen:
            seen.add(key)
            arrows.append(arrow)
    highlights = list(dict.fromkeys(list(highlights_a) + list(highlights_b)))
    return arrows, highlights


def _arrow_key(arrow):
    return (arrow[0], arrow[1])


def _square(coord):
    return square_from_coord(coord)


def _cell(coord):
    sq = square_from_coord(coord)
    return (sq.col, sq.row)


def _ensure_floors():
    global _FLOORS
    if _FLOORS is not None:
        return _FLOORS
    vector_floor = None
    raster_floor = None
    for pattern in library.enabled_patterns():
        for variant in pattern.vector_variants:
            need = _needed(len(variant.edges), pattern.coverage_threshold)
            if vector_floor is None or need < vector_floor:
                vector_floor = need
        for variant in pattern.raster_variants:
            need = _needed(variant.ink, pattern.coverage_threshold)
            if raster_floor is None or need < raster_floor:
                raster_floor = need
    _FLOORS = (
        vector_floor if vector_floor is not None else 1,
        raster_floor if raster_floor is not None else 1,
        LETTER_INK_FLOOR,
        CODE_INK_FLOOR,
        LETTER_INK_FLOOR,
    )
    return _FLOORS


def _needed(size, threshold):
    need = int(size * threshold)
    if need < size * threshold:
        need += 1
    return max(need, 1)


def _build_templates():
    global _LETTER_TEMPLATES, _DIGIT_TEMPLATES
    if _LETTER_TEMPLATES is not None:
        return
    resource = resources.files("chessshootout.server.moderation").joinpath("words.json")
    with resource.open(encoding="utf-8") as source:
        data = json.load(source)
    letters = []
    digits = []
    chars = set(data["letters"]) | set(data["letter_segments"]) | set(data["digit_segments"])
    for char in sorted(chars):
        index = digits if char in DIGIT_ALPHABET else letters
        seen = set()
        for pixels in _glyph_pixel_sets(data, char):
            box = geometry.pixels_bbox(pixels)
            if box is None:
                continue
            minx, miny, maxx, maxy = box
            width = maxx - minx + 1
            height = maxy - miny + 1
            relpix = frozenset((px - minx, py - miny) for px, py in pixels)
            key = _norm_grid(relpix, width, height, _norm_width(width, height))
            if key in seen:
                continue
            seen.add(key)
            index.append((char, _norm_width(width, height), relpix, width, height, {}))
    _LETTER_TEMPLATES = tuple(letters)
    _DIGIT_TEMPLATES = tuple(digits)


def _glyph_pixel_sets(data, char):
    sets = []
    rows = data["letters"].get(char)
    if rows:
        cells = {(cx, cy) for cy, row in enumerate(rows)
                 for cx, ch in enumerate(row) if ch == "#"}
        if cells:
            sets.append(cells)
    for table in ("letter_segments", "digit_segments"):
        for construction in data[table].get(char, ()):
            for xf, yf in GLYPH_STRETCH:
                strokes = []
                for a, b in construction:
                    strokes.extend(geometry.arrow_segments(
                        Square(row=a[1] * yf, col=a[0] * xf),
                        Square(row=b[1] * yf, col=b[0] * xf)))
                pixels = geometry.lit_pixels_from_segments(
                    strokes, geometry.DEFAULT_SUPERSAMPLE)
                if pixels:
                    sets.append(pixels)
    return sets


def _letter_templates():
    _build_templates()
    return _LETTER_TEMPLATES


def _digit_templates():
    _build_templates()
    return _DIGIT_TEMPLATES


def _norm_width(width, height):
    return max(1, min(2 * GLYPH_NORM_HEIGHT, round(GLYPH_NORM_HEIGHT * width / height)))


def _norm_grid(relpix, width, height, nw):
    return frozenset(
        (min(nw - 1, px * nw // width),
         min(GLYPH_NORM_HEIGHT - 1, py * GLYPH_NORM_HEIGHT // height))
        for px, py in relpix)


def _glyph_descriptor(pixels):
    box = geometry.pixels_bbox(pixels)
    if box is None:
        return None
    minx, miny, maxx, maxy = box
    width = maxx - minx + 1
    height = maxy - miny + 1
    relpix = frozenset((px - minx, py - miny) for px, py in pixels)
    nw = _norm_width(width, height)
    return (nw, _norm_grid(relpix, width, height, nw))


def _jitter_grids(grid):
    return [frozenset((x + dx, y + dy) for x, y in grid)
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def _jitter_iou(shifted, glen, template):
    best = 0.0
    tlen = len(template)
    for grid in shifted:
        inter = len(grid & template)
        if not inter:
            continue
        score = inter / (glen + tlen - inter)
        if score > best:
            best = score
    return best


def _match_descriptor(desc, templates, threshold):
    nw, grid = desc
    glen = len(grid)
    shifted = _jitter_grids(grid)
    best_char = None
    best_score = threshold
    for char, t_nw, relpix, width, height, cache in templates:
        if abs(t_nw - nw) > 1 + nw // 5:
            continue
        template = cache.get(nw)
        if template is None:
            template = _norm_grid(relpix, width, height, nw)
            cache[nw] = template
        tlen = len(template)
        if min(glen, tlen) <= best_score * max(glen, tlen):
            continue
        score = _jitter_iou(shifted, glen, template)
        if score > best_score:
            best_score = score
            best_char = char
    return best_char


def _code_table():
    global _CODE_TABLE
    if _CODE_TABLE is not None:
        return _CODE_TABLE
    hard = {}
    soft = {}
    for pattern in library.enabled_patterns():
        if not (_is_code(pattern) and pattern.digits):
            continue
        if pattern.action == library.HARD_BLOCK:
            hard.setdefault(pattern.digits, pattern.id)
        elif pattern.action == library.SOFT_FLAG:
            soft.setdefault(pattern.digits, pattern.id)
    _CODE_TABLE = (hard, soft)
    return _CODE_TABLE


def _folded_words():
    global _WORD_FOLDED
    if _WORD_FOLDED is not None:
        return _WORD_FOLDED
    folded = []
    for entry in library.word_list():
        if entry.action == library.DISABLED:
            continue
        folded.append((_fold(entry.text), entry.text))
    _WORD_FOLDED = tuple(folded)
    return _WORD_FOLDED


def _fold(text):
    return "".join(HOMOGLYPHS.get(ch, ch) for ch in text.upper())


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


def detect(arrows, highlights, codes_seen=None, changed=None, context=()):
    library.preload()
    codes_in = frozenset(codes_seen) if codes_seen else frozenset()
    arrows, highlights, arrow_edges, drawn_edges, cells = _normalize_inputs(arrows, highlights)
    context_cells = [_cell(coord) for coord in context]
    changed_edges, changed_cells = _changed_edges_cells(changed)
    key = (tuple(arrows), tuple(highlights), frozenset(context_cells), codes_in,
           _changed_key(changed_edges, changed_cells))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    verdict = _run(arrows, highlights, arrow_edges, drawn_edges, cells, context_cells,
                   codes_in, changed_edges, changed_cells)
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
         codes_in, changed_edges, changed_cells):
    if not arrows and not cells:
        return Verdict(CLEAN, codes_seen_out=codes_in)

    supersample = geometry.DEFAULT_SUPERSAMPLE
    side = geometry.board_width(supersample)
    segments = []
    for arrow in arrows:
        segments.extend(geometry.arrow_segments(_square(arrow[0]), _square(arrow[1])))
    board_thin = geometry.rasterize_board(segments, cells, supersample)
    context = set(context_cells)
    shape_cells = set(cells) | context | geometry.traversed_cells(segments)
    board = geometry.rasterize_board([], shape_cells, supersample)
    highlight_board = geometry.rasterize_board([], set(cells) | context, supersample)
    drawn_bbox = geometry.bitmap_bbox(board, side)
    board_ink = geometry.popcount(board)
    thin_ink = geometry.popcount(board_thin)

    vector_floor, raster_floor, word_floor, code_floor, letter_floor = _ensure_floors()
    heuristic = _heuristic_center(drawn_edges)
    if (changed_edges is None and len(drawn_edges) < vector_floor
            and board_ink < raster_floor and thin_ink < word_floor
            and thin_ink < code_floor and thin_ink < letter_floor
            and heuristic is None):
        return Verdict(CLEAN, codes_seen_out=codes_in)

    anchor_edges = drawn_edges if changed_edges is None else changed_edges
    vector = _stage_vector(drawn_edges, anchor_edges, arrow_edges, arrows)
    if vector is not None and vector[0].action == library.HARD_BLOCK:
        return Verdict(BLOCKED, pattern_id=vector[0].id, matched_arrows=vector[2],
                       matched_highlights=[], codes_seen_out=codes_in)

    window = _changed_pixels(changed_edges, changed_cells, supersample) \
        if changed_edges is not None else None
    raster = _stage_raster(board, highlight_board, side, drawn_bbox, window)
    hard_raster = [m for m in raster if m[0].action == library.HARD_BLOCK]
    if hard_raster:
        pattern, placed = hard_raster[0]
        matched_a, matched_h = _map_pixels(placed, arrows, highlights, cells, supersample)
        return Verdict(BLOCKED, pattern_id=pattern.id, matched_arrows=matched_a,
                       matched_highlights=matched_h, codes_seen_out=codes_in)

    if len(set(cells)) > (BOARD_SIZE * BOARD_SIZE) // 2:
        complement = _complement_board(cells, supersample)
        comp_bbox = geometry.bitmap_bbox(complement, side)
        comp = _stage_raster(complement, complement, side, comp_bbox, None)
        comp_hard = [m for m in comp if m[0].action == library.HARD_BLOCK]
        if comp_hard:
            return Verdict(BLOCKED, pattern_id=comp_hard[0][0].id,
                           matched_arrows=[], matched_highlights=list(highlights),
                           codes_seen_out=codes_in)

    letters = _stage_letters(board_thin)
    if letters is not None and letters[0] == "word":
        return Verdict(BLOCKED, pattern_id="word:" + letters[1],
                       matched_arrows=list(arrows), matched_highlights=list(highlights),
                       codes_seen_out=codes_in)

    code = _stage_codes(board_thin)
    if code is not None and code[0] == "hard":
        return Verdict(BLOCKED, pattern_id=code[1],
                       matched_arrows=list(arrows), matched_highlights=list(highlights),
                       codes_seen_out=codes_in)

    soft_ids = set()
    soft_marks = None
    for pattern, placed_pixels in raster:
        if pattern.action == library.SOFT_FLAG and _is_code(pattern):
            soft_ids.add(pattern.id)
            if soft_marks is None:
                soft_marks = _map_pixels(placed_pixels, arrows, highlights,
                                         cells, supersample)
    if vector is not None and vector[0].action == library.SOFT_FLAG:
        soft_ids.add(vector[0].id)
        if soft_marks is None:
            soft_marks = (vector[2], [])
    if code is not None and code[0] == "soft":
        soft_ids |= set(code[1])
        if soft_marks is None:
            soft_marks = (list(arrows), list(highlights))

    if letters is not None and not soft_ids:
        return Verdict(BLOCKED, pattern_id=GENERIC_LETTER_ID,
                       matched_arrows=list(arrows), matched_highlights=list(highlights),
                       codes_seen_out=codes_in)

    codes_out = codes_in | frozenset(pid for pid in soft_ids if pid in _code_ids())
    boosters = codes_out & _code_ids()
    if len(boosters) >= 2:
        marks = soft_marks if soft_marks is not None else (list(arrows), list(highlights))
        return Verdict(BLOCKED, pattern_id=CODE_COOCCURRENCE_ID,
                       matched_arrows=marks[0], matched_highlights=marks[1],
                       codes_seen_out=codes_out, suspect_ids=tuple(sorted(boosters)))

    if heuristic is not None and heuristic[2]:
        matched = [arrow for arrow, edges in arrow_edges
                   if {_double_edge(edge) for edge in edges} & heuristic[3]]
        return Verdict(BLOCKED, pattern_id=HEURISTIC_ID, matched_arrows=matched,
                       matched_highlights=[], codes_seen_out=codes_out)

    if soft_ids or heuristic is not None:
        ids = tuple(sorted(soft_ids)) + ((HEURISTIC_ID,) if heuristic is not None else ())
        marks = soft_marks if soft_marks is not None else ([], [])
        return Verdict(SUSPECT, pattern_id=ids[0] if ids else None,
                       matched_arrows=marks[0], matched_highlights=marks[1],
                       codes_seen_out=codes_out, suspect_ids=ids)

    return Verdict(CLEAN, codes_seen_out=codes_out)


def _is_code(pattern):
    return pattern.transform_group == "digit" and pattern.id.startswith("code_")


def _code_ids():
    return frozenset(pattern.id for pattern in library.compiled_patterns()
                     if pattern.action == library.SOFT_FLAG and _is_code(pattern))


def _stage_vector(drawn_edges, anchor_edges, arrow_edges, arrows):
    if not drawn_edges or not anchor_edges:
        return None
    by_delta = defaultdict(list)
    for edge in anchor_edges:
        by_delta[_delta(edge)].append(edge)
    ordered = sorted(library.enabled_patterns(),
                     key=lambda pattern: pattern.action != library.HARD_BLOCK)
    for pattern in ordered:
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
    matches = []
    for pattern in library.enabled_patterns():
        if pattern.channel not in (library.RASTER, library.BOTH):
            continue
        best = _match_raster(pattern, board, highlight_board, side, drawn_bbox, window)
        if best is not None:
            matches.append((pattern, best))
    return matches


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


def _row_slots(pixels):
    box = geometry.pixels_bbox(pixels)
    if box is None:
        return None
    minx, miny, maxx, maxy = box
    width = maxx - minx + 1
    height = maxy - miny + 1
    rows = geometry.bitmap_from_pixels(pixels, width, height, minx, miny)
    colmask = 0
    for row in rows:
        colmask |= row
    return rows, width, _column_runs(colmask, width)


def _column_runs(colmask, width):
    runs = []
    x = 0
    while x < width:
        if (colmask >> x) & 1:
            start = x
            while x < width and (colmask >> x) & 1:
                x += 1
            runs.append((start, x - 1))
        else:
            x += 1
    return runs


def _slot_descriptor(rows, x0, x1):
    pixels = {(x, y) for y, row in enumerate(rows)
              for x in range(x0, x1 + 1) if (row >> x) & 1}
    return _glyph_descriptor(pixels)


def _recognize_slot(rows, x0, x1, templates, threshold):
    desc = _slot_descriptor(rows, x0, x1)
    if desc is None:
        return None
    return _match_descriptor(desc, templates, threshold)


def _scan_line(pixels):
    seg = _row_slots(pixels)
    if seg is None:
        return None
    rows, _, slots = seg
    if len(slots) < MIN_WORD_GLYPHS:
        return None
    letters = [_recognize_slot(rows, x0, x1, _letter_templates(), LETTER_IOU)
               for x0, x1 in slots]
    return _assemble(letters)


def _stage_letters(board):
    _, _, _, _, letter_floor = _ensure_floors()
    if geometry.popcount(board) < letter_floor:
        return None
    lit = _bitmap_pixels(board)
    templates = _letter_templates()
    generic = False
    for op_key in OCR_READING_OPS:
        seg = _row_slots({geometry.apply_op(pixel, op_key) for pixel in lit})
        if seg is None:
            continue
        rows, _, slots = seg
        recognized = [(_recognize_slot(rows, x0, x1, templates, LETTER_IOU),
                       x0, x1, _run_vextent(rows, x0, x1)) for x0, x1 in slots]
        word = _assemble([glyph[0] for glyph in recognized])
        if word is not None:
            return ("word", word)
        if not generic and _generic_hit(recognized, rows, templates):
            generic = True
    return ("generic", None) if generic else None


def _generic_hit(recognized, rows, templates):
    for group in _aligned_groups(recognized, MIN_GENERIC_LETTERS):
        effective = [glyph for glyph in group if glyph[0] not in LINE_LETTERS]
        if len(effective) >= MIN_GENERIC_LETTERS:
            return True
    if len(recognized) != 1:
        return False
    _, x0, x1, _ = recognized[0]
    pixels = {(x, y) for y, row in enumerate(rows)
              for x in range(x0, x1 + 1) if (row >> x) & 1}
    glyph = _largest_component(pixels)
    minx, miny, maxx, maxy = geometry.pixels_bbox(glyph)
    if min(maxx - minx + 1, maxy - miny + 1) < LONE_MIN_SPAN:
        return False
    desc = _glyph_descriptor(glyph)
    if desc is None:
        return False
    return _lone_match(desc, templates) in LONE_LETTERS


def _largest_component(pixels):
    remaining = set(pixels)
    best = set()
    while remaining:
        start = remaining.pop()
        stack = [start]
        component = {start}
        while stack:
            px, py = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (px + dx, py + dy)
                    if neighbor in remaining:
                        remaining.discard(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        if len(component) > len(best):
            best = component
    return best


def _dilate(pixels):
    return {(x + dx, y + dy) for x, y in pixels
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def _lone_match(desc, templates):
    nw, grid = desc
    dgrid = _dilate(grid)
    best_char = None
    best_score = LONE_COVERAGE
    for char, t_nw, relpix, width, height, cache in templates:
        if abs(t_nw - nw) > 1 + nw // 5:
            continue
        template = cache.get(nw)
        if template is None:
            template = _norm_grid(relpix, width, height, nw)
            cache[nw] = template
        if max(len(grid), len(template)) > LONE_INK_RATIO * min(len(grid), len(template)):
            continue
        dtemplate = _dilate(template)
        drawn_cover = sum(1 for p in grid if p in dtemplate) / len(grid)
        template_cover = sum(1 for p in template if p in dgrid) / len(template)
        score = min(drawn_cover, template_cover)
        if score > best_score:
            best_score = score
            best_char = char
    return best_char


def _bitmap_pixels(rows):
    pixels = set()
    for y, row in enumerate(rows):
        bit = row
        while bit:
            low = bit & -bit
            pixels.add((low.bit_length() - 1, y))
            bit ^= low
    return pixels


def _assemble(letters):
    for start in range(len(letters)):
        if letters[start] is None:
            continue
        run = []
        for char in letters[start:]:
            if char is None:
                break
            run.append(char)
        if len(run) < MIN_WORD_GLYPHS:
            continue
        text = _fold("".join(run))
        word = _matches_word(text)
        if word is not None:
            return word
    return None


def _matches_word(text):
    for folded, original in _folded_words():
        if len(folded) >= MIN_WORD_GLYPHS and folded in text:
            return original
    return None


def _stage_codes(board):
    _, _, _, code_floor, _ = _ensure_floors()
    if geometry.popcount(board) < code_floor:
        return None
    hard_codes, soft_codes = _code_table()
    if not hard_codes and not soft_codes:
        return None
    lit = set()
    for y, row in enumerate(board):
        bit = row
        while bit:
            low = bit & -bit
            lit.add((low.bit_length() - 1, y))
            bit ^= low
    soft_hit = frozenset()
    for op_key in OCR_READING_OPS:
        transformed = [geometry.apply_op((x, y), op_key) for x, y in lit]
        found = _scan_code_line(transformed, hard_codes, soft_codes)
        if found is None:
            continue
        if found[0] == "hard":
            return found
        soft_hit |= found[1]
    if soft_hit:
        return ("soft", soft_hit)
    return None


def _scan_code_line(pixels, hard_codes, soft_codes):
    seg = _row_slots(pixels)
    if seg is None:
        return None
    rows, _, slots = seg
    if len(slots) < MIN_CODE_DIGITS:
        return None
    templates = _digit_templates()
    glyphs = []
    for x0, x1 in slots:
        digit = _recognize_slot(rows, x0, x1, templates, DIGIT_IOU)
        glyphs.append((digit, x0, x1, _run_vextent(rows, x0, x1)))
    hard = None
    soft = set()
    for group in _aligned_groups(glyphs, MIN_CODE_DIGITS):
        text = "".join(glyph[0] for glyph in group)
        for start in range(len(text)):
            for end in range(start + MIN_CODE_DIGITS, len(text) + 1):
                sub = text[start:end]
                if sub in hard_codes:
                    hard = hard_codes[sub]
                elif sub in soft_codes:
                    soft.add(soft_codes[sub])
    if hard is not None:
        return ("hard", hard)
    if soft:
        return ("soft", frozenset(soft))
    return None


def _run_vextent(rows, x0, x1):
    mask = ((1 << (x1 - x0 + 1)) - 1) << x0
    ys = [y for y, row in enumerate(rows) if row & mask]
    if not ys:
        return None
    return (min(ys), max(ys))


def _aligned_groups(glyphs, min_size):
    groups = []
    current = []
    for glyph in glyphs:
        char, _, _, extent = glyph
        if char is None or extent is None:
            if len(current) >= min_size:
                groups.append(current)
            current = []
            continue
        if current and not _glyphs_aligned(current[-1], glyph):
            if len(current) >= min_size:
                groups.append(current)
            current = []
        current.append(glyph)
    if len(current) >= min_size:
        groups.append(current)
    return groups


def _glyphs_aligned(prev, cur):
    _, _, prev_x1, prev_extent = prev
    _, cur_x0, _, cur_extent = cur
    prev_h = prev_extent[1] - prev_extent[0] + 1
    cur_h = cur_extent[1] - cur_extent[0] + 1
    if abs(prev_h - cur_h) > 2:
        return False
    overlap = min(prev_extent[1], cur_extent[1]) - max(prev_extent[0], cur_extent[0]) + 1
    if overlap < DIGIT_VOVERLAP * min(prev_h, cur_h):
        return False
    gap = cur_x0 - prev_x1 - 1
    return gap <= DIGIT_GAP_FACTOR * max(prev_h, cur_h)


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
        tip_dir = (geometry._sign(corner[0] - vertex[0]),
                   geometry._sign(corner[1] - vertex[1]))
        for onward in adjacency[corner]:
            if onward == vertex:
                continue
            arm_dir = (geometry._sign(onward[0] - corner[0]),
                       geometry._sign(onward[1] - corner[1]))
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
