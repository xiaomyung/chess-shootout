"""juice.py owns only the *damage* half of the whack choreography now: a torn
sprite is a pure function of (key, tier) and nothing else. The regrow buckets
that used to un-punch the notches step by step are gone — the fail heal is a
two-source composite built by the view (torn top / whole bottom, split at a
travelling seam), so juice never needs to know how far along a repair is.

The damage model itself is "stepped amount, random placement": every punch is
drawn uniformly inside the sprite's bounding box (no edge ring — any part of
the body can take a hit), and the tiers are cumulative rather than independent
rolls. One seeded float stream per key is laid out in fixed blocks — punches
first, then cracks, then the max-tier chunk and ragged crown — so tier N reads
the same prefix tier N-1 read and simply keeps going. That is what makes the
damage *grow in place* instead of reshuffling on every hit, and it is pinned
below as set inclusion on the transparent pixels.
"""

import dataclasses
import inspect
import math

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.skillcheck import juice
from chessshootout.frontend.skillcheck.juice import (
    Trauma, Hitstop, sakurai_vibrate, torn_sprite, flash_sprite,
    TRAUMA_DECAY_PER_S, HITSTOP_CAP_MS, TORN_MAX_TIER,
    _TORN_TIERS, _TORN_CACHE, _torn_surface,
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


def _hollow_piece_surface(size=48):
    # Real piece art is not convex — a knight's jaw, a king's cross and every
    # base/stem junction leave transparent gaps well inside the bounding box,
    # right where the cracks are drawn. This fixture reproduces that with a
    # transparent slot straight through the middle of a solid block.
    surf = pg.Surface((size, size), pg.SRCALPHA)
    surf.fill((200, 190, 175, 255))
    pg.draw.rect(surf, (0, 0, 0, 0),
                 pg.Rect(size // 2 - size // 12, 0, size // 6, size))
    return surf


# Twelve seeds is enough that a placement rule which only ever chews the rim
# cannot sneak through the body-wide pins below by luck of one lucky key.
_DAMAGE_KEYS = [(f"torn-{i}", 48) for i in range(12)]
_DAMAGE_TIERS = tuple(range(1, TORN_MAX_TIER + 1))


def _opaque_count(surf):
    w, h = surf.get_size()
    return sum(1 for x in range(w) for y in range(h) if surf.get_at((x, y))[3] > 0)


def _transparent_pixels(surf):
    w, h = surf.get_size()
    return {(x, y) for x in range(w) for y in range(h) if surf.get_at((x, y))[3] == 0}


def _transparent_count_in(surf, rect):
    return sum(1 for x in range(rect.left, rect.right)
               for y in range(rect.top, rect.bottom)
               if surf.get_at((x, y))[3] == 0)


def _ink_pixels(surf, base):
    # Pixels the damage pass re-coloured without removing them: the crack veins.
    w, h = surf.get_size()
    return {(x, y) for x in range(w) for y in range(h)
            if surf.get_at((x, y))[3] > 0 and surf.get_at((x, y)) != base.get_at((x, y))}


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


def test_torn_max_tier_covers_exactly_the_tier_tuple():
    """TORN_MAX_TIER is public (the check views clamp damage tiers against it)
    and derives from the tier tuple, so tier N always has an entry — the old
    three parallel dicts could drift from the constant and KeyError at draw
    time. The tuple entries are frozen: tier data can never be mutated at
    runtime, only monkeypatched wholesale in tests."""
    assert len(_TORN_TIERS) == TORN_MAX_TIER
    assert TORN_MAX_TIER == 3, "the shipped damage model has exactly three tiers"
    with pytest.raises(dataclasses.FrozenInstanceError):
        _TORN_TIERS[0].notches = 99


def test_torn_tier_tuple_matches_the_shipped_tables():
    """The 2026-07 shipped per-tier values, byte-for-byte: a refactor of the
    table SHAPE must not move a single number (the float-stream layout and the
    cached torn sprites both hang off them)."""
    assert [(t.notches, t.notch_frac, t.cracks) for t in _TORN_TIERS] == [
        (3, 0.10, 1), (6, 0.11, 2), (9, 0.12, 3)]


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


def test_trauma_has_no_roll_channel():
    # roll_deg shipped with the whack juice pass but no view ever consumed it;
    # the offset channel (axes 0 and 1 of the smooth noise) is the whole API.
    assert not hasattr(Trauma, "roll_deg")


def test_trauma_offset_bounded_by_max_at_full_trauma():
    t = Trauma()
    t.add(1.0)
    max_px = 30.0
    for now in range(0, 4000, 37):
        dx, dy = t.offset(now, max_px)
        assert abs(dx) <= max_px + 1e-9
        assert abs(dy) <= max_px + 1e-9


def test_trauma_offset_deterministic_for_same_state_and_now():
    a = Trauma()
    a.add(0.5)
    b = Trauma()
    b.add(0.5)
    assert a.offset(999, 20.0) == b.offset(999, 20.0)


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


# --- easing lives in visual/tween now ---------------------------------------

def test_juice_owns_no_easing_duplicate():
    # ease_out_back duplicated tween.out_back with the same overshoot; both
    # combo call sites clamp their input to [0, 1], where the two are equal
    # (pinned in test_tween.py). One easing home, no drift.
    assert not hasattr(juice, "ease_out_back")


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
    # Not one lucky seed: every key has to lose body on every step up, or the
    # tier the view picked would read as "no worse than the last hit".
    base = _piece_surface()
    base_n = _opaque_count(base)
    for key in _DAMAGE_KEYS:
        counts = [_opaque_count(_torn_surface(base, key, tier)) for tier in _DAMAGE_TIERS]
        assert base_n > counts[0], key
        for higher, lower in zip(counts, counts[1:]):
            assert higher > lower, (key, counts)


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


# --- stepped amount, random placement ---------------------------------------

def test_torn_tier_tables_only_ever_grow():
    # The cumulative model rests on the tier tuple being monotone. Tier N draws
    # the first tier.notches punches of one stream and re-punches the earlier
    # ones at tier.notch_frac: a shrinking count would drop wounds, a shrinking
    # radius would heal their rims, and either way tier N would stop containing
    # tier N-1.
    counts = [t.notches for t in _TORN_TIERS]
    fracs = [t.notch_frac for t in _TORN_TIERS]
    cracks = [t.cracks for t in _TORN_TIERS]
    assert counts == sorted(counts) and counts[0] < counts[-1]
    assert fracs == sorted(fracs)
    assert cracks == sorted(cracks) and cracks[0] < cracks[-1]


def test_torn_damage_is_cumulative_tier_over_tier():
    # The point of the single sequential float stream: damage grows in place.
    # Punches are hard-edged circles, so "the wound stayed put" is exactly set
    # inclusion on the transparent pixels — a reshuffle would move a hole and
    # the inclusion would fail immediately.
    base = _piece_surface()
    for key in _DAMAGE_KEYS:
        holes = [_transparent_pixels(_torn_surface(base, key, tier))
                 for tier in _DAMAGE_TIERS]
        for lower, higher in zip(holes, holes[1:]):
            assert lower <= higher, key
        assert holes[0] < holes[-1], key


def test_torn_damage_lands_in_the_middle_of_the_body_not_just_the_rim():
    # The old model aimed every punch at a ring around the silhouette, so the
    # middle third of the sprite was untouchable by construction. Uniform
    # placement has to put holes there for a healthy share of the seeds.
    base = _piece_surface()
    bbox = base.get_bounding_rect()
    middle = pg.Rect(bbox.left + bbox.width // 3, bbox.top + bbox.height // 3,
                     bbox.width // 3, bbox.height // 3)
    hit = [key for key in _DAMAGE_KEYS
           if _transparent_count_in(_torn_surface(base, key, 2), middle) > 0]
    assert len(hit) >= len(_DAMAGE_KEYS) // 2, hit


def test_torn_damage_spreads_over_the_whole_bbox_not_one_cluster():
    # Same claim from the other side, pooled over the seeds and on a finer 5x5
    # grid: the dead-centre cell takes hits (the rim model could not reach it at
    # all) and so does nearly every other cell, so the placement is spread
    # rather than parked on one favourite spot.
    grid = 5
    base = _piece_surface()
    bbox = base.get_bounding_rect()
    intact = _transparent_pixels(base)
    cells = set()
    for key in _DAMAGE_KEYS:
        for x, y in _transparent_pixels(_torn_surface(base, key, 2)) - intact:
            cells.add((grid * (x - bbox.left) // bbox.width,
                       grid * (y - bbox.top) // bbox.height))
    assert (grid // 2, grid // 2) in cells, sorted(cells)
    assert len(cells) >= grid * grid - 2, sorted(cells)


def test_torn_different_keys_punch_different_places():
    base = _piece_surface()
    shapes = {frozenset(_transparent_pixels(_torn_surface(base, key, 2)))
              for key in _DAMAGE_KEYS}
    assert len(shapes) == len(_DAMAGE_KEYS), "two victims never break identically"


def test_the_piece_still_reads_as_a_piece_at_max_tier():
    # Measured on this fixture, max tier leaves 0.39-0.61 of the body standing
    # (real piece art keeps more — its silhouette is narrower than this disc, so
    # a good share of every punch lands on empty box). The floor is the guard
    # against a radius/count edit that turns the victim into a puff of dust.
    base = _piece_surface()
    base_n = _opaque_count(base)
    left = [_opaque_count(_torn_surface(base, key, TORN_MAX_TIER)) / base_n
            for key in _DAMAGE_KEYS]
    assert min(left) > 0.35, left
    assert sum(left) / len(left) > 0.45, left


def test_torn_never_paints_outside_the_silhouette():
    # Damage only ever removes. The crack veins are clipped to the source alpha,
    # which is what keeps the cumulative property true on real (non-convex) art:
    # an unclipped tier-3 crack could ink over a hollow — or over a hole tier 2
    # had already punched — and tier 3 would no longer contain tier 2.
    base = _hollow_piece_surface()
    hollow = _transparent_pixels(base)
    for key in _DAMAGE_KEYS[:4]:
        for tier in _DAMAGE_TIERS:
            assert hollow <= _transparent_pixels(_torn_surface(base, key, tier)), (key, tier)


def test_torn_cracks_are_cumulative_too(monkeypatch):
    # Mute every alpha-punching element and the crack ink is all that is left.
    # It has to nest tier over tier as well, which only holds because the crack
    # floats start at a fixed offset in the stream instead of picking up after
    # however many punches the tier happened to draw.
    monkeypatch.setattr(juice, "_TORN_TIERS",
                        tuple(dataclasses.replace(t, notches=0) for t in _TORN_TIERS))
    monkeypatch.setattr(juice, "_TORN_CHUNK_FRAC", 0.0)
    monkeypatch.setattr(juice, "_TORN_RAGGED", 0)
    base = _piece_surface()
    intact = _transparent_pixels(base)
    for key in _DAMAGE_KEYS[:4]:
        frames = [_torn_surface(base, key, tier) for tier in _DAMAGE_TIERS]
        assert all(_transparent_pixels(frame) == intact for frame in frames), \
            "the mute really did silence every punch, so only ink is left to compare"
        veins = [_ink_pixels(frame, base) for frame in frames]
        for lower, higher in zip(veins, veins[1:]):
            assert lower <= higher, key
        assert veins[0] < veins[-1], key


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
