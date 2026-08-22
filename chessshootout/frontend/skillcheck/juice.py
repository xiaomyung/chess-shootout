import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pygame as pg

from chessshootout.frontend.visual.cache import new_size_cache, memoized_surface
from chessshootout.skillcheck.rng import seeded_floats

_NOISE_FREQS = ((13.0, 7.0), (27.0, 11.0))
_NOISE_PHASE = 1.7

TRAUMA_DECAY_PER_S = 1.5
HITSTOP_CAP_MS = 250.0

_SAKURAI_OMEGA = 2.0 * math.pi * 55.0

_TORN_CACHE = new_size_cache()
_FLASH_CACHE = new_size_cache()


@dataclass(frozen=True)
class _TornTier:
    """
    One step of the victim's damage: how many bites are taken out of the
    sprite, how big each one is as a fraction of the piece, and how many cracks
    run across it. The three shipped tiers are approved feel -- treat these
    numbers as fixed, never as something to recompute
    """

    notches: int
    notch_frac: float
    cracks: int


_TORN_TIERS = (_TornTier(3, 0.10, 1), _TornTier(6, 0.11, 2), _TornTier(9, 0.12, 3))
TORN_MAX_TIER = len(_TORN_TIERS)

_TORN_CHUNK_FRAC = 0.34
_TORN_RAGGED = 5
_CRACK_RGBA = (18, 14, 12, 235)
_TORN_RADIUS_BASE = 0.7
_TORN_RADIUS_JITTER = 0.6
_TORN_CHUNK_OFFSET = 0.6
_TORN_RAGGED_BAND_FRAC = 0.08
_TORN_RAGGED_RADIUS_FRAC = 0.09
_TORN_CRACK_WIDTH_FRAC = 0.03
_TORN_PUNCH_FLOATS = 3
_TORN_CRACK_FLOATS = 4
_TORN_CHUNK_FLOATS = 1
_TORN_RAGGED_FLOATS = 2
_TORN_CRACK_BASE = _TORN_PUNCH_FLOATS * max(t.notches for t in _TORN_TIERS)
_TORN_EXTRA_BASE = _TORN_CRACK_BASE + _TORN_CRACK_FLOATS * max(t.cracks for t in _TORN_TIERS)
_TORN_FLOATS = _TORN_EXTRA_BASE + _TORN_CHUNK_FLOATS + _TORN_RAGGED_FLOATS * _TORN_RAGGED


def _smooth_noise(now_ms: int, axis: int) -> float:
    """
    A wandering value that never jumps, which is what makes a screen shake read
    as a shudder rather than as flicker. Two sine waves of unrelated frequency
    are summed, and each axis is given its own pair and phase so the two never
    move together

    :param now_ms: pygame ticks in milliseconds for this frame
    :param axis: 0 for horizontal, 1 for vertical
    :returns: a smooth value in [-1, 1]
    """
    t = now_ms / 1000.0
    (base_a, step_a), (base_b, step_b) = _NOISE_FREQS
    f1 = base_a + axis * step_a
    f2 = base_b + axis * step_b
    phase = axis * _NOISE_PHASE
    return 0.5 * math.sin(t * f1 + phase) + 0.5 * math.sin(t * f2 + phase * 2.0)


class Trauma:
    """
    The screen shake behind a shootout: hits add trauma, time takes it away,
    and the views ask it for a pixel offset to draw their whole scene at. It is
    one of the shared feel tools this module owns -- shake, hitstop, the
    torn and flash sprite caches, and the particle lifecycle -- so every check
    shudders in the same language
    """

    def __init__(self, decay_per_s: float = TRAUMA_DECAY_PER_S) -> None:
        """
        Start calm, with no shake and no frame yet seen. The default decay is
        the approved feel value, and the argument exists so tests can pin a
        rate rather than so callers can retune it

        :param decay_per_s: how much trauma bleeds away per second, on the same
            0-to-1 scale the value itself uses
        """
        self._decay_per_s = decay_per_s
        self._value = 0.0
        self._last_ms: int | None = None

    def add(self, amount: float) -> None:
        """
        Feed a hit in. Trauma is capped at full, so a burst of hits in one
        moment shakes hard but never harder than the shipped maximum

        :param amount: trauma to add on the 0-to-1 scale, where the whack view
            spends about a third of the range per pop
        """
        self._value = max(0.0, min(1.0, self._value + amount))

    def update(self, now_ms: int) -> None:
        """
        Bleed trauma off for the time since the last frame, which is what makes
        a shake settle instead of ringing on. The very first call only takes
        the timestamp, so a check that starts mid-frame does not lose trauma
        for time it was not running

        :param now_ms: pygame tick count in milliseconds for this frame
        """
        if self._last_ms is None:
            self._last_ms = now_ms
            return
        dt = (now_ms - self._last_ms) / 1000.0
        self._last_ms = now_ms
        if dt > 0.0:
            self._value = max(0.0, self._value - self._decay_per_s * dt)

    def offset(self, now_ms: int, max_offset_px: float) -> tuple[float, float]:
        """
        Give the pixel shift to draw this frame at. Trauma is squared first, so
        the shake dies away sharply rather than trailing off, and the two axes
        wander independently. Calm frames answer dead centre, which lets the
        caller skip the whole shake cheaply

        :param now_ms: pygame tick count in milliseconds for this frame
        :param max_offset_px: how far full trauma may push the scene, in pixels
        :returns: (dx, dy) offset in pixels, never beyond the maximum
        """
        shake = self._value * self._value
        if shake <= 0.0:
            return (0.0, 0.0)
        span = shake * max_offset_px
        return (span * _smooth_noise(now_ms, 0), span * _smooth_noise(now_ms, 1))

    @property
    def value(self) -> float:
        """
        How shaken the scene currently is, which the views read to scale other
        reactions off the same feeling

        :returns: trauma from 0.0 for calm to 1.0 for a fresh hit
        """
        return self._value


class Hitstop:
    """
    The freeze frame that sells a hit: for a few tens of milliseconds after a
    pop the check stops advancing its animation clock, so the blow reads as
    landing rather than being swept past. Only the animation clock stops --
    the real clock, the deadline and the server keep running
    """

    def __init__(self, cap_ms: float = HITSTOP_CAP_MS) -> None:
        """
        Start unfrozen. The cap is the approved feel value and is a hard
        ceiling on the freeze, so no pile-up of hits can stall a check for
        longer than a quarter second

        :param cap_ms: longest freeze allowed, in milliseconds, measured from
            whichever trigger came last
        """
        self._cap_ms = cap_ms
        self._until: float | None = None

    def trigger(self, now_ms: int, duration_ms: float) -> None:
        """
        Freeze from now for a while. Overlapping hits extend the freeze rather
        than restart it, but never past the cap measured from this trigger, so
        rapid fire cannot chain one long stall

        :param now_ms: pygame ticks in milliseconds the hit landed at
        :param duration_ms: freeze this hit asks for, in milliseconds
        """
        horizon = now_ms + self._cap_ms
        target = now_ms + min(duration_ms, self._cap_ms)
        if self._until is not None and self._until > now_ms:
            target = max(self._until, target)
        self._until = min(target, horizon)

    def frozen(self, now_ms: int) -> bool:
        """
        Whether this frame falls inside a freeze, which the views use to decide
        whether to advance their animation clock at all

        :param now_ms: pygame tick count in milliseconds for this frame
        :returns: True while the freeze is still running
        """
        return self._until is not None and now_ms < self._until


def sakurai_vibrate(now_ms: int, start_ms: int, duration_ms: float, amp_px: float) -> float:
    """
    The buzz a struck piece makes: a fast wobble that fades out over its
    window, the fighting-game trick for making a hit feel like it hurt. It is
    silent outside its window, so a caller can pass it every frame and let it
    decide when it applies

    :param now_ms: pygame tick count in milliseconds for this frame
    :param start_ms: pygame ticks the hit landed at
    :param duration_ms: how long the buzz lasts, in milliseconds
    :param amp_px: how far the first wobble reaches, in pixels
    :returns: the horizontal shift for this frame in pixels, zero outside the
        window
    """
    if duration_ms <= 0.0:
        return 0.0
    t = now_ms - start_ms
    if t < 0.0 or t >= duration_ms:
        return 0.0
    envelope = 1.0 - t / duration_ms
    return amp_px * envelope * math.sin(t / 1000.0 * _SAKURAI_OMEGA)


def expire_particles(items: list[tuple[Any, ...]], now_ms: int, ttl_ms: float) -> None:
    """
    Retire the particles that have outlived their window, the sweep every burst
    system in the check views runs once a frame. It trusts spawn order and only
    walks the front of the list, stopping at the first survivor, so a sweep
    costs nothing on a list that is mostly alive

    :param items: the view's own particle list of (spawn_ms, ...) tuples,
        oldest first; trimmed in place
    :param now_ms: pygame tick count in milliseconds for this frame
    :param ttl_ms: how long a particle lives, in milliseconds; an item goes the
        instant its age reaches it
    """
    while items and now_ms - items[0][0] >= ttl_ms:
        items.pop(0)


def particle_ages(items: list[tuple[Any, ...]],
                  now_ms: int) -> Iterator[tuple[float, tuple[Any, ...]]]:
    """
    Walk a particle list handing each one its age and its payload, which is how
    the check views drive every fade, drift and shrink. It never filters:
    callers index colours by position, so every item is yielded -- even one
    outside its window -- and the draw loops skip those themselves

    :param items: the view's particle list of (spawn_ms, ...) tuples
    :param now_ms: pygame tick count in milliseconds for this frame
    :returns: one (age in milliseconds, payload after the spawn stamp) pair per
        item, in list order
    """
    for item in items:
        yield now_ms - item[0], item[1:]


def _punch(mask: pg.Surface, cx: float, cy: float, radius: float) -> None:
    """
    Bite one hole out of the damage mask, which is what later erases that patch
    of the victim. Sub-pixel bites are dropped rather than drawn as a dot

    :param mask: the mask being cut, opaque where the piece survives
    :param cx: bite centre x in mask pixels
    :param cy: bite centre y in mask pixels
    :param radius: bite radius in pixels
    """
    if radius < 1.0:
        return
    pg.draw.circle(mask, (0, 0, 0, 0), (int(cx), int(cy)), max(int(radius), 1))


def _draw_cracks(surf: pg.Surface, bbox: pg.Rect, floats: tuple[float, ...], idx: int,
                 count: int, width: int) -> None:
    """
    Score dark fracture lines across the middle of the victim, the damage that
    reads even where nothing has been bitten off yet. They are kept to the
    inner half of the piece so a crack never appears to float off it

    :param surf: layer the cracks are drawn on, later masked to the piece
    :param bbox: the sprite's opaque bounds in its own pixels
    :param floats: the seeded stream the endpoints are read from
    :param idx: where in that stream this tier's cracks begin
    :param count: how many cracks this tier draws
    :param width: line thickness in pixels
    """
    inset = bbox.inflate(-bbox.width // 2, -bbox.height // 2)
    for _ in range(count):
        x0 = inset.left + inset.width * floats[idx]
        y0 = inset.top + inset.height * floats[idx + 1]
        x1 = inset.left + inset.width * floats[idx + 2]
        y1 = inset.top + inset.height * floats[idx + 3]
        pg.draw.line(surf, _CRACK_RGBA, (x0, y0), (x1, y1), width)
        idx += _TORN_CRACK_FLOATS


def _torn_surface(base: pg.Surface, key: Any, tier: int) -> pg.Surface:
    """
    Beat up a piece's sprite to the given tier: bites taken out of it, cracks
    scored across it, and at the worst tier a whole chunk gone and its crown
    left ragged. Damage is cumulative by construction -- one seeded stream is
    read in fixed blocks, so a higher tier re-punches the same wounds and
    simply keeps going, which is what makes a victim break up in place instead
    of reshuffling on every hit

    :param base: the undamaged sprite, left untouched
    :param key: identity of this victim, which seeds where the damage lands;
        two victims with different keys never break identically
    :param tier: damage step from 1 to TORN_MAX_TIER
    :returns: a new damaged sprite, the same size as the original
    """
    surf = base.copy()
    bbox = surf.get_bounding_rect()
    if bbox.width <= 0 or bbox.height <= 0:
        return surf
    floats = seeded_floats(f"torn:{key}", _TORN_FLOATS)
    span = min(bbox.width, bbox.height)
    mask = pg.Surface(surf.get_size(), pg.SRCALPHA)
    mask.fill((255, 255, 255, 255))
    tier_spec = _TORN_TIERS[tier - 1]
    radius_base = span * tier_spec.notch_frac
    idx = 0
    for _ in range(tier_spec.notches):
        _punch(mask, bbox.left + bbox.width * floats[idx],
               bbox.top + bbox.height * floats[idx + 1],
               radius_base * (_TORN_RADIUS_BASE + _TORN_RADIUS_JITTER * floats[idx + 2]))
        idx += _TORN_PUNCH_FLOATS
    if tier >= TORN_MAX_TIER:
        idx = _TORN_EXTRA_BASE
        ang = floats[idx] * 2.0 * math.pi
        _punch(mask, bbox.centerx + math.cos(ang) * bbox.width / 2.0 * _TORN_CHUNK_OFFSET,
               bbox.centery + math.sin(ang) * bbox.height / 2.0 * _TORN_CHUNK_OFFSET,
               span * _TORN_CHUNK_FRAC)
        idx += _TORN_CHUNK_FLOATS
        for _ in range(_TORN_RAGGED):
            _punch(mask, bbox.left + bbox.width * floats[idx],
                   bbox.top + span * _TORN_RAGGED_BAND_FRAC * floats[idx + 1],
                   span * _TORN_RAGGED_RADIUS_FRAC)
            idx += _TORN_RAGGED_FLOATS
    veins = pg.Surface(surf.get_size(), pg.SRCALPHA)
    _draw_cracks(veins, bbox, floats, _TORN_CRACK_BASE, tier_spec.cracks,
                 max(int(span * _TORN_CRACK_WIDTH_FRAC), 1))
    veins.blit(surf, (0, 0), special_flags=pg.BLEND_RGBA_MIN)
    surf.blit(veins, (0, 0))
    surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    return surf


def torn_sprite(base: pg.Surface, key: Any, tier: int) -> pg.Surface:
    """
    Give the damaged sprite for a victim at one tier, building it once and
    reusing it for every frame after. This is what the whack check draws its
    mole as, so the piece visibly comes apart as the hit quota fills; an
    undamaged tier hands the original straight back

    :param base: the undamaged sprite
    :param key: identity of this victim at this size, which seeds the damage
        and keys the cache with the tier
    :param tier: damage step, 0 for untouched up to TORN_MAX_TIER
    :returns: the shared damaged sprite, or the base sprite at tier 0
    """
    if tier <= 0:
        return base
    return memoized_surface(_TORN_CACHE, (key, tier),
                            lambda: _torn_surface(base, key, tier))


def flash_sprite(base: pg.Surface, key: Any) -> pg.Surface:
    """
    Give the blown-out white version of a sprite, the single frame of impact a
    check shows the moment a shot connects. The whiten keeps the piece's own
    silhouette, and each one is built once and shared

    :param base: the sprite to whiten, damage and all
    :param key: identity of that exact sprite, which keys the cache
    :returns: the shared whitened sprite
    """
    def build() -> pg.Surface:
        """
        Whiten this sprite, called only on a cache miss

        :returns: the freshly whitened sprite
        """
        surf = base.copy()
        surf.fill((255, 255, 255, 0), special_flags=pg.BLEND_RGB_ADD)
        return surf
    return memoized_surface(_FLASH_CACHE, key, build)
