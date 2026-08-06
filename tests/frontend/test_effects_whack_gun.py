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

A finished check hands the gun over instead of dropping it: hand_off_gun_px() clears
the held state SILENTLY (no tumble) and arms a one-shot handoff keyed by the
shooter's square, which the very next capture() OR miss() from that square consumes
as predrawn — no draw-flourish, so the check's last aimed frame and the shot's first
aimed frame are the same picture. The latch is keyed by square (a capture by any
other piece cannot inherit it) and deliberately SURVIVES cut(), which
board._start_move_animation fires between the handoff and the capture; only a real
reset (clear_transients) drops it, and re-arming a check (hold_gun_px) clears a stale
one. capture(predrawn=True) is the same switch for callers that can pass it directly
— the session cannot, because its capture is three frames deep behind
board.apply_gated_move.

A consumed handoff means MORE than a predrawn gun on the WIN path: the whack already
killed the victim (its body is blasted off the pit by the check's own choreography,
and the kill flair is credited there at the killing pixel), so the capture behind it
is ADVANCE-ONLY — the fire phase is skipped whole. No pellet, no muzzle flash, no
impact/blood/hole/ragdoll, no victim sprite to draw, no recoil, and no wait: it has
nothing to aim at and nothing to fly, so on_fire and on_slide both land on the very
first update and the entry retires immediately. Every on_fire callback receives the
advance_only flag as its argument (no instance-flag windowing around the call), and
board._on_capture_fire returns on it before crediting a second kill or cueing a
gunshot.
The FAIL path consumes the same handoff, but a miss is a real volley — it draws no
new gun, then shoots and whiffs on schedule. Captures with no check behind them still
draw, aim, fire and travel exactly as before.
"""

import math
import random
from types import SimpleNamespace

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.domain.match import Match
from chessshootout.frontend.board import Board
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.effects import (
    AIM_MS, CHECK_DROP_MS, DRAW_MS, GUN_PX_AIM_RATE, MUZZLE_MS, PROJECTILE_MAX_MS,
    PROJECTILE_TRAVEL_MS, TAG_MS, WHACK_SHOT_LIFE_EPS_MS, WHACK_SHOT_TRAVEL_MS,
    EffectManager)
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
    start = math.pi - 0.05
    g["aim"] = start
    target = (px - 200, py - 10)
    raw = em._angle_to(_pivot(em), target) - start
    assert raw < -math.pi, \
        "the unwrapped difference is a near-full turn backwards — the wrap is live here"
    em.aim_gun_px(target, 16)
    assert g["aim"] > start, \
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
    entry = _capture(em)
    assert entry["predrawn"] is True, "the capture picks it straight back up"
    assert entry["advance_only"] is True, "and it advances instead of firing again"


def test_the_handoff_belongs_to_the_shooter_and_is_consumed_once():
    em = _em()
    _held(em)
    em.hand_off_gun_px()
    other = _capture(em, from_sq=Square(1, 1))
    assert other["predrawn"] is False, "another piece's capture cannot inherit the handoff"
    assert other["advance_only"] is False, "and it shoots for itself"
    em.captures = []
    stale = _capture(em)
    assert stale["predrawn"] is False, "and a stale latch never survives one capture"
    assert stale["advance_only"] is False


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
    entry = _capture(em)
    assert entry["predrawn"] is False, "a real reset drops the latch"
    assert entry["advance_only"] is False, "and the capture behind it shoots normally"


def test_arming_a_fresh_check_clears_a_stale_handoff():
    em = _em()
    _held(em)
    em.hand_off_gun_px()
    _held(em)
    em.release_gun_px(500)
    entry = _capture(em)
    assert entry["predrawn"] is False, \
        "a check that ended in a tumble cannot leave a predrawn capture behind it"
    assert entry["advance_only"] is False


def _armed_advance(em, **kw):
    _held(em, attacker_type="queen")
    em.hand_off_gun_px()
    return _capture(em, **kw)


def test_the_capture_behind_a_won_whack_never_fires_a_second_time():
    # The victim was already blasted off the pit by the whack choreography; a
    # second volley shot a corpse and the impact FX rebuilt it to shred it again.
    em = _em()
    order = []
    entry = _armed_advance(em, on_fire=lambda advance_only: order.append("fire"),
                           on_slide=lambda: order.append("slide"))
    assert entry["advance_only"] is True
    em.update(0)
    assert order == ["fire", "slide"], \
        "with nothing to aim at and nothing to fly, both hooks land on the first update"
    assert em.projectiles == [], "no pellet leaves the barrel"
    assert em.particles == [], "and no muzzle flash either"
    assert em.holes == [] and em._shake is None, "nothing hits anything"
    assert {p["kind"] for p in em.particles}.isdisjoint({"impact", "blood", "ragdoll"}), \
        "no impact ring, no blood, no ragdoll — the victim is gone"
    assert em.captures == [], "and the entry retires with the slide"


def test_the_advancing_capture_waits_out_no_draw_aim_or_travel_beat():
    em = _em()
    order = []
    entry = _armed_advance(em, now_ms=1000, on_fire=lambda advance_only: order.append("fire"),
                           on_slide=lambda: order.append("slide"))
    assert entry["fire_at"] == entry["start"] == 1000, \
        "the gun is already up and pointed — no DRAW_MS, no AIM_MS to sit through"
    em.update(1000)
    assert order == ["fire", "slide"], \
        "and no PROJECTILE_TRAVEL_MS wait for a pellet that never flew"
    assert em.captures == []


def test_a_plain_capture_behind_no_check_still_shoots_everything():
    em = _em()
    order = []
    entry = _capture(em, on_fire=lambda advance_only: order.append("fire"),
                     on_slide=lambda: order.append("slide"))
    assert entry["advance_only"] is False
    em.update(0)
    em.update(DRAW_MS + AIM_MS)
    assert order == ["fire"]
    assert em.projectiles, "the pellets fly"
    assert [p["kind"] for p in em.particles] == ["flash"], "and the muzzle flashes"
    for t in range(DRAW_MS + AIM_MS, DRAW_MS + AIM_MS + PROJECTILE_TRAVEL_MS + 20, 20):
        em.update(t)
    assert order == ["fire", "slide"]
    assert {p["kind"] for p in em.particles} >= {"impact", "blood", "ragdoll"}, \
        "the victim takes the hit it is still standing for"
    assert em.holes, "and keeps the bullet hole"


def test_the_advancing_capture_holds_the_gun_still_and_hides_the_dead_victim():
    em = _em()
    plain, advancing = _window(), _window()
    _capture(em, predrawn=True)
    em.update(0)
    em.update(AIM_MS)
    em.draw_over(plain, AIM_MS)
    em.captures = []
    em.particles = []
    em.projectiles = []
    em.holes = []
    _armed_advance(em)
    em.draw_over(advancing, 0)
    victim = pg.Rect(4 * _CELL, 4 * _CELL, _CELL, _CELL)
    assert _pixels(advancing, victim) == _pixels(_window(), victim), \
        "the victim square stays empty — its body left with the skill-check"
    assert _pixels(advancing, victim) != _pixels(plain, victim), \
        "a normal capture does hold the victim sprite there"


def test_cut_and_clear_transients_never_leave_the_gun_behind():
    em = _em()
    _held(em)
    em.cut(500)
    assert em.has_gun_px() is False
    assert len(em.drops) == 1, "cut tumbles it away when it knows the clock"
    _held(em)
    em.clear_transients()
    assert em.has_gun_px() is False, "a new game can never inherit a held gun"


def test_advance_only_fire_passes_the_flag_to_the_callback_so_the_gunshot_is_muted():
    # The whack check already fired the real gunshots AND already credited the
    # kill at the pit it happened on, so the advancing capture is silent all the
    # way through — on_fire receives advance_only as its argument and
    # board._on_capture_fire returns on it before the gunshot cue, the kill
    # flair and the announcer line. The old instance flag (set around the call,
    # cleared after) is gone: there is no window for an exception or reentrant
    # fire to leak a stale True through.
    em = _em()
    fired = {}
    _armed_advance(em, on_fire=lambda advance_only: fired.setdefault("advance", advance_only))
    em.update(5000)
    assert fired["advance"] is True, \
        "the callback sees the advance flag and can skip the gunshot"
    assert not hasattr(em, "firing_advance_only"), \
        "the flag travels as an argument, never as shared instance state"


def test_a_plain_capture_fire_reports_not_advance_only():
    em = _em()
    fired = {}
    _capture(em, on_fire=lambda advance_only: fired.setdefault("advance", advance_only))
    em.update(5000)
    assert fired["advance"] is False


def test_a_weaponless_fire_still_reports_not_advance_only(monkeypatch):
    # The two no-art early returns never armed the old flag either — callers
    # read the initialized False, so the argument form must pass False too.
    em = _em()
    monkeypatch.setattr(em, "_weapon", lambda gun, cell: None)
    seen = []
    surf = pg.Surface((_CELL, _CELL), pg.SRCALPHA)
    em.capture(now_ms=0, attacker_type="queen", attacker_surface=surf, victim_surface=surf,
               from_sq=_FROM, victim_sq=Square(4, 4), to_sq=Square(4, 4), cell_size=_CELL,
               on_fire=lambda advance_only: seen.append(advance_only))
    em.miss(now_ms=0, attacker_type="queen", from_sq=_FROM, victim_sq=Square(4, 4),
            cell_size=_CELL, on_fire=lambda advance_only: seen.append(advance_only))
    assert em.captures == [], "no weapon art, no staged choreography — both fired inline"
    assert seen == [False, False]


def _fire_board(calls):
    match = Match()
    match.new_game()
    board = Board(pg.display.get_surface(), match,
                  shot_callback=lambda entry: calls.append("shot"),
                  announce_callback=lambda key, captured: calls.append(("announce", key)))
    board.load_assets()
    board.set_rect(pg.Rect(0, 0, 800, 800))
    return board


def test_an_advancing_capture_cues_no_gunshot_and_credits_no_second_kill():
    em = _em()
    calls = []
    board = _fire_board(calls)
    board.effects = em
    entry = SimpleNamespace(move=SimpleNamespace(captured=None))
    board._on_capture_fire(entry, "white", Square(4, 4), True)
    assert calls == [], "no gunshot cue and no announcer line behind a won whack"
    assert em.callouts == [] and em.particles == [], "and no second kill flair"
    assert em._streak_count == 0, "the streak was already credited at the killing pixel"
    board._on_capture_fire(entry, "white", Square(4, 4), False)
    assert calls == ["shot", ("announce", "first_blood")], \
        "a capture with no check behind it still cues and announces its kill"
    assert em._streak_count == 1


def _miss(em, from_sq=_FROM, victim_sq=Square(4, 4), now_ms=0, **kw):
    em.miss(now_ms=now_ms, attacker_type="queen", from_sq=from_sq, victim_sq=victim_sq,
            cell_size=_CELL, **kw)
    return em.captures[-1]


def test_the_failed_whacks_miss_shoots_the_gun_already_in_the_hand():
    # The fail beat keeps the same weapon on screen: the check's last aimed frame
    # flows straight into the whiff instead of tumbling and re-drawing a twin gun.
    em = _em()
    _held(em, attacker_type="queen")
    em.hand_off_gun_px()
    fired = []
    entry = _miss(em, on_fire=lambda advance_only: fired.append(1))
    assert entry["predrawn"] is True, "no second draw-flourish for a gun it never let go of"
    assert entry["fire_at"] == AIM_MS, "only the aim beat stands between the check and the whiff"
    assert em.drops == [], "and nothing tumbles in between"
    em.update(entry["fire_at"] - 1)
    assert fired == [] and em.projectiles == []
    em.update(entry["fire_at"])
    assert fired == [1], "a miss is NOT advance-only — it really pulls the trigger"
    assert em.projectiles, "the whole spread leaves the barrel"
    assert em.callouts, "and the SKILL ISSUE callout still lands with it"


def test_a_miss_with_no_handoff_keeps_the_full_draw_and_aim_beat():
    em = _em()
    fired = []
    entry = _miss(em, on_fire=lambda advance_only: fired.append(1))
    assert entry["predrawn"] is False, "nothing was handed over — it draws for itself"
    assert entry["fire_at"] == DRAW_MS + AIM_MS
    em.update(entry["fire_at"])
    assert fired == [1] and em.projectiles


def test_the_miss_consumes_the_handoff_so_nothing_inherits_it_afterwards():
    em = _em()
    _held(em)
    em.hand_off_gun_px()
    _miss(em)
    em.captures = []
    assert em._gun_handoff is None
    assert _capture(em)["predrawn"] is False, "the latch is spent — one shot, not two"


def test_register_kill_pins_the_hit_word_to_the_pixel_it_was_earned_at():
    em = _em()
    px = (137.0, 421.0)
    for i in range(7):
        em.register_kill("white", Square(0, 4), _CELL, i)
    em.update(10_000)
    assert em.register_kill("white", Square(0, 4), _CELL, 10_001, px=px) == "hit"
    tag = [p for p in em.particles if p["kind"] == "tag"][-1]
    assert tag["px"] == px
    assert em._anchor(tag) == px, "the word pops where the piece died, not on its home square"


def test_a_kill_with_no_pixel_still_anchors_to_the_captured_square():
    em = _em()
    for i in range(7):
        em.register_kill("white", Square(0, 4), _CELL, i)
    em.update(10_000)
    em.register_kill("white", Square(2, 3), _CELL, 10_001)
    tag = [p for p in em.particles if p["kind"] == "tag"][-1]
    assert "px" not in tag, "the square path stays byte-identical — no anchor key at all"
    assert em._anchor(tag) == em.geom(Square(2, 3))


def test_impact_px_shreds_the_air_at_a_pixel_and_leaves_no_body_behind():
    em = _em()
    px = (321.0, 123.0)
    em.impact_px(0, px, _CELL)
    kinds = [p["kind"] for p in em.particles]
    assert set(kinds) == {"impact", "blood", "spark", "smoke"}, \
        "the whole square-anchored package spawns, minus the ragdoll"
    assert "ragdoll" not in kinds, "the victim already flew off the pit on the check's own arc"
    assert len(em.holes) == 1, "and it keeps the bullet hole"
    assert all(em._anchor(p) == px for p in em.particles)
    assert em._anchor(em.holes[0]) == px
    assert all("victim_sq" not in p for p in em.particles + em.holes), \
        "nothing about a pixel impact refers to a square"


def test_impact_px_paints_at_the_pixel_and_nowhere_near_a_square_centre():
    em = _em()
    px = (305.0, 105.0)
    empty = _window()
    hit = _window()
    em.impact_px(0, px, _CELL)
    em.draw_holes(hit, 40)
    em.draw_over(hit, 40)
    at_px = pg.Rect(280, 80, 50, 50)
    at_centre = pg.Rect(338, 138, 24, 24)
    assert em.geom(Square(1, 3)) == (350, 150), "the pixel sits well off its own square centre"
    assert _pixels(hit, at_px) != _pixels(empty, at_px), \
        "the ring, blood and hole all land on the pixel"
    assert _pixels(hit, at_centre) == _pixels(empty, at_centre), \
        "and nothing at all lands on the square centre that used to anchor them"


def _ink(surf):
    lit = [surf.get_at((x, y)) for x in range(surf.get_width())
           for y in range(surf.get_height()) if surf.get_at((x, y)).a > 200]
    return [sum(c[i] for c in lit) / len(lit) for i in range(3)]


def test_the_taunt_tag_wears_the_loss_colour_instead_of_the_kill_amber():
    em = _em()
    em.taunt_tag(0, "LOSER", Square(4, 4), _CELL)
    taunt = [p for p in em.particles if p["kind"] == "tag"][0]
    assert taunt["victim_sq"] == Square(4, 4) and taunt["dur"] == TAG_MS
    assert "px" not in taunt, "a taunt belongs to the square that just survived"
    em.particles = []
    em._tag(0, "LOSER", Square(4, 4), _CELL)
    amber = [p for p in em.particles if p["kind"] == "tag"][0]
    assert _ink(taunt["surf"])[1] < _ink(amber["surf"])[1] - 20, \
        "the taunt reads red like SKILL ISSUE, not gold like a hit word"
    assert pg.Color(Colors.loss).g < pg.Color(Colors.amber_hi).g


def test_a_fail_with_nothing_to_capture_still_spends_the_gun_handoff():
    # trigger_skillcheck_fail bumps instead of shooting when the "capture" turns
    # out to have no victim (a locked quiet move). That branch reached no
    # effects.miss() to spend the latch, so the NEXT real capture from that
    # square inherited a predrawn gun and silently advanced without firing.
    board = _fire_board([])
    fx = board.effects
    frm, to = Square(6, 4), Square(4, 4)
    assert board.match.piece_at(to) is None, "the destination really is empty"
    fx.hold_gun_px(now_ms=0, attacker_type="pawn", from_sq=frm, cell_size=board.cell_size)
    fx.hand_off_gun_px()
    assert fx._gun_handoff == frm

    board.trigger_skillcheck_fail(frm, to)
    assert fx.captures == [], "with no victim there is no volley to stage"
    assert fx._gun_handoff is None, "and the latch is spent on the way out anyway"
    assert fx.take_gun_handoff(frm) is False


def test_the_fail_volley_still_inherits_the_gun_the_board_took_off_the_latch():
    # The board now spends the latch up front, so it has to hand what it took
    # straight to the miss — otherwise the whiff would draw a second gun the
    # piece never let go of.
    board = _fire_board([])
    fx = board.effects
    frm, victim = Square(6, 4), Square(1, 4)
    assert board.match.piece_at(victim) is not None
    fx.hold_gun_px(now_ms=0, attacker_type="pawn", from_sq=frm, cell_size=board.cell_size)
    fx.hand_off_gun_px()

    board.trigger_skillcheck_fail(frm, victim)
    entry = fx.captures[-1]
    assert entry["predrawn"] is True, "no second draw-flourish for a gun already in the hand"
    assert entry["fire_at"] == entry["start"] + AIM_MS, "only the aim beat, no DRAW_MS"
    assert fx._gun_handoff is None
    assert fx.drops == [], "and nothing tumbles in between"


def test_a_fail_with_no_handoff_behind_it_draws_for_itself():
    board = _fire_board([])
    fx = board.effects
    frm, victim = Square(6, 4), Square(1, 4)
    board.trigger_skillcheck_fail(frm, victim)
    entry = fx.captures[-1]
    assert entry["predrawn"] is False
    assert entry["fire_at"] == entry["start"] + DRAW_MS + AIM_MS, \
        "a fail with no check gun behind it still draws, aims, then whiffs"
