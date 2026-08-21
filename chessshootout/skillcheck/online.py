from collections.abc import Container, Sequence
from typing import Any

from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.backend.utils import PROMO_TYPE_BY_LETTER, Square
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.combo import COMBO_SERVER_MIN_INTER_PRESS_MS, ComboChallenge
from chessshootout.skillcheck.mole import MOLE_MIN_INTER_SHOT_MS, MoleChallenge
from chessshootout.skillcheck.rng import move_roll_key, ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts
from chessshootout.skillcheck.wheel import (
    SKILLCHECK_DEADLINE_MS, WHEEL_HUMAN_FLOOR_MS, WheelChallenge, period_for_diff)

SKILLCHECK_HUMAN_FLOOR_MS = WHEEL_HUMAN_FLOOR_MS
SKILLCHECK_LAG_BOUND_MS = 200.0
SKILLCHECK_TIME_FRACTION = 0.10

_MIN_INTER_INPUT_MS = {
    SkillCheckKind.WHACK: MOLE_MIN_INTER_SHOT_MS,
    SkillCheckKind.COMBO: COMBO_SERVER_MIN_INTER_PRESS_MS,
}


def skillcheck_deadline_ms(initial_seconds: float) -> float:
    """
    Give how long a skill check may run in this game, the server-owned figure
    every kind is then built against. It is the standard deadline or a tenth
    of the starting clock, whichever is shorter, so a fast game never spends a
    large slice of its own time on mini-games -- there is no third term

    :param initial_seconds: starting time on each player's clock in seconds,
        or zero for a game with no clock
    :returns: deadline in milliseconds, never above SKILLCHECK_DEADLINE_MS
    """
    if not initial_seconds:
        return SKILLCHECK_DEADLINE_MS
    tenth = initial_seconds * SKILLCHECK_TIME_FRACTION * 1000.0
    return min(SKILLCHECK_DEADLINE_MS, tenth)


def promo_value(promo_char: str | None) -> int:
    """
    Give the material value of the piece a pawn is promoting to, read from the
    single letter the wire carries for it

    :param promo_char: promotion letter (q, r, b or n), or None when the move
        is not a promotion
    :returns: material value of that piece, zero when there is none
    """
    if promo_char is None:
        return 0
    return PIECE_VALUES.get(PROMO_TYPE_BY_LETTER.get(promo_char), 0)


def value_diff_for(facts: TriggerFacts, promo_char: str | None = None) -> int:
    """
    Give the material swing behind a move, the one number that sets how hard
    its check plays. A promotion is scored as the pawn against what it turns
    into and a capture as the capturer against its victim, so taking downwards
    is always the harder shot

    :param facts: what the move does, from compute_facts
    :param promo_char: promotion letter when the move promotes, taken as a
        queen when the player has not chosen yet
    :returns: capturer value minus captured value, zero for a quiet move
    """
    if facts.is_promotion:
        return PIECE_VALUES[PieceType.PAWN] - promo_value(promo_char or "q")
    if facts.is_capture:
        return facts.capturer_value - facts.captured_value
    return 0


def challenge_from(kind: SkillCheckKind, seed: str, value_diff: int,
                   deadline_ms: float = SKILLCHECK_DEADLINE_MS,
                   captured_value: int = 0
                   ) -> WheelChallenge | AimChallenge | MoleChallenge | ComboChallenge | None:
    """
    Build the challenge behind one skill check, the single place any of the
    four engines is constructed. Both sides call it -- the server to judge
    shots, the client to draw the same challenge -- and the server rebuilds it
    from the seed alone rather than from anything a client sends

    :param kind: which mini-game is running
    :param seed: per-check seed, fresh random text that carries no trace of
        the room's selection secret
    :param value_diff: capturer value minus captured value, which sets the
        difficulty
    :param deadline_ms: milliseconds the check may run for, from
        skillcheck_deadline_ms
    :param captured_value: material value of the piece being taken, which
        sizes the whack layout and the length of a combo
    :returns: the challenge to render and judge against, or None for a kind
        that fires no check
    """
    if kind == SkillCheckKind.WHEEL:
        return WheelChallenge.from_seed(seed, period_ms=period_for_diff(value_diff))
    if kind == SkillCheckKind.AIM:
        return AimChallenge.from_seed(seed, value_diff)
    if kind == SkillCheckKind.WHACK:
        return MoleChallenge.from_seed(seed, value_diff, deadline_ms, captured_value)
    if kind == SkillCheckKind.COMBO:
        return ComboChallenge.from_seed(seed, value_diff, deadline_ms, captured_value)
    return None


def select_kind(secret: str, ply_index: int, backend: Backend, from_sq: Square, to_sq: Square,
                locks: Container[tuple[Square, Square]],
                facts: TriggerFacts | None = None) -> SkillCheckKind:
    """
    Decide which check, if any, a move fires -- the authoritative call the
    server makes for every online move. The roll is drawn from the room's
    secret, which never goes on any wire, so nobody can see a check coming or
    shop around for a move that avoids one

    :param secret: the room's skill-check secret, kept server-side only
    :param ply_index: plies played so far, also server-side only, so the same
        move later in the game draws afresh
    :param backend: engine holding the position the move is judged against
    :param from_sq: square the piece would leave
    :param to_sq: square it would land on
    :param locks: (from, to) pairs already fluffed this turn, which fire no
        check because they cannot be played at all
    :param facts: trigger facts when the caller already probed the move, or
        None to probe it here
    :returns: the kind to run, NONE when the move simply lands
    """
    if (from_sq, to_sq) in locks:
        return SkillCheckKind.NONE
    roll = ply_roll(secret, move_roll_key(ply_index, from_sq, to_sq))
    return select_skillcheck(backend, from_sq, to_sq, roll, locks, facts)


def adjudicated_elapsed_ms(client_elapsed_ms: float, recv_ms: float, start_ms: float,
                           bound_ms: float = SKILLCHECK_LAG_BOUND_MS) -> int:
    """
    Decide how far into a check a shot really was, the number every online
    verdict is then measured at. The shooter's own reading is trusted only
    inside a window ending at the moment the shot arrived, so an honest laggy
    player is judged fairly while a modded one can shift its timing by no more
    than that window

    :param client_elapsed_ms: milliseconds the shooter says had passed
    :param recv_ms: when the shot arrived, on the server clock
    :param start_ms: when the check was armed, on the same clock
    :param bound_ms: how far back before the arrival gap a claim may reach
    :returns: whole milliseconds to judge the shot at, never negative
    """
    raw = recv_ms - start_ms
    bounded = min(max(client_elapsed_ms, raw - bound_ms), raw)
    return int(max(0.0, bounded))


def adjudicated_flipped(color: str) -> bool:
    """
    Say whether a side sees the board from Black's end, which the whack hit
    box needs because a mole is drawn above its hole. The judge works it out
    from the mover's colour rather than from anything a client sends

    :param color: side that is moving, white or black
    :returns: True when that side's board is drawn flipped
    """
    return color == "black"


def is_past_deadline(elapsed_ms: float, deadline_ms: float = SKILLCHECK_DEADLINE_MS) -> bool:
    """
    Tell whether a shot arrived after the check's time was up. The deadline
    runs from the moment the check was armed and nothing resets it, so falling
    silent or dropping the connection cannot stretch it

    :param elapsed_ms: milliseconds into the check the shot is judged at
    :param deadline_ms: this check's deadline in milliseconds
    :returns: True when the shot is too late to count
    """
    return elapsed_ms > deadline_ms


def shot_wins(kind: SkillCheckKind, challenge: Any, elapsed_ms: float, miss_count: int = 0,
              deadline_ms: float = SKILLCHECK_DEADLINE_MS, *, progress: int = 0,
              direction: str | None = None, target: tuple[float, float] | None = None,
              hole_squares: Sequence[tuple[int, int]] | None = None,
              last_hit_pop: int = -1, flipped: bool = False) -> bool:
    """
    Judge one input against a running skill check -- the single verdict the
    server uses for all four kinds, carrying the shared floors with it: an
    input quicker than a human could react, or later than the deadline, never
    wins whatever the mini-game itself would say

    :param kind: which mini-game is running, which picks the test applied
    :param challenge: the challenge for that kind, rebuilt from the seed by
        whoever is judging
    :param elapsed_ms: milliseconds into the check, already clamped by
        adjudicated_elapsed_ms on the server path
    :param miss_count: shots already missed in this check
    :param deadline_ms: this check's deadline in milliseconds
    :param progress: hits or prompts already banked, which says what a combo
        owes next
    :param direction: direction pressed, for a combo input
    :param target: (row, col) in board space for a whack shot -- the shooter
        sends this and nothing else about the geometry
    :param hole_squares: pit squares for a whack shot, re-derived by the judge
        rather than taken from the shooter
    :param last_hit_pop: mole already hit, so one mole cannot be shot twice
    :param flipped: True when the mover's board is drawn from Black's end
    :returns: True when this input counts as a hit
    """
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


def hits_required(kind: SkillCheckKind, challenge: Any) -> int:
    """
    Give how many good inputs win this check, so a caller can tell a hit that
    only banks progress from the one that lands the move. Wheel and aim are
    settled by a single shot, while whack and combo have to be worked through

    :param kind: which mini-game is running
    :param challenge: the challenge for that kind, which carries the quota it
        was built with
    :returns: number of hits needed to win the check
    """
    if kind == SkillCheckKind.WHACK:
        return challenge.hits_required
    if kind == SkillCheckKind.COMBO:
        return challenge.prompt_count
    return 1


def aim_expired(challenge: AimChallenge, elapsed_ms: float, miss_count: int = 0) -> bool:
    """
    Tell whether a Steady-Aim check has run out, which happens when the victim
    has shrunk to nothing rather than at a fixed time

    :param challenge: the aim challenge being judged
    :param elapsed_ms: milliseconds since the check started
    :param miss_count: shots already missed, which bring expiry forward
    :returns: True when the check is over and lost
    """
    return challenge.is_expired(elapsed_ms, miss_count)


def check_expired(kind: SkillCheckKind, challenge: Any, elapsed_ms: float, miss_count: int = 0,
                  progress: int = 0, last_hit_pop: int = -1) -> bool:
    """
    Tell whether a check is already lost on its own terms, before its deadline
    is even reached. This is the one fail predicate every surface shares --
    the move gate, the resume path and the sweep all ask it -- so a player can
    never dodge a lost check by going quiet or dropping the connection

    :param kind: which mini-game is running
    :param challenge: the challenge for that kind, rebuilt from the seed by
        whoever is asking
    :param elapsed_ms: milliseconds since the check started
    :param miss_count: misses spent so far, which exhaust whack and combo
    :param progress: hits banked so far, which decide whether a whack quota is
        still reachable
    :param last_hit_pop: mole already hit, left out of what remains
    :returns: True when the check is lost
    """
    if kind == SkillCheckKind.AIM:
        return aim_expired(challenge, elapsed_ms, miss_count)
    if kind == SkillCheckKind.WHACK:
        return (challenge.quota_unreachable(elapsed_ms, progress, last_hit_pop)
                or challenge.whiffs_exhausted(miss_count))
    if kind == SkillCheckKind.COMBO:
        return challenge.wrongs_exhausted(miss_count)
    return False


def min_inter_input_ms(kind: SkillCheckKind) -> float:
    """
    Give the shortest gap allowed between two inputs in one check, the
    server-side rate gate that stops a scripted client spraying inputs at the
    kinds that take more than one. Kinds settled by a single shot have no gap

    :param kind: which mini-game is running
    :returns: minimum milliseconds between accepted inputs, zero when the kind
        takes only one
    """
    return _MIN_INTER_INPUT_MS.get(kind, 0.0)
