from collections.abc import Iterable
from dataclasses import dataclass

from chessshootout.skillcheck.rng import seeded_floats

WHEEL_ARC_DEGREES = 60.0
WHEEL_PERIOD_MS = 800.0
WHEEL_ARC_SHRINK_PER_ROTATION = 10.0
WHEEL_ARC_MIN_DEGREES = 5.0
WHEEL_HUMAN_FLOOR_MS = 120.0
WHEEL_RTT_CAP_MS = 200.0
SKILLCHECK_DEADLINE_MS = 5000.0
WHEEL_SPEED_PER_DIFF = 0.2
WHEEL_SPEED_DIFF_DIVISOR = 4.0
WHEEL_SPEED_MULT_MIN = 0.2
WHEEL_PLACEMENT_BASE_PROB = 0.5
WHEEL_PLACEMENT_PER_DIFF = 0.05
WHEEL_PLACEMENT_MIN_PROB = 0.1
WHEEL_PLACEMENT_MAX_PROB = 0.9


def needle_speed_mult(value_diff: int) -> float:
    """
    Scale the wheel's needle speed by how lopsided the capture is, which is
    how material difficulty reaches this mini-game: a queen taking a pawn
    spins fast, a pawn taking a queen spins slow. The result is floored, so
    the period built from it can never divide by zero

    :param value_diff: capturer value minus captured value, positive when the
        stronger piece is doing the taking
    :returns: multiplier on the base needle speed, always above zero
    """
    return max(WHEEL_SPEED_MULT_MIN,
               1.0 + WHEEL_SPEED_PER_DIFF * value_diff / WHEEL_SPEED_DIFF_DIVISOR)


def period_for_diff(value_diff: int) -> float:
    """
    Give how long one full needle revolution takes for this capture, the
    figure both the renderer and the judge build the dial from. A faster
    needle means a shorter period and a harder tap

    :param value_diff: capturer value minus captured value
    :returns: revolution period in milliseconds
    """
    return WHEEL_PERIOD_MS / needle_speed_mult(value_diff)


def random_placement_prob(value_diff: int) -> float:
    """
    Give the chance this dial is drawn somewhere other than the square being
    captured, which drags the player's eyes away from the action. It follows
    the same material slope as the needle speed, so the lopsided captures are
    the ones most often relocated

    :param value_diff: capturer value minus captured value
    :returns: probability of relocating the dial, clamped to [0.1, 0.9]
    """
    prob = WHEEL_PLACEMENT_BASE_PROB + WHEEL_PLACEMENT_PER_DIFF * value_diff
    return min(WHEEL_PLACEMENT_MAX_PROB, max(WHEEL_PLACEMENT_MIN_PROB, prob))


def _placement_floats(seed: str) -> tuple[float, ...]:
    """
    Draw the two numbers the dial placement needs -- whether to relocate, and
    where to -- on their own namespace, so placement never disturbs the arc
    geometry drawn from the same seed

    :param seed: per-check seed, the only input the placement varies with
    :returns: (relocation roll, square pick), both in [0, 1)
    """
    return seeded_floats(f"place:{seed}", 2)


def placement_square(seed: str, value_diff: int, excluded: Iterable[tuple[int, int]] = (),
                     board_size: int = 8) -> tuple[int, int] | None:
    """
    Choose the board square the wheel dial is drawn over, fixed by the seed so
    it is never a surprise to only one side. When it does not relocate the
    caller draws the dial on the move's own target square instead

    :param seed: the check's seed, which fixes both the roll and the pick
    :param value_diff: capturer value minus captured value, which sets how
        often the dial relocates
    :param excluded: (row, col) squares the dial must avoid, normally the
        move's own from and to squares
    :param board_size: side length of the board being drawn on
    :returns: (row, col) to draw over, or None to leave the dial on the move
    """
    roll, pick = _placement_floats(seed)
    if roll >= random_placement_prob(value_diff):
        return None
    blocked = set(excluded)
    allowed = [(row, col) for row in range(board_size) for col in range(board_size)
               if (row, col) not in blocked]
    if not allowed:
        return None
    return allowed[int(pick * len(allowed)) % len(allowed)]


def _seed_floats(seed: str) -> tuple[float, ...]:
    """
    Draw the two numbers that fix one dial's geometry, namespaced so a seed
    also used by another engine cannot produce a correlated wheel

    :param seed: per-check seed; the same text always gives the same dial
    :returns: (arc position, needle start), both in [0, 1)
    """
    return seeded_floats(f"wheel:{seed}", 2)


@dataclass(frozen=True)
class WheelChallenge:
    """
    One wheel challenge: where the winning arc sits, how wide it starts, how
    fast the needle sweeps and where it starts from. Frozen and derived purely
    from a seed, so the judge and both screens hold the identical dial
    """

    arc_start_deg: float
    arc_width_deg: float
    period_ms: float
    start_angle_deg: float

    @classmethod
    def from_seed(cls, seed: str, arc_width_deg: float = WHEEL_ARC_DEGREES,
                  period_ms: float = WHEEL_PERIOD_MS) -> "WheelChallenge":
        """
        Build the dial for one check from its seed, which is the only way a
        challenge is ever made. The server does it to adjudicate and the
        client does it to draw, and both land on the same dial because nothing
        else feeds in

        :param seed: per-check seed, fresh random text that carries no trace
            of the room's selection secret
        :param arc_width_deg: starting width of the winning arc in degrees
        :param period_ms: milliseconds per needle revolution, normally taken
            from period_for_diff so material difficulty applies
        :returns: the challenge to render and adjudicate against
        """
        arc, start = _seed_floats(seed)
        return cls(
            arc_start_deg=arc * 360.0,
            arc_width_deg=arc_width_deg,
            period_ms=period_ms,
            start_angle_deg=start * 360.0,
        )

    def needle_deg(self, elapsed_ms: float) -> float:
        """
        Give where the needle points this far into the check, the one position
        the renderer draws and the judge tests

        :param elapsed_ms: milliseconds since the check started
        :returns: needle angle in degrees, wrapped into [0, 360)
        """
        return (self.start_angle_deg + 360.0 * elapsed_ms / self.period_ms) % 360.0

    def arc_width_at(self, elapsed_ms: float) -> float:
        """
        Give how wide the winning arc still is; it narrows every revolution,
        so hesitating is never free. The shrink stops at a floor, which keeps
        a check that runs long still winnable

        :param elapsed_ms: milliseconds since the check started
        :returns: current arc width in degrees, never below the floor
        """
        rotations = max(elapsed_ms, 0.0) / self.period_ms
        shrunk = self.arc_width_deg - WHEEL_ARC_SHRINK_PER_ROTATION * rotations
        return max(WHEEL_ARC_MIN_DEGREES, shrunk)

    def in_arc(self, angle_deg: float, arc_width_deg: float | None = None) -> bool:
        """
        Tell whether an angle falls inside the winning arc, measured clockwise
        from where the arc starts. The band is half-open: the near edge counts
        and the far edge does not

        :param angle_deg: angle to test, normally the needle's
        :param arc_width_deg: width to test against, or None for the arc's
            starting width
        :returns: True when the angle is inside the winning band
        """
        width = self.arc_width_deg if arc_width_deg is None else arc_width_deg
        delta = (angle_deg - self.arc_start_deg) % 360.0
        return delta < width

    def in_arc_at(self, angle_deg: float, elapsed_ms: float) -> bool:
        """
        Tell whether an angle is inside the arc as it stands at this moment,
        shrinkage included. This is the test that decides a wheel tap

        :param angle_deg: angle to test, normally the needle's
        :param elapsed_ms: milliseconds since the check started
        :returns: True when the angle is inside the arc at that time
        """
        return self.in_arc(angle_deg, self.arc_width_at(elapsed_ms))


def effective_elapsed_ms(recv_ms: float, start_ms: float, half_rtt_ms: float) -> float:
    """
    Work out how far the player saw the needle sweep, crediting them for the
    trip their tap took to arrive. A laggy honest player is judged fairly,
    while the credit is floored at zero and capped, so a forged round-trip
    cannot buy a wider window

    :param recv_ms: when the tap arrived, on the judging side's clock
    :param start_ms: when the check started, on the same clock
    :param half_rtt_ms: one-way trip estimate to credit back, in milliseconds
    :returns: perceived elapsed milliseconds to judge the tap at
    """
    compensation = min(max(half_rtt_ms, 0.0), WHEEL_RTT_CAP_MS)
    return (recv_ms - start_ms) - compensation


def adjudicate(challenge: WheelChallenge, recv_ms: float, start_ms: float,
               half_rtt_ms: float = 0.0) -> bool:
    """
    Judge one wheel tap: the move lands when the needle was inside the arc as
    the player tapped, and a tap quicker than a human could react is thrown
    out. This is the local game's verdict -- an online tap is sent to the
    server, which judges it through shot_wins instead

    :param challenge: dial the tap is judged against
    :param recv_ms: when the tap arrived, on the judging side's clock
    :param start_ms: when the check started, on the same clock
    :param half_rtt_ms: one-way trip estimate to credit back, zero locally
    :returns: True when the tap lands the move
    """
    elapsed = effective_elapsed_ms(recv_ms, start_ms, half_rtt_ms)
    if elapsed < WHEEL_HUMAN_FLOOR_MS:
        return False
    return challenge.in_arc_at(challenge.needle_deg(elapsed), elapsed)
