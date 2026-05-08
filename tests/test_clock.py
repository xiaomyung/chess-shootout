import pytest

from backend.clock import Clock
from pieces import PieceColor

from tests.helpers import (
    BLACK, WHITE, K, Q, R, B, N, P,
    make_backend, piece, sq, play_moves,
)


def fake_now(ts):
    return lambda: ts[0]


def make_clock(initial=300, increment=5, ts=None):
    ts = ts if ts is not None else [0.0]
    return Clock.create(initial, increment, now_provider=fake_now(ts)), ts


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
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 2.0
    clock.on_move_made(PieceColor.WHITE)
    # Debited 2.0, then +5 increment.
    assert clock.white_remaining == pytest.approx(303.0)
    assert clock.running_for == PieceColor.BLACK
    assert clock.last_tick_at == 2.0
    assert clock.black_remaining == 300


def test_on_move_made_black_symmetric():
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 2.0
    clock.on_move_made(PieceColor.WHITE)
    ts[0] = 5.0
    clock.on_move_made(PieceColor.BLACK)
    # Black was running 3 seconds, then +5 increment.
    assert clock.black_remaining == pytest.approx(302.0)
    assert clock.running_for == PieceColor.WHITE
    assert clock.last_tick_at == 5.0


def test_stop_clears_running_state():
    clock, _ = make_clock()
    clock.start()
    clock.stop()
    assert clock.running_for is None
    assert clock.last_tick_at is None


def test_remaining_returns_correct_side():
    clock, _ = make_clock(60, 0)
    clock.white_remaining = 42
    clock.black_remaining = 17
    assert clock.remaining(PieceColor.WHITE) == 42
    assert clock.remaining(PieceColor.BLACK) == 17


def test_snapshot_restore_round_trip():
    clock, ts = make_clock(300, 5)
    clock.start()
    ts[0] = 4.0
    clock.tick()
    snap = clock.snapshot()
    # Mutate the clock arbitrarily.
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
    # Snapshot should reflect pre-move state (not yet debited / no increment).
    snap_white, snap_black, snap_running, snap_last_tick, snap_flagged = entry.prev_clock_snapshot
    assert snap_white == pre_white
    assert snap_running == PieceColor.WHITE
    assert snap_last_tick == 0.0
    # Clock now reflects post-move state: white debited 2s + 5s increment, black to move.
    assert bk.clock.white_remaining == pytest.approx(303.0)
    assert bk.clock.running_for == PieceColor.BLACK


def test_promotion_pending_does_not_snapshot_clock_yet():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(1, 0): piece(P, WHITE),
    })
    ts = [0.0]
    bk.setup_clock(300, 5, now_provider=fake_now(ts))
    result = bk.try_move(sq(1, 0), sq(0, 0))
    assert result.promotion_required
    # Pending entry has no snapshot yet (it's appended without _finalize_move running).
    assert bk.move_history[-1].prev_clock_snapshot is None
    # Clock kept running for white (move not finalized).
    assert bk.clock.running_for == PieceColor.WHITE


def test_clock_runs_during_pending_promotion():
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
    # After promote -> _finalize_move -> on_move_made: tick again (no extra elapsed),
    # then +5 increment, switch to black.
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
    # Now black is on the clock with 10s remaining.
    ts[0] = 100.0
    bk.tick_clock()
    assert bk.clock.flagged == PieceColor.BLACK
    assert bk.game_result() == "white_wins_on_time"


# DEVIATION: FIDE 6.9 says "flag fall in a position the opponent cannot mate" is a draw.
# We match chess.com / lichess: timeout always loses, regardless of remaining material.
def test_timeout_outranks_insufficient_material_DEVIATION():
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(0, 4): piece(K, BLACK),
        sq(0, 0): piece(B, BLACK),
    })
    ts = [0.0]
    bk.setup_clock(initial_seconds=1.0, increment_seconds=0, now_provider=fake_now(ts))
    ts[0] = 2.0
    bk.tick_clock()
    assert bk.game_result() == "black_wins_on_time"


def test_no_tick_after_game_over():
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
    pre_white = bk.clock.white_remaining
    ts[0] = 999.0
    bk.tick_clock()
    assert bk.clock.white_remaining == pre_white


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
    # Just assert we got back to one-pawn-pre state without exception.
    assert bk.piece_at(sq(6, 0)) is not None
    assert bk.piece_at(sq(5, 0)) is None


def test_clock_stops_on_checkmate():
    # Set up a position where white can deliver mate with the queen.
    bk = make_backend({
        sq(7, 7): piece(K, WHITE),
        sq(6, 6): piece(Q, WHITE),
        sq(0, 0): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    ts = [0.0]
    bk.setup_clock(60, 5, now_provider=fake_now(ts))
    # Qg7 -> b7 is mate? Let's be explicit: move Q from (6,6)=g2 to (1,6)=g7,
    # then to deliver mate against Ka8 we'd want different geometry. Easier: just
    # use a pre-built mate-in-one.
    # Reset to a clearer mate-in-one: white Kg6 + Qa6, black Kh8.
    bk = make_backend({
        sq(7, 4): piece(K, WHITE),
        sq(2, 6): piece(K, WHITE),
        sq(2, 0): piece(Q, WHITE),
        sq(0, 7): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    # Two kings on white side is illegal — fix with a single king setup.
    bk = make_backend({
        sq(2, 6): piece(K, WHITE),
        sq(2, 0): piece(Q, WHITE),
        sq(0, 7): piece(K, BLACK),
    }, turn=WHITE, castling_rights={"WK": False, "WQ": False, "BK": False, "BQ": False})
    ts = [0.0]
    bk.setup_clock(60, 5, now_provider=fake_now(ts))
    # Qa6 -> Qa7 / Qh1? Easier: Qa6-Qh6 or Qa6-Qa8.
    # Black Kh8 with white Kg6: any back-rank queen check on the 8th rank with
    # king covering g7 is mate. Qa8# fits: Qa8 covers the 8th rank, king g6
    # covers g7/h7/g8.
    result = bk.try_move(sq(2, 0), sq(0, 0))
    assert result.legal
    assert result.is_checkmate
    assert bk.game_result() == "white_wins"
    # Clock should have stopped (no further on_move_made on a mate).
    assert bk.clock.running_for is None
