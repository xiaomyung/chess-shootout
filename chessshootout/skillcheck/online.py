from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.backend.utils import PROMO_TYPE_BY_LETTER
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.combo import COMBO_SERVER_MIN_INTER_PRESS_MS, ComboChallenge
from chessshootout.skillcheck.mole import MOLE_MIN_INTER_SHOT_MS, MoleChallenge
from chessshootout.skillcheck.rng import move_roll_key, ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import (
    SKILLCHECK_DEADLINE_MS, WHEEL_HUMAN_FLOOR_MS, WheelChallenge, period_for_diff)

SKILLCHECK_HUMAN_FLOOR_MS = WHEEL_HUMAN_FLOOR_MS
SKILLCHECK_LAG_BOUND_MS = 200.0
SKILLCHECK_TIME_FRACTION = 0.10

_MIN_INTER_INPUT_MS = {
    SkillCheckKind.WHACK: MOLE_MIN_INTER_SHOT_MS,
    SkillCheckKind.COMBO: COMBO_SERVER_MIN_INTER_PRESS_MS,
}


def skillcheck_deadline_ms(initial_seconds):
    if not initial_seconds:
        return SKILLCHECK_DEADLINE_MS
    tenth = initial_seconds * SKILLCHECK_TIME_FRACTION * 1000.0
    return min(SKILLCHECK_DEADLINE_MS, tenth)


def promo_value(promo_char):
    if promo_char is None:
        return 0
    return PIECE_VALUES.get(PROMO_TYPE_BY_LETTER.get(promo_char), 0)


def value_diff_for(facts, promo_char=None):
    if facts.is_promotion:
        return PIECE_VALUES[PieceType.PAWN] - promo_value(promo_char or "q")
    if facts.is_capture:
        return facts.capturer_value - facts.captured_value
    return 0


def challenge_from(kind, seed, value_diff, deadline_ms=SKILLCHECK_DEADLINE_MS,
                   captured_value=0):
    if kind == SkillCheckKind.WHEEL:
        return WheelChallenge.from_seed(seed, period_ms=period_for_diff(value_diff))
    if kind == SkillCheckKind.AIM:
        return AimChallenge.from_seed(seed, value_diff)
    if kind == SkillCheckKind.WHACK:
        return MoleChallenge.from_seed(seed, value_diff, deadline_ms, captured_value)
    if kind == SkillCheckKind.COMBO:
        return ComboChallenge.from_seed(seed, value_diff, deadline_ms, captured_value)
    return None


def select_kind(secret, ply_index, backend, from_sq, to_sq, locks, facts=None):
    if (from_sq, to_sq) in locks:
        return SkillCheckKind.NONE
    roll = ply_roll(secret, move_roll_key(ply_index, from_sq, to_sq))
    return select_skillcheck(backend, from_sq, to_sq, roll, locks, facts)


def adjudicated_elapsed_ms(client_elapsed_ms, recv_ms, start_ms,
                           bound_ms=SKILLCHECK_LAG_BOUND_MS):
    raw = recv_ms - start_ms
    bounded = min(max(client_elapsed_ms, raw - bound_ms), raw)
    return int(max(0.0, bounded))


def is_past_deadline(elapsed_ms, deadline_ms=SKILLCHECK_DEADLINE_MS):
    return elapsed_ms > deadline_ms


def shot_wins(kind, challenge, elapsed_ms, miss_count=0, deadline_ms=SKILLCHECK_DEADLINE_MS,
              *, progress=0, direction=None, target=None, hole_squares=None,
              last_hit_pop=-1, flipped=False):
    if elapsed_ms < SKILLCHECK_HUMAN_FLOOR_MS or is_past_deadline(elapsed_ms, deadline_ms):
        return False
    if kind == SkillCheckKind.WHEEL:
        return challenge.in_arc_at(challenge.needle_deg(elapsed_ms), elapsed_ms)
    if kind == SkillCheckKind.AIM:
        return challenge.on_target(elapsed_ms, miss_count)
    if kind == SkillCheckKind.WHACK:
        if target is None or hole_squares is None:
            return False
        return challenge.hit_at(elapsed_ms, target[0], target[1], hole_squares, last_hit_pop,
                                flipped=flipped)
    if kind == SkillCheckKind.COMBO:
        return challenge.press_correct(progress, direction)
    return False


def hits_required(kind, challenge):
    if kind == SkillCheckKind.WHACK:
        return challenge.hits_required
    if kind == SkillCheckKind.COMBO:
        return challenge.prompt_count
    return 1


def aim_expired(challenge, elapsed_ms, miss_count=0):
    return challenge.is_expired(elapsed_ms, miss_count)


def check_expired(kind, challenge, elapsed_ms, miss_count=0, progress=0, last_hit_pop=-1):
    if kind == SkillCheckKind.AIM:
        return aim_expired(challenge, elapsed_ms, miss_count)
    if kind == SkillCheckKind.WHACK:
        return (challenge.quota_unreachable(elapsed_ms, progress, last_hit_pop)
                or challenge.whiffs_exhausted(miss_count))
    if kind == SkillCheckKind.COMBO:
        return challenge.wrongs_exhausted(miss_count)
    return False


def min_inter_input_ms(kind):
    return _MIN_INTER_INPUT_MS.get(kind, 0.0)
