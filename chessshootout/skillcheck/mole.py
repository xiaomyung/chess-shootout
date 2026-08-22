from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from chessshootout.backend.pieces import PIECE_VALUES, Piece, PieceType
from chessshootout.backend.utils import BOARD_SIZE
from chessshootout.skillcheck.rng import seeded_floats
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS

MOLE_POPS_TOTAL = 5
MOLE_HITS_REQUIRED = 3
MOLE_MINOR_PIECE_VALUE = 3
MOLE_QUEEN_PIECE_VALUE = PIECE_VALUES[PieceType.QUEEN]
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
MOLE_FIT_EPSILON_MS = 0.001
MOLE_HOLE_MIN = 3
MOLE_HOLE_CAP = 5
MOLE_HOLE_RADIUS_CELLS = 3
MOLE_HITBOX_RX_FRAC = 0.40
MOLE_HITBOX_RY_FRAC = 0.52
MOLE_HITBOX_CY_FRAC = -0.30
MOLE_RECOIL_LOCKOUT_MS = 180.0
MOLE_MIN_INTER_SHOT_MS = 80.0
MOLE_MAX_WHIFFS = 3
MOLE_TAUNTS = ("missed me", "lol", "nice aim", "rip", "too slow",
               "2 ez", "bye bye", "not even close", "lmaoo", "git gud")


def hitbox_lift(flipped: bool) -> float:
    """
    Give how far above its pit square a mole's hit box sits. The piece rises
    out of the hole, so the box has to hug the drawn body rather than the
    square, and the lift flips over when the board is seen from Black's side

    :param flipped: True when the board is drawn from Black's side, which
        reverses which way is up in board rows
    :returns: row offset to add to the pit square centre, in cell heights
    """
    return -MOLE_HITBOX_CY_FRAC if flipped else MOLE_HITBOX_CY_FRAC


def pick_taunt(seed: str) -> str:
    """
    Pick the jeer the mole leaves behind when a player loses a whack check,
    drawn from the check's seed so both players see the same one

    :param seed: seed of the check that was just lost, which both sides hold
    :returns: taunt text to show over the square
    """
    roll = seeded_floats(f"moletaunt:{seed}", 1)[0]
    return MOLE_TAUNTS[int(roll * len(MOLE_TAUNTS)) % len(MOLE_TAUNTS)]


def occupied_squares(state: list[list[Piece | None]],
                     board_size: int) -> list[tuple[int, int]]:
    """
    List the squares that currently hold a piece, so the pit layout can avoid
    them. Mole holes are only ever dug in empty ground

    :param state: board array of pieces and empty squares
    :param board_size: side length of the board to scan
    :returns: (row, col) of every occupied square, in reading order
    """
    return [(row, col)
            for row in range(board_size) for col in range(board_size)
            if state[row][col] is not None]


def _clamped_hole_count(captured_value: int) -> int:
    """
    Give how many pits are dug for a capture: the bigger the piece being
    taken, the more ground the player has to watch, held between a floor and
    a cap

    :param captured_value: material value of the piece being captured
    :returns: number of pits to dig
    """
    return min(MOLE_HOLE_CAP, max(MOLE_HOLE_MIN, captured_value))


def _required_hits(captured_value: int) -> int:
    """
    Give how many moles have to be hit to win, the quota that makes a big
    capture harder: three for a pawn, four for a piece, and all five pops for
    a queen

    :param captured_value: material value of the piece being captured
    :returns: number of hits needed to land the move
    """
    return (MOLE_HITS_REQUIRED + (captured_value >= MOLE_MINOR_PIECE_VALUE)
            + (captured_value >= MOLE_QUEEN_PIECE_VALUE))


def _compressed_hits(required: int) -> int:
    """
    Scale the hit quota down for a short check, where only three pops fit in
    the time available. The quota keeps its proportion but never falls below
    two, so a compressed check is still a fight

    :param required: quota the full-length schedule would have used
    :returns: quota for the compressed schedule
    """
    return max(MOLE_HITS_COMPRESSED,
               round(required * MOLE_POPS_COMPRESSED / MOLE_POPS_TOTAL))


def _hole_sequence(seed: str, count: int, hole_count: int) -> list[int]:
    """
    Decide which pit each mole pops out of, drawn from the seed. The same pit
    is never used twice in a row, so the player always has to move the gun

    :param seed: per-check seed, which fixes the whole pop order
    :param count: how many pops the schedule has
    :param hole_count: how many pits were dug
    :returns: pit index per pop, in order
    """
    floats = seeded_floats(f"mole:{seed}", MOLE_POPS_TOTAL)
    holes = [int(floats[0] * hole_count) % hole_count]
    for i in range(1, count):
        candidates = [hole for hole in range(hole_count) if hole != holes[-1]]
        holes.append(candidates[int(floats[i] * (hole_count - 1))])
    return holes


def _gap_sequence(seed: str) -> list[float]:
    """
    Decide the pause between one mole dropping and the next being telegraphed,
    jittered from the seed so the rhythm is never a metronome

    :param seed: per-check seed, which fixes the jitter on every gap
    :returns: gap in milliseconds per pop, never below the floor
    """
    floats = seeded_floats(f"molegap:{seed}", MOLE_POPS_TOTAL)
    return [max(MOLE_GAP_FLOOR_MS, MOLE_GAP_MS + (f * 2.0 - 1.0) * MOLE_GAP_JITTER_MS)
            for f in floats]


def _up_times(count: int, value_diff: int) -> list[float]:
    """
    Decide how long each mole stays up, following a ramp that tightens as the
    check goes on. A lopsided capture shortens every window, which is how
    material difficulty reaches this mini-game

    :param count: how many pops the schedule has
    :param value_diff: capturer value minus captured value
    :returns: up-time in milliseconds per pop, never below the floor
    """
    return [max(MOLE_POP_UP_FLOOR_MS, MOLE_UP_RAMP_MS[i] - MOLE_UP_PER_DIFF_MS * value_diff)
            for i in range(count)]


def _build_times(intro_ms: float, precue_ms: float, gaps: list[float], ups: list[float],
                 first_up_min_ms: float) -> list[tuple[float, float, float]]:
    """
    Lay the pops out on one timeline: telegraph, up, down, then a pause before
    the next. The first mole is held back so the check has a readable start
    instead of a pop the instant it opens

    :param intro_ms: quiet time before anything is telegraphed
    :param precue_ms: warning time between a telegraph and its mole appearing
    :param gaps: pause after each pop, in milliseconds
    :param ups: how long each mole stays up, in milliseconds
    :param first_up_min_ms: earliest the first mole may appear
    :returns: (telegraph, up, down) times in milliseconds per pop, measured
        from the start of the check
    """
    t = max(intro_ms, first_up_min_ms - precue_ms)
    times = []
    for i, up_ms in enumerate(ups):
        t_up = t + precue_ms
        times.append((t, t_up, t_up + up_ms))
        t = t_up + up_ms + gaps[i]
    return times


def _fit_scale(target: float, components: list[tuple[float, float]]) -> float:
    """
    Find the one factor that squeezes a whole schedule into the time
    available, respecting each part's own floor. Parts already sitting at
    their floor stop shrinking and the rest absorb what is left, re-solved
    until it settles

    :param target: total milliseconds the schedule has to fit into
    :param components: (nominal duration, floor) for every part of it
    :returns: factor to scale the nominal durations by, 0.0 when not even the
        floors fit
    """
    scale = target / sum(nominal for nominal, _ in components)
    for _ in range(len(components)):
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


def _scaled_times(scale: float, gaps: list[float],
                  ups: list[float]) -> list[tuple[float, float, float]]:
    """
    Rebuild the pop timeline with every part scaled down and then held at its
    floor, the second half of fitting a schedule into a short deadline

    :param scale: factor worked out by _fit_scale
    :param gaps: nominal pause after each pop, in milliseconds
    :param ups: nominal up-time per pop, in milliseconds
    :returns: (telegraph, up, down) times in milliseconds per pop
    """
    return _build_times(
        max(MOLE_INTRO_FLOOR_MS, MOLE_INTRO_MS * scale),
        max(MOLE_PRECUE_FLOOR_MS, MOLE_PRECUE_MS * scale),
        [max(MOLE_GAP_FLOOR_MS, gap * scale) for gap in gaps],
        [max(MOLE_POP_UP_FLOOR_MS, up_ms * scale) for up_ms in ups],
        MOLE_FIRST_POP_FLOOR_MS,
    )


def _refit_times(count: int, gaps: list[float], ups: list[float], deadline_ms: float,
                 required: int) -> tuple[list[tuple[float, float, float]], int]:
    """
    Squeeze a schedule that overruns its deadline back inside it, and lower
    the hit quota when even the floored schedule cannot show enough moles.
    Settling this at build time is what keeps every challenge winnable and
    identical on both sides

    :param count: how many pops the schedule has
    :param gaps: nominal pause after each pop, in milliseconds
    :param ups: nominal up-time per pop, in milliseconds
    :param deadline_ms: milliseconds the whole check has to fit into
    :param required: hit quota before the refit
    :returns: the refitted (telegraph, up, down) times and the quota that
        actually fits inside them
    """
    components = ([(MOLE_INTRO_MS, MOLE_INTRO_FLOOR_MS)]
                  + [(MOLE_PRECUE_MS, MOLE_PRECUE_FLOOR_MS)] * count
                  + [(up_ms, MOLE_POP_UP_FLOOR_MS) for up_ms in ups]
                  + [(gap, MOLE_GAP_FLOOR_MS) for gap in gaps[:count - 1]])
    scale = _fit_scale(deadline_ms - MOLE_GRACE_MS, components)
    times = _scaled_times(scale, gaps, ups)
    inside = sum(1 for _, _, down in times
                 if down + MOLE_GRACE_MS <= deadline_ms + MOLE_FIT_EPSILON_MS)
    if inside < required:
        required = max(1, inside)
    return times, required


@dataclass(frozen=True)
class MolePop:
    """
    One scheduled mole: which pit it uses and the three moments of its life --
    telegraphed, up, and back down. The times are milliseconds from the start
    of the check, so they mean the same thing to the judge and to both screens
    """

    hole: int
    t_telegraph_ms: float
    t_up_ms: float
    t_down_ms: float


@dataclass(frozen=True)
class MoleChallenge:
    """
    One whack-a-mole challenge: the whole pop schedule, how many pits were dug
    and how many hits the player owes. Built purely from a seed, so the server
    re-derives the very schedule it judges shots against
    """

    pops: tuple[MolePop, ...]
    hole_count: int
    hits_required: int
    deadline_ms: float

    @classmethod
    def from_seed(cls, seed: str, value_diff: int = 0,
                  deadline_ms: float = SKILLCHECK_DEADLINE_MS,
                  captured_value: int = 0) -> "MoleChallenge":
        """
        Build the whole challenge from its seed: how many pits, which mole
        pops when, and how many hits are owed. A deadline too short for the
        full schedule gets a compressed one, refitted and if need be with a
        lowered quota, so the check always fits the time it is given

        :param seed: per-check seed, fresh random text that carries no trace
            of the room's selection secret
        :param value_diff: capturer value minus captured value, which shortens
            every up-window for a lopsided capture
        :param deadline_ms: milliseconds the check may run for, normally
            SKILLCHECK_DEADLINE_MS or the smaller share a fast time control
            allows
        :param captured_value: material value of the piece being taken, which
            sets both the pit count and the hit quota
        :returns: the challenge to render and adjudicate against
        """
        compressed = deadline_ms < MOLE_COMPRESS_DEADLINE_MS
        count = MOLE_POPS_COMPRESSED if compressed else MOLE_POPS_TOTAL
        required = _required_hits(captured_value)
        if compressed:
            required = _compressed_hits(required)
        hole_count = _clamped_hole_count(captured_value)
        holes = _hole_sequence(seed, count, hole_count)
        gaps = _gap_sequence(seed)[:count]
        ups = _up_times(count, value_diff)
        times = _build_times(MOLE_INTRO_MS, MOLE_PRECUE_MS, gaps, ups, MOLE_FIRST_POP_MIN_MS)
        if times[-1][2] + MOLE_GRACE_MS > deadline_ms:
            times, required = _refit_times(count, gaps, ups, deadline_ms, required)
        pops = tuple(MolePop(hole, telegraph, up, down)
                     for hole, (telegraph, up, down) in zip(holes, times))
        return cls(pops=pops, hole_count=hole_count, hits_required=required,
                   deadline_ms=deadline_ms)

    def pop_up_at(self, elapsed_ms: float) -> int | None:
        """
        Say which mole is up right now, the question every shot starts from.
        The window runs a little past the mole dropping, so a shot that looked
        fair on the player's screen still counts

        :param elapsed_ms: milliseconds since the check started
        :returns: index of the mole that is up, or None when none is
        """
        for index, pop in enumerate(self.pops):
            if pop.t_up_ms <= elapsed_ms < pop.t_down_ms + MOLE_GRACE_MS:
                return index
        return None

    def hit_at(self, elapsed_ms: float, row_f: float, col_f: float,
               hole_squares: Sequence[tuple[int, int]], last_hit_pop: int = -1, *,
               flipped: bool = False) -> bool:
        """
        Judge one whack shot: it hits when a mole is up and the shot lands
        inside the upright oval drawn around that mole. The shot arrives in
        board coordinates and never in pixels, which is what lets the server
        judge it without knowing anything about the shooter's window

        :param elapsed_ms: milliseconds since the check started
        :param row_f: shot row in board space, where a whole number is a
            square edge and a half is its centre
        :param col_f: shot column in that same board space
        :param hole_squares: pit squares in pit order, re-derived by whoever
            is judging rather than taken from the shooter
        :param last_hit_pop: mole already hit, so one mole cannot be shot
            twice
        :param flipped: True when the mover sees the board from Black's side,
            which flips the hit box's lift
        :returns: True when the shot hits the mole that is up
        """
        index = self.pop_up_at(elapsed_ms)
        if index is None or index == last_hit_pop:
            return False
        hole = self.pops[index].hole
        if hole >= len(hole_squares):
            return False
        row, col = hole_squares[hole]
        lift = hitbox_lift(flipped)
        ccy = row + 0.5 + lift
        ccx = col + 0.5
        return (((col_f - ccx) / MOLE_HITBOX_RX_FRAC) ** 2
                + ((row_f - ccy) / MOLE_HITBOX_RY_FRAC) ** 2) <= 1.0

    def remaining_hittable(self, elapsed_ms: float, last_hit_pop: int = -1) -> int:
        """
        Count the moles that can still be hit from this moment on, which is
        what separates a lost check from a merely bad one

        :param elapsed_ms: milliseconds since the check started
        :param last_hit_pop: mole already hit, which stops counting once it is
            the one up
        :returns: how many pops are still catchable
        """
        return sum(1 for index, pop in enumerate(self.pops)
                   if pop.t_down_ms + MOLE_GRACE_MS > elapsed_ms
                   and not (index == last_hit_pop and pop.t_up_ms <= elapsed_ms))

    def quota_unreachable(self, elapsed_ms: float, hits: int, last_hit_pop: int = -1) -> bool:
        """
        Tell whether the quota can no longer be met, which ends the check
        early instead of making a player sit out a schedule they have already
        lost. The server tests the same thing, so going quiet saves nobody

        :param elapsed_ms: milliseconds since the check started
        :param hits: moles hit so far
        :param last_hit_pop: mole already hit, left out of what remains
        :returns: True when the check is lost
        """
        return hits + self.remaining_hittable(elapsed_ms, last_hit_pop) < self.hits_required

    def pop_mandatory(self, index: int, hits: int) -> bool:
        """
        Tell whether this mole has to be hit for the quota to still be
        reachable, which the view uses to mark the pop that cannot be missed

        :param index: position of the mole in the schedule
        :param hits: moles hit so far
        :returns: True when missing this one loses the check
        """
        return hits + (len(self.pops) - index) == self.hits_required

    def whiffs_exhausted(self, miss_count: int) -> bool:
        """
        Tell whether the player has run out of wild shots. Whack forgives a
        few misses before the check is lost, which keeps a nervous player in
        it without making the gun free to spray

        :param miss_count: shots fired that hit nothing
        :returns: True when the misses already spent lose the check
        """
        return miss_count >= MOLE_MAX_WHIFFS


def _free_squares(capture_sq: tuple[int, int], blocked: set[tuple[int, int]], radius: int,
                  board_size: int) -> list[tuple[int, int]]:
    """
    List the empty squares within a square ring of the capture, the ground the
    pits may be dug in. Keeping them near the capture keeps the mini-game
    where the player is already looking

    :param capture_sq: (row, col) the capture happens on
    :param blocked: squares that already hold a piece
    :param radius: how many squares out from the capture to consider
    :param board_size: side length of the board
    :returns: (row, col) candidates, in reading order
    """
    row0, col0 = capture_sq
    return [(row, col)
            for row in range(max(0, row0 - radius), min(board_size, row0 + radius + 1))
            for col in range(max(0, col0 - radius), min(board_size, col0 + radius + 1))
            if (row, col) not in blocked]


def _min_gap_squared(square: tuple[int, int], picked: list[tuple[int, int]]) -> int:
    """
    Give how far a candidate square sits from the nearest pit already placed.
    Distances are compared as whole squares, which keeps the arithmetic exact
    so a tie really is a tie and the layout stays reproducible

    :param square: (row, col) candidate being measured
    :param picked: pits already placed, never empty
    :returns: squared distance to the closest of them
    """
    row, col = square
    return min((row - other_row) ** 2 + (col - other_col) ** 2
               for other_row, other_col in picked)


def _farthest_index(candidates: list[tuple[int, int]], picked: list[tuple[int, int]],
                    tie_value: float) -> int:
    """
    Choose the candidate that sits furthest from every pit already placed,
    which spreads the pits out instead of letting them clump. An exact tie is
    broken by a seeded draw, so the walk stays a pure function of the seed

    :param candidates: (row, col) squares still available
    :param picked: pits already placed
    :param tie_value: seeded float in [0, 1) that settles an exact tie
    :returns: index into candidates of the pit to place next
    """
    best = -1
    tied = []
    for index, square in enumerate(candidates):
        gap = _min_gap_squared(square, picked)
        if gap > best:
            best = gap
            tied = [index]
        elif gap == best:
            tied.append(index)
    return tied[int(tie_value * len(tied)) % len(tied)]


def hole_squares(seed: str, captured_value: int, capture_sq: tuple[int, int],
                 occupied: Iterable[tuple[int, int]],
                 board_size: int = BOARD_SIZE) -> tuple[tuple[int, int], ...]:
    """
    Work out where the pits are dug for one whack check: a seeded
    farthest-point walk over the free squares around the capture. This is
    load-bearing for fair play, because the judge re-derives the layout in its
    own process rather than trusting geometry a client reports

    :param seed: per-check seed, the only thing the layout varies with
    :param captured_value: material value of the piece being taken, which sets
        how many pits are dug
    :param capture_sq: (row, col) the capture happens on
    :param occupied: squares holding a piece, which cannot be dug
    :param board_size: side length of the board
    :returns: pit squares as (row, col), in the order the pops index them by
    """
    blocked = set(occupied)
    hole_count = _clamped_hole_count(captured_value)
    radius = MOLE_HOLE_RADIUS_CELLS
    candidates = _free_squares(capture_sq, blocked, radius, board_size)
    while len(candidates) < hole_count and radius < board_size - 1:
        radius += 1
        candidates = _free_squares(capture_sq, blocked, radius, board_size)
    if not candidates:
        return ()
    floats = seeded_floats(f"moleholes:{seed}", MOLE_HOLE_CAP)
    total = min(hole_count, len(candidates))
    picked = [candidates.pop(int(floats[0] * len(candidates)) % len(candidates))]
    for tie_value in floats[1:total]:
        picked.append(candidates.pop(_farthest_index(candidates, picked, tie_value)))
    return tuple(picked)


def holes_for(seed: str, captured_value: int, capture_sq: tuple[int, int],
              state: list[list[Piece | None]],
              board_size: int = BOARD_SIZE) -> tuple[tuple[int, int], ...]:
    """
    Dig the pits for a whack check straight from a board position, the call
    both the server and the local game make as a check is armed. The server
    stores what comes back on the pending check and judges every shot against
    it, so a client can never nominate its own holes

    :param seed: per-check seed, fresh random text that carries no trace of
        the room's selection secret
    :param captured_value: material value of the piece being taken
    :param capture_sq: (row, col) the capture happens on
    :param state: board array the occupied squares are read from
    :param board_size: side length of that board
    :returns: pit squares as (row, col), in the order the pops index them by
    """
    return hole_squares(seed, captured_value, capture_sq,
                        occupied_squares(state, board_size), board_size)
