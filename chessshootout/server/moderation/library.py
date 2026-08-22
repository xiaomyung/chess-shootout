import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, cast

from chessshootout.server.moderation import geometry


HARD_BLOCK = "HARD_BLOCK"
DISABLED = "DISABLED"

VECTOR = "vector"
RASTER = "raster"
BOTH = "both"

_PATTERNS = None


@dataclass(frozen=True)
class VectorVariant:
    """
    One compiled drawing of a banned symbol for the arrow channel: the exact
    single-square edges that drawing lays down, anchored at the origin. A single
    authored pattern compiles into many of these, one per rotation, reflection
    and size
    """

    edges: frozenset[tuple[tuple[int, int], tuple[int, int]]]


@dataclass(frozen=True)
class RasterVariant:
    """
    One compiled drawing of a banned symbol for the pixel channel: a small
    bitmap trimmed to its own ink, with its size and how many pixels it lights.
    That ink count is what coverage is measured against
    """

    rows: tuple[int, ...]
    width: int
    height: int
    ink: int


@dataclass
class CompiledPattern:
    """
    One entry of the authored symbol library ready to be matched: what it is
    called, what happens when it trips, which channels it matches on, how much
    of it must be present to count, and every compiled drawing of it. Entries
    marked DISABLED stay in the library as reference but never match
    """

    id: str
    action: str
    channel: str
    coverage_threshold: float
    iou_threshold: float
    supersample: int
    vector_variants: tuple[VectorVariant, ...]
    raster_variants: tuple[RasterVariant, ...]


def _load_json(name: str) -> dict[str, Any]:
    """
    Read one data file that ships inside the moderation package. Going through
    the package resources rather than a filesystem path is what keeps the symbol
    library readable from a packaged build as well as from a source checkout

    :param name: file name beside this module, e.g. patterns.json.
    :returns: the parsed JSON document.
    """
    resource = resources.files("chessshootout.server.moderation").joinpath(name)
    with resource.open(encoding="utf-8") as source:
        return cast(dict[str, Any], json.load(source))


def _parse_segments(
        raw: list[list[list[int]]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """
    Read a pattern authored as strokes into the point pairs the geometry helpers
    work with. Authored coordinates are lattice points in the same (col, row)
    space a drawn arrow lands in

    :param raw: stroke list from patterns.json, each stroke a pair of [col, row].
    :returns: the strokes as (start, end) lattice-point pairs.
    """
    return [((a[0], a[1]), (b[0], b[1])) for a, b in raw]


def _parse_grid(rows: list[str]) -> set[tuple[int, int]]:
    """
    Read a pattern authored as ASCII art into the squares it fills, where a hash
    marks a filled square. This is how symbols made of highlighted squares are
    written down in the library

    :param rows: art rows from patterns.json, top row first.
    :returns: the filled squares as (col, row) lattice points.
    """
    return {(cx, cy) for cy, row in enumerate(rows)
            for cx, ch in enumerate(row) if ch == "#"}


def _scale_cells(cells: set[tuple[int, int]], factor: int) -> set[tuple[int, int]]:
    """
    Magnify a filled-square drawing, every square becoming a solid block. This
    is how one authored grid also covers the same symbol drawn larger on the
    board

    :param cells: filled squares as (col, row) lattice points.
    :param factor: whole-number magnification; 1 leaves the drawing as authored.
    :returns: the filled squares of the magnified drawing.
    """
    return {(cx * factor + i, cy * factor + j)
            for cx, cy in cells for i in range(factor) for j in range(factor)}


def _vector_variants(segments: list[tuple[tuple[int, int], tuple[int, int]]],
                     ops: tuple[str, ...], scale_min: int,
                     scale_max: int) -> tuple[VectorVariant, ...]:
    """
    Compile one authored stroke pattern into every arrow-channel drawing of it:
    each symmetry of the pattern at each allowed size. Symmetries that come out
    identical are kept once, so the matcher never retries the same shape

    :param segments: authored strokes as (start, end) lattice-point pairs.
    :param ops: DIHEDRAL keys the pattern is allowed to be turned or mirrored by.
    :param scale_min: smallest magnification to compile.
    :param scale_max: largest magnification to compile, inclusive.
    :returns: the distinct compiled drawings.
    """
    legs = geometry.segment_legs(segments)
    seen = set()
    variants = []
    for op_key in ops:
        for factor in range(scale_min, scale_max + 1):
            scaled = geometry.scale_segments(legs, factor)
            transformed = geometry.transform_segments(scaled, op_key)
            edges = set()
            for a, b in transformed:
                unit = geometry.segment_unit_edges(a, b)
                if unit:
                    edges |= unit
            normalized = geometry.normalize_edges(edges)[0]
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            variants.append(VectorVariant(normalized))
    return tuple(variants)


def _raster_variant_from_cells(cells: set[tuple[int, int]], op_key: str, factor: int,
                               supersample: int) -> tuple[list[int], int, int]:
    """
    Turn one symmetry and size of a filled-square pattern into the bitmap the
    pixel channel matches on

    :param cells: authored filled squares as (col, row) lattice points.
    :param op_key: DIHEDRAL key naming the rotation or reflection.
    :param factor: whole-number magnification.
    :param supersample: pixels per square along one side.
    :returns: the bitmap rows trimmed to their ink, plus width and height in pixels.
    """
    scaled = _scale_cells(cells, factor)
    transformed = {geometry.apply_op((cx, cy), op_key) for cx, cy in scaled}
    pixels = geometry.lit_pixels_from_cells(transformed, supersample)
    return geometry.normalized_bitmap_from_pixels(pixels)


def _raster_variant_from_segments(
        segments: list[tuple[tuple[int, int], tuple[int, int]]], op_key: str,
        factor: int, supersample: int) -> tuple[list[int], int, int]:
    """
    Turn one symmetry and size of a stroke pattern into a bitmap as well, so a
    symbol authored as arrows is still caught when a player draws it out of
    highlighted squares instead

    :param segments: authored strokes as (start, end) lattice-point pairs.
    :param op_key: DIHEDRAL key naming the rotation or reflection.
    :param factor: whole-number magnification.
    :param supersample: pixels per square along one side.
    :returns: the bitmap rows trimmed to their ink, plus width and height in pixels.
    """
    scaled = geometry.scale_segments(geometry.segment_legs(segments), factor)
    transformed = geometry.transform_segments(scaled, op_key)
    pixels = geometry.lit_pixels_from_segments(transformed, supersample)
    return geometry.normalized_bitmap_from_pixels(pixels)


def _raster_variants(cells: set[tuple[int, int]],
                     segments: list[tuple[tuple[int, int], tuple[int, int]]],
                     ops: tuple[str, ...], scale_min: int, scale_max: int,
                     supersample: int) -> tuple[RasterVariant, ...]:
    """
    Compile one authored pattern into every pixel-channel drawing of it: each
    symmetry at each allowed size, taken from the pattern's squares when it has
    them and from its strokes otherwise. Duplicate bitmaps are kept once

    :param cells: authored filled squares; empty when the pattern is strokes only.
    :param segments: authored strokes, used when there are no filled squares.
    :param ops: DIHEDRAL keys the pattern is allowed to be turned or mirrored by.
    :param scale_min: smallest magnification to compile.
    :param scale_max: largest magnification to compile, inclusive.
    :param supersample: pixels per square along one side.
    :returns: the distinct compiled bitmaps.
    """
    seen = set()
    variants = []
    for op_key in ops:
        for factor in range(scale_min, scale_max + 1):
            if cells:
                rows, width, height = _raster_variant_from_cells(cells, op_key, factor, supersample)
            else:
                rows, width, height = _raster_variant_from_segments(
                    segments, op_key, factor, supersample)
            key = tuple(rows)
            if not rows or key in seen:
                continue
            seen.add(key)
            variants.append(RasterVariant(key, width, height, geometry.popcount(rows)))
    return tuple(variants)


def _compile_pattern(entry: dict[str, Any], supersample: int) -> CompiledPattern:
    """
    Build one library entry into its matchable form, compiling whichever
    channels the entry declares. A pattern authored either as strokes or as
    ASCII art arrives here and leaves as ready-to-match drawings

    :param entry: one raw pattern object from patterns.json.
    :param supersample: pixels per square along one side.
    :returns: the compiled pattern.
    """
    channel = entry["channel"]
    ops = geometry.TRANSFORM_GROUPS[entry["transform_group"]]
    scale_min = entry["scale_min"]
    scale_max = entry["scale_max"]
    segments = _parse_segments(entry["segments"]) if "segments" in entry else []
    cells = _parse_grid(entry["grid"]) if "grid" in entry else set()
    vector_variants: tuple[VectorVariant, ...] = ()
    raster_variants: tuple[RasterVariant, ...] = ()
    if channel in (VECTOR, BOTH) and segments:
        vector_variants = _vector_variants(segments, ops, scale_min, scale_max)
    if channel in (RASTER, BOTH):
        raster_variants = _raster_variants(
            cells, segments, ops, scale_min, scale_max, supersample)
    return CompiledPattern(
        id=entry["id"],
        action=entry["action"],
        channel=channel,
        coverage_threshold=entry["coverage_threshold"],
        iou_threshold=entry["iou_threshold"],
        supersample=supersample,
        vector_variants=vector_variants,
        raster_variants=raster_variants,
    )


def preload(supersample: int = geometry.DEFAULT_SUPERSAMPLE) -> None:
    """
    Build the whole symbol library once and keep it for the life of the process.
    Compiling every symmetry and size is the expensive part of moderation, so it
    happens on the first check and never again -- later calls, including ones
    asking for a different resolution, leave the built library alone

    :param supersample: pixels per square along one side, used only on the build.
    """
    global _PATTERNS
    if _PATTERNS is not None:
        return
    pattern_data = _load_json("patterns.json")
    _PATTERNS = tuple(_compile_pattern(entry, supersample)
                      for entry in pattern_data["patterns"])


def compiled_patterns() -> tuple[CompiledPattern, ...]:
    """
    Hand back every entry of the symbol library, disabled ones included,
    building it first if needed. Disabled entries are kept visible here because
    they are documentation of what was deliberately not switched on

    :returns: every compiled pattern in library order.
    """
    preload()
    return cast(tuple[CompiledPattern, ...], _PATTERNS)


def enabled_patterns() -> tuple[CompiledPattern, ...]:
    """
    Hand back only the entries a drawing is actually checked against, building
    the library first if needed. Both matching stages iterate this list, so an
    entry switched off in patterns.json stops costing anything

    :returns: the compiled patterns whose action is not DISABLED.
    """
    preload()
    return tuple(pattern for pattern in cast(tuple[CompiledPattern, ...], _PATTERNS)
                 if pattern.action != DISABLED)
