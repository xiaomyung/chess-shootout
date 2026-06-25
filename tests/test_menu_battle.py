"""MenuBattle backdrop: deterministic simulation + render assertions.

The battle is driven by an injected `random.Random(seed)` and explicit
millisecond timestamps, so every test below is reproducible across xdist
workers. Rendering tests assert real pixels (entities over the gradient
backdrop, the scrim darkening the edges) rather than bare draw() calls.
"""

import math
import os
import random
from unittest.mock import MagicMock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.menu.menu_battle import (
    MenuBattle, MAX_PAWNS, RAGDOLL_MS, IDLE_TIMEOUT_MS, IDLE_RADIUS,
    WEAPON_SWITCH_MIN, WEAPON_SWITCH_MAX, GUN_DRAW_SEC, PROJECTILE_MAX_MS,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 700))
    yield
    pg.quit()


TITLEBAR = 40
INITIAL_PAWNS = 5


def _intro_battle(seed=7, w=1000, h=700, card=pg.Rect(300, 130, 400, 440),
                  logo=pg.Rect(470, 60, 52, 52), top_inset=TITLEBAR):
    """A freshly-launched battle, still playing the entrance intro."""
    b = MenuBattle(pg.display.get_surface(), rng=random.Random(seed))
    b.top_inset = top_inset
    b.set_rect(pg.Rect(0, 0, w, h))
    b.set_avoid_rect(card)
    b.set_logo_rect(logo)
    return b


def _battle(seed=7, w=1000, h=700, card=pg.Rect(300, 130, 400, 440), top_inset=TITLEBAR):
    """A running battle with the intro already finished and pawns on the field."""
    b = _intro_battle(seed=seed, w=w, h=h, card=card, top_inset=top_inset)
    b._intro_active = False
    b._intro_t = 1.0
    for _ in range(INITIAL_PAWNS):
        b._spawn_pawn(True)
    return b


def _run(b, steps, start=1000, step_ms=16):
    t = start
    for _ in range(steps):
        b.update(t)
        t += step_ms
    return t


def test_running_battle_has_queen_and_pawns():
    b = _battle()
    assert b.queen is not None
    assert len(b.pawns) == INITIAL_PAWNS
    assert all(p["alive"] for p in b.pawns)


def test_launch_starts_in_intro_with_no_pawns():
    b = _intro_battle()
    assert b._intro_active is True
    assert b.pawns == []


def test_intro_holds_in_the_logo_during_the_start_grace():
    b = _intro_battle()
    b.update(1000)
    b.update(1200)
    assert b._intro_t == 0.0, "the queen should sit in the logo during the start grace"
    b.update(1800)
    assert b._intro_t > 0.0, "the fly-in begins after the grace"


def test_intro_finishes_lands_queen_and_says_a_oneliner():
    from chessshootout.frontend.menu.menu_battle import INTRO_LINES
    b = _intro_battle()
    t = 1000
    while b._intro_active and t < 1000 + 200 * 16:
        b.update(t)
        t += 16
    assert b._intro_active is False, "the intro should finish"
    assert b.queen["bubble"] is not None
    assert b.queen["bubble"]["text"] in INTRO_LINES, "the queen should drop a one-liner on landing"


@pytest.mark.parametrize("seed", range(10), ids=lambda s: f"seed_{s}")
def test_queen_lands_fully_inside_the_window_box(seed):
    b = _intro_battle(seed=seed)
    t = 1000
    while b._intro_active and t < 1000 + 300 * 16:
        b.update(t)
        t += 16
    assert not b._intro_active, "the intro should finish"
    assert b._fully_in_window(b.queen), \
        "the queen must land with her whole body inside the window"


def test_pawns_only_start_after_the_intro():
    b = _intro_battle()
    t = 1000
    for _ in range(40):
        b.update(t)
        t += 16
        if b._intro_active:
            assert b.pawns == [], "no pawns should appear while the queen is still flying in"
    for _ in range(260):
        b.update(t)
        t += 16
    assert b.pawns, "pawns should start coming once the queen has landed"


def test_intro_queen_is_drawn_on_the_overlay():
    b = _intro_battle(logo=pg.Rect(450, 300, 60, 60))
    b.update(1000)
    b.update(1016)
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    b.draw_intro_overlay(win)
    lit = any(win.get_at((x, y))[:3] != (0, 0, 0)
              for x in range(440, 525) for y in range(285, 365))
    assert lit, "the flying queen should be drawn on the intro overlay near the logo"


def test_landing_arms_the_gun_draw_flourish():
    b = _intro_battle()
    b._finish_intro(5000)
    assert b.queen["draw_anim"] == GUN_DRAW_SEC


def test_gun_draw_flourish_decays_to_zero():
    b = _battle()
    b.pawns = []
    b.queen["draw_anim"] = GUN_DRAW_SEC
    _run(b, 60)
    assert b.queen["draw_anim"] == 0.0


def test_queen_does_not_fire_while_drawing_the_gun():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = 500, 360, 99
    _aim_at(b, b.queen, p)
    b.queen["draw_anim"] = 0.5
    b.acc["qfire"] = -1
    b.projectiles.clear()
    b._step(0.0, 5000)
    assert b.projectiles == [], "the queen must finish drawing her gun before firing"


def test_gun_draw_flourish_grows_the_gun_from_nothing():
    b = _battle()
    win = pg.display.get_surface()
    entry = b._weapons["queen"]["revolver"]
    region = [(x, y) for x in range(465, 545) for y in range(325, 375)]
    win.fill((0, 0, 0))
    b._draw_gun_flourish(win, entry, (500, 350), 0.0, GUN_DRAW_SEC, GUN_DRAW_SEC, 5, True)
    early = any(win.get_at(pt)[:3] != (0, 0, 0) for pt in region)
    win.fill((0, 0, 0))
    b._draw_gun_flourish(win, entry, (500, 350), 0.0, GUN_DRAW_SEC * 0.2, GUN_DRAW_SEC, 5, True)
    late = any(win.get_at(pt)[:3] != (0, 0, 0) for pt in region)
    assert not early, "at the start of the draw the gun is 0-size (invisible)"
    assert late, "as the draw completes the gun grows in"


class _ConstRng:
    def __init__(self, v):
        self.v = v

    def random(self):
        return self.v


def test_kill_can_trigger_a_celebratory_spin():
    b = _battle()
    b.queen["draw_anim"] = 0.0
    b.rng = _ConstRng(0.0)
    b._land_hit(True, b.pawns[0], 5000)
    assert b.queen["draw_anim"] > 0
    assert b.queen["draw_grow"] is False, "a kill spin twirls the gun without growing it"
    assert b.queen["draw_spins"] == 1


def test_most_kills_do_not_spin():
    b = _battle()
    b.queen["draw_anim"] = 0.0
    b.rng = _ConstRng(0.9)
    b._land_hit(True, b.pawns[0], 5000)
    assert b.queen["draw_anim"] == 0.0


def test_dropping_a_gun_adds_a_drop_that_fades_after_three_seconds():
    b = _battle()
    b.drops = []
    b._drop_gun("revolver", b.queen, 5000)
    assert len(b.drops) == 1 and b.drops[0]["dur"] == 3000
    b._prune(5000 + 2999)
    assert b.drops, "the dropped gun stays on the ground before 3s"
    b._prune(5000 + 3001)
    assert b.drops == [], "the dropped gun disappears after 3s"


def test_dropped_gun_falls_to_the_ground_in_front_of_her():
    b = _battle()
    q = b.queen
    q["x"], q["y"], q["face"] = 500, 400, 1
    b.drops = []
    b._drop_gun("revolver", q, 0)
    d = b.drops[0]
    start_x, start_y = d["x"], d["y"]
    for _ in range(60):
        b._update_drops(0.016)
    assert d["y"] > start_y, "the gun should fall under gravity"
    assert d["resting"] is True and d["y"] == d["ground_y"], "it should settle on the ground"
    assert d["x"] > start_x, "facing right, it should land in front of her"


def test_weapon_swap_drops_the_old_gun():
    b = _battle()
    q = b.queen
    q["weapon"], q["weapon_switch"] = "revolver", 0.0
    b.drops = []
    b.rng = _ConstRng(0.0)
    b._step(0.0, 5000)
    assert q["weapon"] != "revolver", "the timer should switch the weapon"
    assert b.drops, "swapping should drop the previous gun on the ground"


def test_initial_pawns_spawn_outside_the_card():
    b = _battle()
    for p in b.pawns:
        assert not b._in_obstacle(p["x"], p["y"]), "a pawn spawned under the card"


def test_set_avoid_rect_pushes_existing_entities_out():
    b = _battle(card=pg.Rect(60, 60, 200, 200))
    _run(b, 40)
    new_card = pg.Rect(400, 300, 300, 200)
    b.queen["x"], b.queen["y"] = new_card.center
    b.pawns[0]["x"], b.pawns[0]["y"] = new_card.center
    b.set_avoid_rect(new_card)
    assert not b._in_obstacle(b.queen["x"], b.queen["y"])
    assert not b._in_obstacle(b.pawns[0]["x"], b.pawns[0]["y"])


def test_set_rect_rescales_without_respawning():
    b = _battle()
    _run(b, 30)
    count_before = len(b.pawns)
    queen_h_before = b.queen["sprite_h"]
    b.set_rect(pg.Rect(0, 0, 1400, 1000))
    assert len(b.pawns) == count_before
    assert b._initialized is True
    assert b.queen["sprite_h"] != queen_h_before


def test_in_obstacle_inside_vs_outside():
    b = _battle()
    cx, cy = b.avoid_rect.center
    assert b._in_obstacle(cx, cy) is True
    assert b._in_obstacle(10, 10) is False


def test_avoid_pushes_inside_point_to_nearest_edge():
    b = _battle()
    o = b.obstacle
    near_left_x = o[0] + 5
    mid_y = (o[1] + o[3]) / 2
    out_x, out_y = b._avoid(near_left_x, mid_y)
    assert out_x == o[0]
    assert out_y == mid_y


def test_avoid_leaves_outside_point_untouched():
    b = _battle()
    assert b._avoid(5, 5) == (5, 5)


def test_seg_hits_rect_detects_crossing():
    b = _battle()
    cx, cy = b.avoid_rect.center
    assert b._seg_hits_rect(0, cy, b.rect.width, cy) is True
    assert b._seg_hits_rect(0, 5, b.rect.width, 5) is False


def test_route_target_rounds_a_corner_when_blocked():
    b = _battle()
    o = b.obstacle
    cy = (o[1] + o[3]) / 2
    target = b._route_target(0, cy, b.rect.width, cy)
    assert tuple(target) != (b.rect.width, cy)
    corners = {(o[0] - 22, o[1] - 22), (o[2] + 22, o[1] - 22),
               (o[2] + 22, o[3] + 22), (o[0] - 22, o[3] + 22)}
    assert tuple(target) in corners


def test_waypoints_stay_in_the_queens_reachable_band():
    b = _battle()
    qo = b._entity_obstacle(b.queen)
    ymin = b.top_inset + b.queen["sprite_h"]
    for _ in range(300):
        wp = b._rand_waypoint(qo)
        assert wp[1] >= ymin - 0.01, "waypoints must not target above the queen's reachable area"
        assert wp[1] <= b.rect.height + 0.01


def test_route_target_goes_straight_when_clear():
    b = _battle()
    assert b._route_target(0, 5, 200, 5) == (200, 5)


def test_no_obstacle_when_avoid_rect_empty():
    b = MenuBattle(pg.display.get_surface(), rng=random.Random(1))
    b.set_rect(pg.Rect(0, 0, 800, 600))
    b.set_avoid_rect(pg.Rect(0, 0, 0, 0))
    assert b.obstacle is None
    assert b._avoid(400, 300) == (400, 300)


def test_entity_obstacle_expands_by_full_model_extent():
    b = _battle(card=pg.Rect(400, 250, 300, 200))
    o = b.obstacle
    q = b.queen
    qo = b._entity_obstacle(q)
    hw = b._art["queen"]["w"] / 2
    assert qo[0] == o[0] - hw
    assert qo[2] == o[2] + hw
    assert qo[1] == o[1]
    assert qo[3] == o[3] + q["sprite_h"]


def test_full_model_rect_does_not_overlap_the_card():
    b = _battle(card=pg.Rect(400, 250, 300, 200))
    o = b.obstacle
    q = b.queen
    art_w = b._art["queen"]["w"]
    q["x"], q["y"] = o[0] + 5, (o[1] + o[3]) / 2
    q["x"], q["y"] = b._push_out(b._entity_obstacle(q), q["x"], q["y"])
    left, right = q["x"] - art_w / 2, q["x"] + art_w / 2
    top, bottom = q["y"] - q["sprite_h"], q["y"]
    overlaps = left < o[2] and right > o[0] and top < o[3] and bottom > o[1]
    assert not overlaps, "the queen's whole model rect must clear the card"


def test_idle_queen_rerolls_waypoint_after_two_seconds():
    b = _battle()
    q = b.queen
    q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], 1000
    q["wp"] = [q["x"], q["y"]]
    b._unstick_queen(1000 + IDLE_TIMEOUT_MS + 1, b._entity_obstacle(q))
    assert q["anchor_ms"] == 1000 + IDLE_TIMEOUT_MS + 1
    assert q["wp"] != [q["x"], q["y"]], "an idle queen should pick a fresh waypoint"


def test_idle_queen_holds_waypoint_before_timeout():
    b = _battle()
    q = b.queen
    q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], 1000
    q["wp"] = [10.0, 10.0]
    b._unstick_queen(1000 + IDLE_TIMEOUT_MS - 200, b._entity_obstacle(q))
    assert q["wp"] == [10.0, 10.0]


def test_moving_queen_resets_idle_anchor():
    b = _battle()
    q = b.queen
    q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], 1000
    q["x"] += IDLE_RADIUS + 50
    b._unstick_queen(5000, b._entity_obstacle(q))
    assert q["anchor_x"] == q["x"]
    assert q["anchor_ms"] == 5000


def test_queen_full_model_stays_within_window_during_play():
    b = _battle()
    for _ in range(300):
        b.update(b._last_ms + 16 if b._last_ms else 1000)
        q = b.queen
        w = b._art["queen"]["w"]
        assert q["x"] - w / 2 >= -0.01
        assert q["x"] + w / 2 <= b.rect.width + 0.01
        assert q["y"] - q["sprite_h"] >= b.top_inset - 0.01
        assert q["y"] <= b.rect.height + 0.01


def test_queen_clamped_against_top_left_borders():
    b = _battle()
    q = b.queen
    q["x"], q["y"] = -100, -100
    b._clamp_queen_to_window()
    assert q["x"] == b._art["queen"]["w"] / 2
    assert q["y"] == b.top_inset + q["sprite_h"]


def test_queen_clamped_against_bottom_right_borders():
    b = _battle()
    q = b.queen
    q["x"], q["y"] = b.rect.width + 300, b.rect.height + 300
    b._clamp_queen_to_window()
    assert q["x"] == b.rect.width - b._art["queen"]["w"] / 2
    assert q["y"] == float(b.rect.height)


def test_window_clamp_does_not_touch_pawns():
    b = _battle()
    b.pawns[0]["x"] = -200
    b._clamp_queen_to_window()
    assert b.pawns[0]["x"] == -200, "pawns enter from off-screen and must not be clamped"


def test_fully_in_window_true_and_false():
    b = _battle()
    p = b.pawns[0]
    w, h = b._art["pawn"]["w"], p["sprite_h"]
    p["x"], p["y"] = w / 2 + 1, b.top_inset + h + 1
    assert b._fully_in_window(p) is True
    p["x"] = w / 2 - 1
    assert b._fully_in_window(p) is False


def test_queen_does_not_fire_at_partially_offscreen_pawn():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = -5, 300, 99
    b.acc["qfire"] = -1
    b.particles.clear()
    b._step(0.016, 5000)
    assert b.particles == [], "queen must ignore a pawn whose hitbox isn't fully on-screen"


def _aim_at(b, shooter, target):
    gx, gy = b._gun_pivot(shooter)
    bx, by = b._body_point(target)
    shooter["aim"] = math.atan2(by - gy, bx - gx)


def test_queen_fires_at_fully_onscreen_pawn():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = 500, 360, 99
    _aim_at(b, b.queen, p)
    b.acc["qfire"] = -1
    b.projectiles.clear()
    b._step(0.0, 5000)
    assert b.projectiles, "firing should launch a projectile"


def test_queen_holds_fire_until_aimed_at_the_pawn():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = 500, 360, 99
    _aim_at(b, b.queen, p)
    b.queen["aim"] += 1.5
    b.acc["qfire"] = -1
    b.particles.clear()
    b.projectiles.clear()
    b._step(0.0, 5000)
    assert b.projectiles == [], "the queen must point at the target before shooting"
    assert b.particles == []


def test_pawn_does_not_fire_when_partially_offscreen():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = -5, 300, -1
    _aim_at(b, p, b.queen)
    b.acc["qfire"] = 99
    b.particles.clear()
    b.projectiles.clear()
    b._step(0.0, 5000)
    assert b.projectiles == [], "a pawn must not fire until its hitbox is fully on-screen"


def test_pawn_fires_when_fully_onscreen():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = 40, 360, -1
    _aim_at(b, p, b.queen)
    b.acc["qfire"] = 99
    b.projectiles.clear()
    b._step(0.0, 5000)
    assert b.projectiles, "firing should launch a projectile"


def test_projectile_flies_along_the_barrel():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"], p["fire"] = 500, 360, 99
    _aim_at(b, b.queen, p)
    b.acc["qfire"] = -1
    b.projectiles.clear()
    b._step(0.0, 5000)
    assert b.projectiles, "firing should launch a projectile"
    pr = b.projectiles[0]
    travel = math.atan2(pr["vy"], pr["vx"])
    delta = abs((travel - b.queen["aim"] + math.pi) % (2 * math.pi) - math.pi)
    assert delta < 0.3, "the projectile should travel along the barrel, not curve away"


def test_kill_emits_hitmark_and_red_particles_not_a_blood_circle():
    b = _battle()
    p = b.pawns[0]
    b.particles.clear()
    b._kill_pawn(p, 5000)
    kinds = [pt["kind"] for pt in b.particles]
    assert "hitmark" in kinds, "a hit should land a hitmarker on the target"
    sparks = [pt for pt in b.particles if pt["kind"] == "spark"]
    assert sparks and all(pt["color"] == Colors.blood for pt in sparks), \
        "damage should fly red particles"
    assert "blood" not in kinds, "the red blood circle must be gone"
    assert p["dying"] is True


def test_landing_a_hit_on_the_queen_shakes_and_marks_her():
    b = _battle()
    b.queen["flinch"] = 0.0
    b.particles.clear()
    b._land_hit(False, b.queen, 5000)
    assert b.queen["flinch"] == 1.0, "the queen should shake when hit"
    assert any(pt["kind"] == "hitmark" for pt in b.particles)
    assert any(pt["kind"] == "spark" and pt["color"] == Colors.blood for pt in b.particles)


def test_shotgun_launches_a_pellet_spread_revolver_one():
    b = _battle()
    p = b.pawns[0]
    p["x"], p["y"] = 500, 360
    b.queen["weapon"] = "shotgun"
    _aim_at(b, b.queen, p)
    b.projectiles.clear()
    b._fire(b.queen, p, True, 5000)
    assert len(b.projectiles) == 6
    b.queen["weapon"] = "revolver"
    b.projectiles.clear()
    b._fire(b.queen, p, True, 5000)
    assert len(b.projectiles) == 1


def test_fire_plays_the_shooters_gun_sound():
    b = _battle()
    b.sound_manager = MagicMock()
    b.queen["weapon"] = "blunderbuss"
    b._fire(b.queen, b.pawns[0], True, 5000)
    b.sound_manager.play_menu_gun.assert_called_once_with("blunderbuss")
    b.sound_manager.play_menu_gun.reset_mock()
    p = b.pawns[0]
    p["weapon"] = "revolver"
    b._fire(p, b.queen, False, 5000)
    b.sound_manager.play_menu_gun.assert_called_once_with("revolver")


def test_fire_without_sound_manager_does_not_crash():
    b = _battle()
    assert b.sound_manager is None
    b._fire(b.queen, b.pawns[0], True, 5000)


def test_hit_projectile_collides_with_the_hitbox_and_lands():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"] = 500, 360
    b.queen["weapon"] = "revolver"
    _aim_at(b, b.queen, p)
    b.projectiles.clear()
    b.particles.clear()
    b._spawn_projectiles(b.queen, p, True, *b._muzzle_point(b.queen), True, 5000)
    landed = False
    for i in range(60):
        b._update_projectiles(0.016, 5000 + (i + 1) * 16)
        if p["dying"]:
            landed = True
            break
    assert landed, "a hit projectile should collide with the hitbox and kill the pawn"
    assert any(pt["kind"] == "hitmark" for pt in b.particles)


def test_miss_projectile_flies_past_and_never_lands():
    b = _battle()
    b.pawns = [b.pawns[0]]
    p = b.pawns[0]
    p["x"], p["y"] = 500, 360
    b.queen["weapon"] = "revolver"
    _aim_at(b, b.queen, p)
    b.projectiles.clear()
    b._spawn_projectiles(b.queen, p, True, *b._muzzle_point(b.queen), False, 5000)
    for i in range(150):
        b._update_projectiles(0.016, 5000 + (i + 1) * 16)
    assert not p["dying"], "a miss must not kill the pawn"
    assert b.projectiles == [], "a missed projectile should fly off and despawn"


def _pellet_at(x, y, is_queen=True, born=5000):
    return {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "style": "pellet",
            "size": 4.0, "len": 7.0, "color": Colors.amber_hi,
            "is_queen": is_queen, "born": born, "max_ms": PROJECTILE_MAX_MS}


def test_every_queen_pellet_kills_any_pawn_it_lands_on():
    """A pellet kills whatever pawn it intersects, not a pre-chosen target."""
    b = _battle()
    b.pawns = [b.pawns[0]]
    victim = b.pawns[0]
    victim["x"], victim["y"] = 400, 360
    b.particles.clear()
    b.projectiles = [_pellet_at(*b._body_point(victim))]
    b._update_projectiles(0.016, 5016)
    assert victim["dying"] is True, "a pellet landing on a pawn kills it"
    assert b.projectiles == [], "the pellet is consumed on impact"
    assert any(pt["kind"] == "hitmark" for pt in b.particles)


def test_a_single_shot_can_drop_multiple_pawns():
    """Each pellet of a spread resolves independently, so one blast can fell several pawns."""
    b = _battle()
    b.pawns = b.pawns[:2]
    near, far = b.pawns
    near["x"], near["y"] = 300, 300
    far["x"], far["y"] = 650, 420
    b.projectiles = [_pellet_at(*b._body_point(near)), _pellet_at(*b._body_point(far))]
    b._update_projectiles(0.016, 5016)
    assert near["dying"] and far["dying"], "each pellet kills the pawn it lands on"
    assert b.projectiles == [], "both pellets are consumed"


def test_lead_pellet_flies_straight_the_rest_scatter():
    """One pellet always runs straight down the aim line; the remaining pellets fan out."""
    b = _battle()
    p = b.pawns[0]
    p["x"], p["y"] = 500, 360
    b.queen["weapon"] = "blunderbuss"
    _aim_at(b, b.queen, p)
    mx, my = b._muzzle_point(b.queen)
    b.projectiles.clear()
    b._spawn_projectiles(b.queen, p, True, mx, my, True, 5000)
    bx, by = b._body_point(p)
    base = math.atan2(by - my, bx - mx)

    def off(pr):
        return abs((math.atan2(pr["vy"], pr["vx"]) - base + math.pi) % (2 * math.pi) - math.pi)

    assert off(b.projectiles[0]) < 1e-6, "the lead pellet is dead straight on the aim line"
    assert any(off(pr) > 1e-3 for pr in b.projectiles[1:]), "the rest scatter around it"


def test_pawn_pellet_strikes_the_queen_not_other_pawns():
    """Pawn fire resolves against the queen only; pawns don't friendly-fire each other."""
    b = _battle()
    bystander = b.pawns[1]
    bystander["x"], bystander["y"] = 400, 360
    b.projectiles = [_pellet_at(*b._body_point(bystander), is_queen=False)]
    b._update_projectiles(0.016, 5016)
    assert bystander["alive"] is True, "a pawn's bullet passes through other pawns"


def _drew_anything(surf, rect=None):
    rect = (rect or surf.get_rect()).clip(surf.get_rect())
    for x in range(rect.left, rect.right, 4):
        for y in range(rect.top, rect.bottom, 4):
            if tuple(surf.get_at((x, y))[:3]) != (0, 0, 0):
                return True
    return False


def test_new_queen_starts_with_a_zeroed_ko_counter():
    b = _battle()
    assert b.queen["kills"] == 0 and b.queen["ko_wink_until"] == 0


def test_a_kill_bumps_the_ko_counter_into_its_amber_wink():
    b = _battle()
    b.pawns = [b.pawns[0]]
    b._kill_pawn(b.pawns[0], 5000)
    assert b.queen["kills"] == 1
    assert b.queen["ko_wink_until"] > 5000, "a kill bumps the counter into the amber wink"


def test_begin_intro_resets_the_ko_counter():
    b = _battle()
    b.queen["kills"], b.queen["ko_wink_until"] = 7, 10 ** 9
    b.begin_intro()
    assert b.queen["kills"] == 0 and b.queen["ko_wink_until"] == 0


def test_ko_counter_draws_above_the_queen_after_the_intro():
    b = _battle()
    b.pawns = []
    b.queen["x"], b.queen["y"], b.queen["kills"] = 500, 400, 3
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    b._draw_ko_counter(surf)
    assert _drew_anything(surf), "the counter shows once the queen has landed"


def test_ko_counter_hidden_during_the_intro():
    b = _intro_battle()
    b.queen["x"], b.queen["y"], b.queen["kills"] = 500, 400, 3
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    b._draw_ko_counter(surf)
    assert not _drew_anything(surf), "the counter is hidden until the queen lands"


def test_ko_counter_is_centered_above_the_head():
    """At (150, 400) — open space, clear of the card — the badge centers above the head."""
    b = _battle()
    b.pawns = []
    b.queen["x"], b.queen["y"], b.queen["kills"] = 150, 400, 3
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    b._draw_ko_counter(surf)
    cx = int(b.queen["x"])
    left = _drew_anything(surf, pg.Rect(0, 0, cx, surf.get_height()))
    right = _drew_anything(surf, pg.Rect(cx, 0, surf.get_width() - cx, surf.get_height()))
    head_top = int(b.queen["y"] - b.queen["sprite_h"])
    assert left and right, "the badge straddles the queen's centre (centered above the head)"
    assert not _drew_anything(surf, pg.Rect(0, head_top, surf.get_width(),
                                            surf.get_height() - head_top)), \
        "and it sits above the head, not over her body"


def test_fits_above_rejects_top_edge_and_the_card_hitbox():
    b = _battle()
    assert b._fits_above(pg.Rect(40, b.rect.y + b.top_inset + 20, 60, 20)) is True
    assert b._fits_above(pg.Rect(40, b.rect.y + b.top_inset - 5, 60, 20)) is False
    assert b._fits_above(pg.Rect(b.avoid_rect.x + 10, b.avoid_rect.y + 10, 40, 20)) is False


def test_prefer_right_picks_the_side_with_more_room():
    b = _battle()
    assert b._prefer_right(60, 400) is True, "near the left wall the badge wants the right"
    assert b._prefer_right(b.rect.right - 60, 400) is False, "near the right wall it wants the left"


def test_ko_counter_dodges_to_the_side_and_stays_near_the_head():
    """Wall on the left, no room above: the badge dodges right and stays near the head."""
    b = _battle()
    b.pawns = []
    sprite_h = b.queen["sprite_h"]
    b.queen["y"], b.queen["kills"] = b.top_inset + sprite_h, 3
    b.queen["x"] = 70
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    b._draw_ko_counter(surf)
    qx = int(b.queen["x"])
    mid_body = int(b.queen["y"] - sprite_h * 0.5)
    assert _drew_anything(surf, pg.Rect(qx, 0, surf.get_width() - qx, surf.get_height())), \
        "with the wall on the left, the badge dodges to her right"
    assert not _drew_anything(surf, pg.Rect(0, 0, qx, surf.get_height())), "and not to her left"
    assert not _drew_anything(surf, pg.Rect(0, mid_body, surf.get_width(),
                                            surf.get_height() - mid_body)), \
        "and it stays near the head, never dropping to mid-body"


def test_ko_counter_dodges_the_menu_card_hitbox():
    """Head tucked under the menu card (no room above): the badge dodges the card hitbox."""
    b = _battle()
    b.pawns = []
    card = b.avoid_rect
    b.queen["x"], b.queen["kills"] = card.centerx, 3
    b.queen["y"] = card.bottom + b.queen["sprite_h"]
    surf = pg.display.get_surface()
    surf.fill((0, 0, 0))
    b._draw_ko_counter(surf)
    assert _drew_anything(surf), "the badge still renders"
    assert not _drew_anything(surf, card), "it avoids the menu card hitbox, not just the top edge"


def test_ko_counter_draws_behind_the_voicelines(monkeypatch):
    b = _battle()
    order = []
    monkeypatch.setattr(b, "_draw_ko_counter", lambda *a: order.append("ko"))
    monkeypatch.setattr(b, "_draw_bubble", lambda *a: order.append("bubble"))
    b.draw(b.window)
    assert "ko" in order and "bubble" in order
    assert order.index("ko") < order.index("bubble"), \
        "the counter draws before (behind) the speech bubbles"


def test_firing_kicks_recoil_scaled_by_gun_strength():
    b = _battle()
    q = b.queen
    q["weapon"], q["aim"] = "blunderbuss", 0.0
    b._fire(q, b.pawns[0], True, 5000)
    strong = q["recoil"]
    q["recoil"], q["weapon"] = 0.0, "revolver"
    b._fire(q, b.pawns[0], True, 5000)
    weak = q["recoil"]
    assert strong > weak > 0, "a stronger gun should kick back harder"


def test_recoil_decays_back_to_rest():
    """Block the queen from re-firing during the settle window so only the decay is measured."""
    b = _battle()
    q = b.queen
    q["weapon"], q["aim"] = "shotgun", 0.0
    b._fire(q, b.pawns[0], True, 5000)
    kicked = q["recoil"]
    b.acc["qfire"] = 999
    for i in range(40):
        b.update(5000 + (i + 1) * 16)
    assert q["recoil"] < kicked * 0.1, "recoil should settle back toward rest"


def test_recoil_nudges_the_muzzle_backward():
    b = _battle()
    q = b.queen
    q["x"], q["y"], q["aim"], q["weapon"] = 500, 300, 0.0, "shotgun"
    q["recoil"] = 0.0
    rest_x, _ = b._muzzle_point(q)
    q["recoil"] = 12.0
    kicked_x, _ = b._muzzle_point(q)
    assert kicked_x < rest_x, "aiming right, recoil should pull the muzzle back to the left"


def _pawns_overlap(b, a, c):
    w = b._art["pawn"]["w"]
    dx = abs(c["x"] - a["x"])
    dy = abs((c["y"] - c["sprite_h"] / 2) - (a["y"] - a["sprite_h"] / 2))
    return (w - dx) > 0.01 and ((a["sprite_h"] + c["sprite_h"]) / 2 - dy) > 0.01


def test_overlapping_pawns_are_separated():
    b = _battle()
    b.pawns = b.pawns[:2]
    a, c = b.pawns
    a["x"], a["y"] = 150.0, 300.0
    c["x"], c["y"] = 158.0, 305.0
    assert _pawns_overlap(b, a, c)
    b._separate_pawns()
    assert not _pawns_overlap(b, a, c)


def test_separation_resolves_a_pile_over_passes():
    b = _battle()
    b.pawns = b.pawns[:3]
    for i, p in enumerate(b.pawns):
        p["x"], p["y"] = 150.0 + i, 300.0 + i
    for _ in range(12):
        b._separate_pawns()
    for i, j in ((0, 1), (0, 2), (1, 2)):
        assert not _pawns_overlap(b, b.pawns[i], b.pawns[j])


def test_dying_pawns_are_excluded_from_separation():
    b = _battle()
    b.pawns = b.pawns[:2]
    a, c = b.pawns
    a["x"], a["y"] = 150.0, 300.0
    c["x"], c["y"], c["dying"], c["alive"] = 150.0, 300.0, True, False
    b._separate_pawns()
    assert (a["x"], a["y"]) == (150.0, 300.0)
    assert (c["x"], c["y"]) == (150.0, 300.0)


def test_update_moves_the_queen():
    b = _battle()
    qx, qy = b.queen["x"], b.queen["y"]
    _run(b, 120)
    assert (b.queen["x"], b.queen["y"]) != (qx, qy)


def _model_clears_card(b, ent):
    o = b.obstacle
    w = b._art[ent["kind"]]["w"]
    left, right = ent["x"] - w / 2, ent["x"] + w / 2
    top, bottom = ent["y"] - ent["sprite_h"], ent["y"]
    return not (left < o[2] and right > o[0] and top < o[3] and bottom > o[1])


def test_entities_full_models_stay_out_of_the_card_during_play():
    b = _battle()
    for _ in range(200):
        b.update(b._last_ms + 16 if b._last_ms else 1000)
        assert _model_clears_card(b, b.queen)
        for p in b.pawns:
            if p["alive"]:
                assert _model_clears_card(b, p)


def test_firing_creates_flash_and_projectiles():
    b = _battle()
    kinds_seen = set()
    saw_projectile = False
    for _ in range(400):
        b.update(b._last_ms + 16 if b._last_ms else 1000)
        kinds_seen.update(p["kind"] for p in b.particles)
        if b.projectiles:
            saw_projectile = True
    assert "flash" in kinds_seen
    assert saw_projectile, "firing should launch projectiles"
    assert "tracer" not in kinds_seen and "muzzle" not in kinds_seen


def test_ragdoll_progresses_and_pawn_is_removed():
    b = _battle()
    dying = None
    t = 1000
    while dying is None and t < 1000 + 1600 * 16:
        b.update(t)
        t += 16
        dying = next((p for p in b.pawns if p["dying"]), None)
    assert dying is not None, "queen never landed a kill over a long run"
    assert dying["alive"] is False
    early = b._ragdoll(dying, dying["death_ms"] + int(0.25 * RAGDOLL_MS))
    late = b._ragdoll(dying, dying["death_ms"] + int(0.75 * RAGDOLL_MS))
    assert abs(late[0]) > abs(early[0]), "ragdoll rotation should grow over time"
    assert late[1] < early[1], "ragdoll should fade out"
    b.update(dying["death_ms"] + RAGDOLL_MS + 50)
    assert dying not in b.pawns, "the pawn should be removed after the ragdoll finishes"


def test_pawn_count_stays_within_max_and_fills_up():
    b = _battle()
    peak = 0
    for _ in range(800):
        b.update(b._last_ms + 16 if b._last_ms else 1000)
        assert len(b.pawns) <= MAX_PAWNS
        peak = max(peak, len(b.pawns))
    assert peak >= MAX_PAWNS - 1, "spawning should fill up toward the max over a long run"


def _distinct_colors(surf, rect, step=8):
    seen = set()
    for x in range(rect.x, rect.right, step):
        for y in range(rect.y, rect.bottom, step):
            seen.add(surf.get_at((x, y))[:3])
    return seen


def test_background_is_not_pure_black():
    b = _battle()
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    b.draw(win)
    assert win.get_at((2, 2))[:3] != (0, 0, 0)


def test_background_gradient_is_lit_at_top_center():
    b = _battle()
    bg = b._background((1000, 700))
    top_center = sum(bg.get_at((500, 130))[:3])
    bottom_corner = sum(bg.get_at((4, 696))[:3])
    assert top_center > bottom_corner, "the radial backdrop should be brightest near top-centre"


def test_projectile_draws_a_streak_at_its_position():
    b = _battle()
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    pr = {"x": 300, "y": 200, "vx": 800, "vy": 0, "style": "bullet",
          "size": 6, "len": 16, "color": Colors.amber_hi}
    b._draw_projectile(win, pr)
    lit = any(win.get_at((x, 200))[:3] != (0, 0, 0) for x in range(285, 305))
    assert lit, "the projectile should draw a visible streak at its position"
    assert win.get_at((600, 500))[:3] == (0, 0, 0), "nothing should draw away from the projectile"


def test_draw_paints_many_distinct_colors():
    b = _battle()
    _run(b, 60)
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    b.draw(win)
    assert len(_distinct_colors(win, win.get_rect())) > 12


def test_scrim_darkens_edges_more_than_center():
    b = _battle()
    win = pg.display.get_surface()
    win.fill(Colors.text)
    b.draw_scrim(win)
    center = sum(win.get_at(win.get_rect().center)[:3])
    corner = sum(win.get_at((2, 2))[:3])
    assert corner < center, "scrim should darken corners more than the centre"


def test_gun_image_renders_near_the_hand():
    b = _battle()
    q = b.queen
    q["x"], q["y"], q["face"], q["aim"], q["weapon"] = 500, 350, 1, 0.0, "blunderbuss"
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    b._draw_gun(win, q, 0, 0)
    px, py = b._gun_pivot(q)
    region = pg.Rect(int(px) - 4, int(py) - 30, int(q["gun_len"]) + 20, 60).clip(win.get_rect())
    lit = any(win.get_at((x, y))[:3] != (0, 0, 0)
              for x in range(region.x, region.right, 2)
              for y in range(region.y, region.bottom, 2))
    assert lit, "the gun image should render around the entity's hand"


def test_loads_all_six_guns_with_four_flashes_each():
    b = _battle()
    assert set(b._battle["guns"]) == {
        "blunderbuss", "hand_cannon", "lever_action", "ray_gun", "revolver", "shotgun"}
    for gun, flashes in b._battle["flashes"].items():
        assert len(flashes) == 4, f"{gun} should have 4 flashes"


def test_pawns_use_the_revolver():
    b = _battle()
    assert all(p["weapon"] == "revolver" for p in b.pawns)


def test_same_gun_is_identical_size_for_queen_and_pawn():
    b = _battle()
    assert b._weapons["queen"]["revolver"]["gun"].get_size() == \
        b._weapons["pawn"]["revolver"]["gun"].get_size(), \
        "a gun must be the same size in any hand, not scaled to the holder"


def test_gun_grip_anchor_differs_from_the_barrel_tip():
    b = _battle()
    for gm in b._battle["guns"].values():
        assert (gm["gx"], gm["gy"]) != (gm["ax"], gm["ay"]), \
            "the hand grip must be a distinct point from the barrel tip"


def test_muzzle_sits_a_barrel_length_from_the_hand_along_the_aim():
    b = _battle()
    q = b.queen
    q["x"], q["y"], q["aim"], q["weapon"] = 500, 300, 0.0, "revolver"
    hx, hy = b._gun_pivot(q)
    mx, my = b._muzzle_point(q)
    entry = b._weapons["queen"]["revolver"]
    reach = math.hypot(entry["barrel"][0] - entry["grip"][0],
                       entry["barrel"][1] - entry["grip"][1])
    assert mx > hx, "aiming right, the muzzle should be right of the hand"
    assert abs(math.hypot(mx - hx, my - hy) - reach) < 1.0


def test_queen_starts_with_the_blunderbuss():
    b = _battle()
    assert b.queen["weapon"] == "blunderbuss"


def test_queen_switch_timer_resets_into_range_and_changes_weapon():
    b = _battle()
    q = b.queen
    q["weapon"], q["weapon_switch"] = "blunderbuss", 0.0
    weapons = set()
    resets = []
    prev = q["weapon_switch"]
    for _ in range(2000):
        b.update(b._last_ms + 16 if b._last_ms else 1000)
        if q["weapon_switch"] > prev:
            resets.append(q["weapon_switch"])
        prev = q["weapon_switch"]
        weapons.add(q["weapon"])
    assert resets, "the switch timer should reset at least once"
    assert all(WEAPON_SWITCH_MIN <= r <= WEAPON_SWITCH_MAX for r in resets)
    assert len(weapons) >= 2, "the queen should cycle through more than one weapon"
    assert weapons <= set(b._battle["guns"])


def test_flash_particle_records_weapon_and_valid_index():
    b = _battle()
    b.pawns = [b.pawns[0]]
    b.pawns[0]["x"], b.pawns[0]["y"], b.pawns[0]["fire"] = 500, 360, 99
    b.queen["weapon"] = "shotgun"
    _aim_at(b, b.queen, b.pawns[0])
    b.acc["qfire"] = -1
    b.particles.clear()
    b._step(0.0, 5000)
    flashes = [p for p in b.particles if p["kind"] == "flash"]
    assert flashes, "the queen should emit a flash particle when firing"
    assert flashes[0]["weapon"] == "shotgun"
    assert 0 <= flashes[0]["idx"] < 4


def test_flash_index_is_uniform_over_many_shots():
    b = _battle()
    seen = set()
    for now in range(1000, 1000 + 4000 * 16, 16):
        b.update(now)
        for p in b.particles:
            if p["kind"] == "flash":
                seen.add(p["idx"])
    assert seen == {0, 1, 2, 3}, "all four flash variants should appear over many shots"


def test_draw_is_noop_before_set_rect():
    b = MenuBattle(pg.display.get_surface(), rng=random.Random(1))
    win = pg.display.get_surface()
    win.fill((9, 9, 9))
    b.update(1000)
    b.draw(win)
    assert b.queen is None
    assert win.get_at((10, 10))[:3] == (9, 9, 9)


def test_renders_without_piece_art():
    b = MenuBattle(pg.display.get_surface(), rng=random.Random(2))
    b._queen_src = None
    b._pawn_src = None
    b.set_rect(pg.Rect(0, 0, 900, 600))
    b.set_avoid_rect(pg.Rect(250, 120, 400, 360))
    _run(b, 40)
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    b.draw(win)
    assert len(_distinct_colors(win, win.get_rect())) > 5


def test_wrap_words_keeps_each_word_on_its_own_line_at_min_width():
    lines = MenuBattle._wrap_words("alpha beta gamma", get_font(12, bold=True), 1)
    assert lines == ["alpha", "beta", "gamma"]


def test_wrap_words_does_not_split_a_single_word():
    font = get_font(12, bold=True)
    assert MenuBattle._wrap_words("supercalifragilistic", font, 1) == ["supercalifragilistic"]


def test_wrap_words_stays_one_line_when_width_is_ample():
    font = get_font(12, bold=True)
    assert MenuBattle._wrap_words("short text here", font, 10000) == ["short text here"]


def _amber_in_band(window, y0, y1):
    amber = pg.Color(Colors.amber)[:3]
    for y in range(max(y0, 0), min(y1, window.get_height())):
        for x in range(0, window.get_width(), 3):
            c = window.get_at((x, y))[:3]
            if all(abs(a - b) <= 22 for a, b in zip(c, amber)):
                return True
    return False


def test_bubble_near_titlebar_shifts_below_it():
    """A queen whose head sits against the title bar gets her bubble shifted to the side,
    entirely below the reserved title-bar strip (never drawn into it)."""
    b = _battle()
    q = b.queen
    q["x"], q["y"] = 120, b.top_inset + q["head"] + 10
    b._say(q, "GET BACK IN LINE", "queen", 1000)
    b._last_ms = 1300
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    b.draw(win)
    assert not _amber_in_band(win, 0, b.top_inset)
    assert _amber_in_band(win, b.top_inset, b.top_inset + 90)
