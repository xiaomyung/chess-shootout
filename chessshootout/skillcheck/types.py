from dataclasses import dataclass
from enum import Enum


class SkillCheckKind(Enum):
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
    is_capture: bool = False
    capturer_value: int = 0
    captured_value: int = 0
    is_promotion: bool = False
    is_forced: bool = False


@dataclass(frozen=True)
class SkillCheckOutcome:
    ply: int
    kind: str
    won: bool
    san: str = ""


def whiffs_by_ply(outcomes):
    whiffs = {}
    for outcome in outcomes:
        if not outcome.won:
            whiffs.setdefault(outcome.ply, []).append(
                (KIND_LABEL.get(outcome.kind, outcome.kind), outcome.san))
    return whiffs
