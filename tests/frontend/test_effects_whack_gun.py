"""The px-target held gun: during a whack skill-check the ATTACKER piece keeps its
gun out and tracks a live pixel target (the mover's crosshair, the mirror's relayed
impact) instead of a square center — the check gun (`check()`) can only point at a
square, so the two states are independent and a check reload can never steal the
whack gun's aim.

The aim is smoothed with the menu-battle formula (delta wrapped to (-pi, pi],
GUN_PX_AIM_RATE per second) so the barrel swings after the crosshair rather than
snapping to it, and every element is derived from the same pivot/muzzle geometry
the capture path uses — `aimed_target` off the SMOOTHED angle, so a shot leaves the
barrel where the barrel actually points.

Shots are purely cosmetic: no lead pellet, no capture to resolve, no bystander
wounding (inert), and — unlike the capture volley, which is allowed to sail on for
PROJECTILE_MAX_MS — the slug's lifetime is capped at its own travel time so it dies
AT the impact point. WHACK_SHOT_TRAVEL_MS is deliberately far snappier than the
capture travel: the pellet has to land while the hit still reads as one beat.

A WON check hands the gun over instead of dropping it: hand_off_gun_px() clears the
held state SILENTLY (no tumble) and arms a one-shot handoff keyed by the shooter's
square, which the very next capture() from that square consumes as predrawn — no
draw-flourish, fire_at only AIM_MS out, so the check's last aimed frame and the
capture's first aimed frame are the same picture. The latch is keyed by square (a
capture by any other piece cannot inherit it) and deliberately SURVIVES cut(), which
board._start_move_animation fires between the handoff and the capture; only a real
reset (clear_transients) drops it. capture(predrawn=True) is the same switch for
callers that can pass it directly — the session cannot, because its capture is three
frames deep behind board.apply_gated_move.
"""

import math
import random

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.visual.effects import (
    AIM_MS, CHECK_DROP_MS, DRAW_MS, GUN_PX_AIM_RATE, MUZZLE_MS, PROJECTILE_MAX_MS,
    WHACK_SHOT_LIFE_EPS_MS, WHACK_SHOT_TRAVEL_MS, EffectManager)
from chessshootout.frontend.visual.gunfx import GUNS, PIECE_GUN

_pygame_init = pygame_display(800, 800)

_CELL = 100
_FROM = Square(6, 4)


def _em(seed=7):
    em = EffectManager(rng=random.Random(seed))
    em.geom = lambda sq: (sq.col * _CELL + _CELL // 2, sq.row * _CELL + _CELL // 2)
    em.board_rect = pg.Rect(0, 0, 800, 800)
    return em


def _held(em, attacker_type="pawn", target_px=None, now_ms=0):
    em.hold_gun_px(now_ms=now_ms, attacker_type=attacker_type, from_sq=_FROM,
                   cell_size=_CELL, target_px=target_px)
    return em._whack_gun


def _pivot(em):
    return em._pivot(_FROM, _CELL)


def _window():
    return pg.Surface((800, 800))


def _pixels(surf, rect):
    return pg.image.tostring(surf.subsurface(rect), "RGB")


def test_holding_the_px_gun_arms_an_independent_state():
    em = _em()
    g = _held(em)
    assert g is not None and em.has_gun_px() is True
    assert em._check_gun is None, "the check gun state is untouched — the two never share"
    assert em.is_active() is True, "the effects layer must keep drawing for the held gun"


def test_a_check_reload_cannot_steal_the_whack_gun():
    em = _em()
    _held(em, attacker_type="queen")
    em.check(now_ms=0, attacker_type="rook", king_sq=Square(0, 4),
             from_sq=Square(7, 0), cell_size=_CELL)
    assert em.has_gun_px() is True, "the whack gun survives a check landing mid-overlay"
    assert em._check_gun is not None
    assert em._whack_gun["weapon"] is not em._check_gun["weapon"], "each keeps its own weapon"


def test_hold_points_at_the_initial_target_and_defaults_to_zero_without_one():
    em = _em()
    px, py = _pivot(em)
    assert _held(em, target_px=(px, py - 200))["aim"] == pytest.approx(-math.pi / 2)
    assert _held(em)["aim"] == 0.0, "no target yet — the barrel starts level"


def test_aim_eases_toward_the_target_instead_of_snapping():
    em = _em()
    px, py = _pivot(em)
    g = _held(em, target_px=(px + 200, py))
    assert g["aim"] == pytest.approx(0.0)
    up = (px, py - 200)
    em.aim_gun_px(up, 16)
    step = g["aim"]
    want = -math.pi / 2
    assert want < step < 0.0, "one frame swings toward the target"
    fraction = step / want
    assert 0.0 < fraction < 0.5, \
        "and covers only a fraction of the gap — a snap would land on the target"
    assert fraction == pytest.approx(min(1.0, 0.016 * GUN_PX_AIM_RATE), abs=0.01)
    for t in range(32, 1200, 16):
        em.aim_gun_px(up, t)
    assert g["aim"] == pytest.approx(want, abs=0.01), "it converges given enough frames"


def test_aim_takes_the_short_way_round_the_wrap():
    em = _em()
    px, py = _pivot(em)
    g = _held(em)
    g["aim"] = math.pi - 0.05
    em.aim_gun_px((px - 200, py + 10), 16)
    assert g["aim"] > math.pi - 0.05, \
        "crossing +pi keeps turning the same way instead of unwinding a full circle"


def test_aim_is_inert_without_a_gun_or_a_target():
    em = _em()
    em.aim_gun_px((10, 10), 16)
    assert em.has_gun_px() is False
    g = _held(em)
    em.aim_gun_px(None, 16)
    assert g["aim"] == 0.0, "a missing target leaves the barrel where it was"


def test_release_drops_the_gun_with_a_tumble():
    em = _em()
    _held(em)
    em.release_gun_px(500)
    assert em.has_gun_px() is False
    assert len(em.drops) == 1, "the gun tumbles away like the check gun's release"
    drop = em.drops[0]
    assert drop["from_sq"] == _FROM and drop["dur"] == CHECK_DROP_MS
    assert drop["spin"] != 0.0
    em.release_gun_px(600)
    assert len(em.drops) == 1, "releasing twice never spawns a second drop"


def test_firing_spawns_the_attacker_guns_own_slug():
    em = _em()
    target = (250.0, 250.0)
    _held(em, attacker_type="knight")
    em.fire_gun_px(0, target)
    spec = GUNS[PIECE_GUN["knight"]]
    assert em.projectiles, "a registered hit puts a slug in the air"
    assert {pr["color"] for pr in em.projectiles} == {spec.color}, \
        "the projectile carries the capturing piece's gun colour"
    assert all(not pr["lead"] and pr["capture"] is None for pr in em.projectiles), \
        "the whack volley is cosmetic — it resolves no capture"
    assert all(pr["inert"] for pr in em.projectiles), "and wounds no bystander"


def test_firing_leaves_the_muzzle_along_the_smoothed_aim():
    em = _em()
    px, py = _pivot(em)
    g = _held(em, target_px=(px + 200, py))
    em.fire_gun_px(0, (px, py - 300))
    flashes = [p for p in em.particles if p["kind"] == "flash_px"]
    assert len(flashes) == 1, "the fire triggers the held gun's muzzle flash"
    assert flashes[0]["aim"] == g["aim"] and flashes[0]["dur"] == MUZZLE_MS
    assert flashes[0]["muzzle"][0] > px, \
        "the flash sits off the barrel tip, which still points where the gun points"
    pr = em.projectiles[0]
    assert pr["vy"] < 0 and pr["y"] < py, "the slug still flies at the impact point"
    assert g["fired_at"] == 0, "and the gun recoils"


def test_a_shotgun_attacker_sprays_the_whole_pellet_spread():
    em = _em()
    _held(em, attacker_type="rook")
    em.fire_gun_px(0, (250.0, 250.0))
    spec = GUNS[PIECE_GUN["rook"]]
    assert spec.pellets > 1
    assert len(em.projectiles) == spec.pellets, "the rook's shotgun sprays every pellet"
    angles = {math.atan2(pr["vy"], pr["vx"]) for pr in em.projectiles}
    assert len(angles) == spec.pellets, "each pellet gets its own spread angle"


def test_firing_without_a_held_gun_is_a_no_op():
    em = _em()
    em.fire_gun_px(0, (250.0, 250.0))
    assert em.projectiles == [] and em.particles == []
    _held(em)
    em.fire_gun_px(0, None)
    assert em.projectiles == [], "and a missing impact point fires nothing"


def test_the_slug_dies_at_the_impact_point_instead_of_flying_past():
    em = _em()
    target = em.geom(Square(4, 4))
    _held(em, target_px=target)
    em.update(0)
    em.fire_gun_px(0, target)
    pr = em.projectiles[0]
    assert pr["max_ms"] == WHACK_SHOT_TRAVEL_MS + WHACK_SHOT_LIFE_EPS_MS
    assert pr["max_ms"] < PROJECTILE_MAX_MS, "far shorter than the capture volley's lifetime"
    for t in range(20, WHACK_SHOT_TRAVEL_MS + 1, 20):
        em.update(t)
    assert em.projectiles, "it is still in the air right up to the impact"
    assert math.hypot(pr["x"] - target[0], pr["y"] - target[1]) <= 4, \
        "and it is ON the impact point at travel time"
    em.update(WHACK_SHOT_TRAVEL_MS + WHACK_SHOT_LIFE_EPS_MS + 1)
    assert em.projectiles == [], "one frame later it is gone — nothing sails on"


def test_whack_slugs_never_wound_a_bystander_they_cross():
    em = _em()
    bystander = Square(4, 4)
    em._bystanders = {bystander}
    target = em.geom(Square(2, 4))
    _held(em)
    em.update(0)
    em.fire_gun_px(0, target)
    for t in range(20, WHACK_SHOT_TRAVEL_MS + 1, 20):
        em.update(t)
    assert em._bystanders == {bystander}, "a cosmetic slug consumes no bystander"
    assert [p for p in em.particles if p["kind"] == "blood"] == [], "and draws no blood"


def test_the_held_gun_flourishes_then_tracks_and_never_reallocates():
    em = _em()
    window = _window()
    px, py = _pivot(em)
    _held(em, attacker_type="queen", target_px=(px + 200, py))
    em.draw_over(window, DRAW_MS // 2)
    for i in range(100):
        now = DRAW_MS + i * 16
        em.aim_gun_px((px + 200 - i, py - i), now)
        em.update(now)
        em.draw_over(window, now)
    assert em.projectiles == [] and em.drops == [], "an idle tracking gun spawns nothing"
    assert em.particles == [], "and holds no per-frame particle"
    assert len(em._weapon_cache) == 1, "the weapon is built once, never per frame"


def test_the_gun_actually_paints_pixels_at_the_attacker():
    em = _em()
    px, py = _pivot(em)
    empty = _window()
    em.draw_over(empty, 0)
    held = _window()
    _held(em, attacker_type="rook", target_px=(px + 200, py))
    em.draw_over(held, DRAW_MS + 1)
    around = pg.Rect(int(px) - 80, int(py) - 80, 160, 160)
    far = pg.Rect(0, 0, 160, 160)
    assert _pixels(held, around) != _pixels(empty, around), \
        "the barrel is painted at the capturer, not lost to a silent early return"
    assert _pixels(held, far) == _pixels(empty, far), "and only there"


def _capture(em, from_sq=_FROM, victim_sq=Square(4, 4), now_ms=0, **kw):
    surf = pg.Surface((_CELL, _CELL), pg.SRCALPHA)
    surf.fill((200, 40, 40, 255))
    em.capture(now_ms=now_ms, attacker_type="queen", attacker_surface=surf,
               victim_surface=surf, from_sq=from_sq, victim_sq=victim_sq,
               to_sq=victim_sq, cell_size=_CELL, **kw)
    return em.captures[-1]


def test_a_predrawn_capture_skips_the_draw_flourish_entirely():
    em = _em()
    normal = _capture(em)
    assert normal["predrawn"] is False
    assert normal["fire_at"] == DRAW_MS + AIM_MS, "the untouched capture still draws first"
    em.captures = []
    fast = _capture(em, predrawn=True)
    assert fast["predrawn"] is True
    assert fast["fire_at"] == AIM_MS, "a gun already in hand only needs the aim beat"


def test_the_predrawn_capture_paints_the_gun_on_its_very_first_frame():
    em = _em()
    slow, fast = _window(), _window()
    _capture(em)
    em.draw_over(slow, 0)
    em.captures = []
    _capture(em, predrawn=True)
    em.draw_over(fast, 0)
    region = pg.Rect(int(_pivot(em)[0]) - 90, int(_pivot(em)[1]) - 90, 180, 180)
    assert _pixels(fast, region) != _pixels(slow, region), \
        "frame zero of the flourish is an empty spin-up; the handoff is already aimed"


def test_the_win_handoff_drops_nothing_and_predraws_the_capture():
    em = _em()
    _held(em, attacker_type="queen")
    em.hand_off_gun_px()
    assert em.has_gun_px() is False, "the held gun leaves the whack state"
    assert em.drops == [], "a WON check never tumbles the gun — the capture keeps shooting it"
    assert _capture(em)["predrawn"] is True, "the capture picks it straight back up"


def test_the_handoff_belongs_to_the_shooter_and_is_consumed_once():
    em = _em()
    _held(em)
    em.hand_off_gun_px()
    other = _capture(em, from_sq=Square(1, 1))
    assert other["predrawn"] is False, "another piece's capture cannot inherit the handoff"
    em.captures = []
    assert _capture(em)["predrawn"] is False, "and a stale latch never survives one capture"


def test_the_handoff_survives_the_boards_cut_but_not_a_reset():
    em = _em()
    _held(em)
    em.hand_off_gun_px()
    em.cut(500)
    assert em.drops == [], "cut runs between the handoff and the capture — nothing tumbles"
    assert _capture(em)["predrawn"] is True, "and the handoff is still live for it"
    _held(em)
    em.hand_off_gun_px()
    em.clear_transients()
    em.captures = []
    assert _capture(em)["predrawn"] is False, "a real reset drops the latch"


def test_arming_a_fresh_check_clears_a_stale_handoff():
    em = _em()
    _held(em)
    em.hand_off_gun_px()
    _held(em)
    em.release_gun_px(500)
    assert _capture(em)["predrawn"] is False, \
        "a check that ended in a tumble cannot leave a predrawn capture behind it"


def test_cut_and_clear_transients_never_leave_the_gun_behind():
    em = _em()
    _held(em)
    em.cut(500)
    assert em.has_gun_px() is False
    assert len(em.drops) == 1, "cut tumbles it away when it knows the clock"
    _held(em)
    em.clear_transients()
    assert em.has_gun_px() is False, "a new game can never inherit a held gun"
