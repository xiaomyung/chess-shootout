"""generate_pgn header emission, with focus on the supplemental [CSMatchId] tag:
it sits below the Seven-Tag-Roster + TimeControl (so standard importers still read a
clean roster), it round-trips back through the header parser, and adding it never
breaks movetext replay.

Also the write-time sanitizers, which are the single choke point for every
untrusted string the file can carry: tag_value for header values (nicknames and
termination text) and comment_value for anything embedded in {} movetext (the
skill-check annotations, whose san comes straight off the /resume wire)."""

from chessshootout.backend.backend import Backend
from chessshootout.domain.pgn.generate import (
    COMMENT_MAX_CHARS, comment_value, format_annotations, generate_pgn,
)
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


def test_adversarial_nickname_cannot_forge_a_second_tag():
    """The one injection an opponent can reach through the honest server: the
    nickname validator allows `"`, `[` and `]`, and 20 chars is enough for
    `X"][Termination "Lag`. The loader's tag regex is unanchored and its dict
    comprehension lets a later duplicate win, so an unescaped value would forge a
    real [Termination] tag on the victim's own PGN."""
    text = generate_pgn([], "white_wins", white_name='X"][Termination "Lag')
    headers = parse_pgn_headers(text)
    assert "Termination" not in headers
    assert headers["White"] == "XTermination Lag"
    assert headers["Result"] == "1-0"
    assert text.count("[White ") == 1


def test_adversarial_nickname_leaves_the_movetext_parseable():
    backend = _played("e4", "e5")
    text = generate_pgn(backend.move_history, "white_wins",
                        white_name='a"]\\[b', black_name="[CSMatchId]")
    parsed, ok = load_pgn_into_backend(Backend(), text)
    assert ok is True
    assert parsed.moves == ["e4", "e5"]
    assert parsed.headers["White"] == "ab"
    assert parsed.headers["Black"] == "CSMatchId"
    assert extract_csmatchid(parsed.headers) is None


def test_termination_and_match_id_values_are_escaped_too():
    mid = fake_uuid4(9)
    text = generate_pgn([], "white_wins", match_id=mid,
                        termination='Abandoned"][Result "0-1')
    headers = parse_pgn_headers(text)
    assert headers["Result"] == "1-0"
    assert headers["Termination"] == "AbandonedResult 0-1"
    assert extract_csmatchid(headers) == mid


def test_newline_in_a_name_cannot_split_the_tag_into_two_headers():
    """The tag sanitizer used to drop only ", \\, [ and ] -- a CR/LF rides through
    those and ends the tag line early, so the rest of the value becomes its own
    header line for the unanchored tag regex to pick up."""
    text = generate_pgn([], "white_wins", white_name='Ann"]\n[Result "0-1"]\n[X "')
    headers = parse_pgn_headers(text)
    assert headers["Result"] == "1-0"
    assert "X" not in headers
    assert headers["White"] == "AnnResult 0-1X "
    assert len([line for line in text.splitlines() if line.startswith("[")]) == 8


def test_control_characters_are_stripped_from_every_tag_value():
    text = generate_pgn([], "white_wins", white_name="a\rb\tc\x00d",
                        black_name="e\x1b[2Jf", termination="g\vh")
    headers = parse_pgn_headers(text)
    assert headers["White"] == "abcd"
    assert headers["Black"] == "e2Jf", "ESC goes with the control chars, [ with the tag set"
    assert headers["Termination"] == "gh"
    assert "\r" not in text and "\t" not in text


def test_server_supplied_san_cannot_forge_a_result_header_from_a_comment():
    """/resume hands back skillcheck_log[].san free-form and it is embedded in {}
    movetext verbatim. Closing the brace and opening a tag line forges a header,
    and parse_pgn_headers lets the LAST match win -- so the forged [Result] would
    be the one the history screen reads."""
    backend = _played("e4", "d5", "exd5")
    hostile = 'x} \n[Result "0-1"] {'
    log = [SkillCheckOutcome(3, "wheel", False, hostile)]
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations=format_annotations(log))

    headers = parse_pgn_headers(text)
    assert headers["Result"] == "1-0", "the genuine result still wins the last-match race"
    assert text.count('[Result "') == 1
    assert "\n" not in text.split("\n\n", 1)[1].rstrip("\n"), "movetext stays one line"


def test_forged_san_round_trips_as_an_inert_comment():
    backend = _played("e4", "d5", "exd5")
    log = [SkillCheckOutcome(3, "wheel", False, 'x} [Result "0-1"] {')]
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations=format_annotations(log))

    parsed, ok = load_pgn_into_backend(Backend(), text)
    assert ok is True
    assert parsed.moves == ["e4", "d5", "exd5"]
    assert parsed.result == "1-0"
    assert parsed.headers["Result"] == "1-0"
    assert "{" not in parsed.move_comments[2] and "}" not in parsed.move_comments[2]
    assert "[" not in parsed.move_comments[2] and "]" not in parsed.move_comments[2]


def test_an_oversize_annotation_is_capped_before_it_is_embedded():
    """san is server-supplied and unbounded on the wire; a megabyte of it in a
    comment is a megabyte written to disk on every throttled autosave tick."""
    backend = _played("e4", "d5", "exd5")
    log = [SkillCheckOutcome(3, "wheel", False, "Q" * 100_000)]
    text = generate_pgn(backend.move_history, "white_wins",
                        annotations=format_annotations(log))

    parsed = parse_pgn(text)
    assert len(parsed.move_comments[2]) == COMMENT_MAX_CHARS
    assert len(text) < 1000


def test_an_all_hostile_annotation_emits_no_empty_braces():
    backend = _played("e4", "d5", "exd5")
    text = generate_pgn(backend.move_history, "white_wins", annotations={3: "{}[]\\\n"})
    assert "{" not in text and "}" not in text
    parsed, ok = load_pgn_into_backend(Backend(), text)
    assert ok is True
    assert parsed.moves == ["e4", "d5", "exd5"]


def test_a_real_annotation_is_never_touched_by_the_comment_sanitizer():
    """The genuine annotation vocabulary -- labels, the middle dot separator, the
    tick and cross glyphs and SAN -- has to survive byte-identically, or the
    round-trip through parse_comment silently drops outcomes."""
    log = [
        SkillCheckOutcome(3, "whack", True),
        SkillCheckOutcome(3, "combo", False, "Qxd5+"),
    ]
    note = format_annotations(log)[3]
    assert comment_value(note) == note == "Whack-a-Mole ✓ · Combo ✗ Qxd5+"


def test_five_outcomes_on_one_ply_still_fit_under_the_comment_cap():
    """The cap has to clear the worst legitimate ply: a turn where the player
    misses several different captures, each logged against the same ply."""
    log = [SkillCheckOutcome(7, "whack", False, "Qxd5+") for _ in range(5)]
    note = format_annotations(log)[7]
    assert comment_value(note) == note


def test_ordinary_names_are_emitted_byte_identically():
    text = generate_pgn([], "draw_agreement", white_name="Magnus C.",
                        black_name="Hikaru (GM) #1")
    assert '[White "Magnus C."]' in text
    assert '[Black "Hikaru (GM) #1"]' in text


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
