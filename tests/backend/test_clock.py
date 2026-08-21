"""Clock engine + Backend clock integration.

Time is driven by an injectable ``now_provider`` (a mutable ``ts`` list), so every
elapsed-time assertion is deterministic — no wall clock. Invariants exercised:
flag-fall always loses (chess.com/lichess, not FIDE 6.9), a pending promotion keeps
the mover's clock running until ``promote`` finalizes the ply, and undo round-trips
the full clock snapshot.
"""

import logging

import pytest

from chessshootout.backend.clock import Clock
from chessshootout.backend.pieces import PieceColor

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, P,
    make_backend, piece, sq,
)


def fake_now(ts):
    return lambda: ts[0]


def make_clock(initial=300, increment=5, ts=None):
    ts = ts if ts is not None else [0.0]
    return Clock.create(initial, increment, now_provider=fake_now(ts)), ts


def watch_legal_move_scans(backend):
    """Records every _has_no_legal_moves call the engine makes. The scan walks all
    64 squares generating legal moves for each piece, so it is by far the most
    expensive thing tick_clock could do -- and tick_clock runs once per frame."""
    calls = []
    original = backend._has_no_legal_moves

    def counted(color):
        calls.append(color)
        return original(color)

    backend._has_no_legal_moves = counted
    return calls


def test_clock_construction_defaults():
    clock, _ = make_clock(300, 5)
    assert clock.initial_seconds == 300
    assert clock.increment_seconds == 5
    assert clock.white_remaining == 300
    assert clock.black_remaining == 300
    assert clock.running_for is None
    assert clock.last_tick_at is None
    assert clock.flagged is None


def test_start_sets_white_running_and_records_now():
    clock, ts = make_clock(300, 5)
    ts[0] = 7.5
    clock.start()
    assert clock.running_for == PieceColor.WHITE
    assert clock.last_tick_at == 7.5


def test_tick_with_no_elapsed_changes_nothing():
    clock, ts = make_clock(300, 5)
    clock.start()
    clock.tick()
    assert clock.white_remaining == 300


def test_tick_subtracts_elapsed_from_running_color():
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 2.0
    clock.tick()
    assert clock.white_remaining == pytest.approx(298.0)
    assert clock.black_remaining == 300


def test_tick_flags_when_remaining_hits_zero():
    clock, ts = make_clock(initial=1.0, increment=5)
    clock.start()
    ts[0] = 2.0
    clock.tick()
    assert clock.flagged == PieceColor.WHITE
    assert clock.running_for is None
    assert clock.last_tick_at is None
    assert clock.white_remaining == 0


def test_tick_no_op_when_running_for_is_none():
    clock, ts = make_clock(300, 5)
    ts[0] = 2.0
    clock.tick()
    assert clock.white_remaining == 300


def test_on_move_made_white_debits_then_increments_then_switches():
    """White ran 2s, then +5 increment, then the clock switches to black."""
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 2.0
    clock.on_move_made(PieceColor.WHITE)
    assert clock.white_remaining == pytest.approx(303.0)
    assert clock.running_for == PieceColor.BLACK
    assert clock.last_tick_at == 2.0
    assert clock.black_remaining == 300


def test_on_move_made_black_symmetric():
    """After white's move, black runs 3s then gets +5 increment on its own ply."""
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 2.0
    clock.on_move_made(PieceColor.WHITE)
    ts[0] = 5.0
    clock.on_move_made(PieceColor.BLACK)
    assert clock.black_remaining == pytest.approx(302.0)
    assert clock.running_for == PieceColor.WHITE
    assert clock.last_tick_at == 5.0


def test_stop_clears_running_state():
    clock, _ = make_clock()
    clock.start()
    clock.stop()
    assert clock.running_for is None
    assert clock.last_tick_at is None


@pytest.mark.parametrize(
    "color, white_val, black_val, expected",
    [
        pytest.param(PieceColor.WHITE, 42, 17, 42, id="remaining_white"),
        pytest.param(PieceColor.BLACK, 42, 17, 17, id="remaining_black"),
    ],
)
def test_remaining_returns_correct_side(color, white_val, black_val, expected):
    clock, _ = make_clock(60, 0)
    clock.white_remaining = white_val
    clock.black_remaining = black_val
    assert clock.remaining(color) == expected


def test_snapshot_restore_round_trip():
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 4.0
    clock.tick()
    snap = clock.snapshot()
    clock.white_remaining = 0
    clock.black_remaining = 0
    clock.running_for = None
    clock.last_tick_at = None
    clock.flagged = PieceColor.BLACK
    clock.restore(snap)
    assert clock.white_remaining == pytest.approx(296.0)
    assert clock.black_remaining == 300
    assert clock.running_for == PieceColor.WHITE
    assert clock.last_tick_at == 4.0
    assert clock.flagged is None


def test_backend_init_clock_is_none():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    assert bk.clock is None


def test_backend_tick_clock_no_op_when_clock_none():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    bk.tick_clock()
    assert bk.clock is None


def test_backend_setup_clock_starts_white_running():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    ts = [0.0]
    bk.setup_clock(300, 5, now_provider=fake_now(ts))
    assert bk.clock is not None
    assert bk.clock.running_for == PieceColor.WHITE
    assert bk.clock.last_tick_at == 0.0


def test_backend_new_game_clears_clock():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    bk.setup_clock(300, 5)
    assert bk.clock is not None
    bk.new_game()
    assert bk.clock is None


def test_finalize_move_snapshots_clock_and_calls_on_move_made():
    """Snapshot captures pre-move state; clock then debits + increments + switches."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(300, 5, now_provider=fake_now(ts))
    pre_white = bk.clock.white_remaining
    ts[0] = 2.0
    result = bk.try_move(sq(6, 0), sq(5, 0))
    assert result.legal
    entry = bk.move_history[-1]
    assert entry.prev_clock_snapshot is not None
    snap_white, snap_black, snap_running, snap_last_tick, snap_flagged = entry.prev_clock_snapshot
    assert snap_white == pre_white
    assert snap_running == PieceColor.WHITE
    assert snap_last_tick == 0.0
    assert bk.clock.white_remaining == pytest.approx(303.0)
    assert bk.clock.running_for == PieceColor.BLACK


def test_promotion_pending_does_not_snapshot_clock_yet():
    """Pending promotion is appended without _finalize_move, so no snapshot yet."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(1, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(300, 5, now_provider=fake_now(ts))
    result = bk.try_move(sq(1, 0), sq(0, 0))
    assert result.promotion_required
    assert bk.move_history[-1].prev_clock_snapshot is None
    assert bk.clock.running_for == PieceColor.WHITE


def test_clock_runs_during_pending_promotion():
    """White's clock keeps ticking until promote() finalizes the ply."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(1, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(300, 5, now_provider=fake_now(ts))
    bk.try_move(sq(1, 0), sq(0, 0))
    ts[0] = 5.0
    bk.tick_clock()
    assert bk.clock.white_remaining == pytest.approx(295.0)
    bk.promote(sq(0, 0), Q)
    assert bk.clock.white_remaining == pytest.approx(300.0)
    assert bk.clock.running_for == PieceColor.BLACK


def test_timeout_white_results_in_black_wins_on_time():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=fake_now(ts))
    ts[0] = 2.0
    bk.tick_clock()
    assert bk.clock.flagged == PieceColor.WHITE
    assert bk.game_result() == "black_wins_on_time"


def test_timeout_black_results_in_white_wins_on_time():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=10.0, increment_seconds=0, now_provider=fake_now(ts))
    bk.try_move(sq(6, 0), sq(5, 0))
    ts[0] = 100.0
    bk.tick_clock()
    assert bk.clock.flagged == PieceColor.BLACK
    assert bk.game_result() == "white_wins_on_time"


def test_timeout_outranks_insufficient_material_DEVIATION():
    """FIDE 6.9 draws a flag-fall the opponent can't mate; we lose it (chess.com).
    The falling flag is what makes tick_clock scan for legal moves at all, and
    White has plenty here, so the tick stands instead of being rolled back."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 0): piece(B, BLACK),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=fake_now(ts))
    ts[0] = 2.0
    bk.tick_clock()
    assert bk.clock.flagged == PieceColor.WHITE
    assert bk.clock.white_remaining == 0
    assert bk.clock.running_for is None
    assert bk.game_result() == "black_wins_on_time"


def test_no_tick_after_game_over():
    """A mated side must never be flagged on top of the mate, so the tick that
    would have dropped the flag is rolled back whole -- remaining times, running
    side and the last-tick stamp included, exactly as if it never ran."""
    bk = make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 5): piece(P, WHITE),
        sq(6, 6): piece(P, WHITE),
        sq(6, 7): piece(P, WHITE),
        sq(7, 0): piece(R, BLACK),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    ts = [0.0]
    bk.setup_clock(60, 0, now_provider=fake_now(ts))
    assert bk.game_result() == "black_wins"
    pre = bk.clock.snapshot()
    ts[0] = 999.0
    bk.tick_clock()
    assert bk.clock.snapshot() == pre
    assert bk.clock.flagged is None
    assert bk.game_result() == "black_wins"


def test_routine_tick_never_scans_for_legal_moves():
    """The client ticks the clock once per frame. Nothing about a tick that leaves
    both flags standing depends on whose move is legal, so the whole-board scan
    must stay out of it -- it used to run on every single frame."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(300, 0, now_provider=fake_now(ts))
    scans = watch_legal_move_scans(bk)
    for step in (1.0, 2.0, 3.0):
        ts[0] = step
        bk.tick_clock()
    assert scans == []
    assert bk.clock.white_remaining == pytest.approx(297.0)


def test_flag_falling_tick_scans_once_and_keeps_the_flag():
    """The scan is not dropped, only deferred: the one tick that drops a flag pays
    for it, and a side that does have moves keeps the flag it just lost."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=fake_now(ts))
    scans = watch_legal_move_scans(bk)
    ts[0] = 2.0
    bk.tick_clock()
    assert scans == [PieceColor.WHITE]
    assert bk.clock.flagged == PieceColor.WHITE
    assert bk.game_result() == "black_wins_on_time"


def test_tick_after_a_flag_has_fallen_scans_nothing_more():
    """Once a flag is down the clock is finished, so every later frame returns
    before the scan and before touching a single field."""
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=fake_now(ts))
    ts[0] = 2.0
    bk.tick_clock()
    after_flag = bk.clock.snapshot()
    scans = watch_legal_move_scans(bk)
    ts[0] = 50.0
    bk.tick_clock()
    assert scans == []
    assert bk.clock.snapshot() == after_flag


def test_undo_restores_clock_state():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(300, 5, now_provider=fake_now(ts))
    pre_snap = bk.clock.snapshot()
    ts[0] = 2.0
    bk.try_move(sq(6, 0), sq(5, 0))
    assert bk.clock.white_remaining == pytest.approx(303.0)
    bk.undo()
    assert bk.clock.snapshot() == pre_snap
    assert bk.clock.white_remaining == 300
    assert bk.clock.running_for == PieceColor.WHITE


def test_undo_with_no_clock_does_not_crash():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(6, 0): piece(P, WHITE),
    })
    bk.try_move(sq(6, 0), sq(5, 0))
    bk.undo()
    assert bk.piece_at(sq(6, 0)) is not None
    assert bk.piece_at(sq(5, 0)) is None


def test_clock_stops_on_checkmate():
    """Qa8# (white Kg6, Qa6, black Kh8) ends the game with no further on_move_made."""
    bk = make_backend({
        sq(2, 6): piece(K, WHITE),
        sq(2, 0): piece(Q, WHITE),
        sq(0, 7): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    ts = [0.0]
    bk.setup_clock(60, 5, now_provider=fake_now(ts))
    result = bk.try_move(sq(2, 0), sq(0, 0))
    assert result.legal
    assert result.is_checkmate
    assert bk.game_result() == "white_wins"
    assert bk.clock.running_for is None


@pytest.mark.parametrize(
    "initial, preset_remaining, color, amount, expected_added, expected_remaining",
    [
        pytest.param(180, 100.0, BLACK, 15, 15.0, 115.0, id="below_initial_adds_full"),
        pytest.param(180, None, WHITE, 15, 0.0, 180.0, id="at_cap_returns_zero"),
        pytest.param(180, 170.0, BLACK, 15, 10.0, 180.0, id="partial_cap_returns_actual"),
        pytest.param(60, 75.0, WHITE, 15, 0.0, 75.0, id="above_initial_is_noop"),
        pytest.param(180, 100.0, BLACK, 0, 0.0, 100.0, id="zero_seconds_is_noop"),
    ],
)
def test_add_time_caps(
    initial, preset_remaining, color, amount, expected_added, expected_remaining
):
    """add_time tops up toward initial_seconds; headroom (and amount) caps the grant."""
    increment = 5 if initial == 60 else 0
    clock, _ = make_clock(initial, increment)
    if preset_remaining is not None:
        if color == WHITE:
            clock.white_remaining = preset_remaining
        else:
            clock.black_remaining = preset_remaining
    added = clock.add_time(color, amount)
    assert added == expected_added
    assert clock.remaining(color) == expected_remaining


def test_add_time_isolates_color():
    """Granting to one color leaves the other color's remaining untouched."""
    clock, _ = make_clock(180, 0)
    clock.white_remaining = 100.0
    clock.black_remaining = 100.0
    added = clock.add_time(PieceColor.BLACK, 15)
    assert added == 15.0
    assert clock.white_remaining == 100.0
    assert clock.black_remaining == 115.0


def test_add_time_to_flagged_player_is_noop():
    clock, _ = make_clock(180, 0)
    clock.white_remaining = 0.0
    clock.flagged = PieceColor.WHITE
    added = clock.add_time(PieceColor.WHITE, 15)
    assert added == 0.0
    assert clock.white_remaining == 0.0
    assert clock.flagged == PieceColor.WHITE


@pytest.mark.parametrize(
    "running_for, expected_side, expect_anchor",
    [
        pytest.param("white", PieceColor.WHITE, True, id="white_running"),
        pytest.param("black", PieceColor.BLACK, True, id="black_running"),
        pytest.param(None, None, False, id="nobody_running"),
    ],
)
def test_restore_from_server_adopts_known_wire_values_silently(
    running_for, expected_side, expect_anchor, caplog
):
    """The three spellings the server actually sends are routine sync, not a
    degraded state, so none of them may leave a warning in the crash-log buffer."""
    clock, ts = make_clock(300, 5)
    ts[0] = 9.0
    with caplog.at_level(logging.WARNING, logger="chess.backend"):
        clock.restore_from_server(120.0, 90.5, running_for)
    assert clock.white_remaining == 120.0
    assert clock.black_remaining == 90.5
    assert clock.running_for == expected_side
    assert clock.last_tick_at == (9.0 if expect_anchor else None)
    assert [r for r in caplog.records if r.name == "chess.backend"] == []


def test_restore_from_server_warns_but_still_stops_on_an_unknown_side(caplog):
    """A side the client cannot read is a degraded sync, not a crash: the clock
    still stops tolerantly, but silence used to make it look like the server had
    genuinely sent 'nobody is running' -- the warning names the value instead."""
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 4.0
    with caplog.at_level(logging.WARNING, logger="chess.backend"):
        clock.restore_from_server(120.0, 90.0, "sideways")
    assert clock.running_for is None
    assert clock.last_tick_at is None
    assert clock.white_remaining == 120.0
    assert clock.black_remaining == 90.0
    warnings = [r for r in caplog.records
                if r.name == "chess.backend" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "sideways" in warnings[0].getMessage()
