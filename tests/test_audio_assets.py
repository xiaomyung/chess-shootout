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
