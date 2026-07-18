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
GLYPH_SCALES = (1, 2)
GLYPH_COVERAGE = 0.72
GLYPH_IOU = 0.6
MIN_WORD_GLYPHS = 3
MIN_GENERIC_LETTERS = 2
GENERIC_LETTER_COVERAGE = 0.72
LINE_LETTERS = frozenset({"I", "L", "J"})
DIGIT_COVERAGE = 0.85
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
_GLYPHS = None
_WORD_FOLDED = None
_GLYPH_WIDTH_INDEX = None
_DIGIT_WIDTH_INDEX = None
_LETTER_WIDTH_INDEX = None
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
    glyph_floor = None
    digit_floor = None
    for char, variants in _glyph_atlas().items():
        for variant in variants:
            need = _needed(variant[3], GLYPH_COVERAGE)
            if glyph_floor is None or need < glyph_floor:
                glyph_floor = need
            if char in DIGIT_ALPHABET:
                dneed = _needed(variant[3], DIGIT_COVERAGE)
                if digit_floor is None or dneed < digit_floor:
                    digit_floor = dneed
    unit_glyph = glyph_floor if glyph_floor is not None else 1
    _FLOORS = (
        vector_floor if vector_floor is not None else 1,
        raster_floor if raster_floor is not None else 1,
        unit_glyph * MIN_WORD_GLYPHS,
        (digit_floor if digit_floor is not None else 1) * MIN_CODE_DIGITS,
        unit_glyph * MIN_GENERIC_LETTERS,
    )
    return _FLOORS


def _needed(size, threshold):
    need = int(size * threshold)
    if need < size * threshold:
        need += 1
    return max(need, 1)


def _glyph_atlas():
    global _GLYPHS
    if _GLYPHS is not None:
        return _GLYPHS
    resource = resources.files("chessshootout.server.moderation").joinpath("words.json")
    with resource.open(encoding="utf-8") as source:
        data = json.load(source)
    atlas = {}
    for char, rows in data["letters"].items():
        cells = set()
        for cy, row in enumerate(rows):
            for cx, ch in enumerate(row):
                if ch == "#":
                    cells.add((cx, cy))
        variants = []
        seen = set()
        for factor in GLYPH_SCALES:
            scaled = set()
            for cx, cy in cells:
                for i in range(factor):
                    for j in range(factor):
                        scaled.add((cx * factor + i, cy * factor + j))
            _add_glyph_variant(variants, seen, scaled)
        atlas[char] = variants
    _add_segment_glyphs(atlas, data["letter_segments"], GLYPH_SCALES)
    _add_segment_glyphs(atlas, data["digit_segments"], GLYPH_SCALES)
    _GLYPHS = {char: tuple(variants) for char, variants in atlas.items()}
    return _GLYPHS


def _add_segment_glyphs(atlas, table, scales):
    for char, constructions in table.items():
        variants = atlas.setdefault(char, [])
        seen = {variant[0] for variant in variants}
        for segments in constructions:
            for factor in scales:
                strokes = []
                for a, b in segments:
                    strokes.extend(geometry.arrow_segments(
                        Square(row=a[1] * factor, col=a[0] * factor),
                        Square(row=b[1] * factor, col=b[0] * factor)))
                pixels = geometry.lit_pixels_from_segments(
                    strokes, geometry.DEFAULT_SUPERSAMPLE)
                _add_glyph_variant(variants, seen, pixels)


def _add_glyph_variant(variants, seen, pixels):
    grid_rows, width, height = geometry.normalized_bitmap_from_pixels(pixels)
    key = tuple(grid_rows)
    if not grid_rows or key in seen:
        return
    seen.add(key)
    variants.append((key, width, height, geometry.popcount(grid_rows)))


def _glyphs_by_width():
    global _GLYPH_WIDTH_INDEX
    if _GLYPH_WIDTH_INDEX is not None:
        return _GLYPH_WIDTH_INDEX
    index = defaultdict(list)
    for char, variants in _glyph_atlas().items():
        for grows, gw, gh, gink in variants:
            index[gw].append((char, grows, gw, gh, gink))
    _GLYPH_WIDTH_INDEX = index
    return _GLYPH_WIDTH_INDEX


def _digit_glyphs_by_width():
    global _DIGIT_WIDTH_INDEX
    if _DIGIT_WIDTH_INDEX is not None:
        return _DIGIT_WIDTH_INDEX
    index = defaultdict(list)
    for char, variants in _glyph_atlas().items():
        if char not in DIGIT_ALPHABET:
            continue
        for grows, gw, gh, gink in variants:
            index[gw].append((char, grows, gw, gh, gink))
    _DIGIT_WIDTH_INDEX = index
    return _DIGIT_WIDTH_INDEX


def _letter_glyphs_by_width():
    global _LETTER_WIDTH_INDEX
    if _LETTER_WIDTH_INDEX is not None:
        return _LETTER_WIDTH_INDEX
    index = defaultdict(list)
    for char, variants in _glyph_atlas().items():
        if char in DIGIT_ALPHABET or char in LINE_LETTERS:
            continue
        for grows, gw, gh, gink in variants:
            index[gw].append((char, grows, gw, gh, gink))
    _LETTER_WIDTH_INDEX = index
    return _LETTER_WIDTH_INDEX


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

    word = _stage_words(board_thin)
    if word is not None:
        return Verdict(BLOCKED, pattern_id="word:" + word,
                       matched_arrows=list(arrows), matched_highlights=list(highlights),
                       codes_seen_out=codes_in)

    if _stage_generic_letters(board_thin, letter_floor):
        return Verdict(BLOCKED, pattern_id=GENERIC_LETTER_ID,
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
        for offy in range(y0, y1 + 1):
            for offx in range(x0, x1 + 1):
                placed = geometry.embed(rows, offx, offy, side, side)
                inter = geometry.popcount(geometry.bitmap_and(placed, board))
                if inter < _needed(variant.ink, pattern.coverage_threshold):
                    continue
                lit_h = geometry.popcount(geometry.bitmap_and(placed, highlight_board))
                if lit_h < _needed(variant.ink, RASTER_HIGHLIGHT_SHARE):
                    continue
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


def _stage_words(board):
    _, _, word_floor, _, _ = _ensure_floors()
    if geometry.popcount(board) < word_floor:
        return None
    lit = set()
    for y, row in enumerate(board):
        bit = row
        while bit:
            low = bit & -bit
            x = low.bit_length() - 1
            lit.add((x, y))
            bit ^= low
    for op_key in OCR_READING_OPS:
        transformed = [geometry.apply_op((x, y), op_key) for x, y in lit]
        found = _scan_line(transformed)
        if found is not None:
            return found
    return None


def _scan_line(pixels):
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
    slots = _column_runs(colmask, width)
    if len(slots) < MIN_WORD_GLYPHS:
        return None
    letters = []
    for x0, x1 in slots:
        char = _best_letter(rows, x0, x1)
        letters.append(char)
    return _assemble(letters)


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


def _best_letter(rows, x0, x1):
    return _best_glyph(rows, x0, x1, _glyphs_by_width(), GLYPH_COVERAGE)


def _best_digit(rows, x0, x1):
    return _best_glyph(rows, x0, x1, _digit_glyphs_by_width(), DIGIT_COVERAGE)


def _best_glyph(rows, x0, x1, index, coverage):
    rw = x1 - x0 + 1
    mask = (1 << rw) - 1
    subcols = [(row >> x0) & mask for row in rows]
    srows, sw, sh = geometry.normalized_bitmap_from_pixels(_bitmap_pixels(subcols))
    if not srows:
        return None
    return _match_normalized(srows, sw, sh, index, coverage)


def _match_normalized(srows, sw, sh, index, coverage):
    sink = geometry.popcount(srows)
    best = None
    best_score = GLYPH_IOU
    for gwidth in range(sw - 2, sw + 3):
        for char, grows, gw, gh, gink in index.get(gwidth, ()):
            if abs(gh - sh) > 2:
                continue
            inter = _best_overlap(list(grows), gw, gh, srows, sw, sh)
            cov = inter / gink
            rev = inter / sink
            score = inter / (gink + sink - inter) if (gink + sink - inter) else 0.0
            if cov >= coverage and rev >= coverage and score > best_score:
                best_score = score
                best = char
    return best


def _stage_generic_letters(board, letter_floor):
    if geometry.popcount(board) < letter_floor:
        return False
    lit = _bitmap_pixels(board)
    index = _letter_glyphs_by_width()
    for op_key in OCR_READING_OPS:
        transformed = {geometry.apply_op(pixel, op_key) for pixel in lit}
        if _count_structured_letters(transformed, index) >= MIN_GENERIC_LETTERS:
            return True
    return False


def _count_structured_letters(pixels, index):
    count = 0
    for component in _connected_components(pixels):
        srows, sw, sh = geometry.normalized_bitmap_from_pixels(component)
        if not srows:
            continue
        if _match_normalized(srows, sw, sh, index, GENERIC_LETTER_COVERAGE) is not None:
            count += 1
    return count


def _connected_components(pixels):
    remaining = set(pixels)
    components = []
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
        components.append(component)
    return components


def _bitmap_pixels(rows):
    pixels = set()
    for y, row in enumerate(rows):
        bit = row
        while bit:
            low = bit & -bit
            pixels.add((low.bit_length() - 1, y))
            bit ^= low
    return pixels


def _best_overlap(grows, gw, gh, srows, sw, sh):
    best = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            placed = geometry.embed(grows, dx, dy, sw, sh)
            inter = geometry.popcount(geometry.bitmap_and(placed, srows))
            if inter > best:
                best = inter
    return best


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
    slots = _column_runs(colmask, width)
    if len(slots) < MIN_CODE_DIGITS:
        return None
    glyphs = []
    for x0, x1 in slots:
        glyphs.append((_best_digit(rows, x0, x1), x0, x1, _run_vextent(rows, x0, x1)))
    hard = None
    soft = set()
    for group in _aligned_digit_groups(glyphs):
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


def _aligned_digit_groups(glyphs):
    groups = []
    current = []
    for glyph in glyphs:
        char, _, _, extent = glyph
        if char is None or extent is None:
            if len(current) >= MIN_CODE_DIGITS:
                groups.append(current)
            current = []
            continue
        if current and not _digits_aligned(current[-1], glyph):
            if len(current) >= MIN_CODE_DIGITS:
                groups.append(current)
            current = []
        current.append(glyph)
    if len(current) >= MIN_CODE_DIGITS:
        groups.append(current)
    return groups


def _digits_aligned(prev, cur):
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
