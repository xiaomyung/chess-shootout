"""juice.py owns only the *damage* half of the whack choreography now: a torn
sprite is a pure function of (key, tier) and nothing else. The regrow buckets
that used to un-punch the notches step by step are gone — the fail heal is a
two-source composite built by the view (torn top / whole bottom, split at a
travelling seam), so juice never needs to know how far along a repair is.
"""

import inspect
import math

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.skillcheck import juice
from chessshootout.frontend.skillcheck.juice import (
    Trauma, Hitstop, sakurai_vibrate, ease_out_back, torn_sprite, flash_sprite,
    TRAUMA_DECAY_PER_S, HITSTOP_CAP_MS, TORN_MAX_TIER,
    _TORN_NOTCHES, _TORN_NOTCH_FRAC, _TORN_CRACKS, _TORN_CACHE, _torn_surface,
)


_pygame_init = pygame_display(200, 200)


def _piece_surface(size=48):
    # A synthetic piece-like sprite: a solid alpha core with a partial-alpha
    # halo. Every pixel we care about has alpha > 0 so "opaque pixel" counts
    # are meaningful. Owned entirely by this test (no real assets loaded).
    surf = pg.Surface((size, size), pg.SRCALPHA)
    c = size / 2.0
    core = size * 0.36
    halo = size * 0.44
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c)
            if d <= core:
                surf.set_at((x, y), (120, 160, 210, 255))
            elif d <= halo:
                surf.set_at((x, y), (120, 160, 210, 150))
    return surf


def _opaque_count(surf):
    w, h = surf.get_size()
    return sum(1 for x in range(w) for y in range(h) if surf.get_at((x, y))[3] > 0)


def _mean_rgb_of_opaque(surf):
    w, h = surf.get_size()
    total = [0, 0, 0]
    n = 0
    for x in range(w):
        for y in range(h):
            px = surf.get_at((x, y))
            if px[3] > 0:
                total[0] += px[0]
                total[1] += px[1]
                total[2] += px[2]
                n += 1
    return sum(total) / (3 * n)


# --- module constants -------------------------------------------------------

def test_named_defaults_are_the_live_tuned_values():
    """The tuned defaults are named constants so other modules can reference
    them; the constructors must keep defaulting to those exact values."""
    assert Trauma()._decay_per_s == TRAUMA_DECAY_PER_S
    assert Hitstop()._cap_ms == HITSTOP_CAP_MS


def test_torn_max_tier_covers_exactly_the_tier_tables():
    """TORN_MAX_TIER is public (the check views clamp damage tiers against it),
    so the per-tier tables must cover exactly tiers 1..TORN_MAX_TIER — a table
    edit that drifts from the constant is a silent KeyError at draw time."""
    expected = set(range(1, TORN_MAX_TIER + 1))
    assert set(_TORN_NOTCHES) == expected
    assert set(_TORN_NOTCH_FRAC) == expected
    assert set(_TORN_CRACKS) == expected


# --- Trauma -----------------------------------------------------------------

def test_trauma_add_clamps_to_one():
    t = Trauma()
    t.add(0.8)
    t.add(0.8)
    assert t.value == pytest.approx(1.0)


def test_trauma_add_floors_at_zero():
    t = Trauma()
    t.add(-5.0)
    assert t.value == 0.0


def test_trauma_decays_to_zero_over_time():
    t = Trauma(decay_per_s=1.5)
    t.add(1.0)
    t.update(0)          # first call initializes the timestamp, no decay
    assert t.value == pytest.approx(1.0)
    t.update(1000)       # 1.0 s * 1.5 decay -> clamped to 0
    assert t.value == 0.0


def test_trauma_partial_decay_is_linear():
    t = Trauma(decay_per_s=1.5)
    t.add(1.0)
    t.update(0)
    t.update(200)        # 0.2 s -> -0.30
    assert t.value == pytest.approx(0.7, abs=1e-6)


def test_trauma_offset_zero_at_zero_trauma():
    t = Trauma()
    assert t.offset(1234, 40.0) == (0.0, 0.0)
    assert t.roll_deg(1234, 8.0) == 0.0


def test_trauma_offset_bounded_by_max_at_full_trauma():
    t = Trauma()
    t.add(1.0)
    max_px = 30.0
    for now in range(0, 4000, 37):
        dx, dy = t.offset(now, max_px)
        assert abs(dx) <= max_px + 1e-9
        assert abs(dy) <= max_px + 1e-9


def test_trauma_roll_bounded_by_max_at_full_trauma():
    t = Trauma()
    t.add(1.0)
    for now in range(0, 4000, 37):
        assert abs(t.roll_deg(now, 9.0)) <= 9.0 + 1e-9


def test_trauma_offset_deterministic_for_same_state_and_now():
    a = Trauma()
    a.add(0.5)
    b = Trauma()
    b.add(0.5)
    assert a.offset(999, 20.0) == b.offset(999, 20.0)
    assert a.roll_deg(999, 5.0) == b.roll_deg(999, 5.0)


def test_trauma_offset_moves_with_time():
    t = Trauma()
    t.add(1.0)
    assert t.offset(100, 30.0) != t.offset(300, 30.0)


# --- Hitstop ----------------------------------------------------------------

def test_hitstop_frozen_inside_window_not_outside():
    h = Hitstop()
    h.trigger(1000, 120)
    assert h.frozen(1000) is True
    assert h.frozen(1119) is True
    assert h.frozen(1120) is False
    assert h.frozen(1200) is False


def test_hitstop_idle_is_never_frozen():
    h = Hitstop()
    assert h.frozen(0) is False


def test_hitstop_cap_enforced():
    h = Hitstop(cap_ms=250.0)
    h.trigger(0, 1000)      # requested 1000, capped to 250
    assert h.frozen(249) is True
    assert h.frozen(250) is False
    assert h.frozen(251) is False


def test_hitstop_overlapping_triggers_never_exceed_cap_horizon():
    h = Hitstop(cap_ms=250.0)
    h.trigger(0, 250)       # freeze until 250
    h.trigger(100, 250)     # extends, but only to 100 + 250 = 350
    assert h.frozen(349) is True
    assert h.frozen(350) is False
    # horizon measured from the latest trigger never exceeds the cap
    assert h.frozen(100 + 250) is False


def test_hitstop_overlap_extends_forward():
    h = Hitstop(cap_ms=250.0)
    h.trigger(0, 100)       # until 100
    h.trigger(50, 100)      # until 150 (extends past the first horizon)
    assert h.frozen(120) is True
    assert h.frozen(150) is False


# --- sakurai_vibrate --------------------------------------------------------

def test_sakurai_zero_outside_window():
    assert sakurai_vibrate(90, 100, 300, 10.0) == 0.0      # before start
    assert sakurai_vibrate(400, 100, 300, 10.0) == 0.0     # at/after end
    assert sakurai_vibrate(500, 100, 300, 10.0) == 0.0


def test_sakurai_zero_duration_is_silent():
    assert sakurai_vibrate(150, 100, 0, 10.0) == 0.0


def test_sakurai_bounded_by_amplitude():
    amp = 12.0
    for now in range(100, 500):
        assert abs(sakurai_vibrate(now, 100, 400, amp)) <= amp + 1e-9


def test_sakurai_envelope_decays():
    amp = 12.0
    start, dur = 0, 400
    early = max(abs(sakurai_vibrate(t, start, dur, amp)) for t in range(0, 100))
    late = max(abs(sakurai_vibrate(t, start, dur, amp)) for t in range(300, 400))
    assert late < early


# --- ease_out_back ----------------------------------------------------------

def test_ease_out_back_endpoints():
    assert ease_out_back(0.0) == pytest.approx(0.0, abs=1e-9)
    assert ease_out_back(1.0) == pytest.approx(1.0, abs=1e-9)


def test_ease_out_back_overshoots_above_one():
    peak = max(ease_out_back(i / 100.0) for i in range(0, 101))
    assert peak > 1.0


# --- torn_sprite ------------------------------------------------------------

def test_torn_tier_zero_returns_base_unchanged():
    base = _piece_surface()
    assert torn_sprite(base, ("p", "w", 48, 0), 0) is base


def test_torn_returns_new_surface_for_damaged_tiers():
    base = _piece_surface()
    for tier in (1, 2, 3):
        out = torn_sprite(base, ("p", "w", 48, tier), tier)
        assert out is not base
        assert out.get_size() == base.get_size()


def test_torn_opaque_pixels_strictly_decrease_with_tier():
    base = _piece_surface()
    base_n = _opaque_count(base)
    n1 = _opaque_count(torn_sprite(base, ("n", "w", 48, 1), 1))
    n2 = _opaque_count(torn_sprite(base, ("n", "w", 48, 2), 2))
    n3 = _opaque_count(torn_sprite(base, ("n", "w", 48, 3), 3))
    assert base_n > n1 > n2 > n3


def test_torn_cache_hit_returns_same_object():
    base = _piece_surface()
    key = ("b", "b", 48, 2)
    first = torn_sprite(base, key, 2)
    second = torn_sprite(base, key, 2)
    assert first is second


def test_torn_different_tiers_produce_different_pixels():
    base = _piece_surface()
    t1 = torn_sprite(base, ("q", "w", 48, 1), 1)
    t2 = torn_sprite(base, ("q", "w", 48, 2), 2)
    assert t1 is not t2
    w, h = base.get_size()
    differing = any(t1.get_at((x, y)) != t2.get_at((x, y))
                    for x in range(w) for y in range(h))
    assert differing


# --- flash_sprite -----------------------------------------------------------

def test_flash_same_size_and_opaque_count():
    base = _piece_surface()
    flashed = flash_sprite(base, ("k", "w", 48))
    assert flashed.get_size() == base.get_size()
    assert _opaque_count(flashed) == _opaque_count(base)


def test_flash_is_visibly_whiter():
    base = _piece_surface()
    flashed = flash_sprite(base, ("k", "b", 48))
    assert _mean_rgb_of_opaque(flashed) > _mean_rgb_of_opaque(base)


def test_flash_cache_hit_returns_same_object():
    base = _piece_surface()
    key = ("r", "w", 48)
    assert flash_sprite(base, key) is flash_sprite(base, key)


# --- the regrow buckets are gone --------------------------------------------

def test_torn_sprite_takes_no_regrow_argument():
    # The heal is a view-side composite over the *undamaged* source sprite now.
    # Keeping a regrow parameter here would mean two competing repair models and
    # a cache keyed on a number the view no longer owns.
    assert list(inspect.signature(torn_sprite).parameters) == ["base", "key", "tier"]
    assert list(inspect.signature(_torn_surface).parameters) == ["base", "key", "tier"]
    assert not hasattr(juice, "TORN_REGROW_STEPS")


def test_torn_cache_key_is_exactly_the_key_and_the_tier():
    # A stale third component in the key would strand every entry the view asks
    # for and rebuild the (expensive) punched surface on every frame.
    base = _piece_surface()
    key = ("cachekey", "w", 48)
    tier_one = torn_sprite(base, key, 1)
    tier_three = torn_sprite(base, key, 3)
    assert tier_one is not tier_three
    assert _TORN_CACHE[(key, 1)] is tier_one
    assert _TORN_CACHE[(key, 3)] is tier_three
    assert torn_sprite(base, key, 1) is tier_one


def test_torn_damage_is_seeded_by_the_key():
    base = _piece_surface()
    a = torn_sprite(base, ("seed-a", 48), 2)
    b = torn_sprite(base, ("seed-b", 48), 2)
    assert pg.image.tostring(a, "RGBA") != pg.image.tostring(b, "RGBA"), \
        "two checks never tear their victims the same way"


def test_torn_leaves_the_source_sprite_untouched():
    # The base is the board's shared piece image; the view composites the heal
    # straight out of it, so a mutating punch would corrupt the whole board.
    base = _piece_surface()
    before = pg.image.tostring(base, "RGBA")
    for tier in range(1, TORN_MAX_TIER + 1):
        torn_sprite(base, ("untouched", 48, tier), tier)
    assert pg.image.tostring(base, "RGBA") == before
    assert base.get_alpha() == 255
