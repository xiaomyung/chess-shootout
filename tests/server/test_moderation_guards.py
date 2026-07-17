"""Structural guards + meta-tests + timing pin for the moderation package.

- Knight-L drift guard: the detector's arrow-elbow logic (geometry.arrow_polyline)
  must reproduce the client's Annotations._knight_arrow_corner exactly for every
  knight vector, or arrow decomposition diverges from what the opponent drew.
- Library meta-test: every patterns.json entry compiles, and every ENABLED entry
  trips its own canonical construction (doubles as full enabled-pattern coverage).
- Words meta-test: every words.json entry is renderable and recognized by the OCR
  classifier at cell resolution.
- Timing pin: a near-cap store churned through detect() stays under budget. The
  arrows are lattice-aligned on purpose: random squares mostly produce arrows
  with no unit-edge decomposition, which understates the vector stage's real
  worst case. Budget matches the plan's event-loop bound (<10 ms/update).
- Enabled vector patterns must decompose their authored segments COMPLETELY
  through segment_legs: a knight-vector or off-lattice segment that silently
  drops edges degenerates the template (the code_kkk_vector three-bare-lines
  false positive). DISABLED entries may carry undrawable drafts.
- Every letter of every listed word has a block glyph AND, when the word can fit
  the board at skeleton width, the letters need segment-skeleton constructions
  so the word is reachable end-to-end.

The frontend import here is intentional and safe: the pygame guard
(tests/infra/test_server_no_pygame.py) scans only package SOURCE under server/
and backend/, never tests/. Keep the import inside the test.
"""

import random
import time

from chessshootout.backend.utils import Square
from chessshootout.server.moderation import detector, geometry, library
from tests.server import moderation_helpers as M


TIMING_BUDGET_MS = 10.0


def test_knight_l_elbow_matches_client_annotations():
    from chessshootout.frontend.board.annotations import Annotations

    checked = 0
    for base_row in range(8):
        for base_col in range(8):
            for drow, dcol in ((1, 2), (2, 1), (-1, 2), (-2, 1),
                               (1, -2), (2, -1), (-1, -2), (-2, -1)):
                trow, tcol = base_row + drow, base_col + dcol
                if not (0 <= trow < 8 and 0 <= tcol < 8):
                    continue
                from_sq = Square(base_row, base_col)
                to_sq = Square(trow, tcol)
                corner = Annotations._knight_arrow_corner(from_sq, to_sq)
                corner_point = (corner.col, corner.row)
                polyline = geometry.arrow_polyline(from_sq, to_sq)
                assert len(polyline) == 3, (
                    f"{from_sq}->{to_sq}: expected an L polyline, got {polyline}")
                assert polyline[1] == corner_point, (
                    f"{from_sq}->{to_sq}: geometry elbow {polyline[1]} != "
                    f"client corner {corner_point}")
                checked += 1
    assert checked == 336


def test_every_pattern_entry_compiles():
    compiled = library.compiled_patterns()
    entry_ids = {entry["id"] for entry in M.pattern_entries()}
    compiled_ids = {pattern.id for pattern in compiled}
    assert compiled_ids == entry_ids
    for pattern in compiled:
        assert pattern.action in (library.HARD_BLOCK, library.SOFT_FLAG, library.DISABLED)
        if pattern.action == library.DISABLED:
            continue
        has_vector = bool(pattern.vector_variants)
        has_raster = bool(pattern.raster_variants)
        assert has_vector or has_raster, f"{pattern.id}: compiled to no variants"


def test_every_enabled_entry_trips_its_canonical_construction():
    missed = []
    for entry in M.enabled_entries():
        is_vector = "segments" in entry and entry["channel"] in ("vector", "both")
        if is_vector:
            verdict = detector.detect(M.canonical_arrows(entry), [])
        else:
            verdict = detector.detect([], M.canonical_highlights(entry))
        soft = entry["action"] == "SOFT_FLAG"
        allowed = {detector.BLOCKED} | ({detector.SUSPECT} if soft else set())
        if verdict.kind not in allowed:
            missed.append((entry["id"], verdict.kind))
    assert not missed, f"enabled entries that did not trip their canonical form: {missed}"


def test_enabled_vector_segments_decompose_completely():
    undecomposed = []
    for entry in M.enabled_entries():
        if "segments" not in entry or entry["channel"] not in ("vector", "both"):
            continue
        legs = geometry.segment_legs(
            [((a[0], a[1]), (b[0], b[1])) for a, b in entry["segments"]])
        for a, b in legs:
            if geometry.segment_unit_edges(a, b) is None:
                undecomposed.append((entry["id"], a, b))
    assert not undecomposed, (
        f"enabled vector segments that drop edges silently: {undecomposed}")


def test_every_word_letter_has_skeleton_construction():
    skeletons = M.letter_segment_atlas()
    missing = set()
    for entry in M.word_entries():
        for ch in entry["text"].upper():
            if ch not in skeletons or not skeletons[ch]:
                missing.add(ch)
    assert not missing, f"word letters without skeleton constructions: {missing}"


def test_every_word_entry_renderable_and_recognized():
    atlas = M.letter_atlas()
    missed = []
    for entry in M.word_entries():
        text = entry["text"]
        renderable = all(ch.upper() in atlas for ch in text)
        if not renderable:
            missed.append((text, "unrenderable"))
            continue
        cells = M.spell_cells(text, atlas)
        if M.ocr_scan(cells) is None:
            missed.append((text, "unrecognized"))
    assert not missed, f"word entries not renderable/recognized by the OCR: {missed}"


def test_worst_case_timing_under_budget():
    rng = random.Random(42)
    directions = ((1, 0), (0, 1), (1, 1), (1, -1))
    arrows = []
    seen = set()
    while len(arrows) < 120:
        col, row = rng.randrange(8), rng.randrange(8)
        dcol, drow = rng.choice(directions)
        length = rng.randrange(1, 8)
        tcol, trow = col + dcol * length, row + drow * length
        if not (0 <= tcol < 8 and 0 <= trow < 8):
            continue
        if ((col, row), (tcol, trow)) in seen:
            continue
        seen.add(((col, row), (tcol, trow)))
        arrows.append((M.coord(col, row), M.coord(tcol, trow)))
    highlight_cells = set()
    while len(highlight_cells) < 60:
        highlight_cells.add((rng.randrange(8), rng.randrange(8)))
    highlights = [M.coord(*cell) for cell in highlight_cells]

    # Pattern compilation, the glyph atlas, and the OCR width indices are built
    # lazily on the first detect() and amortized once per process -- that is
    # init cost, not the per-update cost this budget bounds. Warm it so a cold
    # worker (xdist splits files across processes) times steady state, not the
    # one-time build.
    detector.detect(list(arrows), highlights)

    # thread_time (this thread's CPU), not wall clock or process_time: detect()
    # is single-threaded and synchronous, so this budget bounds the CPU it burns
    # on one thread. Wall clock deschedules under xdist CPU contention (timing
    # the scheduler); process_time sums every thread in the process, so a
    # lingering server-fixture thread in the same xdist worker inflates it.
    # thread_time counts only the calling thread and is immune to both.
    worst_ms = 0.0
    for i in range(30):
        churned = list(arrows)
        churned[i % 120] = (M.coord(rng.randrange(8), rng.randrange(8)),
                            M.coord(rng.randrange(8), rng.randrange(8)))
        start = time.thread_time()
        detector.detect(churned, highlights)
        worst_ms = max(worst_ms, (time.thread_time() - start) * 1000)

    assert worst_ms < TIMING_BUDGET_MS, (
        f"worst-case detect() {worst_ms:.2f} ms exceeded budget "
        f"{TIMING_BUDGET_MS} ms -- fix perf, do not loosen silently")
