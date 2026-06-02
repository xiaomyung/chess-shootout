"""Phase 10a gun-fight capture/effects layer.

Three surfaces are covered:
  * EffectManager (frontend/visual/effects.py) — the two-stage capture
    choreography (draw/aim -> fire -> travel -> impact), the board screen-shake
    decay, the check gun-draw, and reduce-motion / intensity gating. A fake
    `geom` resolver and an injected deterministic rng make every assertion
    reproducible across xdist workers.
  * gunfx (frontend/visual/gunfx.py) — the shared GunSpec/GUNS registry that
    consolidated menu-battle's scattered gun dicts, plus the aim geometry.
  * Board (frontend/board/board.py) — that shake rides _cell_rect while
    _cell_rect_base / cell_at / arrows / the promotion popover opt out, and that
    show_check_gun locates the real checking piece (including through a blocker).
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pygame as pg
import pytest

from backend.match import Match
from backend.pieces import Piece, PieceColor, PieceType
from backend.utils import Square
from frontend.board import Board
from frontend.visual import gunfx
from frontend.visual.effects import (
    AIM_MS, CHECK_DROP_MS, DRAW_MS, HOLE_FADE_MS, HOLE_HOLD_MS, HOLE_IN_MS,
    INTENSITY_SCALE, PIECE_GUN, RECOIL_MS, SHAKE_AMP, SHAKE_HARD_MS, EffectManager,
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
    pg.display.set_mode((780, 780))
    yield
    pg.quit()


def _em(reduce_motion=False, intensity="full", seed=7):
    em = EffectManager(rng=random.Random(seed))
    em.geom = lambda sq: (sq.col * 100 + 50, sq.row * 100 + 50)
    em.configure(reduce_motion, intensity)
    return em


def _surf():
    return pg.Surface((40, 40), pg.SRCALPHA)


# --------------------------------------------------------------------------- #
# Screen shake
# --------------------------------------------------------------------------- #
def test_shake_offset_zero_when_idle():
    assert _em().shake_offset(0) == (0, 0)


def test_trigger_shake_is_bounded_then_self_clears():
    em = _em()
    em._trigger_shake(1000, "hard")
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
    em._trigger_shake(0, "hard")
    early = max(abs(c) for c in em.shake_offset(int(SHAKE_HARD_MS * 0.05)))
    late = max(abs(c) for c in em.shake_offset(int(SHAKE_HARD_MS * 0.95)))
    assert late < early


def test_reduce_motion_suppresses_shake():
    em = _em(reduce_motion=True)
    em._trigger_shake(0, "hard")
    assert em._shake is None
    assert em.shake_offset(10) == (0, 0)


def test_intensity_scales_shake_amplitude():
    full = _em(intensity="full")
    full._trigger_shake(0, "hard")
    subtle = _em(intensity="subtle")
    subtle._trigger_shake(0, "hard")
    assert full._shake["amp"] == pytest.approx(SHAKE_AMP["hard"] * 1.0)
    assert subtle._shake["amp"] == pytest.approx(
        SHAKE_AMP["hard"] * INTENSITY_SCALE["subtle"])
    assert subtle._shake["amp"] < full._shake["amp"]


# --------------------------------------------------------------------------- #
# Two-stage capture choreography
# --------------------------------------------------------------------------- #
def test_capture_defers_fire_and_impact_with_correct_timing():
    em = _em()
    fired, slid = [], []
    em.capture(now_ms=1000, attacker_type="queen", attacker_surface=_surf(),
               victim_surface=_surf(), from_sq=Square(7, 3), victim_sq=Square(0, 3),
               to_sq=Square(0, 3), cell_size=80, power="hard",
               on_fire=lambda: fired.append(1), on_slide=lambda: slid.append(1))
    assert len(em.captures) == 1
    c = em.captures[0]
    assert c["fire_at"] == 1000 + DRAW_MS + AIM_MS
    assert c["impact_at"] > c["fire_at"]
    assert Square(0, 3) in em.held_squares()

    em.update(c["fire_at"] - 1)
    assert fired == [] and slid == []

    em.update(c["fire_at"])
    assert fired == [1] and slid == []
    assert any(p["kind"] == "projectile" for p in em.particles)
    assert Square(0, 3) in em.held_squares()

    em.update(c["impact_at"])
    assert slid == [1]
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
    em.update(c["impact_at"])
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


# --------------------------------------------------------------------------- #
# Check gun-draw: held until the opponent moves, then dropped (menu-battle style)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# cut() / clear() lifecycle
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# gunfx registry + geometry
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Board shake integration
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Board check-gun wiring
# --------------------------------------------------------------------------- #
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


def test_capture_power_scales_with_victim_value():
    assert Board._capture_power(QUEEN) == "hard"
    assert Board._capture_power(ROOK) == "hard"
    assert Board._capture_power(BISHOP) == "med"
    assert Board._capture_power(KNIGHT) == "med"
    assert Board._capture_power(PAWN) == "soft"
