from dataclasses import dataclass
from enum import Enum


class SkillCheckKind(Enum):
    NONE = "none"
    WHEEL = "wheel"
    DUEL = "duel"


@dataclass(frozen=True)
class TriggerFacts:
    is_capture: bool = False
    capturer_value: int = 0
    captured_value: int = 0
    is_promotion: bool = False
    is_forced: bool = False
