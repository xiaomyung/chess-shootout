from dataclasses import dataclass
from enum import Enum


class SkillCheckKind(Enum):
    NONE = "none"
    WHEEL = "wheel"
    AIM = "aim"


KIND_LABEL = {"wheel": "Wheel", "aim": "Steady-Aim"}


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
