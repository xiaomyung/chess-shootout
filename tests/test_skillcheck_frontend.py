"""Frontend skill-check layer: the wheel controller's tap/auto-fail/result-hold
lifecycle, the generic overlay host that finishes and reports outcome, the
kind->controller registry, and the Frontend gate that defers a Shootout capture
into a wheel and applies the move on a win / locks it on a fail. Casual games
never gate, locked moves are blocked, and a landed ply clears the locks.
"""

import os
from collections import Counter

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.backend.utils import Square
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.skillcheck.overlay import SkillCheckOverlay
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.frontend.skillcheck.wheel_view import WheelController, WHEEL_RESULT_HOLD_MS
from chessshootout.skillcheck.coordinator import move_roll_key
from chessshootout.skillcheck.rng import ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import WheelChallenge, WHEEL_HUMAN_FLOOR_MS


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1100, 800))
    yield
    pg.quit()


def _always_in_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def _never_in_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=0.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def _tap():
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": (10, 10)})


# ---- wheel controller lifecycle --------------------------------------------

def test_wheel_tap_in_arc_lands_after_hold():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0)
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50)
    ctrl.handle_event(_tap())
    assert ctrl.landed is True
    assert ctrl.done is False
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50 + WHEEL_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_wheel_tap_outside_arc_fails():
    ctrl = WheelController(_never_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0)
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50)
    ctrl.handle_event(_tap())
    assert ctrl.landed is False


def test_wheel_sub_human_tap_fails():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0)
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) - 20)
    ctrl.handle_event(_tap())
    assert ctrl.landed is False


def test_wheel_auto_fails_at_deadline():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=1500)
    ctrl.update(1499)
    assert ctrl.landed is None
    ctrl.update(1500)
    assert ctrl.landed is False


def test_wheel_second_tap_is_ignored():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0)
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50)
    ctrl.handle_event(_tap())
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 60)
    ctrl.handle_event(_tap())
    assert ctrl.landed is True


def test_wheel_draw_does_not_crash():
    ctrl = WheelController(_always_in_arc(), pg.Rect(40, 40, 80, 80), now_ms=0)
    ctrl.update(200)
    ctrl.draw(pg.display.get_surface())
    assert ctrl.done is False


# ---- overlay host ----------------------------------------------------------

def test_overlay_finishes_and_reports_outcome():
    overlay = SkillCheckOverlay()
    done = []
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0)
    overlay.start(ctrl, ("ctx",), lambda context, landed: done.append((context, landed)))
    assert overlay.is_active() is True
    overlay.update(int(WHEEL_HUMAN_FLOOR_MS) + 30)
    ctrl.handle_event(_tap())
    overlay.update(int(WHEEL_HUMAN_FLOOR_MS) + 30 + WHEEL_RESULT_HOLD_MS)
    assert overlay.is_active() is False
    assert done == [(("ctx",), True)]


def test_overlay_cancel_clears():
    overlay = SkillCheckOverlay()
    overlay.start(WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0),
                  None, lambda context, landed: None)
    overlay.cancel()
    assert overlay.is_active() is False


# ---- registry --------------------------------------------------------------

def test_registry_builds_wheel_controller():
    ctrl = build_controller(SkillCheckKind.WHEEL, seed="s", cell_rect=pg.Rect(0, 0, 80, 80),
                            now_ms=0, deadline_ms=5000)
    assert isinstance(ctrl, WheelController)


def test_registry_returns_none_for_unbuilt_duel():
    assert build_controller(SkillCheckKind.DUEL, seed="s", cell_rect=pg.Rect(0, 0, 80, 80),
                            now_ms=0, deadline_ms=5000) is None


# ---- frontend gate integration ---------------------------------------------

def _start_local(app, variant):
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": 5, "increment_seconds": 0, "variant": variant})
    app.draw_frame()


def _set_queen_takes_pawn(app):
    b = app.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[4][3] = Piece(PieceType.QUEEN, PieceColor.WHITE)
    b.state[3][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    b.turn = PieceColor.WHITE
    b.move_history = []
    b.position_counts = Counter()
    b.position_counts[b._position_key()] = 1
    return Square(4, 3), Square(3, 3)


def _wheel_seed(backend, frm, to):
    for i in range(3000):
        seed = "w{}".format(i)
        roll = ply_roll(seed, move_roll_key(0, frm, to))
        if select_skillcheck(backend, frm, to, roll) == SkillCheckKind.WHEEL:
            return seed
    raise AssertionError("no wheel seed")


def test_casual_capture_does_not_gate():
    app = Frontend(1100, 800)
    _start_local(app, "casual")
    frm, to = _set_queen_takes_pawn(app)
    assert app._skillcheck_gate(frm, to) is False
    assert app.skillcheck_overlay.is_active() is False


def test_shootout_wheel_capture_defers_into_overlay():
    app = Frontend(1100, 800)
    _start_local(app, "shootout")
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.reset(enabled=True, seed=_wheel_seed(app.match.backend, frm, to))
    assert app._skillcheck_gate(frm, to) is True
    assert app.skillcheck_overlay.is_active() is True


def test_won_skillcheck_applies_move():
    app = Frontend(1100, 800)
    _start_local(app, "shootout")
    frm, to = _set_queen_takes_pawn(app)
    app._on_skillcheck_done((frm, to), True)
    assert len(app.match.move_history) == 1
    assert app.match.piece_at(to).type == PieceType.QUEEN


def test_failed_skillcheck_locks_move():
    app = Frontend(1100, 800)
    _start_local(app, "shootout")
    frm, to = _set_queen_takes_pawn(app)
    app._on_skillcheck_done((frm, to), False)
    assert len(app.match.move_history) == 0
    assert app.skillcheck.is_locked(frm, to) is True
    assert app._skillcheck_gate(frm, to) is True
    assert app.skillcheck_overlay.is_active() is False


def test_landed_ply_clears_locks():
    app = Frontend(1100, 800)
    _start_local(app, "shootout")
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.lock(Square(7, 4), Square(6, 4))
    app.match.try_move(Square(4, 3), Square(3, 3))
    app._on_move_landed(app.match.move_history[-1])
    assert len(app.skillcheck.locks) == 0


def test_board_marks_locked_target():
    app = Frontend(1100, 800)
    _start_local(app, "shootout")
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.lock(frm, to)
    app.board.selected_square = frm
    assert app.board._is_target_locked(to) is True
    assert app.board._is_target_locked(Square(5, 3)) is False
