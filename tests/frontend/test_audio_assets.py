"""New v2.4.3 audio slots: registration guard (always on) + an opt-in
shipping-presence check.

Empty slot pools are a legitimate silent no-op, so a green suite does NOT prove
the ui_tick / give_ratchet sounds actually ship. The presence check is opt-in
(set CHESS_CHECK_ASSETS=1) and is meant to run on the release branch after the
audition picks are processed into assets/sounds/.
"""
import array
import os

import pygame as pg
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
    "mole_heal": "skillcheck/mole_heal",
    "whack_hit": "skillcheck/whack_hit",
    "whack_kill": "skillcheck/whack_kill",
    "whack_dry": "skillcheck/whack_dry",
    "mole_taunt": "skillcheck/mole_taunt",
    "whiff_ricochet": "skillcheck/whiff_ricochet",
    "combo_hit": "skillcheck/combo_hit",
    "combo_wrong": "skillcheck/combo_wrong",
    "combo_complete": "skillcheck/combo_complete",
    "combo_fail": "skillcheck/combo_fail",
    "combo_streak": "skillcheck/combo_streak",
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


# Per-press combo cues answer a keypress: whatever silence or quiet pre-roll a
# source carries in front of its transient becomes felt input latency, so the
# audible onset — not the file start — is what the guard measures. A wrong-press
# scratch that woke up 600 ms in read as "the sound belongs to my NEXT press".
COMBO_PRESS_CUE_DIRS = ("skillcheck/combo_wrong", "skillcheck/combo_hit")
CUE_ONSET_LIMIT_MS = 80.0
CUE_ONSET_FRACTION = 0.25


@pytest.fixture(scope="module")
def mixer():
    pg.init()
    try:
        pg.mixer.init()
    except pg.error:
        pytest.skip("no mixer in this environment")
    init = pg.mixer.get_init()
    if init is None or init[1] not in (16, -16):
        pg.mixer.quit()
        pytest.skip("onset probe needs a 16-bit mixer")
    yield init
    pg.mixer.quit()


def _onset_ms(path, init):
    freq, _, channels = init
    raw = pg.mixer.Sound(str(path)).get_raw()
    samples = array.array("h")
    samples.frombytes(raw[:len(raw) - len(raw) % 2])
    peak = max((abs(s) for s in samples), default=0)
    if peak == 0:
        return 0.0
    threshold = peak * CUE_ONSET_FRACTION
    for i, s in enumerate(samples):
        if abs(s) >= threshold:
            return (i // channels) * 1000.0 / freq
    return 0.0


@pytest.mark.parametrize("dst", COMBO_PRESS_CUE_DIRS)
def test_combo_press_cue_onsets_land_immediately(dst, mixer):
    oggs = sorted((paths.SOUNDS_DIR / dst).glob("*.ogg"))
    if not oggs:
        pytest.skip(f"{dst} ships no oggs (a silent pool is a legitimate no-op)")
    late = {p.name: round(_onset_ms(p, mixer), 1) for p in oggs
            if _onset_ms(p, mixer) > CUE_ONSET_LIMIT_MS}
    assert late == {}, (
        f"{dst} cues answer a keypress; these wake up too late (ms after play): {late} — "
        f"trim the head so the transient is the first thing the player hears"
    )
