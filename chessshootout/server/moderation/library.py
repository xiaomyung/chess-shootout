import json
from dataclasses import dataclass, field
from importlib import resources

from chessshootout.server.moderation import geometry


HARD_BLOCK = "HARD_BLOCK"
SOFT_FLAG = "SOFT_FLAG"
DISABLED = "DISABLED"

VECTOR = "vector"
RASTER = "raster"
BOTH = "both"

_PATTERNS = None
_WORDS = None


@dataclass(frozen=True)
class VectorVariant:
    edges: frozenset
    width: int
    height: int


@dataclass(frozen=True)
class RasterVariant:
    rows: tuple
    width: int
    height: int
    ink: int


@dataclass
class CompiledPattern:
    id: str
    tier: int
    action: str
    channel: str
    transform_group: str
    scale_min: int
    scale_max: int
    coverage_threshold: float
    iou_threshold: float
    supersample: int
    vector_variants: tuple
    raster_variants: tuple
    digits: str = ""
    provenance: dict = field(default_factory=dict)


@dataclass
class WordEntry:
    text: str
    lang: str
    action: str
    provenance: dict = field(default_factory=dict)


def _load_json(name):
    resource = resources.files("chessshootout.server.moderation").joinpath(name)
    with resource.open(encoding="utf-8") as source:
        return json.load(source)


def _parse_segments(raw):
    return [((a[0], a[1]), (b[0], b[1])) for a, b in raw]


def _parse_grid(rows):
    cells = set()
    for cy, row in enumerate(rows):
        for cx, ch in enumerate(row):
            if ch == "#":
                cells.add((cx, cy))
    return cells


def _scale_cells(cells, factor):
    expanded = set()
    for cx, cy in cells:
        for i in range(factor):
            for j in range(factor):
                expanded.add((cx * factor + i, cy * factor + j))
    return expanded


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
            normalized, width, height = geometry.normalize_edges(edges)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            variants.append(VectorVariant(normalized, width, height))
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
        tier=entry["tier"],
        action=entry["action"],
        channel=channel,
        transform_group=entry["transform_group"],
        scale_min=scale_min,
        scale_max=scale_max,
        coverage_threshold=entry["coverage_threshold"],
        iou_threshold=entry["iou_threshold"],
        supersample=supersample,
        vector_variants=vector_variants,
        raster_variants=raster_variants,
        digits=entry.get("digits", ""),
        provenance=entry.get("provenance", {}),
    )


def preload(supersample=geometry.DEFAULT_SUPERSAMPLE):
    global _PATTERNS, _WORDS
    if _PATTERNS is not None:
        return
    pattern_data = _load_json("patterns.json")
    compiled = tuple(_compile_pattern(entry, supersample)
                     for entry in pattern_data["patterns"])
    word_data = _load_json("words.json")
    words = tuple(WordEntry(
        text=entry["text"],
        lang=entry["lang"],
        action=entry["action"],
        provenance=entry.get("provenance", {}),
    ) for entry in word_data["words"])
    _PATTERNS = compiled
    _WORDS = words


def compiled_patterns():
    preload()
    return _PATTERNS


def enabled_patterns():
    preload()
    return tuple(pattern for pattern in _PATTERNS if pattern.action != DISABLED)


def word_list():
    preload()
    return _WORDS
