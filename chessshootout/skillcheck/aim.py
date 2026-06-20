import hashlib
import math
from dataclasses import dataclass

from chessshootout.skillcheck.wheel import needle_speed_mult

AIM_DEADLINE_MS = 5000.0
AIM_TRAVEL_PERIOD_MS = 1500.0
AIM_ROTATION_PERIOD_MS = 3700.0
AIM_LOBE_FRACTION = 1.3
AIM_HIT_RADIUS_FRAC = 0.40
AIM_HIT_ASPECT = 0.6
AIM_START_GAP_MS = 220.0
AIM_START_JITTER = 0.06
AIM_SWAY_STEP = 0.10
AIM_SWAY_CAP = 1.7
AIM_SHRINK_STEP = 0.10
AIM_SHRINK_CAP = 1.7
AIM_SHRINK_EXP = 2.5

_CROSSINGS = (0.25, 0.75)


def _seed_floats(seed):
    digest = hashlib.sha256("aim:{}".format(seed).encode("utf-8")).digest()
    a = int.from_bytes(digest[0:8], "big") / 2.0 ** 64
    b = int.from_bytes(digest[8:16], "big") / 2.0 ** 64
    c = int.from_bytes(digest[16:24], "big") / 2.0 ** 64
    return a, b, c


def _amplitude():
    return AIM_LOBE_FRACTION / 2.0


@dataclass(frozen=True)
class AimChallenge:
    phase0: float
    rotation0_deg: float
    travel_period_ms: float
    rotation_period_ms: float
    deadline_ms: float

    @classmethod
    def from_seed(cls, seed, value_diff=0, deadline_ms=AIM_DEADLINE_MS):
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

    def travel_mult(self, miss_count):
        return min(AIM_SWAY_CAP, 1.0 + AIM_SWAY_STEP * miss_count)

    def shrink_mult(self, miss_count):
        return min(AIM_SHRINK_CAP, 1.0 + AIM_SHRINK_STEP * miss_count)

    def param_at(self, elapsed_ms, miss_count=0):
        return (self.phase0
                + (elapsed_ms / self.travel_period_ms) * self.travel_mult(miss_count)) % 1.0

    def rotation_deg_at(self, elapsed_ms, miss_count=0):
        mult = self.travel_mult(miss_count)
        return self.rotation0_deg + 360.0 * (elapsed_ms / self.rotation_period_ms) * mult

    def lobe_point(self, t):
        theta = 2.0 * math.pi * t
        amp = _amplitude()
        return (amp * math.cos(theta), amp * math.sin(theta) * math.cos(theta))

    def _rotate(self, point, rot_deg):
        rot = math.radians(rot_deg)
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        return (point[0] * cos_r - point[1] * sin_r, point[0] * sin_r + point[1] * cos_r)

    def reticle_offset(self, elapsed_ms, miss_count=0):
        point = self.lobe_point(self.param_at(elapsed_ms, miss_count))
        return self._rotate(point, self.rotation_deg_at(elapsed_ms, miss_count))

    def path_offsets(self, elapsed_ms, miss_count, samples):
        rot_deg = self.rotation_deg_at(elapsed_ms, miss_count)
        return [self._rotate(self.lobe_point(i / samples), rot_deg)
                for i in range(samples + 1)]

    def piece_scale(self, elapsed_ms, miss_count=0):
        p = min(1.0, (elapsed_ms / self.deadline_ms) * self.shrink_mult(miss_count))
        return max(0.0, 1.0 - p ** AIM_SHRINK_EXP)

    def hit_radius(self, elapsed_ms, miss_count=0):
        return AIM_HIT_RADIUS_FRAC * self.piece_scale(elapsed_ms, miss_count)

    def hit_radii(self, elapsed_ms, miss_count=0):
        ry = self.hit_radius(elapsed_ms, miss_count)
        return AIM_HIT_ASPECT * ry, ry

    def contains(self, fx, fy, elapsed_ms, miss_count=0):
        rx, ry = self.hit_radii(elapsed_ms, miss_count)
        if rx <= 0.0 or ry <= 0.0:
            return False
        return (fx / rx) ** 2 + (fy / ry) ** 2 <= 1.0

    def on_target(self, elapsed_ms, miss_count=0):
        fx, fy = self.reticle_offset(elapsed_ms, miss_count)
        return self.contains(fx, fy, elapsed_ms, miss_count)

    def is_expired(self, elapsed_ms, miss_count=0):
        return self.piece_scale(elapsed_ms, miss_count) <= 0.0
