import math
from dataclasses import dataclass

from chessshootout.skillcheck.rng import seeded_floats
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS, needle_speed_mult

AIM_DEADLINE_MS = SKILLCHECK_DEADLINE_MS
AIM_TRAVEL_PERIOD_MS = 1500.0
AIM_ROTATION_PERIOD_MS = 3700.0
AIM_LOBE_FRACTION = 1.3
AIM_HIT_RADIUS_FRAC = 0.40
AIM_HIT_ASPECT = 0.6
AIM_START_JITTER = 0.06
AIM_SWAY_STEP = 0.10
AIM_SWAY_CAP = 1.7
AIM_SHRINK_STEP = 0.10
AIM_SHRINK_CAP = 1.7
AIM_SHRINK_EXP = 2.5


def _seed_floats(seed: str) -> tuple[float, ...]:
    """
    Draw the three numbers one aim challenge needs, namespaced so a seed also
    used by another engine cannot produce a correlated figure-8

    :param seed: per-check seed, the only input the figure-8 varies with
    :returns: (which lobe, start jitter, initial rotation), each in [0, 1)
    """
    return seeded_floats("aim:{}".format(seed), 3)


def _amplitude() -> float:
    """
    Give the half-width of the figure-8 the crosshair traces, the single place
    the size of the path is set

    :returns: amplitude of the path in board-cell widths
    """
    return AIM_LOBE_FRACTION / 2.0


@dataclass(frozen=True)
class AimChallenge:
    """
    One Steady-Aim challenge: a crosshair traces a rotating figure-8 over the
    victim while the piece shrinks away as the timer. Every distance here is
    in cell fractions rather than pixels, so a shot can be judged without
    knowing anything about the player's window size
    """

    phase0: float
    rotation0_deg: float
    travel_period_ms: float
    rotation_period_ms: float
    deadline_ms: float

    @classmethod
    def from_seed(cls, seed: str, value_diff: int = 0,
                  deadline_ms: float = AIM_DEADLINE_MS) -> "AimChallenge":
        """
        Build one aim challenge from its seed. The crosshair starts out on a
        lobe rather than at a crossing, so the first pass over the victim is
        always a beat away and the check can never be won by clicking the
        instant it appears

        :param seed: per-check seed, fresh random text that carries no trace
            of the room's selection secret
        :param value_diff: capturer value minus captured value, which speeds
            up both the travel and the rotation for a lopsided capture
        :param deadline_ms: milliseconds over which the victim shrinks to
            nothing, which is also when the challenge expires
        :returns: the challenge to render and adjudicate against
        """
        a, b, c = _seed_floats(seed)
        mult = needle_speed_mult(value_diff)
        tip = 0.0 if a < 0.5 else 0.5
        return cls(
            phase0=(tip + b * AIM_START_JITTER) % 1.0,
            rotation0_deg=c * 360.0,
            travel_period_ms=AIM_TRAVEL_PERIOD_MS / mult,
            rotation_period_ms=AIM_ROTATION_PERIOD_MS / mult,
            deadline_ms=deadline_ms,
        )

    def travel_mult(self, miss_count: int) -> float:
        """
        Give how much faster the crosshair sways after this many misses, the
        punishment for a wild shot. It is capped, so a run of misses cannot
        spiral into something nobody could hit

        :param miss_count: shots already missed in this check
        :returns: multiplier on the travel and rotation speed
        """
        return min(AIM_SWAY_CAP, 1.0 + AIM_SWAY_STEP * miss_count)

    def shrink_mult(self, miss_count: int) -> float:
        """
        Give how much faster the victim shrinks after this many misses, the
        other half of the miss punishment. Capped like the sway, so the check
        stays winnable

        :param miss_count: shots already missed in this check
        :returns: multiplier on the shrink rate
        """
        return min(AIM_SHRINK_CAP, 1.0 + AIM_SHRINK_STEP * miss_count)

    def param_at(self, elapsed_ms: float, miss_count: int = 0) -> float:
        """
        Give how far around the figure-8 the crosshair has travelled, as a
        fraction of one lap. Everything about where the crosshair sits is
        derived from this one number

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which speed the travel up
        :returns: position along the path in [0, 1)
        """
        return (self.phase0
                + (elapsed_ms / self.travel_period_ms) * self.travel_mult(miss_count)) % 1.0

    def rotation_deg_at(self, elapsed_ms: float, miss_count: int = 0) -> float:
        """
        Give how far the whole figure-8 has turned by now. The path spins as
        well as being traced, so the crosshair never repeats the same line
        twice within a check

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which speed the spin up
        :returns: rotation of the path in degrees, not wrapped
        """
        mult = self.travel_mult(miss_count)
        return self.rotation0_deg + 360.0 * (elapsed_ms / self.rotation_period_ms) * mult

    def lobe_point(self, t: float) -> tuple[float, float]:
        """
        Give the point on the unturned figure-8 at this position along the
        path, the shape every crosshair position is built from

        :param t: position along the path, one lap per whole unit
        :returns: (x, y) offset from the victim centre in board-cell widths,
            before rotation
        """
        theta = 2.0 * math.pi * t
        amp = _amplitude()
        return (amp * math.cos(theta), amp * math.sin(theta) * math.cos(theta))

    def _rotate(self, point: tuple[float, float], rot_deg: float) -> tuple[float, float]:
        """
        Spin one path offset around the victim's centre, the step that turns
        the fixed figure-8 into the rotating one the player has to read

        :param point: (x, y) offset in cell widths before rotation
        :param rot_deg: angle to turn it by, in degrees
        :returns: the turned (x, y) offset in cell widths
        """
        rot = math.radians(rot_deg)
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        return (point[0] * cos_r - point[1] * sin_r, point[0] * sin_r + point[1] * cos_r)

    def reticle_offset(self, elapsed_ms: float, miss_count: int = 0) -> tuple[float, float]:
        """
        Give where the crosshair sits right now, relative to the victim's
        centre. The renderer multiplies it by the cell size to place the
        crosshair, and the hit test compares it against the hit box

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which speed the path up
        :returns: (x, y) offset from the victim centre in board-cell widths
        """
        point = self.lobe_point(self.param_at(elapsed_ms, miss_count))
        return self._rotate(point, self.rotation_deg_at(elapsed_ms, miss_count))

    def path_offsets(self, elapsed_ms: float, miss_count: int,
                     samples: int) -> list[tuple[float, float]]:
        """
        Trace the whole figure-8 as it currently lies, used to draw the path
        itself when the view is set to show it

        :param elapsed_ms: milliseconds since the check started, which fixes
            the rotation the path is drawn at
        :param miss_count: shots already missed, which speed the spin up
        :param samples: how many segments to split the lap into
        :returns: samples + 1 (x, y) offsets in cell widths, closing the loop
        """
        rot_deg = self.rotation_deg_at(elapsed_ms, miss_count)
        return [self._rotate(self.lobe_point(i / samples), rot_deg)
                for i in range(samples + 1)]

    def piece_scale(self, elapsed_ms: float, miss_count: int = 0) -> float:
        """
        Give how big the victim still is, which is this check's clock made
        visible: generous early, then a collapse. Reaching zero is exactly
        what expiry means here

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which shrink it faster
        :returns: scale in [0, 1], full at the start and nothing at the
            deadline
        """
        p = min(1.0, (max(0.0, elapsed_ms) / self.deadline_ms) * self.shrink_mult(miss_count))
        return max(0.0, 1.0 - p ** AIM_SHRINK_EXP)

    def hit_radius(self, elapsed_ms: float, miss_count: int = 0) -> float:
        """
        Give the tall radius of the hit box as it stands. It tracks the
        victim's size, so a late shot has to be far more accurate than an
        early one

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which shrink the box faster
        :returns: vertical radius in board-cell widths
        """
        return AIM_HIT_RADIUS_FRAC * self.piece_scale(elapsed_ms, miss_count)

    def hit_radii(self, elapsed_ms: float, miss_count: int = 0) -> tuple[float, float]:
        """
        Give both radii of the hit box, which is an upright ellipse rather
        than a circle because a chess piece is taller than it is wide

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which shrink the box faster
        :returns: (horizontal, vertical) radii in board-cell widths
        """
        ry = self.hit_radius(elapsed_ms, miss_count)
        return AIM_HIT_ASPECT * ry, ry

    def contains(self, fx: float, fy: float, elapsed_ms: float, miss_count: int = 0) -> bool:
        """
        Tell whether a point falls on the victim at this moment. A fully
        shrunk victim catches nothing, so a shot past the deadline is always
        a miss

        :param fx: horizontal offset from the victim centre, in cell widths
        :param fy: vertical offset from the victim centre, in cell widths
        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which shrink the box faster
        :returns: True when the point is on the victim
        """
        rx, ry = self.hit_radii(elapsed_ms, miss_count)
        if rx <= 0.0 or ry <= 0.0:
            return False
        return (fx / rx) ** 2 + (fy / ry) ** 2 <= 1.0

    def on_target(self, elapsed_ms: float, miss_count: int = 0) -> bool:
        """
        Tell whether a shot fired right now would land, by asking where the
        crosshair is and whether that is on the victim. This is the verdict
        for a Steady-Aim shot both locally and on the server

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed in this check
        :returns: True when the crosshair is over the victim
        """
        fx, fy = self.reticle_offset(elapsed_ms, miss_count)
        return self.contains(fx, fy, elapsed_ms, miss_count)

    def is_expired(self, elapsed_ms: float, miss_count: int = 0) -> bool:
        """
        Tell whether the victim has shrunk away entirely, which is how a
        Steady-Aim check runs out. The server asks the same question through
        check_expired, so a player who simply stops shooting still loses it

        :param elapsed_ms: milliseconds since the check started
        :param miss_count: shots already missed, which bring expiry forward
        :returns: True when the check is over and lost
        """
        return self.piece_scale(elapsed_ms, miss_count) <= 0.0
