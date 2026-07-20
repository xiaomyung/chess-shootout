"""generate_pgn header emission, with focus on the supplemental [CSMatchId] tag:
it sits below the Seven-Tag-Roster + TimeControl (so standard importers still read a
clean roster), it round-trips back through the header parser, and adding it never
breaks movetext replay."""

from chessshootout.backend.backend import Backend
from chessshootout.domain.pgn.generate import format_annotations, generate_pgn
from chessshootout.domain.pgn.load import (
    extract_csmatchid, load_pgn_into_backend, parse_comment, parse_pgn,
    parse_pgn_headers,
)
from chessshootout.skillcheck.types import SkillCheckOutcome
from tests.helpers import fake_uuid4


def _played(*sans):
    backend = Backend()
    backend.new_game()
    for san in sans:
        res = backend.apply_san(san)
        assert res.legal, f"illegal in fixture: {san}"
    return backend


def test_csmatchid_tag_present_when_provided():
    mid = fake_uuid4(7)
    assert f'[CSMatchId "{mid}"]' in generate_pgn([], "white_wins", match_id=mid)


def test_csmatchid_tag_absent_when_none():
    assert "CSMatchId" not in generate_pgn([], "draw_agreement")


def test_csmatchid_follows_timecontrol_and_precedes_termination():
    mid = fake_uuid4(3)
    text = generate_pgn([], "white_wins_on_time", match_id=mid)
    assert text.index("TimeControl") < text.index("CSMatchId") < text.index("Termination")


def test_seven_tag_roster_precedes_csmatchid():
    mid = fake_uuid4(1)
    text = generate_pgn([], "white_wins", match_id=mid)
    csi = text.index("[CSMatchId ")
    for tag in ("Event", "Site", "Date", "Round", "White", "Black", "Result"):
        assert text.index(f"[{tag} ") < csi


def test_csmatchid_round_trips_through_headers():
    mid = fake_uuid4(11)
    text = generate_pgn([], "white_wins", match_id=mid)
    assert extract_csmatchid(parse_pgn_headers(text)) == mid


def test_pgn_with_csmatchid_still_loads_into_backend():
    backend = _played("e4", "e5", "Nf3")
    mid = fake_uuid4(5)
    text = generate_pgn(backend.move_history, "white_wins", match_id=mid)
    parsed, ok = load_pgn_into_backend(Backend(), text)
    assert ok is True
    assert parsed.moves == ["e4", "e5", "Nf3"]
    assert extract_csmatchid(parsed.headers) == mid


def test_format_annotations_groups_and_orders_per_ply():
    log = [
        SkillCheckOutcome(13, "wheel", True),
        SkillCheckOutcome(14, "wheel", False, "Rxe5"),
        SkillCheckOutcome(15, "wheel", False, "Rxe5"),
        SkillCheckOutcome(15, "aim", True),
    ]
    ann = format_annotations(log)
    assert ann == {
        13: "Wheel ✓",
        14: "Wheel ✗ Rxe5",
        15: "Wheel ✗ Rxe5 · Steady-Aim ✓",
    }


def test_format_annotations_labels_whack_and_combo_kinds():
    log = [
        SkillCheckOutcome(13, "whack", True),
        SkillCheckOutcome(14, "combo", False, "Qxd5"),
        SkillCheckOutcome(14, "whack", True),
    ]
    ann = format_annotations(log)
    assert ann == {
        13: "Whack-a-Mole ✓",
        14: "Combo ✗ Qxd5 · Whack-a-Mole ✓",
    }


def test_format_annotations_empty_log_is_empty_dict():
    assert format_annotations([]) == {}


def test_generate_pgn_injects_annotation_after_the_right_san():
    backend = _played("e4", "e5", "Nf3", "Nc6")
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations={1: "Wheel ✓", 4: "Steady-Aim ✗ Nxe5"})
    assert "1. e4 {Wheel ✓} e5" in text
    assert "2. Nf3 Nc6 {Steady-Aim ✗ Nxe5}" in text


def test_generate_pgn_without_annotations_is_byte_identical():
    backend = _played("e4", "e5", "Nf3")
    assert (generate_pgn(backend.move_history, "white_wins")
            == generate_pgn(backend.move_history, "white_wins", annotations={}))


def test_generate_pgn_annotation_on_trailing_unpaired_white_move():
    backend = _played("e4", "e5", "Nf3")
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations={3: "Wheel ✓"})
    body = text.strip().splitlines()[-1]
    assert body.endswith("2. Nf3 {Wheel ✓} 1-0")


def test_generate_pgn_annotations_survive_a_full_round_trip():
    backend = _played("e4", "e5", "Nf3", "Nc6")
    ann = {1: "Wheel ✓", 4: "Steady-Aim ✗ Nxe5"}
    text = generate_pgn(backend.move_history, "white_wins", annotations=ann)
    parsed = parse_pgn(text)
    assert parsed.moves == ["e4", "e5", "Nf3", "Nc6"]
    assert parsed.move_comments == ["Wheel ✓", "", "", "Steady-Aim ✗ Nxe5"]


def test_generate_pgn_injects_whack_and_combo_annotations_after_the_right_san():
    backend = _played("e4", "d5", "exd5", "Qxd5")
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations={3: "Whack-a-Mole ✓", 4: "Combo ✗ Qxd5"})
    assert "2. exd5 {Whack-a-Mole ✓} Qxd5 {Combo ✗ Qxd5}" in text


def test_generate_load_round_trip_with_whack_and_combo_outcomes():
    backend = _played("e4", "d5", "exd5", "Qxd5")
    log = [
        SkillCheckOutcome(3, "whack", True),
        SkillCheckOutcome(4, "combo", False, "Qxd5"),
    ]
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations=format_annotations(log))
    fresh = Backend()
    parsed, ok = load_pgn_into_backend(fresh, text)
    assert ok is True
    assert [e.san for e in fresh.move_history] == ["e4", "d5", "exd5", "Qxd5"]
    events = [parse_comment(comment) for comment in parsed.move_comments]
    assert events == [[], [], [("whack", True, "")], [("combo", False, "Qxd5")]]
