"""Frontend skill-check layer: the wheel controller's tap/auto-fail/result-hold
lifecycle, the multi-shot aim controller (hit/miss-escalate/timeout), the generic
overlay host that finishes and reports outcome, the kind->controller registry, and
the Frontend gate that defers a Shootout capture into a wheel or steady-aim and
applies the move on a win / locks it on a fail. The aim check renders over the
victim square (en-passant aware) and suppresses that square on the live board so
the shrinking piece doesn't ghost. Every failed check makes the piece swear. A
landed ply clears the locks.
"""

import logging
import math
from collections import Counter
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.backend.utils import BOARD_SIZE, Square
from chessshootout.domain.premoves import Premove
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.game.skillcheck_session import CheckContext
from chessshootout.frontend.skillcheck.aim_view import (
    AimController, AIM_CROSS_LW_FRAC, AIM_RING_LW_FRAC, AIM_RESULT_HOLD_MS,
    AIM_MISS_FLASH_MS, AIM_SHOT_HOLD_MS, _spotlight_surface, _SHOOTER_KEY, _VICTIM_KEY)
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.overlay import SkillCheckOverlay
from chessshootout.frontend.skillcheck.registry import CheckSpec, build_controller
from chessshootout.frontend.skillcheck.wheel_view import (
    WheelController, WHEEL_RESULT_HOLD_MS, _clamp_bubble_left, _needle_polygon)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.coordinator import move_roll_key
from chessshootout.skillcheck.rng import ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome
from chessshootout.domain.pgn.generate import format_annotations
from chessshootout.skillcheck.wheel import (
    WheelChallenge, WHEEL_HUMAN_FLOOR_MS, adjudicate, placement_square)


_pygame_init = pygame_display(1100, 800)


def _always_in_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def _never_in_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=0.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def _tap():
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": (10, 10)})


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


def _band_ring_hue(ctrl, surface):
    """Walk the wheel's arc band radius and return the first painted hue we hit (the band
    fills 360 deg here, so every spoke crosses it)."""
    cx, cy = ctrl.center
    r = ctrl.radius - ctrl.band_w // 2
    for deg in range(0, 360, 3):
        a = math.radians(deg - 90.0)
        px, py = int(cx + r * math.cos(a)), int(cy + r * math.sin(a))
        col = surface.get_at((px, py))
        if col in (pg.Color(Colors.accent), pg.Color(Colors.spectate)):
            return col
    return None


def test_wheel_draw_paints_the_dial_pixels():
    """The dial is not a no-op draw: the hub paints text-color at the exact center, the band
    paints the accent hue for a live check, and a passive (spectated) wheel swaps the band to
    the spectate hue. Pixel-level, so replacing draw() with `pass` would fail this."""
    surf = pg.Surface((300, 300), pg.SRCALPHA)
    surf.fill((7, 8, 9, 255))
    live = WheelController(_always_in_arc(), pg.Rect(100, 100, 80, 80), now_ms=0)
    live.update(200)
    live.draw(surf)
    assert surf.get_at(live.center) == pg.Color(Colors.text), "the needle hub paints at center"
    assert _band_ring_hue(live, surf) == pg.Color(Colors.accent), "a live wheel band is accent"

    surf2 = pg.Surface((300, 300), pg.SRCALPHA)
    surf2.fill((7, 8, 9, 255))
    passive = WheelController(_always_in_arc(), pg.Rect(100, 100, 80, 80), now_ms=0, passive=True)
    passive.update(200)
    passive.draw(surf2)
    assert _band_ring_hue(passive, surf2) == pg.Color(Colors.spectate), \
        "a spectated wheel reads in the spectate hue, not the mover's accent"


def test_render_needle_pixel_matches_the_adjudication_angle_convention():
    """The rendered needle must sit at the exact pixel angle the engine used to decide the
    tap won -- same zero direction, same rotation sense. A silent drift here (e.g. a sign
    flip or a different zero-reference between wheel.py and wheel_view.py) would let the
    dial visually lie about which taps land."""
    ch = WheelChallenge(arc_start_deg=10.0, arc_width_deg=40.0, period_ms=3600.0,
                        start_angle_deg=0.0)
    elapsed = 121.0
    needle_deg = ch.needle_deg(elapsed)
    assert adjudicate(ch, elapsed, 0.0) is True, "sanity: this elapsed is a genuine win"
    ctrl = WheelController(ch, pg.Rect(100, 100, 160, 160), now_ms=0)
    ctrl.update(int(elapsed))
    surf = pg.Surface((400, 400), pg.SRCALPHA)
    surf.fill((7, 8, 9, 255))
    ctrl.draw(surf)
    cx, cy = ctrl.center
    needle_len = ctrl.radius - ctrl.ring_w - 2
    a = math.radians(needle_deg - 90.0)
    px = int(cx + needle_len * 0.6 * math.cos(a))
    py = int(cy + needle_len * 0.6 * math.sin(a))
    assert surf.get_at((px, py)) == pg.Color(Colors.text), \
        "the pixel the engine says is a winning tap sits under the drawn needle"


_WHEEL_GEOMETRY_FRACS = {"ring_w": 0.08, "band_w": 0.20, "needle_w": 0.12, "hub_r": 0.10}


def _wheel_at_cell(cell):
    return WheelController(_always_in_arc(), pg.Rect(0, 0, cell, cell), now_ms=0)


@pytest.mark.parametrize("cell,expected_radius", [(60, 28), (99, 49), (170, 86)])
def test_geometry_ratios_track_the_anchor_fractions_at_min_default_and_fullscreen(
        cell, expected_radius):
    ctrl = _wheel_at_cell(cell)
    assert ctrl.radius == expected_radius
    for attr, frac in _WHEEL_GEOMETRY_FRACS.items():
        ratio = getattr(ctrl, attr) / ctrl.radius
        assert ratio == pytest.approx(frac, abs=0.6 / ctrl.radius), \
            "{} drifted more than one rounding step off its anchor fraction".format(attr)


def test_default_radius_reproduces_todays_approved_pixel_values(monkeypatch):
    from chessshootout.frontend.skillcheck import wheel_view as wheel_view_module
    sizes = []
    real_get_font = wheel_view_module.get_font
    monkeypatch.setattr(wheel_view_module, "get_font", lambda size, **kw: (
        sizes.append(size), real_get_font(size, **kw))[1])
    ctrl = _wheel_at_cell(99)
    assert ctrl.radius == 49
    assert (ctrl.ring_w, ctrl.band_w, ctrl.needle_w, ctrl.hub_r) == (4, 10, 6, 5)
    assert sizes[-1] == 13, "the hint font must still request today's approved 13pt at r=49"


def test_needle_tip_is_narrower_than_the_shaft_no_more_full_width_overshoot():
    ctrl = _wheel_at_cell(99)
    assert ctrl.needle_tip_w < ctrl.needle_w
    assert ctrl.needle_tip_w == max(2, round(ctrl.needle_w * 0.30))


def test_needle_polygon_tapers_and_its_cap_sits_exactly_at_the_needle_length():
    cx, cy, deg, length, base_w, tip_w = 100.0, 100.0, 0.0, 40.0, 10.0, 3.0
    base_a, tip_a, tip_b, base_b = _needle_polygon(cx, cy, deg, length, base_w, tip_w)
    base_width = math.hypot(base_a[0] - base_b[0], base_a[1] - base_b[1])
    tip_width = math.hypot(tip_a[0] - tip_b[0], tip_a[1] - tip_b[1])
    assert base_width == pytest.approx(base_w)
    assert tip_width == pytest.approx(tip_w)
    assert tip_width < base_width, "the polygon actually tapers, it is not a constant-width quad"
    tip_center = ((tip_a[0] + tip_b[0]) / 2.0, (tip_a[1] + tip_b[1]) / 2.0)
    assert math.hypot(tip_center[0] - cx, tip_center[1] - cy) == pytest.approx(length), \
        "the tip cap is centered exactly at needle_len, the old half-shaft-width overshoot is gone"


def test_footprint_stays_within_budget_at_a_small_window_cell():
    cell = 57
    ctrl = _wheel_at_cell(cell)
    timer_outer = ctrl.radius + ctrl.ring_w + ctrl.timer_gap
    footprint = timer_outer * 2 + 8
    assert footprint <= 1.20 * cell + 2, "the dial must not blow its footprint budget"


def test_hint_bubble_left_clamps_inside_the_window():
    assert _clamp_bubble_left(-200, 150, 600) == 4, "clamps off the left edge"
    assert _clamp_bubble_left(700, 150, 600) == 600 - 150 - 4, "clamps off the right edge"
    assert _clamp_bubble_left(200, 150, 600) == 200, "leaves an already-on-screen bubble alone"


def test_hint_bubble_draw_stays_inside_the_window_for_a_column_zero_wheel():
    ctrl = WheelController(_always_in_arc(), pg.Rect(-40, 300, 99, 99), now_ms=0)
    window = pg.Surface((600, 600), pg.SRCALPHA)
    ctrl._draw_hint_bubble(window, ctrl.center[0], ctrl.center[1],
                           ctrl.radius + ctrl.ring_w + ctrl.timer_gap)
    border = pg.Color(Colors.border_strong)
    painted_cols = [x for x in range(window.get_width())
                    if any(window.get_at((x, y)) == border for y in range(window.get_height()))]
    assert painted_cols, "the bubble actually drew something"
    assert min(painted_cols) >= 4, "the bubble never bleeds off the left edge of the window"


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


def test_registry_builds_wheel_controller():
    ctrl = build_controller(
        SkillCheckKind.WHEEL,
        CheckSpec(seed="s", cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000))
    assert isinstance(ctrl, WheelController)


def test_registry_builds_aim_controller():
    ctrl = build_controller(
        SkillCheckKind.AIM,
        CheckSpec(seed="s", cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000,
                  value_diff=4, victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                  board_rect=pg.Rect(0, 0, 640, 640)))
    assert isinstance(ctrl, AimController)


def _aim_centerable():
    return AimChallenge(phase0=0.0, rotation0_deg=0.0, travel_period_ms=1500.0,
                        rotation_period_ms=3700.0, deadline_ms=5000.0)


def _aim_ctrl(challenge=None, **kw):
    return AimController(challenge or _aim_centerable(), pg.Rect(0, 0, 80, 80), now_ms=0, **kw)


def test_aim_hit_on_center_crossing_lands_after_hold():
    ctrl = _aim_ctrl()
    ctrl.update(375)
    ctrl.handle_event(_tap())
    assert ctrl.landed is True
    assert ctrl.done is False
    ctrl.update(375 + AIM_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_aim_miss_escalates_and_keeps_the_overlay_open():
    ctrl = _aim_ctrl()
    ctrl.update(10)
    ctrl.handle_event(_tap())
    assert ctrl.landed is None
    assert ctrl.miss_count == 1
    assert ctrl.done is False
    fired = [c for c in ctrl._fx.captures if c.get("miss")]
    assert fired and fired[0]["callout"] is False, "a per-miss dry-fire, no big SKILL ISSUE"
    assert any(p.get("kind") == "tag" for p in ctrl._fx.particles), "the piece swears on a miss"


def test_aim_miss_plays_the_shot_sound_when_the_gun_fires():
    played = []
    ctrl = AimController(_aim_centerable(), pg.Rect(60, 60, 80, 80), now_ms=0,
                         board_rect=pg.Rect(0, 0, 640, 640),
                         geom=lambda sq: (sq.col * 80 + 40, sq.row * 80 + 40),
                         from_sq=Square(5, 5), victim_sq=Square(3, 3),
                         attacker_type="queen", shot_sound=lambda: played.append(1))
    ctrl.update(10)
    ctrl.handle_event(_tap())
    assert ctrl.miss_count == 1
    assert played == [], "the shot is silent until the draw-and-aim finishes"
    ctrl.update(600)
    assert played == [1], "the dry-fire plays the gunshot when the gun actually fires"


def test_aim_miss_with_a_real_geom_and_no_shooter_square_never_leaks_a_sentinel():
    """A check opened without a from_sq/victim_sq stands the missing squares in as
    sentinel strings. A board resolver only understands Squares -- the production
    one is `board.cell_rect(sq).center` -- so handing it a sentinel would blow up
    inside EffectManager the first time the miss choreography looked up a centre.
    The view answers its own sentinels with its centre and passes real squares
    straight through, so the wiring is safe whichever resolver is installed."""
    surf = pg.display.get_surface()
    asked = []

    def board_geom(sq):
        asked.append(sq)
        return (sq.col * 80 + 40, sq.row * 80 + 40)

    ctrl = AimController(_aim_centerable(), pg.Rect(160, 240, 80, 80), now_ms=0,
                         victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                         board_rect=pg.Rect(0, 0, 640, 640), geom=board_geom,
                         from_sq=None, victim_sq=None, attacker_type="queen")
    ctrl.update(10)
    ctrl.handle_event(_tap())
    assert ctrl.miss_count == 1, "the shot was played out as a miss"
    assert [c for c in ctrl._fx.captures if c.get("miss")], "a dry-fire is staged"
    for now in range(20, 900, 20):
        ctrl.update(now)
        ctrl.draw(surf)
    assert asked == [], "the board resolver is never asked to place a sentinel"
    assert ctrl._geom(_SHOOTER_KEY) == ctrl.center == (200, 280)
    assert ctrl._geom(_VICTIM_KEY) == ctrl.center
    assert ctrl._geom(Square(1, 2)) == (200, 120), "a real square still routes to the board"
    assert asked == [Square(1, 2)], "and only a real square reaches the resolver"


def test_aim_miss_then_center_hit_still_wins():
    ctrl = _aim_ctrl()
    ctrl.update(10)
    ctrl.handle_event(_tap())
    assert ctrl.miss_count == 1
    ctrl.update(341)
    ctrl.handle_event(_tap())
    assert ctrl.landed is True


def test_aim_timeout_fails_at_deadline():
    ctrl = _aim_ctrl()
    ctrl.update(4999)
    assert ctrl.landed is None
    ctrl.update(5000)
    assert ctrl.landed is False
    ctrl.update(5000 + AIM_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_aim_immediate_tap_misses_under_the_start_guard():
    ctrl = AimController(AimChallenge.from_seed("guard-x", 0), pg.Rect(0, 0, 80, 80), now_ms=0)
    ctrl.update(0)
    ctrl.handle_event(_tap())
    assert ctrl.landed is None, "the figure-8 starts a lobe away so an instant tap can't win"
    assert ctrl.miss_count == 1


def test_aim_second_tap_after_a_win_is_ignored():
    ctrl = _aim_ctrl()
    ctrl.update(375)
    ctrl.handle_event(_tap())
    ctrl.update(380)
    ctrl.handle_event(_tap())
    assert ctrl.landed is True
    assert ctrl.miss_count == 0


def test_aim_space_also_fires():
    ctrl = _aim_ctrl()
    ctrl.update(375)
    ctrl.handle_event(pg.event.Event(pg.KEYDOWN, {"key": pg.K_SPACE, "unicode": " ", "mod": 0}))
    assert ctrl.landed is True


def test_aim_draw_does_not_crash():
    surf = pg.display.get_surface()
    ctrl = AimController(_aim_centerable(), pg.Rect(40, 40, 80, 80), now_ms=0,
                         victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                         board_rect=pg.Rect(0, 0, 640, 640))
    ctrl.update(200)
    ctrl.draw(surf)
    ctrl.update(220)
    ctrl.handle_event(_tap())
    ctrl.update(260)
    ctrl.draw(surf)
    assert ctrl.done is False


def test_aim_relayout_reanchors_and_set_board_rect_updates_region():
    ctrl = AimController(_aim_centerable(), pg.Rect(0, 0, 80, 80), now_ms=0,
                         board_rect=pg.Rect(0, 0, 640, 640))
    ctrl.relayout(pg.Rect(200, 200, 100, 100))
    assert ctrl.center == (250, 250)
    ctrl.set_board_rect(pg.Rect(10, 10, 700, 700))
    assert ctrl._board_rect == pg.Rect(10, 10, 700, 700)


def test_aim_victim_resamples_once_per_size_not_per_relayout(monkeypatch):
    calls = []
    real_smoothscale = pg.transform.smoothscale

    def spy(surface, size):
        calls.append(size)
        return real_smoothscale(surface, size)

    monkeypatch.setattr(pg.transform, "smoothscale", spy)
    victim = pg.Surface((80, 80), pg.SRCALPHA)
    ctrl = AimController(_aim_centerable(), pg.Rect(0, 0, 80, 80), now_ms=0,
                         victim_surface=victim, board_rect=pg.Rect(0, 0, 640, 640))
    assert calls == [], "the first cell_rect matches the victim's native size -- no resample"
    for size in (160, 80, 160, 200, 160):
        ctrl.relayout(pg.Rect(0, 0, size, size))
    assert len(calls) == 2, \
        "only the two distinct new sizes (160, 200) ever trigger a real resample"
    assert ctrl._victim.get_size() == (160, 160)


def test_aim_victim_relayout_never_cumulatively_rescales(monkeypatch):
    real_smoothscale = pg.transform.smoothscale
    calls = []
    monkeypatch.setattr(pg.transform, "smoothscale", lambda s, sz: (
        calls.append(sz), real_smoothscale(s, sz))[1])
    victim = pg.Surface((80, 80), pg.SRCALPHA)
    ctrl = AimController(_aim_centerable(), pg.Rect(0, 0, 80, 80), now_ms=0,
                         victim_surface=victim, board_rect=pg.Rect(0, 0, 640, 640))
    ctrl.relayout(pg.Rect(0, 0, 160, 160))
    first = ctrl._victim
    ctrl.relayout(pg.Rect(0, 0, 80, 80))
    ctrl.relayout(pg.Rect(0, 0, 160, 160))
    second = ctrl._victim
    assert second is first, "the same target size returns the cached resample, not a fresh chain"
    assert len(calls) == 1, "only one real resample happened despite bouncing through 3 sizes"


def test_spotlight_surface_size_matches_its_radius():
    assert _spotlight_surface(45).get_size() == (90, 90)
    assert _spotlight_surface(10).get_size() == (20, 20)


def test_spotlight_surface_is_cached_by_radius():
    assert _spotlight_surface(45) is _spotlight_surface(45)


def test_aim_stroke_width_fracs_reproduce_the_old_fixed_pixel_widths_at_anchor_cell():
    cell = 99.6
    assert max(1, round(cell * AIM_CROSS_LW_FRAC)) == 2, \
        "the old fixed 2.4px cross/reticle stroke rounded to 2px at the approved default"
    assert max(1, round(cell * AIM_RING_LW_FRAC)) == 2, \
        "the old fixed 2px hit-ring/path stroke is unchanged at the approved default"


def test_wheel_online_tap_sends_a_shot_and_never_resolves_locally():
    shots = []
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0,
                           on_shot=lambda *a: shots.append(1))
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50)
    ctrl.handle_event(_tap())
    assert shots == [1], "firing sends exactly one shot to the server"
    assert ctrl.landed is None, "the client never paints its own verdict online"
    assert ctrl.done is False


def test_wheel_online_does_not_auto_fail_at_the_deadline():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0,
                           deadline_ms=1500, on_shot=lambda *a: None)
    ctrl.update(3000)
    assert ctrl.landed is None, "the server sweep fails an unanswered wheel, not the client"
    assert ctrl.done is False


def test_wheel_online_is_still_one_shot():
    shots = []
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0,
                           on_shot=lambda *a: shots.append(1))
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50)
    ctrl.handle_event(_tap())
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 80)
    ctrl.handle_event(_tap())
    assert shots == [1]


def test_wheel_online_frozen_draw_does_not_crash():
    ctrl = WheelController(_always_in_arc(), pg.Rect(40, 40, 80, 80), now_ms=0,
                           on_shot=lambda *a: None)
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 50)
    ctrl.handle_event(_tap())
    ctrl.update(int(WHEEL_HUMAN_FLOOR_MS) + 60)
    ctrl.draw(pg.display.get_surface())
    assert ctrl.landed is None


def test_aim_online_tap_is_optimistic_miss_never_a_local_win():
    shots = []
    ctrl = _aim_ctrl(on_shot=lambda *a: shots.append(1))
    ctrl.update(375)
    ctrl.handle_event(_tap())
    assert shots == [1], "the shot goes to the server"
    assert ctrl.landed is None, "even a geometrically on-target tap is only the server's to upgrade"
    assert ctrl.miss_count == 1
    fired = [c for c in ctrl._fx.captures if c.get("miss")]
    assert fired and fired[0]["callout"] is False, "optimistic dry-fire feedback, no big verdict"


def test_aim_online_does_not_self_fail_at_expiry():
    ctrl = _aim_ctrl(on_shot=lambda *a: None)
    ctrl.update(6000)
    assert ctrl.landed is None, "the server decides expiry online"
    assert ctrl.done is False


def test_aim_online_post_expiry_draw_does_not_crash():
    ctrl = AimController(_aim_centerable(), pg.Rect(40, 40, 80, 80), now_ms=0,
                         victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                         board_rect=pg.Rect(0, 0, 640, 640), on_shot=lambda *a: None)
    ctrl.update(7000)
    ctrl.draw(pg.display.get_surface())
    assert ctrl.landed is None


def test_aim_online_resume_seeds_the_miss_count():
    """A resumed aim check restores the server's miss_count and the next dry-fire escalates
    off that seed (3 -> 4), freezing the figure-8 on the seeded lobe — mirrors the spectate
    3->4 path. A behavioral consequence, not a freshly-set constructor arg."""
    ctrl = _aim_ctrl(on_shot=lambda *a: None, miss_count=2)
    ctrl.update(375)
    ctrl.handle_event(_tap())
    assert ctrl.miss_count == 3, "the seeded miss_count is the base the dry-fire escalates from"
    assert ctrl._shot_render == (375, 2), "the shot freezes on the seeded (pre-increment) lobe"
    assert ctrl._shot_offset == ctrl.challenge.reticle_offset(375, 2), \
        "the frozen crosshair sits on the escalated lobe, not the fresh miss_count=0 figure-8"
    assert ctrl._shot_offset != ctrl.challenge.reticle_offset(375, 1), \
        "the seeded lobe differs from a lower escalation — the count really drove the geometry"


def test_wheel_online_resolve_holds_the_verdict_then_finishes():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0,
                           on_shot=lambda *a: None)
    ctrl.update(300)
    ctrl.handle_event(_tap())
    ctrl.update(350)
    ctrl.resolve(True)
    assert ctrl.landed is True
    assert ctrl.done is False, "the green verdict holds before the move applies"
    ctrl.update(350 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_aim_online_resolve_loss_holds_then_finishes():
    ctrl = _aim_ctrl(on_shot=lambda *a: None)
    ctrl.update(300)
    ctrl.resolve(False)
    assert ctrl.landed is False
    assert ctrl.done is False
    ctrl.update(300 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_aim_miss_flashes_red_then_fades_to_normal():
    ctrl = _aim_ctrl(on_shot=lambda *a: None)
    ctrl.update(10)
    ctrl.handle_event(_tap())
    fresh, _ = ctrl._reticle_colors()
    assert fresh != pg.Color(Colors.accent), "a fresh miss tints the reticle red"
    ctrl.update(10 + AIM_MISS_FLASH_MS + 50)
    faded, _ = ctrl._reticle_colors()
    assert faded == pg.Color(Colors.accent), "the red flash fades back to normal color"


def test_aim_online_locks_render_on_the_clicked_shot_not_the_resolve_time():
    ctrl = _aim_ctrl(on_shot=lambda *a: None)
    ctrl.update(800)
    ctrl.handle_event(_tap())
    assert ctrl._shot_render == (800, 0), "the click is captured at fire, pre-increment"
    ctrl.update(1100)
    ctrl.resolve(True)
    assert ctrl._render_state() == (800, 0), \
        "the crosshair locks on the clicked point, not where it drifted during the RTT"


def test_wheel_online_freezes_the_needle_at_the_fire_not_the_resolve():
    ctrl = WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0,
                           on_shot=lambda *a: None)
    ctrl.update(400)
    ctrl.handle_event(_tap())
    assert ctrl._committed_at == 400
    ctrl.update(700)
    ctrl.resolve(True)
    assert ctrl._frozen_elapsed() == 400, "resolve never moves the frozen needle"


def test_aim_online_crosshair_holds_at_the_shot_then_resumes():
    ctrl = _aim_ctrl(on_shot=lambda *a: None)
    ctrl.update(800)
    ctrl.handle_event(_tap())
    held = ctrl._shot_offset
    assert held is not None
    ctrl.update(800 + 30)
    e, m = ctrl._now - ctrl.start_ms, ctrl.miss_count
    assert ctrl._crosshair_offset(e, m) == held, "the crosshair holds at the click — no teleport"
    ctrl.update(800 + AIM_SHOT_HOLD_MS + 50)
    e, m = ctrl._now - ctrl.start_ms, ctrl.miss_count
    assert ctrl._crosshair_offset(e, m) == ctrl.challenge.reticle_offset(e, m), \
        "after the hold (no verdict) the crosshair resumes the live figure-8 for the next shot"


def test_aim_online_resolve_lands_on_the_held_point_with_no_snap():
    ctrl = _aim_ctrl(on_shot=lambda *a: None)
    ctrl.update(800)
    ctrl.handle_event(_tap())
    held = ctrl._shot_offset
    ctrl.update(840)
    ctrl.resolve(True)
    elapsed, miss = ctrl._render_state()
    assert ctrl._crosshair_offset(elapsed, miss) == held, "verdict lands on the shot point, no snap"


def _spectate_wheel(challenge=None):
    return WheelController(challenge or _always_in_arc(), pg.Rect(0, 0, 80, 80),
                           now_ms=0, passive=True)


def _spectate_aim(**kw):
    return AimController(_aim_centerable(), pg.Rect(0, 0, 80, 80), now_ms=0,
                         victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                         board_rect=pg.Rect(0, 0, 640, 640), passive=True, **kw)


def test_passive_wheel_ignores_input_and_never_self_resolves():
    ctrl = _spectate_wheel()
    assert ctrl._passive is True and ctrl._online is True
    assert ctrl.handle_event(_tap()) is False, "a spectator click does not drive the check"
    ctrl.update(6000)
    assert ctrl.landed is None and ctrl.done is False, "only the server verdict resolves it"


def test_passive_wheel_shot_freezes_the_needle_at_the_relayed_elapsed():
    ctrl = _spectate_wheel()
    ctrl.update(1000)
    ctrl.spectate_shot(742.0, 0, True)
    assert ctrl._frozen_elapsed() == 742.0, "frozen where the mover fired, not on local time"
    assert ctrl._committed_at is not None, "the spin stops on the relayed shot"


def test_passive_wheel_resolve_holds_then_finishes():
    ctrl = _spectate_wheel()
    ctrl.update(500)
    ctrl.spectate_shot(400.0, 0, True)
    ctrl.resolve(True)
    assert ctrl.landed is True and ctrl.done is False
    ctrl.update(500 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_passive_wheel_draw_does_not_crash():
    ctrl = WheelController(_always_in_arc(), pg.Rect(40, 40, 80, 80), now_ms=0, passive=True)
    ctrl.update(300)
    ctrl.draw(pg.display.get_surface())
    ctrl.spectate_shot(300.0, 0, False)
    ctrl.draw(pg.display.get_surface())
    assert ctrl.landed is None


def test_passive_aim_ignores_input_and_never_self_resolves():
    ctrl = _spectate_aim()
    assert ctrl.handle_event(_tap()) is False
    ctrl.update(7000)
    assert ctrl.landed is None and ctrl.done is False


def test_passive_aim_win_shot_freezes_without_a_dry_miss():
    ctrl = _spectate_aim()
    ctrl.update(900)
    ctrl.spectate_shot(820.0, 0, True)
    assert ctrl._shot_render == (820.0, 0), "frozen at the winning crosshair"
    assert ctrl.miss_count == 0, "a win does not escalate"
    assert not [c for c in ctrl._fx.captures if c.get("miss")], "a winning shot fires no dry-miss"


def test_passive_aim_miss_shot_replays_the_dry_fire_and_escalates():
    ctrl = _spectate_aim()
    ctrl.update(600)
    ctrl.spectate_shot(560.0, 0, False)
    assert ctrl._shot_render == (560.0, 0), "frozen at the mover's fired position"
    assert ctrl.miss_count == 1, "the relayed miss escalates the reticle"
    fired = [c for c in ctrl._fx.captures if c.get("miss")]
    assert fired and fired[0]["callout"] is False, "the same dry gun-miss the mover saw"


def test_passive_aim_trusts_the_relayed_pre_shot_miss_count():
    ctrl = _spectate_aim()
    ctrl.update(600)
    ctrl.spectate_shot(560.0, 3, False)
    assert ctrl.miss_count == 4, "the spectator uses the server's pre-shot count + 1"


def test_passive_aim_skips_the_board_scrim():
    ctrl = _spectate_aim()
    win = pg.Surface((640, 640), pg.SRCALPHA)
    win.fill((1, 2, 3, 255))
    ctrl._draw_scrim(win)
    assert win.get_at((5, 5)) == pg.Color(1, 2, 3, 255), "no dimming scrim over the live board"


def test_passive_aim_reticle_uses_the_spectate_hue():
    ctrl = _spectate_aim()
    ctrl.update(100)
    live, _ = ctrl._reticle_colors()
    assert live == pg.Color(Colors.spectate), "the opponent's check reads in the spectate hue"
    mover = _aim_ctrl(on_shot=lambda *a: None)
    mover.update(100)
    live2, _ = mover._reticle_colors()
    assert live2 == pg.Color(Colors.accent), "my own check stays in the accent hue"


def test_passive_aim_draw_does_not_crash():
    ctrl = _spectate_aim()
    ctrl.update(400)
    ctrl.draw(pg.display.get_surface())
    ctrl.spectate_shot(380.0, 0, False)
    ctrl.draw(pg.display.get_surface())
    assert ctrl.landed is None


def test_overlay_is_passive_only_for_a_spectate_controller():
    overlay = SkillCheckOverlay()
    overlay.start(WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0),
                  None, lambda *a: None)
    assert overlay.is_passive() is False, "a playable check captures input"
    overlay.cancel()
    overlay.start(_spectate_wheel(), None, lambda *a: None)
    assert overlay.is_passive() is True
    overlay.spectate_shot(500.0, 0, True)
    assert overlay._controller._frozen_override == 500.0, "the overlay relays the shot through"


def test_registry_threads_passive_into_both_controllers():
    """passive=True must reach the controller through the registry, not just be stored:
    a passive controller swallows no input and never self-resolves past its deadline. These
    consequences are reachable only if the flag was actually wired into build_controller."""
    w = build_controller(
        SkillCheckKind.WHEEL,
        CheckSpec(seed="s", cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000,
                  passive=True))
    assert w.handle_event(_tap()) is False, "a registry-built passive wheel ignores the tap"
    w.update(6000)
    assert w.landed is None and w.done is False, "and never self-fails at the deadline"
    a = build_controller(
        SkillCheckKind.AIM,
        CheckSpec(seed="s", cell_rect=pg.Rect(0, 0, 80, 80), now_ms=0, deadline_ms=5000,
                  value_diff=4, victim_surface=pg.Surface((80, 80), pg.SRCALPHA),
                  board_rect=pg.Rect(0, 0, 640, 640), passive=True))
    assert a.handle_event(_tap()) is False, "a registry-built passive aim ignores the tap"
    a.update(7000)
    assert a.landed is None and a.done is False, "only the server verdict resolves a spectated aim"


def _start_local(app):
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": 5, "increment_seconds": 0})
    app.draw_frame()


def _set_queen_takes_pawn(app):
    b = app.game.match.backend
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
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed(app.game.match.backend, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    assert app.game.skillcheck_overlay.is_active() is True


def test_won_skillcheck_applies_move():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), True)
    assert len(app.game.match.move_history) == 1
    assert app.game.match.piece_at(to).type == PieceType.QUEEN


def test_failed_skillcheck_locks_move():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), False)
    assert len(app.game.match.move_history) == 0
    assert app.game.skillcheck.is_locked(frm, to) is True
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    assert app.game.skillcheck_overlay.is_active() is False


def test_failed_skillcheck_fires_the_miss_fx():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), False)
    fx = app.game.board.effects
    fired = any(c.get("miss") for c in fx.captures) or bool(fx.callouts)
    assert fired, "a failed skill-check fires the gun-and-miss FX"
    assert fx.held_squares() == set(), "the victim stays on the board after a miss"


def test_won_skillcheck_logs_resolved_with_kind_ply_and_outcome(caplog):
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.game.skillcheck_session._on_skillcheck_done(
            CheckContext(frm, to, None, SkillCheckKind.WHEEL), True)
    resolved = [r.getMessage() for r in caplog.records if "skillcheck resolved" in r.getMessage()]
    assert resolved, "a landed check must log its resolution"
    assert "kind=wheel" in resolved[0]
    assert "ply=1" in resolved[0]
    assert "won=True" in resolved[0]


def test_failed_skillcheck_logs_resolved_and_the_move_lock(caplog):
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        app.game.skillcheck_session._on_skillcheck_done(
            CheckContext(frm, to, None, SkillCheckKind.AIM), False)
    messages = [r.getMessage() for r in caplog.records]
    resolved = [m for m in messages if "skillcheck resolved" in m]
    locked = [m for m in messages if "skillcheck move locked" in m]
    assert resolved and "kind=aim" in resolved[0] and "won=False" in resolved[0]
    assert locked, "a whiffed check must log that the move got locked"


def _shootout_with_wheel(app):
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed(app.game.match.backend, frm, to))
    return frm, to


def _render_wheel(app, frm, to, seed, value_diff=8):
    return app.game.skillcheck_session._skillcheck_render_square(
        SkillCheckKind.WHEEL, seed, value_diff, frm, to)


def _seed_where(app, frm, to, value_diff, relocates):
    for i in range(6000):
        seed = "seek-{}".format(i)
        if (_render_wheel(app, frm, to, seed, value_diff) != to) == relocates:
            return seed
    raise AssertionError("no seed found")


def test_wheel_relocates_to_a_random_on_board_square():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    target = _render_wheel(app, frm, to, _seed_where(app, frm, to, 8, relocates=True))
    assert target != to
    assert 0 <= target.row < BOARD_SIZE and 0 <= target.col < BOARD_SIZE


def test_wheel_can_still_spawn_on_the_capture_square():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    assert _render_wheel(app, frm, to, _seed_where(app, frm, to, 8, relocates=False)) == to


def test_relocated_wheel_never_lands_on_the_from_or_to_square():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    relocated = [t for i in range(400)
                 if (t := _render_wheel(app, frm, to, "avoid-{}".format(i))) != to]
    assert relocated, "at p=0.9 plenty of seeds relocate"
    assert all(t != frm and t != to for t in relocated), "only the move's own squares are excluded"


def test_relocated_wheel_may_sit_on_another_piece():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    landed_on_a_piece = any(
        (t := _render_wheel(app, frm, to, "onpiece-{}".format(i))) != to
        and app.game.match.piece_at(t) is not None for i in range(400))
    assert landed_on_a_piece, "bystander squares are fair game; only from/to are excluded"


def test_placement_excludes_only_the_from_and_to_squares():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_ep_capture(app)
    exclusions = app.game.skillcheck_session._placement_exclusions(frm, to)
    assert exclusions == {(frm.row, frm.col), (to.row, to.col)}


def test_gate_target_matches_the_pure_engine_placement():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    for i in range(200):
        seed = "match-{}".format(i)
        exclusions = app.game.skillcheck_session._placement_exclusions(frm, to)
        engine = placement_square(seed, 8, exclusions, BOARD_SIZE)
        target = _render_wheel(app, frm, to, seed)
        assert target == (to if engine is None else Square(engine[0], engine[1]))


def test_wheel_placement_is_deterministic_across_app_instances():
    one = Frontend(1100, 800)
    _start_local(one)
    f1, t1 = _set_queen_takes_pawn(one)
    two = Frontend(1100, 800)
    _start_local(two)
    f2, t2 = _set_queen_takes_pawn(two)
    assert _render_wheel(one, f1, t1, "same") == _render_wheel(two, f2, t2, "same")


def test_steady_aim_never_relocates_even_for_a_lopsided_trade():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    for i in range(200):
        assert app.game.skillcheck_session._skillcheck_render_square(
            SkillCheckKind.AIM, "aim-{}".format(i), 8, frm, to) == to


def _wheel_seed_that_relocates(app, frm, to):
    for i in range(8000):
        seed = "wp{}".format(i)
        roll = ply_roll(seed, move_roll_key(len(app.game.match.move_history), frm, to))
        if select_skillcheck(app.game.match.backend, frm, to, roll) != SkillCheckKind.WHEEL:
            continue
        app.game.skillcheck.reset(enabled=True, seed=seed)
        app.game.skillcheck_session.teardown_skillcheck_overlay()
        app.game.skillcheck_session.skillcheck_gate(frm, to)
        relocated = app.game.skillcheck_session.skillcheck_target != to
        app.game.skillcheck_session.teardown_skillcheck_overlay()
        if relocated:
            return seed
    raise AssertionError("no relocating wheel seed")


def test_relocated_wheel_positions_the_dial_there_and_draws():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed_that_relocates(app, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    target = app.game.skillcheck_session.skillcheck_target
    assert target != to
    ctrl = app.game.skillcheck_overlay._controller
    assert isinstance(ctrl, WheelController)
    assert ctrl.center == app.game.board.cell_rect(target).center
    assert app.game.board.aim_suppressed_square is None, "a wheel never suppresses a live square"
    app.draw_frame()


def test_relocated_wheel_win_applies_the_original_capture():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed_that_relocates(app, frm, to))
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    assert app.game.skillcheck_session.skillcheck_target != to, \
        "the dial relocated away from the capture square"
    assert app.game.skillcheck_overlay._context[:3] == (frm, to, None), \
        "the move context keeps real squares"
    app.game.skillcheck_session._on_skillcheck_done(app.game.skillcheck_overlay._context, True)
    assert len(app.game.match.move_history) == 1
    assert app.game.match.piece_at(to).type == PieceType.QUEEN, \
        "the real capture lands on the victim"


def test_queen_promotion_scores_value_like_a_pawn_taking_a_queen():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    assert app.game.skillcheck_session._capture_value_diff(frm, to, PieceType.QUEEN) == -8
    assert app.game.skillcheck_session._capture_value_diff(frm, to, PieceType.KNIGHT) == -2


def test_capturing_promotion_value_diff_uses_the_promoted_piece_not_the_capture():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_capture_promo(app)
    assert app.game.skillcheck_session._capture_value_diff(frm, to, PieceType.QUEEN) == -8, \
        "a pawn taking a rook and promoting to a queen scores by the queen, not the rook"


def test_queen_promotion_wheel_rarely_relocates():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    relocated = sum(
        _render_wheel(app, frm, to, "pr{}".format(i), value_diff=-8) != to for i in range(2000))
    assert 0 < relocated < 400, "a queen promotion relocates roughly a tenth of the time"


def test_premoved_capture_defers_into_the_skillcheck():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _shootout_with_wheel(app)
    app.game.board.premoves = [Premove(frm, to, app.game.match.piece_at(frm))]
    app.game.board.premove_color = app.game.match.current_turn()
    fired = app.game.board.try_apply_next_premove()
    assert fired is False, "a premove that triggers a skill-check does not apply silently"
    assert app.game.skillcheck_overlay.is_active() is True, "it defers into the wheel overlay"
    assert app.game.board.premoves == [], "the lone premove is consumed into the skill-check"
    assert len(app.game.match.move_history) == 0, "no ply lands until the skill-check resolves"


def test_premove_chain_survives_a_won_skillcheck():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _shootout_with_wheel(app)
    follow = Premove(Square(7, 4), Square(6, 4), app.game.match.piece_at(Square(7, 4)))
    app.game.board.premoves = [Premove(frm, to, app.game.match.piece_at(frm)), follow]
    app.game.board.premove_color = app.game.match.current_turn()
    app.game.board.try_apply_next_premove()
    assert app.game.skillcheck_overlay.is_active() is True
    assert app.game.board.premoves == [follow], "the rest of the chain survives the deferral"
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), True)
    assert len(app.game.match.move_history) == 1, "the won move lands"
    assert app.game.board.premoves == [follow], "and the chain lives on for the next turn"


def test_premove_chain_is_dropped_on_a_failed_skillcheck():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _shootout_with_wheel(app)
    follow = Premove(Square(7, 4), Square(6, 4), app.game.match.piece_at(Square(7, 4)))
    app.game.board.premoves = [Premove(frm, to, app.game.match.piece_at(frm)), follow]
    app.game.board.premove_color = app.game.match.current_turn()
    app.game.board.try_apply_next_premove()
    assert app.game.board.premoves == [follow]
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), False)
    assert len(app.game.match.move_history) == 0, "the failed move does not land"
    assert app.game.skillcheck.is_locked(frm, to) is True
    assert app.game.board.premoves == [], "a failed skill-check drops the rest of the chain"


def test_failed_click_move_skillcheck_keeps_opponents_premove():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    opp = Premove(Square(0, 4), Square(0, 5), app.game.match.piece_at(Square(0, 4)))
    app.game.board.premoves = [opp]
    app.game.board.premove_color = PieceColor.BLACK
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), False)
    assert app.game.board.premoves == [opp], \
        "a failed skill-check must not wipe the opponent's premove"
    assert app.game.skillcheck.is_locked(frm, to) is True


def _aim_seed(backend, frm, to):
    for i in range(3000):
        seed = "a{}".format(i)
        roll = ply_roll(seed, move_roll_key(0, frm, to))
        if select_skillcheck(backend, frm, to, roll) == SkillCheckKind.AIM:
            return seed
    raise AssertionError("no aim seed")


def _set_white_ep_capture(app):
    b = app.game.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[3][4] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.state[3][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    b.turn = PieceColor.WHITE
    b.en_passant_target = Square(2, 3)
    b.move_history = []
    b.position_counts = Counter()
    b.position_counts[b._position_key()] = 1
    return Square(3, 4), Square(2, 3)


def test_shootout_aim_capture_targets_the_victim_square():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_aim_seed(app.game.match.backend, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    assert app.game.skillcheck_overlay.is_active() is True
    assert isinstance(app.game.skillcheck_overlay._controller, AimController)
    assert app.game.skillcheck_session.skillcheck_target == to, \
        "the aim renders over the victim square"
    assert app.game.board.aim_suppressed_square == to, "the live victim is hidden so it can't ghost"


def test_aim_capture_targets_the_en_passant_pawn():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_ep_capture(app)
    app.game.skillcheck.reset(enabled=True, seed=_aim_seed(app.game.match.backend, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    assert app.game.skillcheck_session.skillcheck_target == Square(3, 3), \
        "aim renders over the EP pawn, not empty cell"
    assert app.game.board.aim_suppressed_square == Square(3, 3)


def test_won_aim_capture_applies_the_move_and_clears_suppress():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_aim_seed(app.game.match.backend, frm, to))
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    assert app.game.board.aim_suppressed_square == to
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.AIM), True)
    assert len(app.game.match.move_history) == 1
    assert app.game.match.piece_at(to).type == PieceType.QUEEN
    assert app.game.board.aim_suppressed_square is None, \
        "the suppress lifts when the check resolves"


def test_failed_aim_clears_suppress_and_swears():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_aim_seed(app.game.match.backend, frm, to))
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.AIM), False)
    assert app.game.board.aim_suppressed_square is None
    assert app.game.skillcheck.is_locked(frm, to) is True
    assert any(p.get("kind") == "tag" for p in app.game.board.effects.particles)


def test_every_failed_check_makes_the_piece_swear():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), False)
    fx = app.game.board.effects
    assert any(p.get("kind") == "tag" for p in fx.particles), "a failed wheel curses too"


def test_failed_capture_swear_floats_over_the_attacker_not_the_victim():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.board.trigger_skillcheck_fail(frm, to)
    tags = [p for p in app.game.board.effects.particles if p.get("kind") == "tag"]
    assert tags, "a failed capture swears"
    assert all(t["victim_sq"] == frm for t in tags), "the shooter (capturer) curses, not the victim"


def test_aim_miss_swear_floats_over_the_attacker():
    ctrl = AimController(_aim_centerable(), pg.Rect(0, 0, 80, 80), now_ms=0,
                         geom=lambda sq: (sq.col * 80 + 40, sq.row * 80 + 40),
                         from_sq=Square(6, 4), victim_sq=Square(3, 3), attacker_type="queen")
    ctrl.update(10)
    ctrl.handle_event(_tap())
    tags = [p for p in ctrl._fx.particles if p.get("kind") == "tag"]
    assert tags, "a miss spawns a swear"
    assert tags[0]["victim_sq"] == Square(6, 4), "the shooter swears, not the target piece"


def test_failed_aim_drops_the_surviving_piece_back_in():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_aim_seed(app.game.match.backend, frm, to))
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    assert app.game.board.aim_suppressed_square == to
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.AIM), False)
    assert any(a["sq"] == to for a in app.game.board._restore_anims), \
        "a failed aim drops the surviving victim back onto its square"


def test_failed_wheel_never_drops_a_piece_in():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed(app.game.match.backend, frm, to))
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    assert app.game.board.aim_suppressed_square is None, "a wheel never suppresses the live piece"
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, None, SkillCheckKind.WHEEL), False)
    assert app.game.board._restore_anims == [], \
        "the wheel piece never left, so nothing falls back in"


def test_restore_piece_schedules_then_self_clears():
    app = Frontend(1100, 800)
    _start_local(app)
    _set_queen_takes_pawn(app)
    app.game.board.restore_piece(Square(3, 3))
    assert len(app.game.board._restore_anims) == 1
    app.game.board._restore_anims[0]["start"] -= 10_000
    app.game.board.draw_board()
    assert app.game.board._restore_anims == [], "the restore animation self-clears once it finishes"


def test_cancel_animations_clears_restores():
    app = Frontend(1100, 800)
    _start_local(app)
    _set_queen_takes_pawn(app)
    app.game.board.restore_piece(Square(3, 3))
    app.game.board.cancel_animations()
    assert app.game.board._restore_anims == [], "a hard reset drops any in-flight restore"


def test_restore_state_falls_fades_then_bounces_and_rocks_to_upright():
    from chessshootout.frontend.board import board as B
    dy0, a0, ang0 = B.Board._restore_state(0.0)
    assert dy0 == pytest.approx(-B.RESTORE_DROP_FRAC), "starts a full drop above the square"
    assert a0 == 0, "and fully transparent"
    assert ang0 == 0.0, "upright while it falls"
    dy_land, a_land, ang_land = B.Board._restore_state(B.RESTORE_FALL_PORTION)
    assert dy_land == pytest.approx(0.0), "touches the tile floor at the end of the fall"
    assert a_land == 255, "fully faded in by the time it lands"
    assert ang_land == pytest.approx(0.0), "upright at the instant of impact"
    just_after = B.RESTORE_FALL_PORTION + (1.0 - B.RESTORE_FALL_PORTION) * 0.12
    dy_hop, _, ang_hop = B.Board._restore_state(just_after)
    assert dy_hop < 0.0, "it springs back up off the floor when it lands"
    assert ang_hop != 0.0, "and tips on its base, trying to balance"
    dy_end, _, ang_end = B.Board._restore_state(0.999)
    assert abs(dy_end) < B.RESTORE_REBOUND_FRAC * 0.25, "the bounce decays to standing upright"
    assert abs(ang_end) < B.RESTORE_ROCK_DEG * 0.25, "and the rock settles back to upright"


def _set_white_pawn_promo(app):
    b = app.game.match.backend
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
    app.game.skillcheck.reset(enabled=True, seed="seed")
    app.game.board.handle_click(frm)
    app.game.board.handle_click(to)
    assert app.game.board.pending_promotion_square == to, "the piece picker comes up first"
    assert app.game.board._promotion_from == frm
    assert app.game.match.piece_at(frm) is not None, "nothing is applied until a piece is chosen"
    assert app.game.match.piece_at(to) is None


def test_shootout_promotion_always_fires_the_wheel():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.game.skillcheck.reset(enabled=True, seed="anything")
    app.game.board.handle_click(frm)
    app.game.board.handle_click(to)
    app.game.board.pick_promotion(PieceType.ROOK)
    assert app.game.skillcheck_overlay.is_active() is True, "promotions are 100% wheel now"
    assert len(app.game.match.move_history) == 0, "nothing applies until the wheel resolves"


def test_failed_promotion_skillcheck_promotes_nothing():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.game.skillcheck.reset(
        enabled=True,
        seed=_promo_seed(app.game.match.backend, frm, to, SkillCheckKind.WHEEL))
    app.game.board.handle_click(frm)
    app.game.board.handle_click(to)
    app.game.board.pick_promotion(PieceType.ROOK)
    assert app.game.skillcheck_overlay.is_active() is True
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, PieceType.ROOK, SkillCheckKind.WHEEL), False)
    assert app.game.match.piece_at(frm).type == PieceType.PAWN, "a failed wheel promotes to nothing"
    assert app.game.match.piece_at(to) is None
    assert app.game.skillcheck.is_locked(frm, to) is True


def test_won_promotion_skillcheck_uses_the_chosen_piece():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.game.skillcheck.reset(
        enabled=True,
        seed=_promo_seed(app.game.match.backend, frm, to, SkillCheckKind.WHEEL))
    app.game.board.handle_click(frm)
    app.game.board.handle_click(to)
    app.game.board.pick_promotion(PieceType.ROOK)
    app.game.skillcheck_session._on_skillcheck_done(
        CheckContext(frm, to, PieceType.ROOK, SkillCheckKind.WHEEL), True)
    assert app.game.match.piece_at(to).type == PieceType.ROOK, \
        "a won wheel promotes to the chosen piece"


def _set_white_capture_promo(app):
    b = app.game.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][0] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[1][4] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.state[0][5] = Piece(PieceType.ROOK, PieceColor.BLACK)
    b.turn = PieceColor.WHITE
    b.move_history = []
    b.position_counts = Counter()
    b.position_counts[b._position_key()] = 1
    return Square(1, 4), Square(0, 5)


def test_capturing_promotion_rolling_aim_shows_the_picker_first():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_capture_promo(app)
    app.game.skillcheck.reset(enabled=True, seed=_aim_seed(app.game.match.backend, frm, to))
    app.game.board.handle_click(frm)
    app.game.board.handle_click(to)
    assert app.game.board.pending_promotion_square == to, "the piece picker still comes up first"
    assert app.game.skillcheck_overlay.is_active() is False, "nothing fires until a piece is chosen"
    app.game.board.pick_promotion(PieceType.QUEEN)
    assert app.game.skillcheck_overlay.is_active() is True
    assert isinstance(app.game.skillcheck_overlay._controller, AimController)
    assert app.game.skillcheck_session.skillcheck_target == to, \
        "the aim renders over the captured piece"


def test_wheel_period_scales_with_capture_material():
    from chessshootout.skillcheck.wheel import WHEEL_PERIOD_MS, period_for_diff
    app = Frontend(1100, 800)
    _start_local(app)
    b = app.game.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][0] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[4][3] = Piece(PieceType.QUEEN, PieceColor.WHITE)
    b.state[3][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    qxp_diff = app.game.skillcheck_session._capture_value_diff(Square(4, 3), Square(3, 3), None)
    qxp = period_for_diff(qxp_diff)
    b.state[4][3] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.state[3][2] = Piece(PieceType.QUEEN, PieceColor.BLACK)
    pxq_diff = app.game.skillcheck_session._capture_value_diff(Square(4, 3), Square(3, 2), None)
    pxq = period_for_diff(pxq_diff)
    assert qxp < WHEEL_PERIOD_MS < pxq, "strong-eats-weak spins faster, weak-eats-strong slower"


def test_promotion_wheel_period_uses_the_chosen_piece():
    from chessshootout.skillcheck.wheel import period_for_diff
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    queen = period_for_diff(
        app.game.skillcheck_session._capture_value_diff(frm, to, PieceType.QUEEN))
    knight = period_for_diff(
        app.game.skillcheck_session._capture_value_diff(frm, to, PieceType.KNIGHT))
    assert queen == pytest.approx(period_for_diff(-8)), "queen promotion scores like pawn x queen"
    assert knight == pytest.approx(period_for_diff(-2))
    assert queen > knight, "promoting to a queen is the easiest (slowest) wheel"


def test_failed_non_capturing_promotion_bumps_instead_of_shooting():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_white_pawn_promo(app)
    app.game.board.trigger_skillcheck_fail(frm, to)
    assert any(a.bump for a in app.game.board.animations), "a quiet promotion lunges and bumps back"
    assert app.game.board.effects.captures == [], "and never fires the gun (no victim to shoot)"


def test_failed_capture_still_fires_the_gun_miss_not_a_bump():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.board.trigger_skillcheck_fail(frm, to)
    assert app.game.board.effects.captures, "a failed capture still fires the gun"
    assert not any(a.bump for a in app.game.board.animations), "no bump when there is a victim"


def test_undo_clears_skillcheck_locks():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.lock(Square(4, 3), Square(3, 3))
    assert len(app.game.skillcheck.locks) == 1
    app.game._on_undo()
    assert len(app.game.skillcheck.locks) == 0, "a stale lock must not survive an undo"


def test_reset_to_new_game_tears_down_skillcheck_state():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.lock(Square(4, 3), Square(3, 3))
    ctrl = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), now_ms=0)
    app.game.skillcheck_overlay.start(ctrl, (Square(4, 3), Square(3, 3)), lambda c, landed: None)
    app.game._reset_to_new_game()
    assert app.game.skillcheck_overlay.is_active() is False, "reset cancels any in-flight overlay"
    assert len(app.game.skillcheck.locks) == 0, "reset clears the lock set"


def test_game_over_cancels_active_wheel_without_firing_its_move():
    app = Frontend(1100, 800)
    _start_local(app)
    landed = []
    ctrl = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), now_ms=0)
    app.game.skillcheck_overlay.start(
        ctrl, (Square(4, 3), Square(3, 3)), lambda c, won: landed.append(won))
    app.game.manual_result = "white_wins_by_resignation"
    app.draw_frame()
    assert app.game.skillcheck_overlay.is_active() is False, \
        "the wheel is cancelled when the game ends"
    assert landed == [], "its on_done never fires a stale move into the finished game"


def test_skillcheck_miss_aims_at_the_en_passant_pawn():
    app = Frontend(1100, 800)
    _start_local(app)
    b = app.game.match.backend
    b._reset_state()
    b.state[7][4] = Piece(PieceType.KING, PieceColor.WHITE)
    b.state[0][4] = Piece(PieceType.KING, PieceColor.BLACK)
    b.state[3][4] = Piece(PieceType.PAWN, PieceColor.WHITE)
    b.state[3][3] = Piece(PieceType.PAWN, PieceColor.BLACK)
    b.turn = PieceColor.WHITE
    app.game.board.trigger_skillcheck_fail(Square(3, 4), Square(2, 3))
    caps = app.game.board.effects.captures
    assert caps, "the miss FX scheduled a gun choreography"
    assert caps[0]["victim_sq"] == Square(3, 3), "the gun aims at the EP pawn, not the empty cell"


def test_wheel_relayouts_when_the_board_moves():
    app = Frontend(1100, 800)
    _start_local(app)
    to_sq = Square(3, 3)
    ctrl = WheelController(WheelChallenge.from_seed("x"), app.game.board.cell_rect(to_sq), now_ms=0)
    app.game.skillcheck_overlay.start(ctrl, (Square(4, 3), to_sq), lambda c, landed: None)
    app.game.skillcheck_session.skillcheck_target = to_sq
    before = ctrl.center
    app.window = pg.Surface((1700, 1100))
    app._compute_layout()
    assert ctrl.center == app.game.board.cell_rect(to_sq).center, \
        "the dial re-anchors to the square"
    assert ctrl.center != before, "a resize actually moved it"


def test_premoved_quiet_move_still_fires_normally_in_shootout():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed="seed")
    quiet_from, quiet_to = Square(7, 4), Square(6, 4)
    app.game.board.premoves = [Premove(quiet_from, quiet_to, app.game.match.piece_at(quiet_from))]
    app.game.board.premove_color = app.game.match.current_turn()
    fired = app.game.board.try_apply_next_premove()
    assert fired is True, "a non-triggering premove applies as before"
    assert app.game.skillcheck_overlay.is_active() is False
    assert len(app.game.match.move_history) == 1


def test_landed_ply_clears_locks():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.lock(Square(7, 4), Square(6, 4))
    app.game.match.try_move(Square(4, 3), Square(3, 3))
    app.game._on_move_landed(app.game.match.move_history[-1])
    assert len(app.game.skillcheck.locks) == 0


def test_board_marks_locked_target():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.lock(frm, to)
    app.game.board.selected_square = frm
    assert app.game.board._is_target_locked(to) is True
    assert app.game.board._is_target_locked(Square(5, 3)) is False


def test_local_won_wheel_logs_the_outcome_for_pgn():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed(app.game.match.backend, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    app.game.skillcheck_session._on_skillcheck_done(app.game.skillcheck_overlay._context, True)
    assert app.game.skillcheck_session.skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]
    assert format_annotations(app.game.skillcheck_session.skillcheck_log) == {1: "Wheel ✓"}


def test_local_failed_wheel_logs_the_whiffed_move_san():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed(app.game.match.backend, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    app.game.skillcheck_session._on_skillcheck_done(app.game.skillcheck_overlay._context, False)
    assert app.game.skillcheck_session.skillcheck_log == [
        SkillCheckOutcome(1, "wheel", False, "Qxd5")]
    assert len(app.game.match.move_history) == 0, "a failed check lands no ply"
    assert format_annotations(app.game.skillcheck_session.skillcheck_log) == {1: "Wheel ✗ Qxd5"}


def test_local_won_check_lands_in_the_saved_pgn_text():
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = _set_queen_takes_pawn(app)
    app.game.skillcheck.reset(enabled=True, seed=_wheel_seed(app.game.match.backend, frm, to))
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    app.game.skillcheck_session._on_skillcheck_done(app.game.skillcheck_overlay._context, True)
    app.game.manual_result = "white_wins_by_resignation"
    text = app.game.result_flow._build_pgn_text()
    assert "1. Qxd5 {Wheel ✓}" in text


def test_undo_drops_only_the_undone_ply_and_dangling_fail():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    app.game.match.backend.apply_san("e4")
    app.game.match.backend.apply_san("e5")
    app.game.skillcheck_session.skillcheck_log = [
        SkillCheckOutcome(1, "wheel", True, ""),
        SkillCheckOutcome(2, "aim", True, ""),
        SkillCheckOutcome(3, "wheel", False, "Nxe4"),
    ]
    app.game._on_undo()
    assert len(app.game.match.move_history) == 1
    assert app.game.skillcheck_session.skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "")]


def test_reset_to_new_game_clears_the_skillcheck_log():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck_session.skillcheck_log = [SkillCheckOutcome(1, "wheel", True, "")]
    app.game._reset_to_new_game()
    assert app.game.skillcheck_session.skillcheck_log == []


def test_teardown_clears_the_full_online_overlay_tracking_set():
    """Teardown must null EVERY overlay-tracking field, not the scattered subset it used to.
    Before the divergence fix it left _online_skillcheck / _online_spectate_kind set, so a
    later result still thought a check was open."""
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = Square(4, 3), Square(3, 3)
    app.game.skillcheck_session.skillcheck_target = to
    app.game.skillcheck_session.online_skillcheck = (frm, to, None, SkillCheckKind.WHEEL)
    app.game.skillcheck_session.online_spectate_kind = SkillCheckKind.AIM
    app.game.skillcheck_session.online_skillcheck_opened_ms = 12345
    app.game.skillcheck_session.online_verdict_action = lambda: None
    app.game.board.aim_suppressed_square = to
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    assert app.game.skillcheck_session.skillcheck_target is None
    assert app.game.skillcheck_session.online_skillcheck is None
    assert app.game.skillcheck_session.online_spectate_kind is None
    assert app.game.skillcheck_session.online_skillcheck_opened_ms is None
    assert app.game.skillcheck_session.online_verdict_action is None
    assert app.game.board.aim_suppressed_square is None


def test_clear_online_skillcheck_state_resets_all_six_transient_fields():
    """The dedicated reset clears all six transient online fields including the held pending
    move that teardown deliberately leaves alone."""
    app = Frontend(1100, 800)
    _start_local(app)
    frm, to = Square(4, 3), Square(3, 3)
    app.game.skillcheck_session.skillcheck_target = to
    app.game.skillcheck_session.pending_online_move = (frm, to, None)
    app.game.skillcheck_session.online_skillcheck = (frm, to, None, SkillCheckKind.WHEEL)
    app.game.skillcheck_session.online_spectate_kind = SkillCheckKind.AIM
    app.game.skillcheck_session.online_skillcheck_opened_ms = 999
    app.game.skillcheck_session.online_verdict_action = lambda: None
    app.game.skillcheck_session.clear_online_skillcheck_state()
    assert app.game.skillcheck_session.skillcheck_target is None
    assert app.game.skillcheck_session.pending_online_move is None
    assert app.game.skillcheck_session.online_skillcheck is None
    assert app.game.skillcheck_session.online_spectate_kind is None
    assert app.game.skillcheck_session.online_skillcheck_opened_ms is None
    assert app.game.skillcheck_session.online_verdict_action is None


def test_skillcheck_whiffs_lists_only_fails_grouped_by_ply():
    app = Frontend(1100, 800)
    app.game.skillcheck_session.skillcheck_log = [
        SkillCheckOutcome(3, "wheel", True, ""),
        SkillCheckOutcome(5, "wheel", False, "Qxd6"),
        SkillCheckOutcome(5, "aim", False, "Rxd6"),
        SkillCheckOutcome(7, "aim", True, ""),
    ]
    assert app.game.skillcheck_session.skillcheck_whiffs() == {
        5: [("Wheel", "Qxd6"), ("Steady-Aim", "Rxd6")]}, "wins excluded, fails grouped"


def test_move_rows_insert_a_whiff_row_after_the_pair_that_whiffed():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        app.game.match.backend.apply_san(san)
    rows = app.game.right_menu._move_rows(
        app.game.match.move_history, {3: [("Wheel", "Qxd6")]})
    assert [r[0] for r in rows] == ["pair", "pair", "whiff"]
    assert rows[2] == ("whiff", ("Wheel", "Qxd6"), None), "ply 3 is white of the 2nd pair"


def test_multiple_whiffs_one_ply_stack_one_per_row():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        app.game.match.backend.apply_san(san)
    rows = app.game.right_menu._move_rows(
        app.game.match.move_history, {3: [("Wheel", "Qxa2"), ("Steady-Aim", "Qxd4")]})
    assert [r[0] for r in rows] == ["pair", "pair", "whiff", "whiff"]
    assert rows[2] == ("whiff", ("Wheel", "Qxa2"), None)
    assert rows[3] == ("whiff", ("Steady-Aim", "Qxd4"), None)


def test_no_whiffs_means_no_extra_rows():
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5"]:
        app.game.match.backend.apply_san(san)
    rows = app.game.right_menu._move_rows(app.game.match.move_history, {})
    assert [r[0] for r in rows] == ["pair"]


def test_black_only_whiff_row_has_an_empty_white_slot():
    """A whiff on a black ply (ply 4 = black of the 2nd pair) renders the (label, san) in the
    black slot and None in the white slot — the slot positioning, not just the presence."""
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        app.game.match.backend.apply_san(san)
    rows = app.game.right_menu._move_rows(
        app.game.match.move_history, {4: [("Steady-Aim", "Rxe5")]})
    assert [r[0] for r in rows] == ["pair", "pair", "whiff"]
    assert rows[2] == ("whiff", None, ("Steady-Aim", "Rxe5"))


def test_both_sides_whiff_same_pair_share_one_row():
    """A white whiff (ply 3) and a black whiff (ply 4) on the same pair collapse into a single
    whiff row carrying both slots — not two stacked rows."""
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        app.game.match.backend.apply_san(san)
    rows = app.game.right_menu._move_rows(
        app.game.match.move_history, {3: [("Wheel", "Qxd5")], 4: [("Steady-Aim", "Rxe5")]})
    assert [r[0] for r in rows] == ["pair", "pair", "whiff"]
    assert rows[2] == ("whiff", ("Wheel", "Qxd5"), ("Steady-Aim", "Rxe5"))


def test_whiff_on_a_non_final_pair_offsets_the_following_pairs_row_index():
    """A whiff inserted after the first pair pushes the second pair down a row; _pair_to_row
    must follow that offset so a later pair still maps to its real render row (not its index)."""
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6"]:
        app.game.match.backend.apply_san(san)
    rows = app.game.right_menu._move_rows(
        app.game.match.move_history, {1: [("Wheel", "Qxd5")]})
    assert [r[0] for r in rows] == ["pair", "whiff", "pair"]
    assert rows[1] == ("whiff", ("Wheel", "Qxd5"), None), "ply 1 is white of the 1st pair"
    assert app.game.right_menu._pair_to_row == {0: 0, 1: 2}, \
        "the 2nd pair shifts past the whiff row"
    second = rows[app.game.right_menu._pair_to_row[1]]
    assert second[0] == "pair" and second[1] == 1, "_pair_to_row[1] lands on the 2nd pair row"


def test_loading_a_pgn_with_a_miss_populates_review_whiffs(tmp_path):
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6", "Bb5"]:
        app.game.match.backend.apply_san(san)
    app.game.skillcheck_session.skillcheck_log = [SkillCheckOutcome(5, "aim", False, "Bxc6")]
    app.game.manual_result = "white_wins_by_resignation"
    text = app.game.result_flow._build_pgn_text()
    path = tmp_path / "g.pgn"
    path.write_text(text, encoding="utf-8")
    app2 = Frontend(1100, 800)
    app2._open_pgn_review(str(path))
    app2._execute_pending_nav()
    assert app2.review._skillcheck_whiffs() == {5: [("Steady-Aim", "Bxc6")]}


def test_two_event_ply_round_trips_through_the_saved_pgn_file(tmp_path):
    """A single ply can carry two outcomes (a whiffed wheel + a landed steady-aim). They share
    one ' · '-joined comment in the file; reloading must split it back into BOTH outcomes,
    proving the separator is unambiguous through real file text."""
    app = Frontend(1100, 800)
    _start_local(app)
    app.game.skillcheck.reset(enabled=False)
    for san in ["e4", "e5", "Nf3", "Nc6", "Bb5"]:
        app.game.match.backend.apply_san(san)
    app.game.skillcheck_session.skillcheck_log = [
        SkillCheckOutcome(4, "wheel", False, "Rxe5"),
        SkillCheckOutcome(4, "aim", True, ""),
    ]
    app.game.manual_result = "white_wins_by_resignation"
    text = app.game.result_flow._build_pgn_text()
    assert "Wheel ✗ Rxe5 · Steady-Aim ✓" in text, "both events join with the dot separator"
    path = tmp_path / "two.pgn"
    path.write_text(text, encoding="utf-8")
    app2 = Frontend(1100, 800)
    app2._open_pgn_review(str(path))
    app2._execute_pending_nav()
    assert app2.review._skillcheck_log == [
        SkillCheckOutcome(4, "wheel", False, "Rxe5"),
        SkillCheckOutcome(4, "aim", True, ""),
    ], "the reloaded log reconstructs both events on ply 4"


def test_local_skillcheck_deadline_is_tc_capped():
    app = Frontend(1100, 800)
    app.game._time_control = (300, 0)
    assert app.game.skillcheck_session._skillcheck_deadline_ms() == 5000, "5+0 -> the 5s base"
    app.game._time_control = (40, 0)
    assert app.game.skillcheck_session._skillcheck_deadline_ms() == 4000, "a 40s game -> 10% = 4s"
    app.game._time_control = None
    assert app.game.skillcheck_session._skillcheck_deadline_ms() == 5000, "no clock -> the base"


def _cued_wheel(audio=None, *, passive=False, on_shot=None):
    if audio is None:
        audio = MagicMock()
    return WheelController(_always_in_arc(), pg.Rect(0, 0, 80, 80), now_ms=0,
                           on_shot=on_shot, passive=passive, audio=audio)


def _cued_aim(audio=None, *, passive=False, on_shot=None, miss_count=0):
    if audio is None:
        audio = MagicMock()
    return AimController(AimChallenge.from_seed("seed-aim", 0), pg.Rect(0, 0, 80, 80),
                         now_ms=0, on_shot=on_shot, passive=passive, audio=audio,
                         miss_count=miss_count)


def test_wheel_plays_appear_ding_once_at_ctor():
    audio = MagicMock()
    _cued_wheel(audio)
    audio.play_skillcheck_appear.assert_called_once()
    audio.play_aim_lock.assert_not_called()


def test_aim_plays_lock_ding_once_at_ctor_not_appear():
    audio = MagicMock()
    _cued_aim(audio)
    audio.play_aim_lock.assert_called_once()
    audio.play_skillcheck_appear.assert_not_called()


def test_wheel_passive_ctor_makes_no_cue():
    audio = MagicMock()
    _cued_wheel(audio, passive=True)
    audio.play_skillcheck_appear.assert_not_called()


def test_aim_passive_ctor_makes_no_cue():
    audio = MagicMock()
    _cued_aim(audio, passive=True)
    audio.play_aim_lock.assert_not_called()


def test_wheel_tick_fires_once_per_arc_entry():
    audio = MagicMock()
    c = _cued_wheel(audio)
    audio.reset_mock()
    seq = iter([False, True, True, False, True])
    stub = MagicMock()
    stub.needle_deg.return_value = 0.0
    stub.in_arc_at.side_effect = lambda deg, elapsed: next(seq)
    c.challenge = stub
    for t in range(1, 6):
        c.update(t)
    assert audio.play_wheel_tick.call_count == 2


def test_aim_beep_fires_once_per_target_entry():
    audio = MagicMock()
    c = _cued_aim(audio)
    audio.reset_mock()
    seq = iter([False, True, True, False, True])
    stub = MagicMock()
    stub.on_target.side_effect = lambda elapsed, miss: next(seq)
    stub.is_expired.return_value = False
    c.challenge = stub
    for t in range(1, 6):
        c.update(t)
    assert audio.play_aim_beep.call_count == 2


def test_wheel_local_commit_win_plays_win_once():
    audio = MagicMock()
    c = _cued_wheel(audio)
    audio.reset_mock()
    c._commit(True)
    audio.play_skillcheck_win.assert_called_once()
    audio.play_skillcheck_miss.assert_not_called()


def test_wheel_local_commit_miss_plays_miss_once():
    audio = MagicMock()
    c = _cued_wheel(audio)
    audio.reset_mock()
    c._commit(False)
    audio.play_skillcheck_miss.assert_called_once()
    audio.play_skillcheck_win.assert_not_called()


def test_wheel_online_resolve_win_plays_win():
    audio = MagicMock()
    c = _cued_wheel(audio, on_shot=lambda e: None)
    audio.reset_mock()
    c.resolve(True)
    audio.play_skillcheck_win.assert_called_once()


def test_wheel_passive_resolve_is_silent():
    audio = MagicMock()
    c = _cued_wheel(audio, passive=True)
    audio.reset_mock()
    c.resolve(True)
    audio.play_skillcheck_win.assert_not_called()
    audio.play_skillcheck_miss.assert_not_called()


def test_aim_expiry_plays_miss_once():
    audio = MagicMock()
    c = _cued_aim(audio)
    audio.reset_mock()
    stub = MagicMock()
    stub.on_target.return_value = False
    stub.is_expired.return_value = True
    c.challenge = stub
    c.update(10)
    audio.play_skillcheck_miss.assert_called_once()
    audio.play_skillcheck_win.assert_not_called()


def test_aim_online_resolve_win_plays_win():
    audio = MagicMock()
    c = _cued_aim(audio, on_shot=lambda e: None)
    audio.reset_mock()
    c.resolve(True)
    audio.play_skillcheck_win.assert_called_once()


def test_aim_local_miss_shot_plays_swear_once():
    audio = MagicMock()
    c = _cued_aim(audio)
    audio.reset_mock()
    c._replay_miss(100, 0)
    audio.play_swear.assert_called_once()


def test_aim_online_miss_shot_plays_no_swear():
    audio = MagicMock()
    c = _cued_aim(audio, on_shot=lambda e: None)
    audio.reset_mock()
    c._replay_miss(100, 0)
    audio.play_swear.assert_not_called()


def test_aim_passive_miss_shot_is_silent():
    audio = MagicMock()
    c = _cued_aim(audio, passive=True)
    audio.reset_mock()
    c._replay_miss(100, 0)
    audio.play_swear.assert_not_called()


def test_aim_victim_scale_tracks_challenge():
    c = _cued_aim()
    assert c.victim_scale() == c.challenge.piece_scale(*c._render_state())


def test_local_timeout_after_a_miss_shows_gone_not_stale_shot():
    """Local aim: after firing a miss then timing out, the result-hold shows the
    expired (gone) piece, not a stale partial reappearance of the last shot."""
    c = _cued_aim()
    c._now = 500
    c._replay_miss(500, 0)
    assert c._shot_render is not None
    c.update(10_000)
    assert c._committed_at is not None and c._landed is False
    elapsed, miss = c._render_state()
    assert (elapsed, miss) != c._shot_render
    assert c.challenge.piece_scale(elapsed, miss) <= 0.02


def test_online_win_freezes_the_fired_shot():
    """An online WIN pins the piece to the shot moment (matches local's instant
    resolve) instead of the RTT-shrunk resolve moment."""
    c = _cued_aim(on_shot=lambda e: None)
    c._now = 500
    c._replay_miss(500, 0)
    c.resolve(True)
    assert c._render_state() == c._shot_render


def test_online_miss_shows_gone_not_stale_shot():
    """An online MISS looks the same as a local miss: the piece is gone, not a
    frozen partial reappearance of the last shot."""
    c = _cued_aim(on_shot=lambda e: None)
    c._now = 500
    c._replay_miss(500, 0)
    c._now = 10_000
    c.resolve(False)
    elapsed, miss = c._render_state()
    assert (elapsed, miss) != c._shot_render
    assert c.challenge.piece_scale(elapsed, miss) <= 0.02


def test_overlay_aim_victim_scale_passthrough():
    ov = SkillCheckOverlay()
    assert ov.aim_victim_scale() == 1.0
    ov._controller = _cued_wheel()
    assert ov.aim_victim_scale() == 1.0
    aim = _cued_aim()
    ov._controller = aim
    assert ov.aim_victim_scale() == aim.victim_scale()


def test_base_controller_carries_the_whole_overlay_contract():
    # The overlay used to getattr-probe close/set_board_rect/victim_scale/_passive
    # per call; the base class owns real no-op defaults now, so every concrete
    # controller answers the full surface and the overlay calls it directly. The
    # wheel (which overrides none of them) is the proof by inheritance.
    from chessshootout.frontend.skillcheck.controller import SkillCheckController
    base = SkillCheckController()
    assert base.passive is False
    assert base.victim_scale() == 1.0
    base.close()
    base.set_board_rect(pg.Rect(0, 0, 10, 10))
    ov = SkillCheckOverlay()
    assert ov.is_passive() is False and ov.aim_victim_scale() == 1.0
    ov.set_board_rect(pg.Rect(0, 0, 10, 10))
    ov._controller = _cued_wheel(passive=True)
    assert ov.is_passive() is True, "is_passive reads the public property, not a private probe"
    ov.set_board_rect(pg.Rect(0, 0, 10, 10))
    ov.cancel()
