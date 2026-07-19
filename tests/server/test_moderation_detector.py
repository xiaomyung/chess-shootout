"""Pure-detector trip matrix for chessshootout.server.moderation.

Every ENABLED pattern must trip across a sample of its D4 orbit x scale range x
translations, and the full evasion matrix (stroke split/merge, direction flip,
decoys against BOTH channels, slow-draw, mixed media, multi/cross-color union,
negative space, chirality, integer scaling) must survive as individually-named
cases. Threshold edges bracket the 85% vector-coverage boundary.

Review-hardening rationale (post-review fixes pinned here, not in production):
- Raster IoU is LOCAL (placement bbox + one-cell margin ring): a global IoU let
  any decoy ink anywhere on the board sink the ratio and hide a full raster
  symbol (test_evasion_raster_decoy_blob_still_trips).
- The raster board is arrow-DILATED (arrow-traversed cells count as filled), so
  a symbol drawn half in arrows and half in highlights still reaches template
  coverage -- but a pure-arrow cluster can never raster-match a cell template
  because a highlight-share floor (RASTER_HIGHLIGHT_SHARE of pattern ink must
  come from real highlight cells) guards the channel; pure-arrow symbols belong
  to the vector channel.
- Pattern segments compile through the same knight-L polyline decomposition the
  client renders (geometry.segment_legs). The elbow rule is "long leg first",
  which is D4-equivariant, so decompose-then-transform equals
  transform-then-decompose.
- Stage-4 runs on the maximal C4-invariant SUBSET about each candidate center
  (decoy edges die in the rotation intersection), so one throwaway arrow cannot
  switch the novel-variant net off.

Coordinate convention (col,row)=(x,y), origin top-left; a lattice point (col,row)
is a square center. Constructions come from each pattern's OWN segments/grid.
"""

import pytest

from chessshootout.server.moderation import detector, geometry
from tests.server import moderation_helpers as M


SWASTIKA_SCREENSHOTS = {
    "v1_hooks_only_pinwheel": [
        [[3, 3], [4, 1]], [[3, 3], [5, 4]], [[3, 3], [2, 5]], [[3, 3], [1, 2]],
    ],
    "v2_cross_plus_tip_hooks": [
        [[3, 3], [3, 1]], [[3, 3], [5, 3]], [[3, 3], [3, 5]], [[3, 3], [1, 3]],
        [[3, 1], [5, 1]], [[5, 3], [5, 5]], [[3, 5], [1, 5]], [[1, 3], [1, 1]],
    ],
    "v3_overlapping_straight_arrow_pinwheel": [
        [[3, 1], [3, 3]], [[3, 3], [3, 5]], [[1, 3], [3, 3]], [[3, 3], [5, 3]],
        [[3, 1], [4, 1]], [[5, 3], [5, 4]], [[3, 5], [2, 5]], [[1, 3], [1, 2]],
    ],
    "v4_cross_plus_partial_hooks": [
        [[3, 1], [3, 5]], [[1, 3], [5, 3]],
        [[3, 1], [5, 1]], [[5, 3], [5, 5]], [[3, 5], [1, 5]],
    ],
}


def _assert_trips(verdict, *, label=""):
    assert verdict.kind == detector.BLOCKED, (
        f"{label}: expected {detector.BLOCKED}, got {verdict.kind} "
        f"id={verdict.pattern_id}"
    )


def _assert_clean(verdict, label=""):
    assert verdict.kind == detector.CLEAN, (
        f"{label}: expected clean, got {verdict.kind} id={verdict.pattern_id}"
    )


def _swastika_axis_unit_arrows():
    entry = M.entry_by_id("swastika_axis")
    edges = set()
    for a, b in entry["segments"]:
        edges |= geometry.segment_unit_edges(tuple(a), tuple(b))
    ordered = sorted(edges)
    return [(M.coord(*p), M.coord(*q)) for p, q in ordered]


# --- every enabled pattern trips across D4 x scale x translation --------------

ENABLED_IDS = [entry["id"] for entry in M.enabled_entries()]


@pytest.mark.parametrize("pattern_id", ENABLED_IDS)
def test_enabled_pattern_trips_across_orbit(pattern_id):
    entry = M.entry_by_id(pattern_id)
    group = geometry.TRANSFORM_GROUPS[entry["transform_group"]]
    is_vector = "segments" in entry and entry["channel"] in ("vector", "both")
    samples = 0
    for op_key in group:
        for factor in range(entry["scale_min"], entry["scale_max"] + 1):
            for dx, dy in ((0, 0), (1, 0), (0, 1)):
                if is_vector:
                    arrows = M.transformed_vector_arrows(
                        entry["segments"], op_key, factor, dx, dy)
                    if arrows is None:
                        continue
                    verdict = detector.detect(arrows, [])
                else:
                    cells = M.grid_cells(entry["grid"])
                    highlights = M.transformed_raster_highlights(
                        cells, op_key, factor, dx, dy)
                    if highlights is None:
                        continue
                    verdict = detector.detect([], highlights)
                samples += 1
                _assert_trips(verdict,
                              label=f"{pattern_id} {op_key} x{factor} +{dx},{dy}")
    assert samples > 0, f"{pattern_id}: no on-board orbit sample fit the board"


# --- evasion matrix (individually named) --------------------------------------

def test_evasion_stroke_split_unit_arrows_trip():
    verdict = detector.detect(_swastika_axis_unit_arrows(), [])
    _assert_trips(verdict, label="stroke split")


def test_evasion_stroke_merge_segment_arrows_trip():
    entry = M.entry_by_id("swastika_axis")
    verdict = detector.detect(M.arrows_from_segments(entry["segments"]), [])
    _assert_trips(verdict, label="stroke merge")


def test_evasion_direction_flip_trips():
    entry = M.entry_by_id("swastika_axis")
    forward = M.arrows_from_segments(entry["segments"])
    flipped = [(b, a) for a, b in forward]
    _assert_trips(detector.detect(flipped, []), label="direction flip")


def test_evasion_decoy_arrows_still_trip():
    entry = M.entry_by_id("swastika_axis")
    base = M.arrows_from_segments(entry["segments"])
    decoyed = base + [("a1", "a4"), ("h1", "h4"), ("b7", "g7"), ("g1", "f3")]
    _assert_trips(detector.detect(decoyed, []), label="decoys")


def test_evasion_raster_decoy_blob_still_trips():
    # A 20-cell decoy blob sank the OLD global IoU below threshold and hid a
    # fully-drawn highlight swastika; local (bbox+margin) IoU ignores far ink.
    entry = M.entry_by_id("swastika_raster5")
    symbol = set(M.grid_cells(entry["grid"]))
    blob = {(x, y) for x in range(4) for y in range(5, 8)}
    blob |= {(x, 7) for x in range(4, 8)} | {(7, 6), (6, 6), (5, 6), (7, 5)}
    verdict = detector.detect([], M.highlights_from_cells(sorted(symbol | blob)))
    _assert_trips(verdict, label="raster decoy blob")
    assert verdict.pattern_id == "swastika_raster5"


def _row_run_arrows(cells, rows):
    arrows = []
    leftover = []
    for y in rows:
        row_cells = sorted(c for c in cells if c[1] == y)
        start = prev = row_cells[0]
        runs = []
        for cell in row_cells[1:]:
            if cell[0] == prev[0] + 1:
                prev = cell
            else:
                runs.append((start, prev))
                start = prev = cell
        runs.append((start, prev))
        for a, b in runs:
            if a == b:
                leftover.append(a)
            else:
                arrows.append((M.coord(*a), M.coord(*b)))
    return arrows, leftover


def test_evasion_half_arrow_half_highlight_trips():
    # Two full swastika arms drawn as arrows, the rest as highlights: neither
    # channel alone reaches coverage; the dilated raster board unifies them.
    entry = M.entry_by_id("swastika_raster5")
    cells = set(M.grid_cells(entry["grid"]))
    arrows, leftover = _row_run_arrows(cells, (0, 4))
    rest = [c for c in cells if c[1] not in (0, 4)] + leftover
    verdict = detector.detect(arrows, M.highlights_from_cells(sorted(rest)))
    _assert_trips(verdict, label="half arrows half highlights")
    assert verdict.pattern_id == "swastika_raster5"


def test_evasion_scaled_minimal_swastika_x3_trips():
    # A 3x minimal swastika spans 6 and fits the board; scale_max must reach it
    # or drawing the symbol bigger is a free evasion.
    entry = M.entry_by_id("swastika_axis_min")
    arrows = M.transformed_vector_arrows(entry["segments"], "r0", 3, 0, 0)
    assert arrows is not None
    verdict = detector.detect(arrows, [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == "swastika_axis_min"


# Long axis arms with rotationally-consistent DIAGONAL hooks: C4-chiral but
# matching no library template (the axis-hook long-arm form is now the
# swastika_axis7 template and hard-blocks; this stays the heuristic's case).
NOVEL_PINWHEEL = [
    [[3, 3], [3, 0]], [[3, 0], [5, 2]], [[3, 3], [6, 3]], [[6, 3], [4, 5]],
    [[3, 3], [3, 6]], [[3, 6], [1, 4]], [[3, 3], [0, 3]], [[0, 3], [2, 1]],
]


def test_evasion_novel_pinwheel_with_decoy_stays_suspect():
    # Long-armed C4-chiral pinwheel not in the library: the stage-4 net must
    # keep flagging it when a throwaway decoy arrow is added (subset core).
    base = M.arrows_from_segments(NOVEL_PINWHEEL)
    alone = detector.detect(base, [])
    assert alone.kind == detector.SUSPECT
    assert alone.pattern_id == detector.HEURISTIC_ID
    decoyed = detector.detect(base + [("a1", "b1")], [])
    assert decoyed.kind == detector.SUSPECT
    assert decoyed.pattern_id == detector.HEURISTIC_ID


def test_evasion_slow_draw_trips_at_completing_mark():
    unit_arrows = _swastika_axis_unit_arrows()
    accumulated = []
    trip_index = None
    for index, arrow in enumerate(unit_arrows, start=1):
        accumulated.append(arrow)
        verdict = detector.detect(list(accumulated), [], changed=arrow)
        if verdict.kind == detector.BLOCKED:
            trip_index = index
            break
    # v2 coverage floor is 0.78: the 12th axis edge completes >=78% of the
    # overlapping 12-edge swastika_knight4 template (10/12), so the symbol trips
    # one edge earlier than the 13/16 axis-proper boundary.
    assert trip_index == 12, f"slow-draw tripped at {trip_index}, expected 12 (>=78%)"


def test_evasion_slow_draw_below_threshold_stays_clean():
    unit_arrows = _swastika_axis_unit_arrows()
    eleven = unit_arrows[:11]
    verdict = detector.detect(eleven, [], changed=eleven[-1])
    _assert_clean(verdict, "slow-draw 11/16")


def test_evasion_mixed_media_arrow_stroke_plus_highlights_trips():
    entry = M.entry_by_id("swastika_raster5")
    cells = M.grid_cells(entry["grid"])
    row = sorted(c for c in cells if c[1] == 2)
    arrow_cells = row[:2]
    arrows = [(M.coord(*arrow_cells[0]), M.coord(*arrow_cells[-1]))]
    highlights = M.highlights_from_cells(
        [c for c in cells if c not in set(arrow_cells)])
    verdict = detector.detect(arrows, highlights)
    _assert_trips(verdict, label="mixed media")
    assert verdict.pattern_id == "swastika_raster5"


def test_evasion_multi_color_union_trips():
    entry = M.entry_by_id("swastika_axis")
    base = M.arrows_from_segments(entry["segments"])
    own, opp = base[:3], base[3:]
    arrows, highlights = detector.union_sides(own, [], opp, [])
    _assert_trips(detector.detect(arrows, highlights), label="multi-color union")


def test_evasion_cross_color_union_trips():
    entry = M.entry_by_id("ss_bolts_vector")
    base = M.arrows_from_segments(entry["segments"])
    side_a, side_b = base[:3], base[3:]
    # Neither side alone reaches coverage; only the union is a symbol.
    _assert_clean(detector.detect(side_a, []), "cross-color side A alone")
    _assert_clean(detector.detect(side_b, []), "cross-color side B alone")
    arrows, highlights = detector.union_sides(side_a, [], side_b, [])
    _assert_trips(detector.detect(arrows, highlights), label="cross-color union")


def test_evasion_negative_space_fill_complement_trips():
    entry = M.entry_by_id("swastika_raster5")
    symbol = set(M.grid_cells(entry["grid"]))
    everything = {(x, y) for x in range(8) for y in range(8)}
    complement = everything - symbol
    assert len(complement) > 32
    verdict = detector.detect([], M.highlights_from_cells(sorted(complement)))
    _assert_trips(verdict, label="negative space")
    assert verdict.pattern_id == "swastika_raster5"


def test_chirality_same_chirality_pinwheel_trips():
    verdict = detector.detect(M.arrows_from_segments(
        SWASTIKA_SCREENSHOTS["v1_hooks_only_pinwheel"]), [])
    _assert_trips(verdict, label="same-chirality pinwheel")
    assert verdict.pattern_id == "swastika_knight4"


def test_chirality_mirror_chirality_pinwheel_also_trips():
    mirror = [[[6 - a[0], a[1]], [6 - b[0], b[1]]]
              for a, b in SWASTIKA_SCREENSHOTS["v1_hooks_only_pinwheel"]]
    _assert_trips(detector.detect(M.arrows_from_segments(mirror), []),
                  label="mirror-chirality pinwheel")


def test_chirality_mixed_knight_fan_stays_clean():
    fan = [("d4", target) for target in
           ("e6", "f5", "f3", "e2", "c2", "b3", "b5", "c6")]
    _assert_clean(detector.detect(fan, []), "mixed 8-move knight fan")


# --- threshold edges ----------------------------------------------------------

def test_threshold_below_78_percent_does_not_trip():
    unit_arrows = _swastika_axis_unit_arrows()
    # 11 axis edges cover < 78% of every swastika template (incl. the 12-edge
    # knight4 the axis stroke set overlaps) -- below the v2 0.78 floor.
    _assert_clean(detector.detect(unit_arrows[:11], []), "11/16 coverage")


def test_threshold_at_least_78_percent_trips():
    unit_arrows = _swastika_axis_unit_arrows()
    # 12 axis edges complete >=78% of the overlapping 12-edge knight4 template.
    _assert_trips(detector.detect(unit_arrows[:12], []), label="12/16 coverage")


# --- user swastika screenshot fixtures ----------------------------------------

@pytest.mark.parametrize("name", sorted(SWASTIKA_SCREENSHOTS))
def test_swastika_screenshot_fixture_blocks(name):
    verdict = detector.detect(M.arrows_from_segments(SWASTIKA_SCREENSHOTS[name]), [])
    assert verdict.kind == detector.BLOCKED, f"{name}: {verdict.kind}"


def test_swastika_screenshot_receiver_mirrored_blocks():
    for name, arrows in SWASTIKA_SCREENSHOTS.items():
        mirrored = [[[7 - a[0], 7 - a[1]], [7 - b[0], 7 - b[1]]] for a, b in arrows]
        verdict = detector.detect(M.arrows_from_segments(mirrored), [])
        assert verdict.kind == detector.BLOCKED, f"{name} mirrored: {verdict.kind}"


# --- v2 hardening: free-square context ----------------------------------------

def test_free_square_context_completes_symbol_and_is_excluded_from_marks():
    # A swastika finished by the board's free last-move highlight: 14 user cells
    # sit below the raster5 coverage floor, the 3 context squares complete it,
    # and the context cells never surface in matched_highlights (not user marks).
    cells = M.grid_cells(M.entry_by_id("swastika_raster5")["grid"])
    context = M.highlights_from_cells(cells[:3])
    user = M.highlights_from_cells(cells[3:])
    assert detector.detect([], user).kind == detector.CLEAN
    verdict = detector.detect([], user, context=context)
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == "swastika_raster5"
    assert len(verdict.matched_highlights) == 14
    assert not any(c in verdict.matched_highlights for c in context)


def test_context_default_empty_is_backward_compatible():
    cells = M.grid_cells(M.entry_by_id("swastika_raster5")["grid"])
    user = M.highlights_from_cells(cells[3:])
    assert detector.detect([], user).kind == detector.CLEAN
    assert detector.detect([], user, context=()).kind == detector.CLEAN


# --- v2 hardening: authored hand-proportion swastika templates ----------------

def test_thin_stroke_hand_swastika_blocks():
    thin7 = ["..#.###", "..#...#", "..#...#", "#######",
             "#...#..", "#...#..", "###.#.."]
    verdict = detector.detect([], M.highlights_from_cells(M.grid_cells(thin7)))
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id.startswith("swastika_raster7_thin")


def test_bold_stroke_hand_swastika_blocks():
    bold8 = ["..######", "..######", "..##..##", "########",
             "########", "##..##..", "######..", "######.."]
    verdict = detector.detect([], M.highlights_from_cells(M.grid_cells(bold8)))
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id.startswith("swastika_raster8_bold")


def test_short_hook_cross_swastikas_block():
    # Proportion sweep found cross swastikas with 1-cell hooks fully CLEAN
    # (no arrows, so the C4 heuristic never sees them): arm2/hook1 and
    # arm3/hook1 highlight forms, plus the arm3 arrow forms that only reached
    # SUSPECT. Templates swastika_raster5_hook1/raster7_hook1/axis7 close them.
    hook5 = [".##..", "..#.#", "#####", "#.#..", "..##."]
    verdict = detector.detect([], M.highlights_from_cells(M.grid_cells(hook5)))
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == "swastika_raster5_hook1"
    hook7 = ["..##...", "...#...", "...#..#", "#######",
             "#..#...", "...#...", "...##.."]
    verdict = detector.detect([], M.highlights_from_cells(M.grid_cells(hook7)))
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == "swastika_raster7_hook1"
    arm3_hook2 = M.arrows_from_segments(M.entry_by_id("swastika_axis7")["segments"])
    verdict = detector.detect(arm3_hook2, [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == "swastika_axis7"


def test_short_hook_templates_leave_plain_crosses_clean():
    # The hook1 templates are cross-dominated; a plain highlighted plus, X, or
    # full file+rank cross must stay clean (0.85 floor requires the hooks).
    plus7 = [(x, 3) for x in range(7)] + [(3, y) for y in range(7) if y != 3]
    assert detector.detect([], M.highlights_from_cells(plus7)).kind == detector.CLEAN
    file_rank = [(4, y) for y in range(8)] + [(x, 3) for x in range(8) if x != 4]
    assert detector.detect([], M.highlights_from_cells(file_rank)).kind == detector.CLEAN
    cross_arrows = [("d1", "d8"), ("a4", "h4")]
    assert detector.detect(cross_arrows, []).kind == detector.CLEAN


# --- v2 hardening: C4-symmetry hard block for tight arrow swastikas ------------

TIGHT_ARROW_SWASTIKA = [
    ("b3", "c4"), ("d1", "c2"), ("d3", "b3"), ("d3", "d1"),
    ("d3", "d5"), ("d3", "f3"), ("d5", "e4"), ("f3", "e2"),
]


def test_c4_tight_arrow_swastika_hard_blocks():
    # A compact chiral pinwheel with diagonal hooks that matches NO template:
    # v1 relayed it as SUSPECT, v2 promotes a tight C4 core (>=12 doubled edges,
    # span<=4, bent tips, strict chirality) to a hard block.
    verdict = detector.detect(TIGHT_ARROW_SWASTIKA, [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == detector.HEURISTIC_ID
    assert verdict.matched_arrows


def test_c4_long_armed_pinwheel_stays_suspect():
    # The long-armed novel pinwheel (core span 6) is NOT tight: it must remain a
    # relayed SUSPECT, not a hard block.
    verdict = detector.detect(M.arrows_from_segments(NOVEL_PINWHEEL), [])
    assert verdict.kind == detector.SUSPECT
    assert verdict.pattern_id == detector.HEURISTIC_ID
