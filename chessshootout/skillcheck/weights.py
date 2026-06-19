from chessshootout.skillcheck.types import SkillCheckKind

NONE = SkillCheckKind.NONE
WHEEL = SkillCheckKind.WHEEL

CAPTURE_WHEEL_SHARE = 1.0

CAPTURE_FIRE = {NONE: 0.0, WHEEL: CAPTURE_WHEEL_SHARE}
PROMOTION_FIRE = {NONE: 0.0, WHEEL: 1.0}

_NEVER = {NONE: 1.0, WHEEL: 0.0}
_ORDER = (NONE, WHEEL)


def distribution_for(facts):
    if facts.is_forced:
        return _NEVER
    if facts.is_capture:
        return CAPTURE_FIRE
    if facts.is_promotion:
        return PROMOTION_FIRE
    return _NEVER


def roll_skillcheck(facts, roll):
    dist = distribution_for(facts)
    cumulative = 0.0
    for kind in _ORDER:
        cumulative += dist.get(kind, 0.0)
        if roll < cumulative:
            return kind
    return NONE
