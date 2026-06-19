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
from chessshootout.domain.premoves import Premove
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


# ---- frontend gate integration ---------------------------------------------

def _start_local(app):
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": 5, "increment_seconds": 0})
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


def test_shootout_wheel_capture_defers_into_overlay():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.reset(enabled=True, seed=_wheel_seed(app.match.backend, frm, to))
    assert app._skillcheck_gate(frm, to) is True
    assert app.skillcheck_overlay.is_active() is True


def test_won_skillcheck_applies_move():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app._on_skillcheck_done((frm, to), True)
    assert len(app.match.move_history) == 1
    assert app.match.piece_at(to).type == PieceType.QUEEN


def test_failed_skillcheck_locks_move():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app._on_skillcheck_done((frm, to), False)
    assert len(app.match.move_history) == 0
    assert app.skillcheck.is_locked(frm, to) is True
    assert app._skillcheck_gate(frm, to) is True
    assert app.skillcheck_overlay.is_active() is False


def test_failed_skillcheck_fires_the_miss_fx():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app._on_skillcheck_done((frm, to), False)
    fx = app.board.effects
    fired = any(c.get("miss") for c in fx.captures) or bool(fx.callouts)
    assert fired, "a failed skill-check fires the gun-and-miss FX"
    assert fx.held_squares() == set(), "the victim stays on the board after a miss"


def _shootout_with_wheel(app):
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.reset(enabled=True, seed=_wheel_seed(app.match.backend, frm, to))
    return frm, to


def test_premoved_capture_defers_into_the_skillcheck():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _shootout_with_wheel(app)
    app.board.premoves = [Premove(frm, to, app.match.piece_at(frm))]
    app.board.premove_color = app.match.current_turn()
    fired = app.board.try_apply_next_premove()
    assert fired is False, "a premove that triggers a skill-check does not apply silently"
    assert app.skillcheck_overlay.is_active() is True, "it defers into the wheel overlay"
    assert app.board.premoves == [], "the lone premove is consumed into the skill-check"
    assert len(app.match.move_history) == 0, "no ply lands until the skill-check resolves"


def test_premove_chain_survives_a_won_skillcheck():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _shootout_with_wheel(app)
    follow = Premove(Square(7, 4), Square(6, 4), app.match.piece_at(Square(7, 4)))
    app.board.premoves = [Premove(frm, to, app.match.piece_at(frm)), follow]
    app.board.premove_color = app.match.current_turn()
    app.board.try_apply_next_premove()
    assert app.skillcheck_overlay.is_active() is True
    assert app.board.premoves == [follow], "the rest of the chain survives the deferral"
    app._on_skillcheck_done((frm, to), True)
    assert len(app.match.move_history) == 1, "the won move lands"
    assert app.board.premoves == [follow], "and the chain lives on for the next turn"


def test_premove_chain_is_dropped_on_a_failed_skillcheck():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _shootout_with_wheel(app)
    follow = Premove(Square(7, 4), Square(6, 4), app.match.piece_at(Square(7, 4)))
    app.board.premoves = [Premove(frm, to, app.match.piece_at(frm)), follow]
    app.board.premove_color = app.match.current_turn()
    app.board.try_apply_next_premove()
    assert app.board.premoves == [follow]
    app._on_skillcheck_done((frm, to), False)
    assert len(app.match.move_history) == 0, "the failed move does not land"
    assert app.skillcheck.is_locked(frm, to) is True
    assert app.board.premoves == [], "a failed skill-check drops the rest of the chain"


def test_failed_click_move_skillcheck_keeps_opponents_premove():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    opp = Premove(Square(0, 4), Square(0, 5), app.match.piece_at(Square(0, 4)))
    app.board.premoves = [opp]
    app.board.premove_color = PieceColor.BLACK
    app._on_skillcheck_done((frm, to), False)
    assert app.board.premoves == [opp], "a failed skill-check must not wipe the opponent's premove"
    assert app.skillcheck.is_locked(frm, to) is True


# ---- promotion: picker before the wheel ------------------------------------

def _set_white_pawn_promo(app):
    b = app.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][0] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[1][4] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.turn = PieceColor.WHITE
    b.move_history = []
    b.position_counts = Counter()
    b.position_counts[b._position_key()] = 1
    return Square(1, 4), Square(0, 4)


def _promo_seed(backend, frm, to, want):
    for i in range(8000):
        seed = "p{}".format(i)
        roll = ply_roll(seed, move_roll_key(0, frm, to))
        if select_skillcheck(backend, frm, to, roll) == want:
            return seed
    raise AssertionError("no promo seed for {}".format(want))


def test_shootout_promotion_shows_picker_before_applying():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.skillcheck.reset(enabled=True, seed="seed")
    app.board.handle_click(frm)
    app.board.handle_click(to)
    assert app.board.pending_promotion_square == to, "the piece picker comes up first"
    assert app.board._promotion_from == frm
    assert app.match.piece_at(frm) is not None, "nothing is applied until a piece is chosen"
    assert app.match.piece_at(to) is None


def test_shootout_promotion_always_fires_the_wheel():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.skillcheck.reset(enabled=True, seed="anything")
    app.board.handle_click(frm)
    app.board.handle_click(to)
    app.board.pick_promotion(PieceType.ROOK)
    assert app.skillcheck_overlay.is_active() is True, "promotions are 100% wheel now"
    assert len(app.match.move_history) == 0, "nothing applies until the wheel resolves"


def test_failed_promotion_skillcheck_promotes_nothing():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.skillcheck.reset(enabled=True, seed=_promo_seed(app.match.backend, frm, to,
                                                        SkillCheckKind.WHEEL))
    app.board.handle_click(frm)
    app.board.handle_click(to)
    app.board.pick_promotion(PieceType.ROOK)
    assert app.skillcheck_overlay.is_active() is True
    app._on_skillcheck_done((frm, to, PieceType.ROOK), False)
    assert app.match.piece_at(frm).type == PieceType.PAWN, "a failed wheel promotes to nothing"
    assert app.match.piece_at(to) is None
    assert app.skillcheck.is_locked(frm, to) is True


def test_won_promotion_skillcheck_uses_the_chosen_piece():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.skillcheck.reset(enabled=True, seed=_promo_seed(app.match.backend, frm, to,
                                                        SkillCheckKind.WHEEL))
    app.board.handle_click(frm)
    app.board.handle_click(to)
    app.board.pick_promotion(PieceType.ROOK)
    app._on_skillcheck_done((frm, to, PieceType.ROOK), True)
    assert app.match.piece_at(to).type == PieceType.ROOK, "a won wheel promotes to the chosen piece"


def test_wheel_period_scales_with_capture_material():
    from chessshootout.skillcheck.wheel import WHEEL_PERIOD_MS
    app = Frontend(1100, 800)
    _start_local(app)
    b = app.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][0] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[4][3] = Piece(PieceType.QUEEN, PieceColor.WHITE)
    b.state[3][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    qxp = app._wheel_period(Square(4, 3), Square(3, 3), None)
    b.state[4][3] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.state[3][2] = Piece(PieceType.QUEEN, PieceColor.BLACK)
    pxq = app._wheel_period(Square(4, 3), Square(3, 2), None)
    assert qxp < WHEEL_PERIOD_MS < pxq, "strong-eats-weak spins faster, weak-eats-strong slower"


def test_promotion_wheel_period_uses_the_chosen_piece():
    from chessshootout.skillcheck.wheel import period_for_diff
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    queen = app._wheel_period(frm, to, PieceType.QUEEN)
    knight = app._wheel_period(frm, to, PieceType.KNIGHT)
    assert queen == pytest.approx(period_for_diff(9))
    assert knight == pytest.approx(period_for_diff(3))
    assert queen < knight, "promoting to a queen is the hardest (fastest) wheel"


def test_failed_non_capturing_promotion_bumps_instead_of_shooting():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.board.trigger_skillcheck_fail(frm, to)
    assert any(a.bump for a in app.board.animations), "a quiet promotion lunges and bumps back"
    assert app.board.effects.captures == [], "and never fires the gun (no victim to shoot)"


def test_failed_capture_still_fires_the_gun_miss_not_a_bump():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.board.trigger_skillcheck_fail(frm, to)
    assert app.board.effects.captures, "a failed capture still fires the gun"
    assert not any(a.bump for a in app.board.animations), "no bump when there is a victim"


# ---- lifecycle teardown (bug-hunt fixes) -----------------------------------

def test_undo_clears_skillcheck_locks():
    app = Frontend(1100, 800)
    _start_local(app)
    app.skillcheck.lock(Square(4, 3), Square(3, 3))
    assert len(app.skillcheck.locks) == 1
    app._on_undo()
    assert len(app.skillcheck.locks) == 0, "a stale lock must not survive an undo"


def test_reset_to_new_game_tears_down_skillcheck_state():
    app = Frontend(1100, 800)
    _start_local(app)
    app.skillcheck.lock(Square(4, 3), Square(3, 3))
    ctrl = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), now_ms=0)
    app.skillcheck_overlay.start(ctrl, (Square(4, 3), Square(3, 3)), lambda c, landed: None)
    app._reset_to_new_game()
    assert app.skillcheck_overlay.is_active() is False, "reset cancels any in-flight overlay"
    assert len(app.skillcheck.locks) == 0, "reset clears the lock set"


def test_game_over_cancels_active_wheel_without_firing_its_move():
    app = Frontend(1100, 800)
    _start_local(app)
    landed = []
    ctrl = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), now_ms=0)
    app.skillcheck_overlay.start(ctrl, (Square(4, 3), Square(3, 3)),
                                 lambda c, won: landed.append(won))
    app.manual_result = "white_wins_by_resignation"
    app.draw_frame()
    assert app.skillcheck_overlay.is_active() is False, "the wheel is cancelled when the game ends"
    assert landed == [], "its on_done never fires a stale move into the finished game"


def test_skillcheck_miss_aims_at_the_en_passant_pawn():
    app = Frontend(1100, 800)
    _start_local(app)
    b = app.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[3][4] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.state[3][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    b.turn = PieceColor.WHITE
    app.board.trigger_skillcheck_fail(Square(3, 4), Square(2, 3))
    caps = app.board.effects.captures
    assert caps, "the miss FX scheduled a gun choreography"
    assert caps[0]["victim_sq"] == Square(3, 3), "the gun aims at the EP pawn, not the empty cell"


def test_wheel_relayouts_when_the_board_moves():
    app = Frontend(1100, 800)
    _start_local(app)
    to_sq = Square(3, 3)
    ctrl = WheelController(WheelChallenge.from_seed("x"), app.board.cell_rect(to_sq), now_ms=0)
    app.skillcheck_overlay.start(ctrl, (Square(4, 3), to_sq), lambda c, landed: None)
    app._skillcheck_target = to_sq
    before = ctrl.center
    app.window = pg.Surface((1700, 1100))
    app._compute_layout()
    assert ctrl.center == app.board.cell_rect(to_sq).center, "the dial re-anchors to the square"
    assert ctrl.center != before, "a resize actually moved it"


def test_premoved_quiet_move_still_fires_normally_in_shootout():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.reset(enabled=True, seed="seed")
    quiet_from, quiet_to = Square(7, 4), Square(6, 4)
    app.board.premoves = [Premove(quiet_from, quiet_to, app.match.piece_at(quiet_from))]
    app.board.premove_color = app.match.current_turn()
    fired = app.board.try_apply_next_premove()
    assert fired is True, "a non-triggering premove applies as before"
    assert app.skillcheck_overlay.is_active() is False
    assert len(app.match.move_history) == 1


def test_landed_ply_clears_locks():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.lock(Square(7, 4), Square(6, 4))
    app.match.try_move(Square(4, 3), Square(3, 3))
    app._on_move_landed(app.match.move_history[-1])
    assert len(app.skillcheck.locks) == 0


def test_board_marks_locked_target():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.skillcheck.lock(frm, to)
    app.board.selected_square = frm
    assert app.board._is_target_locked(to) is True
    assert app.board._is_target_locked(Square(5, 3)) is False
