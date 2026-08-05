"""Session integration for the two new skill-check kinds. A local WHACK gate hands
the controller the SAME hole squares the pure engine derives from the frozen board
(seed + captured value + capture square + occupied set), a COMBO gate threads the
capturer's cell-scaled sprite and the captured value into the challenge, and the
controller's own geom-derived affine — the single owner of the px->board inverse —
round-trips square centers on both orientations. Victim-square suppression now covers
{AIM, WHACK, COMBO}
while sync_aim_check_gun stays an AIM-only coupling, and every path that discards a
live controller (teardown, screen exit, new-game reset, overlay replacement) calls
close() so the whack check's hidden OS cursor can never leak. The input swallow
path is pinned: arrows reach the combo pad, never move-stepping.

A failed WHACK taunts with the same loss-coloured FLAIR WORD the kill words use —
no speech bubble anywhere in it. The session stores the check seed at overlay-open
and on a fail spawns effects.taunt_tag(pick_taunt(seed)) over the surviving victim
— deterministic per seed, so mover and spectator render the same word — plus the
taunt sound for the mover only (the spectate mirror stays muted). The seed clears
on every terminal path so a stale seed can never leak into the next check's taunt.
The failed WHACK is also the one restore that skips the board
drop (restore_piece(drop=False)): its overlay already set the victim down on its
own square, so the piece must simply be there the frame the overlay ends.

The KILL is credited at the pit, on the hit that earns it — not later at the home
square. The controller reports every registered hit as (px, kill); on the killing
one the session calls board.whack_kill_at(px, victim_sq, color, victim_piece),
the single choke point that registers the streak at that pixel, shreds the air
there (impact_px) and announces it. The mirror runs the identical package off the
relayed shot, so a spectator sees and hears the kill on the pit it happened on.

While a WHACK runs, the CAPTURER on the board keeps its gun out and tracks the live
crosshair (the mirror tracks the last relayed impact instead, falling back to the
victim square before the first relay), and every REGISTERED hit fires that piece's
own capture projectile at the impact point — whiffs, lockout shots and locked moves
throw nothing. sync_whack_gun is the single owner of that state: one call per frame
arms it while the overlay is a live whack and releases it (tumbling drop) the moment
it is not, which is what covers every teardown path at once. The terminal paths
release explicitly too, because a screen that stops drawing stops syncing — the gun
must never survive into the next game.

NEITHER whack verdict tumbles the gun: win or miss, the piece keeps the weapon and
hands it to whatever fires next (hand_off_gun_px -> predrawn capture on a win,
predrawn miss volley on a fail), so the check's last aimed frame flows straight
into the shot with no drop and no second draw-flourish. On a WIN the handoff also
arms the capture ADVANCE-ONLY — the whack already blasted the victim off the pit,
so the capture keeps the aimed gun and the slide but fires nothing at the empty
square, and with no draw, aim or pellet flight to wait out it resolves on its first
update. Only the abandonment paths — teardown, Esc, resign, new game — tumble, and
a capture with no check behind it is untouched. Because the latch outlives the
check, every branch of trigger_skillcheck_fail that cannot reach effects.miss()
spends it instead, or the next capture in the game would inherit a predrawn gun
and silently advance without firing.
"""

import math
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.frontend.focus_helpers import FakeTicks, install_clock
from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.backend.utils import Square
from chessshootout.frontend.skillcheck.combo_view import ComboController, COMBO_TIME_LIMIT_MS
from chessshootout.frontend.skillcheck.mole_view import MoleController
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.frontend.visual.effects import AIM_MS, DRAW_MS, EffectManager
from chessshootout.frontend.visual.gunfx import GUNS, PIECE_GUN
from chessshootout.skillcheck import mole
from chessshootout.skillcheck.combo import ComboChallenge
from chessshootout.skillcheck.coordinator import move_roll_key
from chessshootout.skillcheck.mole import MoleChallenge
from chessshootout.skillcheck.rng import ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind
from tests.helpers import BLACK, K, P, Q, R, WHITE, make_app, make_backend, piece, sq, \
    start_single_screen


_pygame_init = pygame_display(1100, 800)


def _local_app():
    app = make_app(1100, 800)
    start_single_screen(app)
    return app


def _capture_board(app, victim=P):
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(victim, BLACK),
    }, turn=WHITE)
    return sq(4, 3), sq(3, 3)


def _kind_seed(backend, frm, to, want):
    for i in range(8000):
        seed = "kseed-{}".format(i)
        roll = ply_roll(seed, move_roll_key(0, frm, to))
        if select_skillcheck(backend, frm, to, roll) == want:
            return seed
    raise AssertionError("no seed found for {}".format(want))


def _gate(app, want, victim=P):
    frm, to = _capture_board(app, victim=victim)
    seed = _kind_seed(app.game.match.backend, frm, to, want)
    app.game.skillcheck.reset(enabled=True, seed=seed)
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    composed = "{}:{}:{}{}{}{}:{}".format(
        seed, 0, frm.row, frm.col, to.row, to.col, want.value)
    return frm, to, composed


def _occupied(app):
    state = app.game.match.state
    return [(row, col) for row in range(8) for col in range(8)
            if state[row][col] is not None]


def test_local_whack_gate_hands_the_controller_the_engine_hole_squares():
    app = _local_app()
    frm, to, composed = _gate(app, SkillCheckKind.WHACK)
    ctrl = app.game.skillcheck_overlay._controller
    assert isinstance(ctrl, MoleController)
    holes = mole.hole_squares(composed, 1, (to.row, to.col), _occupied(app), 8)
    assert ctrl._hole_squares == holes, \
        "the session derives exactly the engine's holes from the frozen board"
    assert (to.row, to.col) not in ctrl._hole_squares, "holes never spawn on occupied squares"


def test_local_whack_gate_threads_the_captured_value_into_the_challenge():
    app = _local_app()
    frm, to, composed = _gate(app, SkillCheckKind.WHACK, victim=R)
    ctrl = app.game.skillcheck_overlay._controller
    deadline = app.game.skillcheck_session._skillcheck_deadline_ms()
    assert ctrl.challenge == MoleChallenge.from_seed(composed, 4, deadline, 5), \
        "the rook's value (5) reaches the challenge, not a defaulted 0"
    assert ctrl.challenge.hole_count == 5, "a rook kill digs five pits"
    assert len(ctrl._hole_squares) == 5


def test_shot_inverse_round_trips_square_centers_on_both_orientations():
    # The controller's affine (derived from the geom the session hands it) is the
    # only px->board inverse left — it must agree with Board.cell_rect either way up.
    app = _local_app()
    board = app.game.board
    for flipped in (False, True):
        board.flipped = flipped
        ctrl = build_controller(
            SkillCheckKind.WHACK, seed="inv-seed", cell_rect=board.cell_rect(Square(3, 3)),
            now_ms=0, deadline_ms=5000, captured_value=1, hole_squares=((2, 2),),
            geom=lambda sq: board.cell_rect(sq).center)
        for row, col in ((0, 0), (3, 3), (7, 7), (2, 5)):
            center = board.cell_rect(Square(row, col)).center
            assert ctrl._shot_target(center) == (row + 0.5, col + 0.5), \
                "flipped={} square ({},{})".format(flipped, row, col)
        ctrl.close()
    board.flipped = False


def test_local_combo_gate_passes_attacker_surface_and_captured_value():
    app = _local_app()
    frm, to, composed = _gate(app, SkillCheckKind.COMBO, victim=R)
    ctrl = app.game.skillcheck_overlay._controller
    assert isinstance(ctrl, ComboController)
    queen_sprite = app.game.board.piece_images_scaled[(PieceType.QUEEN, PieceColor.WHITE)]
    assert ctrl._attacker_src is queen_sprite, "the capturer's cell-scaled sprite dances"
    deadline = min(app.game.skillcheck_session._skillcheck_deadline_ms(), COMBO_TIME_LIMIT_MS)
    assert ctrl.challenge == ComboChallenge.from_seed(composed, 4, deadline, 5)
    assert ctrl.challenge.prompt_count == 6, "the rook's value stretches the combo"


def test_whack_and_combo_suppress_the_victim_square():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    assert app.game.skillcheck_session.skillcheck_target == to
    assert app.game.board.aim_suppressed_square == to, "the overlay owns drawing the victim"
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    assert app.game.board.aim_suppressed_square is None

    frm, to, _ = _gate(app, SkillCheckKind.COMBO)
    assert app.game.board.aim_suppressed_square == to
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    assert app.game.board.aim_suppressed_square is None


def test_wheel_still_never_suppresses_a_square():
    app = _local_app()
    _gate(app, SkillCheckKind.WHEEL)
    assert app.game.board.aim_suppressed_square is None
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def test_sync_aim_check_gun_is_inert_for_whack_and_combo():
    app = _local_app()
    for want in (SkillCheckKind.WHACK, SkillCheckKind.COMBO):
        _gate(app, want)
        assert app.game.board.aim_suppressed_square is not None
        app.game.skillcheck_session.sync_aim_check_gun()
        fx = app.game.board.effects
        assert fx.aim_victim is None, \
            "{}: the aim held-gun must not draw over the overlay's victim".format(want.value)
        assert fx.aim_victim_scale == 1.0
        app.game.skillcheck_session.teardown_skillcheck_overlay()


def test_sync_aim_check_gun_still_arms_for_aim():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.AIM)
    app.game.skillcheck_session.sync_aim_check_gun()
    assert app.game.board.effects.aim_victim == to, "the AIM coupling is untouched"
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    app.game.skillcheck_session.sync_aim_check_gun()
    assert app.game.board.effects.aim_victim is None


def test_failed_whack_restores_the_suppressed_victim_instantly_and_clears_state():
    # The whack overlay already landed the victim on its own square with the
    # jump-out; dropping it a second time from above read as the piece appearing
    # out of thin air and repairing itself mid-air.
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, False)
    assert app.game.board.aim_suppressed_square is None, "the square stops being suppressed"
    assert app.game.skillcheck_session.active_kind is None
    assert app.game.board._restore_anims == [], \
        "no drop animation is queued — the piece simply is on its square"
    assert app.game.match.piece_at(to) is not None
    assert app.game.skillcheck.is_locked(frm, to) is True


@pytest.mark.parametrize("kind", [SkillCheckKind.AIM, SkillCheckKind.COMBO])
def test_other_failed_kinds_still_drop_the_victim_back_in(kind):
    # Driven through the done handler directly: the drop policy is a property of
    # the kind, not of which roll opened the check.
    app = _local_app()
    frm, to = _capture_board(app)
    app.game.board.aim_suppressed_square = to
    app.game.skillcheck_session._on_skillcheck_done((frm, to, None, kind), False)
    assert any(a["sq"] == to for a in app.game.board._restore_anims), \
        "only the whack skips the drop; the approved aim/combo restore is untouched"


def _tags_on(fx, square):
    return [p for p in fx.particles if p["kind"] == "tag" and p.get("victim_sq") == square]


def _reference_taunt(cell, text):
    # Same builder, same cell, same colours -- a byte-identical surface is the only
    # way to pin the WORD, which the particle keeps only as pre-rendered pixels.
    ref = EffectManager()
    ref.taunt_tag(0, text, Square(0, 0), cell)
    return ref.particles[-1]["surf"]


def _same_pixels(left, right):
    return (left.get_size() == right.get_size()
            and pg.image.tostring(left, "RGBA") == pg.image.tostring(right, "RGBA"))


def test_failed_whack_taunts_with_a_flair_word_over_the_surviving_victim():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    seed = session.active_seed
    assert seed is not None, "the session stores the check seed at overlay-open"
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    session._on_skillcheck_done(context, False)
    taunts = _tags_on(fx, to)
    assert len(taunts) == 1, "one flair word, anchored on the surviving victim"
    assert _same_pixels(taunts[0]["surf"],
                        _reference_taunt(app.game.board.cell_size, mole.pick_taunt(seed))), \
        "the line comes from the per-check seed, not the controller"
    assert _tags_on(fx, frm), "and the attacker's own swear still lands on its square"
    app.sound_manager.play_mole_taunt.assert_called_once()
    assert session.active_seed is None, "the seed clears at resolution"


def test_the_taunt_is_a_flair_tag_and_never_a_speech_bubble():
    # Speech bubbles are player chat only -- a mole taunt must not touch them.
    app = _local_app()
    _gate(app, SkillCheckKind.WHACK)
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, False)
    assert all(b.shown_at is None for b in app.game.speech_bubbles.values()), \
        "the chat bubbles stay empty"
    assert not hasattr(app.game, "taunt_bubble"), "the taunt bubble is gone for good"


def test_won_whack_never_taunts():
    app = _local_app()
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, True)
    assert _tags_on(app.game.board.effects, to) == []
    app.sound_manager.play_mole_taunt.assert_not_called()
    assert app.game.skillcheck_session.active_seed is None


def test_online_whack_fail_shows_the_board_taunt_with_sound():
    app = _local_app()
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.skillcheck_target = sq(3, 3)
    session.active_seed = "wire-seed"
    session._on_online_skillcheck_done(
        (sq(4, 3), sq(3, 3), None, SkillCheckKind.WHACK), False)
    taunts = _tags_on(fx, sq(3, 3))
    assert len(taunts) == 1
    assert _same_pixels(taunts[0]["surf"],
                        _reference_taunt(app.game.board.cell_size,
                                         mole.pick_taunt("wire-seed"))), \
        "both clients derive the same line from the same wire seed"
    app.sound_manager.play_mole_taunt.assert_called_once()
    assert session.active_seed is None


def test_spectated_online_whack_fail_taunts_silently():
    # _begin_online_verdict nulls online_spectate_kind BEFORE the done handler runs,
    # so spectator-ness must survive on the online_was_spectator latch instead.
    app = _local_app()
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.skillcheck_target = sq(3, 3)
    session.active_seed = "wire-seed"
    session.online_was_spectator = True
    session.online_spectate_kind = None
    session._on_online_skillcheck_done(
        (sq(4, 3), sq(3, 3), None, SkillCheckKind.WHACK), False)
    assert _tags_on(fx, sq(3, 3)), "the mirror still shows the victim's line"
    app.sound_manager.play_mole_taunt.assert_not_called()
    assert session.online_was_spectator is False


def test_a_taunt_with_no_victim_square_paints_nothing():
    # aim_suppressed_square is None on every non-capture path; a tag anchored to a
    # None square would blow up in geom() the first frame it drew.
    app = _local_app()
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session._show_whack_taunt(None, "seed", True)
    assert [p for p in fx.particles if p["kind"] == "tag"] == []


def test_spectate_open_arms_the_spectator_latch():
    app = _local_app()
    session = app.game.skillcheck_session
    session.open_spectate_overlay(
        SkillCheckKind.WHACK, "spec-seed", 0, 5000, sq(4, 3), sq(3, 3), None, 1)
    assert session.online_was_spectator is True
    session.teardown_skillcheck_overlay()


def _mock_controller():
    ctrl = MagicMock()
    ctrl._passive = False
    return ctrl


def test_teardown_closes_the_live_controller():
    app = _local_app()
    ctrl = _mock_controller()
    app.game.skillcheck_overlay.start(ctrl, (sq(4, 3), sq(3, 3)), lambda c, landed: None)
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    ctrl.close.assert_called_once()


def test_screen_exit_closes_the_live_controller():
    app = _local_app()
    ctrl = _mock_controller()
    app.game.skillcheck_overlay.start(ctrl, (sq(4, 3), sq(3, 3)), lambda c, landed: None)
    app.game.exit()
    ctrl.close.assert_called_once()
    assert not app.game.skillcheck_overlay.is_active()


def test_reset_to_new_game_closes_the_live_controller():
    app = _local_app()
    ctrl = _mock_controller()
    app.game.skillcheck_overlay.start(ctrl, (sq(4, 3), sq(3, 3)), lambda c, landed: None)
    app.game._reset_to_new_game()
    ctrl.close.assert_called_once()


def test_overlay_replacement_closes_the_displaced_controller():
    app = _local_app()
    stale = _mock_controller()
    stale._passive = True
    app.game.skillcheck_overlay.start(stale, (sq(1, 1), sq(2, 2)), lambda c, landed: None)
    _gate(app, SkillCheckKind.WHACK)
    stale.close.assert_called_once()
    assert app.game.skillcheck_overlay._controller is not stale
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def test_normal_overlay_finish_also_closes_the_controller():
    app = _local_app()
    done = []
    ctrl = _mock_controller()
    ctrl.done = True
    ctrl.landed = True
    app.game.skillcheck_overlay.start(ctrl, ("ctx",), lambda c, landed: done.append(landed))
    app.game.skillcheck_overlay.update(0)
    ctrl.close.assert_called_once()
    assert done == [True]


def test_arrow_keys_reach_the_combo_pad_not_move_stepping():
    app = _local_app()
    _gate(app, SkillCheckKind.COMBO)
    ctrl = app.game.skillcheck_overlay._controller
    ctrl.update(ctrl.start_ms + 200)
    assert app.game.swallows_input() is True
    app.game.board.step_review = MagicMock()
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_LEFT, "unicode": "", "mod": 0}))
    app.input_router.check_events()
    app.game.board.step_review.assert_not_called()
    assert ctrl._progress + ctrl._wrong_count == 1, "the press registered on the combo pad"
    pg.event.clear()
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def _whack_app(monkeypatch):
    app = _local_app()
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    frm, to, _ = _gate(app, SkillCheckKind.WHACK)
    return app, clock, frm, to


def _aim_angle(app, frm, target_px):
    px, py = app.game.board.effects._pivot(frm, app.game.board.cell_size)
    return math.atan2(target_px[1] - py, target_px[0] - px)


def _spin(session, clock, frames=200, step=16):
    for _ in range(frames):
        clock.advance(step)
        session.sync_whack_gun()


def _fire_at(ctrl, px, at_ms):
    ctrl.update(at_ms)
    ctrl.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": px}))


def _live_pop_shot(ctrl):
    pop = ctrl.challenge.pops[0]
    return ctrl._hole_px[pop.hole], ctrl.start_ms + int(pop.t_up_ms) + 10


def test_sync_whack_gun_arms_the_capturers_gun_and_eases_after_the_crosshair(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    right = board.cell_rect(sq(4, 7)).center
    up = board.cell_rect(sq(0, 3)).center
    cursor = {"px": right}
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: cursor["px"])
    session.sync_whack_gun()
    assert fx.has_gun_px() is True, "a live whack puts the gun in the attacker's hand"
    assert fx._whack_gun["from_sq"] == frm, "the CAPTURER aims, not the victim"
    assert fx._whack_gun["aim"] == pytest.approx(_aim_angle(app, frm, right)), \
        "it starts pointing at the crosshair instead of swinging in from nowhere"
    cursor["px"] = up
    clock.advance(16)
    session.sync_whack_gun()
    want = _aim_angle(app, frm, up)
    swung = fx._whack_gun["aim"]
    assert want < swung < _aim_angle(app, frm, right), \
        "one frame after the crosshair moves the barrel is on its way, not there"
    _spin(session, clock)
    assert fx._whack_gun["aim"] == pytest.approx(want, abs=0.02), "and it catches up"
    session.teardown_skillcheck_overlay()


def test_teardown_tumbles_the_gun_and_the_next_whack_rearms_clean(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    session.teardown_skillcheck_overlay()
    assert fx.has_gun_px() is False, "the gun leaves with the overlay"
    assert len(fx.drops) == 1, "and tumbles away instead of blinking out"
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "no later frame can resurrect a torn-down check"
    frm2, _, _ = _gate(app, SkillCheckKind.WHACK)
    session.sync_whack_gun()
    assert fx.has_gun_px() is True and fx._whack_gun["from_sq"] == frm2, \
        "the second check arms its own capturer"
    session.teardown_skillcheck_overlay()


def test_a_new_game_never_inherits_a_held_whack_gun(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    app.game._reset_to_new_game()
    assert fx.has_gun_px() is False
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "the stale-overlay invariant holds on the next frame too"


def test_leaving_the_screen_releases_the_held_whack_gun(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    app.game.exit()
    assert fx.has_gun_px() is False, \
        "a screen that stops drawing stops syncing — exit must release it itself"


def test_a_registered_hit_fires_the_capturers_own_projectile(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    ctrl = app.game.skillcheck_overlay._controller
    px, at_ms = _live_pop_shot(ctrl)
    _fire_at(ctrl, px, at_ms)
    assert ctrl._progress == 1, "the shot registered"
    spec = GUNS[PIECE_GUN["queen"]]
    assert len(fx.projectiles) == spec.pellets, "the queen's blunderbuss empties its spread"
    assert {pr["color"] for pr in fx.projectiles} == {spec.color}
    assert all(pr["capture"] is None for pr in fx.projectiles), "the volley is cosmetic"
    assert fx._whack_gun["fired_at"] is not None, "and the gun kicks"
    session.teardown_skillcheck_overlay()


def test_whiffs_and_lockout_shots_throw_nothing(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    ctrl = app.game.skillcheck_overlay._controller
    _fire_at(ctrl, app.game.board.cell_rect(frm).center, ctrl.start_ms + 300)
    assert ctrl._progress == 0
    assert fx.projectiles == [], "a whiff never leaves the barrel"
    px, at_ms = _live_pop_shot(ctrl)
    _fire_at(ctrl, px, at_ms)
    fired = len(fx.projectiles)
    assert fired > 0
    _fire_at(ctrl, px, at_ms + 1)
    assert len(fx.projectiles) == fired, "a shot eaten by the recoil lockout fires nothing"
    session.teardown_skillcheck_overlay()


def test_a_locked_move_reopens_no_check_and_holds_no_gun(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    session._on_skillcheck_done(context, False)
    assert app.game.skillcheck.is_locked(frm, to) is True
    session.sync_whack_gun()
    assert fx.has_gun_px() is False
    assert session.skillcheck_gate(frm, to) is True, "the locked move is swallowed"
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "a locked retry arms nothing"


def test_the_mirror_aims_at_the_victim_then_at_the_relayed_impact(monkeypatch):
    app = _local_app()
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    frm, to = _capture_board(app)
    session.open_spectate_overlay(
        SkillCheckKind.WHACK, "spec-seed", 0, 5000, frm, to, None, 1)
    session.sync_whack_gun()
    assert fx.has_gun_px() is True, "the spectator sees the opponent draw too"
    victim_px = board.cell_rect(to).center
    assert fx._whack_gun["aim"] == pytest.approx(_aim_angle(app, frm, victim_px)), \
        "before the first relay the barrel rests on the victim"
    ctrl = app.game.skillcheck_overlay._controller
    ctrl.update(ctrl.start_ms + 900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(0.5, 0.5))
    impact = board.cell_rect(sq(0, 0)).center
    assert fx.projectiles, "the relayed hit fires the mirror's gun"
    assert {pr["color"] for pr in fx.projectiles} == {GUNS[PIECE_GUN["queen"]].color}
    _spin(session, clock)
    assert fx._whack_gun["aim"] == pytest.approx(_aim_angle(app, frm, impact), abs=0.02), \
        "and the barrel follows the opponent's shots from there on"
    session.teardown_skillcheck_overlay()


@pytest.mark.parametrize("kind", [SkillCheckKind.WHEEL, SkillCheckKind.AIM,
                                  SkillCheckKind.COMBO])
def test_no_other_kind_ever_arms_the_px_gun(kind, monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    _gate(app, kind)
    app.game.skillcheck_session.sync_whack_gun()
    assert app.game.board.effects.has_gun_px() is False, \
        "{}: only the whack check hands the piece a tracking gun".format(kind.value)
    app.game.skillcheck_session.teardown_skillcheck_overlay()


def _finish_check(app, landed):
    context = app.game.skillcheck_overlay._context
    app.game.skillcheck_overlay.cancel()
    app.game.skillcheck_session._on_skillcheck_done(context, landed)


def test_a_won_whack_hands_the_same_gun_to_the_capture(monkeypatch):
    # The check gun and the capture gun are the same weapon in the same hand: no
    # tumble-drop, no second draw-flourish, and nothing to aim at any more either.
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    _finish_check(app, True)
    assert fx.has_gun_px() is False and fx.drops == [], \
        "a won check never throws the gun away mid-shootout"
    entry = fx.captures[0]
    assert entry["predrawn"] is True
    assert entry["fire_at"] == entry["start"], \
        "no DRAW_MS, no AIM_MS — the gun is up and the victim is already gone"
    assert entry["advance_only"] is True, \
        "the whack already killed the victim — the capture must not shoot the empty square"
    session.sync_whack_gun()
    assert fx.has_gun_px() is False, "and the whack state stays gone afterwards"


def test_a_won_whacks_capture_advances_without_firing_a_shot(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    session.sync_whack_gun()
    _finish_check(app, True)
    entry = fx.captures[0]
    fx.update(entry["fire_at"])
    assert fx.projectiles == [], "no volley leaves the barrel"
    assert [p["kind"] for p in fx.particles if p["kind"] in ("flash", "impact", "blood",
                                                             "ragdoll")] == [], \
        "and nothing is shot, wounded or thrown around"
    assert fx.holes == []
    assert fx.captures == [], "the capture retires on the same update it fires"
    assert board.is_animating() is True, "the attacker slides onto the square straight away"


def test_a_failed_whack_hands_the_same_gun_to_the_miss_volley(monkeypatch):
    # The fail beat is one continuous take too: the gun that was tracking the moles
    # is the gun that whiffs, so it must not tumble and re-draw a twin in between.
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    _finish_check(app, False)
    assert fx.has_gun_px() is False
    assert fx.drops == [], "a miss keeps the weapon in hand — nothing is thrown away"
    entry = fx.captures[0]
    assert entry["miss"] is True
    assert entry["predrawn"] is True, "the SKILL ISSUE shot inherits the drawn gun"
    assert entry["fire_at"] == entry["start"] + AIM_MS, \
        "only the aim beat stands between the check and the whiff — no DRAW_MS"
    assert not entry.get("advance_only"), "and it really does fire at the survivor"
    assert fx._gun_handoff is None, "the miss spends the latch"


def test_the_failed_whacks_volley_still_shoots_and_calls_the_skill_issue(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    _finish_check(app, False)
    entry = fx.captures[0]
    fx.projectiles = []
    fx.update(entry["fire_at"])
    assert fx.projectiles, "the whole spread leaves the barrel"
    assert fx.callouts, "and the SKILL ISSUE callout lands with it"


@pytest.mark.parametrize("kind", [SkillCheckKind.WHEEL, SkillCheckKind.AIM,
                                  SkillCheckKind.COMBO])
def test_no_other_kind_ever_hands_a_gun_on(kind, monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    session, fx = app.game.skillcheck_session, app.game.board.effects
    fx.hold_gun_px(now_ms=0, attacker_type="queen", from_sq=sq(4, 3),
                   cell_size=app.game.board.cell_size)
    session._end_whack_gun(kind)
    assert fx._gun_handoff is None, \
        "{}: only the whack passes its weapon on".format(kind.value)
    assert len(fx.drops) == 1, "every other kind drops it"


def test_a_plain_capture_is_untouched_by_the_handoff(monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    frm, to = _capture_board(app)
    app.game.board.apply_gated_move(frm, to)
    entry = app.game.board.effects.captures[0]
    assert entry["predrawn"] is False
    assert entry["advance_only"] is False, "it has a victim to shoot and it shoots it"
    assert entry["fire_at"] == entry["start"] + DRAW_MS + AIM_MS, \
        "a capture with no check behind it still draws, aims, then fires"


GORE = {"impact", "blood", "spark", "smoke"}


def _gore(fx):
    return [p for p in fx.particles if p["kind"] in GORE]


def _land_hits(ctrl, count):
    px = None
    for pop in ctrl.challenge.pops[:count]:
        px = ctrl._hole_px[pop.hole]
        _fire_at(ctrl, px, ctrl.start_ms + int(pop.t_up_ms) + 10)
    return px


def test_the_killing_hit_lands_the_whole_kill_package_on_the_pit(monkeypatch):
    # The victim dies at the hole it was popping out of, so the gore, the bullet
    # hole and the streak credit all belong to that pixel — not to the home square
    # the capture will later slide onto.
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    ctrl = app.game.skillcheck_overlay._controller
    assert ctrl.challenge.hits_required == 3, "a pawn takes three pops"
    session.sync_whack_gun()
    px = _land_hits(ctrl, 3)
    assert ctrl._progress == 3 and ctrl.landed is True
    assert {p["kind"] for p in _gore(fx)} == GORE, \
        "ring, blood, sparks and smoke — the full impact package"
    assert all(p["px"] == px for p in _gore(fx)), "every piece of it on the pit"
    assert len(fx.holes) == 1 and fx.holes[0]["px"] == px
    assert not any(p["kind"] == "ragdoll" for p in fx.particles), \
        "the body already flew off the pit on the check's own arc"
    assert fx._streak_count == 1, "the kill is credited once, here"
    app.sound_manager.play_announcer.assert_called_once_with("first_blood")


def test_the_hits_before_the_last_one_credit_nothing(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    ctrl = app.game.skillcheck_overlay._controller
    session.sync_whack_gun()
    _land_hits(ctrl, 2)
    assert ctrl._progress == 2, "two of three — the mole is hurt, not dead"
    assert _gore(fx) == [] and fx.holes == [], "no gore before the kill"
    assert fx._streak_count == 0
    app.sound_manager.play_announcer.assert_not_called()
    app.sound_manager.play_hit.assert_not_called()


def test_the_kill_flair_pops_at_the_pit_pixel_and_names_the_victim(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx, board = app.game.skillcheck_session, app.game.board.effects, app.game.board
    fx.register_kill("black", to, board.cell_size, 0)
    session.sync_whack_gun()
    px = _land_hits(app.game.skillcheck_overlay._controller, 3)
    tag = [p for p in fx.particles if p["kind"] == "tag"][-1]
    assert tag["px"] == px and fx._anchor(tag) == px, \
        "the hit word pops where the piece died, not on its home square"
    # The grunt names the piece that actually died, not the one that shot it.
    app.sound_manager.play_hit.assert_called_once_with(PieceType.PAWN)


def test_the_won_whacks_capture_never_credits_the_kill_a_second_time(monkeypatch):
    # The move animation cuts the live transients as it starts, so the only thing
    # that could double up is the capture crediting its own kill on top.
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session.sync_whack_gun()
    _land_hits(app.game.skillcheck_overlay._controller, 3)
    holes = len(fx.holes)
    _finish_check(app, True)
    fx.update(fx.captures[0]["fire_at"])
    assert fx._streak_count == 1, "one kill, one streak step"
    assert _gore(fx) == [], "the advancing capture shreds nothing on the empty square"
    assert len(fx.holes) == holes, "and punches no second bullet hole"
    app.sound_manager.play_announcer.assert_called_once_with("first_blood")


def test_the_mirror_lands_the_same_kill_package_at_the_relayed_pit(monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    session, fx = app.game.skillcheck_session, app.game.board.effects
    frm, to = _capture_board(app)
    session.open_spectate_overlay(
        SkillCheckKind.WHACK, "spec-seed", 0, 5000, frm, to, None, 1)
    ctrl = app.game.skillcheck_overlay._controller
    assert ctrl.challenge.hits_required == 3
    for i in range(1, 4):
        ctrl.update(ctrl.start_ms + 400 * i)
        ctrl.spectate_shot(400.0 * i, 0, i == 3, progress=i, target=(2.5, 2.5))
        if i < 3:
            assert _gore(fx) == [], "the mirror waits for the killing relay too"
    px = ctrl._board_to_px(2.5, 2.5)
    assert {p["kind"] for p in _gore(fx)} == GORE
    assert all(p["px"] == px for p in _gore(fx)), \
        "the spectator sees the kill on the pit it happened on"
    assert fx._streak_count == 1, "and the streak is credited on the mirror as well"
    app.sound_manager.play_announcer.assert_called_once_with("first_blood")
    session.teardown_skillcheck_overlay()


def test_a_kill_with_no_attacker_left_on_the_board_credits_nothing(monkeypatch):
    app, clock, frm, to = _whack_app(monkeypatch)
    session, fx = app.game.skillcheck_session, app.game.board.effects
    session._whack_gun_from = sq(5, 5)
    session._on_whack_hit_px(app.game.board.cell_rect(to).center, kill=True)
    assert _gore(fx) == [] and fx.holes == [], "no colour to credit, no package"
    assert fx._streak_count == 0
    session.teardown_skillcheck_overlay()


def _hand_off(fx, board, from_sq):
    fx.hold_gun_px(now_ms=0, attacker_type="queen", from_sq=from_sq,
                   cell_size=board.cell_size)
    fx.hand_off_gun_px()
    assert fx._gun_handoff == from_sq


def test_a_fail_with_no_attacker_still_spends_the_gun_handoff(monkeypatch):
    # trigger_skillcheck_fail returns early when there is no piece to shoot with;
    # a handoff left armed there would ride into the NEXT capture, which would then
    # advance predrawn and silently, firing at nothing.
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    board, fx = app.game.board, app.game.board.effects
    frm, to = _capture_board(app)
    empty = sq(5, 5)
    _hand_off(fx, board, empty)
    board.trigger_skillcheck_fail(empty, to)
    assert fx.captures == [], "there was no attacker to fire the volley"
    assert fx._gun_handoff is None, "and the latch is spent anyway"
    board.apply_gated_move(frm, to)
    assert fx.captures[0]["predrawn"] is False, "the next capture draws for itself"


def test_a_fail_with_no_board_geometry_still_spends_the_gun_handoff(monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    board, fx = app.game.board, app.game.board.effects
    frm, to = _capture_board(app)
    _hand_off(fx, board, frm)
    board.cell_size = 0
    board.trigger_skillcheck_fail(frm, to)
    assert fx.captures == [] and fx._gun_handoff is None


def test_whack_kill_at_is_inert_without_geometry_or_a_victim(monkeypatch):
    app = _local_app()
    install_clock(monkeypatch, FakeTicks())
    board, fx = app.game.board, app.game.board.effects
    px = board.cell_rect(sq(3, 3)).center
    board.whack_kill_at(px, None, "white", None)
    board.whack_kill_at(px, sq(3, 3), None, None)
    board.cell_size = 0
    board.whack_kill_at(px, sq(3, 3), "white", None)
    assert fx.particles == [] and fx.holes == [] and fx.callouts == []
    assert fx._streak_count == 0
