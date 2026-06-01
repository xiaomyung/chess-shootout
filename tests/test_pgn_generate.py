"""generate_pgn header emission, with focus on the supplemental [CSMatchId] tag:
it sits below the Seven-Tag-Roster + TimeControl (so standard importers still read a
clean roster), it round-trips back through the header parser, and adding it never
breaks movetext replay."""

from backend.backend import Backend
from frontend.pgn.generate import generate_pgn
from frontend.pgn.load import (
    extract_csmatchid, load_pgn_into_backend, parse_pgn_headers,
)
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
