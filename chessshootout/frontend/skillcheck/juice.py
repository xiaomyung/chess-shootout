import math

import pygame as pg

from chessshootout.frontend.visual.cache import new_size_cache, memoized_surface
from chessshootout.frontend.visual.tween import OUT_BACK_OVERSHOOT
from chessshootout.skillcheck.rng import seeded_floats


_NOISE_FREQS = ((13.0, 7.0), (27.0, 11.0))
_NOISE_PHASE = 1.7

TRAUMA_DECAY_PER_S = 1.5
HITSTOP_CAP_MS = 250.0

_SAKURAI_OMEGA = 2.0 * math.pi * 55.0

_TORN_CACHE = new_size_cache()
_FLASH_CACHE = new_size_cache()

TORN_MAX_TIER = 3

_TORN_NOTCHES = {1: 2, 2: 4, 3: 6}
_TORN_NOTCH_FRAC = {1: 0.11, 2: 0.15, 3: 0.16}
_TORN_CRACKS = {1: 1, 2: 2, 3: 3}
_TORN_CHUNK_FRAC = 0.34
_TORN_RAGGED = 5
_TORN_FLOATS = 48
_CRACK_RGBA = (18, 14, 12, 235)
_TORN_REACH_BASE = 0.85
_TORN_REACH_JITTER = 0.25
_TORN_RADIUS_BASE = 0.7
_TORN_RADIUS_JITTER = 0.6
_TORN_CHUNK_OFFSET = 0.6
_TORN_RAGGED_BAND_FRAC = 0.08
_TORN_RAGGED_RADIUS_FRAC = 0.09
_TORN_CRACK_WIDTH_FRAC = 0.03


def _smooth_noise(now_ms, axis):
    t = now_ms / 1000.0
    (base_a, step_a), (base_b, step_b) = _NOISE_FREQS
    f1 = base_a + axis * step_a
    f2 = base_b + axis * step_b
    phase = axis * _NOISE_PHASE
    return 0.5 * math.sin(t * f1 + phase) + 0.5 * math.sin(t * f2 + phase * 2.0)


class Trauma:

    def __init__(self, decay_per_s=TRAUMA_DECAY_PER_S):
        self._decay_per_s = decay_per_s
        self._value = 0.0
        self._last_ms = None

    def add(self, amount):
        self._value = max(0.0, min(1.0, self._value + amount))

    def update(self, now_ms):
        if self._last_ms is None:
            self._last_ms = now_ms
            return
        dt = (now_ms - self._last_ms) / 1000.0
        self._last_ms = now_ms
        if dt > 0.0:
            self._value = max(0.0, self._value - self._decay_per_s * dt)

    def offset(self, now_ms, max_offset_px):
        shake = self._value * self._value
        if shake <= 0.0:
            return (0.0, 0.0)
        span = shake * max_offset_px
        return (span * _smooth_noise(now_ms, 0), span * _smooth_noise(now_ms, 1))

    def roll_deg(self, now_ms, max_deg):
        shake = self._value * self._value
        if shake <= 0.0:
            return 0.0
        return shake * max_deg * _smooth_noise(now_ms, 2)

    @property
    def value(self):
        return self._value


class Hitstop:

    def __init__(self, cap_ms=HITSTOP_CAP_MS):
        self._cap_ms = cap_ms
        self._until = None

    def trigger(self, now_ms, duration_ms):
        horizon = now_ms + self._cap_ms
        target = now_ms + min(duration_ms, self._cap_ms)
        if self._until is not None and self._until > now_ms:
            target = max(self._until, target)
        self._until = min(target, horizon)

    def frozen(self, now_ms):
        return self._until is not None and now_ms < self._until


def sakurai_vibrate(now_ms, start_ms, duration_ms, amp_px):
    if duration_ms <= 0.0:
        return 0.0
    t = now_ms - start_ms
    if t < 0.0 or t >= duration_ms:
        return 0.0
    envelope = 1.0 - t / duration_ms
    return amp_px * envelope * math.sin(t / 1000.0 * _SAKURAI_OMEGA)


def ease_out_back(t, overshoot=OUT_BACK_OVERSHOOT):
    c3 = overshoot + 1.0
    u = t - 1.0
    return 1.0 + c3 * u * u * u + overshoot * u * u


def _punch(mask, cx, cy, radius):
    if radius < 1.0:
        return
    pg.draw.circle(mask, (0, 0, 0, 0), (int(cx), int(cy)), max(int(radius), 1))


def _draw_cracks(surf, bbox, floats, idx, count, width, rgba=_CRACK_RGBA):
    if width < 1 or rgba[3] <= 0:
        return
    inset = bbox.inflate(-bbox.width // 2, -bbox.height // 2)
    for _ in range(count):
        x0 = inset.left + inset.width * floats[idx]
        y0 = inset.top + inset.height * floats[idx + 1]
        x1 = inset.left + inset.width * floats[idx + 2]
        y1 = inset.top + inset.height * floats[idx + 3]
        pg.draw.line(surf, rgba, (x0, y0), (x1, y1), width)
        idx += 4


def _torn_surface(base, key, tier):
    surf = base.copy()
    bbox = surf.get_bounding_rect()
    if bbox.width <= 0 or bbox.height <= 0:
        return surf
    floats = seeded_floats(f"torn:{key}", _TORN_FLOATS)
    span = min(bbox.width, bbox.height)
    cx, cy = bbox.centerx, bbox.centery
    hx, hy = bbox.width / 2.0, bbox.height / 2.0
    mask = pg.Surface(surf.get_size(), pg.SRCALPHA)
    mask.fill((255, 255, 255, 255))
    idx = 0
    radius_base = span * _TORN_NOTCH_FRAC[tier]
    for _ in range(_TORN_NOTCHES[tier]):
        ang = floats[idx] * 2.0 * math.pi
        reach = _TORN_REACH_BASE + _TORN_REACH_JITTER * floats[idx + 2]
        _punch(mask, cx + math.cos(ang) * hx * reach, cy + math.sin(ang) * hy * reach,
               radius_base * (_TORN_RADIUS_BASE + _TORN_RADIUS_JITTER * floats[idx + 1]))
        idx += 3
    if tier >= TORN_MAX_TIER:
        ang = floats[idx] * 2.0 * math.pi
        _punch(mask, cx + math.cos(ang) * hx * _TORN_CHUNK_OFFSET,
               cy + math.sin(ang) * hy * _TORN_CHUNK_OFFSET,
               span * _TORN_CHUNK_FRAC)
        idx += 1
        for _ in range(_TORN_RAGGED):
            _punch(mask, bbox.left + bbox.width * floats[idx],
                   bbox.top + span * _TORN_RAGGED_BAND_FRAC * floats[idx + 1],
                   span * _TORN_RAGGED_RADIUS_FRAC)
            idx += 2
    surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    _draw_cracks(surf, bbox, floats, idx, _TORN_CRACKS[tier],
                 max(int(span * _TORN_CRACK_WIDTH_FRAC), 1))
    return surf


def torn_sprite(base, key, tier):
    if tier <= 0:
        return base
    return memoized_surface(_TORN_CACHE, (key, tier),
                            lambda: _torn_surface(base, key, tier))


def flash_sprite(base, key):
    def build():
        surf = base.copy()
        surf.fill((255, 255, 255, 0), special_flags=pg.BLEND_RGB_ADD)
        return surf
    return memoized_surface(_FLASH_CACHE, key, build)
