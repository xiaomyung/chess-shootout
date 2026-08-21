import math
from collections.abc import Callable
from typing import cast

import pygame as pg

from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.skillcheck.controller import SkillCheckController, EdgeTrigger
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import rounded_rect_surface, supersample
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS, WheelChallenge, adjudicate

WHEEL_RESULT_HOLD_MS = 380
WHEEL_TIME_LIMIT_MS = SKILLCHECK_DEADLINE_MS
WHEEL_DEFAULT_DEADLINE_MS = WHEEL_TIME_LIMIT_MS
WHEEL_TIMER_RAMP = 2.0
_ARC_STEPS = 56

WHEEL_MIN_RADIUS = 24
WHEEL_RING_FRAC = 0.08
WHEEL_MIN_RING_W = 2
WHEEL_BAND_FRAC = 0.20
WHEEL_MIN_BAND_W = 3
WHEEL_NEEDLE_FRAC = 0.12
WHEEL_MIN_NEEDLE_W = 2
WHEEL_HUB_FRAC = 0.10
WHEEL_MIN_HUB_R = 2
WHEEL_NEEDLE_TIP_FRAC = 0.30
WHEEL_MIN_NEEDLE_TIP_W = 2
WHEEL_TIMER_GAP_FRAC = 0.06
WHEEL_MIN_TIMER_GAP = 1
WHEEL_BACKDROP_PAD_FRAC = 0.08
WHEEL_HINT_FONT_FRAC = 0.26
WHEEL_MIN_HINT_FONT = 10
WHEEL_HINT_PAD_X_FRAC = 0.24
WHEEL_HINT_PAD_Y_FRAC = 0.12
WHEEL_HINT_GAP_FRAC = 0.20
WHEEL_FOOTPRINT_CELL_FRAC = 1.20
WHEEL_SURFACE_MARGIN_PX = 8
WHEEL_FOOTPRINT_DENOM = 2 * (1 + WHEEL_RING_FRAC + WHEEL_TIMER_GAP_FRAC)

_WHEEL_STATIC_CACHE = new_cache()


def _rim_point(cx: float, cy: float, radius: float, deg: float) -> tuple[float, float]:
    """
    Place a point on the dial's rim. Wheel angles read like a clock face --
    zero at the top, growing clockwise -- so this is the one place that
    convention is turned into screen coordinates

    :param cx: dial centre x in pixels on the surface being drawn
    :param cy: dial centre y in pixels on the surface being drawn
    :param radius: distance out from the centre in pixels
    :param deg: angle in wheel degrees, zero at twelve o'clock
    :returns: the (x, y) pixel position on that rim
    """
    angle = math.radians(deg - 90.0)
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def _band_polygon(cx: float, cy: float, inner: float, outer: float, deg_from: float,
                  deg_to: float) -> list[tuple[float, float]]:
    """
    Trace a thick arc as a closed polygon, which is how both the winning band
    and the countdown ring are drawn -- pygame has no filled-arc primitive, so
    the shape is sampled out along the far rim and back along the near one

    :param cx: dial centre x in pixels on the surface being drawn
    :param cy: dial centre y in pixels on the surface being drawn
    :param inner: near radius of the band in pixels
    :param outer: far radius of the band in pixels
    :param deg_from: where the band starts, in wheel degrees
    :param deg_to: where it ends, clockwise from the start
    :returns: the band's outline as pixel points, ready to fill
    """
    points = []
    for i in range(_ARC_STEPS + 1):
        deg = deg_from + (deg_to - deg_from) * i / _ARC_STEPS
        points.append(_rim_point(cx, cy, outer, deg))
    for i in range(_ARC_STEPS + 1):
        deg = deg_to - (deg_to - deg_from) * i / _ARC_STEPS
        points.append(_rim_point(cx, cy, inner, deg))
    return points


def _clamp_bubble_left(left: int, bubble_w: int, window_w: int) -> int:
    """
    Keep the SPACE / CLICK hint fully on screen. A dial on the a-file or the
    h-file would otherwise push its hint off the edge of the window, and the
    one instruction the player needs would be the part that got cut

    :param left: where the hint would sit, in window pixels
    :param bubble_w: the hint's width in pixels
    :param window_w: the window's width in pixels
    :returns: a left edge that keeps the whole hint inside the window
    """
    return max(4, min(left, window_w - bubble_w - 4))


def _needle_polygon(cx: float, cy: float, deg: float, length: float, base_w: float,
                    tip_w: float) -> list[tuple[float, float]]:
    """
    Shape the sweeping needle: a spike that tapers from the hub to a narrow
    tip, so the exact angle being judged is easy to read against the arc

    :param cx: hub centre x in pixels on the surface being drawn
    :param cy: hub centre y in pixels on the surface being drawn
    :param deg: where the needle points, in wheel degrees
    :param length: hub-to-tip length in pixels
    :param base_w: width at the hub in pixels
    :param tip_w: width at the tip in pixels, narrower than the base
    :returns: the needle's four corners as pixel points, ready to fill
    """
    angle = math.radians(deg - 90.0)
    dx, dy = math.cos(angle), math.sin(angle)
    px, py = -dy, dx
    base_half, tip_half = base_w / 2.0, tip_w / 2.0
    tip_x, tip_y = cx + dx * length, cy + dy * length
    return [
        (cx + px * base_half, cy + py * base_half),
        (tip_x + px * tip_half, tip_y + py * tip_half),
        (tip_x - px * tip_half, tip_y - py * tip_half),
        (cx - px * base_half, cy - py * base_half),
    ]


class WheelController(SkillCheckController):
    """
    The wheel mini-game: a needle sweeps a dial and the player taps while it is
    inside the shrinking winning arc. It is the quickest of the four kinds and
    the only one promotions ever fire, and the dial may be drawn on a square
    away from the move to pull the player's eyes off the board
    """

    challenge: WheelChallenge

    def __init__(self, challenge: WheelChallenge, cell_rect: pg.Rect, now_ms: int,
                 deadline_ms: float = WHEEL_DEFAULT_DEADLINE_MS,
                 on_shot: Callable[[float], None] | None = None, passive: bool = False,
                 audio: SoundManager | None = None) -> None:
        """
        Open a wheel check on one square. The dial comes entirely from the
        challenge, which both players and the server built from the same seed,
        so nobody is tapping at a different wheel

        :param challenge: the dial to draw and judge against
        :param cell_rect: rect of the square the dial is drawn over
        :param now_ms: pygame ticks in milliseconds the check counts from
        :param deadline_ms: how long the check may run, in milliseconds
        :param on_shot: reports the tap to the server, None in a local game
        :param passive: True for the read-only mirror of the opponent's wheel
        :param audio: sound manager for the tick and verdict cues
        """
        self._init_common(challenge, now_ms, deadline_ms, on_shot=on_shot, passive=passive,
                          audio=audio)
        self._apply_geometry(cell_rect)
        self._frozen_override: float | None = None
        self._tick_edge = EdgeTrigger()
        self._cue("play_skillcheck_appear")

    def _apply_geometry(self, cell_rect: pg.Rect) -> None:
        """
        Size the whole dial from the square it is drawn on, which is also how a
        resize is absorbed. The wheel is one radius-anchored proportional
        model: the radius is solved so the dial plus its countdown ring fit a
        footprint of about 1.2 cells, and ring, band, needle, hub, gaps and
        hint type are then fixed fractions of that radius, anchored at the
        values approved at the default r=49. The minimums are guards against a
        degenerate window only -- nothing look-bearing is a fixed pixel count

        :param cell_rect: the square's rect in window pixels; its centre
            anchors the dial and its width sets the radius
        """
        self.center = cell_rect.center
        cell = cell_rect.width
        self.radius = max(WHEEL_MIN_RADIUS, round(
            (cell * WHEEL_FOOTPRINT_CELL_FRAC - WHEEL_SURFACE_MARGIN_PX) / WHEEL_FOOTPRINT_DENOM))
        r = self.radius
        self.ring_w = max(WHEEL_MIN_RING_W, round(r * WHEEL_RING_FRAC))
        self.band_w = max(WHEEL_MIN_BAND_W, round(r * WHEEL_BAND_FRAC))
        self.needle_w = max(WHEEL_MIN_NEEDLE_W, round(r * WHEEL_NEEDLE_FRAC))
        self.hub_r = max(WHEEL_MIN_HUB_R, round(r * WHEEL_HUB_FRAC))
        self.needle_tip_w = max(
            WHEEL_MIN_NEEDLE_TIP_W, round(self.needle_w * WHEEL_NEEDLE_TIP_FRAC))
        self.timer_gap = max(WHEEL_MIN_TIMER_GAP, round(r * WHEEL_TIMER_GAP_FRAC))
        self.backdrop_pad = round(r * WHEEL_BACKDROP_PAD_FRAC)
        self._hint_font = get_font(
            max(WHEEL_MIN_HINT_FONT, round(r * WHEEL_HINT_FONT_FRAC)), bold=True)
        self._hint_pad_x = round(r * WHEEL_HINT_PAD_X_FRAC)
        self._hint_pad_y = round(r * WHEEL_HINT_PAD_Y_FRAC)
        self._hint_gap = round(r * WHEEL_HINT_GAP_FRAC)

    def _fire(self) -> None:
        """
        Take the player's tap, the one shot a wheel check ever gets. Offline it
        is judged here and now; online only the elapsed time is sent and the
        dial freezes while the server decides, since the client never paints a
        verdict it was not given
        """
        if self._online:
            self._committed_at = self._now
            cast(Callable[..., None], self._on_shot)(self._now - self.start_ms)
            return
        self._commit(self._landed_now())

    def spectate_shot(self, elapsed: float, miss_count: int, won: bool, progress: int = 0,
                      direction: str | None = None,
                      target: tuple[float, float] | None = None) -> None:
        """
        Freeze the mirror on the moment the opponent tapped, so the watcher
        sees the needle stop exactly where the shot was fired rather than sweep
        on past it. The verdict itself arrives separately, from the server

        :param elapsed: milliseconds into the check the tap was fired at
        :param miss_count: unused by the wheel, which allows only one tap
        :param won: unused here; the wheel waits for the server's verdict
        :param progress: unused by the wheel, which has nothing to accumulate
        :param direction: unused by the wheel, which takes no direction
        :param target: unused by the wheel, which is not aimed
        """
        self._frozen_override = elapsed
        self._committed_at = self._now

    def update(self, now_ms: int) -> None:
        """
        Advance the sweep by one frame: tick once each time the needle crosses
        into the winning arc, which is the audible cue the player times the tap
        against. Offline an untouched wheel fails itself at the deadline;
        online the server's sweep does that instead

        :param now_ms: pygame tick count in milliseconds for this frame
        """
        self._now = now_ms
        if self._committed_at is None:
            elapsed = now_ms - self.start_ms
            in_arc = self.challenge.in_arc_at(self.challenge.needle_deg(elapsed), elapsed)
            if self._tick_edge.update(in_arc):
                self._cue("play_wheel_tick")
        if (not self._online and self._committed_at is None
                and now_ms - self.start_ms >= self.deadline_ms):
            self._commit(False)

    @property
    def done(self) -> bool:
        """
        Whether the wheel has held its verdict long enough to be retired. The
        green or red arc is what tells the player how the tap went, so it stays
        up for a beat before the move lands or locks

        :returns: True once the verdict has been shown
        """
        return self._done_after(WHEEL_RESULT_HOLD_MS)

    def _landed_now(self) -> bool:
        """
        Judge the tap that just happened with the shared wheel adjudicator, the
        same one the server runs, so a local win and an online win mean exactly
        the same thing. Nothing is credited back for lag, since a local tap
        made no trip

        :returns: True when the tap lands the move
        """
        return adjudicate(self.challenge, self._now, self.start_ms, 0.0)

    def _commit(self, landed: bool) -> None:
        """
        Settle an offline wheel: freeze the dial on the verdict and sound it.
        The overlay retires the check a moment later, and only then does the
        move land or lock

        :param landed: True when the tap won the capture or promotion
        """
        self._landed = landed
        self._committed_at = self._now
        self._emit_verdict()

    def _frozen_elapsed(self) -> float:
        """
        Give the moment the dial is drawn at, preferring the opponent's own
        shot time in the mirror. Their tap was timed on their machine, so
        replaying it at the local commit time would show the needle somewhere
        they never saw

        :returns: milliseconds into the check to draw
        """
        if self._frozen_override is not None:
            return self._frozen_override
        return super()._frozen_elapsed()

    def draw(self, window: pg.Surface) -> None:
        """
        Paint the dial on its square, and under it the SPACE / CLICK hint while
        the tap is still to come. The hint is dropped once a shot is committed
        and in the mirror, where there is nothing for the watcher to press

        :param window: surface to draw on, the app window
        """
        cx, cy = self.center
        elapsed = self._frozen_elapsed()
        timer_outer = self.radius + self.ring_w + self.timer_gap
        size = timer_outer * 2 + WHEEL_SURFACE_MARGIN_PX
        window.blit(self._render_dial(elapsed, size), (cx - size // 2, cy - size // 2))
        if self._committed_at is None and not self._passive:
            self._draw_hint_bubble(window, cx, cy, timer_outer)

    def _render_dial(self, elapsed: float, size: int) -> pg.Surface:
        """
        Compose one frame of the dial: the parts that never move are drawn once
        per radius and copied, the sweeping parts are drawn fresh on top

        :param elapsed: milliseconds into the check this frame shows
        :param size: side of the square plate to draw on, in pixels
        :returns: the finished dial for this frame
        """
        layer = self._static_layer(size).copy()
        layer.blit(self._render_dynamic(elapsed, size), (0, 0))
        return layer

    def _static_layer(self, size: int) -> pg.Surface:
        """
        The unchanging plate behind the dial: the dimmed disc that lifts the
        wheel off the board and the rim ring around it. It depends on nothing
        but the radius, so it is built once and shared by every frame and every
        later wheel of that size

        :param size: side of the square plate to draw on, in pixels
        :returns: the shared static plate for this radius
        """
        def build() -> pg.Surface:
            """
            Draw the plate for this radius, called only on a cache miss

            :returns: the freshly drawn plate
            """
            def render(surf: pg.Surface, k: int) -> None:
                """
                Paint the backdrop disc and the rim onto the oversized canvas,
                scaling every radius and width by the enlargement factor

                :param surf: the oversized canvas being drawn into
                :param k: how many times oversized that canvas is
                """
                c = surf.get_width() / 2.0
                pg.draw.circle(surf, pg.Color(Colors.bg + "ea"), (c, c),
                               (self.radius + self.backdrop_pad) * k)
                pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), self.radius * k,
                               max(int(self.ring_w * k), 1))
            return supersample((size, size), render)
        return cast(pg.Surface, memoized_surface(_WHEEL_STATIC_CACHE, self.radius, build))

    def _render_dynamic(self, elapsed: float, size: int) -> pg.Surface:
        """
        Draw everything about the dial that moves: the countdown ring draining
        from amber to red, the winning arc as it narrows -- or its verdict
        colour once a shot is in -- and the needle on top

        :param elapsed: milliseconds into the check this frame shows
        :param size: side of the square plate to draw on, in pixels
        :returns: the moving layer, to be laid over the static plate
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the ring, the arc and the needle onto the oversized canvas,
            scaling every radius and width by the enlargement factor

            :param surf: the oversized canvas being drawn into
            :param k: how many times oversized that canvas is
            """
            c = surf.get_width() / 2.0

            if self._committed_at is None and self.deadline_ms > 0:
                remaining = max(0.0, 1.0 - elapsed / self.deadline_ms)
                if remaining > 0.0:
                    blend = (1.0 - remaining) ** WHEEL_TIMER_RAMP
                    timer_base = self._signal_color(Colors.amber)
                    timer_color = pg.Color(timer_base).lerp(pg.Color(Colors.loss), blend)
                    inner = (self.radius + self.timer_gap) * k
                    outer = (self.radius + self.ring_w + self.timer_gap) * k
                    end_deg = remaining * 360.0
                    pg.draw.polygon(surf, timer_color,
                                    _band_polygon(c, c, inner, outer, 0.0, end_deg))
                    cap_mid, cap_r = (inner + outer) / 2.0, (outer - inner) / 2.0
                    for cap_deg in (0.0, end_deg):
                        pg.draw.circle(surf, timer_color, _rim_point(c, c, cap_mid, cap_deg), cap_r)

            arc_width = self.challenge.arc_width_at(elapsed)
            arc_color = self._signal_color(Colors.accent)
            if self._committed_at is not None and self._landed is not None:
                arc_color = Colors.win if self._landed else Colors.loss
            band = _band_polygon(c, c, (self.radius - self.band_w) * k, self.radius * k,
                                 self.challenge.arc_start_deg,
                                 self.challenge.arc_start_deg + arc_width)
            pg.draw.polygon(surf, pg.Color(arc_color), band)

            needle_len = (self.radius - self.ring_w - 2) * k
            needle_deg = self.challenge.needle_deg(elapsed)
            pg.draw.polygon(surf, pg.Color(Colors.text),
                            _needle_polygon(c, c, needle_deg, needle_len,
                                            self.needle_w * k, self.needle_tip_w * k))
            pg.draw.circle(surf, pg.Color(Colors.text),
                           _rim_point(c, c, needle_len, needle_deg), self.needle_tip_w * k / 2.0)
            pg.draw.circle(surf, pg.Color(Colors.text), (c, c), max(self.hub_r * k, 1))

        return supersample((size, size), render)

    def _draw_hint_bubble(self, window: pg.Surface, cx: int, cy: int,
                          timer_outer: int) -> None:
        """
        Print how to fire, in a pill under the dial. It normally sits below the
        wheel and flips above it near the bottom of the window, and it is
        clamped sideways, so the instruction is readable wherever the dial
        landed

        :param window: surface to draw on, the app window
        :param cx: dial centre x in window pixels
        :param cy: dial centre y in window pixels
        :param timer_outer: outer radius of the countdown ring in pixels, which
            the pill is placed clear of
        """
        label = self._hint_font.render("SPACE / CLICK", True, pg.Color(Colors.text))
        pad_x, pad_y = self._hint_pad_x, self._hint_pad_y
        bubble_w = label.get_width() + pad_x * 2
        bubble_h = label.get_height() + pad_y * 2
        bubble = rounded_rect_surface((bubble_w, bubble_h), bubble_h // 2,
                                      Colors.surface_raised, border=Colors.border_strong,
                                      border_width=1)
        left = _clamp_bubble_left(cx - bubble_w // 2, bubble_w, window.get_width())
        top = cy + timer_outer + self._hint_gap
        if top + bubble_h > window.get_height():
            top = cy - timer_outer - self._hint_gap - bubble_h
        window.blit(bubble, (left, top))
        window.blit(label, (left + pad_x, top + pad_y))
