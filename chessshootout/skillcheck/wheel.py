import hashlib
from dataclasses import dataclass

WHEEL_ARC_DEGREES = 60.0
WHEEL_PERIOD_MS = 800.0
WHEEL_ARC_SHRINK_PER_ROTATION = 10.0
WHEEL_ARC_MIN_DEGREES = 5.0
WHEEL_HUMAN_FLOOR_MS = 120.0
WHEEL_RTT_CAP_MS = 200.0


def _seed_floats(seed):
    digest = hashlib.sha256(f"wheel:{seed}".encode("utf-8")).digest()
    first = int.from_bytes(digest[0:8], "big") / 2.0 ** 64
    second = int.from_bytes(digest[8:16], "big") / 2.0 ** 64
    return first, second


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
        rotations = int(max(elapsed_ms, 0.0) / self.period_ms)
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
