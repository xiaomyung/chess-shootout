import math
from dataclasses import dataclass

from chessshootout.skillcheck.rng import seeded_floats
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS

MOLE_POPS_TOTAL = 5
MOLE_HITS_REQUIRED = 3
MOLE_POPS_COMPRESSED = 3
MOLE_HITS_COMPRESSED = 2
MOLE_COMPRESS_DEADLINE_MS = 3500.0
MOLE_INTRO_MS = 450.0
MOLE_INTRO_FLOOR_MS = 250.0
MOLE_FIRST_POP_MIN_MS = 450.0
MOLE_FIRST_POP_FLOOR_MS = 300.0
MOLE_PRECUE_MS = 250.0
MOLE_PRECUE_FLOOR_MS = 180.0
MOLE_GAP_MS = 140.0
MOLE_GAP_FLOOR_MS = 80.0
MOLE_GAP_JITTER_MS = 60.0
MOLE_UP_RAMP_MS = (850.0, 850.0, 780.0, 700.0, 750.0)
MOLE_POP_UP_FLOOR_MS = 600.0
MOLE_UP_PER_DIFF_MS = 9.0
MOLE_GRACE_MS = 120.0
MOLE_HOLE_MIN = 3
MOLE_HOLE_CAP = 5
MOLE_HOLE_RADIUS_CELLS = 3
MOLE_HITBOX_FRAC = 0.55
MOLE_RECOIL_LOCKOUT_MS = 180.0
MOLE_MIN_INTER_SHOT_MS = 80.0


def _clamped_hole_count(captured_value):
    return min(MOLE_HOLE_CAP, max(MOLE_HOLE_MIN, captured_value))


def _hole_sequence(seed, count, hole_count):
    floats = seeded_floats(f"mole:{seed}", MOLE_POPS_TOTAL)
    holes = [int(floats[0] * hole_count) % hole_count]
    for i in range(1, count):
        candidates = [hole for hole in range(hole_count) if hole != holes[-1]]
        holes.append(candidates[int(floats[i] * (hole_count - 1))])
    return holes


def _gap_sequence(seed):
    floats = seeded_floats(f"molegap:{seed}", MOLE_POPS_TOTAL)
    return [max(MOLE_GAP_FLOOR_MS, MOLE_GAP_MS + (f * 2.0 - 1.0) * MOLE_GAP_JITTER_MS)
            for f in floats]


def _up_times(count, value_diff):
    return [max(MOLE_POP_UP_FLOOR_MS, MOLE_UP_RAMP_MS[i] - MOLE_UP_PER_DIFF_MS * value_diff)
            for i in range(count)]


def _build(intro_ms, precue_ms, gaps, ups, first_up_min_ms):
    t = max(intro_ms, first_up_min_ms - precue_ms)
    times = []
    for i, up_ms in enumerate(ups):
        t_up = t + precue_ms
        times.append((t, t_up, t_up + up_ms))
        t = t_up + up_ms + gaps[i]
    return times


def _fit_scale(target, components):
    scale = target / sum(nominal for nominal, _ in components)
    for _ in components:
        floored = sum(floor for nominal, floor in components if nominal * scale < floor)
        free = sum(nominal for nominal, floor in components if nominal * scale >= floor)
        if free <= 0.0:
            return 0.0
        adjusted = (target - floored) / free
        if adjusted <= 0.0:
            return 0.0
        if adjusted == scale:
            break
        scale = adjusted
    return scale


def _scaled_times(scale, gaps, ups):
    return _build(
        max(MOLE_INTRO_FLOOR_MS, MOLE_INTRO_MS * scale),
        max(MOLE_PRECUE_FLOOR_MS, MOLE_PRECUE_MS * scale),
        [max(MOLE_GAP_FLOOR_MS, gap * scale) for gap in gaps],
        [max(MOLE_POP_UP_FLOOR_MS, up_ms * scale) for up_ms in ups],
        MOLE_FIRST_POP_FLOOR_MS,
    )


@dataclass(frozen=True)
class MolePop:
    hole: int
    t_telegraph_ms: float
    t_up_ms: float
    t_down_ms: float


@dataclass(frozen=True)
class MoleChallenge:
    pops: tuple
    hole_count: int
    hits_required: int
    deadline_ms: float

    @classmethod
    def from_seed(cls, seed, value_diff=0, deadline_ms=SKILLCHECK_DEADLINE_MS,
                  captured_value=0):
        compressed = deadline_ms < MOLE_COMPRESS_DEADLINE_MS
        count = MOLE_POPS_COMPRESSED if compressed else MOLE_POPS_TOTAL
        required = MOLE_HITS_COMPRESSED if compressed else MOLE_HITS_REQUIRED
        hole_count = _clamped_hole_count(captured_value)
        holes = _hole_sequence(seed, count, hole_count)
        gaps = _gap_sequence(seed)[:count]
        ups = _up_times(count, value_diff)
        times = _build(MOLE_INTRO_MS, MOLE_PRECUE_MS, gaps, ups, MOLE_FIRST_POP_MIN_MS)
        if times[-1][2] + MOLE_GRACE_MS > deadline_ms:
            components = ([(MOLE_INTRO_MS, MOLE_INTRO_FLOOR_MS)]
                          + [(MOLE_PRECUE_MS, MOLE_PRECUE_FLOOR_MS)] * count
                          + [(up_ms, MOLE_POP_UP_FLOOR_MS) for up_ms in ups]
                          + [(gap, MOLE_GAP_FLOOR_MS) for gap in gaps[:count - 1]])
            scale = _fit_scale(deadline_ms - MOLE_GRACE_MS, components)
            times = _scaled_times(scale, gaps, ups)
            inside = sum(1 for _, _, down in times if down + MOLE_GRACE_MS < deadline_ms)
            if inside < required:
                required = max(1, inside)
        pops = tuple(MolePop(hole, telegraph, up, down)
                     for hole, (telegraph, up, down) in zip(holes, times))
        return cls(pops=pops, hole_count=hole_count, hits_required=required,
                   deadline_ms=deadline_ms)

    def pop_up_at(self, elapsed_ms):
        for index, pop in enumerate(self.pops):
            if pop.t_up_ms <= elapsed_ms < pop.t_down_ms + MOLE_GRACE_MS:
                return index
        return None

    def hit_at(self, elapsed_ms, row_f, col_f, hole_squares, last_hit_pop=-1):
        index = self.pop_up_at(elapsed_ms)
        if index is None or index == last_hit_pop:
            return False
        hole = self.pops[index].hole
        if hole >= len(hole_squares):
            return False
        row, col = hole_squares[hole]
        return math.hypot(row_f - (row + 0.5), col_f - (col + 0.5)) <= MOLE_HITBOX_FRAC

    def remaining_hittable(self, elapsed_ms, last_hit_pop=-1):
        count = 0
        for index, pop in enumerate(self.pops):
            if pop.t_down_ms + MOLE_GRACE_MS <= elapsed_ms:
                continue
            if index == last_hit_pop and pop.t_up_ms <= elapsed_ms:
                continue
            count += 1
        return count

    def quota_unreachable(self, elapsed_ms, hits, last_hit_pop=-1):
        return hits + self.remaining_hittable(elapsed_ms, last_hit_pop) < self.hits_required


def _free_squares(capture_sq, blocked, radius, board_size):
    row0, col0 = capture_sq
    return [(row, col)
            for row in range(max(0, row0 - radius), min(board_size, row0 + radius + 1))
            for col in range(max(0, col0 - radius), min(board_size, col0 + radius + 1))
            if (row, col) not in blocked]


def hole_squares(seed, captured_value, capture_sq, occupied, board_size=8):
    blocked = set(occupied)
    hole_count = _clamped_hole_count(captured_value)
    radius = MOLE_HOLE_RADIUS_CELLS
    candidates = _free_squares(capture_sq, blocked, radius, board_size)
    while len(candidates) < hole_count and radius < board_size - 1:
        radius += 1
        candidates = _free_squares(capture_sq, blocked, radius, board_size)
    floats = seeded_floats(f"moleholes:{seed}", MOLE_HOLE_CAP)
    picked = []
    for value in floats[:min(hole_count, len(candidates))]:
        picked.append(candidates.pop(int(value * len(candidates)) % len(candidates)))
    return tuple(picked)
