import math
import typing

import pygame as pg

from chessshootout.backend.utils import BOARD_SIZE, Square
from chessshootout.frontend.skillcheck.controller import SkillCheckController
from chessshootout.frontend.skillcheck.juice import (
    Trauma, Hitstop, sakurai_vibrate, torn_sprite, flash_sprite, TORN_MAX_TIER)
from chessshootout.frontend.visual.cache import new_size_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    SUPERSAMPLE, cosine_pulse, rounded_rect_surface, supersample)
from chessshootout.frontend.visual.tween import out_cubic
from chessshootout.infra import env
from chessshootout.skillcheck.mole import (
    MOLE_GRACE_MS, MOLE_HITBOX_CY_FRAC, MOLE_HITBOX_RX_FRAC, MOLE_HITBOX_RY_FRAC,
    MOLE_INTRO_MS, MOLE_MAX_WHIFFS, MOLE_RECOIL_LOCKOUT_MS)
from chessshootout.skillcheck.rng import seeded_floats

MOLE_VIEW_FAIL_HOLD_MS = 1250
MOLE_VIEW_HOLE_STAGGER_MS = 40.0
MOLE_VIEW_HOLE_OPEN_MS = 160.0
MOLE_VIEW_RETREAT_MS = 160.0
MOLE_VIEW_POP_HEIGHT_FRAC = 1.0
MOLE_VIEW_POP_OVERSHOOT = 1.08
MOLE_VIEW_POP_APEX_FRAC = 0.30
MOLE_VIEW_POP_LIFT_CAP = 1.2
MOLE_VIEW_PIT_RX_FRAC = 0.42
MOLE_VIEW_PIT_RY_FRAC = 0.24
MOLE_VIEW_PIT_RIM_FRAC = 0.14
MOLE_VIEW_PIT_INSET_FRAC = 0.06
MOLE_VIEW_EMERGE_FADE_FRAC = 0.35
MOLE_VIEW_PIT_GLOW_ALPHA = 60
MOLE_VIEW_PIT_CLOSE_MS = 160.0
MOLE_VIEW_PULSE_MS = 420
MOLE_VIEW_PULSE_BUCKETS = 6
MOLE_VIEW_TELE_WHITE_MIN = 0.35
MOLE_VIEW_TELE_ALPHA_GAIN = 0.5
MOLE_VIEW_DANGER_PULSE_MS = 200
MOLE_VIEW_DANGER_SWITCH = 0.5
MOLE_VIEW_DANGER_RIM_SCALE = 1.6
MOLE_VIEW_SQUASH_BUCKETS = 4
MOLE_VIEW_SQUASH_X = 0.28
MOLE_VIEW_SQUASH_Y = 0.38
MOLE_VIEW_CROSS_ARM_FRAC = 0.19
MOLE_VIEW_CROSS_GAP_FRAC = 0.05
MOLE_VIEW_CROSS_LW_FRAC = 0.024
MOLE_VIEW_CROSS_BLADE_W_FRAC = 0.11
MOLE_VIEW_CROSS_TIP_W_FRAC = 0.035
MOLE_VIEW_CROSS_ARC_PAD_FRAC = 0.42
MOLE_VIEW_CROSS_ARC_W_FRAC = 0.9
MOLE_VIEW_CROSS_ARC_SPAN_DEG = 55.0
MOLE_VIEW_CROSS_ARC_SEGS = 24
MOLE_VIEW_CROSS_DOT_FRAC = 0.18
MOLE_VIEW_CROSS_GLOW_FRAC = 0.16
MOLE_VIEW_CROSS_GLOW_GAIN = 0.30
MOLE_VIEW_CROSS_OUT_MS = 120.0
MOLE_VIEW_CROSS_OUT_SCALE = 0.72
MOLE_VIEW_CROSS_OUT_BUCKETS = 6
MOLE_VIEW_BLOOM_BUCKETS = 8
MOLE_VIEW_BLOOM_SPREAD_FRAC = 0.62
MOLE_VIEW_BLOOM_SPIN_DEG = 30.0
MOLE_VIEW_KICK_FRAC = 0.12
MOLE_VIEW_KICK_MS = 140.0
MOLE_VIEW_MUZZLE_MS = 90.0
MOLE_VIEW_MUZZLE_FRAC = 0.34
MOLE_VIEW_MUZZLE_RAY_W_DIV = 6
MOLE_VIEW_HIT_FLASH_MS = 90.0
MOLE_VIEW_TRAUMA_PER_HIT = 0.3
MOLE_VIEW_TRAUMA_OFFSET_FRAC = 0.10
MOLE_VIEW_HITSTOP_HIT_MS = 60.0
MOLE_VIEW_HITSTOP_KILL_MS = 200.0
MOLE_VIEW_VIBRATE_AMP_FRAC = 0.05
MOLE_VIEW_WIN_POP_MS = 350.0
MOLE_VIEW_WIN_POP_R_FRAC = 1.1
MOLE_VIEW_WIN_POP_GAIN = 0.85
MOLE_VIEW_WIN_HOLD_MS = 750
MOLE_VIEW_TOSS_MS = 550.0
MOLE_VIEW_TOSS_SPEED_FRAC = 2.6
MOLE_VIEW_TOSS_UP_FRAC = 1.4
MOLE_VIEW_TOSS_GRAVITY_FRAC = 6.0
MOLE_VIEW_TOSS_SPIN_DPS = 540.0
MOLE_VIEW_TOSS_FADE_START = 0.45
MOLE_VIEW_TOSS_FALLBACK_ARC = (0.2, 0.8)
MOLE_VIEW_JUMP_RISE_MS = 180.0
MOLE_VIEW_JUMP_HOP_MS = 320.0
MOLE_VIEW_JUMP_HEIGHT_FRAC = 0.5
MOLE_VIEW_LAND_SQUASH_MS = 90.0
MOLE_VIEW_REGROW_MS = 550.0
MOLE_VIEW_HEAL_BUCKETS = 24
MOLE_VIEW_SEAM_BAND_FRAC = 0.21
MOLE_VIEW_SEAM_WHITE_CORE = 0.6
MOLE_VIEW_SEAM_GLOW_W_FRAC = 1.25
MOLE_VIEW_SEAM_GLOW_H_FRAC = 0.10
MOLE_VIEW_SEAM_GLOW_CORE = 0.8
MOLE_VIEW_SPARK_MS = 260.0
MOLE_VIEW_SPARK_SPEED_FRAC = 0.30
MOLE_VIEW_SPARK_RISE_FRAC = 0.12
MOLE_VIEW_SPARK_R_FRAC = 0.035
MOLE_VIEW_SPARK_SPEED_JITTER = (0.6, 0.8)
MOLE_VIEW_SPARK_RISE_JITTER = (0.5, 1.0)
MOLE_VIEW_PIP_W_FRAC = 0.11
MOLE_VIEW_PIP_H_FRAC = 0.20
MOLE_VIEW_PIP_GAP_FRAC = 0.07
MOLE_VIEW_PIP_OFFSET_FRAC = 0.66
MOLE_VIEW_PIP_FADE_DELAY_MS = 300.0
MOLE_VIEW_PIP_FADE_MS = 250.0
MOLE_VIEW_PIP_RADIUS_DIV = 3
MOLE_VIEW_CROSS_STRIKE_SIZE_FRAC = 0.16
MOLE_VIEW_CROSS_STRIKE_GAP_FRAC = 0.07
MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC = 0.66
MOLE_VIEW_CROSS_STRIKE_LW_FRAC = 0.12
MOLE_VIEW_CROSS_STRIKE_PAD_FRAC = 0.28
MOLE_VIEW_CROSS_STRIKE_RING_LW_FRAC = 0.1
MOLE_VIEW_CASING_W_FRAC = 0.10
MOLE_VIEW_CASING_H_FRAC = 0.05
MOLE_VIEW_CASING_TIP_DIV = 4
MOLE_VIEW_CASING_VX_FRAC = 1.4
MOLE_VIEW_CASING_UP_FRAC = 1.8
MOLE_VIEW_CASING_GRAVITY_FRAC = 7.0
MOLE_VIEW_CASING_FALL_FRAC = 0.7
MOLE_VIEW_CASING_SPIN_DPS = 520.0
MOLE_VIEW_CASING_SPIN_BUCKET_DEG = 20
MOLE_VIEW_CASING_UP_JITTER = (0.7, 0.6)
MOLE_VIEW_CASING_REST_MS = 1000.0
MOLE_VIEW_CASING_FADE_MS = 400.0
MOLE_VIEW_CASING_COMMIT_FADE_MS = 300.0
MOLE_VIEW_PUFF_MS = 320.0
MOLE_VIEW_PUFF_COUNT = 5
MOLE_VIEW_PUFF_R_FRAC = 0.09
MOLE_VIEW_PUFF_SPEED_FRAC = 0.9
MOLE_VIEW_PUFF_SPEED_JITTER = (0.5, 0.5)
MOLE_VIEW_DEBRIS_MS = 420.0
MOLE_VIEW_DEBRIS_COUNT = 7
MOLE_VIEW_DEBRIS_R_FRAC = 0.05
MOLE_VIEW_DEBRIS_SPEED_FRAC = 1.6
MOLE_VIEW_DEBRIS_SPEED_JITTER = (0.4, 0.6)
MOLE_VIEW_DEBRIS_GRAVITY_FRAC = 4.0
MOLE_VIEW_IMPACT_MS = 260.0
MOLE_VIEW_IMPACT_R_FRAC = 0.12
MOLE_VIEW_FALLBACK_SPREAD_FRAC = 1.2
MOLE_VIEW_TARGET_MAX = BOARD_SIZE - 0.001
MOLE_VIEW_HITBOX_LW = 1
MOLE_VIEW_HITBOX_ACTIVE_LW = 2


class MoleCasing(typing.NamedTuple):
    spawn_ms: float
    x0: float
    y0: float
    vx: float
    vy: float
    gravity: float
    t_land: float
    spin: float


class MoleToss(typing.NamedTuple):
    x0: float
    y0: float
    vx: float
    vy: float
    spin: float


_PIT_DARK = pg.Color(Colors.well_deep)
_CROSS_COLOR = pg.Color(Colors.text)
_CROSS_EDGE = pg.Color(Colors.bg)
_CROSS_ARC = pg.Color(Colors.accent)
_CROSS_ARC_HOT = pg.Color(Colors.amber_hi)
_CROSS_DOT = pg.Color(Colors.amber_hi)
_CROSS_GLOW = pg.Color(Colors.accent)
_IMPACT_COLOR = pg.Color(Colors.spectate)
_HITBOX_COLOR = pg.Color(Colors.spectate)
_HITBOX_ACTIVE_COLOR = pg.Color(Colors.win)
_DUST_COLORS = (pg.Color(Colors.text_dim), pg.Color(Colors.text_muted), pg.Color(Colors.border))
_DEBRIS_COLORS = (pg.Color(Colors.amber_hi), pg.Color(Colors.accent_hi), pg.Color(Colors.amber))

_AXES = ((1, 0), (-1, 0), (0, 1), (0, -1))

_POP_APEX = MOLE_VIEW_POP_HEIGHT_FRAC * MOLE_VIEW_POP_OVERSHOOT
_CLEAR = (0, 0, 0, 0)
_KEEP = (255, 255, 255)

_MOLE_STATIC_CACHE = new_size_cache()


def _pit_render(rim_color, glow_alpha, rim_scale=1.0):
    def render(surf, k):
        w, h = surf.get_size()
        rim = pg.Color(rim_color)
        glow = pg.Color(rim.r, rim.g, rim.b, glow_alpha)
        pg.draw.ellipse(surf, glow, pg.Rect(0, 0, w, h))
        inset_x = int(w * MOLE_VIEW_PIT_INSET_FRAC)
        inset_y = int(h * MOLE_VIEW_PIT_INSET_FRAC)
        outer = pg.Rect(inset_x, inset_y, w - 2 * inset_x, h - 2 * inset_y)
        pg.draw.ellipse(surf, rim, outer)
        rim_w = max(int(outer.height * MOLE_VIEW_PIT_RIM_FRAC * rim_scale), 1)
        pg.draw.ellipse(surf, _PIT_DARK, outer.inflate(-2 * rim_w, -2 * rim_w))
    return render


def _pit_surface(rx, ry):
    def build():
        return supersample((2 * rx, 2 * ry),
                           _pit_render(Colors.accent, MOLE_VIEW_PIT_GLOW_ALPHA))
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit", rx, ry), build)


def _pit_mouth(rx, ry):
    w, h = 2 * rx * SUPERSAMPLE, 2 * ry * SUPERSAMPLE
    inset_x = int(w * MOLE_VIEW_PIT_INSET_FRAC)
    inset_y = int(h * MOLE_VIEW_PIT_INSET_FRAC)
    rim = max(int((h - 2 * inset_y) * MOLE_VIEW_PIT_RIM_FRAC), 1)
    return (max((w // 2 - inset_x - rim) // SUPERSAMPLE, 1),
            max((h // 2 - inset_y - rim) // SUPERSAMPLE, 1))


def _emerge_mask(w, rx, ry, fade):
    def build():
        mask = pg.Surface((w, ry + fade + 1), pg.SRCALPHA)
        half = w / 2.0
        for x in range(w):
            dx = abs(x + 0.5 - half) / rx
            arc = round(ry * math.sqrt(1.0 - dx * dx)) if dx < 1.0 else 0
            mask.fill(_KEEP, (x, 0, 1, arc))
            for i in range(fade):
                mask.fill((*_KEEP, int(255 * (1.0 - (i + 1) / fade))), (x, arc + i, 1, 1))
        return mask
    return memoized_surface(_MOLE_STATIC_CACHE, ("emerge", w, rx, ry, fade), build)


def _pit_front_surface(rx, ry):
    def build():
        pit = _pit_surface(rx, ry)
        half = max(pit.get_height() // 2, 1)
        front = pg.Surface((pit.get_width(), half), pg.SRCALPHA)
        front.blit(pit, (0, half - pit.get_height()))
        return front
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit_front", rx, ry), build)


def _seam_band_surface(w, h):
    def build():
        band = pg.Surface((w, h), pg.SRCALPHA)
        hot = pg.Color(Colors.amber_hi)
        white = pg.Color(Colors.text)
        half = max(h / 2.0, 1.0)
        for y in range(h):
            edge = abs(y - half) / half
            gain = (1.0 - min(edge, 1.0)) ** 2
            col = hot.lerp(white, MOLE_VIEW_SEAM_WHITE_CORE * (1.0 - edge))
            pg.draw.line(band, (int(col.r * gain), int(col.g * gain), int(col.b * gain)),
                         (0, y), (w - 1, y))
        return band
    return memoized_surface(_MOLE_STATIC_CACHE, ("seam", w, h), build)


def _seam_glow_surface(w, h):
    def build():
        surf = pg.Surface((w, h))
        hot = pg.Color(Colors.amber_hi)
        white = pg.Color(Colors.text)
        half_w = max(w / 2.0, 1.0)
        half_h = max(h / 2.0, 1.0)
        edge = max(1.0 - MOLE_VIEW_SEAM_GLOW_CORE, 0.001)
        for y in range(h):
            v = 1.0 - min(abs(y + 0.5 - half_h) / half_h, 1.0)
            col = hot.lerp(white, MOLE_VIEW_SEAM_WHITE_CORE * v)
            for x in range(w):
                d = min(abs(x + 0.5 - half_w) / half_w, 1.0)
                gain = v * v * min((1.0 - d) / edge, 1.0)
                surf.set_at((x, y), (int(col.r * gain), int(col.g * gain), int(col.b * gain)))
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("seamglow", w, h), build)


def _cross_blade_points(c, ux, uy, inner, outer, tip_half, base_half):
    px, py = -uy, ux
    return ((c + ux * inner + px * tip_half, c + uy * inner + py * tip_half),
            (c + ux * outer + px * base_half, c + uy * outer + py * base_half),
            (c + ux * outer - px * base_half, c + uy * outer - py * base_half),
            (c + ux * inner - px * tip_half, c + uy * inner - py * tip_half))


def _cross_arc_points(c, r_in, r_out, a0, a1):
    segs = MOLE_VIEW_CROSS_ARC_SEGS
    angles = [a0 + (a1 - a0) * i / segs for i in range(segs + 1)]
    outer = [(c + r_out * math.cos(a), c + r_out * math.sin(a)) for a in angles]
    inner = [(c + r_in * math.cos(a), c + r_in * math.sin(a)) for a in reversed(angles)]
    return outer + inner


def _render_cross_blades(surf, k, c, gap, arm, tip_half, base_half):
    for ux, uy in _AXES:
        pg.draw.polygon(surf, _CROSS_EDGE, _cross_blade_points(
            c, ux, uy, gap * k - k, (gap + arm) * k + k,
            tip_half * k + k, base_half * k + k))
    for ux, uy in _AXES:
        pg.draw.polygon(surf, _CROSS_COLOR, _cross_blade_points(
            c, ux, uy, gap * k, (gap + arm) * k, tip_half * k, base_half * k))


def _crosshair_surface(arm, gap, lw, bloom_bucket, out_bucket):
    def build():
        bloom = bloom_bucket / MOLE_VIEW_BLOOM_BUCKETS
        s = (1.0 - (1.0 - MOLE_VIEW_CROSS_OUT_SCALE)
             * out_bucket / MOLE_VIEW_CROSS_OUT_BUCKETS)
        a = max(arm * s, 2.0)
        g = (gap + arm * MOLE_VIEW_BLOOM_SPREAD_FRAC * bloom) * s
        stroke = max(lw * s, 1.0)
        tip_half = max(a * MOLE_VIEW_CROSS_TIP_W_FRAC, 0.5) / 2.0
        base_half = max(a * MOLE_VIEW_CROSS_BLADE_W_FRAC, 2.0) / 2.0
        arc_r = g + a + max(a * MOLE_VIEW_CROSS_ARC_PAD_FRAC, 2.0)
        arc_w = max(stroke * MOLE_VIEW_CROSS_ARC_W_FRAC, 1.0)
        dot_r = max(a * MOLE_VIEW_CROSS_DOT_FRAC, 1.6)
        spin = math.radians(MOLE_VIEW_BLOOM_SPIN_DEG * bloom)
        span = math.radians(MOLE_VIEW_CROSS_ARC_SPAN_DEG)
        arc_col = _CROSS_ARC.lerp(_CROSS_ARC_HOT, bloom)
        reach = int(math.ceil(arc_r + arc_w)) + 2

        def render(surf, k):
            c = surf.get_width() / 2.0
            _render_cross_blades(surf, k, c, g, a, tip_half, base_half)
            for i in range(4):
                mid = math.pi / 4.0 + i * math.pi / 2.0 + spin
                pg.draw.polygon(surf, arc_col, _cross_arc_points(
                    c, (arc_r - arc_w / 2.0) * k, (arc_r + arc_w / 2.0) * k,
                    mid - span / 2.0, mid + span / 2.0))
            pg.draw.circle(surf, _CROSS_EDGE, (c, c), dot_r * k + k)
            pg.draw.circle(surf, _CROSS_DOT, (c, c), dot_r * k)
        return supersample(2 * reach + 1, render)
    key = ("cross", arm, gap, lw, bloom_bucket, out_bucket)
    return memoized_surface(_MOLE_STATIC_CACHE, key, build)


def _cross_glow_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r))
        for i in range(r, 0, -1):
            gain = (1.0 - i / r) ** 2 * MOLE_VIEW_CROSS_GLOW_GAIN
            col = (int(_CROSS_GLOW.r * gain), int(_CROSS_GLOW.g * gain),
                   int(_CROSS_GLOW.b * gain))
            pg.draw.circle(surf, col, (r, r), i)
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("crossglow", r), build)


def _strike_cross_surface(size, struck):
    def build():
        def render(surf, k):
            w = surf.get_width()
            r = w / 2.0
            if struck:
                pg.draw.circle(surf, pg.Color(Colors.loss), (r, r), r)
                lw = max(int(w * MOLE_VIEW_CROSS_STRIKE_LW_FRAC), 2)
                pad = w * MOLE_VIEW_CROSS_STRIKE_PAD_FRAC
                pg.draw.line(surf, pg.Color(Colors.on_accent), (pad, pad),
                             (w - pad, w - pad), lw)
                pg.draw.line(surf, pg.Color(Colors.on_accent), (w - pad, pad),
                             (pad, w - pad), lw)
            else:
                lw = max(int(w * MOLE_VIEW_CROSS_STRIKE_RING_LW_FRAC), 2)
                pg.draw.circle(surf, pg.Color(Colors.border_strong), (r, r), r - lw, lw)
        return supersample((size, size), render)
    return memoized_surface(_MOLE_STATIC_CACHE, ("strike", size, struck), build)


def _danger_render(bucket):
    hot = bucket >= 1
    rim = pg.Color(Colors.text) if hot else pg.Color(Colors.loss)
    alpha = 255 if hot else MOLE_VIEW_PIT_GLOW_ALPHA
    scale = MOLE_VIEW_DANGER_RIM_SCALE if hot else 1.0
    return _pit_render(rim, alpha, scale)


def _telegraph_render(bucket):
    frac = bucket / (MOLE_VIEW_PULSE_BUCKETS - 1)
    blend = MOLE_VIEW_TELE_WHITE_MIN + (1.0 - MOLE_VIEW_TELE_WHITE_MIN) * frac
    rim = pg.Color(Colors.accent).lerp(pg.Color(Colors.text), blend)
    alpha = int(MOLE_VIEW_PIT_GLOW_ALPHA
                + (255 - MOLE_VIEW_PIT_GLOW_ALPHA) * frac * MOLE_VIEW_TELE_ALPHA_GAIN)
    return _pit_render(rim, alpha)


def _pit_telegraph_surface(rx, ry, bucket, danger=False):
    def build():
        render = _danger_render(bucket) if danger else _telegraph_render(bucket)
        return supersample((2 * rx, 2 * ry), render)
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit_tele", rx, ry, bucket, danger), build)


def _muzzle_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r))
        hot = pg.Color(Colors.amber_hi)
        for i in range(r, 0, -1):
            edge = i / r
            col = pg.Color(int(hot.r * (1.0 - edge) ** 2), int(hot.g * (1.0 - edge) ** 2),
                           int(hot.b * (1.0 - edge) ** 2))
            pg.draw.circle(surf, col, (r, r), i)
        for dx, dy in _AXES:
            pg.draw.line(surf, hot, (r, r), (r + dx * r, r + dy * r),
                         max(r // MOLE_VIEW_MUZZLE_RAY_W_DIV, 1))
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("muzzle", r), build)


def _win_pop_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r))
        warm = pg.Color(Colors.amber)
        for i in range(r, 0, -1):
            edge = i / r
            gain = (1.0 - edge) ** 2 * MOLE_VIEW_WIN_POP_GAIN
            pg.draw.circle(surf, (int(warm.r * gain), int(warm.g * gain), int(warm.b * gain)),
                           (r, r), i)
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("winpop", r), build)


def _casing_surface(w, h):
    def build():
        surf = pg.Surface((w, h), pg.SRCALPHA)
        surf.fill(pg.Color(Colors.amber))
        pg.draw.rect(surf, pg.Color(Colors.amber_hi),
                     pg.Rect(0, 0, max(w // MOLE_VIEW_CASING_TIP_DIV, 1), h))
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("casing", w, h), build)


def _casing_rotated(w, h, bucket):
    def build():
        base = _casing_surface(w, h)
        deg = bucket * MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        return base if deg == 0 else pg.transform.rotate(base, deg)
    return memoized_surface(_MOLE_STATIC_CACHE, ("casing_rot", w, h, bucket), build)


def _expire(items, now_ms, ttl_ms):
    while items and now_ms - items[0][0] >= ttl_ms:
        items.pop(0)


def _blit_alpha(window, surf, pos, alpha):
    if alpha < 255:
        surf.set_alpha(alpha)
    window.blit(surf, pos)
    if alpha < 255:
        surf.set_alpha(255)


def _puff_color(tt, j):
    return _DUST_COLORS[min(int(tt * len(_DUST_COLORS)), len(_DUST_COLORS) - 1)]


def _debris_color(tt, j):
    return _DEBRIS_COLORS[j % len(_DEBRIS_COLORS)]


class MoleController(SkillCheckController):

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms, *, hole_squares=None,
                 victim_surface=None, geom=None, from_sq=None, shot_sound=None, on_shot=None,
                 progress=0, passive=False, audio=None, on_hit_px=None,
                 mirror_targets=False, last_hit_pop=-1):
        self._init_common(challenge, now_ms, deadline_ms, on_shot=on_shot, passive=passive,
                          audio=audio)
        self._hole_squares = tuple(hole_squares) if hole_squares is not None else ()
        self._geom = geom
        self._from_sq = from_sq
        self._shot_sound = shot_sound
        self._on_hit_px = on_hit_px
        self._mirror_targets = mirror_targets
        self._init_victim(victim_surface, cell_rect)
        self._victim_bbox = None
        self._squash_cache = {}
        self._heal_cache = {}
        self._emerge_scratch = {}
        self._progress = progress
        self._miss_count = 0
        self._torn_key = hash(challenge.pops)
        self._last_hit_pop = last_hit_pop
        self._last_hit_anim_ms = None
        self._last_hit_height = 0.0
        self._last_hit_px = None
        self._reset_effects(cell_rect.center)
        self._win_ms = None
        self._last_shot_ms = None
        self._shot_count = 0
        self._next_telegraph = 0
        self._next_pop = 0
        self._cues_primed = False
        self._anim_ms = float(now_ms)
        first = challenge.pops[0]
        self._intro_ms = max(min(MOLE_INTRO_MS, first.t_telegraph_ms), 1.0)
        self._debug_hitbox = env.get_debug_hitbox()
        self._cursor_hidden = False
        if not passive:
            pg.mouse.set_visible(False)
            self._cursor_hidden = True
        self._apply_geometry(cell_rect)
        self._cue("play_mole_fall")

    def _reset_effects(self, flash_px):
        self._hit_flash_ms = None
        self._vibrate_ms = None
        self._vibrate_dur_ms = 0.0
        self._flash_ms = None
        self._flash_px = flash_px
        self._trauma = Trauma()
        self._hitstop = Hitstop()
        self._toss = None
        self._casings = []
        self._puffs = []
        self._debris = []
        self._impacts = []
        self._seam_sparks = []
        self._last_heal_bucket = 0

    def _apply_geometry(self, cell_rect):
        cell = max(int(cell_rect.width), 1)
        self.center = cell_rect.center
        self.cell_size = cell
        if self._victim_orig is not None:
            self._victim = self._scaled_victim(cell)
        if self._victim is not None:
            self._victim_bbox = self._victim.get_bounding_rect()
        self._affine = self._derive_affine()
        self._hole_px = self._hole_centers()
        self._pit_rx = max(int(cell * MOLE_VIEW_PIT_RX_FRAC), 6)
        self._pit_ry = max(int(cell * MOLE_VIEW_PIT_RY_FRAC), 4)
        self._mouth_rx, self._mouth_ry = _pit_mouth(self._pit_rx, self._pit_ry)
        self._emerge_fade = max(int(self._mouth_ry * MOLE_VIEW_EMERGE_FADE_FRAC), 2)
        self._cross_arm = max(int(cell * MOLE_VIEW_CROSS_ARM_FRAC), 4)
        self._cross_gap = max(int(cell * MOLE_VIEW_CROSS_GAP_FRAC), 2)
        self._cross_lw = max(round(cell * MOLE_VIEW_CROSS_LW_FRAC), 1)
        self._kick_amp = cell * MOLE_VIEW_KICK_FRAC
        self._pip_w = max(int(cell * MOLE_VIEW_PIP_W_FRAC), 4)
        self._pip_h = max(int(cell * MOLE_VIEW_PIP_H_FRAC), 6)
        self._pip_gap = max(int(cell * MOLE_VIEW_PIP_GAP_FRAC), 2)
        self._strike_size = max(int(cell * MOLE_VIEW_CROSS_STRIKE_SIZE_FRAC), 6)
        self._strike_gap = max(int(cell * MOLE_VIEW_CROSS_STRIKE_GAP_FRAC), 2)
        self._squash_cache.clear()
        self._heal_cache.clear()
        self._emerge_scratch.clear()

    def _derive_affine(self):
        if self._geom is None:
            return None
        x0, y0 = self._geom(Square(0, 0))
        x1, y1 = self._geom(Square(1, 1))
        dx, dy = x1 - x0, y1 - y0
        if dx == 0 or dy == 0:
            return None
        return (float(x0), float(y0), float(dx), float(dy))

    def _hole_centers(self):
        if self._geom is not None:
            return tuple(self._geom(Square(row, col)) for row, col in self._hole_squares)
        n = len(self._hole_squares)
        spread = self.cell_size * MOLE_VIEW_FALLBACK_SPREAD_FRAC
        return tuple((int(self.center[0] + (i - (n - 1) / 2.0) * spread), self.center[1])
                     for i in range(n))

    def _board_to_px(self, row_f, col_f):
        if self._affine is None:
            return None
        x0, y0, dx, dy = self._affine
        return (x0 + (col_f - 0.5) * dx, y0 + (row_f - 0.5) * dy)

    def _shot_target(self, pos):
        if self._affine is None:
            return None
        x0, y0, dx, dy = self._affine
        return ((pos[1] - y0) / dy + 0.5, (pos[0] - x0) / dx + 0.5)

    def _clamp_target(self, target):
        return (min(max(target[0], 0.0), MOLE_VIEW_TARGET_MAX),
                min(max(target[1], 0.0), MOLE_VIEW_TARGET_MAX))

    def relayout(self, cell_rect):
        self._apply_geometry(cell_rect)

    def handle_event(self, event):
        if self._passive:
            return False
        if self._committed_at is not None:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._fire(event.pos)
            return True
        if event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
            self._fire(pg.mouse.get_pos())
            return True
        return False

    def _fire(self, pos):
        if (self._last_shot_ms is not None
                and self._now - self._last_shot_ms < MOLE_RECOIL_LOCKOUT_MS):
            self._cue("play_whack_dry")
            return
        target = self._shot_target(pos)
        if target is None:
            return
        target = self._clamp_target(target)
        self._flash_ms = self._now
        self._flash_px = pos
        self._last_shot_ms = self._now
        if self._shot_sound is not None:
            self._shot_sound()
        elapsed = self._now - self.start_ms
        if self._online:
            self._on_shot(elapsed, target=target)
        flipped = self._affine is not None and self._affine[3] < 0
        if self.challenge.hit_at(elapsed, target[0], target[1], self._hole_squares,
                                 self._last_hit_pop, flipped=flipped):
            self._register_hit(elapsed, pos)
        else:
            self._miss_count += 1
            self._spawn_puffs(pos)
            self._cue("play_whiff_ricochet")
            if not self._online and self.challenge.whiffs_exhausted(self._miss_count):
                self._commit(False)
        self._spawn_casing(pos)

    def _register_hit(self, elapsed, shot_px):
        idx = self.challenge.pop_up_at(elapsed)
        self._duck_pop(idx, elapsed)
        hole = self.challenge.pops[idx].hole
        if hole < len(self._hole_px):
            self._last_hit_px = self._hole_px[hole]
        self._progress += 1
        kill = self._progress >= self.challenge.hits_required
        self._hit_juice(kill)
        self._emit_hit_px(shot_px, kill)
        if self._audio is not None and not self._passive:
            self._audio.play_whack_hit(self._progress - 1)
        if kill:
            self._cue("play_whack_kill")
            if not self._online:
                self._commit(True)

    def _emit_hit_px(self, shot_px, kill):
        if self._on_hit_px is None:
            return
        px = self._last_hit_px if self._last_hit_px is not None else shot_px
        if px is not None:
            self._on_hit_px(px, kill)

    def _hit_juice(self, kill):
        self._trauma.add(MOLE_VIEW_TRAUMA_PER_HIT)
        dur = MOLE_VIEW_HITSTOP_KILL_MS if kill else MOLE_VIEW_HITSTOP_HIT_MS
        self._hitstop.trigger(self._now, dur)
        self._vibrate_ms = self._now
        self._vibrate_dur_ms = dur
        self._hit_flash_ms = self._now
        self._spawn_debris(self._last_hit_px if self._last_hit_px is not None else self.center)

    def _spawn_casing(self, pos):
        self._shot_count += 1
        cell = self.cell_size
        f = seeded_floats(f"molecasing:{self._shot_count}", 3)
        up_base, up_span = MOLE_VIEW_CASING_UP_JITTER
        vx = (f[0] * 2.0 - 1.0) * cell * MOLE_VIEW_CASING_VX_FRAC
        vy = -cell * MOLE_VIEW_CASING_UP_FRAC * (up_base + up_span * f[1])
        g = cell * MOLE_VIEW_CASING_GRAVITY_FRAC
        fall = cell * MOLE_VIEW_CASING_FALL_FRAC
        t_land = (-vy + math.sqrt(vy * vy + 2.0 * g * fall)) / g
        spin = 1.0 if f[2] < 0.5 else -1.0
        self._casings.append(
            MoleCasing(self._now, float(pos[0]), float(pos[1]), vx, vy, g, t_land, spin))

    def _spawn_burst(self, items, pos, prefix, count, tag=""):
        f = seeded_floats(f"{prefix}:{tag}{self._shot_count + 1}", count * 2)
        items.append((self._now, float(pos[0]), float(pos[1]), f))

    def _spawn_puffs(self, pos):
        self._spawn_burst(self._puffs, pos, "molepuff", MOLE_VIEW_PUFF_COUNT)

    def _spawn_debris(self, pos, tag=""):
        self._spawn_burst(self._debris, pos, "moledebris", MOLE_VIEW_DEBRIS_COUNT, tag=tag)

    def _spawn_seam_sparks(self):
        if self._jump_elapsed() is None or self._damage_tier() <= 0:
            return
        bucket = self._heal_bucket()
        speed_base, speed_span = MOLE_VIEW_SPARK_SPEED_JITTER
        rise_base, rise_span = MOLE_VIEW_SPARK_RISE_JITTER
        while self._last_heal_bucket < bucket:
            self._last_heal_bucket += 1
            f = seeded_floats(f"moleseam:{self._torn_key}:{self._last_heal_bucket}", 4)
            frac = 1.0 - self._last_heal_bucket / MOLE_VIEW_HEAL_BUCKETS
            for side, speed_f, rise_f in ((-1, f[0], f[1]), (1, f[2], f[3])):
                self._seam_sparks.append(
                    (self._now, side, frac, speed_base + speed_span * speed_f,
                     rise_base + rise_span * rise_f))

    def _spectate_px(self, target):
        px = self._board_to_px(target[0], target[1])
        if px is None or not self._mirror_targets:
            return px
        lift = -MOLE_HITBOX_CY_FRAC if self._affine[3] < 0 else MOLE_HITBOX_CY_FRAC
        return (px[0], px[1] + 2.0 * lift * self._affine[3])

    def spectate_shot(self, elapsed, miss_count, won, progress=0, direction=None,
                      target=None):
        px = None
        if target is not None:
            px = self._spectate_px(target)
        if px is not None:
            self._impacts.append((self._now, px[0], px[1]))
            self._spawn_casing(px)
        if progress > self._progress:
            self._progress = progress
            if px is not None:
                self._last_hit_px = px
            idx = self.challenge.pop_up_at(elapsed)
            if idx is not None:
                self._duck_pop(idx, elapsed)
            kill = progress >= self.challenge.hits_required
            self._hit_juice(kill)
            self._emit_hit_px(px, kill)
        elif not won:
            if miss_count + 1 > self._miss_count:
                self._miss_count = miss_count + 1
            if px is not None:
                self._spawn_puffs(px)

    def resolve(self, won):
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        if won:
            self._win_ms = self._now
        self._emit_verdict()
        self._restore_cursor()

    def _commit(self, landed):
        self._landed = landed
        self._committed_at = self._now
        if landed:
            self._win_ms = self._now
        self._emit_verdict()
        self._restore_cursor()

    def close(self):
        self._restore_cursor()

    def _restore_cursor(self):
        if self._cursor_hidden:
            pg.mouse.set_visible(True)
            self._cursor_hidden = False

    def update(self, now_ms):
        dt = now_ms - self._now
        self._now = now_ms
        self._trauma.update(now_ms)
        if dt > 0 and not self._hitstop.frozen(now_ms):
            self._anim_ms += dt
        _expire(self._puffs, now_ms, MOLE_VIEW_PUFF_MS)
        _expire(self._debris, now_ms, MOLE_VIEW_DEBRIS_MS)
        _expire(self._impacts, now_ms, MOLE_VIEW_IMPACT_MS)
        _expire(self._seam_sparks, now_ms, MOLE_VIEW_SPARK_MS)
        self._casings = [c for c in self._casings if now_ms - c.spawn_ms
                         < c.t_land * 1000.0 + MOLE_VIEW_CASING_REST_MS
                         + MOLE_VIEW_CASING_FADE_MS]
        self._spawn_seam_sparks()
        if self._toss is None and self._toss_elapsed() is not None:
            self._start_toss()
        if self._committed_at is None:
            elapsed = now_ms - self.start_ms
            self._cue_schedule(elapsed)
            if not self._online and (elapsed >= self.deadline_ms
                                     or self.challenge.quota_unreachable(
                                         elapsed, self._progress, self._last_hit_pop)):
                self._commit(False)

    def _cue_schedule(self, elapsed):
        pops = self.challenge.pops
        live = self._cues_primed
        self._cues_primed = True
        while (self._next_telegraph < len(pops)
               and elapsed >= pops[self._next_telegraph].t_telegraph_ms):
            self._next_telegraph += 1
            if live:
                self._cue("play_mole_telegraph")
        while self._next_pop < len(pops) and elapsed >= pops[self._next_pop].t_up_ms:
            self._next_pop += 1
            if live:
                self._cue("play_mole_pop")

    @property
    def done(self):
        hold = MOLE_VIEW_WIN_HOLD_MS if self._landed else MOLE_VIEW_FAIL_HOLD_MS
        if self._online:
            if self._resolved_at is None:
                return False
            return self._now - self._resolved_at >= hold
        if self._committed_at is None:
            return False
        return self._now - self._committed_at >= hold

    @property
    def landed(self):
        return self._landed

    def draw(self, window):
        elapsed = self._frozen_elapsed()
        off = self._trauma.offset(self._now, self.cell_size * MOLE_VIEW_TRAUMA_OFFSET_FRAC)
        group = (int(off[0]), int(off[1]))
        self._draw_pits(window, elapsed, group)
        self._draw_puffs(window)
        self._draw_victim(window, elapsed, group)
        self._draw_casings(window)
        self._draw_debris(window)
        self._draw_impacts(window)
        self._draw_win_pop(window, group)
        if not self._passive:
            self._draw_muzzle(window)
            self._draw_crosshair(window)
        self._draw_pips(window, group)
        self._draw_strike_crosses(window, group)
        if self._debug_hitbox:
            self._draw_hitboxes(window, elapsed)

    def _telegraph_hole(self, elapsed):
        if self._committed_at is not None:
            return None
        for index, pop in enumerate(self.challenge.pops):
            if pop.t_telegraph_ms <= elapsed < pop.t_up_ms:
                return index, pop.hole
        return None

    def _draw_pits(self, window, elapsed, group):
        self._draw_home_pit(window, elapsed, group)
        tele = self._telegraph_hole(elapsed)
        pit = _pit_surface(self._pit_rx, self._pit_ry)
        for i, (hx, hy) in enumerate(self._hole_px):
            open_t = (elapsed - i * MOLE_VIEW_HOLE_STAGGER_MS) / MOLE_VIEW_HOLE_OPEN_MS
            if open_t <= 0.0:
                continue
            scale = min(open_t, 1.0) * self._pit_close_scale(i)
            if scale <= 0.0:
                continue
            cx, cy = hx + group[0], hy + group[1]
            if scale < 1.0:
                self._draw_pit_mouth(window, cx, cy, scale)
                continue
            surf = pit
            if tele is not None and i == tele[1]:
                surf = self._telegraph_surface(tele[0])
            window.blit(surf, (cx - surf.get_width() // 2, cy - surf.get_height() // 2))

    def _draw_pit_mouth(self, window, cx, cy, scale):
        rx = max(int(self._pit_rx * scale), 2)
        ry = max(int(self._pit_ry * scale), 1)
        pg.draw.ellipse(window, _PIT_DARK, pg.Rect(cx - rx, cy - ry, 2 * rx, 2 * ry))

    def _draw_home_pit(self, window, elapsed, group):
        scale = min(elapsed / MOLE_VIEW_HOLE_OPEN_MS, 1.0) * self._home_pit_close_scale()
        if scale <= 0.0:
            return
        cx, cy = self.center[0] + group[0], self.center[1] + group[1]
        if scale < 1.0:
            self._draw_pit_mouth(window, cx, cy, scale)
            return
        surf = _pit_surface(self._pit_rx, self._pit_ry)
        window.blit(surf, (cx - surf.get_width() // 2, cy - surf.get_height() // 2))

    @staticmethod
    def _close_ramp(closing_ms):
        if closing_ms <= 0.0:
            return 1.0
        return max(1.0 - closing_ms / MOLE_VIEW_PIT_CLOSE_MS, 0.0)

    def _outro_start(self):
        if self._committed_at is None:
            return None
        if self._landed:
            return self._committed_at + MOLE_VIEW_HITSTOP_KILL_MS
        return self._committed_at

    def _pit_close_scale(self, index):
        start = self._outro_start()
        if start is None:
            return 1.0
        return self._close_ramp(self._now - start - index * MOLE_VIEW_HOLE_STAGGER_MS)

    def _home_pit_close_scale(self):
        jump_t = self._jump_elapsed()
        if jump_t is not None:
            return self._close_ramp(jump_t - MOLE_VIEW_JUMP_RISE_MS - MOLE_VIEW_JUMP_HOP_MS)
        start = self._outro_start()
        if start is None:
            return 1.0
        return self._close_ramp(self._now - start)

    def _telegraph_surface(self, index):
        danger = self.challenge.pop_mandatory(index, self._progress)
        if danger:
            pulse = cosine_pulse(self._anim_ms, MOLE_VIEW_DANGER_PULSE_MS)
            bucket = 1 if pulse >= MOLE_VIEW_DANGER_SWITCH else 0
        else:
            bucket = int(cosine_pulse(self._anim_ms, MOLE_VIEW_PULSE_MS)
                         * (MOLE_VIEW_PULSE_BUCKETS - 1))
        return _pit_telegraph_surface(self._pit_rx, self._pit_ry, bucket, danger)

    def _damage_tier(self):
        required = max(self.challenge.hits_required, 1)
        steps = -(-TORN_MAX_TIER * self._progress // required)
        return max(min(steps, TORN_MAX_TIER), 0)

    def _heal_progress(self):
        jump_t = self._jump_elapsed()
        if jump_t is None:
            return 0.0
        total = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS + MOLE_VIEW_REGROW_MS
        return min(max(jump_t / total, 0.0), 1.0)

    def _heal_bucket(self):
        return min(int(self._heal_progress() * MOLE_VIEW_HEAL_BUCKETS),
                   MOLE_VIEW_HEAL_BUCKETS)

    def _torn_victim(self, tier):
        return torn_sprite(self._victim, (self._torn_key, self.cell_size), tier)

    def _heal_sprite(self, tier, bucket):
        if tier <= 0 or bucket >= MOLE_VIEW_HEAL_BUCKETS:
            return self._victim
        if bucket <= 0:
            return self._torn_victim(tier)
        cached = self._heal_cache.get((tier, bucket))
        if cached is None:
            cached = self._build_heal_sprite(tier, bucket)
            self._heal_cache[(tier, bucket)] = cached
        return cached

    def _build_heal_sprite(self, tier, bucket):
        torn = self._torn_victim(tier)
        w, h = torn.get_size()
        seam_y = max(round(h * (1.0 - bucket / MOLE_VIEW_HEAL_BUCKETS)), 0)
        surf = pg.Surface((w, h), pg.SRCALPHA)
        if seam_y > 0:
            surf.blit(torn, (0, 0), area=pg.Rect(0, 0, w, seam_y))
        if seam_y < h:
            surf.blit(self._victim, (0, seam_y), area=pg.Rect(0, seam_y, w, h - seam_y))
        band_h = max(int(h * MOLE_VIEW_SEAM_BAND_FRAC), 3)
        surf.blit(_seam_band_surface(w, band_h), (0, seam_y - band_h // 2),
                  special_flags=pg.BLEND_RGB_ADD)
        return surf

    def _victim_sprite(self):
        tier = self._damage_tier()
        if self._jump_elapsed() is not None:
            return self._heal_sprite(tier, self._heal_bucket())
        sprite = self._torn_victim(tier)
        if self._flash_active():
            sprite = flash_sprite(sprite, (self._torn_key, self.cell_size, tier))
        return sprite

    def _flash_active(self):
        return (self._hit_flash_ms is not None
                and self._now - self._hit_flash_ms < MOLE_VIEW_HIT_FLASH_MS)

    def _squash_variant(self, sprite, bucket):
        if bucket <= 0:
            return sprite
        key = (id(sprite), bucket)
        cached = self._squash_cache.get(key)
        if cached is None:
            p = bucket / (MOLE_VIEW_SQUASH_BUCKETS - 1)
            w = max(int(sprite.get_width() * (1.0 + MOLE_VIEW_SQUASH_X * p)), 1)
            h = max(int(sprite.get_height() * (1.0 - MOLE_VIEW_SQUASH_Y * p)), 1)
            cached = pg.transform.smoothscale(sprite, (w, h))
            self._squash_cache[key] = cached
        return cached

    def _blit_victim(self, window, center_px, height_frac, group, squash=0, lift_px=0.0,
                     ground_dy=None, lip=False):
        if height_frac <= 0.0:
            return None
        sprite = self._squash_variant(self._victim_sprite(), squash)
        w, h = sprite.get_size()
        vib = 0.0
        if self._vibrate_ms is not None:
            vib = sakurai_vibrate(self._now, self._vibrate_ms, self._vibrate_dur_ms,
                                  self.cell_size * MOLE_VIEW_VIBRATE_AMP_FRAC)
        cx = center_px[0] + group[0] + int(vib)
        ground = self._emergence_dy(height_frac) if ground_dy is None else ground_dy
        base_y = center_px[1] + group[1] + ground
        if height_frac < 1.0:
            clip_h = max(int(h * height_frac), 1)
            rect = pg.Rect(cx - w // 2, base_y - clip_h, w, clip_h)
            window.blit(self._emerging_sprite(sprite, clip_h - ground), rect.topleft)
            return rect
        lift = int((min(height_frac, MOLE_VIEW_POP_LIFT_CAP) - 1.0) * h + lift_px)
        rect = pg.Rect(cx - w // 2, base_y - h - lift, w, h)
        window.blit(sprite, rect)
        if lip:
            front = _pit_front_surface(self._pit_rx, self._pit_ry)
            window.blit(front, (center_px[0] + group[0] - front.get_width() // 2,
                                center_px[1] + group[1]))
        return rect

    def _emerging_sprite(self, sprite, cut):
        w, h = sprite.get_size()
        scratch = self._emerge_scratch.get((w, h))
        if scratch is None:
            scratch = pg.Surface((w, h), pg.SRCALPHA)
            self._emerge_scratch[(w, h)] = scratch
        scratch.fill(_CLEAR)
        scratch.blit(sprite, (0, 0), special_flags=pg.BLEND_RGBA_MAX)
        scratch.fill(_CLEAR, (0, max(cut + self._mouth_ry, 0), w, h))
        scratch.blit(_emerge_mask(w, self._mouth_rx, self._mouth_ry, self._emerge_fade),
                     (0, cut - self._emerge_fade), special_flags=pg.BLEND_RGBA_MULT)
        return scratch

    def _emergence_dy(self, height_frac):
        return int(self._pit_ry * (1.0 - min(height_frac, 1.0)))

    def _rest_ground_dy(self):
        h = self._victim.get_height()
        return h - h // 2

    def _jump_elapsed(self):
        if self._landed is not False or self._committed_at is None:
            return None
        return self._now - self._committed_at

    def _toss_elapsed(self):
        if not self._landed or self._committed_at is None:
            return None
        toss_t = self._now - self._committed_at - MOLE_VIEW_HITSTOP_KILL_MS
        return toss_t if toss_t >= 0.0 else None

    def _start_toss(self):
        origin = self._last_hit_px if self._last_hit_px is not None else self.center
        cell = self.cell_size
        dx, dy = self._toss_direction(origin)
        speed = cell * MOLE_VIEW_TOSS_SPEED_FRAC
        spin = seeded_floats(f"moletossspin:{self._torn_key}", 1)[0]
        self._toss = MoleToss(float(origin[0]), float(origin[1]), dx * speed,
                              dy * speed - cell * MOLE_VIEW_TOSS_UP_FRAC,
                              1.0 if spin < 0.5 else -1.0)
        self._spawn_debris(origin, "toss")

    def _toss_direction(self, origin):
        if self._from_sq is not None and self._geom is not None:
            ax, ay = self._geom(self._from_sq)
            dx, dy = origin[0] - ax, origin[1] - ay
            dist = math.hypot(dx, dy)
            if dist > 0.0:
                return (dx / dist, dy / dist)
        low, high = MOLE_VIEW_TOSS_FALLBACK_ARC
        f = seeded_floats(f"moletossdir:{self._torn_key}", 1)
        ang = -math.pi * (low + (high - low) * f[0])
        return (math.cos(ang), math.sin(ang))

    def _toss_point(self, toss_t):
        t = toss_t / 1000.0
        g = self.cell_size * MOLE_VIEW_TOSS_GRAVITY_FRAC
        return (self._toss.x0 + self._toss.vx * t,
                self._toss.y0 + self._toss.vy * t + 0.5 * g * t * t)

    @staticmethod
    def _toss_alpha(progress):
        fade = ((progress - MOLE_VIEW_TOSS_FADE_START)
                / max(1.0 - MOLE_VIEW_TOSS_FADE_START, 0.001))
        return max(int(255 * (1.0 - max(fade, 0.0))), 0)

    def _draw_toss(self, window, toss_t, group):
        if self._toss is None or toss_t >= MOLE_VIEW_TOSS_MS:
            return
        x, y = self._toss_point(toss_t)
        deg = self._toss.spin * toss_t / 1000.0 * MOLE_VIEW_TOSS_SPIN_DPS
        sprite = pg.transform.rotozoom(self._torn_victim(self._damage_tier()), deg, 1.0)
        sprite.set_alpha(self._toss_alpha(toss_t / MOLE_VIEW_TOSS_MS))
        window.blit(sprite, (int(x) + group[0] - sprite.get_width() // 2,
                             int(y) + group[1] - sprite.get_height() // 2))

    def _draw_jump(self, window, jump_t, group):
        rect = self._jump_victim_rect(window, jump_t, group)
        self._draw_seam_glow(window, rect)
        self._draw_seam_sparks(window, rect)

    def _jump_victim_rect(self, window, jump_t, group):
        rest_dy = self._rest_ground_dy()
        if jump_t < MOLE_VIEW_JUMP_RISE_MS:
            return self._blit_victim(window, self.center,
                                     out_cubic(jump_t / MOLE_VIEW_JUMP_RISE_MS),
                                     group, lip=True)
        hop_t = jump_t - MOLE_VIEW_JUMP_RISE_MS
        if hop_t < MOLE_VIEW_JUMP_HOP_MS:
            u = hop_t / MOLE_VIEW_JUMP_HOP_MS
            lift = self.cell_size * MOLE_VIEW_JUMP_HEIGHT_FRAC * math.sin(math.pi * u)
            return self._blit_victim(window, self.center, 1.0, group, lift_px=lift,
                                     ground_dy=int(rest_dy * u))
        land_t = hop_t - MOLE_VIEW_JUMP_HOP_MS
        squash = 0
        if land_t < MOLE_VIEW_LAND_SQUASH_MS:
            p = 1.0 - land_t / MOLE_VIEW_LAND_SQUASH_MS
            squash = min(int(p * MOLE_VIEW_SQUASH_BUCKETS), MOLE_VIEW_SQUASH_BUCKETS - 1)
        return self._blit_victim(window, self.center, 1.0, group, squash=squash,
                                 ground_dy=rest_dy)

    def _healing(self):
        if self._jump_elapsed() is None or self._damage_tier() <= 0:
            return False
        return 0 < self._heal_bucket() < MOLE_VIEW_HEAL_BUCKETS

    def _seam_y(self, rect, frac):
        return rect.top + self._victim.get_height() * frac

    def _body_edge_x(self, rect, side):
        bbox = self._victim_bbox
        return rect.left + (bbox.right if side > 0 else bbox.left)

    def _draw_seam_glow(self, window, rect):
        if rect is None or not self._healing():
            return
        y = self._seam_y(rect, 1.0 - self._heal_bucket() / MOLE_VIEW_HEAL_BUCKETS)
        if y > rect.bottom:
            return
        bbox = self._victim_bbox
        w = max(int(bbox.width * MOLE_VIEW_SEAM_GLOW_W_FRAC), 4)
        h = max(int(self.cell_size * MOLE_VIEW_SEAM_GLOW_H_FRAC), 3)
        glow = _seam_glow_surface(w, h)
        window.blit(glow, (rect.left + bbox.centerx - w // 2, int(y) - h // 2),
                    special_flags=pg.BLEND_RGB_ADD)

    def _draw_seam_sparks(self, window, rect):
        if rect is None:
            return
        cell = self.cell_size
        for i, (t0, side, frac, speed, rise) in enumerate(self._seam_sparks):
            tt = (self._now - t0) / MOLE_VIEW_SPARK_MS
            if not 0.0 <= tt < 1.0:
                continue
            y = self._seam_y(rect, frac) - cell * MOLE_VIEW_SPARK_RISE_FRAC * rise * tt
            if y > rect.bottom:
                continue
            x = (self._body_edge_x(rect, side)
                 + side * cell * MOLE_VIEW_SPARK_SPEED_FRAC * speed * tt)
            r = max(int(cell * MOLE_VIEW_SPARK_R_FRAC * (1.0 - tt)), 1)
            pg.draw.circle(window, _DEBRIS_COLORS[i % len(_DEBRIS_COLORS)],
                           (int(x), int(y)), r)

    @staticmethod
    def _bounce_height(pop, elapsed):
        window = pop.t_down_ms - pop.t_up_ms + MOLE_GRACE_MS
        u = (elapsed - pop.t_up_ms) / window
        if u <= 0.0 or u >= 1.0:
            return 0.0
        if u < MOLE_VIEW_POP_APEX_FRAC:
            return _POP_APEX * out_cubic(u / MOLE_VIEW_POP_APEX_FRAC)
        fall = (u - MOLE_VIEW_POP_APEX_FRAC) / (1.0 - MOLE_VIEW_POP_APEX_FRAC)
        return _POP_APEX * (1.0 - fall * fall)

    @staticmethod
    def _pop_frame(idx, height):
        if height <= 0.0:
            return None
        bucket = int((1.0 - height / _POP_APEX) * MOLE_VIEW_SQUASH_BUCKETS)
        return idx, height, min(bucket, MOLE_VIEW_SQUASH_BUCKETS - 1)

    def _duck_pop(self, idx, elapsed):
        self._last_hit_pop = idx
        self._last_hit_anim_ms = self._anim_ms
        self._last_hit_height = self._bounce_height(self.challenge.pops[idx], elapsed)

    def _render_pop(self, elapsed):
        idx = None
        for i, pop in enumerate(self.challenge.pops):
            if pop.t_up_ms <= elapsed:
                idx = i
        if idx is None:
            return None
        if idx == self._last_hit_pop and self._last_hit_anim_ms is not None:
            duck = (self._anim_ms - self._last_hit_anim_ms) / MOLE_VIEW_RETREAT_MS
            return self._pop_frame(idx, self._last_hit_height * (1.0 - duck))
        return self._pop_frame(idx, self._bounce_height(self.challenge.pops[idx], elapsed))

    def _draw_victim(self, window, elapsed, group):
        if self._victim is None:
            return
        toss_t = self._toss_elapsed()
        if toss_t is not None:
            self._draw_toss(window, toss_t, group)
            return
        jump_t = self._jump_elapsed()
        if jump_t is not None:
            self._draw_jump(window, jump_t, group)
            return
        if elapsed < self._intro_ms:
            self._blit_victim(window, self.center, 1.0 - elapsed / self._intro_ms, group,
                              lip=True)
            return
        rendered = self._render_pop(elapsed)
        if rendered is None:
            return
        idx, height_frac, squash = rendered
        hole = self.challenge.pops[idx].hole
        if hole >= len(self._hole_px):
            return
        self._blit_victim(window, self._hole_px[hole], height_frac, group, squash, lip=True)

    def _draw_burst(self, window, items, life_ms, count, r_frac, speed_frac, jitter,
                    gravity_frac, color_fn):
        cell = self.cell_size
        g = cell * gravity_frac
        speed_base, speed_span = jitter
        for spawn_ms, x, y, floats in items:
            tt = (self._now - spawn_ms) / life_ms
            if not 0.0 <= tt < 1.0:
                continue
            t = (self._now - spawn_ms) / 1000.0
            r = max(int(cell * r_frac * (1.0 - tt)), 1)
            for j in range(count):
                ang = floats[j * 2] * 2.0 * math.pi
                speed = cell * speed_frac * (speed_base + speed_span * floats[j * 2 + 1])
                px = x + math.cos(ang) * speed * t
                py = y + math.sin(ang) * speed * t + 0.5 * g * t * t
                pg.draw.circle(window, color_fn(tt, j), (int(px), int(py)), r)

    def _draw_puffs(self, window):
        self._draw_burst(window, self._puffs, MOLE_VIEW_PUFF_MS, MOLE_VIEW_PUFF_COUNT,
                         MOLE_VIEW_PUFF_R_FRAC, MOLE_VIEW_PUFF_SPEED_FRAC,
                         MOLE_VIEW_PUFF_SPEED_JITTER, 0.0, _puff_color)

    def _draw_debris(self, window):
        self._draw_burst(window, self._debris, MOLE_VIEW_DEBRIS_MS, MOLE_VIEW_DEBRIS_COUNT,
                         MOLE_VIEW_DEBRIS_R_FRAC, MOLE_VIEW_DEBRIS_SPEED_FRAC,
                         MOLE_VIEW_DEBRIS_SPEED_JITTER, MOLE_VIEW_DEBRIS_GRAVITY_FRAC,
                         _debris_color)

    def _commit_fade_alpha(self, delay_ms, span_ms):
        if self._committed_at is None:
            return 255
        fading = self._now - self._committed_at - delay_ms
        if fading <= 0.0:
            return 255
        return max(int(255 * (1.0 - fading / span_ms)), 0)

    def _draw_casings(self, window):
        cell = self.cell_size
        w = max(int(cell * MOLE_VIEW_CASING_W_FRAC), 3)
        h = max(int(cell * MOLE_VIEW_CASING_H_FRAC), 2)
        buckets = 360 // MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        cap = self._commit_fade_alpha(0.0, MOLE_VIEW_CASING_COMMIT_FADE_MS)
        for spawn_ms, x0, y0, vx, vy, g, t_land, spin in self._casings:
            t_ms = self._now - spawn_ms
            t = min(t_ms / 1000.0, t_land)
            x = x0 + vx * t
            y = y0 + vy * t + 0.5 * g * t * t
            deg = spin * t * MOLE_VIEW_CASING_SPIN_DPS
            bucket = int(deg / MOLE_VIEW_CASING_SPIN_BUCKET_DEG) % buckets
            surf = _casing_rotated(w, h, bucket)
            alpha = min(self._casing_alpha(t_ms - t_land * 1000.0), cap)
            if alpha <= 0:
                continue
            _blit_alpha(window, surf, (int(x) - surf.get_width() // 2,
                                       int(y) - surf.get_height() // 2), alpha)

    @staticmethod
    def _casing_alpha(ground_ms):
        fading = ground_ms - MOLE_VIEW_CASING_REST_MS
        if fading <= 0.0:
            return 255
        return max(int(255 * (1.0 - fading / MOLE_VIEW_CASING_FADE_MS)), 0)

    def _draw_impacts(self, window):
        lw = max(self._cross_lw, 1)
        for spawn_ms, x, y in self._impacts:
            tt = (self._now - spawn_ms) / MOLE_VIEW_IMPACT_MS
            if not 0.0 <= tt < 1.0:
                continue
            r = max(int(self.cell_size * MOLE_VIEW_IMPACT_R_FRAC * tt), 2)
            pg.draw.circle(window, _IMPACT_COLOR, (int(x), int(y)), r, lw)

    def _draw_win_pop(self, window, group):
        if self._win_ms is None or self._now - self._win_ms >= MOLE_VIEW_WIN_POP_MS:
            return
        r = max(int(self.cell_size * MOLE_VIEW_WIN_POP_R_FRAC), 8)
        px = self._last_hit_px if self._last_hit_px is not None else self.center
        window.blit(_win_pop_surface(r), (int(px[0]) - r + group[0],
                                          int(px[1]) - r + group[1]),
                    special_flags=pg.BLEND_RGB_ADD)

    def _draw_muzzle(self, window):
        if self._flash_ms is None or self._now - self._flash_ms >= MOLE_VIEW_MUZZLE_MS:
            return
        r = max(int(self.cell_size * MOLE_VIEW_MUZZLE_FRAC), 4)
        window.blit(_muzzle_surface(r), (int(self._flash_px[0]) - r,
                                         int(self._flash_px[1]) - r),
                    special_flags=pg.BLEND_RGB_ADD)

    def _crosshair_fade(self):
        if self._committed_at is None:
            return 1.0
        return max(1.0 - (self._now - self._committed_at) / MOLE_VIEW_CROSS_OUT_MS, 0.0)

    def _draw_crosshair(self, window):
        fade = self._crosshair_fade()
        if fade <= 0.0:
            return
        mx, my = pg.mouse.get_pos()
        if self._flash_ms is not None:
            t = self._now - self._flash_ms
            if t < MOLE_VIEW_KICK_MS:
                my -= int(self._kick_amp * (1.0 - t / MOLE_VIEW_KICK_MS))
        bloom = 0.0
        if self._last_shot_ms is not None:
            t = self._now - self._last_shot_ms
            if t < MOLE_RECOIL_LOCKOUT_MS:
                bloom = 1.0 - t / MOLE_RECOIL_LOCKOUT_MS
        if fade >= 1.0:
            glow = _cross_glow_surface(
                max(int(self.cell_size * MOLE_VIEW_CROSS_GLOW_FRAC), 6))
            window.blit(glow, (mx - glow.get_width() // 2, my - glow.get_height() // 2),
                        special_flags=pg.BLEND_RGB_ADD)
        surf = _crosshair_surface(self._cross_arm, self._cross_gap, self._cross_lw,
                                  round(bloom * MOLE_VIEW_BLOOM_BUCKETS),
                                  round((1.0 - fade) * MOLE_VIEW_CROSS_OUT_BUCKETS))
        _blit_alpha(window, surf,
                    (mx - surf.get_width() // 2, my - surf.get_height() // 2),
                    int(255 * fade))

    def _draw_hitboxes(self, window, elapsed):
        if self._affine is None:
            return
        up = self.challenge.pop_up_at(elapsed)
        live_hole = self.challenge.pops[up].hole if up is not None else None
        rx = abs(self._affine[2]) * MOLE_HITBOX_RX_FRAC
        ry = abs(self._affine[3]) * MOLE_HITBOX_RY_FRAC
        lift = -MOLE_HITBOX_CY_FRAC if self._affine[3] < 0 else MOLE_HITBOX_CY_FRAC
        for i, (row, col) in enumerate(self._hole_squares):
            if elapsed - i * MOLE_VIEW_HOLE_STAGGER_MS <= 0.0:
                continue
            px = self._board_to_px(row + 0.5 + lift, col + 0.5)
            rect = pg.Rect(int(px[0] - rx), int(px[1] - ry), int(2 * rx), int(2 * ry))
            hot = i == live_hole
            pg.draw.ellipse(window, _HITBOX_ACTIVE_COLOR if hot else _HITBOX_COLOR, rect,
                            MOLE_VIEW_HITBOX_ACTIVE_LW if hot else MOLE_VIEW_HITBOX_LW)

    def _draw_pips(self, window, group):
        alpha = self._commit_fade_alpha(MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS)
        if alpha <= 0:
            return
        n = self.challenge.hits_required
        filled = min(self._progress, n)
        w, h, gap = self._pip_w, self._pip_h, self._pip_gap
        total = n * w + (n - 1) * gap
        x = self.center[0] - total // 2 + group[0]
        y = self.center[1] + int(self.cell_size * MOLE_VIEW_PIP_OFFSET_FRAC) + group[1]
        radius = max(h // MOLE_VIEW_PIP_RADIUS_DIV, 2)
        for i in range(n):
            if i < filled:
                fill, border = Colors.accent, Colors.accent_hi
            else:
                fill, border = Colors.surface, Colors.border_strong
            surf = rounded_rect_surface((w, h), radius, fill, border=border, border_width=1)
            _blit_alpha(window, surf, (x + i * (w + gap), y), alpha)

    def _draw_strike_crosses(self, window, group):
        if self._geom is None or self._from_sq is None:
            return
        alpha = self._commit_fade_alpha(MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS)
        if alpha <= 0:
            return
        ax, ay = self._geom(self._from_sq)
        size, gap = self._strike_size, self._strike_gap
        total = MOLE_MAX_WHIFFS * size + (MOLE_MAX_WHIFFS - 1) * gap
        x = ax - total // 2 + group[0]
        y = ay + int(self.cell_size * MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC) + group[1]
        struck = min(self._miss_count, MOLE_MAX_WHIFFS)
        for i in range(MOLE_MAX_WHIFFS):
            surf = _strike_cross_surface(size, i < struck)
            _blit_alpha(window, surf, (x + i * (size + gap), y), alpha)
