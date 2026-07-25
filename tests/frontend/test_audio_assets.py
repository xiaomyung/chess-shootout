"""New v2.4.3 audio slots: registration guard (always on) + an opt-in
shipping-presence check.

Empty slot pools are a legitimate silent no-op, so a green suite does NOT prove
the ui_tick / give_ratchet sounds actually ship. The presence check is opt-in
(set CHESS_CHECK_ASSETS=1) and is meant to run on the release branch after the
audition picks are processed into assets/sounds/.
"""
import os

import pytest

from chessshootout import paths
from chessshootout.frontend.audio.slots import SLOTS


NEW_SLOTS = {"ui_tick": "ui/tick", "give_ratchet": "clock/give_ratchet"}

MENU_REDESIGN_SLOTS = {
    "drum_tick": "ui/drum_tick",
    "turret_ratchet": "ui/turret_ratchet",
    "card_toggle": "ui/card_toggle",
    "rail_click": "ui/rail_click",
    "focus_action": "ui/focus_action",
}

RAIL_SECTIONS_SLOTS = {
    "section_toggle": "ui/section_toggle",
    "chip_toggle": "ui/chip_toggle",
    "cap_press": "ui/cap_press",
    "vol_notch": "ui/vol_notch",
    "chat_receive": "ui/chat_receive",
}

WHACK_COMBO_SLOTS = {
    "mole_fall": "skillcheck/mole_fall",
    "mole_telegraph": "skillcheck/mole_telegraph",
    "mole_pop": "skillcheck/mole_pop",
    "whack_hit": "skillcheck/whack_hit",
    "whack_kill": "skillcheck/whack_kill",
    "whack_dry": "skillcheck/whack_dry",
    "mole_taunt": "skillcheck/mole_taunt",
    "whiff_ricochet": "skillcheck/whiff_ricochet",
    "combo_hit": "skillcheck/combo_hit",
    "combo_wrong": "skillcheck/combo_wrong",
    "combo_complete": "skillcheck/combo_complete",
    "combo_fail": "skillcheck/combo_fail",
}


@pytest.mark.parametrize("slot_id, dst", sorted(NEW_SLOTS.items()))
def test_new_slot_registered_with_expected_dst(slot_id, dst):
    assert slot_id in SLOTS
    assert SLOTS[slot_id].dst == dst


@pytest.mark.skipif(
    not os.environ.get("CHESS_CHECK_ASSETS"),
    reason="opt-in shipping-asset presence check; set CHESS_CHECK_ASSETS=1",
)
@pytest.mark.parametrize("dst", sorted(NEW_SLOTS.values()))
def test_new_slot_pool_ships_oggs(dst):
    pool = paths.SOUNDS_DIR / dst
    oggs = sorted(pool.glob("*.ogg"))
    assert oggs, (
        f"{dst} pool is empty — process the audition picks "
        f"(packaging/process_sounds.py) before shipping"
    )


@pytest.mark.parametrize("slot_id, dst", sorted(MENU_REDESIGN_SLOTS.items()))
def test_menu_redesign_slot_registered_with_expected_dst(slot_id, dst):
    assert slot_id in SLOTS
    assert SLOTS[slot_id].dst == dst
    assert SLOTS[slot_id].src == slot_id


@pytest.mark.skipif(
    not os.environ.get("CHESS_CHECK_ASSETS"),
    reason="opt-in shipping-asset presence check; set CHESS_CHECK_ASSETS=1",
)
@pytest.mark.parametrize("dst", sorted(MENU_REDESIGN_SLOTS.values()))
def test_menu_redesign_slot_pool_ships_oggs(dst):
    pool = paths.SOUNDS_DIR / dst
    oggs = sorted(pool.glob("*.ogg"))
    assert oggs, (
        f"{dst} pool is empty — process the audition picks "
        f"(packaging/process_sounds.py) before shipping"
    )


@pytest.mark.parametrize("slot_id, dst", sorted(RAIL_SECTIONS_SLOTS.items()))
def test_rail_sections_slot_registered_with_expected_dst(slot_id, dst):
    assert slot_id in SLOTS
    assert SLOTS[slot_id].dst == dst
    assert SLOTS[slot_id].src == slot_id


@pytest.mark.parametrize("slot_id, dst", sorted(WHACK_COMBO_SLOTS.items()))
def test_whack_combo_slot_registered_with_expected_dst(slot_id, dst):
    assert slot_id in SLOTS
    assert SLOTS[slot_id].dst == dst
    assert SLOTS[slot_id].src == slot_id
    assert dst.startswith("skillcheck/")
