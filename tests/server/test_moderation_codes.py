"""Arrow-drawn numeric hate-code detection for chessshootout.server.moderation.

Pure-arrow numeric codes evaded the raster code channel (raster codes require a
highlight-ink share, so an arrow-only cluster never reached a cell template).
Digits now carry a segment-skeleton atlas (words.json digit_segments) rendered
through the SAME arrow rasterization + knight-L decomposition the letter OCR
path uses, and a digit-OCR stage reads arrow-drawn codes at supersampled
resolution across every D4 reading direction (receiver-mirrored included).

Action tiers mirror the existing raster patterns exactly: 1488 HARD_BLOCK (its
own vector template already caught the stacked two-row form; the OCR stage adds
the inline single-row form), and 88 / 14 / 18 / 311 SOFT_FLAG -- a lone 88 has
innocent-number ambiguity and must never hard-block on its own; two soft codes
(same frame or across a wipe via codes_seen) co-occurrence-block, identical to
the highlight path.

Coordinate convention (col,row)=(x,y), origin top-left.
"""

import random

import pytest

from chessshootout.backend.utils import Square, coord_from_square, on_board
from chessshootout.server.moderation import detector, geometry
from tests.server import moderation_helpers as M


def _c(col, row):
    return coord_from_square(Square(row=row, col=col))


CODE_ACTION = {
    "88": detector.SUSPECT,
    "14": detector.SUSPECT,
    "18": detector.SUSPECT,
    "311": detector.SUSPECT,
    "1488": detector.BLOCKED,
}


def _spell(text, step=None):
    return M.arrows_from_segments(M.digit_code_segments(text, step))


# --- each arrow-drawn code trips with the correct action ----------------------

@pytest.mark.parametrize("text", sorted(CODE_ACTION))
def test_arrow_code_trips_with_expected_action(text):
    verdict = detector.detect(_spell(text), [])
    assert verdict.kind == CODE_ACTION[text], (
        f"{text}: expected {CODE_ACTION[text]}, got {verdict.kind} "
        f"id={verdict.pattern_id} suspect={verdict.suspect_ids}")


def test_arrow_soft_code_reports_the_matching_pattern_id():
    verdict = detector.detect(_spell("88"), [])
    assert verdict.suspect_ids == ("code_88",)
    assert "code_88" in verdict.codes_seen_out


def test_arrow_1488_inline_single_row_hard_blocks():
    verdict = detector.detect(_spell("1488"), [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id.startswith("code_1488")


# --- orientation x scale orbit ------------------------------------------------

@pytest.mark.parametrize("text", sorted(CODE_ACTION))
def test_arrow_code_trips_across_orientation_and_scale(text):
    segments = M.digit_code_segments(text)
    expected = CODE_ACTION[text]
    allowed = {detector.BLOCKED}
    if expected == detector.SUSPECT:
        allowed.add(detector.SUSPECT)
    samples = 0
    for op_key in geometry.D4_ALL:
        for factor in (1, 2):
            arrows = M.transformed_vector_arrows(segments, op_key, factor, 0, 0)
            if arrows is None:
                continue
            verdict = detector.detect(arrows, [])
            samples += 1
            assert verdict.kind in allowed, (
                f"{text} {op_key} x{factor}: {verdict.kind} id={verdict.pattern_id}")
    assert samples >= 8, f"{text}: too few on-board orbit samples ({samples})"


def test_arrow_1488_receiver_mirrored_hard_blocks():
    segments = M.digit_code_segments("1488")
    mirrored = [[[7 - a[0], 7 - a[1]], [7 - b[0], 7 - b[1]]] for a, b in segments]
    verdict = detector.detect(M.arrows_from_segments(mirrored), [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id.startswith("code_1488")


# --- temporal code memory (arrow channel) -------------------------------------

def test_arrow_temporal_14_then_88_across_wipe_blocks():
    first = detector.detect(_spell("14"), [])
    assert first.kind == detector.SUSPECT
    assert first.codes_seen_out == frozenset({"code_14"})
    second = detector.detect(_spell("88"), [], codes_seen=first.codes_seen_out)
    assert second.kind == detector.BLOCKED
    assert second.pattern_id == detector.CODE_COOCCURRENCE_ID
    assert set(second.suspect_ids) == {"code_14", "code_88"}


def test_arrow_two_different_codes_thread_via_memory_block():
    # Two DIFFERENT arrow-drawn soft codes across a wipe co-occurrence-block,
    # same as the highlight channel's temporal memory.
    first = detector.detect(_spell("14"), [])
    assert first.codes_seen_out == frozenset({"code_14"})
    second = detector.detect(_spell("18"), [], codes_seen=first.codes_seen_out)
    assert second.kind == detector.BLOCKED
    assert second.pattern_id == detector.CODE_COOCCURRENCE_ID
    assert set(second.suspect_ids) == {"code_14", "code_18"}


def test_arrow_soft_code_reuses_raster_pattern_id():
    # The arrow channel emits the SAME pattern id the highlight/raster channel
    # uses for each code, so codes_seen memory threads across both channels.
    from chessshootout.server.moderation import library

    raster_ids = {pattern.digits: pattern.id
                  for pattern in library.enabled_patterns()
                  if pattern.action == library.SOFT_FLAG
                  and pattern.transform_group == "digit" and pattern.digits}
    for text in ("88", "14", "18", "311"):
        verdict = detector.detect(_spell(text), [])
        assert verdict.suspect_ids == (raster_ids[text],), (
            f"{text}: arrow id {verdict.suspect_ids} != raster id {raster_ids[text]}")


# --- padded-digit decoys (substring scan) -------------------------------------

@pytest.mark.parametrize("padded,code_id", [
    ("148", "code_14"),
    ("114", "code_14"),
    ("884", "code_88"),
    ("788", "code_88"),
])
def test_arrow_padded_digit_decoy_still_flags(padded, code_id):
    # Exact-match grouping let one decoy digit defeat every soft code ("148"
    # scanned as the single token 148, not containing 14). The word path
    # substring-matches (_matches_word), so the digit path must too: every
    # contiguous substring of an aligned digit group is checked.
    verdict = detector.detect(_spell(padded), [])
    assert verdict.kind == detector.SUSPECT, (
        f"{padded}: padded decoy evaded -> {verdict.kind}")
    assert code_id in verdict.suspect_ids


def test_arrow_padded_temporal_thread_still_blocks():
    # The padding evasion also severed temporal memory: "148" then "884" wrote
    # no codes_seen at all. With substring scanning the thread survives.
    first = detector.detect(_spell("148"), [])
    assert "code_14" in first.codes_seen_out
    second = detector.detect(_spell("884"), [], codes_seen=first.codes_seen_out)
    assert second.kind == detector.BLOCKED
    assert second.pattern_id == detector.CODE_COOCCURRENCE_ID


def test_arrow_1488_substrings_resolve_hard_over_soft():
    # 1488 contains soft substrings (14, 88); the hard table must win.
    verdict = detector.detect(_spell("1488"), [])
    assert verdict.kind == detector.BLOCKED
    assert verdict.pattern_id.startswith("code_1488")


def test_arrow_repeated_same_code_stays_single_soft_flag():
    # "888" contains 88 twice -- still ONE soft id, so it must NOT
    # co-occurrence-block on its own.
    verdict = detector.detect(_spell("888"), [])
    assert verdict.kind == detector.SUSPECT
    assert verdict.suspect_ids == ("code_88",)


# --- false-positive constraints -----------------------------------------------

def test_lone_arrow_88_never_hard_blocks():
    verdict = detector.detect(_spell("88"), [])
    assert verdict.kind != detector.BLOCKED, (
        f"lone 88 hard-blocked: {verdict.pattern_id}")


INNOCENT_ARROW_SETS = {
    "rook_file": [("e2", "e7")],
    "two_developing": [("e2", "e4"), ("g1", "f3")],
    "three_lines": [("e2", "e4"), ("d2", "d4"), ("b1", "c3")],
    "italian_plan": [("f1", "c4"), ("g1", "f3"), ("e1", "g1"), ("d2", "d3")],
}


@pytest.mark.parametrize("name", sorted(INNOCENT_ARROW_SETS))
def test_innocent_arrow_sets_do_not_trip_codes(name):
    verdict = detector.detect(INNOCENT_ARROW_SETS[name], [])
    assert verdict.kind == detector.CLEAN, (
        f"{name}: innocent arrows tripped -> {verdict.kind} id={verdict.pattern_id}")


def test_rank_file_count_doodles_do_not_hard_block():
    # A cluster of parallel file/rank arrows (counting squares) vaguely resembles
    # digit strokes -- it must never reach a hard block.
    doodles = [
        [("a2", "a6"), ("c2", "c6"), ("e2", "e6")],
        [("b3", "f3"), ("b5", "f5")],
        [("d1", "d7"), ("f1", "f7"), ("b1", "b7")],
    ]
    for arrows in doodles:
        verdict = detector.detect(arrows, [])
        assert verdict.kind != detector.BLOCKED, (
            f"doodle {arrows} hard-blocked as {verdict.pattern_id}")


def test_two_three_arrow_digitish_shapes_do_not_hard_block():
    # Small arrow sets that individually look like a digit stroke: a bare box,
    # an "H"-ish pair, an open triangle. None is a full aligned code.
    shapes = [
        [("c3", "c5"), ("c5", "e5"), ("e5", "e3"), ("e3", "c3")],
        [("c3", "c6"), ("e3", "e6"), ("c4", "e4")],
        [("c3", "e3"), ("e3", "d5"), ("d5", "c3")],
    ]
    for arrows in shapes:
        verdict = detector.detect(arrows, [])
        assert verdict.kind != detector.BLOCKED, (
            f"digit-ish shape {arrows} hard-blocked as {verdict.pattern_id}")


# --- seeded piece-geometry fuzz: zero hard blocks -----------------------------

def _rook_targets(col, row):
    return ([(cc, row) for cc in range(8) if cc != col]
            + [(col, rr) for rr in range(8) if rr != row])


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


def _is_code_verdict(verdict):
    pid = verdict.pattern_id
    if pid == detector.CODE_COOCCURRENCE_ID:
        return True
    if isinstance(pid, str) and pid.startswith("code_"):
        return True
    return any(isinstance(s, str) and s.startswith("code_") for s in verdict.suspect_ids)


def _code_fuzz_corpus():
    # Full 500-board pinned corpus (seed unchanged); RNG generation is cheap,
    # detect() is sliced across chunks so no single test dominates CI time.
    rng = random.Random(88148814)
    generators = (_rook_targets, _bishop_targets, _knight_targets)
    boards = []
    for _ in range(500):
        arrows = []
        for _ in range(rng.randint(1, 7)):
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
def test_seeded_piece_geometry_fuzz_no_code_false_positives(chunk):
    # The digit channel must never trip on piece-geometry arrows. Scope is the
    # code channel specifically: a coincidental swastika/heuristic hit belongs
    # to the shape channel's own FP corpus, not this feature.
    code_trips = []
    code_hard = []
    for arrows, highlights in _code_fuzz_corpus()[chunk::10]:
        verdict = detector.detect(arrows, highlights)
        if not _is_code_verdict(verdict):
            continue
        code_trips.append((verdict.kind, verdict.pattern_id, arrows, highlights))
        if verdict.kind == detector.BLOCKED:
            code_hard.append((verdict.pattern_id, arrows, highlights))
    assert not code_hard, f"seeded fuzz produced {len(code_hard)} code hard blocks: {code_hard[:5]}"
    assert not code_trips, (
        f"seeded fuzz produced {len(code_trips)} code false positives: {code_trips[:5]}")
