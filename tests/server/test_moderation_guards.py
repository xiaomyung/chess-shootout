"""Structural guards + meta-tests + timing pin for the moderation package.

- Knight-L drift guard: the detector's arrow-elbow logic (geometry.arrow_polyline)
  must reproduce the client's Annotations._knight_arrow_corner exactly for every
  knight vector, or arrow decomposition diverges from what the opponent drew.
- Library meta-test: every patterns.json entry compiles, and every ENABLED entry
  trips its own canonical construction (doubles as full enabled-pattern coverage).
- Timing pin: a near-cap store churned through detect() stays under budget. The
  arrows are lattice-aligned on purpose: random squares mostly produce arrows
  with no unit-edge decomposition, which understates the vector stage's real
  worst case. Budget matches the plan's event-loop bound (<10 ms/update).
- Enabled vector patterns must decompose their authored segments COMPLETELY
  through segment_legs: a knight-vector or off-lattice segment that silently
  drops edges degenerates the template (a three-bare-lines false positive).
  DISABLED entries may carry undrawable drafts.

The frontend import here is intentional and safe: the pygame guard
(tests/infra/test_server_no_pygame.py) scans only package SOURCE under server/
and backend/, never tests/. Keep the import inside the test.
"""

import gc
import random
import time

from chessshootout.backend.utils import Square
from chessshootout.server.moderation import detector, geometry, library
from tests.server import moderation_helpers as M


TIMING_BUDGET_MS = 10.0
DENSE_TIMING_BUDGET_MS = 120.0


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
        assert pattern.action in (library.HARD_BLOCK, library.DISABLED)
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
        if verdict.kind != detector.BLOCKED:
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

    # Pattern compilation is built lazily on the first detect() and amortized
    # once per process -- that is init cost, not the per-update cost this budget
    # bounds. Warm it so a cold
    # worker (xdist splits files across processes) times steady state, not the
    # one-time build.
    detector.detect(list(arrows), highlights)

    # thread_time (this thread's CPU), not wall clock or process_time: detect()
    # is single-threaded and synchronous, so this budget bounds the CPU it burns
    # on one thread. Wall clock deschedules under xdist CPU contention (timing
    # the scheduler); process_time sums every thread in the process, so a
    # lingering server-fixture thread in the same xdist worker inflates it.
    # thread_time counts only the calling thread and is immune to both.
    # GC is paused around the loop: thread_time bills a gen2 collection pass to
    # whichever call it lands in, and with pygame imported by the knight-elbow
    # test above, one pass costs ~20 ms -- process-graph noise, not detect()
    # cost. The pause makes the pin measure the detector alone; the budget
    # itself stays untouched.
    # Even thread_time inflates on a saturated shared runner (SMT-sibling
    # contention, cache thrash, frequency throttling bill extra CPU-seconds to
    # the same instructions), so each input is sampled a few times and the BEST
    # sample -- its true uncontended cost -- is what the worst-input max is
    # taken over. An order-of-magnitude regression pushes every sample over the
    # line; transient contention on one sample no longer can.
    worst_ms = 0.0
    gc.collect()
    gc.disable()
    try:
        for i in range(30):
            churned = list(arrows)
            churned[i % 120] = (M.coord(rng.randrange(8), rng.randrange(8)),
                                M.coord(rng.randrange(8), rng.randrange(8)))
            best_ms = float("inf")
            for _ in range(3):
                start = time.thread_time()
                detector.detect(churned, highlights)
                best_ms = min(best_ms, (time.thread_time() - start) * 1000)
            worst_ms = max(worst_ms, best_ms)
    finally:
        gc.enable()

    budget_ms = TIMING_BUDGET_MS * M.machine_scale()
    assert worst_ms < budget_ms, (
        f"worst-case detect() {worst_ms:.2f} ms exceeded budget "
        f"{budget_ms:.2f} ms -- fix perf, do not loosen silently")


def test_dense_clean_set_timing_under_its_own_budget():
    """Second timing pin, for the input class the first one misses.

    test_worst_case_timing_under_budget uses long random lattice arrows: they
    fall out of the vector stage almost immediately (~1.4 ms measured), so its
    10 ms budget says nothing about the detector's real ceiling. The dense
    CLEAN set (moderation_helpers.dense_clean_arrows) keeps every stage in its
    expensive branch and costs ~32 ms per call on the dev box -- 3x the other
    pin's budget, and that is NOT a bug to fix by loosening: it is why the
    server meters moderation CPU per room/player (moderation.load) instead of
    trusting a per-call bound. This budget exists so an order-of-magnitude
    regression in that ceiling is caught; the load meter is what bounds the
    damage in production.

    Sampling differs from the other pin on purpose: detect() memoises on the
    exact arrow tuple, so repeating an identical call times the MEMO. Every
    sample here is a distinct rotation of the same set -- identical work,
    always a cache miss -- and the min across rotations is the uncontended
    cost (an xdist-loaded worker inflates individual samples).

    The budget is scaled by machine_scale(): the number below is the dev-box
    ceiling, and a CI runner executing the same code ~7x slower must not read
    as a regression."""
    arrows = M.dense_clean_arrows()
    assert detector.detect(list(arrows), []).kind == detector.CLEAN, (
        "the pin needs a CLEAN verdict: a block short-circuits the later stages")

    best_ms = float("inf")
    gc.collect()
    gc.disable()
    try:
        for i in range(8):
            rotated = arrows[i + 1:] + arrows[:i + 1]
            start = time.thread_time()
            verdict = detector.detect(rotated, [])
            best_ms = min(best_ms, (time.thread_time() - start) * 1000)
            assert verdict.kind == detector.CLEAN
    finally:
        gc.enable()

    budget_ms = DENSE_TIMING_BUDGET_MS * M.machine_scale()
    assert best_ms < budget_ms, (
        f"dense-clean detect() {best_ms:.2f} ms exceeded budget "
        f"{budget_ms:.2f} ms -- fix perf, do not loosen silently")


def test_detect_is_thread_safe_under_concurrent_callers():
    """Handlers run detect() inside asyncio.to_thread, so the module-level
    LRU memo (dict + order list) is shared across worker threads; unlocked
    pop(0)/append pairs corrupt it under contention. Hammer distinct and
    repeated inputs from a pool and pin that every concurrent verdict matches
    its serial twin."""
    from concurrent.futures import ThreadPoolExecutor

    swastika = [(tuple(a), tuple(b))
                for a, b in M.SWASTIKA_SCREENSHOTS["v1_hooks_only_pinwheel"]]
    inputs = [tuple(M.arrows_from_segments(swastika))]
    rng = random.Random(11)
    for _ in range(31):
        arrows = tuple((M.coord(rng.randrange(8), rng.randrange(8)),
                        M.coord(rng.randrange(8), rng.randrange(8)))
                       for _ in range(rng.randrange(1, 12)))
        inputs.append(tuple(a for a in arrows if a[0] != a[1]))

    serial = [detector.detect(list(arrows), []).kind for arrows in inputs]
    with ThreadPoolExecutor(max_workers=6) as pool:
        concurrent = list(pool.map(
            lambda arrows: detector.detect(list(arrows), []).kind, inputs * 3))
    assert concurrent == serial * 3
