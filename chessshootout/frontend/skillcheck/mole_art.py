import math
from collections.abc import Callable
from typing import cast

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


def _pit_render(rim_color: str | pg.Color, glow_alpha: int,
                rim_scale: float = 1.0) -> Callable[[pg.Surface, int], None]:
    """
    Give the drawing routine for one mole pit -- a soft halo, a coloured rim
    and the dark mouth punched through it. Every pit the whack check shows
    (resting, telegraphed, about to be fatal) is this one shape in different
    colours, which is what makes the holes read as one set

    :param rim_color: colour of the ring around the mouth, as a hex token from
        Colors or a ready pg.Color
    :param glow_alpha: opacity from 0 to 255 of the halo that bleeds outside
        the rim
    :param rim_scale: how much thicker than usual to draw the rim, used to make
        a pit that must not be missed read at a glance
    :returns: a render callback in the shape supersample expects
    """
    def render(surf: pg.Surface, k: int) -> None:
        """
        Lay down the halo, the rim and the dark mouth on the oversized canvas

        :param surf: oversized canvas being drawn on
        :param k: how many times bigger that canvas is than the finished pit;
            unused here, since every measurement is taken from the canvas
        """
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


def pit_surface(rx: int, ry: int, accent: str = Colors.accent) -> pg.Surface:
    """
    The resting pit a mole can pop out of, the hole whack-a-mole digs into the
    board around a capture. A check draws up to five of these every frame, so
    each size and colour is built once and then handed out from the module
    cache

    :param rx: half-width of the pit in pixels
    :param ry: half-height in pixels, smaller than rx so the hole lies flat on
        the board
    :param accent: rim colour as a hex token from Colors; the spectate mirror
        passes its own so a watched check never looks like the player's
    :returns: the shared pit for that size and colour
    """
    def build() -> pg.Surface:
        """
        Draw the pit the first time this size and colour is asked for

        :returns: the finished pit
        """
        return supersample((2 * rx, 2 * ry),
                           _pit_render(accent, MOLE_VIEW_PIT_GLOW_ALPHA))
    return cast(pg.Surface,
                memoized_surface(_MOLE_STATIC_CACHE, ("pit", rx, ry, accent), build))


def pit_mouth(rx: int, ry: int) -> tuple[int, int]:
    """
    Measure the dark opening inside a pit, which is the edge a climbing mole is
    clipped against. It is worked out from the same insets and rim width the
    pit is drawn with, so the body appears exactly at the hole rather than
    floating over it

    :param rx: half-width of the pit in pixels
    :param ry: half-height of the pit in pixels
    :returns: (half-width, half-height) of the opening in pixels
    """
    w, h = 2 * rx * SUPERSAMPLE, 2 * ry * SUPERSAMPLE
    inset_x = int(w * MOLE_VIEW_PIT_INSET_FRAC)
    inset_y = int(h * MOLE_VIEW_PIT_INSET_FRAC)
    rim = max(int((h - 2 * inset_y) * MOLE_VIEW_PIT_RIM_FRAC), 1)
    return (max((w // 2 - inset_x - rim) // SUPERSAMPLE, 1),
            max((h // 2 - inset_y - rim) // SUPERSAMPLE, 1))


def emerge_mask(w: int, rx: int, ry: int, fade: int) -> pg.Surface:
    """
    The stencil that makes a mole look like it is climbing out of the ground
    rather than sliding up behind a straight cut: an arch shaped like the pit
    mouth, softening away over a few rows. It is multiplied over the sprite,
    and like every plate here it is drawn once and cached

    :param w: width of the sprite it will be multiplied over, in pixels
    :param rx: half-width of the pit opening in pixels
    :param ry: half-height of that opening, the depth of the arch
    :param fade: how many rows the soft lower edge takes
    :returns: the shared mask, meant for a BLEND_RGBA_MULT blit
    """
    def build() -> pg.Surface:
        """
        Draw the arch column by column the first time this shape is asked for

        :returns: the finished mask
        """
        mask = pg.Surface((w, ry + fade + 1), pg.SRCALPHA)
        half = w / 2.0
        for x in range(w):
            dx = abs(x + 0.5 - half) / rx
            arc = round(ry * math.sqrt(1.0 - dx * dx)) if dx < 1.0 else 0
            mask.fill(_KEEP, (x, 0, 1, arc))
            for i in range(fade):
                mask.fill((*_KEEP, int(255 * (1.0 - (i + 1) / fade))), (x, arc + i, 1, 1))
        return mask
    return cast(pg.Surface,
                memoized_surface(_MOLE_STATIC_CACHE, ("emerge", w, rx, ry, fade), build))


def pit_front_surface(rx: int, ry: int, accent: str = Colors.accent) -> pg.Surface:
    """
    The near lip of a pit, drawn on top of the mole so the body sits inside the
    hole instead of on the board. Sliced out of the finished pit rather than
    drawn again, so the lip can never disagree with the hole it belongs to

    :param rx: half-width of the pit in pixels
    :param ry: half-height of the pit in pixels
    :param accent: rim colour as a hex token from Colors, matching the pit
    :returns: the shared lower half of that pit
    """
    def build() -> pg.Surface:
        """
        Cut the lower half out of the pit the first time it is asked for

        :returns: the finished lip
        """
        pit = pit_surface(rx, ry, accent)
        half = max(pit.get_height() // 2, 1)
        front = pg.Surface((pit.get_width(), half), pg.SRCALPHA)
        front.blit(pit, (0, half - pit.get_height()))
        return front
    return cast(pg.Surface,
                memoized_surface(_MOLE_STATIC_CACHE, ("pit_front", rx, ry, accent), build))


def seam_band_surface(w: int, h: int) -> pg.Surface:
    """
    The hot line where a torn mole is knitting itself back together, drawn
    across the join while it heals after a check the player lost. It is
    brightest in the middle and falls off to nothing at both edges

    :param w: width of the band in pixels, the sprite's width
    :param h: height of the band in pixels, how tall the hot line looks
    :returns: the shared band, meant for a BLEND_RGB_ADD blit
    """
    def build() -> pg.Surface:
        """
        Draw the band row by row the first time this size is asked for

        :returns: the finished band
        """
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
    return cast(pg.Surface, memoized_surface(_MOLE_STATIC_CACHE, ("seam", w, h), build))


def seam_glow_surface(w: int, h: int) -> pg.Surface:
    """
    The wider bloom that travels with a healing seam, spilling past the mole's
    body so the join reads from across the board. Every pixel is placed by
    hand, which is why it exists once per size and lives in the cache

    :param w: width of the glow in pixels, drawn wider than the body
    :param h: height of the glow in pixels
    :returns: the shared glow, meant for a BLEND_RGB_ADD blit
    """
    def build() -> pg.Surface:
        """
        Fill the glow pixel by pixel the first time this size is asked for

        :returns: the finished glow
        """
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
    return cast(pg.Surface, memoized_surface(_MOLE_STATIC_CACHE, ("seamglow", w, h), build))


def _cross_blade_points(c: float, ux: int, uy: int, inner: float, outer: float,
                        tip_half: float, base_half: float) -> tuple[tuple[float, float], ...]:
    """
    Corner the wedge that makes up one arm of the crosshair: narrow where it
    points at the middle, wider at its outer end. Four of them, one per
    direction, are the whole sight

    :param c: centre of the canvas in pixels, both across and down
    :param ux: horizontal part of the unit direction this arm points along
    :param uy: vertical part of that same direction
    :param inner: distance from the centre the arm starts at, in pixels
    :param outer: distance it reaches out to, in pixels
    :param tip_half: half-thickness at the inner end, in pixels
    :param base_half: half-thickness at the outer end, in pixels
    :returns: the four corners in order, ready for a polygon
    """
    px, py = -uy, ux
    return ((c + ux * inner + px * tip_half, c + uy * inner + py * tip_half),
            (c + ux * outer + px * base_half, c + uy * outer + py * base_half),
            (c + ux * outer - px * base_half, c + uy * outer - py * base_half),
            (c + ux * inner - px * tip_half, c + uy * inner - py * tip_half))


def _cross_arc_points(c: float, r_in: float, r_out: float, a0: float,
                      a1: float) -> list[tuple[float, float]]:
    """
    Trace one thick arc of the crosshair's ring as a closed outline -- out
    along the far radius and back along the near one. Pygame draws no thick
    arcs, so the ring is four polygons walked at this resolution

    :param c: centre of the canvas in pixels, both across and down
    :param r_in: near radius of the arc in pixels
    :param r_out: far radius of the arc in pixels
    :param a0: angle the arc starts at, in radians
    :param a1: angle it ends at, in radians
    :returns: the outline points in order, ready for a polygon
    """
    segs = MOLE_VIEW_CROSS_ARC_SEGS
    angles = [a0 + (a1 - a0) * i / segs for i in range(segs + 1)]
    outer = [(c + r_out * math.cos(a), c + r_out * math.sin(a)) for a in angles]
    inner = [(c + r_in * math.cos(a), c + r_in * math.sin(a)) for a in reversed(angles)]
    return outer + inner


def _render_cross_blades(surf: pg.Surface, k: int, c: float, gap: float, arm: float,
                         tip_half: float, base_half: float) -> None:
    """
    Draw the crosshair's four arms twice: once fattened in the background
    colour, then again in the ink colour on top. That dark outline is what
    keeps the sight readable over a light square as well as a dark one

    :param surf: oversized canvas being drawn on
    :param k: how many times bigger that canvas is than the finished sight,
        which every length here is scaled by
    :param c: centre of the canvas in pixels
    :param gap: hole left open around the middle, in finished pixels
    :param arm: length of one arm, in finished pixels
    :param tip_half: half-thickness at the inner end, in finished pixels
    :param base_half: half-thickness at the outer end, in finished pixels
    """
    for color, pad in ((_CROSS_EDGE, k), (_CROSS_COLOR, 0)):
        for ux, uy in _AXES:
            pg.draw.polygon(surf, color, _cross_blade_points(
                c, ux, uy, gap * k - pad, (gap + arm) * k + pad,
                tip_half * k + pad, base_half * k + pad))


def crosshair_surface(arm: int, gap: int, lw: int, bloom_bucket: int,
                      out_bucket: int) -> pg.Surface:
    """
    The gun sight the player aims a whack check with: four blades, a ringed
    corner arc and a dot in the middle. It blooms open after every shot while
    the recoil lockout runs and shrinks away as the check ends, and both of
    those are bucketed so the cache holds a handful of variants instead of one
    per frame

    :param arm: length of one blade in pixels at rest
    :param gap: hole left open around the middle, in pixels
    :param lw: stroke width the arc is derived from, in pixels
    :param bloom_bucket: how far open the recoil bloom is, 0 to
        MOLE_VIEW_BLOOM_BUCKETS
    :param out_bucket: how far into shrinking away the sight is, 0 to
        MOLE_VIEW_CROSS_OUT_BUCKETS
    :returns: the shared sight for exactly that shape and state
    """
    def build() -> pg.Surface:
        """
        Work the sight's proportions out and draw it, the first time this exact
        combination is asked for

        :returns: the finished sight
        """
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

        def render(surf: pg.Surface, k: int) -> None:
            """
            Lay the blades, the four corner arcs and the centre dot down on the
            oversized canvas

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the finished
                sight, which every length here is scaled by
            """
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
    return cast(pg.Surface, memoized_surface(_MOLE_STATIC_CACHE, key, build))


def _radial_glow(r: int, color: pg.Color, gain_scale: float) -> pg.Surface:
    """
    A round bloom that is brightest at its middle and dies out at the rim,
    which every light the whack check throws is made from -- the muzzle flash,
    the sight's halo, the burst on the winning hit

    :param r: radius of the glow in pixels
    :param color: colour at the very centre, thinned out towards the rim
    :param gain_scale: overall brightness, 1.0 reaching the full colour
    :returns: an opaque glow surface, meant for a BLEND_RGB_ADD blit
    """
    surf = pg.Surface((2 * r, 2 * r))
    for i in range(r, 0, -1):
        gain = (1.0 - i / r) ** 2 * gain_scale
        pg.draw.circle(surf, (int(color.r * gain), int(color.g * gain), int(color.b * gain)),
                       (r, r), i)
    return surf


def cross_glow_surface(r: int) -> pg.Surface:
    """
    The faint halo sitting under the crosshair, which stops the sight from
    disappearing into a busy or pale square

    :param r: radius of the halo in pixels
    :returns: the shared halo, meant for a BLEND_RGB_ADD blit
    """
    return cast(pg.Surface, memoized_surface(
        _MOLE_STATIC_CACHE, ("crossglow", r),
        lambda: _radial_glow(r, _CROSS_GLOW, MOLE_VIEW_CROSS_GLOW_GAIN)))


def _danger_render(bucket: int) -> Callable[[pg.Surface, int], None]:
    """
    Give the drawing routine for a pit whose mole simply cannot be missed if
    the quota is still to be met. It alarms between two frames -- a loss-red
    rest and a thick white flash -- rather than breathing like an ordinary
    telegraph

    :param bucket: which of the two frames to draw, 1 being the flash
    :returns: a render callback in the shape supersample expects
    """
    hot = bucket >= 1
    rim = pg.Color(Colors.text) if hot else pg.Color(Colors.loss)
    alpha = 255 if hot else MOLE_VIEW_PIT_GLOW_ALPHA
    scale = MOLE_VIEW_DANGER_RIM_SCALE if hot else 1.0
    return _pit_render(rim, alpha, scale)


def _telegraph_render(bucket: int, accent: str) -> Callable[[pg.Surface, int], None]:
    """
    Give the drawing routine for a pit warming up before its mole appears. The
    rim washes towards white and the halo strengthens as the pulse climbs,
    which is the warning the player aims on

    :param bucket: step of the pulse, 0 to MOLE_VIEW_PULSE_BUCKETS - 1
    :param accent: rim colour at the bottom of the pulse, as a hex token from
        Colors
    :returns: a render callback in the shape supersample expects
    """
    frac = bucket / (MOLE_VIEW_PULSE_BUCKETS - 1)
    blend = MOLE_VIEW_TELE_WHITE_MIN + (1.0 - MOLE_VIEW_TELE_WHITE_MIN) * frac
    rim = pg.Color(accent).lerp(pg.Color(Colors.text), blend)
    alpha = int(MOLE_VIEW_PIT_GLOW_ALPHA
                + (255 - MOLE_VIEW_PIT_GLOW_ALPHA) * frac * MOLE_VIEW_TELE_ALPHA_GAIN)
    return _pit_render(rim, alpha)


def pit_telegraph_surface(rx: int, ry: int, bucket: int, danger: bool = False,
                          accent: str = Colors.accent) -> pg.Surface:
    """
    The lit pit that warns a mole is about to appear, in either of its two
    voices: an ordinary breathing telegraph, or the alarm on a pop the player
    must hit to still meet the quota. One surface per size, step and voice,
    kept in the module cache

    :param rx: half-width of the pit in pixels
    :param ry: half-height of the pit in pixels
    :param bucket: step of the pulse, which fixes how bright this frame is
    :param danger: True for the pop that cannot be missed
    :param accent: rim colour as a hex token from Colors, ignored on a danger
        pit, which has its own palette
    :returns: the shared telegraph pit for that size, step and voice
    """
    def build() -> pg.Surface:
        """
        Draw the lit pit the first time this combination is asked for

        :returns: the finished pit
        """
        render = _danger_render(bucket) if danger else _telegraph_render(bucket, accent)
        return supersample((2 * rx, 2 * ry), render)
    key = ("pit_tele", rx, ry, bucket, danger, accent)
    return cast(pg.Surface, memoized_surface(_MOLE_STATIC_CACHE, key, build))


def muzzle_surface(r: int) -> pg.Surface:
    """
    The flash under the crosshair the instant a shot goes off: a hot bloom with
    four rays crossing it, which is what makes a whack shot feel fired rather
    than clicked

    :param r: radius of the flash in pixels
    :returns: the shared flash, meant for a BLEND_RGB_ADD blit
    """
    def build() -> pg.Surface:
        """
        Draw the bloom and its rays the first time this size is asked for

        :returns: the finished flash
        """
        hot = pg.Color(Colors.amber_hi)
        surf = _radial_glow(r, hot, 1.0)
        for dx, dy in _AXES:
            pg.draw.line(surf, hot, (r, r), (r + dx * r, r + dy * r),
                         max(r // MOLE_VIEW_MUZZLE_RAY_W_DIV, 1))
        return surf
    return cast(pg.Surface, memoized_surface(_MOLE_STATIC_CACHE, ("muzzle", r), build))


def win_pop_surface(r: int) -> pg.Surface:
    """
    The burst thrown at the hit that fills the quota and wins the check, played
    where that last mole was standing

    :param r: radius of the burst in pixels
    :returns: the shared burst, meant for a BLEND_RGB_ADD blit
    """
    return cast(pg.Surface, memoized_surface(
        _MOLE_STATIC_CACHE, ("winpop", r),
        lambda: _radial_glow(r, pg.Color(Colors.amber), MOLE_VIEW_WIN_POP_GAIN)))


def _casing_surface(w: int, h: int) -> pg.Surface:
    """
    One spent shell, upright and unturned: a brass body with a brighter tip.
    Every shot throws one of these out to sell the gun as a real weapon

    :param w: length of the casing in pixels
    :param h: thickness of the casing in pixels
    :returns: the shared upright casing for that size
    """
    def build() -> pg.Surface:
        """
        Draw the casing the first time this size is asked for

        :returns: the finished casing
        """
        surf = pg.Surface((w, h), pg.SRCALPHA)
        surf.fill(pg.Color(Colors.amber))
        pg.draw.rect(surf, pg.Color(Colors.amber_hi),
                     pg.Rect(0, 0, max(w // MOLE_VIEW_CASING_TIP_DIV, 1), h))
        return surf
    return cast(pg.Surface, memoized_surface(_MOLE_STATIC_CACHE, ("casing", w, h), build))


def casing_rotated(w: int, h: int, bucket: int) -> pg.Surface:
    """
    A spent shell at one step of its tumble. The spin is quantised to
    MOLE_VIEW_CASING_SPIN_BUCKET_DEG so a handful of turned copies cover the
    whole flight, instead of a fresh rotation every frame for every casing in
    the air

    :param w: length of the casing in pixels
    :param h: thickness of the casing in pixels
    :param bucket: which step of the turn, counted in whole buckets from
        upright
    :returns: the shared casing turned to that step
    """
    def build() -> pg.Surface:
        """
        Turn the upright casing the first time this step is asked for

        :returns: the finished turned casing
        """
        base = _casing_surface(w, h)
        deg = bucket * MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        return base if deg == 0 else pg.transform.rotate(base, deg)
    return cast(pg.Surface,
                memoized_surface(_MOLE_STATIC_CACHE, ("casing_rot", w, h, bucket), build))
