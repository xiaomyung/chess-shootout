import math
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, cast

from chessshootout.backend.utils import BOARD_SIZE, Square, square_from_coord

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
_CACHE: "dict[tuple[Any, ...], Verdict]" = {}
_CACHE_ORDER: list[tuple[Any, ...]] = []
_LOCK = threading.Lock()


@dataclass
class Verdict:
    """
    What the symbol filter concluded about one drawing of shared board marks:
    clean, suspect or blocked, which library pattern (or the novelty heuristic)
    it matched, and which marks made up the match. The handler relays, warns or
    strips on the strength of this
    """

    kind: str
    pattern_id: object = None
    matched_arrows: list[tuple[str, str]] = field(default_factory=list)
    matched_highlights: list[str] = field(default_factory=list)


def union_sides(arrows_a: Iterable[tuple[str, str]], highlights_a: Iterable[str],
                arrows_b: Iterable[tuple[str, str]],
                highlights_b: Iterable[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """
    Merge both players' shared marks into one drawing, so two people cannot each
    draw half a symbol and have neither half count. Duplicates collapse and the
    order the marks came in is kept

    :param arrows_a: one side's arrows as (from square, to square) pairs.
    :param highlights_a: one side's highlighted squares in algebraic form.
    :param arrows_b: the other side's arrows.
    :param highlights_b: the other side's highlighted squares.
    :returns: the combined arrows and highlights of both sides.
    """
    arrows = list(dict.fromkeys(list(arrows_a) + list(arrows_b)))
    highlights = list(dict.fromkeys(list(highlights_a) + list(highlights_b)))
    return arrows, highlights


def _square(coord: str) -> Square:
    """
    Read one algebraic square name into an engine square. Marks reach the filter
    as the same text they travel on the wire in, and this is where that text
    becomes geometry

    :param coord: square in algebraic form, e.g. e4.
    :returns: the matching board square.
    """
    return square_from_coord(coord)


def _cell(coord: str) -> tuple[int, int]:
    """
    Read one algebraic square name straight into a lattice cell, the (col, row)
    space the board bitmap and every template are built in

    :param coord: square in algebraic form, e.g. e4.
    :returns: the square as a lattice point (col, row).
    """
    sq = square_from_coord(coord)
    return (sq.col, sq.row)


def _ensure_floors() -> tuple[int, int]:
    """
    Work out the least ink any enabled pattern could possibly need. A drawing
    below both floors, with no suspicious centre either, is declared clean
    without trying a single template -- the cheap exit that keeps ordinary game
    chatter almost free. Computed once and reused for the life of the process

    :returns: the smallest matchable edge count and pixel count.
    """
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


def _needed(size: int, threshold: float) -> int:
    """
    How much of a template has to be present before it counts as drawn. Coverage
    is a fraction of the pattern's own size, and always at least one element, so
    a partly drawn symbol still trips once it is recognisable

    :param size: the template's own edge or pixel count.
    :param threshold: fraction of it that must be present, from patterns.json.
    :returns: the number of elements required, never below one.
    """
    return max(math.ceil(size * threshold), 1)


def _normalize_inputs(
        arrows: Iterable[tuple[str, str]], highlights: Iterable[str],
) -> tuple[list[tuple[str, str]], list[str],
           list[tuple[tuple[str, str], set[tuple[tuple[int, int], tuple[int, int]]]]],
           set[tuple[tuple[int, int], tuple[int, int]]], list[tuple[int, int]]]:
    """
    Turn the marks as they arrived off the wire into every form the stages need.
    Each arrow keeps its own edges alongside it, which is how a match is later
    traced back to the exact arrows that drew it instead of clearing the board

    :param arrows: drawn arrows as (from square, to square) algebraic pairs.
    :param highlights: highlighted squares in algebraic form.
    :returns: the arrows and highlights as lists, each arrow paired with its own
        edges, all edges together, and the highlighted lattice cells.
    """
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


def _changed_edges_cells(
        changed: str | tuple[str, str] | None,
) -> tuple[set[tuple[tuple[int, int], tuple[int, int]]] | None,
           set[tuple[int, int]] | None]:
    """
    Work out what the mark a player has just drawn covers, both as edges and as
    squares. The stages anchor their search on it, so a drawing being built up
    stroke by stroke is checked around the newest stroke rather than rescanned
    whole every time

    :param changed: the mark just added -- a square, an arrow as a pair of
        squares, or None when the whole drawing is the anchor.
    :returns: the edges and squares that mark covers, or (None, None) when there
        is no anchor.
    """
    if changed is None:
        return None, None
    if isinstance(changed, str):
        return set(), {_cell(changed)}
    from_sq = _square(changed[0])
    to_sq = _square(changed[1])
    edges = geometry.arrow_unit_edges(from_sq, to_sq)
    cells = geometry.traversed_cells(geometry.arrow_segments(from_sq, to_sq))
    return edges, cells


def detect(arrows: Iterable[tuple[str, str]], highlights: Iterable[str],
           changed: str | tuple[str, str] | None = None,
           context: Iterable[str] = ()) -> Verdict:
    """
    Judge one drawing of shared board marks against the banned-symbol library
    and answer with the verdict the game server acts on: relay it, warn the
    drawer, or strip the marks. This is the only entry point into the filter,
    and it is safe to call from the worker threads marks are checked in --
    library build and the bounded memo of recent verdicts are both locked

    :param arrows: drawn arrows as (from square, to square) algebraic pairs.
    :param highlights: highlighted squares in algebraic form.
    :param changed: the mark just added, which anchors an incremental check;
        None checks the whole drawing.
    :param context: squares the board lights for free, such as the last move
        played -- they can complete a symbol but are never reported as marks.
    :returns: the verdict for this drawing.
    """
    with _LOCK:
        library.preload()
        _ensure_floors()
    arrows, highlights, arrow_edges, drawn_edges, cells = _normalize_inputs(arrows, highlights)
    context_cells = [_cell(coord) for coord in context]
    changed_edges, changed_cells = _changed_edges_cells(changed)
    key = (tuple(arrows), tuple(highlights), frozenset(context_cells),
           _changed_key(changed_edges, changed_cells))
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    verdict = _run(arrows, highlights, arrow_edges, drawn_edges, cells, context_cells,
                   changed_edges, changed_cells)
    with _LOCK:
        _cache_put(key, verdict)
    return verdict


def _changed_key(
        changed_edges: set[tuple[tuple[int, int], tuple[int, int]]] | None,
        changed_cells: set[tuple[int, int]] | None,
) -> tuple[frozenset[tuple[tuple[int, int], tuple[int, int]]],
           frozenset[tuple[int, int]]] | None:
    """
    Fold the anchor into the memo key. A drawing checked while it was being
    built and the same drawing checked whole are different questions, so they
    must not share one cached answer

    :param changed_edges: edges the newest mark covers, or None when unanchored.
    :param changed_cells: squares the newest mark covers, or None.
    :returns: a hashable form of the anchor, or None when there is none.
    """
    if changed_edges is None:
        return None
    return (frozenset(changed_edges),
            frozenset(cast(set[tuple[int, int]], changed_cells)))


def _cache_put(key: tuple[Any, ...], verdict: Verdict) -> None:
    """
    Remember one verdict, dropping the oldest once the memo is full. The bound
    is what stops a player who keeps drawing fresh nonsense from growing the
    server's memory. Called with the module lock held, because the memo is
    shared by every worker thread

    :param key: the drawing's memo key, as built by detect.
    :param verdict: the verdict to remember for it.
    """
    if key in _CACHE:
        return
    _CACHE[key] = verdict
    _CACHE_ORDER.append(key)
    if len(_CACHE_ORDER) > CACHE_LIMIT:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)


def _run(arrows: list[tuple[str, str]], highlights: list[str],
         arrow_edges: list[tuple[tuple[str, str],
                                 set[tuple[tuple[int, int], tuple[int, int]]]]],
         drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]],
         cells: list[tuple[int, int]], context_cells: list[tuple[int, int]],
         changed_edges: set[tuple[tuple[int, int], tuple[int, int]]] | None,
         changed_cells: set[tuple[int, int]] | None) -> Verdict:
    """
    Put one drawing through the filter's stages in order -- too little ink to
    match anything, arrow templates, pixel templates, the same templates against
    the unhighlighted squares, and finally the novelty net for pinwheels nobody
    authored a template for. The first stage that fires decides the verdict, and
    a drawing that survives them all is clean

    :param arrows: drawn arrows as (from square, to square) algebraic pairs.
    :param highlights: highlighted squares in algebraic form.
    :param arrow_edges: each arrow paired with the edges it lays down.
    :param drawn_edges: every edge in the drawing.
    :param cells: highlighted squares as lattice points.
    :param context_cells: free squares that count as ink but never as marks.
    :param changed_edges: edges of the newest mark, or None when unanchored.
    :param changed_cells: squares of the newest mark, or None.
    :returns: the verdict for this drawing.
    """
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


def _stage_vector(
        drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]],
        anchor_edges: set[tuple[tuple[int, int], tuple[int, int]]],
        arrow_edges: list[tuple[tuple[str, str],
                                set[tuple[tuple[int, int], tuple[int, int]]]]],
        arrows: list[tuple[str, str]],
) -> tuple[library.CompiledPattern,
           set[tuple[tuple[int, int], tuple[int, int]]], list[tuple[str, str]]] | None:
    """
    Compare the drawing's edges with every arrow-channel template in the symbol
    library. A match made purely of knight arrows is let go when the drawing is
    mirror-symmetric, because that is an ordinary knight fan rather than the
    one-handed pinwheel a symbol needs

    :param drawn_edges: every edge in the drawing.
    :param anchor_edges: edges placements must line up with, the newest mark's
        when there is one, otherwise the whole drawing's.
    :param arrow_edges: each arrow paired with the edges it lays down.
    :param arrows: the drawn arrows, in the order they were shared.
    :returns: the pattern, the edges it matched and the arrows that drew them,
        or None when nothing matched.
    """
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


def _match_variant(
        variant: library.VectorVariant,
        drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]],
        anchor_by_delta: dict[tuple[int, int],
                              list[tuple[tuple[int, int], tuple[int, int]]]],
        threshold: float,
) -> tuple[set[tuple[tuple[int, int], tuple[int, int]]],
           set[tuple[tuple[int, int], tuple[int, int]]]] | None:
    """
    Try one compiled drawing at every position worth testing. Only placements
    that put a template edge on top of an anchor edge going the same way are
    considered, which is what keeps a whole-board search affordable

    :param variant: one compiled drawing of a pattern.
    :param drawn_edges: every edge in the drawing.
    :param anchor_by_delta: anchor edges grouped by their direction and length.
    :param threshold: fraction of the template that must be present.
    :returns: the edges actually covered and the whole placed template, or None
        when no placement reached the threshold.
    """
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


def _delta(edge: tuple[tuple[int, int], tuple[int, int]]) -> tuple[int, int]:
    """
    Describe an edge by the step from one end to the other. Placements are
    grouped by this, so only template edges that could genuinely lie on a drawn
    edge are ever tried

    :param edge: a canonical edge as a pair of lattice points.
    :returns: the step between its endpoints as (dcol, drow).
    """
    a, b = edge
    return (b[0] - a[0], b[1] - a[1])


def _is_knight(arrow: tuple[str, str]) -> bool:
    """
    Tell whether an arrow is a knight move. Knight arrows are drawn bent, and
    four of them from one square make a pinwheel that is either a symbol or a
    perfectly ordinary look at where a knight can go -- so they get their own
    handling

    :param arrow: an arrow as (from square, to square) in algebraic form.
    :returns: True when the arrow spans a knight's leap.
    """
    from_sq = _square(arrow[0])
    to_sq = _square(arrow[1])
    return {abs(to_sq.row - from_sq.row), abs(to_sq.col - from_sq.col)} == {1, 2}


def _fan_suppressed(matched: list[tuple[str, str]],
                    placed: set[tuple[tuple[int, int], tuple[int, int]]],
                    drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]]) -> bool:
    """
    Decide that an all-knight match is chess analysis rather than a symbol. If
    the player also drew the mirror image of the matched shape, the drawing is
    symmetric, and a symbol of this family never is -- so the match is dropped
    and an ordinary knight fan keeps working

    :param matched: the arrows the match was made of.
    :param placed: the template as it was placed on the board.
    :param drawn_edges: every edge in the drawing.
    :returns: True when the match should be ignored.
    """
    if not matched or not all(_is_knight(arrow) for arrow in matched):
        return False
    return _mirror_present(placed, drawn_edges)


def _mirror_present(placed_edges: set[tuple[tuple[int, int], tuple[int, int]]],
                    drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]]) -> bool:
    """
    Tell whether the drawing also contains a mirror image of a matched shape
    about that shape's own centre. Mirroring is tested on a doubled lattice so a
    centre that falls between squares is still exact

    :param placed_edges: the template as it was placed on the board.
    :param drawn_edges: every edge in the drawing.
    :returns: True when at least one mirror of the shape is also drawn.
    """
    placed_doubled = {_double_edge(edge) for edge in placed_edges}
    drawn_doubled = {_double_edge(edge) for edge in drawn_edges}
    box = geometry.edges_bbox(placed_doubled)
    if box is None:
        return False
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    for axis in ("x", "y", "d", "a"):
        reflected = _transform_edges_about(
            placed_doubled, cx, cy,
            cast(Callable[[tuple[int, int], int, int], tuple[int, int]],
                 lambda p, gx, gy, ax=axis: _reflect(p, gx, gy, ax)))
        if reflected != placed_doubled and reflected <= drawn_doubled:
            return True
    return False


def _complement_board(cells: list[tuple[int, int]], supersample: int) -> list[int]:
    """
    Paint the squares the player did not highlight. Flooding the board and
    leaving a symbol as the empty space is a real evasion, so the same templates
    are run against the negative of the drawing too

    :param cells: the highlighted squares as lattice points.
    :param supersample: pixels per square along one side.
    :returns: a board bitmap of every square that was left unhighlighted.
    """
    filled = set(cells)
    complement = [(cx, cy) for cx in range(BOARD_SIZE) for cy in range(BOARD_SIZE)
                  if (cx, cy) not in filled]
    return geometry.rasterize_board([], complement, supersample)


def _stage_raster(
        board: list[int], highlight_board: list[int], side: int,
        drawn_bbox: tuple[int, int, int, int] | None,
        window: tuple[int, int, int, int] | None,
) -> tuple[library.CompiledPattern, list[int]] | None:
    """
    Compare the board picture with every pixel-channel template in the symbol
    library, stopping at the first pattern that really is drawn there

    :param board: the drawing as a board bitmap, arrows and highlights together.
    :param highlight_board: the same board with only the filled squares on it.
    :param side: the board's side length in pixels.
    :param drawn_bbox: the box the drawing occupies, or None when it is empty.
    :param window: the box around the newest mark, or None to search the whole
        drawing.
    :returns: the pattern and the template as placed, or None when none matched.
    """
    for pattern in library.enabled_patterns():
        if pattern.channel not in (library.RASTER, library.BOTH):
            continue
        best = _match_raster(pattern, board, highlight_board, side, drawn_bbox, window)
        if best is not None:
            return (pattern, best)
    return None


def _match_raster(pattern: library.CompiledPattern, board: list[int],
                  highlight_board: list[int], side: int,
                  drawn_bbox: tuple[int, int, int, int] | None,
                  window: tuple[int, int, int, int] | None) -> list[int] | None:
    """
    Slide one pattern's bitmaps across the region worth searching and report the
    first placement that is genuinely the symbol. Three things must hold at
    once: enough of the template is covered, enough of that comes from really
    highlighted squares (so a cluster of arrows never matches a squares
    template), and the ink right around the placement matches it closely, so a
    big scribble that happens to contain the shape is not read as one

    :param pattern: the library entry being tried.
    :param board: the drawing as a board bitmap, arrows and highlights together.
    :param highlight_board: the same board with only the filled squares on it.
    :param side: the board's side length in pixels.
    :param drawn_bbox: the box the drawing occupies, or None when it is empty.
    :param window: the box around the newest mark, or None to use the drawing's.
    :returns: the template as placed on the board, or None when it is not there.
    """
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


def _map_pixels(placed_rows: list[int], arrows: list[tuple[str, str]],
                highlights: list[str], cells: list[tuple[int, int]],
                supersample: int) -> tuple[list[tuple[str, str]], list[str]]:
    """
    Work out which of the player's own marks the matched pixels came from, so a
    block can name and remove exactly the arrows and squares that drew the
    symbol instead of wiping the board. Free context squares are not in this
    list, because they were never the player's to remove

    :param placed_rows: the matched template as placed, one bitmask per row.
    :param arrows: drawn arrows as (from square, to square) algebraic pairs.
    :param highlights: highlighted squares in algebraic form.
    :param cells: those same highlighted squares as lattice points.
    :param supersample: pixels per square along one side.
    :returns: the arrows and highlights that overlap the matched shape.
    """
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


def _changed_pixels(
        changed_edges: set[tuple[tuple[int, int], tuple[int, int]]] | None,
        changed_cells: set[tuple[int, int]] | None,
        supersample: int) -> tuple[int, int, int, int] | None:
    """
    Bound the pixel search to the neighbourhood of the mark just drawn. While a
    player is still drawing, only placements that could involve the newest
    stroke can newly complete a symbol, so the rest of the board is skipped

    :param changed_edges: edges the newest mark covers, or None.
    :param changed_cells: squares the newest mark covers, or None.
    :param supersample: pixels per square along one side.
    :returns: the pixel box to search, or None when the mark covers nothing.
    """
    cells = set(changed_cells) if changed_cells else set()
    if changed_edges:
        for a, b in changed_edges:
            cells.add(a)
            cells.add(b)
    if not cells:
        return None
    return geometry.pixels_bbox(geometry.lit_pixels_from_cells(cells, supersample))


def _heuristic_center(
        drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]],
) -> tuple[int, int, bool,
           frozenset[tuple[tuple[int, int], tuple[int, int]]]] | None:
    """
    Look for a pinwheel: a shape that turns onto itself in quarter turns but
    never mirrors onto itself. That handedness is what a swastika has whatever
    its arms look like, so this is the net for hate symbols nobody wrote a
    template for. Large drawings get one cheap whole-set test; smaller ones get
    the per-centre scan, where a throwaway decoy arrow simply falls out of the
    shape being tested

    :param drawn_edges: every edge in the drawing.
    :returns: the centre on the doubled lattice, whether the shape is tight
        enough to block outright, and the pinwheel's own edges -- or None when
        there is no pinwheel.
    """
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


def _heuristic_whole_set(
        doubled: frozenset[tuple[tuple[int, int], tuple[int, int]]],
        box: tuple[int, int, int, int],
) -> tuple[int, int, bool,
           frozenset[tuple[tuple[int, int], tuple[int, int]]]] | None:
    """
    The cheap version of the pinwheel test, for drawings too big to pick apart
    piece by piece: the whole drawing must be the pinwheel, and it must be
    compact. A verdict from here is never treated as tight enough to block on
    its own

    :param doubled: the whole drawing's edges on the doubled lattice.
    :param box: the box those edges occupy.
    :returns: the centre and the drawing's own edges, or None when the drawing
        as a whole is not a compact pinwheel.
    """
    minx, miny, maxx, maxy = box
    if (maxx - minx) // 2 > HEURISTIC_MAX_SPAN or (maxy - miny) // 2 > HEURISTIC_MAX_SPAN:
        return None
    for cx in range(minx, maxx + 1):
        for cy in range(miny, maxy + 1):
            if _is_c4_chiral(doubled, cx, cy):
                return (cx, cy, False, doubled)
    return None


def _c4_chiral_core(
        doubled: frozenset[tuple[tuple[int, int], tuple[int, int]]], cx: int,
        cy: int) -> frozenset[tuple[tuple[int, int], tuple[int, int]]] | None:
    """
    Pull out the part of a drawing that really does turn onto itself about one
    centre, and keep it only if it is compact and one-handed. Working on this
    core rather than the whole drawing is what stops a single decoy arrow from
    switching the pinwheel net off, and rejecting anything mirror-symmetric is
    what keeps plain crosses, stars and analysis fans clean

    :param doubled: the drawing's edges on the doubled lattice.
    :param cx: candidate centre column on that lattice.
    :param cy: candidate centre row on that lattice.
    :returns: the pinwheel's edges, or None when this centre carries none.
    """
    half = {edge for edge in doubled
            if _transform_edge(edge, cx, cy, _rotate180) in doubled}
    if len(half) < HEURISTIC_MIN_EDGES:
        return None
    core = frozenset(edge for edge in half
                     if _transform_edge(edge, cx, cy, _rotate90) in doubled
                     and _transform_edge(edge, cx, cy, _rotate270) in doubled)
    if len(core) < HEURISTIC_MIN_EDGES:
        return None
    cminx, cminy, cmaxx, cmaxy = cast(tuple[int, int, int, int],
                                      geometry.edges_bbox(core))
    if (cmaxx - cminx) // 2 > HEURISTIC_MAX_SPAN or (cmaxy - cminy) // 2 > HEURISTIC_MAX_SPAN:
        return None
    for axis in ("x", "y", "d", "a"):
        reflected = _transform_edges_about(
            core, cx, cy,
            cast(Callable[[tuple[int, int], int, int], tuple[int, int]],
                 lambda p, gx, gy, ax=axis: _reflect(p, gx, gy, ax)))
        if reflected == core:
            return None
        if reflected <= doubled:
            return None
    return core


def _core_tight(core: frozenset[tuple[tuple[int, int], tuple[int, int]]]) -> bool:
    """
    Decide whether a pinwheel is compact and hooked enough to remove outright
    rather than merely flag. A tight, hooked pinwheel is the drawing everyone
    recognises; a sprawling one might still be somebody's diagram, so it is only
    reported as suspect

    :param core: the pinwheel's edges on the doubled lattice.
    :returns: True when the shape is small, dense and hooked.
    """
    if len(core) < HEURISTIC_TIGHT_MIN_EDGES:
        return False
    minx, miny, maxx, maxy = cast(tuple[int, int, int, int],
                                  geometry.edges_bbox(core))
    if (maxx - minx) // 2 > HEURISTIC_TIGHT_MAX_SPAN:
        return False
    if (maxy - miny) // 2 > HEURISTIC_TIGHT_MAX_SPAN:
        return False
    return _bent_tip_count(core) >= HEURISTIC_TIGHT_MIN_TIPS


def _bent_tip_count(core: frozenset[tuple[tuple[int, int], tuple[int, int]]]) -> int:
    """
    Count the arms that end in a hook -- a loose end whose last stroke turns a
    corner. Hooks are what separate a swastika from a plain star or cross, so
    this is the deciding measure for blocking a pattern nobody authored

    :param core: the pinwheel's edges on the doubled lattice.
    :returns: how many free ends bend rather than run straight.
    """
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


def _transform_edge(
        edge: tuple[tuple[int, int], tuple[int, int]], cx: int, cy: int,
        fn: Callable[[tuple[int, int], int, int], tuple[int, int]],
) -> tuple[tuple[int, int], tuple[int, int]]:
    """
    Move both ends of one edge with a point transform and put the result back in
    canonical form, so the moved edge can be looked up in the drawing directly

    :param edge: a canonical edge on the doubled lattice.
    :param cx: centre column the transform works about.
    :param cy: centre row the transform works about.
    :param fn: point transform, one of the rotations or a reflection.
    :returns: the transformed edge, canonical again.
    """
    a, b = edge
    return geometry.canonical_edge(fn(a, cx, cy), fn(b, cx, cy))


def _double_edge(
        edge: tuple[tuple[int, int], tuple[int, int]],
) -> tuple[tuple[int, int], tuple[int, int]]:
    """
    Restate an edge on a lattice of twice the resolution. Pinwheels are often
    centred between squares, and doubling makes such a centre a whole number, so
    the symmetry test stays exact integer work

    :param edge: a canonical edge in board coordinates.
    :returns: the same edge with both endpoints doubled.
    """
    a, b = edge
    return geometry.canonical_edge((a[0] * 2, a[1] * 2), (b[0] * 2, b[1] * 2))


def _rotate90(point: tuple[int, int], cx: int, cy: int) -> tuple[int, int]:
    """
    Turn a point a quarter turn about a centre, the step the pinwheel test
    repeats to see whether a shape looks the same four ways round

    :param point: point on the doubled lattice.
    :param cx: centre column.
    :param cy: centre row.
    :returns: the turned point.
    """
    x, y = point
    return (cx - (y - cy), cy + (x - cx))


def _rotate180(point: tuple[int, int], cx: int, cy: int) -> tuple[int, int]:
    """
    Turn a point half a turn about a centre. The pinwheel test starts here,
    because half-turn symmetry is the cheap filter that shrinks the drawing
    before the quarter turns are tried

    :param point: point on the doubled lattice.
    :param cx: centre column.
    :param cy: centre row.
    :returns: the turned point.
    """
    x, y = point
    return (2 * cx - x, 2 * cy - y)


def _rotate270(point: tuple[int, int], cx: int, cy: int) -> tuple[int, int]:
    """
    Turn a point three quarters about a centre, the other direction the pinwheel
    test checks so a shape has to be the same all four ways round

    :param point: point on the doubled lattice.
    :param cx: centre column.
    :param cy: centre row.
    :returns: the turned point.
    """
    x, y = point
    return (cx + (y - cy), cy - (x - cx))


def _reflect(point: tuple[int, int], cx: int, cy: int, axis: str) -> tuple[int, int]:
    """
    Mirror a point about a centre, along a chosen axis. A shape that mirrors
    onto itself is even-handed, and even-handed shapes are ordinary board
    analysis rather than the one-handed pinwheel a hate symbol is

    :param point: point on the doubled lattice.
    :param cx: centre column.
    :param cy: centre row.
    :param axis: x for the vertical mirror, y for the horizontal one, d and a
        for the two diagonals.
    :returns: the mirrored point.
    """
    x, y = point
    if axis == "x":
        return (2 * cx - x, y)
    if axis == "y":
        return (x, 2 * cy - y)
    if axis == "d":
        return (cx + (y - cy), cy + (x - cx))
    return (cx - (y - cy), cy - (x - cx))


def _transform_edges_about(
        edges: Iterable[tuple[tuple[int, int], tuple[int, int]]], cx: int, cy: int,
        fn: Callable[[tuple[int, int], int, int], tuple[int, int]],
) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Turn or mirror a whole edge set about one centre, so the result can be
    compared with the drawing as a set. Every symmetry test in the pinwheel net
    is such a comparison

    :param edges: canonical edges on the doubled lattice.
    :param cx: centre column the transform works about.
    :param cy: centre row the transform works about.
    :param fn: point transform, one of the rotations or a reflection.
    :returns: the transformed edges, canonical again.
    """
    out = set()
    for a, b in edges:
        na = fn(a, cx, cy)
        nb = fn(b, cx, cy)
        out.add(geometry.canonical_edge(na, nb))
    return out


def _is_c4_chiral(doubled: frozenset[tuple[tuple[int, int], tuple[int, int]]], cx: int,
                  cy: int) -> bool:
    """
    Test a whole drawing at once: does a quarter turn about this centre leave it
    exactly as it was, while no mirror does? That combination -- same four ways
    round, different in a mirror -- is the pinwheel handedness the filter is
    hunting for

    :param doubled: the drawing's edges on the doubled lattice.
    :param cx: candidate centre column.
    :param cy: candidate centre row.
    :returns: True when the whole drawing is a one-handed pinwheel here.
    """
    rotated = _transform_edges_about(doubled, cx, cy, _rotate90)
    if rotated != doubled:
        return False
    for axis in ("x", "y", "d", "a"):
        reflected = _transform_edges_about(
            doubled, cx, cy,
            cast(Callable[[tuple[int, int], int, int], tuple[int, int]],
                 lambda p, gx, gy, ax=axis: _reflect(p, gx, gy, ax)))
        if reflected == doubled:
            return False
    return True
