from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts

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


def distribution_for(facts: TriggerFacts) -> dict[SkillCheckKind, float]:
    """
    Pick the odds a candidate move is judged by: a capture splits evenly
    across the four mini-games, a promotion is wheel-only, and everything else
    never fires. A forced move never fires either, because locking a player's
    only legal move would freeze the game

    :param facts: what the move does, gathered once by compute_facts
    :returns: kind to probability, adding up to 1.0 across the table
    """
    if facts.is_forced:
        return _NEVER
    if facts.is_capture:
        return CAPTURE_FIRE
    if facts.is_promotion:
        return PROMOTION_FIRE
    return _NEVER


def roll_skillcheck(facts: TriggerFacts, roll: float) -> SkillCheckKind:
    """
    Turn one seeded roll into the kind of check a move fires, the single place
    the shootout's odds are applied. The kinds are walked in a fixed order, so
    a given roll always yields the same kind on the server and on both clients

    :param facts: what the move does, which selects the odds table
    :param roll: seeded float in [0, 1) drawn for this ply and move
    :returns: the kind to run, NONE when the roll lands outside every share
    """
    dist = distribution_for(facts)
    cumulative = 0.0
    for kind in _ORDER:
        cumulative += dist.get(kind, 0.0)
        if roll < cumulative:
            return kind
    return NONE
