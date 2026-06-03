"""Phase 10a/10b gun-fight capture/effects layer.

Surfaces covered:
  * EffectManager (frontend/visual/effects.py) — the two-stage capture
    choreography (draw/aim -> fire -> travel -> impact), the board screen-shake
    decay, the check gun-draw, reduce-motion / intensity gating, and the 10b
    killstreak counter + announcer callouts (FIRST BLOOD -> DOUBLE..GODLIKE ->
    hit-word tags; same-side, resets on recapture). A fake `geom` resolver and an
    injected deterministic rng make every assertion reproducible across workers.
  * gunfx (frontend/visual/gunfx.py) — the shared GunSpec/GUNS registry that
    consolidated menu-battle's scattered gun dicts, plus the aim geometry.
  * Board (frontend/board/board.py) — that shake rides _cell_rect while
    _cell_rect_base / cell_at / arrows / the promotion popover opt out, and that
    show_check_gun locates the real checking piece (including through a blocker).
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import math
import random
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import MagicMock

import pygame as pg
import pytest

from domain.match import Match
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.board import Board
from frontend.frontend import Frontend
from frontend.visual import gunfx
from frontend.visual.effects import (
    AIM_MS, CALLOUT_LG_MS, CALLOUT_XL_MS, CHECK_DROP_MS, DRAW_MS, HIT_WORDS,
    HOLE_FADE_MS, HOLE_HOLD_MS, HOLE_IN_MS, INTENSITY_SCALE, KING_SHAKE_MS, PIECE_GUN,
    PROJECTILE_MAX_MS, PROJECTILE_TRAVEL_MS, RECOIL_MS, SHAKE_AMP, SHAKE_HARD_MS,
    SHAKE_SOFT_MS, STREAK_LABELS, TAG_MS, TAKEOVER_PAUSE_MS, TAKEOVER_TOTAL_MS,
    EffectManager,
)
from frontend.visual.gunfx import GUNS, GunSpec

WHITE, BLACK = PieceColor.WHITE, PieceColor.BLACK
KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN = (
    PieceType.KING, PieceType.QUEEN, PieceType.ROOK,
    PieceType.BISHOP, PieceType.KNIGHT, PieceType.PAWN,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    if pg.mixer.get_init() is None:
        pg.mixer.init()
    pg.display.set_mode((780, 780))
    yield
    pg.quit()


def _app():
    app = Frontend(780, 780)
    app.sound_manager = MagicMock()
    app._on_start_game({"mode": "single_screen", "nickname": "alice",
                        "time_minutes": None, "increment_seconds": 0, "side": "white"})
    return app


def _em(reduce_motion=False, intensity="full", seed=7):
    em = EffectManager(rng=random.Random(seed))
    em.geom = lambda sq: (sq.col * 100 + 50, sq.row * 100 + 50)
    em.board_rect = pg.Rect(0, 0, 800, 800)
    em.configure(reduce_motion, intensity)
    return em


def _tags(em):
    return [p for p in em.particles if p["kind"] == "tag"]


def _surf():
    return pg.Surface((40, 40), pg.SRCALPHA)


def test_shake_offset_zero_when_idle():
    assert _em().shake_offset(0) == (0, 0)


def test_trigger_shake_is_bounded_then_self_clears():
    em = _em()
    em.trigger_shake(1000, "hard")
    amp = SHAKE_AMP["hard"]
    for t in range(1000, 1000 + SHAKE_HARD_MS, 20):
        ox, oy = em.shake_offset(t)
        assert abs(ox) <= amp and abs(oy) <= amp
    assert any(em.shake_offset(t) != (0, 0)
               for t in range(1000, 1000 + SHAKE_HARD_MS, 20))
    assert em.shake_offset(1000 + SHAKE_HARD_MS + 1) == (0, 0)
    assert em._shake is None


def test_shake_decays_toward_end_of_window():
    em = _em()
    em.trigger_shake(0, "hard")
    early = max(abs(c) for c in em.shake_offset(int(SHAKE_HARD_MS * 0.05)))
    late = max(abs(c) for c in em.shake_offset(int(SHAKE_HARD_MS * 0.95)))
    assert late < early


def test_reduce_motion_suppresses_shake():
    em = _em(reduce_motion=True)
    em.trigger_shake(0, "hard")
    assert em._shake is None
    assert em.shake_offset(10) == (0, 0)


def test_intensity_scales_shake_amplitude():
    full = _em(intensity="full")
    full.trigger_shake(0, "hard")
    subtle = _em(intensity="subtle")
    subtle.trigger_shake(0, "hard")
    assert full._shake["amp"] == pytest.approx(SHAKE_AMP["hard"] * 1.0)
    assert subtle._shake["amp"] == pytest.approx(
        SHAKE_AMP["hard"] * INTENSITY_SCALE["subtle"])
    assert subtle._shake["amp"] < full._shake["amp"]


def _run_until_resolved(em, start, step=16, limit=400):
    t = start
    for _ in range(limit):
        t += step
        em.update(t)
        if not em.captures:
            return t
    return t


def test_capture_fires_a_spread_then_resolves_on_lead_pellet_impact():
    em = _em()
    fired, slid = [], []
    em.capture(now_ms=1000, attacker_type="queen", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(7, 3), victim_sq=Square(0, 3),
               to_sq=Square(0, 3), cell_size=80, power="hard",
               on_fire=lambda: fired.append(1), on_slide=lambda: slid.append(1))
    assert len(em.captures) == 1
    c = em.captures[0]
    assert c["fire_at"] == 1000 + DRAW_MS + AIM_MS
    assert Square(0, 3) in em.held_squares()

    em.update(c["fire_at"] - 1)
    assert fired == [] and slid == [] and em.projectiles == []

    em.update(c["fire_at"])
    assert fired == [1] and slid == []
    assert len(em.projectiles) == GUNS["blunderbuss"].pellets, "queen fires a blunderbuss spread"
    assert sum(1 for pr in em.projectiles if pr["lead"]) == 1, "exactly one lead pellet"
    assert Square(0, 3) in em.held_squares()

    _run_until_resolved(em, c["fire_at"])
    assert slid == [1], "the lead pellet reaching the victim triggers the attacker slide-in"
    assert em.captures == []
    assert any(p["kind"] == "impact" for p in em.particles)
    assert Square(0, 3) not in em.held_squares()


def test_capture_impact_spawns_ragdoll_blood_smoke_and_a_hole():
    em = _em()
    em.capture(now_ms=0, attacker_type="rook", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(0, 0), victim_sq=Square(0, 4),
               to_sq=Square(0, 4), cell_size=80, power="hard")
    c = em.captures[0]
    em.update(c["fire_at"])
    _run_until_resolved(em, c["fire_at"])
    kinds = {p["kind"] for p in em.particles}
    assert {"impact", "blood", "ragdoll", "smoke"} <= kinds
    assert em.holes


def test_shake_triggers_on_fire_not_on_impact():
    em = _em()
    em.capture(now_ms=0, attacker_type="rook", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(0, 0), victim_sq=Square(0, 4),
               to_sq=Square(0, 4), cell_size=80, power="hard")
    c = em.captures[0]
    em.update(c["fire_at"] - 1)
    assert em._shake is None
    em.update(c["fire_at"])
    assert em._shake is not None
    assert em._shake["start"] == c["fire_at"]


def test_reduce_motion_capture_resolves_immediately_without_choreography():
    em = _em(reduce_motion=True)
    fired, slid = [], []
    em.capture(now_ms=0, attacker_type="pawn", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(6, 4), victim_sq=Square(5, 4),
               to_sq=Square(5, 4), cell_size=80,
               on_fire=lambda: fired.append(1), on_slide=lambda: slid.append(1))
    assert em.captures == []
    assert fired == [1] and slid == [1]
    kinds = {p["kind"] for p in em.particles}
    assert "impact" in kinds
    assert "ragdoll" not in kinds and "smoke" not in kinds
    assert em._shake is None


def test_en_passant_holds_destination_square():
    em = _em()
    em.capture(now_ms=0, attacker_type="pawn", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(3, 4), victim_sq=Square(3, 3),
               to_sq=Square(2, 3), cell_size=80)
    assert em.held_squares() == {Square(2, 3)}


def test_recoil_kicks_back_along_aim_then_recovers():
    em = _em()
    em.capture(now_ms=0, attacker_type="rook", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(0, 0), victim_sq=Square(0, 4),
               to_sq=Square(0, 4), cell_size=80, power="hard")
    c = em.captures[0]
    rx0, ry0 = em._recoil(c["gun"], c["weapon"], 0.0, 0)
    assert rx0 < 0
    assert ry0 == pytest.approx(0.0, abs=1e-6)
    rx_mid = em._recoil(c["gun"], c["weapon"], 0.0, RECOIL_MS // 2)[0]
    assert rx0 < rx_mid < 0
    assert em._recoil(c["gun"], c["weapon"], 0.0, RECOIL_MS) == (0.0, 0.0)


def _stray(x, y, cell=80):
    return {"x": x, "y": y, "vx": 1.0, "vy": 0.0, "color": GUNS["shotgun"].color,
            "size": 4, "len": 8, "cell": cell, "lead": False, "capture": None,
            "born": 0, "max_ms": PROJECTILE_MAX_MS}


def test_stray_pellet_wounds_a_bystander_without_killing_it():
    em = _em()
    bystander = Square(4, 4)
    cx, cy = em.geom(bystander)
    em._bystanders = {bystander}
    em.projectiles = [_stray(cx, cy)]
    em.update(0)
    kinds = {p["kind"] for p in em.particles}
    assert "blood" in kinds, "a wounded bystander bleeds"
    assert "ragdoll" not in kinds and not em.holes, "but it does not die — no ragdoll, no hole"
    assert em._piece_shakes.get(bystander) is not None, "the wounded piece shakes"
    assert em.projectiles == [], "the stray pellet is spent on impact"
    assert bystander not in em._bystanders, "and the square won't be wounded twice"


def test_lead_pellet_never_wounds_bystanders_only_the_victim_dies():
    em = _em()
    cx, cy = em.geom(Square(4, 4))
    lead = _stray(cx, cy)
    lead["lead"] = True
    em._bystanders = {Square(4, 4)}
    em.projectiles = [lead]
    em.update(0)
    assert em._piece_shakes == {}, "the aimed lead shot does not wound bystanders it passes"


def test_single_pellet_gun_fires_one_bullet_and_wounds_no_bystanders():
    em = _em()
    em.capture(now_ms=0, attacker_type="pawn", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(6, 4), victim_sq=Square(5, 4),
               to_sq=Square(5, 4), cell_size=80, occupied={Square(5, 0), Square(3, 4)})
    c = em.captures[0]
    em.update(c["fire_at"])
    assert len(em.projectiles) == 1, "a revolver fires a single bullet (no spread)"
    _run_until_resolved(em, c["fire_at"])
    assert em._piece_shakes == {}, "one straight bullet wounds no bystanders"


def test_piece_offset_jitters_a_wounded_piece():
    em = _em()
    sq = Square(2, 2)
    em._piece_shakes = {sq: {"start": 0, "dur": SHAKE_SOFT_MS, "amp": 6}}
    assert em.piece_offset(sq, SHAKE_SOFT_MS // 3) != (0, 0), "mid-window the piece jitters"
    assert em.piece_offset(Square(0, 0), SHAKE_SOFT_MS // 3) == (0, 0), "other squares are still"
    assert em.piece_offset(sq, SHAKE_SOFT_MS + 10) == (0, 0), "the jitter ends with the window"


def test_cut_and_clear_drop_projectiles_and_bystanders():
    em = _em()
    em.projectiles = [_stray(10, 10)]
    em._bystanders = {Square(1, 1)}
    em._piece_shakes = {Square(1, 1): {"start": 0, "dur": SHAKE_SOFT_MS, "amp": 6}}
    em.cut()
    assert em.projectiles == [] and em._bystanders == set() and em._piece_shakes == {}


def test_pellet_spread_lead_straight_rest_scattered():
    spec = GUNS["shotgun"]
    rng = random.Random(1)
    spread = gunfx.pellet_spread(spec, 0.0, lambda lo, hi: lo + rng.random() * (hi - lo))
    assert len(spread) == spec.pellets
    assert spread[0] == (0.0, 1.0), "the lead pellet is dead straight at full speed"
    assert all(abs(a) <= spec.spread for a, _ in spread[1:]), "the rest stay within spread"
    assert any(a != 0.0 for a, _ in spread[1:]), "and actually deviate from the aim line"


def test_draw_bullet_paints_a_streak():
    surf = pg.Surface((80, 80), pg.SRCALPHA)
    gunfx.draw_bullet(surf, (40, 40), 1.0, 0.0, GUNS["shotgun"].color, 6, 24)
    assert surf.get_bounding_rect().width > 0, "the bullet leaves visible pixels"


def _lead_speed(em, from_sq, victim_sq):
    em.capture(now_ms=0, attacker_type="queen", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=from_sq, victim_sq=victim_sq,
               to_sq=victim_sq, cell_size=80)
    c = em.captures[0]
    em.update(c["fire_at"])
    lead = next(pr for pr in em.projectiles if pr["lead"])
    return math.hypot(lead["vx"], lead["vy"])


def test_in_game_pellet_speed_scales_with_distance():
    """Speed = distance / constant, so a far shot's pellets fly proportionally faster."""
    near = _lead_speed(_em(), Square(4, 3), Square(4, 5))
    far = _lead_speed(_em(), Square(7, 0), Square(0, 7))
    assert far > near * 2, "a much farther capture launches a much faster bullet"


def test_capture_resolves_in_a_distance_independent_window():
    """Near and far captures both resolve in roughly the constant travel window."""
    def elapsed(from_sq, victim_sq):
        em = _em()
        em.capture(now_ms=0, attacker_type="queen", attacker_surface=_surf(),
                   victim_surface=_surf(), from_sq=from_sq, victim_sq=victim_sq,
                   to_sq=victim_sq, cell_size=80)
        c = em.captures[0]
        return _run_until_resolved(em, c["fire_at"]) - c["fire_at"]
    near = elapsed(Square(4, 3), Square(4, 5))
    far = elapsed(Square(7, 0), Square(0, 7))
    assert abs(near - far) <= 48, "resolution times stay within ~3 frames across distances"
    assert far <= PROJECTILE_TRAVEL_MS + 48, "even a board-length shot resolves on the beat"


def test_check_holds_the_gun_aimed_at_the_king():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    assert em._check_gun is not None
    assert em._check_gun["from_sq"] == Square(0, 0)
    assert em._check_gun["victim_sq"] == Square(0, 4)
    assert em.drops == []


def test_held_check_gun_does_not_expire_on_update():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.update(10 ** 7)
    assert em._check_gun is not None


def test_opponent_move_drops_the_check_gun():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.cut(now=1000)
    assert em._check_gun is None
    assert len(em.drops) == 1
    drop = em.drops[0]
    assert drop["from_sq"] == Square(0, 0)
    assert drop["start"] == 1000 and drop["dur"] == CHECK_DROP_MS


def test_dropped_gun_fades_out_after_drop_ms():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.cut(now=0)
    em.update(CHECK_DROP_MS - 1)
    assert len(em.drops) == 1
    em.update(CHECK_DROP_MS + 1)
    assert em.drops == []


def test_cut_without_now_clears_held_gun_without_a_drop():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.cut()
    assert em._check_gun is None
    assert em.drops == []


def test_a_second_check_drops_the_previous_held_gun():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.check(now_ms=500, attacker_type="bishop", king_sq=Square(0, 4),
             from_sq=Square(2, 2), cell_size=80)
    assert len(em.drops) == 1
    assert em._check_gun["from_sq"] == Square(2, 2)


def test_clear_drops_held_gun_and_active_drops():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.cut(now=0)
    assert em.drops
    em.clear()
    assert em.drops == [] and em._check_gun is None


def test_drop_motion_finishes_in_a_quarter_of_the_fade_window():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.cut(now=0)
    d = em.drops[0]
    moving = EffectManager._drop_state(d, 100, 100, 0.1)
    settled = EffectManager._drop_state(d, 100, 100, 0.25)
    late = EffectManager._drop_state(d, 100, 100, 0.9)
    assert moving[:3] != settled[:3]
    assert settled[:3] == late[:3]
    assert late[3] < settled[3]
    assert EffectManager._drop_state(d, 100, 100, 0.0)[3] == 255


def test_reduce_motion_suppresses_check_gun():
    em = _em(reduce_motion=True)
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    assert em._check_gun is None and em.drops == []


def test_check_shakes_the_king_piece_horizontally():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    offs = [em.piece_offset(Square(0, 4), t) for t in range(0, KING_SHAKE_MS, 20)]
    assert any(dx != 0 for dx, dy in offs)
    assert all(dy == 0 for dx, dy in offs)
    assert em.piece_offset(Square(0, 4), KING_SHAKE_MS + 1) == (0, 0)


def test_king_shake_only_affects_the_kings_square():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    assert em.piece_offset(Square(3, 3), 40) == (0, 0)


def test_reduce_motion_suppresses_the_king_shake():
    em = _em(reduce_motion=True)
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    assert em._king_shake is None
    assert em.piece_offset(Square(0, 4), 40) == (0, 0)


def test_cut_and_clear_end_the_king_shake():
    em = _em()
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.cut(now=10)
    assert em._king_shake is None
    em.check(now_ms=20, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(0, 0), cell_size=80)
    em.clear()
    assert em._king_shake is None


def test_undo_clears_the_held_check_gun_and_shake():
    board = _board()
    board.effects.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
                        from_sq=Square(0, 0), cell_size=board.cell_size)
    assert board.effects._check_gun is not None
    assert board.effects._king_shake is not None
    board.start_undo_animation(
        SimpleNamespace(from_sq=Square(3, 3), to_sq=Square(3, 3), is_castle=False))
    assert board.effects._check_gun is None
    assert board.effects._king_shake is None


def test_bullet_hole_clears_after_its_shortened_lifetime():
    em = _em()
    em._impact(0, Square(7, 3), Square(0, 3), _surf(), 80)
    total = HOLE_IN_MS + HOLE_HOLD_MS + HOLE_FADE_MS
    em.update(total - 1)
    assert len(em.holes) == 1
    em.update(total + 1)
    assert em.holes == []


def test_cut_keeps_bullet_holes_but_clear_drops_them():
    em = _em()
    em._impact(0, Square(7, 3), Square(0, 3), _surf(), 80)
    assert em.holes and em.particles
    em.cut()
    assert em.holes
    assert em.particles == [] and em.captures == [] and em._shake is None
    em.clear()
    assert em.holes == []


def test_every_piece_gun_has_a_spec():
    for gun in sorted(set(PIECE_GUN.values())):
        assert isinstance(GUNS[gun], GunSpec)


def test_piece_gun_mapping_is_the_art_directed_one():
    assert PIECE_GUN == {
        "pawn": "revolver", "knight": "hand_cannon", "bishop": "lever_action",
        "rook": "shotgun", "queen": "blunderbuss", "king": "ray_gun",
    }


def test_gun_spec_unknown_falls_back_to_revolver():
    assert gunfx.gun_spec("nope") is GUNS["revolver"]


def test_gun_specs_are_frozen():
    with pytest.raises(FrozenInstanceError):
        GUNS["revolver"].scale = 9.0


def test_smoothstep_clamps_and_midpoint():
    assert gunfx.smoothstep(-3) == 0.0
    assert gunfx.smoothstep(5) == 1.0
    assert gunfx.smoothstep(0.5) == pytest.approx(0.5)


def test_weapon_scale_folds_in_spec_scale():
    art = {"guns": {"revolver": {"ax": 10, "ay": 0, "gx": 0, "gy": 0}}, "flashes": {}}
    assert gunfx.gun_base_distance(art, "revolver") == pytest.approx(10.0)
    assert gunfx.weapon_scale(art, "revolver", 50) == pytest.approx(
        50 / 10 * GUNS["revolver"].scale)


def test_aimed_target_projects_barrel_onto_screen():
    img = pg.Surface((20, 20))
    tx, ty = gunfx.aimed_target(img, (0, 0), (10, 0), (100, 100), 0.0)
    assert (round(tx), round(ty)) == (110, 100)


def test_build_weapon_scales_grip_and_barrel():
    art = gunfx.load_battle_art()
    weapon = gunfx.build_weapon(art, "revolver", 60)
    assert weapon is not None
    assert weapon["gun"].get_width() > 0
    assert weapon["barrel"] != (0, 0)


def _board(position_moves=()):
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    match = Match()
    match.new_game()
    for fr, to in position_moves:
        match.try_move(Square(*fr), Square(*to))
    board = Board(win, match)
    board.load_assets()
    board.set_rect(pg.Rect(40, 40, 680, 680))
    return board


def test_cell_rect_applies_shake_offset_base_stays_pure():
    board = _board()
    base = board._cell_rect_base(4, 4)
    board._shake_dx, board._shake_dy = 7, -3
    shaken = board._cell_rect(4, 4)
    assert (shaken.x, shaken.y) == (base.x + 7, base.y - 3)
    assert board._cell_rect_base(4, 4).topleft == base.topleft


def test_cell_at_is_unaffected_by_shake():
    board = _board()
    center = board._cell_rect_base(4, 4).center
    board._shake_dx, board._shake_dy = 9, 9
    assert board.cell_at(center) == Square(4, 4)


def test_draw_board_pulls_active_shake_offset(monkeypatch):
    board = _board()
    board.review_ply = None
    monkeypatch.setattr(board.effects, "shake_offset", lambda now: (6, -4))
    board.draw_board()
    assert (board._shake_dx, board._shake_dy) == (6, -4)


def test_review_mode_zeroes_shake():
    board = _board([((6, 4), (4, 4))])
    board._shake_dx, board._shake_dy = 5, 5
    board.review_ply = 0
    board.draw_board()
    assert (board._shake_dx, board._shake_dy) == (0, 0)


def test_arrows_render_from_base_rect_not_shaken():
    board = _board()
    board.arrows = [(Square(6, 4), Square(4, 4))]
    board._shake_dx, board._shake_dy = 11, 11
    orig = board._cell_rect

    def boom(*_a):
        raise AssertionError("arrow geometry must use _cell_rect_base, not _cell_rect")

    board._cell_rect = boom
    try:
        board._draw_arrows()
    finally:
        board._cell_rect = orig
    assert board._arrow_cache is not None


def test_promotion_popover_anchors_to_base_rect():
    board = _board()
    board.pending_promotion_square = Square(0, 0)
    board._shake_dx, board._shake_dy = 13, 13
    orig = board._cell_rect

    def boom(*_a):
        raise AssertionError("promotion popover must anchor via _cell_rect_base")

    board._cell_rect = boom
    try:
        board._draw_promotion_picker()
    finally:
        board._cell_rect = orig
    assert board._promotion_rects


def _place(board, pieces):
    grid = board.match.state
    for r in range(8):
        for c in range(8):
            grid[r][c] = None
    for sq, piece in pieces.items():
        grid[sq.row][sq.col] = piece


def _no_motion(monkeypatch):
    monkeypatch.setattr("frontend.board.board.env.get_reduce_motion", lambda: False)
    monkeypatch.setattr("frontend.board.board.env.get_effect_intensity", lambda: "full")


def _white_entry():
    return SimpleNamespace(move=SimpleNamespace(piece=SimpleNamespace(color=WHITE)))


def test_segment_empty_detects_a_blocker():
    grid = [[None] * 8 for _ in range(8)]
    assert Board._segment_empty(grid, Square(0, 0), Square(0, 4)) is True
    grid[0][2] = Piece(PAWN, WHITE)
    assert Board._segment_empty(grid, Square(0, 0), Square(0, 4)) is False


def test_king_square_locates_both_kings():
    board = _board()
    _place(board, {
        Square(0, 4): Piece(KING, BLACK),
        Square(7, 4): Piece(KING, WHITE),
    })
    assert board._king_square(BLACK) == Square(0, 4)
    assert board._king_square(WHITE) == Square(7, 4)
    assert board._king_square(BLACK) != board._king_square(WHITE)


def test_checking_square_skips_blocked_slider_finds_real_checker():
    board = _board()
    _place(board, {
        Square(0, 4): Piece(KING, BLACK),
        Square(7, 4): Piece(KING, WHITE),
        Square(0, 0): Piece(ROOK, WHITE),
        Square(0, 2): Piece(PAWN, WHITE),
        Square(4, 4): Piece(QUEEN, WHITE),
    })
    assert board._checking_square(Square(0, 4), WHITE) == Square(4, 4)


def test_show_check_gun_points_from_checker_to_king(monkeypatch):
    _no_motion(monkeypatch)
    board = _board()
    _place(board, {
        Square(0, 4): Piece(KING, BLACK),
        Square(7, 4): Piece(KING, WHITE),
        Square(0, 0): Piece(ROOK, WHITE),
    })
    board.show_check_gun(_white_entry())
    held = board.effects._check_gun
    assert held is not None
    assert held["from_sq"] == Square(0, 0)
    assert held["victim_sq"] == Square(0, 4)


def test_show_check_gun_noop_when_king_not_attacked(monkeypatch):
    _no_motion(monkeypatch)
    board = _board()
    _place(board, {
        Square(0, 0): Piece(KING, BLACK),
        Square(7, 7): Piece(KING, WHITE),
        Square(4, 4): Piece(ROOK, WHITE),
    })
    board.show_check_gun(_white_entry())
    assert board.effects._check_gun is None


def test_show_check_gun_noop_in_review_mode(monkeypatch):
    _no_motion(monkeypatch)
    board = _board()
    _place(board, {
        Square(0, 4): Piece(KING, BLACK),
        Square(7, 4): Piece(KING, WHITE),
        Square(0, 0): Piece(ROOK, WHITE),
    })
    board.review_ply = 0
    board.show_check_gun(_white_entry())
    assert board.effects._check_gun is None


def test_kill_callout_fires_at_the_shot_not_at_move_start(monkeypatch):
    _no_motion(monkeypatch)
    board = _board()
    _place(board, {
        Square(7, 4): Piece(KING, WHITE),
        Square(0, 4): Piece(KING, BLACK),
        Square(4, 3): Piece(QUEEN, WHITE),
        Square(2, 3): Piece(PAWN, BLACK),
    })
    board.match.backend.turn = WHITE
    board.match.backend.move_history = []
    board.handle_click(Square(4, 3))
    board.handle_click(Square(2, 3))
    assert board.effects.captures
    assert board.effects.callouts == [] and _tags(board.effects) == []
    c = board.effects.captures[0]
    board.effects.update(c["fire_at"] - 1)
    assert board.effects.callouts == []
    board.effects.update(c["fire_at"])
    assert len(board.effects.callouts) == 1


def test_capture_routes_announcer_key_to_callback(monkeypatch):
    _no_motion(monkeypatch)
    board = _board()
    keys = []
    board.announce_callback = keys.append
    _place(board, {
        Square(7, 4): Piece(KING, WHITE),
        Square(0, 4): Piece(KING, BLACK),
        Square(4, 3): Piece(QUEEN, WHITE),
        Square(2, 3): Piece(PAWN, BLACK),
    })
    board.match.backend.turn = WHITE
    board.match.backend.move_history = []
    board.handle_click(Square(4, 3))
    board.handle_click(Square(2, 3))
    assert keys == []
    board.effects.update(board.effects.captures[0]["fire_at"])
    assert keys == ["first_blood"]


def test_capture_power_scales_with_victim_value():
    assert Board._capture_power(QUEEN) == "hard"
    assert Board._capture_power(ROOK) == "hard"
    assert Board._capture_power(BISHOP) == "med"
    assert Board._capture_power(KNIGHT) == "med"
    assert Board._capture_power(PAWN) == "soft"


def test_first_kill_of_the_game_is_first_blood():
    em = _em()
    em.register_kill("white", Square(0, 4), 80, 0)
    assert em._streak_count == 1
    assert len(em.callouts) == 1
    assert _tags(em) == []
    assert em.callouts[0]["dur"] == CALLOUT_LG_MS


def test_streak_labels_escalate_for_same_side():
    em = _em()
    durs = []
    for i in range(7):
        em.register_kill("white", Square(0, 4), 80, i)
        durs.append(em.callouts[0]["dur"] if em.callouts else None)
    assert em._streak_count == 7
    assert durs[0] == CALLOUT_LG_MS
    assert durs[1] == CALLOUT_LG_MS
    assert durs[3] == CALLOUT_LG_MS
    assert durs[4] == CALLOUT_XL_MS
    assert durs[6] == CALLOUT_XL_MS


def test_eighth_consecutive_kill_falls_back_to_a_hit_word_tag():
    em = _em()
    for i in range(7):
        em.register_kill("white", Square(0, 4), 80, i)
    em.update(10_000)
    em.register_kill("white", Square(0, 4), 80, 10_001)
    assert em._streak_count == 8
    assert em.callouts == []
    assert len(_tags(em)) == 1


def test_recapture_by_the_other_side_resets_the_streak():
    em = _em()
    em.register_kill("white", Square(0, 4), 80, 0)
    em.register_kill("white", Square(0, 4), 80, 10)
    assert em._streak_count == 2
    em.register_kill("black", Square(4, 4), 80, 20)
    assert em._streak_color == "black"
    assert em._streak_count == 1


def test_same_side_kill_after_a_quiet_move_keeps_building():
    em = _em()
    em.register_kill("white", Square(0, 4), 80, 0)
    em.register_kill("white", Square(0, 4), 80, 50)
    assert em._streak_count == 2


def test_first_blood_only_once_per_game():
    em = _em()
    em.register_kill("white", Square(0, 4), 80, 0)
    em.register_kill("black", Square(4, 4), 80, 10)
    assert em._first_blood_spent is True
    assert em._streak_count == 1
    assert len(_tags(em)) == 1


def test_clear_rearms_first_blood_and_resets_streak():
    em = _em()
    for i in range(3):
        em.register_kill("white", Square(0, 4), 80, i)
    em.clear()
    assert em._streak_color is None
    assert em._streak_count == 0
    assert em._first_blood_spent is False
    assert em.callouts == []


def test_hit_word_tag_anchors_to_the_captured_square():
    em = _em()
    for i in range(7):
        em.register_kill("white", Square(0, 4), 80, i)
    em.update(10_000)
    em.register_kill("white", Square(2, 3), 80, 10_001)
    tag = _tags(em)[0]
    assert tag["dur"] == TAG_MS
    assert tag["victim_sq"] == Square(2, 3)


def test_callout_replaces_so_only_one_big_callout_at_a_time():
    em = _em()
    em.register_kill("white", Square(0, 4), 80, 0)
    em.register_kill("white", Square(0, 4), 80, 10)
    assert len(em.callouts) == 1


def test_callout_expires_after_its_duration():
    em = _em()
    em.register_kill("white", Square(0, 4), 80, 0)
    dur = em.callouts[0]["dur"]
    em.update(dur - 1)
    assert len(em.callouts) == 1
    em.update(dur + 1)
    assert em.callouts == []


def test_callout_animation_keyframes():
    assert EffectManager._callout_anim(0.0) == (0.5, 0)
    scale_in, alpha_in = EffectManager._callout_anim(0.12)
    assert scale_in == pytest.approx(1.06)
    assert alpha_in == 255
    scale_hold, alpha_hold = EffectManager._callout_anim(0.5)
    assert alpha_hold == 255
    assert 1.0 <= scale_hold <= 1.06
    scale_out, alpha_out = EffectManager._callout_anim(0.99)
    assert alpha_out < 40


def test_tag_animation_rises_and_fades():
    rise0, scale0, alpha0 = EffectManager._tag_anim(0.0)
    assert (rise0, alpha0) == (0.0, 0)
    rise_peak, scale_peak, alpha_peak = EffectManager._tag_anim(0.25)
    assert alpha_peak == 255
    assert scale_peak == pytest.approx(1.1)
    rise_end, _, alpha_end = EffectManager._tag_anim(0.99)
    assert rise_end > rise_peak
    assert alpha_end < 10


def test_register_kill_returns_the_announcer_key():
    em = _em()
    seq = [em.register_kill("white", Square(0, 4), 80, i) for i in range(8)]
    assert seq == ["first_blood", "double_kill", "triple_kill", "quadra_kill",
                   "rampage", "unstoppable", "godlike", "hit"]
    assert em.register_kill("black", Square(4, 4), 80, 99) == "hit"


def test_streak_label_table_matches_the_design():
    assert STREAK_LABELS == {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL",
                             5: "RAMPAGE", 6: "UNSTOPPABLE", 7: "GODLIKE"}
    assert HIT_WORDS == ("BLAM", "BOOM", "POW", "BANG", "HEADSHOT", "BODIED", "WASTED")


def test_callout_paints_pixels_and_replaces_rather_than_stacks():
    em = _em()
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    em.register_kill("white", Square(2, 3), 80, 0)
    em.update(300)
    em.draw_over(win, 300)
    assert any(win.get_at((x, y))[:3] != (0, 0, 0)
               for x in range(280, 520, 4) for y in range(290, 390, 4)), \
        "the callout text paints near the board centre"
    em.register_kill("white", Square(2, 3), 80, 400)
    em.draw_over(win, 520)
    assert len(em.callouts) == 1, "a new callout replaces the previous one, never stacks"


def test_takeover_lifecycle():
    em = _em()
    assert not em.has_takeover()
    em.start_takeover("CHECKMATE", "WHITE", 0)
    assert em.has_takeover()
    em.clear_takeover()
    assert not em.has_takeover()


def test_takeover_paints_the_backdrop_across_its_active_window():
    em = _em()
    em.start_takeover("CHECKMATE", "WHITE", 0)
    win = pg.display.get_surface()
    for now in (0, TAKEOVER_PAUSE_MS, TAKEOVER_PAUSE_MS + 200, TAKEOVER_PAUSE_MS + 800,
                TAKEOVER_TOTAL_MS - 100, TAKEOVER_TOTAL_MS):
        win.fill((0, 0, 0))
        em.draw_takeover(win, now)
        if now > TAKEOVER_PAUSE_MS:
            assert win.get_at((5, 5))[:3] != (0, 0, 0), \
                f"the takeover backdrop should cover the screen at t={now}"
    assert em.has_takeover()


def test_takeover_holds_the_position_during_the_opening_pause():
    em = _em()
    em.start_takeover("CHECKMATE", "WHITE", 0)
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    em.draw_takeover(win, TAKEOVER_PAUSE_MS - 100)
    assert win.get_at((5, 5)) == pg.Color(0, 0, 0, 255)
    em.draw_takeover(win, TAKEOVER_PAUSE_MS + 120)
    assert win.get_at((5, 5)) != pg.Color(0, 0, 0, 255)


def test_takeover_draw_clamps_negative_time():
    em = _em()
    em.start_takeover("CHECKMATE", "BLACK", 1000)
    win = pg.display.get_surface()
    em.draw_takeover(win, 500)
    assert em.has_takeover()


def test_raise_flag_then_clear():
    em = _em()
    em.raise_flag(Square(0, 4), 80, 0)
    assert len(em.flags) == 1
    assert em.flags[0]["sq"] == Square(0, 4)
    em.start_takeover("CHECKMATE", "WHITE", 0)
    em.clear()
    assert em.flags == [] and not em.has_takeover()


def test_flag_paints_near_the_kings_square_through_its_pop():
    em = _em()
    em.raise_flag(Square(0, 4), 80, 0)
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    for now in (0, 150, 400):
        em.draw_over(win, now)
    assert any(win.get_at((x, y))[:3] != (0, 0, 0)
               for x in range(455, 498, 2) for y in range(6, 50, 2)), \
        "the surrender flag paints near the king's square"
    assert len(em.flags) == 1


def test_flag_pop_overshoots_then_settles():
    assert EffectManager._pop(0.0) == pytest.approx(0.0, abs=1e-6)
    assert EffectManager._pop(1.0) == pytest.approx(1.0, abs=1e-6)
    assert max(EffectManager._pop(x) for x in (0.6, 0.7, 0.8)) > 1.0


def test_board_show_surrender_flag_anchors_to_the_kings_square():
    board = _board()
    _place(board, {Square(0, 4): Piece(KING, BLACK), Square(7, 4): Piece(KING, WHITE)})
    board.show_surrender_flag(BLACK)
    assert [f["sq"] for f in board.effects.flags] == [Square(0, 4)]


def test_board_show_checkmate_takeover_activates(monkeypatch):
    _no_motion(monkeypatch)
    board = _board()
    board.show_checkmate_takeover("WHITE")
    assert board.effects.has_takeover()


def test_checkmate_result_triggers_takeover_and_loser_flag(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "current_result", lambda: "white_wins")
    app._trigger_result_effects()
    assert app.board.effects.has_takeover()
    assert [f["sq"] for f in app.board.effects.flags] == [Square(0, 4)]


def test_resignation_raises_flag_without_takeover(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "current_result", lambda: "black_wins_by_resignation")
    app._trigger_result_effects()
    assert not app.board.effects.has_takeover()
    assert [f["sq"] for f in app.board.effects.flags] == [Square(7, 4)]


def test_timeout_win_raises_no_flag_and_no_takeover(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "current_result", lambda: "white_wins_on_time")
    app._trigger_result_effects()
    assert not app.board.effects.has_takeover()
    assert app.board.effects.flags == []


def test_draw_triggers_no_win_effects(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "current_result", lambda: "draw_agreement")
    app._trigger_result_effects()
    assert not app.board.effects.has_takeover()
    assert app.board.effects.flags == []


def test_result_sequence_waits_for_capture_choreography(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "current_result", lambda: "white_wins")
    app.board.effects.captures = [{"in_flight": True}]
    app._update_result_pending()
    assert app._result_first_seen_at_ms is None
    assert not app.board.effects.has_takeover()
    app.board.effects.captures = []
    app._update_result_pending()
    assert app._result_first_seen_at_ms is not None
    assert app.board.effects.has_takeover()


def test_result_modal_waits_longer_while_a_takeover_plays(monkeypatch):
    app = _app()
    monkeypatch.setattr(app, "current_result", lambda: "white_wins")
    app._update_result_pending()
    assert app.board.effects.has_takeover()
    app._result_first_seen_at_ms = pg.time.get_ticks() - 600
    assert app._result_modal_should_show() is False
    app._result_first_seen_at_ms = pg.time.get_ticks() - (TAKEOVER_TOTAL_MS + 50)
    assert app._result_modal_should_show() is True
