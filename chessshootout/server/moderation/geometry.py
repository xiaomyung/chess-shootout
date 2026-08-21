from collections.abc import Iterable

from chessshootout.backend.utils import BOARD_SIZE, Square


DEFAULT_SUPERSAMPLE = 4

DIHEDRAL = {
    "r0": (1, 0, 0, 1),
    "r90": (0, -1, 1, 0),
    "r180": (-1, 0, 0, -1),
    "r270": (0, 1, -1, 0),
    "fx": (-1, 0, 0, 1),
    "fy": (1, 0, 0, -1),
    "fd": (0, 1, 1, 0),
    "fa": (0, -1, -1, 0),
}

D4_ALL = ("r0", "r90", "r180", "r270", "fx", "fy", "fd", "fa")
D4_ROTATIONS = ("r0", "r90", "r180", "r270")

TRANSFORM_GROUPS = {
    "d4": D4_ALL,
    "d4_no_reflect": D4_ROTATIONS,
}


def square_point(sq: Square) -> tuple[int, int]:
    """
    Convert an engine square into the moderation package's own lattice point,
    the (col, row) space every shape comparison happens in. Arrow endpoints and
    highlighted squares both enter the symbol filter through this conversion

    :param sq: board square as the engine names it, row 0 being Black's back rank.
    :returns: the square as a lattice point (col, row), origin at the top-left square.
    """
    return (sq.col, sq.row)


def sign(value: int) -> int:
    """
    Reduce a coordinate difference to its direction alone. Walking a line and
    spotting a bent arrow tip both need which way a step goes without caring how
    far it goes

    :param value: difference between two coordinates along one axis.
    :returns: -1 when negative, 0 when zero, 1 when positive.
    """
    return (value > 0) - (value < 0)


def apply_op(point: tuple[int, int], op_key: str) -> tuple[int, int]:
    """
    Apply one of the eight square symmetries -- four rotations and four
    reflections -- to a lattice point about the origin. Every banned pattern is
    compiled through the whole group, so turning or mirroring a symbol is no way
    around the filter

    :param point: lattice point as (col, row).
    :param op_key: key into DIHEDRAL, e.g. r90 or fd.
    :returns: the point after that symmetry.
    """
    a, b, c, d = DIHEDRAL[op_key]
    x, y = point
    return (a * x + b * y, c * x + d * y)


def transform_point(point: tuple[int, int], op_key: str,
                    origin: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """
    Apply a square symmetry about a chosen centre instead of the origin, so a
    shape can be turned where it stands rather than swinging away across the
    board

    :param point: lattice point as (col, row).
    :param op_key: key into DIHEDRAL naming the rotation or reflection.
    :param origin: lattice point the operation turns about.
    :returns: the point after that symmetry.
    """
    ox, oy = origin
    x, y = point
    return _translate_point(apply_op((x - ox, y - oy), op_key), ox, oy)


def scale_point(point: tuple[int, int], factor: int,
                origin: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """
    Push a lattice point away from a centre by a whole-number factor. Scaling is
    what lets one authored template also catch the same symbol drawn two or
    three times as large

    :param point: lattice point as (col, row).
    :param factor: whole-number magnification; 1 leaves the point where it is.
    :param origin: lattice point the magnification is measured from.
    :returns: the scaled point.
    """
    ox, oy = origin
    x, y = point
    return (ox + (x - ox) * factor, oy + (y - oy) * factor)


def _translate_point(point: tuple[int, int], dx: int, dy: int) -> tuple[int, int]:
    """
    Shift a lattice point by whole squares, the primitive every placement search
    uses to slide a shape around the board

    :param point: lattice point as (col, row).
    :param dx: columns to move by, positive towards the h-file.
    :param dy: rows to move by, positive downwards towards rank 1.
    :returns: the shifted point.
    """
    return (point[0] + dx, point[1] + dy)


def canonical_edge(a: tuple[int, int],
                   b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """
    Give one edge a single spelling by ordering its endpoints, so the same short
    segment compares equal however it was drawn. This is why drawing an arrow
    backwards cannot dodge a pattern match

    :param a: one endpoint as (col, row).
    :param b: the other endpoint.
    :returns: the endpoints as a pair, smaller point first.
    """
    return (a, b) if a <= b else (b, a)


def transform_segments(
        segments: list[tuple[tuple[int, int], tuple[int, int]]], op_key: str,
        origin: tuple[int, int] = (0, 0)) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Turn or mirror a whole stroke set at once, the segment-level counterpart of
    transform_point used while compiling a pattern's symmetry orbit

    :param segments: straight strokes as (start, end) lattice-point pairs.
    :param op_key: key into DIHEDRAL naming the rotation or reflection.
    :param origin: lattice point the operation turns about.
    :returns: the strokes after that symmetry.
    """
    return [(transform_point(a, op_key, origin), transform_point(b, op_key, origin))
            for a, b in segments]


def scale_segments(
        segments: list[tuple[tuple[int, int], tuple[int, int]]], factor: int,
        origin: tuple[int, int] = (0, 0)) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Magnify a whole stroke set, the segment-level counterpart of scale_point
    used to compile the larger drawings of one authored pattern

    :param segments: straight strokes as (start, end) lattice-point pairs.
    :param factor: whole-number magnification; 1 leaves the strokes as authored.
    :param origin: lattice point the magnification is measured from.
    :returns: the magnified strokes.
    """
    return [(scale_point(a, factor, origin), scale_point(b, factor, origin))
            for a, b in segments]


def translate_edges(edges: Iterable[tuple[tuple[int, int], tuple[int, int]]], dx: int,
                    dy: int) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Slide a compiled template's edges to a candidate spot on the board. The
    vector stage tries one translation per plausible placement, which is how a
    symbol counts wherever on the board it was drawn

    :param edges: canonical unit edges of the template.
    :param dx: columns to move by.
    :param dy: rows to move by.
    :returns: the moved edges, still in canonical form.
    """
    return {canonical_edge(_translate_point(a, dx, dy), _translate_point(b, dx, dy))
            for a, b in edges}


def polyline_between(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """
    Trace the path the client really draws between two squares: a straight line,
    except a knight jump, which is drawn as an L with the long leg first. The
    filter's geometry has to agree with what players see, or a knight-arrow
    symbol would be compared against a shape nobody drew

    :param a: start point as (col, row).
    :param b: end point as (col, row).
    :returns: the path as two points, or three when it bends at an elbow.
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if {abs(dx), abs(dy)} == {1, 2}:
        if abs(dy) == 2:
            elbow = (a[0], b[1])
        else:
            elbow = (b[0], a[1])
        return [a, elbow, b]
    return [a, b]


def arrow_polyline(from_sq: Square, to_sq: Square) -> list[tuple[int, int]]:
    """
    Trace one drawn arrow as a path of lattice points, the shared first step of
    both the vector and the raster view of that arrow

    :param from_sq: square the arrow starts on.
    :param to_sq: square the arrow points at.
    :returns: the arrow's path, carrying an elbow point for a knight move.
    """
    return polyline_between(square_point(from_sq), square_point(to_sq))


def segment_legs(
        segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Split authored template strokes into their straight legs, using the same
    knight-L rule the client draws with. Templates therefore break down exactly
    the way a player's arrows do, which is what makes authored and drawn shapes
    comparable at all

    :param segments: authored strokes as (start, end) lattice-point pairs.
    :returns: the straight legs those strokes are made of.
    """
    legs = []
    for a, b in segments:
        points = polyline_between(a, b)
        legs.extend((points[i], points[i + 1]) for i in range(len(points) - 1))
    return legs


def segment_unit_edges(
        a: tuple[int, int],
        b: tuple[int, int]) -> set[tuple[tuple[int, int], tuple[int, int]]] | None:
    """
    Walk one straight leg into the single-square edges it covers, the atoms the
    vector stage matches on. Splitting a long arrow into short ones, or merging
    short ones into a long one, yields the very same edges

    :param a: start point as (col, row).
    :param b: end point as (col, row).
    :returns: the unit edges; empty for a zero-length leg, or None when the leg
        runs neither along a line nor along a diagonal and so is undrawable.
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0 and dy == 0:
        return set()
    axis = (dx == 0) != (dy == 0)
    diagonal = abs(dx) == abs(dy)
    if not (axis or diagonal):
        return None
    steps = max(abs(dx), abs(dy))
    sx = sign(dx)
    sy = sign(dy)
    edges = set()
    cx, cy = a
    for _ in range(steps):
        nx, ny = cx + sx, cy + sy
        edges.add(canonical_edge((cx, cy), (nx, ny)))
        cx, cy = nx, ny
    return edges


def polyline_unit_edges(
        points: list[tuple[int, int]]) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Collect the unit edges of a whole path, leg after leg. A knight arrow
    contributes both legs of its L, and an undrawable leg simply adds nothing

    :param points: path as consecutive lattice points.
    :returns: every unit edge the path covers.
    """
    edges = set()
    for i in range(len(points) - 1):
        segment = segment_unit_edges(points[i], points[i + 1])
        if segment:
            edges |= segment
    return edges


def arrow_unit_edges(from_sq: Square,
                     to_sq: Square) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """
    The vector channel's view of one drawn arrow: the single-square edges it
    lays down. Every shared arrow is reduced to this before it is weighed
    against the pattern library

    :param from_sq: square the arrow starts on.
    :param to_sq: square the arrow points at.
    :returns: the arrow's unit edges.
    """
    return polyline_unit_edges(arrow_polyline(from_sq, to_sq))


def arrow_segments(from_sq: Square,
                   to_sq: Square) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    The raster channel's view of one drawn arrow: its path as straight segments,
    ready to be painted onto the board bitmap

    :param from_sq: square the arrow starts on.
    :param to_sq: square the arrow points at.
    :returns: the arrow's straight segments in drawing order.
    """
    points = arrow_polyline(from_sq, to_sq)
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def edges_bbox(
        edges: Iterable[tuple[tuple[int, int], tuple[int, int]]],
) -> tuple[int, int, int, int] | None:
    """
    Measure the box a set of edges occupies. This is the span check that keeps
    the novelty heuristic to compact shapes and bounds where a template may sit

    :param edges: canonical unit edges.
    :returns: (min col, min row, max col, max row), or None when there are no edges.
    """
    if not edges:
        return None
    xs = [c for a, b in edges for c in (a[0], b[0])]
    ys = [c for a, b in edges for c in (a[1], b[1])]
    return (min(xs), min(ys), max(xs), max(ys))


def normalize_edges(
        edges: Iterable[tuple[tuple[int, int], tuple[int, int]]],
) -> tuple[frozenset[tuple[tuple[int, int], tuple[int, int]]], int, int]:
    """
    Anchor an edge set at the origin and report how far it reaches, giving every
    drawing of one shape a single spelling. Pattern compilation dedupes a
    symmetry orbit on this form, so symmetries that coincide are stored once

    :param edges: canonical unit edges in board coordinates.
    :returns: the edges anchored at the origin, plus their column and row spans.
    """
    box = edges_bbox(edges)
    if box is None:
        return (frozenset(), 0, 0)
    minx, miny, maxx, maxy = box
    shifted = frozenset(canonical_edge((a[0] - minx, a[1] - miny), (b[0] - minx, b[1] - miny))
                        for a, b in edges)
    return (shifted, maxx - minx, maxy - miny)


def _bresenham(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """
    Walk the whole-number points along a straight line, the classic integer line
    walk. Used both to light pixels for the raster board and to list the squares
    an arrow crosses

    :param x0: start column.
    :param y0: start row.
    :param x1: end column.
    :param y1: end row.
    :returns: every point on the line, both ends included.
    """
    pixels = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        pixels.append((x, y))
        if x == x1 and y == y1:
            break
        double = 2 * err
        if double >= dy:
            err += dy
            x += sx
        if double <= dx:
            err += dx
            y += sy
    return pixels


def segment_pixel(point: tuple[int, int], supersample: int) -> tuple[int, int]:
    """
    Find the middle pixel of a square in the supersampled bitmap. Arrow strokes
    run centre to centre, so they read as thin lines beside the solid blocks a
    highlighted square leaves

    :param point: lattice point as (col, row).
    :param supersample: pixels per square along one side.
    :returns: the centre pixel as (x, y).
    """
    x, y = point
    return (x * supersample + supersample // 2, y * supersample + supersample // 2)


def lit_pixels_from_segments(
        segments: list[tuple[tuple[int, int], tuple[int, int]]],
        supersample: int = DEFAULT_SUPERSAMPLE) -> set[tuple[int, int]]:
    """
    Paint arrow strokes onto the pixel grid as centre-to-centre lines. This is
    how an arrow contributes ink to the raster channel, where drawings are
    compared against symbol bitmaps

    :param segments: straight strokes as (start, end) lattice-point pairs.
    :param supersample: pixels per square along one side.
    :returns: every lit pixel as (x, y).
    """
    pixels = set()
    for a, b in segments:
        ax, ay = segment_pixel(a, supersample)
        bx, by = segment_pixel(b, supersample)
        pixels.update(_bresenham(ax, ay, bx, by))
    return pixels


def lit_pixels_from_cells(cells: Iterable[tuple[int, int]],
                          supersample: int = DEFAULT_SUPERSAMPLE) -> set[tuple[int, int]]:
    """
    Fill highlighted squares onto the pixel grid, each square lighting its whole
    block. Highlights are the raster channel's solid ink, next to the thin lines
    arrows leave

    :param cells: highlighted squares as (col, row) lattice points.
    :param supersample: pixels per square along one side.
    :returns: every lit pixel as (x, y).
    """
    pixels = set()
    for cx, cy in cells:
        for i in range(supersample):
            for j in range(supersample):
                pixels.add((cx * supersample + i, cy * supersample + j))
    return pixels


def pixels_bbox(pixels: set[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    """
    Measure the box a set of lit pixels occupies, which bounds where a template
    is worth trying instead of sweeping the whole board

    :param pixels: lit pixels as (x, y).
    :returns: (min x, min y, max x, max y), or None when nothing is lit.
    """
    if not pixels:
        return None
    xs = [p[0] for p in pixels]
    ys = [p[1] for p in pixels]
    return (min(xs), min(ys), max(xs), max(ys))


def bitmap_from_pixels(pixels: Iterable[tuple[int, int]], width: int, height: int,
                       offset_x: int = 0, offset_y: int = 0) -> list[int]:
    """
    Pack lit pixels into one integer per row, bit x standing for column x.
    Template matching is bitwise overlap counting on these rows, which is what
    keeps a whole-board scan cheap enough to run beside a live game

    :param pixels: lit pixels as (x, y).
    :param width: window width in pixels; bits outside it are dropped.
    :param height: window height in pixels; rows outside it are dropped.
    :param offset_x: pixel column the window starts at.
    :param offset_y: pixel row the window starts at.
    :returns: one bitmask per row, lowest bit leftmost.
    """
    rows = [0] * height
    for px, py in pixels:
        x = px - offset_x
        y = py - offset_y
        if 0 <= x < width and 0 <= y < height:
            rows[y] |= (1 << x)
    return rows


def normalized_bitmap_from_pixels(
        pixels: set[tuple[int, int]]) -> tuple[list[int], int, int]:
    """
    Pack lit pixels into a bitmap trimmed to the ink itself. Compiled raster
    templates are stored this way, so where a pattern happened to be authored
    never affects what it matches

    :param pixels: lit pixels as (x, y).
    :returns: the trimmed rows plus their width and height in pixels; no rows
        and zero sizes when nothing is lit.
    """
    box = pixels_bbox(pixels)
    if box is None:
        return ([], 0, 0)
    minx, miny, maxx, maxy = box
    width = maxx - minx + 1
    height = maxy - miny + 1
    return (bitmap_from_pixels(pixels, width, height, minx, miny), width, height)


def rasterize_board(segments: list[tuple[tuple[int, int], tuple[int, int]]],
                    cells: Iterable[tuple[int, int]],
                    supersample: int = DEFAULT_SUPERSAMPLE,
                    board_cells: int = BOARD_SIZE) -> list[int]:
    """
    Paint one whole board -- arrows and highlights together -- into a single
    bitmap. Both kinds of mark landing on one canvas is why a symbol drawn half
    in arrows and half in highlights still reads as that symbol

    :param segments: arrow strokes as (start, end) lattice-point pairs.
    :param cells: filled squares as (col, row) lattice points.
    :param supersample: pixels per square along one side.
    :param board_cells: squares along one side of the board.
    :returns: one bitmask per pixel row of the board.
    """
    side = board_cells * supersample
    pixels = lit_pixels_from_segments(segments, supersample)
    pixels |= lit_pixels_from_cells(cells, supersample)
    return bitmap_from_pixels(pixels, side, side)


def board_width(supersample: int = DEFAULT_SUPERSAMPLE,
                board_cells: int = BOARD_SIZE) -> int:
    """
    Report the side of the board in bitmap pixels, the bound every placement
    search stays inside

    :param supersample: pixels per square along one side.
    :param board_cells: squares along one side of the board.
    :returns: the board's side length in pixels.
    """
    return board_cells * supersample


def popcount(rows: list[int]) -> int:
    """
    Count the lit pixels of a bitmap. Coverage and overlap are both fractions of
    ink, so this is the measure the raster stage compares on

    :param rows: bitmask per pixel row.
    :returns: how many pixels are lit.
    """
    return sum(row.bit_count() for row in rows)


def embed(rows: list[int], offset_x: int, offset_y: int, board_width_px: int,
          board_height_px: int) -> list[int]:
    """
    Place a template bitmap onto a board-sized canvas at the spot it matched, so
    the caller can work out which of the player's marks that match covered

    :param rows: template bitmask per row.
    :param offset_x: pixel column the template matched at.
    :param offset_y: pixel row the template matched at.
    :param board_width_px: canvas width in pixels; bits past it are dropped.
    :param board_height_px: canvas height in pixels; rows past it are dropped.
    :returns: a board-sized bitmap holding just the placed template.
    """
    placed = [0] * board_height_px
    board_mask = (1 << board_width_px) - 1
    for y, row in enumerate(rows):
        by = y + offset_y
        if 0 <= by < board_height_px:
            if offset_x >= 0:
                placed[by] = (row << offset_x) & board_mask
            else:
                placed[by] = (row >> (-offset_x)) & board_mask
    return placed


def bitmap_bbox(rows: list[int], width: int) -> tuple[int, int, int, int] | None:
    """
    Measure the box the ink of a bitmap occupies, read straight off the row
    bitmasks. The raster stage only tries placements that can reach this box

    :param rows: bitmask per pixel row.
    :param width: row width in pixels.
    :returns: (min x, min y, max x, max y), or None when nothing is lit.
    """
    minx = width
    maxx = -1
    miny = None
    maxy = None
    for y, row in enumerate(rows):
        if row == 0:
            continue
        if miny is None:
            miny = y
        maxy = y
        low = (row & -row).bit_length() - 1
        high = row.bit_length() - 1
        if low < minx:
            minx = low
        if high > maxx:
            maxx = high
    if miny is None:
        return None
    return (minx, miny, maxx, maxy)


def local_ink(rows: list[int], x0: int, y0: int, x1: int, y1: int) -> int:
    """
    Count the lit pixels inside one window of a bitmap. Overlap is measured
    locally, around the placement only, so a large scribble elsewhere on the
    board cannot dilute the ratio and hide a fully drawn symbol

    :param rows: bitmask per pixel row.
    :param x0: first pixel column of the window.
    :param y0: first pixel row of the window.
    :param x1: pixel column just past the window.
    :param y1: pixel row just past the window.
    :returns: how many pixels are lit inside the window.
    """
    mask = (1 << (x1 - x0)) - 1
    return sum(((rows[y] >> x0) & mask).bit_count() for y in range(y0, y1))


def traversed_cells(
        segments: list[tuple[tuple[int, int], tuple[int, int]]]) -> set[tuple[int, int]]:
    """
    List the squares an arrow passes over. The raster board counts these as
    filled, so strokes and highlights build one shape together instead of two
    half-drawn ones

    :param segments: straight strokes as (start, end) lattice-point pairs.
    :returns: every square the strokes cross, as (col, row) lattice points.
    """
    cells = set()
    for a, b in segments:
        cells.update(_bresenham(a[0], a[1], b[0], b[1]))
    return cells
