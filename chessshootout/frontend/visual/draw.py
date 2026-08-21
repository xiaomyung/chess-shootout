import math
from collections.abc import Callable
from typing import cast

import pygame as pg

from chessshootout.frontend.visual.cache import (
    new_size_cache, memoized_surface, render_text,
)
from chessshootout.frontend.visual.colors import Colors

SUPERSAMPLE = 4
GLOW_BLUR_PASSES = 3
SQRT2 = 1.41421356

_HALF_RGBA_MULT = (128, 128, 128, 128)
_CUT_BORDER_SCALE = 1.25

NOTCH_ZERO_EPSILON = 0.005

TOOLTIP_PAD_X = 10
TOOLTIP_PAD_Y = 5
TOOLTIP_RADIUS = 6


def scale_floor(value: int, scale: float, floor: int = 1) -> int:
    """
    Fit one design-time pixel size to the window the player actually has, never
    letting it shrink past the point of being legible. Paddings, corner cuts,
    icon boxes and font sizes across the whole UI are sized through this, which
    is what keeps a small window usable instead of merely smaller

    :param value: the size in pixels as drawn at the reference window size
    :param scale: how big this window is against the reference, 1.0 being it
    :param floor: smallest result allowed, however far the window shrinks
    :returns: the scaled size in whole pixels, never below floor
    """
    return max(int(value * scale), floor)


def cosine_pulse(now_ms: float, period_ms: float) -> float:
    """
    A smooth breathing value for anything that should throb rather than blink
    -- the low-time clock, the sharing dot, danger cues in the skill checks.
    It eases at both ends, so the loop has no visible seam

    :param now_ms: current time in milliseconds -- pygame ticks or a
        fractional animation clock
    :param period_ms: how long one full breath takes, in milliseconds
    :returns: value from 0.0 at the start of the cycle up to 1.0 at its middle
    """
    phase = (now_ms % period_ms) / period_ms
    return (1 - math.cos(2 * math.pi * phase)) / 2


def notch_readout_slot_w(font: pg.font.Font) -> int:
    """
    Reserve room for the percentage printed beside a notch strip, measured at
    its widest so the notches keep still while the number changes

    :param font: the font the readout is drawn in
    :returns: width in pixels to keep clear for the readout
    """
    return font.size("100%")[0]


def notch_geometry(width: int, count: int, cell_w: int, gap: int, slot_w: int,
                   readout_gap: int) -> tuple[int, int]:
    """
    Place the row of notch cells that stands in for a slider on the volume
    controls. The strip is pushed to the right, up against the readout it
    labels, so the row reads as one block however wide the panel is

    :param width: full width of the row the strip sits in, in pixels
    :param count: how many notch cells there are
    :param cell_w: width of one cell in pixels
    :param gap: space between two cells in pixels
    :param slot_w: width already reserved for the readout
    :param readout_gap: space between the last cell and the readout
    :returns: the strip's left offset within the row, and its total width
    """
    total = count * cell_w + (count - 1) * gap
    return width - slot_w - readout_gap - total, total


def notch_value_from_click(pos_x: int, band_x: int, step: int, count: int,
                           current: float) -> float:
    """
    Work out what a click on the notch strip means. Clicking a cell sets the
    value to that cell, and clicking the first cell when it is already the
    value drops to zero -- which is how the first notch doubles as a mute

    :param pos_x: click position in window pixels, horizontal only
    :param band_x: left edge of the notch strip in window pixels
    :param step: distance from one cell's left edge to the next, in pixels
    :param count: how many notch cells there are
    :param current: value in force right now, from 0.0 to 1.0
    :returns: the value the click asks for, from 0.0 to 1.0
    """
    i = max(0, min(count - 1, (pos_x - band_x) // step))
    target = (i + 1) / count
    if i == 0 and abs(current - target) < NOTCH_ZERO_EPSILON:
        return 0.0
    return target


def supersample(size: int | tuple[int, int], render: Callable[[pg.Surface, int], None],
                scale: int = SUPERSAMPLE) -> pg.Surface:
    """
    The house way of getting smooth edges: draw the shape several times too
    big, then shrink it down. Pygame has no antialiased fill, so every
    hand-drawn shape in the game -- icons, panels, dials, markers -- is made
    this way and then cached, since the oversized draw is the expensive part

    :param size: finished size in pixels, one number for a square
    :param render: draws the shape, given the oversized canvas and the factor
        it was enlarged by, so it can scale its own coordinates and widths
    :param scale: how many times oversized to draw; higher is smoother
    :returns: the finished shape at the requested size, with an alpha channel
    """
    if isinstance(size, int):
        size = (size, size)
    big = pg.Surface((size[0] * scale, size[1] * scale), pg.SRCALPHA)
    render(big, scale)
    return pg.transform.smoothscale(big, size)


def smoothstep(x: float) -> float:
    """
    An ease that starts and ends at rest, used for fades and short reveals
    where a linear ramp would look mechanical

    :param x: progress from 0.0 to 1.0, values outside are clamped in
    :returns: eased progress from 0.0 to 1.0
    """
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _pyramid_blur(surface: pg.Surface, passes: int) -> pg.Surface:
    """
    Blur by repeatedly halving a surface and then blowing it back up, the
    cheap trick that stands in for a real blur kernel. The surface is padded
    to a size the halving divides exactly, then cropped back afterwards

    :param surface: the picture to blur, left untouched
    :param passes: how many halvings to do; each one doubles the softness
    :returns: a new blurred surface the same size as the original
    """
    w, h = surface.get_size()
    factor = 1 << passes
    pw, ph = -(-w // factor) * factor, -(-h // factor) * factor
    ox, oy = (pw - w) // 2, (ph - h) // 2
    work = surface
    if (pw, ph) != (w, h):
        work = pg.Surface((pw, ph), pg.SRCALPHA)
        work.blit(surface, (ox, oy))
    for _ in range(passes):
        work = pg.transform.smoothscale(work, (work.get_width() // 2, work.get_height() // 2))
    for _ in range(passes):
        work = pg.transform.smoothscale(work, (work.get_width() * 2, work.get_height() * 2))
    if (pw, ph) != (w, h):
        return work.subsurface(pg.Rect(ox, oy, w, h)).copy()
    return work


def soft_blur(surface: pg.Surface, passes: int = GLOW_BLUR_PASSES) -> pg.Surface:
    """
    The blur behind every glow in the game -- muzzle flashes, the rim light on
    the black pieces, the halo under the result text. It blurs the picture
    once forwards and once mirrored and averages the two, because the halving
    trick alone drags the light off-centre

    :param surface: the picture to blur, left untouched
    :param passes: softness, as the number of halvings; zero returns the
        original surface unchanged
    :returns: the blurred surface, ready to be laid under the original
    """
    if passes <= 0:
        return surface
    forward = _pyramid_blur(surface, passes)
    mirror = pg.transform.flip(
        _pyramid_blur(pg.transform.flip(surface, True, True), passes), True, True)
    forward.fill(_HALF_RGBA_MULT, special_flags=pg.BLEND_RGBA_MULT)
    mirror.fill(_HALF_RGBA_MULT, special_flags=pg.BLEND_RGBA_MULT)
    forward.blit(mirror, (0, 0), special_flags=pg.BLEND_RGBA_ADD)
    return forward


_INFINITY_CACHE = new_size_cache()


def infinity_surface(height: float, color: str) -> pg.Surface:
    """
    The sideways figure of eight that stands for an untimed game, drawn wherever
    a clock or a time control would otherwise print a number. It is drawn as a
    curve rather than typed, so it matches at any size and in any font

    :param height: wanted height in pixels; the width follows from it
    :param color: ink colour as a hex token from Colors
    :returns: the shared mark at that size and colour
    """
    h = max(int(height), 6)
    w = int(h * 1.7)
    th = max(h * 0.14, 2.2)

    def build() -> pg.Surface:
        """
        Draw the mark the first time this size and colour is asked for

        :returns: the finished mark
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Walk the lemniscate and stamp a dot along it, which gives the
            curve its even, rounded stroke

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the mark
            """
            big_w, big_h = surf.get_size()
            cx, cy = big_w / 2, big_h / 2
            ax, ay = big_w * 0.355, big_h * 0.275
            r = max(th * k / 2, 1.5)
            col = pg.Color(color)
            n = 480
            for i in range(n):
                t = 2 * math.pi * i / n
                d = 1 + math.sin(t) ** 2
                x = cx + ax * math.cos(t) / d
                y = cy + ay * math.sin(t) * math.cos(t) / d / 0.3536
                pg.draw.circle(surf, col, (x, y), r)
        return supersample((w, h), render, scale=8)
    return cast(pg.Surface, memoized_surface(_INFINITY_CACHE, (h, str(color)), build))


_CIRCLE_CACHE = new_size_cache()


def circle_surface(diameter: int, color: str) -> pg.Surface:
    """
    A filled dot with a smooth edge, the workhorse behind status dots,
    connection lights and chip bullets. Pygame's own circle has a hard edge,
    so this one is oversampled and shared instead of drawn per frame

    :param diameter: wanted width and height in pixels
    :param color: fill colour as a hex token from Colors
    :returns: the shared dot at that size and colour
    """
    d = max(int(diameter), 1)

    def build() -> pg.Surface:
        """
        Draw the dot the first time this size and colour is asked for

        :returns: the finished dot
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Fill the whole oversized canvas with one circle

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the dot
            """
            r = surf.get_width() / 2
            pg.draw.circle(surf, pg.Color(color), (r, r), r)
        return supersample(d, render)
    return cast(pg.Surface, memoized_surface(_CIRCLE_CACHE, (d, color), build))


_STRIKE_PIP_CACHE = new_size_cache()


def strike_pip_surface(size: int, struck: bool, *, lw_frac: float, pad_frac: float,
                       ring_lw_frac: float) -> pg.Surface:
    """
    One of the strike pips a live skill check shows: an empty ring for a whiff
    still going spare, a crossed-out disc for one already spent. Whack-a-Mole
    and Combo both use them to say how much room for error is left

    :param size: pip width and height in pixels
    :param struck: True once this whiff has been used up
    :param lw_frac: thickness of the cross, as a share of the pip width
    :param pad_frac: inset of the cross from the edge, as a share of the width
    :param ring_lw_frac: thickness of the empty ring, as a share of the width
    :returns: the shared pip for that size, state and proportions
    """
    def build() -> pg.Surface:
        """
        Draw the pip the first time this exact combination is asked for

        :returns: the finished pip
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Fill and cross the spent form, or ring the spare one

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the pip
            """
            w = surf.get_width()
            r = w / 2.0
            if struck:
                pg.draw.circle(surf, pg.Color(Colors.loss), (r, r), r)
                lw = max(int(w * lw_frac), 2)
                pad = w * pad_frac
                pg.draw.line(surf, pg.Color(Colors.on_accent), (pad, pad),
                             (w - pad, w - pad), lw)
                pg.draw.line(surf, pg.Color(Colors.on_accent), (w - pad, pad),
                             (pad, w - pad), lw)
            else:
                lw = max(int(w * ring_lw_frac), 2)
                pg.draw.circle(surf, pg.Color(Colors.border_strong), (r, r), r - lw, lw)
        return supersample((size, size), render)
    key = (size, struck, lw_frac, pad_frac, ring_lw_frac)
    return cast(pg.Surface, memoized_surface(_STRIKE_PIP_CACHE, key, build))


def stroked_text(font: pg.font.Font, text: str, fill: str, stroke: str, sw: int) -> pg.Surface:
    """
    Text with an outline round it, so a headline still reads over busy art --
    the result outcome and the VS on the match-found card. The outline is
    stamped by redrawing the text in a ring of offsets, so it stays even

    :param font: the font to set the text in
    :param text: the string to draw
    :param fill: colour of the letters themselves
    :param stroke: colour of the outline around them
    :param sw: outline thickness in pixels, also the padding added all round
    :returns: a new surface holding the outlined text
    """
    base = font.render(text, True, fill)
    edge = font.render(text, True, stroke)
    w, h = base.get_size()
    surf = pg.Surface((w + 2 * sw, h + 2 * sw), pg.SRCALPHA)
    for dx in range(-sw, sw + 1):
        for dy in range(-sw, sw + 1):
            if dx * dx + dy * dy <= sw * sw:
                surf.blit(edge, (sw + dx, sw + dy))
    surf.blit(base, (sw, sw))
    return surf


def blit_centered(surface: pg.Surface, text: pg.Surface, center: tuple[float, float]) -> None:
    """
    Draw a text surface centred on the ink itself rather than on its box.
    Display faces leave uneven room above and below the letters, so centring
    the box leaves a heading looking a pixel or two off; this does not

    :param surface: surface to draw onto
    :param text: the already rendered text
    :param center: where the middle of the letters should land, in pixels
    """
    ink = text.get_bounding_rect()
    surface.blit(text, (round(center[0] - ink.centerx), round(center[1] - ink.centery)))


_ROUNDED_RECT_CACHE = new_size_cache()


def rounded_rect_surface(size: int | tuple[int, int], radius: int, fill: str,
                         border: str | None = None, border_width: int = 1) -> pg.Surface:
    """
    A rounded panel with smooth corners, used for the softer shapes in the UI:
    pills, chips, wells and the move log's backing. Each distinct look is drawn
    once and shared, so a screen full of pills costs one draw each

    :param size: panel size in pixels, one number for a square
    :param radius: corner radius in pixels
    :param fill: interior colour as a hex token from Colors
    :param border: outline colour, or None for no outline
    :param border_width: outline thickness in pixels
    :returns: the shared panel for exactly that look
    """
    size_key = size if isinstance(size, int) else tuple(size)
    key = (size_key, int(radius), str(fill), None if border is None else str(border),
           border_width)

    def build() -> pg.Surface:
        """
        Draw the panel the first time this look is asked for

        :returns: the finished panel
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Fill the rounded body, then lay the outline over its edge

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the panel
            """
            r = max(int(radius * k), 1)
            pg.draw.rect(surf, pg.Color(fill), surf.get_rect(), border_radius=r)
            if border is not None:
                pg.draw.rect(surf, pg.Color(border), surf.get_rect(),
                             width=max(int(border_width * k), 1), border_radius=r)
        return supersample(size, render)
    return cast(pg.Surface, memoized_surface(_ROUNDED_RECT_CACHE, key, build))


_CUT_RECT_CACHE = new_size_cache()
_CUT_CORNERS = ("tl", "tr", "br", "bl")


def _cut_rect_points(left: float, top: float, right: float, bottom: float, cut: float,
                     corners: tuple[str, ...]) -> list[tuple[float, float]]:
    """
    Trace the outline of the game's signature panel shape -- a rectangle with
    one or more corners sliced off at 45 degrees. The cut is clamped so it can
    never eat past the middle of a short side

    :param left: left edge in pixels
    :param top: top edge in pixels
    :param right: right edge in pixels
    :param bottom: bottom edge in pixels
    :param cut: how far along each edge the slice reaches, in pixels
    :param corners: which corners to slice, named tl, tr, br and bl
    :returns: the outline points, clockwise from the top-left corner
    """
    c = max(0.0, min(cut, (right - left) / 2, (bottom - top) / 2))
    pts = []
    pts += [(left, top + c), (left + c, top)] if "tl" in corners and c > 0 else [(left, top)]
    pts += [(right - c, top), (right, top + c)] if "tr" in corners and c > 0 else [(right, top)]
    pts += [(right, bottom - c), (right - c, bottom)] if "br" in corners and c > 0 \
        else [(right, bottom)]
    pts += [(left + c, bottom), (left, bottom - c)] if "bl" in corners and c > 0 \
        else [(left, bottom)]
    return pts


def cut_rect_surface(size: int | tuple[int, int], cut: int, fill: str | pg.Color,
                     border: str | pg.Color | None = None, border_width: int = 1,
                     corners: tuple[str, ...] = ("tr",)) -> pg.Surface:
    """
    The panel shape the whole game is built from: a rectangle with its
    top-right corner sliced off. Cards, caps, chips, modals and the board plate
    all come from here, which is what gives the interface one voice. The
    outline is drawn as a slightly larger shape with the fill laid inside it,
    so the sliced edge keeps an even thickness

    :param size: panel size in pixels, one number for a square
    :param cut: length of the slice along each cut edge, in pixels
    :param fill: interior colour, a hex token from Colors or a built Color
    :param border: outline colour, same forms as fill, or None for a flat
        shape with no outline
    :param border_width: outline thickness in pixels
    :param corners: which corners to slice, named tl, tr, br and bl
    :returns: the shared panel for exactly that look
    """
    size_key = size if isinstance(size, int) else tuple(size)
    corner_key = tuple(c for c in _CUT_CORNERS if c in corners)
    key = (size_key, int(cut), str(fill), None if border is None else str(border),
           border_width, corner_key)

    def build() -> pg.Surface:
        """
        Draw the panel the first time this look is asked for

        :returns: the finished panel
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Fill the outer shape in the border colour and drop the inner shape
            on top, its own cut pulled in so the slice stays parallel

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the panel
            """
            w, h = surf.get_size()
            outer_cut = int(round(cut * k))
            if border is None:
                pg.draw.polygon(surf, pg.Color(fill),
                                _cut_rect_points(0, 0, w, h, outer_cut, corners))
                return
            bi = max(int(round(border_width * k)), 1)
            pg.draw.polygon(surf, pg.Color(border),
                            _cut_rect_points(0, 0, w, h, outer_cut, corners))
            inner_cut = max(outer_cut - int(round(bi * (2.0 - SQRT2 * _CUT_BORDER_SCALE))), 0)
            pg.draw.polygon(surf, pg.Color(fill),
                            _cut_rect_points(bi, bi, w - bi, h - bi, inner_cut, corners))
        return supersample(size, render)
    return cast(pg.Surface, memoized_surface(_CUT_RECT_CACHE, key, build))


def build_tooltip_bubble(font: pg.font.Font, label: str, scale: float) -> pg.Surface:
    """
    The little label that appears after hovering a rail button or a player
    strip. It comes back as its own surface rather than a shared one, since
    the caller fades it in, and callers cache it instead of rebuilding it

    :param font: the font the label is set in
    :param label: the tooltip text
    :param scale: window UI scale, applied to the padding and corner cut
    :returns: a new bubble surface holding the finished tooltip
    """
    text = render_text(font, label, Colors.text)
    pad_x = scale_floor(TOOLTIP_PAD_X, scale, 6)
    pad_y = scale_floor(TOOLTIP_PAD_Y, scale, 3)
    w = text.get_width() + 2 * pad_x
    h = text.get_height() + 2 * pad_y
    bubble = cut_rect_surface((w, h), scale_floor(TOOLTIP_RADIUS, scale, 4), Colors.bg,
                              border=Colors.border_strong, border_width=1,
                              corners=("tr",)).copy()
    bubble.blit(text, (pad_x, pad_y))
    return bubble


def _rounded_rect_perimeter(w: float, h: float, r: float,
                            arc_segs: int = 8) -> list[tuple[float, float]]:
    """
    Trace a rounded rectangle as a plain list of points, which is what a dashed
    outline needs -- pygame can round a filled rect's corners, but it cannot
    walk that outline to lay dashes along it

    :param w: width in pixels
    :param h: height in pixels
    :param r: corner radius in pixels, clamped to half the shorter side
    :param arc_segs: how many segments each corner is broken into
    :returns: the outline points, clockwise from the top edge
    """
    r = max(0.0, min(r, w / 2, h / 2))
    pts = [(r, 0.0)]

    def arc(cx: float, cy: float, a0: float, a1: float) -> None:
        """
        Add one rounded corner to the outline being built

        :param cx: centre of that corner's arc, horizontally
        :param cy: centre of that corner's arc, vertically
        :param a0: angle the arc starts at, in degrees
        :param a1: angle the arc ends at, in degrees
        """
        for i in range(1, arc_segs + 1):
            a = math.radians(a0 + (a1 - a0) * i / arc_segs)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    pts.append((w - r, 0.0))
    arc(w - r, r, -90, 0)
    pts.append((w, h - r))
    arc(w - r, h - r, 0, 90)
    pts.append((r, h))
    arc(r, h - r, 90, 180)
    pts.append((0, r))
    arc(r, r, 180, 270)
    return pts


def _densify(pts: list[tuple[float, float]],
             step: float) -> list[tuple[tuple[float, float], float]]:
    """
    Re-space an outline into short, even steps and record how far along the
    outline each point sits. Dashes are cut by distance travelled, so the
    corners have to carry the same running measure as the straights

    :param pts: outline points, treated as a closed loop
    :param step: wanted spacing between points, in pixels
    :returns: each point paired with its distance from the start of the loop
    """
    dense = [(pts[0], 0.0)]
    dist = 0.0
    n = len(pts)
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if seg_len <= 0:
            continue
        steps = max(1, round(seg_len / step))
        for s in range(1, steps + 1):
            t = s / steps
            dist += seg_len / steps
            dense.append(((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t), dist))
    return dense


_DASHED_RECT_CACHE = new_size_cache()


def dashed_rounded_rect_surface(size: int | tuple[int, int], radius: int, border: str,
                                border_width: int = 1, dash: int = 6, gap: int = 5,
                                fill: str | None = None) -> pg.Surface:
    """
    A rounded panel outlined in a dashed line, the game's way of saying a
    control is there but not available -- a signal chip whose feature is off.
    Dashes are laid by distance round the outline, so they stay even through
    the corners

    :param size: panel size in pixels, one number for a square
    :param radius: corner radius in pixels
    :param border: colour of the dashes
    :param border_width: dash thickness in pixels
    :param dash: length of one dash in pixels
    :param gap: space between two dashes in pixels
    :param fill: interior colour, or None to leave the middle empty
    :returns: the shared panel for exactly that look
    """
    size_key = size if isinstance(size, int) else tuple(size)
    key = (size_key, int(radius), str(border), border_width, dash, gap,
           None if fill is None else str(fill))

    def build() -> pg.Surface:
        """
        Draw the panel the first time this look is asked for

        :returns: the finished panel
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Fill the body if asked, then walk the outline dropping a line for
            each stretch that falls inside a dash

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the panel
            """
            w, h = surf.get_size()
            r = radius * k
            if fill is not None:
                pg.draw.rect(surf, pg.Color(fill), surf.get_rect(),
                             border_radius=max(int(r), 1))
            lw = max(int(border_width * k), 1)
            dense = _densify(_rounded_rect_perimeter(w, h, r), max(2.0 * k, 1.0))
            period = dash * k + gap * k
            run = []
            for pt, dist in dense:
                if (dist % period) < dash * k:
                    run.append(pt)
                else:
                    if len(run) >= 2:
                        pg.draw.lines(surf, pg.Color(border), False, run, lw)
                    run = []
            if len(run) >= 2:
                pg.draw.lines(surf, pg.Color(border), False, run, lw)
        return supersample(size, render)
    return cast(pg.Surface, memoized_surface(_DASHED_RECT_CACHE, key, build))


_DASHED_HLINE_CACHE = new_size_cache()


def dashed_hline(width: int, color: str, dash: int = 6, gap: int = 5) -> pg.Surface:
    """
    The hairline rule that separates sections in the right rail and the move
    log. It is a single row of pixels, so it is built flat rather than
    oversampled, and shared by every divider of the same width

    :param width: length of the rule in pixels
    :param color: colour of the dashes
    :param dash: length of one dash in pixels
    :param gap: space between two dashes in pixels
    :returns: the shared rule, one pixel tall
    """
    w = max(int(width), 1)
    key = (w, str(color), dash, gap)

    def build() -> pg.Surface:
        """
        Step across the width dropping one dash per period

        :returns: the finished rule
        """
        surf = pg.Surface((w, 1), pg.SRCALPHA)
        col = pg.Color(color)
        period = max(dash + gap, 1)
        x = 0
        while x < w:
            seg = min(dash, w - x)
            if seg > 0:
                pg.draw.rect(surf, col, pg.Rect(x, 0, seg, 1))
            x += period
        return surf
    return cast(pg.Surface, memoized_surface(_DASHED_HLINE_CACHE, key, build))


_CHEVRON_CACHE = new_size_cache()


def chevron_surface(height: int, color: str, up: bool = False) -> pg.Surface:
    """
    The small arrowhead that says a thing opens or closes -- section headers in
    the rail, the chips on the Play view, the prompts in the Combo check

    :param height: wanted height in pixels; the width follows from it
    :param color: stroke colour as a hex token from Colors
    :param up: point it upwards instead of down
    :returns: the shared chevron at that size, direction and colour
    """
    h = max(int(height), 4)
    w = int(h * 1.6)

    def build() -> pg.Surface:
        """
        Draw the chevron the first time this look is asked for

        :returns: the finished chevron
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Stroke the two strokes of the arrowhead across the canvas

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the chevron
            """
            bw, bh = surf.get_size()
            lw = max(int(h * 0.16 * k), 2)
            if up:
                pts = [(bw * 0.12, bh * 0.68), (bw * 0.5, bh * 0.28), (bw * 0.88, bh * 0.68)]
            else:
                pts = [(bw * 0.12, bh * 0.32), (bw * 0.5, bh * 0.72), (bw * 0.88, bh * 0.32)]
            pg.draw.lines(surf, pg.Color(color), False, pts, lw)
        return supersample((w, h), render)
    return cast(pg.Surface, memoized_surface(_CHEVRON_CACHE, (h, up, str(color)), build))


_ROTATED_CHEVRON_CACHE = new_size_cache()
_CHEVRON_ANGLE_STEP = 6


def rotated_chevron_surface(height: int, color: str, angle: float) -> pg.Surface:
    """
    A chevron turned partway round, which is how a section header animates
    between closed and open. Angles are rounded into steps before caching, so
    a whole sweep costs a handful of surfaces instead of one per frame

    :param height: wanted height in pixels
    :param color: stroke colour as a hex token from Colors
    :param angle: rotation in degrees, snapped to the nearest step
    :returns: the shared chevron at that size, colour and snapped angle
    """
    bucket = int(round(angle / _CHEVRON_ANGLE_STEP)) * _CHEVRON_ANGLE_STEP
    key = (max(int(height), 4), str(color), bucket)

    def build() -> pg.Surface:
        """
        Take the upright chevron and turn it, unless it is already upright

        :returns: the finished chevron at the snapped angle
        """
        base = chevron_surface(height, color)
        if bucket == 0:
            return base
        return pg.transform.rotate(base, bucket)
    return cast(pg.Surface, memoized_surface(_ROTATED_CHEVRON_CACHE, key, build))
