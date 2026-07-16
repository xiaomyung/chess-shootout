"""Opening-name lookup (domain/openings.py): the lichess chess-openings dataset
parses into a longest-prefix table, +/# check markers normalize on both the
dataset and engine-produced SAN sides, and out-of-book tails freeze on the
deepest known line. Pinned dataset rows (assets/openings.tsv):

    1. e4                                     -> B00 King's Pawn Game
    1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5            -> C50 Italian Game: Giuoco Piano
    1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4      -> C51 Italian Game: Evans Gambit
    1. d4 e6 2. c4 Bb4+                        -> A40 Kangaroo Defense
"""

from chessshootout import paths
from chessshootout.backend.backend import Backend
from chessshootout.domain import openings


ITALIAN = ("C50", "Italian Game: Giuoco Piano")
EVANS = ("C51", "Italian Game: Evans Gambit")
GIUOCO_LINE = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]


def test_table_loads_all_entries():
    openings.preload()
    assert len(openings._TABLE) >= 3000
    assert openings._MAX_PLIES >= 10


def test_preload_idempotent_does_not_reparse(monkeypatch):
    openings._TABLE = None
    openings._MAX_PLIES = 0
    calls = {"n": 0}
    real_resource_path = openings.resource_path

    def counting(*parts):
        calls["n"] += 1
        return real_resource_path(*parts)

    monkeypatch.setattr(openings, "resource_path", counting)
    openings.preload()
    openings.preload()
    assert calls["n"] == 1, "the second preload must not touch the dataset again"
    assert len(openings._TABLE) >= 3000


def test_lookup_empty_returns_none():
    openings.preload()
    assert openings.lookup([]) is None


def test_lookup_first_move_is_kings_pawn():
    openings.preload()
    eco, name = openings.lookup(["e4"])
    assert eco.startswith("B")
    assert "Pawn" in name


def test_lookup_giuoco_piano():
    openings.preload()
    assert openings.lookup(GIUOCO_LINE) == ITALIAN


def test_deeper_prefix_beats_shallower():
    openings.preload()
    assert openings.lookup(GIUOCO_LINE) == ITALIAN
    assert openings.lookup(GIUOCO_LINE + ["b4"]) == EVANS


def test_check_suffix_normalizes_both_sides():
    openings.preload()
    backend = Backend()
    backend.new_game()
    for san in ["d4", "e6", "c4", "Bb4"]:
        assert backend.apply_san(san).legal
    engine_sans = [entry.san for entry in backend.move_history]
    assert engine_sans[-1] == "Bb4+", "engine appends the check marker"
    assert openings.lookup(engine_sans) == ("A40", "Kangaroo Defense")


def test_out_of_book_freezes_on_longest_prefix():
    openings.preload()
    with_garbage = GIUOCO_LINE + ["a3", "a6", "h3"]
    assert openings.lookup(with_garbage) == openings.lookup(GIUOCO_LINE) == ITALIAN


def test_attribution_credits_openings_dataset():
    text = paths.resource_path("ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "chess-openings" in text
