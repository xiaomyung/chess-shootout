from chessshootout.backend.utils import BOARD_SIZE


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


def square_point(sq):
    return (sq.col, sq.row)


def sign(value):
    return (value > 0) - (value < 0)


def apply_op(point, op_key):
    a, b, c, d = DIHEDRAL[op_key]
    x, y = point
    return (a * x + b * y, c * x + d * y)


def transform_point(point, op_key, origin=(0, 0)):
    ox, oy = origin
    x, y = point
    return _translate_point(apply_op((x - ox, y - oy), op_key), ox, oy)


def scale_point(point, factor, origin=(0, 0)):
    ox, oy = origin
    x, y = point
    return (ox + (x - ox) * factor, oy + (y - oy) * factor)


def _translate_point(point, dx, dy):
    return (point[0] + dx, point[1] + dy)


def canonical_edge(a, b):
    return (a, b) if a <= b else (b, a)


def transform_segments(segments, op_key, origin=(0, 0)):
    return [(transform_point(a, op_key, origin), transform_point(b, op_key, origin))
            for a, b in segments]


def scale_segments(segments, factor, origin=(0, 0)):
    return [(scale_point(a, factor, origin), scale_point(b, factor, origin))
            for a, b in segments]


def translate_edges(edges, dx, dy):
    return {canonical_edge(_translate_point(a, dx, dy), _translate_point(b, dx, dy))
            for a, b in edges}


def polyline_between(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if {abs(dx), abs(dy)} == {1, 2}:
        if abs(dy) == 2:
            elbow = (a[0], b[1])
        else:
            elbow = (b[0], a[1])
        return [a, elbow, b]
    return [a, b]


def arrow_polyline(from_sq, to_sq):
    return polyline_between(square_point(from_sq), square_point(to_sq))


def segment_legs(segments):
    legs = []
    for a, b in segments:
        points = polyline_between(a, b)
        legs.extend((points[i], points[i + 1]) for i in range(len(points) - 1))
    return legs


def segment_unit_edges(a, b):
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


def polyline_unit_edges(points):
    edges = set()
    for i in range(len(points) - 1):
        segment = segment_unit_edges(points[i], points[i + 1])
        if segment:
            edges |= segment
    return edges


def arrow_unit_edges(from_sq, to_sq):
    return polyline_unit_edges(arrow_polyline(from_sq, to_sq))


def arrow_segments(from_sq, to_sq):
    points = arrow_polyline(from_sq, to_sq)
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def edges_bbox(edges):
    if not edges:
        return None
    xs = [c for a, b in edges for c in (a[0], b[0])]
    ys = [c for a, b in edges for c in (a[1], b[1])]
    return (min(xs), min(ys), max(xs), max(ys))


def normalize_edges(edges):
    box = edges_bbox(edges)
    if box is None:
        return (frozenset(), 0, 0)
    minx, miny, maxx, maxy = box
    shifted = frozenset(canonical_edge((a[0] - minx, a[1] - miny), (b[0] - minx, b[1] - miny))
                        for a, b in edges)
    return (shifted, maxx - minx, maxy - miny)


def _bresenham(x0, y0, x1, y1):
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


def segment_pixel(point, supersample):
    x, y = point
    return (x * supersample + supersample // 2, y * supersample + supersample // 2)


def lit_pixels_from_segments(segments, supersample=DEFAULT_SUPERSAMPLE):
    pixels = set()
    for a, b in segments:
        ax, ay = segment_pixel(a, supersample)
        bx, by = segment_pixel(b, supersample)
        pixels.update(_bresenham(ax, ay, bx, by))
    return pixels


def lit_pixels_from_cells(cells, supersample=DEFAULT_SUPERSAMPLE):
    pixels = set()
    for cx, cy in cells:
        for i in range(supersample):
            for j in range(supersample):
                pixels.add((cx * supersample + i, cy * supersample + j))
    return pixels


def pixels_bbox(pixels):
    if not pixels:
        return None
    xs = [p[0] for p in pixels]
    ys = [p[1] for p in pixels]
    return (min(xs), min(ys), max(xs), max(ys))


def bitmap_from_pixels(pixels, width, height, offset_x=0, offset_y=0):
    rows = [0] * height
    for px, py in pixels:
        x = px - offset_x
        y = py - offset_y
        if 0 <= x < width and 0 <= y < height:
            rows[y] |= (1 << x)
    return rows


def normalized_bitmap_from_pixels(pixels):
    box = pixels_bbox(pixels)
    if box is None:
        return ([], 0, 0)
    minx, miny, maxx, maxy = box
    width = maxx - minx + 1
    height = maxy - miny + 1
    return (bitmap_from_pixels(pixels, width, height, minx, miny), width, height)


def rasterize_board(segments, cells, supersample=DEFAULT_SUPERSAMPLE, board_cells=BOARD_SIZE):
    side = board_cells * supersample
    pixels = lit_pixels_from_segments(segments, supersample)
    pixels |= lit_pixels_from_cells(cells, supersample)
    return bitmap_from_pixels(pixels, side, side)


def board_width(supersample=DEFAULT_SUPERSAMPLE, board_cells=BOARD_SIZE):
    return board_cells * supersample


def popcount(rows):
    return sum(row.bit_count() for row in rows)


def embed(rows, offset_x, offset_y, board_width_px, board_height_px):
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


def bitmap_bbox(rows, width):
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


def local_ink(rows, x0, y0, x1, y1):
    mask = (1 << (x1 - x0)) - 1
    return sum(((rows[y] >> x0) & mask).bit_count() for y in range(y0, y1))


def traversed_cells(segments):
    cells = set()
    for a, b in segments:
        cells.update(_bresenham(a[0], a[1], b[0], b[1]))
    return cells
