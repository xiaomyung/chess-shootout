"""Review lookups over a live engine.

``position_at`` is called every time a player steps back through a game, and it
rebuilds an earlier board by deep-copying the engine and undoing plies on the
copy. The engine owns a running ``Clock`` whose ``now_provider`` is an injected
callable, so the copy leaves the clock out: cloning it per lookup duplicates the
time source for nothing, and the returned grid never depends on it. Piece has no
``__eq__``, so boards are compared as (type, color) grids rather than by object
identity.
"""

import copy

import pytest

from chessshootout.backend.backend import Backend
from tests.helpers import BLACK, WHITE, K, P, make_backend, piece, sq


OPENING = [
    (sq(6, 4), sq(4, 4)),
    (sq(1, 4), sq(3, 4)),
    (sq(7, 6), sq(5, 5)),
    (sq(0, 1), sq(2, 2)),
]


class UncopyableNow:
    """A clock time source that blows up if anything deep-copies it -- the
    tripwire for a review lookup that drags the whole clock into its copy."""

    def __init__(self, ts):
        self.ts = ts

    def __call__(self):
        return self.ts[0]

    def __deepcopy__(self, memo):
        raise AssertionError("position_at must not deep-copy the live clock")


def _grid(rows):
    return tuple(
        tuple((p.type, p.color) if p is not None else None for p in row)
        for row in rows
    )


def _clocked_game(now_provider):
    bk = Backend()
    bk.new_game()
    bk.setup_clock(300, 5, now_provider=now_provider)
    for from_sq, to_sq in OPENING:
        assert bk.try_move(from_sq, to_sq).legal
    return bk


def test_position_at_matches_a_replayed_engine_at_every_ply():
    """Leaving the clock out of the copy must not move a single piece: every ply
    of the browse has to match an engine that simply played that many moves."""
    ts = [0.0]
    bk = _clocked_game(lambda: ts[0])
    for ply in range(len(OPENING) + 1):
        replay = Backend()
        replay.new_game()
        for from_sq, to_sq in OPENING[:ply]:
            assert replay.try_move(from_sq, to_sq).legal
        assert _grid(bk.position_at(ply)) == _grid(replay.state), f"ply {ply}"


def test_position_at_leaves_the_live_clock_untouched():
    """The clock is detached only for the length of the copy, so the live engine
    must come out holding the very same object with the very same time on it."""
    ts = [0.0]
    bk = _clocked_game(lambda: ts[0])
    clock = bk.clock
    before = clock.snapshot()
    bk.position_at(1)
    bk.position_at(3)
    assert bk.clock is clock
    assert bk.clock.snapshot() == before


def test_position_at_does_not_deep_copy_the_clock():
    """Copying the engine wholesale clones the clock's injected time source once
    per review lookup; detaching it before the copy is what this pins down."""
    ts = [0.0]
    bk = _clocked_game(UncopyableNow(ts))
    fresh = Backend()
    fresh.new_game()
    assert _grid(bk.position_at(0)) == _grid(fresh.state)
    assert bk.clock is not None
    assert bk.clock.now_provider() == 0.0


def test_position_at_reattaches_the_clock_when_the_copy_raises(monkeypatch):
    """The detach is wrapped in a finally, so an engine whose copy blows up still
    comes back holding its clock -- without that, one failed lookup would leave
    the live game running untimed."""
    ts = [0.0]
    bk = _clocked_game(lambda: ts[0])
    clock = bk.clock

    def boom(obj):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(copy, "deepcopy", boom)
    with pytest.raises(RuntimeError):
        bk.position_at(1)
    assert bk.clock is clock


def test_position_at_on_an_unclocked_engine_still_rebuilds():
    """Untimed local games never call setup_clock, so the detach has to cope with
    a clock that was None to begin with."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    assert bk.try_move(sq(6, 0), sq(5, 0)).legal
    assert bk.position_at(0)[6][0].type == P
    assert bk.position_at(0)[5][0] is None
    assert bk.clock is None
