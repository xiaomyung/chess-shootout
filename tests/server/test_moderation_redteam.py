"""Deterministic adversarial red-team harness for the v2 moderation detector.

For each enabled HARD_BLOCK base symbol the generator emits a large family of
variations -- stroke repartitions (a segment split into unit arrows), every D4
rotation/mirror, integer scales that fit the board, one-cell-dropped forms with a
matching context cell, arrow<->highlight media swaps, decoy-padded forms, and
thickness tweaks -- runs detect() on each, and computes the ESCAPE RATE: the
fraction of constructions that returned CLEAN when they should have blocked.

Symbols with strong invariants (swastika, SS) are held to a low escape bound.
Every construction that DOES escape today is frozen into
KNOWN_ESCAPES so a regression that lets a currently-blocked form slip through is
caught immediately. The generator is seeded (random.Random) and touches no wall
clock, so the escape set is stable across runs and machines.

Coordinate convention (col,row)=(x,y), origin top-left.
"""

import random

from chessshootout.server.moderation import detector, geometry
from tests.server import moderation_helpers as M


SWASTIKA_BASE_IDS = ["swastika_axis", "swastika_axis7", "swastika_knight4",
                     "swastika_raster5", "swastika_raster5_hook1",
                     "swastika_raster7", "swastika_raster7_thin",
                     "swastika_raster7_hook1"]
SS_BASE_IDS = ["ss_bolts_vector", "ss_bolts_raster"]


def _blocks(arrows, highlights, context=()):
    return detector.detect(arrows, highlights, context=context).kind == detector.BLOCKED


def _cells_of(entry):
    return M.grid_cells(entry["grid"]) if "grid" in entry else None


def _segments_of(entry):
    return [((a[0], a[1]), (b[0], b[1])) for a, b in entry["segments"]] \
        if "segments" in entry else None


def _fits(points):
    return all(0 <= x < 8 and 0 <= y < 8 for x, y in points)


def _shift(points):
    minx = min(p[0] for p in points)
    miny = min(p[1] for p in points)
    return [(p[0] - minx, p[1] - miny) for p in points]


def _vector_constructions(entry, rng):
    segments = _segments_of(entry)
    if segments is None:
        return
    for op_key in geometry.D4_ALL:
        for factor in (1, 2, 3):
            arrows = M.transformed_vector_arrows(entry["segments"], op_key, factor)
            if arrows is not None:
                yield ("d4_scale", arrows, [], ())
    # stroke repartition: every authored segment split into unit-edge arrows
    edges = set()
    for a, b in segments:
        unit = geometry.segment_unit_edges(a, b)
        if unit:
            edges |= unit
    unit_arrows = [(M.coord(*p), M.coord(*q)) for p, q in sorted(edges)]
    yield ("unit_split", unit_arrows, [], ())
    yield ("direction_flip", [(b, a) for a, b in unit_arrows], [], ())
    # decoy padding
    decoys = [("a1", "a3"), ("h8", "h6"), ("b7", "d7")]
    yield ("decoy_pad", M.arrows_from_segments(entry["segments"]) + decoys, [], ())


def _raster_constructions(entry, rng):
    cells = _cells_of(entry)
    if cells is None:
        return
    for op_key in geometry.D4_ALL:
        for factor in (1, 2):
            highlights = M.transformed_raster_highlights(cells, op_key, factor)
            if highlights is not None:
                yield ("d4_scale", [], highlights, ())
    highlights = M.highlights_from_cells(cells)
    # one-cell-dropped + a matching context cell that completes it
    for drop in range(len(cells)):
        kept = cells[:drop] + cells[drop + 1:]
        yield ("drop_plus_context", [],
               M.highlights_from_cells(kept),
               M.highlights_from_cells([cells[drop]]))
    # media swap: one row rendered as arrows, the rest as highlights
    rows = sorted({y for _, y in cells})
    swap_row = rows[len(rows) // 2]
    row_cells = sorted(c for c in cells if c[1] == swap_row)
    if len(row_cells) >= 2:
        arrows = [(M.coord(*row_cells[0]), M.coord(*row_cells[-1]))]
        rest = [c for c in cells if c[1] != swap_row]
        yield ("media_swap", arrows, M.highlights_from_cells(rest), ())
    # decoy blob far from the symbol
    blob = [(x, y) for x in range(2) for y in range(6, 8)]
    yield ("decoy_blob", [], M.highlights_from_cells(cells + blob), ())
    # thickness tweak: dilate every cell right/down where it fits
    thick = set()
    for x, y in cells:
        for dx in (0, 1):
            for dy in (0, 1):
                thick.add((x + dx, y + dy))
    thick = _shift(sorted(thick))
    if _fits(thick):
        yield ("thicken", [], M.highlights_from_cells(thick), ())


def _run_symbol(base_ids, extra_gen=None):
    rng = random.Random(0xC0FFEE)
    total = 0
    escaped = []
    for pid in base_ids:
        entry = M.entry_by_id(pid)
        for label, arrows, highlights, context in _vector_constructions(entry, rng):
            total += 1
            if not _blocks(arrows, highlights, context):
                escaped.append((pid, label))
        for label, arrows, highlights, context in _raster_constructions(entry, rng):
            total += 1
            if not _blocks(arrows, highlights, context):
                escaped.append((pid, label))
    if extra_gen is not None:
        for label, arrows, highlights, context in extra_gen(rng):
            total += 1
            if not _blocks(arrows, highlights, context):
                escaped.append((label, "escape"))
    return total, escaped


# Frozen escape ledger: constructions that the current detector does NOT block.
# An empty set is the goal for a class; any addition here is a deliberate,
# reviewed admission that the construction slips through today.
KNOWN_ESCAPES = {
    # Dilating the minimal 5x5 swastika collapses its arms into a 6x6 blob that
    # reads below every template's coverage; the 7x7/8x8 authored bold template
    # covers the legible thick-stroke case, so this marginal form is left open.
    "swastika": {"swastika_raster5:thicken"},
    "ss": set(),
}

ESCAPE_BOUNDS = {
    "swastika": 0.05,
    "ss": 0.05,
}


def _check(name, total, escaped):
    frozen = KNOWN_ESCAPES[name]
    signatures = {"%s:%s" % (a, b) for a, b in escaped}
    unexpected = signatures - frozen
    stale = frozen - signatures
    assert not unexpected, (
        f"{name}: NEW escapes not in KNOWN_ESCAPES: {sorted(unexpected)}")
    assert not stale, (
        f"{name}: KNOWN_ESCAPES lists constructions that now block "
        f"(tighten the ledger): {sorted(stale)}")
    rate = len(escaped) / total if total else 0.0
    assert rate <= ESCAPE_BOUNDS[name], (
        f"{name}: escape rate {rate:.3f} over {total} constructions exceeds "
        f"bound {ESCAPE_BOUNDS[name]}")


def test_redteam_swastika_escape_rate_bounded():
    total, escaped = _run_symbol(SWASTIKA_BASE_IDS)
    _check("swastika", total, escaped)


def test_redteam_ss_escape_rate_bounded():
    total, escaped = _run_symbol(SS_BASE_IDS)
    _check("ss", total, escaped)
