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


def needle_speed_mult(value_diff):
    return max(WHEEL_SPEED_MULT_MIN,
               1.0 + WHEEL_SPEED_PER_DIFF * value_diff / WHEEL_SPEED_DIFF_DIVISOR)


def period_for_diff(value_diff):
    return WHEEL_PERIOD_MS / needle_speed_mult(value_diff)


def random_placement_prob(value_diff):
    prob = WHEEL_PLACEMENT_BASE_PROB + WHEEL_PLACEMENT_PER_DIFF * value_diff
    return min(WHEEL_PLACEMENT_MAX_PROB, max(WHEEL_PLACEMENT_MIN_PROB, prob))


def _placement_floats(seed):
    return seeded_floats(f"place:{seed}", 2)


def placement_square(seed, value_diff, excluded=(), board_size=8):
    roll, pick = _placement_floats(seed)
    if roll >= random_placement_prob(value_diff):
        return None
    blocked = set(excluded)
    allowed = [(row, col) for row in range(board_size) for col in range(board_size)
               if (row, col) not in blocked]
    if not allowed:
        return None
    return allowed[int(pick * len(allowed)) % len(allowed)]


def _seed_floats(seed):
    return seeded_floats(f"wheel:{seed}", 2)


@dataclass(frozen=True)
class WheelChallenge:
    arc_start_deg: float
    arc_width_deg: float
    period_ms: float
    start_angle_deg: float

    @classmethod
    def from_seed(cls, seed, arc_width_deg=WHEEL_ARC_DEGREES, period_ms=WHEEL_PERIOD_MS):
        arc, start = _seed_floats(seed)
        return cls(
            arc_start_deg=arc * 360.0,
            arc_width_deg=arc_width_deg,
            period_ms=period_ms,
            start_angle_deg=start * 360.0,
        )

    def needle_deg(self, elapsed_ms):
        return (self.start_angle_deg + 360.0 * elapsed_ms / self.period_ms) % 360.0

    def arc_width_at(self, elapsed_ms):
        rotations = max(elapsed_ms, 0.0) / self.period_ms
        shrunk = self.arc_width_deg - WHEEL_ARC_SHRINK_PER_ROTATION * rotations
        return max(WHEEL_ARC_MIN_DEGREES, shrunk)

    def in_arc(self, angle_deg, arc_width_deg=None):
        width = self.arc_width_deg if arc_width_deg is None else arc_width_deg
        delta = (angle_deg - self.arc_start_deg) % 360.0
        return delta < width

    def in_arc_at(self, angle_deg, elapsed_ms):
        return self.in_arc(angle_deg, self.arc_width_at(elapsed_ms))


def effective_elapsed_ms(recv_ms, start_ms, half_rtt_ms):
    compensation = min(max(half_rtt_ms, 0.0), WHEEL_RTT_CAP_MS)
    return (recv_ms - start_ms) - compensation


def adjudicate(challenge, recv_ms, start_ms, half_rtt_ms=0.0):
    elapsed = effective_elapsed_ms(recv_ms, start_ms, half_rtt_ms)
    if elapsed < WHEEL_HUMAN_FLOOR_MS:
        return False
    return challenge.in_arc_at(challenge.needle_deg(elapsed), elapsed)
