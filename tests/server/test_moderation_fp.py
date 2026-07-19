"""False-positive corpus for chessshootout.server.moderation.

The innocent corpus must stay CLEAN: candidate-move arrows (rook/bishop/queen
lines + knight L's), the full 8-move knight fan (mixed chirality -- must NOT trip
the pinwheel), king-safety rings with crossing arrows, plain plus / bare X / hash
grid shapes, real opening-prep arrow sets, and a deterministic seeded fuzz of
piece-geometry arrow sets. Tier-3 FP-fatal shapes (tyr arrowhead, arrow-cross
4-fan, crosshair) are pinned as never-block.

Coordinate convention (col,row)=(x,y), origin top-left.
"""

import random

import pytest

from chessshootout.backend.utils import Square, coord_from_square, on_board
from chessshootout.server.moderation import detector
from tests.server import moderation_helpers as M


def _c(col, row):
    return coord_from_square(Square(row=row, col=col))


def _assert_clean(arrows, highlights, label):
    verdict = detector.detect(arrows, highlights)
    assert verdict.kind == detector.CLEAN, (
        f"{label}: innocent input tripped -> {verdict.kind} "
        f"id={verdict.pattern_id}"
    )


CANDIDATE_ARROW_SETS = {
    "rook_file": [("e2", "e7")],
    "bishop_diagonal": [("c1", "h6")],
    "queen_diagonal": [("d1", "a4")],
    "knight_L_single": [("g1", "f3")],
    "two_developing": [("e2", "e4"), ("g1", "f3")],
    "three_lines": [("e2", "e4"), ("d2", "d4"), ("b1", "c3")],
    "six_analysis": [("e2", "e4"), ("d2", "d4"), ("g1", "f3"),
                     ("b1", "c3"), ("f1", "c4"), ("d1", "h5")],
    "two_knight_Ls": [("g1", "f3"), ("b1", "c3")],
}


@pytest.mark.parametrize("name", sorted(CANDIDATE_ARROW_SETS))
def test_candidate_move_arrows_stay_clean(name):
    _assert_clean(CANDIDATE_ARROW_SETS[name], [], f"candidate {name}")


def test_full_eight_move_knight_fan_stays_clean():
    fan = [("d4", target) for target in
           ("e6", "f5", "f3", "e2", "c2", "b3", "b5", "c6")]
    _assert_clean(fan, [], "8-move knight fan (mixed chirality)")


def test_king_safety_ring_stays_clean():
    ring = ["d3", "e3", "f3", "d4", "f4", "d5", "e5", "f5"]
    _assert_clean([], ring, "king-safety ring")


def test_king_safety_ring_with_crossing_arrows_stays_clean():
    ring = ["d3", "e3", "f3", "d4", "f4", "d5", "e5", "f5"]
    crossing = [("c3", "g7"), ("g3", "c7")]
    _assert_clean(crossing, ring, "king ring + crossing arrows")


SHAPE_ARROW_SETS = {
    "plain_plus": [("c5", "e5"), ("d6", "d4")],
    "bare_x": [("c3", "e5"), ("c5", "e3")],
    "hash_grid": [("c3", "f3"), ("c5", "f5"), ("d2", "d6"), ("e2", "e6")],
}


@pytest.mark.parametrize("name", sorted(SHAPE_ARROW_SETS))
def test_innocent_geometry_shapes_stay_clean(name):
    _assert_clean(SHAPE_ARROW_SETS[name], [], f"shape {name}")


OPENING_PREP_SETS = {
    "italian_plan": [("f1", "c4"), ("g1", "f3"), ("e1", "g1"), ("d2", "d3")],
    "sicilian_ideas": [("c7", "c5"), ("d7", "d6"), ("g8", "f6"), ("b8", "c6")],
    "kings_indian": [("f8", "g7"), ("g8", "f6"), ("e8", "g8"), ("d7", "d6")],
    "queens_gambit": [("d2", "d4"), ("c2", "c4"), ("b1", "c3"), ("c1", "g5")],
}


@pytest.mark.parametrize("name", sorted(OPENING_PREP_SETS))
def test_opening_prep_arrow_sets_stay_clean(name):
    _assert_clean(OPENING_PREP_SETS[name], [], f"opening {name}")


def test_three_parallel_file_arrows_stay_clean():
    # Regression pin: code_kkk_vector once compiled with its knight-vector K-arms
    # silently dropped, degenerating to three bare vertical lines -- any three
    # aligned file arrows at the right spacing hard-blocked as KKK.
    _assert_clean([("a2", "a6"), ("d2", "d6"), ("g2", "g6")], [],
                  "three parallel file arrows")


def test_single_sig_bolt_stays_clean():
    # Pairing rule: one lightning-bolt zigzag is a plausible attack arrow; only
    # the DOUBLE bolt is the SS symbol, and half the pair sits under coverage.
    entry = M.entry_by_id("ss_bolts_vector")
    half = entry["segments"][:len(entry["segments"]) // 2]
    _assert_clean(M.arrows_from_segments(half), [], "single sig bolt")


# --- tier-3 exclusion pins (never block) --------------------------------------

def test_tier3_tyr_arrowhead_single_arrow_never_blocks():
    _assert_clean([("d5", "d2"), ("d2", "c1"), ("d2", "e1")], [], "tyr arrowhead")


def test_tier3_arrow_cross_four_fan_never_blocks():
    fan = [("d4", "d1"), ("d4", "d7"), ("d4", "a4"), ("d4", "g4")]
    _assert_clean(fan, [], "arrow-cross 4-fan")


def test_tier3_crosshair_never_blocks():
    crosshair = [("d4", "d1"), ("d4", "d7"), ("d4", "a4"), ("d4", "g4"),
                 ("c3", "e3"), ("c5", "e5")]
    _assert_clean(crosshair, [], "crosshair")


# --- seeded piece-geometry fuzz -----------------------------------------------

def _rook_targets(col, row):
    out = [(cc, row) for cc in range(8) if cc != col]
    out += [(col, rr) for rr in range(8) if rr != row]
    return out


def _bishop_targets(col, row):
    out = []
    for dcol in (-1, 1):
        for drow in (-1, 1):
            cc, rr = col + dcol, row + drow
            while on_board(Square(rr, cc)):
                out.append((cc, rr))
                cc += dcol
                rr += drow
    return out


def _knight_targets(col, row):
    out = []
    for dcol, drow in ((1, 2), (2, 1), (-1, 2), (-2, 1),
                       (1, -2), (2, -1), (-1, -2), (-2, -1)):
        cc, rr = col + dcol, row + drow
        if on_board(Square(rr, cc)):
            out.append((cc, rr))
    return out


def _piece_fuzz_corpus():
    # The full 500-board pinned corpus (seed unchanged since the feature
    # landed). Generation is pure RNG and costs microseconds; the expensive
    # detect() calls are sliced across parametrized chunks below so no single
    # test is a multi-second CI outlier while total coverage stays at 500.
    rng = random.Random(20260717)
    generators = (_rook_targets, _bishop_targets, _knight_targets)
    boards = []
    for _ in range(500):
        arrows = []
        for _ in range(rng.randint(1, 6)):
            col, row = rng.randrange(8), rng.randrange(8)
            targets = rng.choice(generators)(col, row)
            if not targets:
                continue
            tcol, trow = rng.choice(targets)
            arrows.append((_c(col, row), _c(tcol, trow)))
        highlights = [_c(rng.randrange(8), rng.randrange(8))
                      for _ in range(rng.randint(0, 4))]
        boards.append((arrows, highlights))
    return boards


@pytest.mark.parametrize("chunk", range(10))
def test_seeded_piece_geometry_fuzz_stays_clean(chunk):
    trips = []
    for arrows, highlights in _piece_fuzz_corpus()[chunk::10]:
        verdict = detector.detect(arrows, highlights)
        if verdict.kind != detector.CLEAN:
            trips.append((verdict.pattern_id, arrows, highlights))
    assert not trips, f"seeded fuzz produced {len(trips)} false positives: {trips[:5]}"
