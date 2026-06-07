from chessshootout.skillcheck.types import SkillCheckKind

NONE = SkillCheckKind.NONE
WHEEL = SkillCheckKind.WHEEL
DUEL = SkillCheckKind.DUEL

CAPTURE_GREATER = {NONE: 0.0, WHEEL: 0.30, DUEL: 0.70}
CAPTURE_EQUAL = {NONE: 0.50, WHEEL: 0.25, DUEL: 0.25}
CAPTURE_LESSER = {NONE: 0.80, WHEEL: 0.15, DUEL: 0.05}

CHECK_FIRE_BY_VALUE = {1: 0.15, 3: 0.25, 5: 0.35, 9: 0.50}
CHECK_WHEEL_SHARE = 0.30
CHECK_DUEL_SHARE = 0.70

CHECKMATE_DUEL_CHANCE = 0.10

PROMO_FIRE_BY_VALUE = {3: 0.20, 5: 0.40, 9: 0.60}

_NEVER = {NONE: 1.0, WHEEL: 0.0, DUEL: 0.0}
_ORDER = (NONE, WHEEL, DUEL)


def capture_distribution(capturer_value, captured_value):
    if capturer_value > captured_value:
        return CAPTURE_GREATER
    if capturer_value == captured_value:
        return CAPTURE_EQUAL
    return CAPTURE_LESSER


def check_distribution(checker_value):
    fire = CHECK_FIRE_BY_VALUE.get(checker_value, 0.0)
    return {
        NONE: 1.0 - fire,
        WHEEL: fire * CHECK_WHEEL_SHARE,
        DUEL: fire * CHECK_DUEL_SHARE,
    }


def checkmate_distribution():
    return {NONE: 1.0 - CHECKMATE_DUEL_CHANCE, WHEEL: 0.0, DUEL: CHECKMATE_DUEL_CHANCE}


def promotion_distribution(promo_value):
    fire = PROMO_FIRE_BY_VALUE.get(promo_value, 0.0)
    return {NONE: 1.0 - fire, WHEEL: fire, DUEL: 0.0}


def distribution_for(facts):
    if facts.is_forced:
        return _NEVER
    if facts.is_capture:
        return capture_distribution(facts.capturer_value, facts.captured_value)
    if facts.is_checkmate:
        return checkmate_distribution()
    if facts.is_check:
        return check_distribution(facts.checker_value)
    if facts.is_promotion:
        return promotion_distribution(facts.promo_value)
    return _NEVER


def roll_skillcheck(facts, roll):
    dist = distribution_for(facts)
    cumulative = 0.0
    for kind in _ORDER:
        cumulative += dist.get(kind, 0.0)
        if roll < cumulative:
            return kind
    return NONE
