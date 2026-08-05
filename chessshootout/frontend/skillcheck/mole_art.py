import math

import pygame as pg

from chessshootout.frontend.visual.cache import new_size_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import SUPERSAMPLE, supersample

MOLE_VIEW_PIT_RIM_FRAC = 0.14
MOLE_VIEW_PIT_INSET_FRAC = 0.06
MOLE_VIEW_PIT_GLOW_ALPHA = 60
MOLE_VIEW_PULSE_BUCKETS = 6
MOLE_VIEW_TELE_WHITE_MIN = 0.35
MOLE_VIEW_TELE_ALPHA_GAIN = 0.5
MOLE_VIEW_DANGER_RIM_SCALE = 1.6
MOLE_VIEW_CROSS_BLADE_W_FRAC = 0.11
MOLE_VIEW_CROSS_TIP_W_FRAC = 0.035
MOLE_VIEW_CROSS_ARC_PAD_FRAC = 0.42
MOLE_VIEW_CROSS_ARC_W_FRAC = 0.9
MOLE_VIEW_CROSS_ARC_SPAN_DEG = 55.0
MOLE_VIEW_CROSS_ARC_SEGS = 24
MOLE_VIEW_CROSS_DOT_FRAC = 0.18
MOLE_VIEW_CROSS_GLOW_GAIN = 0.30
MOLE_VIEW_CROSS_OUT_SCALE = 0.72
MOLE_VIEW_CROSS_OUT_BUCKETS = 6
MOLE_VIEW_BLOOM_BUCKETS = 8
MOLE_VIEW_BLOOM_SPREAD_FRAC = 0.62
MOLE_VIEW_BLOOM_SPIN_DEG = 30.0
MOLE_VIEW_MUZZLE_RAY_W_DIV = 6
MOLE_VIEW_WIN_POP_GAIN = 0.85
MOLE_VIEW_SEAM_WHITE_CORE = 0.6
MOLE_VIEW_SEAM_GLOW_CORE = 0.8
MOLE_VIEW_CASING_TIP_DIV = 4
MOLE_VIEW_CASING_SPIN_BUCKET_DEG = 20

PIT_DARK = pg.Color(Colors.well_deep)
_CROSS_COLOR = pg.Color(Colors.text)
_CROSS_EDGE = pg.Color(Colors.bg)
_CROSS_ARC = pg.Color(Colors.accent)
_CROSS_ARC_HOT = pg.Color(Colors.amber_hi)
_CROSS_DOT = pg.Color(Colors.amber_hi)
_CROSS_GLOW = pg.Color(Colors.accent)

_AXES = ((1, 0), (-1, 0), (0, 1), (0, -1))

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
        pg.draw.ellipse(surf, PIT_DARK, outer.inflate(-2 * rim_w, -2 * rim_w))
    return render


def pit_surface(rx, ry):
    def build():
        return supersample((2 * rx, 2 * ry),
                           _pit_render(Colors.accent, MOLE_VIEW_PIT_GLOW_ALPHA))
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit", rx, ry), build)


def pit_mouth(rx, ry):
    w, h = 2 * rx * SUPERSAMPLE, 2 * ry * SUPERSAMPLE
    inset_x = int(w * MOLE_VIEW_PIT_INSET_FRAC)
    inset_y = int(h * MOLE_VIEW_PIT_INSET_FRAC)
    rim = max(int((h - 2 * inset_y) * MOLE_VIEW_PIT_RIM_FRAC), 1)
    return (max((w // 2 - inset_x - rim) // SUPERSAMPLE, 1),
            max((h // 2 - inset_y - rim) // SUPERSAMPLE, 1))


def emerge_mask(w, rx, ry, fade):
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


def pit_front_surface(rx, ry):
    def build():
        pit = pit_surface(rx, ry)
        half = max(pit.get_height() // 2, 1)
        front = pg.Surface((pit.get_width(), half), pg.SRCALPHA)
        front.blit(pit, (0, half - pit.get_height()))
        return front
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit_front", rx, ry), build)


def seam_band_surface(w, h):
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


def seam_glow_surface(w, h):
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


def crosshair_surface(arm, gap, lw, bloom_bucket, out_bucket):
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


def cross_glow_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r))
        for i in range(r, 0, -1):
            gain = (1.0 - i / r) ** 2 * MOLE_VIEW_CROSS_GLOW_GAIN
            col = (int(_CROSS_GLOW.r * gain), int(_CROSS_GLOW.g * gain),
                   int(_CROSS_GLOW.b * gain))
            pg.draw.circle(surf, col, (r, r), i)
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("crossglow", r), build)


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


def pit_telegraph_surface(rx, ry, bucket, danger=False):
    def build():
        render = _danger_render(bucket) if danger else _telegraph_render(bucket)
        return supersample((2 * rx, 2 * ry), render)
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit_tele", rx, ry, bucket, danger), build)


def muzzle_surface(r):
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


def win_pop_surface(r):
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


def casing_rotated(w, h, bucket):
    def build():
        base = _casing_surface(w, h)
        deg = bucket * MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        return base if deg == 0 else pg.transform.rotate(base, deg)
    return memoized_surface(_MOLE_STATIC_CACHE, ("casing_rot", w, h, bucket), build)
