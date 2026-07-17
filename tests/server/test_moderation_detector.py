"""Pure-detector trip matrix for chessshootout.server.moderation.

Every ENABLED pattern must trip across a sample of its D4 orbit x scale range x
translations, and the full evasion matrix (stroke split/merge, direction flip,
decoys against BOTH channels, slow-draw, mixed media, multi/cross-color union,
negative space, temporal code memory, chirality, integer scaling) must survive
as individually-named cases. Threshold edges bracket the 85% vector-coverage
boundary.

Review-hardening rationale (post-review fixes pinned here, not in production):
- Raster IoU is LOCAL (placement bbox + one-cell margin ring): a global IoU let
  any decoy ink anywhere on the board sink the ratio and hide a full raster
  symbol (test_evasion_raster_decoy_blob_still_trips).
- The raster board is arrow-DILATED (arrow-traversed cells count as filled), so
  a symbol drawn half in arrows and half in highlights still reaches template
  coverage -- but a pure-arrow cluster can never raster-match a cell template
  because a highlight-share floor (RASTER_HIGHLIGHT_SHARE of pattern ink must
  come from real highlight cells) guards the channel; pure-arrow symbols belong
  to the vector channel and word OCR.
- Pattern segments compile through the same knight-L polyline decomposition the
  client renders (geometry.segment_legs). Before that fix, knight-vector arms in
  code_kkk_vector were silently dropped, degenerating the template to three bare
  vertical lines that hard-blocked any three aligned file arrows. The elbow rule
  is "long leg first", which is D4-equivariant, so decompose-then-transform
  equals transform-then-decompose.
- Stage-4 runs on the maximal C4-invariant SUBSET about each candidate center
  (decoy edges die in the rotation intersection), so one throwaway arrow cannot
  switch the novel-variant net off.

Word OCR end-to-end: glyph templates carry segment-skeleton constructions
(words.json letter_segments) rendered through the SAME arrow rasterization path
as drawn arrows (including knight-L decomposition), so arrow-written words are
matched at the supersampled resolution. The block-cell atlas remains for the
cell-resolution classifier layer.

Coordinate convention (col,row)=(x,y), origin top-left; a lattice point (col,row)
is a square center. Constructions come from each pattern's OWN segments/grid.
"""

import pytest

from chessshootout.server.moderation import detector, geometry
from tests.server import moderation_helpers as M


HUY_ARROW_FIXTURE = [
    [[0, 1], [2, 5]], [[2, 1], [0, 5]],
    [[3, 1], [4, 3]], [[5, 1], [4, 3]], [[4, 3], [4, 5]],
    [[6, 1], [6, 5]], [[7, 1], [7, 5]], [[6, 5], [7, 1]], [[6, 0], [7, 0]],
]

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


def _assert_trips(verdict, *, soft_ok=False, label=""):
    allowed = {detector.BLOCKED}
    if soft_ok:
        allowed.add(detector.SUSPECT)
    assert verdict.kind in allowed, (
        f"{label}: expected trip ({allowed}), got {verdict.kind} "
        f"id={verdict.pattern_id} suspect={verdict.suspect_ids}"
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
    soft = entry["action"] == "SOFT_FLAG"
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
                _assert_trips(verdict, soft_ok=soft,
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


NOVEL_PINWHEEL = [
    [[3, 3], [3, 0]], [[3, 0], [5, 0]], [[3, 3], [6, 3]], [[6, 3], [6, 5]],
    [[3, 3], [3, 6]], [[3, 6], [1, 6]], [[3, 3], [0, 3]], [[0, 3], [0, 1]],
]


def test_evasion_novel_pinwheel_with_decoy_stays_suspect():
    # Long-armed C4-chiral pinwheel not in the library: the stage-4 net must
    # keep flagging it when a throwaway decoy arrow is added (subset core).
    base = M.arrows_from_segments(NOVEL_PINWHEEL)
    alone = detector.detect(base, [])
    assert alone.kind == detector.SUSPECT
    assert detector.HEURISTIC_ID in alone.suspect_ids
    decoyed = detector.detect(base + [("a1", "b1")], [])
    assert decoyed.kind == detector.SUSPECT
    assert detector.HEURISTIC_ID in decoyed.suspect_ids


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
    assert trip_index == 14, f"slow-draw tripped at {trip_index}, expected 14 (>=85%)"


def test_evasion_slow_draw_below_threshold_stays_clean():
    unit_arrows = _swastika_axis_unit_arrows()
    thirteen = unit_arrows[:13]
    verdict = detector.detect(thirteen, [], changed=thirteen[-1])
    _assert_clean(verdict, "slow-draw 13/16")


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


def test_evasion_temporal_14_then_88_wipe_blocks():
    fourteen = M.highlights_from_cells(M.grid_cells(M.entry_by_id("code_14")["grid"]))
    eighty_eight = M.highlights_from_cells(
        M.grid_cells(M.entry_by_id("code_88")["grid"]))
    first = detector.detect([], fourteen)
    _assert_trips(first, soft_ok=True, label="temporal frame 1 (14)")
    assert "code_14" in first.codes_seen_out
    second = detector.detect([], eighty_eight, codes_seen=first.codes_seen_out)
    _assert_trips(second, label="temporal frame 2 (88 across wipe)")


def test_evasion_temporal_memory_threads_codes_seen():
    fourteen = M.highlights_from_cells(M.grid_cells(M.entry_by_id("code_14")["grid"]))
    three_eleven = M.highlights_from_cells(
        M.grid_cells(M.entry_by_id("code_311")["grid"]))
    first = detector.detect([], fourteen)
    assert first.codes_seen_out == frozenset({"code_14"})
    # Without memory the second code only flags; with memory it co-occurrence-blocks.
    without = detector.detect([], three_eleven)
    assert without.kind == detector.SUSPECT
    assert without.suspect_ids == ("code_311",)
    with_memory = detector.detect([], three_eleven, codes_seen=first.codes_seen_out)
    assert with_memory.kind == detector.BLOCKED
    assert with_memory.pattern_id == detector.CODE_COOCCURRENCE_ID
    assert set(with_memory.suspect_ids) == {"code_14", "code_311"}


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

def test_threshold_below_85_percent_does_not_trip():
    unit_arrows = _swastika_axis_unit_arrows()
    # 13 of 16 template edges == 81.25% < 0.85 needed.
    _assert_clean(detector.detect(unit_arrows[:13], []), "13/16 coverage")


def test_threshold_at_least_85_percent_trips():
    unit_arrows = _swastika_axis_unit_arrows()
    # 14 of 16 template edges == 87.5% >= 0.85 needed.
    _assert_trips(detector.detect(unit_arrows[:14], []), label="14/16 coverage")


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


# --- word OCR classifier (reachable, cell-resolution) -------------------------

def _cell_res_recognizes(text, atlas):
    cells = M.spell_cells(text, atlas)
    return M.ocr_scan(cells)


def test_word_ocr_every_word_recognized_in_raster_letters():
    atlas = M.letter_atlas()
    missed = []
    for entry in M.word_entries():
        text = entry["text"]
        if _cell_res_recognizes(text, atlas) is None:
            missed.append(text)
    assert not missed, f"OCR classifier missed raster-letter words: {missed}"


def test_word_ocr_all_reading_orientations_recognized():
    # A word drawn in ANY D4 orientation is caught, because the OCR replays every
    # reading direction (ocr_scan) before giving up.
    atlas = M.letter_atlas()
    cells = M.spell_cells("fuck", atlas)
    missed = []
    for op_key in geometry.D4_ALL:
        drawn = [geometry.apply_op(point, op_key) for point in cells]
        if M.ocr_scan(drawn) != "fuck":
            missed.append(op_key)
    assert not missed, f"drawn orientations the OCR failed to read: {missed}"


def test_word_ocr_homoglyph_fold_cyrillic_and_leet():
    atlas = M.letter_atlas()
    # Cyrillic ХУЙ folds (X/Y/N) to the Russian slur entry.
    assert _cell_res_recognizes("ХУЙ", atlas) == "хуй"
    # Leet folds: 5->S 1->I 7->T etc. spelling an English slur.
    assert detector._fold("5P1C") == "SPIC"


def test_word_ocr_receiver_mirrored_word_recognized():
    atlas = M.letter_atlas()
    cells = M.spell_cells("fuck", atlas)
    mirrored = [geometry.apply_op(point, "r180") for point in cells]
    assert M.ocr_scan(mirrored) is not None


def test_huy_fixture_cell_resolution_recognized():
    # The user's ХУЙ screenshot, recognized by the OCR classifier at native
    # (cell) resolution -- the layer that actually works.
    atlas = M.letter_atlas()
    assert _cell_res_recognizes("хуй", atlas) == "хуй"


def test_unlisted_word_stays_clean():
    atlas = M.letter_atlas()
    # A benign 3+ letter string that is not on the word list must not match.
    cells = M.spell_cells("cat", atlas)
    assert M.ocr_scan(cells) is None


# --- word OCR end-to-end via detect() -----------------------------------------

def test_huy_arrow_fixture_blocks_end_to_end():
    # The user's ХУЙ screenshot, arrows only (two of the У strokes are
    # knight-vector arrows and render as Ls -- the glyph templates reproduce
    # that through the same decomposition).
    verdict = detector.detect(M.arrows_from_segments(HUY_ARROW_FIXTURE), [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id == "word:хуй"


def test_word_end_to_end_every_board_fitting_word_blocks():
    # Every listed word short enough to draw with skeleton letters on an 8-wide
    # board must hard-block through detect(); longer words are geometrically
    # unwritable at this resolution and stay classifier-only coverage.
    missed = []
    fitted = 0
    for entry in M.word_entries():
        arrows = M.spell_arrows(entry["text"])
        if arrows is None:
            continue
        fitted += 1
        verdict = detector.detect(arrows, [])
        if verdict.kind != detector.BLOCKED:
            missed.append((entry["text"], verdict.kind))
    assert fitted >= 10, f"expected most short words to fit the board, got {fitted}"
    assert not missed, f"board-fitting words that did not block: {missed}"


def test_word_end_to_end_unlisted_word_stays_clean():
    arrows = M.spell_arrows("cat")
    assert arrows is not None
    verdict = detector.detect(arrows, [])
    assert verdict.kind == detector.CLEAN, (
        f"unlisted arrow-written word tripped: {verdict.pattern_id}")


def test_block_atlas_glyphs_cannot_fit_the_board():
    # Rationale for the skeleton atlas: block-filled glyphs are 6-7 cells wide,
    # so three of them plus gutters overrun an 8-wide board -- highlight-drawn
    # words are geometrically impossible and arrow skeletons are the only
    # board-drawable letters.
    atlas = M.letter_atlas()
    widths = {ch: max(len(row) for row in rows) for ch, rows in atlas.items()}
    three_letter = "fag"
    total = sum(widths[ch.upper()] for ch in three_letter) + 2 * (len(three_letter) - 1)
    assert total > 8, f"expected a 3-glyph word to overrun the board, got {total}"
    assert min(widths.values()) >= 4
