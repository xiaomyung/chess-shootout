"""The client side of online skill-checks: the move HOLD gate (a capture/promotion
is sent and held, never optimistically applied; quiet moves fall through), the neutral
overlay opened from skill_check_required, firing it relays a payloadless shot, and the
server's move_applied(won)/skill_check_result(lost) drive the win-apply / fail-lock —
the client never paints its own verdict. Plus resume re-open at the right elapsed,
the lost-verdict watchdog, the held-move-rejection exit, spectate (no board lock), and
terminal/teardown hygiene. Server authority is covered in test_server_skillcheck.py;
here the server is faked and the client state machine is driven directly.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.backend.utils import coord_from_square
from chessshootout.frontend.frontend import Frontend
from chessshootout.online.client import Event
from chessshootout.server.protocol import (
    LockWire, PendingSkillCheckWire, SkillCheckSpectateMessage)
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome
from chessshootout.skillcheck.wheel import placement_square
from tests.helpers import BLACK, K, P, Q, R, WHITE, make_backend, piece, sq


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


class FakeOnlineClient:
    def __init__(self, room_id="room-1"):
        self.room_id = room_id
        self.state = "connected"
        self.opp_state = "connected"
        self.sent_moves = []
        self.shots = 0
        self.state_syncs = 0
        self.pings = 0

    def disconnect(self):
        self.state = "disconnected"

    def send_ping(self, ply):
        self.pings += 1

    def is_connected(self):
        return self.state == "connected"

    def is_server_silent(self):
        return False

    def heartbeat_interval(self):
        return 2.0

    def send_move(self, from_sq, to_sq, promotion=None):
        self.sent_moves.append((from_sq, to_sq, promotion))

    def send_skill_check_shot(self, client_elapsed_ms=0.0):
        self.shots += 1
        self.last_shot_elapsed = client_elapsed_ms

    def request_state_sync(self):
        self.state_syncs += 1

    def get_ping_ms(self):
        return None


def _online_payload(your_color="white"):
    return {
        "white_name": "alice", "black_name": "bob", "your_color": your_color,
        "time_minutes": 5, "increment_seconds": 0,
        "white_country": "", "black_country": "",
        "white_score": 0.0, "black_score": 0.0,
    }


def _online_app(your_color="white"):
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.online_client = FakeOnlineClient()
    app._start_online_game(_online_payload(your_color))
    return app


def _capture_board(app):
    """White Qd4, Black pawn d5 — Qxd5 is a legal vertical capture; kings only otherwise."""
    app.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    }, turn=WHITE)
    return sq(4, 3), sq(3, 3)


def _promo_capture_board(app):
    """White pawn e7, Black rook d8 — exd8=Q is a capturing promotion (preview SAN exd8=Q)."""
    app.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 0): piece(K, BLACK),
        sq(1, 4): piece(P, WHITE), sq(0, 3): piece(R, BLACK),
    }, turn=WHITE)
    return sq(1, 4), sq(0, 3)


def _ep_capture_board(app):
    """White pawn e5, Black pawn d5, EP target d6 — exd6 is an en-passant capture (SAN exd6)."""
    app.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(3, 4): piece(P, WHITE), sq(3, 3): piece(P, BLACK),
    }, turn=WHITE, ep_target=sq(2, 3))
    return sq(3, 4), sq(2, 3)


def _tap():
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": (10, 10)})


def _drive_verdict_hold(app):
    """Advance the overlay past the online result-hold so the deferred apply/lock runs."""
    app.skillcheck_overlay.update(pg.time.get_ticks() + 500)


def _required_payload(frm, to, kind="wheel", promotion=None, value_diff=3,
                      elapsed_ms=0.0, miss_count=0):
    return {
        "kind": kind, "seed": "seed-1", "value_diff": value_diff,
        "deadline_ms": 5000.0, "elapsed_ms": elapsed_ms, "miss_count": miss_count,
        "from": coord_from_square(frm), "to": coord_from_square(to),
        "promotion": promotion,
    }


def _spectate_payload(frm, to, kind="wheel", value_diff=3, promotion=None):
    return SkillCheckSpectateMessage(
        kind=kind, seed="seed-1", value_diff=value_diff, deadline_ms=5000.0,
        from_sq=coord_from_square(frm), to_sq=coord_from_square(to),
        promotion=promotion).model_dump(by_alias=True)


# ---- the move HOLD gate ----------------------------------------------------

def test_online_gate_holds_a_capture_without_applying_locally():
    app = _online_app()
    frm, to = _capture_board(app)
    held = app._skillcheck_gate(frm, to)
    assert held is True, "a capture is swallowed and held for the server"
    assert app.online_client.sent_moves == [("d4", "d5", None)], "the move is sent"
    assert app._pending_online_move == (frm, to, None)
    assert app.match.piece_at(frm) is not None, "nothing applied locally"
    assert len(app.match.move_history) == 0


def test_online_gate_lets_a_quiet_move_fall_through():
    app = _online_app()
    _capture_board(app)
    frm, to = sq(4, 3), sq(4, 4)
    held = app._skillcheck_gate(frm, to)
    assert held is False, "a quiet move is not held; the board applies it optimistically"
    assert app.online_client.sent_moves == [], "the gate itself sends nothing for a quiet move"


def test_online_gate_holds_a_promotion_with_the_chosen_letter():
    app = _online_app()
    app.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 7): piece(K, BLACK),
        sq(1, 0): piece(P, WHITE),
    }, turn=WHITE)
    frm, to = sq(1, 0), sq(0, 0)
    held = app._skillcheck_gate(frm, to, Q)
    assert held is True
    assert app.online_client.sent_moves == [("a7", "a8", "q")], "promotion sent as a letter"
    assert app._pending_online_move[:2] == (frm, to)


def test_online_gate_swallows_a_locked_move_without_sending():
    app = _online_app()
    frm, to = _capture_board(app)
    app.skillcheck.lock(frm, to)
    held = app._skillcheck_gate(frm, to)
    assert held is True
    assert app.online_client.sent_moves == [], "a locked move is swallowed, not re-sent"


def test_online_gate_ignores_an_illegal_destination():
    app = _online_app()
    frm, _ = _capture_board(app)
    held = app._skillcheck_gate(frm, sq(0, 0))
    assert held is False, "an illegal target falls through to the board's normal rejection"
    assert app.online_client.sent_moves == []


# ---- required -> neutral overlay -------------------------------------------

def test_required_opens_a_neutral_overlay_anchored_on_the_message_square():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    assert app.skillcheck_overlay.is_active()
    assert app._online_skillcheck[:2] == (frm, to)
    assert app._pending_online_move is None, "the hold becomes an open check"
    assert app.skillcheck_overlay._controller._online is True, "neutral mode"


def test_required_wheel_placement_matches_the_pure_engine():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, value_diff=8))
    engine = placement_square("seed-1", 8, app._placement_exclusions(frm, to), app.board.SIZE)
    assert app._skillcheck_target == (to if engine is None else sq(engine[0], engine[1]))


def test_firing_the_neutral_overlay_relays_a_payloadless_shot():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app.skillcheck_overlay.update(300)
    app.skillcheck_overlay.handle_event(_tap())
    assert app.online_client.shots == 1, "the tap sends one shot; the server adjudicates"
    assert app.skillcheck_overlay.is_active(), "the overlay stays up awaiting the verdict"


def test_required_aim_suppresses_the_victim_square():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="aim"))
    assert app.board.aim_suppressed_square == to


# ---- server verdict: WIN via move_applied ----------------------------------

def _move_applied(frm, to, ply, *, kind=None, won=None, san="Qxd5"):
    return {
        "from": coord_from_square(frm), "to": coord_from_square(to), "san": san,
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0, "running_for": "black"},
        "ply": ply, "skill_check_kind": kind, "skill_check_won": won,
    }


def test_won_move_applied_holds_then_applies_and_clears_locks():
    app = _online_app()
    frm, to = _capture_board(app)
    app.skillcheck.lock(sq(6, 0), sq(5, 0))
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    assert app._online_skillcheck is None
    assert app.match.piece_at(frm) is not None, "the move waits behind the verdict hold"
    _drive_verdict_hold(app)
    assert not app.skillcheck_overlay.is_active(), "after the hold the overlay tears down"
    assert app.match.piece_at(to) is not None and app.match.piece_at(frm) is None, "applied"
    assert not app.skillcheck.is_locked(sq(6, 0), sq(5, 0)), "an applied ply clears the locks"


def test_a_duplicate_winning_echo_applies_only_once():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    first = _move_applied(frm, to, 1, kind="wheel", won=True)
    app._handle_remote_move_applied(first)
    app._handle_remote_move_applied(first)
    _drive_verdict_hold(app)
    assert len(app.match.move_history) == 1, "the dedup guard applies the won move exactly once"
    assert app._online_skillcheck is None


# ---- server verdict: FAIL via skill_check_result ---------------------------

def _result(frm, to, won=False):
    return {"won": won, "from": coord_from_square(frm), "to": coord_from_square(to)}


def test_failed_result_holds_then_locks_the_move():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_skill_check_result(_result(frm, to))
    assert app._online_skillcheck is None
    assert not app.skillcheck.is_locked(frm, to), "the lock waits behind the verdict hold"
    _drive_verdict_hold(app)
    assert not app.skillcheck_overlay.is_active()
    assert app.skillcheck.is_locked(frm, to), "a failed move is greyed for the turn"
    assert app.match.piece_at(frm) is not None, "the move never applied"


def test_failed_aim_result_restores_the_suppressed_victim_after_the_hold():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="aim"))
    assert app.board.aim_suppressed_square == to
    app.board.restore_piece = MagicMock()
    app._handle_skill_check_result(_result(frm, to))
    app.board.restore_piece.assert_not_called()
    _drive_verdict_hold(app)
    assert app.board.aim_suppressed_square is None
    app.board.restore_piece.assert_called_once_with(to)


def test_failed_wheel_result_does_not_restore_a_piece():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="wheel"))
    app.board.restore_piece = MagicMock()
    app._handle_skill_check_result(_result(frm, to))
    _drive_verdict_hold(app)
    app.board.restore_piece.assert_not_called()


def test_a_result_for_a_different_move_is_ignored():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_skill_check_result(_result(sq(1, 1), sq(2, 2)))
    assert app.skillcheck_overlay.is_active(), "a mismatched result never tears down my check"
    assert app._online_skillcheck is not None


def test_spectate_collision_guard_routes_a_matching_result_to_the_spectate_branch():
    """A spectated check sets BOTH _online_skillcheck and _online_spectate_kind on the SAME
    squares (see _open_spectate_overlay). The _online_spectate_kind-is-None clause in
    _is_my_open_check is the tie-breaker: a fail on those squares must take the SPECTATE
    branch (show "Opponent missed!", never lock my own board), not the mover branch. Without
    the guard the spectator would grey out a move it never made."""
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    assert app._online_skillcheck is not None and app._online_skillcheck[:2] == (frm, to), \
        "spectate sets the open-check tuple on the same squares as the spectate marker"
    assert app._online_spectate_kind is not None
    assert app._is_my_open_check(frm, to) is False, "the guard refuses to claim it as mine"
    app.toast.show = MagicMock()
    app._handle_skill_check_result(_result(frm, to))
    app.toast.show.assert_called_once_with("Opponent missed!")
    _drive_verdict_hold(app)
    assert not app.skillcheck.is_locked(frm, to), "the spectator never locks its own board"
    assert app.match.piece_at(frm) is not None and app.match.piece_at(to) is not None, \
        "no move applied; the spectated fail only ever animated the opponent's whiff"


# ---- spectating the opponent's check ---------------------------------------

def test_spectate_opens_a_passive_overlay_and_leaves_my_board_live():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="aim"))
    assert app._online_spectate_kind == SkillCheckKind.AIM
    assert app.skillcheck_overlay.is_active(), "the opponent's check is mirrored, not hidden"
    assert app.skillcheck_overlay.is_passive(), "but read-only"
    assert app._skillcheck_swallows_input() is False, "my board stays live for premoves"
    assert len(app.skillcheck.locks) == 0


def test_spectate_overlay_matches_the_pure_engine_render_square():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel", value_diff=8))
    engine = placement_square("seed-1", 8, app._placement_exclusions(frm, to), app.board.SIZE)
    assert app._skillcheck_target == (to if engine is None else sq(engine[0], engine[1])), \
        "the spectator reconstructs the same relocated square as the mover"


def test_spectate_shot_freezes_the_wheel_needle_at_the_relayed_elapsed():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._handle_skill_check_spectate_shot({"elapsed_ms": 742.0, "miss_count": 0, "won": True})
    assert app.skillcheck_overlay._controller._frozen_override == 742.0


def test_spectate_aim_miss_relays_a_dry_shot_and_escalates():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="aim"))
    ctrl = app.skillcheck_overlay._controller
    app._handle_skill_check_spectate_shot({"elapsed_ms": 300.0, "miss_count": 0, "won": False})
    assert ctrl.miss_count == 1, "a relayed miss escalates the spectated reticle"
    assert ctrl._shot_render == (300.0, 0), "frozen at the mover's fired position"


def test_opponent_fail_result_holds_red_then_clears_without_locking_me():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._handle_skill_check_result(_result(frm, to))
    assert app._online_spectate_kind is None, "the verdict clears the spectate marker"
    assert app.skillcheck_overlay.is_active(), "the red verdict holds before teardown"
    _drive_verdict_hold(app)
    assert not app.skillcheck_overlay.is_active()
    assert len(app.skillcheck.locks) == 0, "the spectator never locks its own board"


def test_opponent_win_move_applied_holds_green_then_applies():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    assert app._online_spectate_kind is None
    assert app.match.piece_at(to).color == BLACK, "the capture waits behind the green hold"
    _drive_verdict_hold(app)
    assert not app.skillcheck_overlay.is_active()
    assert app.match.piece_at(to).color == WHITE, "the opponent's won capture then applies"


# ---- resume re-open --------------------------------------------------------

def _resumed(pending=None, locks=None, skillcheck_log=None):
    """Mirror the real /resume payload: model_dump() (field-name keys), like the client sees."""
    payload = {
        "move_history": [], "fen": "8/8/8/8/8/8/8/8 w - - 0 1",
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0, "running_for": "white"},
        "pending_skillcheck": pending, "skillcheck_locks": locks or [],
    }
    if skillcheck_log is not None:
        payload["skillcheck_log"] = skillcheck_log
    return payload


def _pending_wire(kind, frm, to, color, *, elapsed_ms=0.0, miss_count=0, promo=None):
    return PendingSkillCheckWire(
        kind=kind, seed="s", value_diff=3, deadline_ms=5000.0, elapsed_ms=elapsed_ms,
        miss_count=miss_count, color=color, from_sq=frm, to_sq=to,
        promotion=promo).model_dump()


def _lock_wire(frm, to):
    return LockWire(from_sq=frm, to_sq=to).model_dump()


def test_resume_reopens_my_pending_check_at_the_right_elapsed():
    app = _online_app("white")
    pending = _pending_wire("wheel", "d4", "d5", "white", elapsed_ms=1200.0)
    app._handle_game_resumed(_resumed(pending=pending))
    assert app.skillcheck_overlay.is_active()
    assert app._online_skillcheck[:2] == (sq(4, 3), sq(3, 3))
    ctrl = app.skillcheck_overlay._controller
    assert ctrl._online is True
    assert pg.time.get_ticks() - ctrl.start_ms == pytest.approx(1200, abs=80), "back-dated start"
    frm, to = sq(4, 3), sq(3, 3)
    engine = placement_square("s", 3, app._placement_exclusions(frm, to), app.board.SIZE)
    assert app._skillcheck_target == (to if engine is None else sq(engine[0], engine[1])), \
        "resume renders the same engine-seeded square as the live gate"


def test_resume_of_an_opponent_pending_opens_a_passive_spectate_overlay():
    app = _online_app("white")
    pending = _pending_wire("aim", "d5", "d4", "black", elapsed_ms=500.0)
    app._handle_game_resumed(_resumed(pending=pending))
    assert app.skillcheck_overlay.is_active()
    assert app.skillcheck_overlay.is_passive()
    assert app._online_spectate_kind == SkillCheckKind.AIM
    ctrl = app.skillcheck_overlay._controller
    assert pg.time.get_ticks() - ctrl.start_ms == pytest.approx(500, abs=80), "back-dated start"


def test_resume_applies_server_display_locks():
    app = _online_app("white")
    app._handle_game_resumed(_resumed(locks=[_lock_wire("e2", "e4")]))
    assert app.skillcheck.is_locked(sq(6, 4), sq(4, 4))


# ---- self-heal watchdog ----------------------------------------------------

def test_watchdog_tears_down_a_stranded_overlay_and_resyncs():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._online_skillcheck_opened_ms = pg.time.get_ticks() - 5000 - 4000 - 100
    app._tick_skillcheck_watchdog()
    assert not app.skillcheck_overlay.is_active(), "a lost verdict can't strand the overlay"
    assert app._online_skillcheck is None
    assert app.online_client.state_syncs == 1


def test_watchdog_does_not_fire_before_the_threshold():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._online_skillcheck_opened_ms = pg.time.get_ticks() - 2000
    app._tick_skillcheck_watchdog()
    assert app.skillcheck_overlay.is_active()
    assert app.online_client.state_syncs == 0


# ---- held-move rejection exit ----------------------------------------------

def test_held_move_rejected_as_desync_clears_and_resyncs():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_online_error({"reason": "invalid_move_format"})
    assert app._pending_online_move is None, "the stranded hold is released"
    assert app.online_client.state_syncs == 1


def test_held_move_rejected_as_locked_clears_without_resync():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_online_error({"reason": "move_locked"})
    assert app._pending_online_move is None
    assert app.online_client.state_syncs == 0, "a benign rejection just re-enables input"


# ---- terminal + teardown hygiene -------------------------------------------

def test_a_terminal_result_tears_down_and_clears_all_online_fields():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_online_result({"reason": "resignation", "winner_color": "black"})
    assert not app.skillcheck_overlay.is_active()
    assert app._online_skillcheck is None
    assert app._online_spectate_kind is None
    assert app._pending_online_move is None
    assert app._online_skillcheck_opened_ms is None


def test_reset_to_new_game_clears_every_online_field():
    app = _online_app()
    app._pending_online_move = (sq(4, 3), sq(3, 3), None)
    app._online_skillcheck = (sq(4, 3), sq(3, 3), None, SkillCheckKind.WHEEL)
    app._online_spectate_kind = SkillCheckKind.AIM
    app._online_skillcheck_opened_ms = 123
    app._reset_to_new_game()
    assert app._pending_online_move is None
    assert app._online_skillcheck is None
    assert app._online_spectate_kind is None
    assert app._online_skillcheck_opened_ms is None


# ---- dispatch wiring + local-branch sentinel -------------------------------

def test_handle_online_event_routes_required_to_the_overlay():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_online_event(Event("skill_check_required", _required_payload(frm, to)))
    assert app._online_skillcheck is not None


def test_handle_online_event_routes_spectate_and_spectate_shot():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_online_event(
        Event("skill_check_spectate", _spectate_payload(frm, to, kind="wheel")))
    assert app._online_spectate_kind == SkillCheckKind.WHEEL
    app._handle_online_event(Event(
        "skill_check_spectate_shot", {"elapsed_ms": 800.0, "miss_count": 0, "won": True}))
    assert app.skillcheck_overlay._controller._frozen_override == 800.0


def test_escape_is_not_swallowed_while_spectating():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._dismiss_top_modal = MagicMock(return_value=False)
    app._on_resign = MagicMock()
    app._handle_escape()
    app._on_resign.assert_called_once()


def test_titlebar_click_during_a_check_reaches_the_chrome_not_a_shot():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    pg.event.clear()
    pg.event.post(pg.event.Event(
        pg.MOUSEBUTTONDOWN, {"button": 1, "pos": (app.window_width // 2, 4)}))
    app.check_events()
    assert app.online_client.shots == 0, "a title-bar click is not swallowed as a shot"
    pg.event.clear()


def test_board_click_during_a_check_still_fires_a_shot():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app.skillcheck_overlay.update(pg.time.get_ticks())
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": (500, 600)}))
    app.check_events()
    assert app.online_client.shots == 1, "clicks below the title bar still register as shots"
    pg.event.clear()


def test_heartbeat_is_suppressed_while_a_won_move_is_deferred_behind_the_hold():
    app = _online_app()
    app._last_heartbeat_sent_ms = -100000  # a ping is due
    app._online_verdict_action = lambda: None  # a verdict is mid result-hold
    app._send_heartbeat_if_due()
    assert app.online_client.pings == 0, \
        "no stale-ply ping during the hold, or the server resyncs and the capture teleports"
    app._online_verdict_action = None
    app._send_heartbeat_if_due()
    assert app.online_client.pings == 1, "the heartbeat resumes once the move has applied"


def test_result_during_the_verdict_hold_flushes_the_won_movers_move():
    """A move_applied(won) opens a 200ms verdict hold with a deferred apply action. If a result
    arrives DURING that hold, _handle_online_result must flush the pending action BEFORE tearing
    down the overlay — otherwise the winning capture is discarded (board a ply behind, the SAN
    and the win-record lost). This is the A2 regression."""
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="wheel"))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    assert app._online_verdict_action is not None, "the apply is deferred behind the hold"
    assert len(app.match.move_history) == 0, "and has not applied yet"
    app._handle_online_result({"reason": "resignation", "winner_color": "black"})
    assert len(app.match.move_history) == 1, "the deferred capture is flushed, not discarded"
    assert app.match.move_history[-1].san == "Qxd5", "and the real SAN lands"
    assert app.match.piece_at(to) is not None and app.match.piece_at(frm) is None, "applied"
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")], "the win is recorded"
    assert app._online_verdict_action is None, "the pending action is consumed exactly once"


def test_result_during_the_spectate_verdict_hold_flushes_the_opponents_move():
    """Same flush on the spectator side: an opponent's won capture deferred behind the green
    hold must still apply when a result lands mid-hold."""
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    assert app._online_verdict_action is not None
    assert app.match.piece_at(to).color == BLACK, "the capture waits behind the green hold"
    app._handle_online_result({"reason": "resignation", "winner_color": "white"})
    assert len(app.match.move_history) == 1, "the opponent's deferred capture is flushed"
    assert app.match.piece_at(to).color == WHITE, "the won capture applied"
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]


def test_local_shootout_still_takes_the_local_branch():
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.online_client = FakeOnlineClient()
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": 5, "increment_seconds": 0})
    assert app.online_client is None, "starting a local game drops any lingering online client"
    app.skillcheck.seed = "force"
    app.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    }, turn=WHITE)
    held = app._skillcheck_gate(sq(4, 3), sq(3, 3))
    assert held is True, "a local capture opens an overlay, not a server hold"
    assert app.skillcheck_overlay.is_active()


# ---- the client-side skill-check log (PGN history) -------------------------

def test_won_move_applied_records_the_outcome():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="wheel"))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    _drive_verdict_hold(app)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]


def test_a_duplicate_winning_echo_logs_the_outcome_once():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    first = _move_applied(frm, to, 1, kind="wheel", won=True)
    app._handle_remote_move_applied(first)
    _drive_verdict_hold(app)
    app._handle_remote_move_applied(first)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]


def test_a_quiet_move_applied_records_nothing():
    app = _online_app()
    _capture_board(app)
    app._handle_remote_move_applied(_move_applied(sq(6, 4), sq(4, 4), 1, san="e4"))
    assert app._skillcheck_log == []


def test_failed_result_records_the_whiffed_move_and_kind():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="wheel"))
    app._handle_skill_check_result(_result(frm, to))
    _drive_verdict_hold(app)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", False, "Qxd5")]


def test_failed_promotion_capture_logs_the_full_promotion_san():
    """A whiffed capturing promotion records preview_san(from,to,'q') against the un-applied
    board — the promotion suffix must survive (exd8=Q, not exd8)."""
    app = _online_app()
    frm, to = _promo_capture_board(app)
    app._skillcheck_gate(frm, to, Q)
    app._handle_skill_check_required(_required_payload(frm, to, kind="wheel", promotion="q"))
    assert app._online_skillcheck[2] == Q, "the chosen promotion rides in the open-check tuple"
    app._handle_skill_check_result(_result(frm, to))
    _drive_verdict_hold(app)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", False, "exd8=Q")]
    assert app.match.piece_at(frm).type == P, "the whiffed pawn never promoted nor moved"


def test_failed_en_passant_capture_logs_the_ep_san():
    """A whiffed en-passant capture logs the EP SAN (exd6) built from the un-applied board."""
    app = _online_app()
    frm, to = _ep_capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="aim"))
    app._handle_skill_check_result(_result(frm, to))
    _drive_verdict_hold(app)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "aim", False, "exd6")]


def test_resumed_log_defaults_a_missing_san_to_empty():
    """A winning outcome legitimately omits the san key on the wire; _apply_resumed_skillcheck_log
    must default it to "" via .get, not KeyError."""
    app = _online_app("white")
    app._apply_resumed_skillcheck_log([{"ply": 1, "kind": "wheel", "won": True}])
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]


def test_spectated_fail_records_the_opponents_whiff_with_the_spectate_kind():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="aim"))
    app._handle_skill_check_result(_result(frm, to))
    _drive_verdict_hold(app)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "aim", False, "Qxd5")]


def test_spectated_win_records_the_outcome():
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    _drive_verdict_hold(app)
    assert app._skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]


def test_skill_check_result_is_ignored_while_resyncing():
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._resyncing = True
    app._handle_skill_check_result(_result(frm, to))
    assert app._skillcheck_log == [], "a fail during resync isn't logged; resume is authoritative"


def test_skill_check_required_is_ignored_while_resyncing():
    """While resyncing, a stray skill_check_required must not open an overlay or claim an open
    check — game_resumed reconstructs the authoritative pending state."""
    app = _online_app()
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._resyncing = True
    app._handle_skill_check_required(_required_payload(frm, to))
    assert not app.skillcheck_overlay.is_active(), "no overlay opens during a resync"
    assert app._online_skillcheck is None, "no open-check state is set mid-resync"


def test_skill_check_spectate_is_ignored_while_resyncing():
    """Same resync gate for the opponent's check: no passive overlay, no spectate marker."""
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._resyncing = True
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="aim"))
    assert not app.skillcheck_overlay.is_active(), "no spectate overlay opens during a resync"
    assert app._online_spectate_kind is None, "no spectate marker is set mid-resync"


def test_spectate_shot_is_ignored_while_resyncing():
    """A spectate_shot arriving mid-resync is dropped (the existing _online_spectate_kind /
    _resyncing guard) — the frozen-override stays unset."""
    app = _online_app("black")
    frm, to = _capture_board(app)
    app._handle_skill_check_spectate(_spectate_payload(frm, to, kind="wheel"))
    app._resyncing = True
    app._handle_skill_check_spectate_shot({"elapsed_ms": 500.0, "miss_count": 0, "won": True})
    assert app.skillcheck_overlay._controller._frozen_override is None, "the shot is dropped"


def test_resume_replaces_the_skillcheck_log_from_the_server():
    app = _online_app("white")
    app._skillcheck_log = [
        SkillCheckOutcome(1, "wheel", True, ""),
        SkillCheckOutcome(2, "aim", False, "Qxd5"),
        SkillCheckOutcome(3, "wheel", True, "")]
    wire = [{"ply": 1, "kind": "aim", "won": True, "san": ""},
            {"ply": 2, "kind": "wheel", "won": False, "san": "Rxe5"}]
    app._handle_game_resumed(_resumed(skillcheck_log=wire))
    assert app._skillcheck_log == [
        SkillCheckOutcome(1, "aim", True, ""),
        SkillCheckOutcome(2, "wheel", False, "Rxe5")]


def test_resume_without_a_log_key_clears_to_empty():
    app = _online_app("white")
    app._skillcheck_log = [SkillCheckOutcome(1, "wheel", True, "")]
    app._handle_game_resumed(_resumed())
    assert app._skillcheck_log == []


def test_online_takeback_drops_the_undone_plys_outcome():
    app = _online_app("white")
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    _drive_verdict_hold(app)
    assert len(app.match.move_history) == 1 and len(app._skillcheck_log) == 1
    app._handle_takeback_applied({
        "ply": 0,
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0, "running_for": "white"}})
    assert app._skillcheck_log == []


def test_a_live_log_round_trips_through_the_resume_wire_unchanged():
    app = _online_app("white")
    frm, to = _capture_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to, kind="wheel"))
    app._handle_remote_move_applied(_move_applied(frm, to, 1, kind="wheel", won=True))
    _drive_verdict_hold(app)
    live = list(app._skillcheck_log)
    other = _online_app("black")
    wire = [{"ply": e.ply, "kind": e.kind, "won": e.won, "san": e.san} for e in live]
    other._handle_game_resumed(_resumed(skillcheck_log=wire))
    assert other._skillcheck_log == live
