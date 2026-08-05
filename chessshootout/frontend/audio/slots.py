from dataclasses import dataclass


SHORT = "short"
SUSTAINED = "sustained"
LOOP = "loop"


@dataclass(frozen=True)
class Slot:
    src: str
    dst: str
    profile: str = SHORT
    stereo: bool = False


PIECES = ("pawn", "knight", "bishop", "rook", "queen", "king")

PIECE_GUN = {
    "pawn": "revolver",
    "knight": "hand_cannon",
    "bishop": "lever_action",
    "rook": "shotgun",
    "queen": "blunderbuss",
    "king": "ray_gun",
}

GUN_SRC = {
    "revolver": "gun_revolver_pawn",
    "hand_cannon": "gun_handcannon_knight",
    "lever_action": "gun_sniper_bishop",
    "shotgun": "gun_shotgun_rook",
    "blunderbuss": "gun_blunderbuss_queen",
    "ray_gun": "gun_ray_gun_king",
}

STREAKS = ("first_blood", "double_kill", "triple_kill", "quadra_kill",
           "rampage", "unstoppable", "godlike")


def _build_slots():
    slots = {}
    for piece in PIECES:
        slots[f"move_{piece}"] = Slot(f"move_{piece}", f"moves/{piece}")
    for gun, src in GUN_SRC.items():
        slots[f"gun_{gun}"] = Slot(src, f"guns/{gun}")
    slots["reload_check"] = Slot("reload_check", "guns/reloads")
    for streak in STREAKS:
        slots[f"announcer_{streak}"] = Slot(
            f"announcer_{streak}", f"announcer/{streak}", SUSTAINED, True)
    slots["announcer_hits"] = Slot("announcer_hits", "announcer/hits")
    slots["announcer_hits_queen"] = Slot("announcer_hits_queen", "announcer/hits_queen")
    slots["sc_appear"] = Slot("sc_appear", "skillcheck/appear")
    slots["sc_win"] = Slot("sc_win", "skillcheck/win")
    slots["sc_miss"] = Slot("sc_miss", "skillcheck/miss")
    slots["wheel_tick"] = Slot("wheel_tick", "skillcheck/wheel_tick")
    slots["aim_lock"] = Slot("aim_lock", "skillcheck/aim_lock")
    slots["aim_beep"] = Slot("aim_beep", "skillcheck/aim_beep")
    slots["swear"] = Slot("swear", "skillcheck/swear")
    slots["mole_fall"] = Slot("mole_fall", "skillcheck/mole_fall")
    slots["mole_telegraph"] = Slot("mole_telegraph", "skillcheck/mole_telegraph")
    slots["mole_pop"] = Slot("mole_pop", "skillcheck/mole_pop")
    slots["whack_hit"] = Slot("whack_hit", "skillcheck/whack_hit")
    slots["whack_kill"] = Slot("whack_kill", "skillcheck/whack_kill")
    slots["whack_dry"] = Slot("whack_dry", "skillcheck/whack_dry")
    slots["mole_taunt"] = Slot("mole_taunt", "skillcheck/mole_taunt")
    slots["whiff_ricochet"] = Slot("whiff_ricochet", "skillcheck/whiff_ricochet")
    slots["combo_hit"] = Slot("combo_hit", "skillcheck/combo_hit")
    slots["combo_wrong"] = Slot("combo_wrong", "skillcheck/combo_wrong")
    slots["combo_complete"] = Slot("combo_complete", "skillcheck/combo_complete")
    slots["combo_fail"] = Slot("combo_fail", "skillcheck/combo_fail")
    slots["combo_streak"] = Slot("combo_streak", "skillcheck/combo_streak")
    slots["ui_click"] = Slot("ui_click_typewriter", "ui/clicks")
    slots["toast"] = Slot("toast_pop", "ui/toast")
    slots["pickup"] = Slot("pickup", "ui/pickup")
    slots["drop"] = Slot("drop", "ui/drop")
    slots["board_flip"] = Slot("board_flip", "ui/board_flip")
    slots["ui_tick"] = Slot("ui_tick", "ui/tick")
    slots["drum_tick"] = Slot("drum_tick", "ui/drum_tick")
    slots["turret_ratchet"] = Slot("turret_ratchet", "ui/turret_ratchet")
    slots["card_toggle"] = Slot("card_toggle", "ui/card_toggle")
    slots["rail_click"] = Slot("rail_click", "ui/rail_click")
    slots["focus_action"] = Slot("focus_action", "ui/focus_action")
    slots["focus_action_off"] = Slot("focus_action_off", "ui/focus_action_off")
    slots["section_toggle"] = Slot("section_toggle", "ui/section_toggle")
    slots["chip_toggle"] = Slot("chip_toggle", "ui/chip_toggle")
    slots["cap_press"] = Slot("cap_press", "ui/cap_press")
    slots["vol_notch"] = Slot("vol_notch", "ui/vol_notch")
    slots["chat_receive"] = Slot("chat_receive", "ui/chat_receive")
    slots["game_start"] = Slot("game_start", "lifecycle/game_start", SUSTAINED, True)
    slots["online_game_start"] = Slot(
        "online_game_start", "lifecycle/online_game_start", SUSTAINED, True)
    slots["castle"] = Slot("castle", "lifecycle/castle")
    slots["undo"] = Slot("undo", "lifecycle/undo")
    slots["checkmate"] = Slot("checkmate", "lifecycle/checkmate")
    slots["draw"] = Slot("draw", "lifecycle/draw", SUSTAINED, True)
    slots["resign"] = Slot("resign", "lifecycle/resign", SUSTAINED, True)
    slots["you_lose"] = Slot("you_lose", "lifecycle/you_lose", SUSTAINED, True)
    slots["you_win"] = Slot("you_win", "lifecycle/you_win", SUSTAINED, True)
    slots["heartbeat_slow"] = Slot("heartbeat_slow", "clock/heartbeat_slow", LOOP)
    slots["heartbeat_fast"] = Slot("heartbeat_fast", "clock/heartbeat_fast", LOOP)
    slots["give_time"] = Slot("give_time", "clock/give_time")
    slots["give_ratchet"] = Slot("give_ratchet", "clock/give_ratchet")
    return slots


SLOTS = _build_slots()


def move_slot(piece_value):
    return f"move_{piece_value}"


def gun_slot(piece_value):
    return f"gun_{PIECE_GUN[piece_value]}"


def hit_slot(victim_value):
    return "announcer_hits_queen" if victim_value == "queen" else "announcer_hits"
