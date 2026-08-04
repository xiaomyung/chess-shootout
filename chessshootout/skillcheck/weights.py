from chessshootout.skillcheck.types import SkillCheckKind

NONE = SkillCheckKind.NONE
WHEEL = SkillCheckKind.WHEEL
AIM = SkillCheckKind.AIM
WHACK = SkillCheckKind.WHACK
COMBO = SkillCheckKind.COMBO

CAPTURE_WHEEL_SHARE = 0.25
CAPTURE_AIM_SHARE = 0.25
CAPTURE_WHACK_SHARE = 0.25
CAPTURE_COMBO_SHARE = 0.25

CAPTURE_FIRE = {NONE: 0.0, WHEEL: CAPTURE_WHEEL_SHARE, AIM: CAPTURE_AIM_SHARE,
                WHACK: CAPTURE_WHACK_SHARE, COMBO: CAPTURE_COMBO_SHARE}
PROMOTION_FIRE = {NONE: 0.0, WHEEL: 1.0}

_NEVER = {NONE: 1.0, WHEEL: 0.0, AIM: 0.0, WHACK: 0.0, COMBO: 0.0}
_ORDER = (NONE, WHEEL, AIM, WHACK, COMBO)


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
