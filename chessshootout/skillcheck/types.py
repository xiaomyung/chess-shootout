from dataclasses import dataclass
from enum import Enum


class SkillCheckKind(Enum):
    """
    Which shootout mini-game a move fires, or NONE when the move simply lands.
    The string values travel on the wire and into saved PGN comments, so they
    are stable identifiers rather than display text
    """

    NONE = "none"
    WHEEL = "wheel"
    AIM = "aim"
    WHACK = "whack"
    COMBO = "combo"


KIND_LABEL = {
    "wheel": "Wheel",
    "aim": "Steady-Aim",
    "whack": "Whack-a-Mole",
    "combo": "Combo",
}


@dataclass(frozen=True)
class TriggerFacts:
    """
    The handful of facts about a candidate move that decide whether a skill
    check fires and which kind it is. They are computed once per move attempt
    and fed to the weights table; is_forced suppresses every check, because
    locking a player's only legal move would freeze the game
    """

    is_capture: bool = False
    capturer_value: int = 0
    captured_value: int = 0
    is_promotion: bool = False
    is_forced: bool = False


@dataclass(frozen=True)
class SkillCheckOutcome:
    """
    One resolved skill check: the ply it fired on, the kind that ran and
    whether the player won it. Both the game and review screens keep a log of
    these, and the PGN writer turns them into move comments
    """

    ply: int
    kind: str
    won: bool
    san: str = ""


def whiffs_by_ply(outcomes: list[SkillCheckOutcome]) -> dict[int, list[tuple[str, str]]]:
    """
    Group the lost skill checks by ply so the move list can mark the moves a
    player fluffed. Wins are dropped, and a ply with no miss is simply absent
    from the result instead of mapping to an empty list

    :param outcomes: resolved checks in play order, wins and misses alike
    :returns: ply number to its misses as (display label, SAN) pairs
    """
    whiffs: dict[int, list[tuple[str, str]]] = {}
    for outcome in outcomes:
        if not outcome.won:
            whiffs.setdefault(outcome.ply, []).append(
                (KIND_LABEL.get(outcome.kind, outcome.kind), outcome.san))
    return whiffs
