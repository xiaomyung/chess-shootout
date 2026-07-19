import json
from dataclasses import dataclass
from importlib import resources

from chessshootout.server.moderation import geometry


HARD_BLOCK = "HARD_BLOCK"
DISABLED = "DISABLED"

VECTOR = "vector"
RASTER = "raster"
BOTH = "both"

_PATTERNS = None


@dataclass(frozen=True)
class VectorVariant:
    edges: frozenset


@dataclass(frozen=True)
class RasterVariant:
    rows: tuple
    width: int
    height: int
    ink: int


@dataclass
class CompiledPattern:
    id: str
    action: str
    channel: str
    coverage_threshold: float
    iou_threshold: float
    supersample: int
    vector_variants: tuple
    raster_variants: tuple


def _load_json(name):
    resource = resources.files("chessshootout.server.moderation").joinpath(name)
    with resource.open(encoding="utf-8") as source:
        return json.load(source)


def _parse_segments(raw):
    return [((a[0], a[1]), (b[0], b[1])) for a, b in raw]


def _parse_grid(rows):
    return {(cx, cy) for cy, row in enumerate(rows)
            for cx, ch in enumerate(row) if ch == "#"}


def _scale_cells(cells, factor):
    return {(cx * factor + i, cy * factor + j)
            for cx, cy in cells for i in range(factor) for j in range(factor)}


def _vector_variants(segments, ops, scale_min, scale_max):
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


def _raster_variant_from_cells(cells, op_key, factor, supersample):
    scaled = _scale_cells(cells, factor)
    transformed = {geometry.apply_op((cx, cy), op_key) for cx, cy in scaled}
    pixels = geometry.lit_pixels_from_cells(transformed, supersample)
    return geometry.normalized_bitmap_from_pixels(pixels)


def _raster_variant_from_segments(segments, op_key, factor, supersample):
    scaled = geometry.scale_segments(geometry.segment_legs(segments), factor)
    transformed = geometry.transform_segments(scaled, op_key)
    pixels = geometry.lit_pixels_from_segments(transformed, supersample)
    return geometry.normalized_bitmap_from_pixels(pixels)


def _raster_variants(cells, segments, ops, scale_min, scale_max, supersample):
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


def _compile_pattern(entry, supersample):
    channel = entry["channel"]
    ops = geometry.TRANSFORM_GROUPS[entry["transform_group"]]
    scale_min = entry["scale_min"]
    scale_max = entry["scale_max"]
    segments = _parse_segments(entry["segments"]) if "segments" in entry else []
    cells = _parse_grid(entry["grid"]) if "grid" in entry else set()
    vector_variants = ()
    raster_variants = ()
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


def preload(supersample=geometry.DEFAULT_SUPERSAMPLE):
    global _PATTERNS
    if _PATTERNS is not None:
        return
    pattern_data = _load_json("patterns.json")
    _PATTERNS = tuple(_compile_pattern(entry, supersample)
                      for entry in pattern_data["patterns"])


def compiled_patterns():
    preload()
    return _PATTERNS


def enabled_patterns():
    preload()
    return tuple(pattern for pattern in _PATTERNS if pattern.action != DISABLED)
