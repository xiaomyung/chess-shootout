from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.rng import move_roll_key, ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind
from chessshootout.skillcheck.wheel import (
    WHEEL_HUMAN_FLOOR_MS, WheelChallenge, period_for_diff)

SKILLCHECK_DEADLINE_MS = 5000.0
SKILLCHECK_HUMAN_FLOOR_MS = WHEEL_HUMAN_FLOOR_MS
SKILLCHECK_RTT_CAP_MS = 200.0

_PROMO_TYPE = {
    "q": PieceType.QUEEN, "r": PieceType.ROOK,
    "b": PieceType.BISHOP, "n": PieceType.KNIGHT,
}


def promo_value(promo_char):
    if promo_char is None:
        return 0
    return PIECE_VALUES.get(_PROMO_TYPE.get(promo_char), 0)


def value_diff_for(facts, promo_char=None):
    if facts.is_capture:
        return facts.capturer_value - facts.captured_value
    if facts.is_promotion:
        return promo_value(promo_char)
    return 0


def challenge_from(kind, seed, value_diff):
    if kind == SkillCheckKind.WHEEL:
        return WheelChallenge.from_seed(seed, period_ms=period_for_diff(value_diff))
    if kind == SkillCheckKind.AIM:
        return AimChallenge.from_seed(seed, value_diff)
    return None


def select_kind(secret, ply_index, backend, from_sq, to_sq, locks):
    if (from_sq, to_sq) in locks:
        return SkillCheckKind.NONE
    roll = ply_roll(secret, move_roll_key(ply_index, from_sq, to_sq))
    return select_skillcheck(backend, from_sq, to_sq, roll, locks)


def rtt_credit_ms(rtt_at_issue_ms, session_min_ms, cap_ms=SKILLCHECK_RTT_CAP_MS):
    return min(max(rtt_at_issue_ms, 0.0), max(session_min_ms, 0.0), cap_ms)


def shot_elapsed_ms(recv_ms, start_ms, credit_ms):
    return int(max(0.0, (recv_ms - start_ms) - credit_ms))


def is_past_deadline(elapsed_ms):
    return elapsed_ms > SKILLCHECK_DEADLINE_MS


def shot_wins(kind, challenge, elapsed_ms, miss_count=0):
    if elapsed_ms < SKILLCHECK_HUMAN_FLOOR_MS or is_past_deadline(elapsed_ms):
        return False
    if kind == SkillCheckKind.WHEEL:
        return challenge.in_arc_at(challenge.needle_deg(elapsed_ms), elapsed_ms)
    return challenge.on_target(elapsed_ms, miss_count)


def aim_expired(challenge, elapsed_ms, miss_count=0):
    return challenge.is_expired(elapsed_ms, miss_count)
