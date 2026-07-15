"""SoundManager unit tests (unified slot model).

Invariant under test: the real playback path (``_play_with_master`` ->
``Sound.play(fade_ms=...)`` for one-shots, ``_heartbeat_channel.play`` for the
loop) is reached only when the manager is enabled and the matching slot pool is
non-empty. Disabled or empty must be a true no-op, never a silent play call.

Every slot is a directory: 0 files -> silent no-op, 1 -> plays it, N -> random
pool. Tests inject mocks into ``manager._slots[...]`` so they never depend on the
processed asset tree existing (that is exercised by the integration suite).
"""

import random
from unittest.mock import MagicMock, patch

import pygame as pg
import pytest

from chessshootout.frontend.audio.sound_manager import (
    SoundManager, HeartbeatConfig,
    STATE_OFF, STATE_SLOW, STATE_FAST, ONESHOT_FADE_MS,
)
from chessshootout.frontend.audio.slots import (
    SLOTS, PIECES, PIECE_GUN, move_slot, gun_slot, hit_slot,
)
from chessshootout.paths import SOUNDS_DIR
from chessshootout.backend.pieces import PieceType


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.mixer.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def fake_channel():
    return MagicMock(name="heartbeat")


@pytest.fixture
def manager(fake_channel):
    sm = SoundManager(SOUNDS_DIR, heartbeat_channel=fake_channel, master_volume=1.0)
    sm._slots["heartbeat_slow"] = [MagicMock(name="hb_slow")]
    sm._slots["heartbeat_fast"] = [MagicMock(name="hb_fast")]
    return sm


def _inject(manager, slot):
    target = MagicMock(name=slot)
    manager._slots[slot] = [target]
    return target


def test_slots_piece_gun_matches_gunfx():
    from chessshootout.frontend.visual.gunfx import PIECE_GUN as GUNFX_PIECE_GUN
    assert PIECE_GUN == GUNFX_PIECE_GUN


def test_registry_has_slot_for_every_piece_move_and_gun():
    for piece in PIECES:
        assert move_slot(piece) in SLOTS
        assert gun_slot(piece) in SLOTS


def test_registry_dst_paths_are_unique():
    dsts = [spec.dst for spec in SLOTS.values()]
    assert len(dsts) == len(set(dsts))


def test_hit_slot_keys_queen_female_others_male():
    assert hit_slot("queen") == "announcer_hits_queen"
    for piece in ("pawn", "knight", "bishop", "rook", "king"):
        assert hit_slot(piece) == "announcer_hits"


def test_load_pool_missing_dir_is_empty(tmp_path, manager):
    assert manager._load_pool(tmp_path / "nope") == []


def test_load_pool_has_no_count_cap(tmp_path, manager):
    for i in range(9):
        (tmp_path / f"{i:02d}.ogg").write_bytes(b"")
    with patch.object(SoundManager, "_safe_load", side_effect=lambda p: MagicMock()):
        pool = manager._load_pool(tmp_path)
    assert len(pool) == 9


def test_load_pool_is_sorted(tmp_path, manager):
    for name in ("c.ogg", "a.ogg", "b.ogg"):
        (tmp_path / name).write_bytes(b"")
    seen = []
    with patch.object(SoundManager, "_safe_load",
                      side_effect=lambda p: seen.append(p.name) or MagicMock()):
        manager._load_pool(tmp_path)
    assert seen == ["a.ogg", "b.ogg", "c.ogg"]


def test_construction_does_not_eagerly_load_any_slot(tmp_path):
    """Loading is lazy per slot: construction alone (which happens on every
    make_app()/Frontend, most of which immediately swap in a mock manager)
    must do no disk work at all."""
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    assert sm._slots == {}


def test_preload_builds_every_slot_so_first_play_never_hits_disk(tmp_path):
    """The real app calls preload() at startup: first playback mid-game must
    never pay ogg-decode latency (a first-capture frame hitch)."""
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    sm.preload()
    assert set(sm._slots) == set(SLOTS)


def test_slot_pool_lazily_builds_every_registry_entry(tmp_path):
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    for name in SLOTS:
        assert sm._slot_pool(name) == []
    assert set(sm._slots) == set(SLOTS)


def test_slot_pool_only_loads_once_per_slot(tmp_path):
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    with patch.object(sm, "_load_pool", wraps=sm._load_pool) as load_pool:
        sm._slot_pool("checkmate")
        sm._slot_pool("checkmate")
    load_pool.assert_called_once()


def test_slot_pool_unknown_name_is_empty(tmp_path):
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    assert sm._slot_pool("no_such_slot") == []


def test_slot_pool_disabled_manager_never_touches_disk():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._slot_pool("checkmate") == []
    assert sm._slots == {}


def test_disabled_manager_has_empty_slots():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._slots == {}
    assert sm._heartbeat_channel is None


ONE_SHOT_DISPATCH = [
    ("play_checkmate", "checkmate"),
    ("play_castle", "castle"),
    ("play_undo", "undo"),
    ("play_game_start", "game_start"),
    ("play_online_game_start", "online_game_start"),
    ("play_give_time", "give_time"),
    ("play_check", "reload_check"),
    ("play_you_win", "you_win"),
    ("play_you_lose", "you_lose"),
    ("play_flag_fall", "you_lose"),
    ("play_draw", "draw"),
    ("play_resign", "resign"),
    ("play_toast", "toast"),
    ("play_flip", "board_flip"),
    ("play_pickup", "pickup"),
    ("play_drop", "drop"),
    ("play_swear", "swear"),
    ("play_ui_click", "ui_click"),
    ("play_skillcheck_appear", "sc_appear"),
    ("play_skillcheck_win", "sc_win"),
    ("play_skillcheck_miss", "sc_miss"),
    ("play_wheel_tick", "wheel_tick"),
    ("play_aim_lock", "aim_lock"),
    ("play_aim_beep", "aim_beep"),
    ("play_drum_tick", "drum_tick"),
    ("play_turret_ratchet", "turret_ratchet"),
    ("play_card_toggle", "card_toggle"),
    ("play_rail_click", "rail_click"),
    ("play_focus_action", "focus_action"),
]


@pytest.mark.parametrize("method,slot", ONE_SHOT_DISPATCH,
                         ids=[m for m, _ in ONE_SHOT_DISPATCH])
def test_one_shot_dispatch_plays_its_slot(manager, method, slot):
    target = _inject(manager, slot)
    getattr(manager, method)()
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


@pytest.mark.parametrize("method,slot", ONE_SHOT_DISPATCH,
                         ids=[m for m, _ in ONE_SHOT_DISPATCH])
def test_one_shot_silent_when_slot_empty(manager, method, slot):
    manager._slots[slot] = []
    with patch.object(manager, "_play_with_master") as play:
        getattr(manager, method)()
    play.assert_not_called()


def test_play_missing_slot_is_noop(manager):
    with patch.object(manager, "_play_with_master") as play:
        manager._play("no_such_slot")
    play.assert_not_called()


def test_play_picks_a_random_variant(manager):
    a, b = MagicMock(), MagicMock()
    manager._slots["checkmate"] = [a, b]
    with patch.object(random, "choice", return_value=b):
        manager.play_checkmate()
    b.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)
    a.play.assert_not_called()


def test_play_move_each_piece_picks_its_slot(manager):
    for piece in PieceType:
        target = _inject(manager, move_slot(piece.value))
        manager.play_move(piece)
        target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_premove_queued_uses_piece_slot(manager):
    target = _inject(manager, move_slot("knight"))
    manager.play_premove_queued(PieceType.KNIGHT)
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_move_none_is_noop(manager):
    with patch.object(manager, "_play_with_master") as play:
        manager.play_move(None)
    play.assert_not_called()


def test_play_capture_each_piece_picks_its_gun(manager):
    for piece in PieceType:
        target = _inject(manager, gun_slot(piece.value))
        manager.play_capture(piece)
        target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture_pawn_uses_revolver_slot(manager):
    target = _inject(manager, "gun_revolver")
    manager.play_capture(PieceType.PAWN)
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture_none_is_noop(manager):
    with patch.object(manager, "_play_with_master") as play:
        manager.play_capture(None)
    play.assert_not_called()


def test_play_capture_picks_random_variant(manager):
    a, b = MagicMock(), MagicMock()
    manager._slots["gun_revolver"] = [a, b]
    with patch.object(random, "choice", return_value=b):
        manager.play_capture(PieceType.PAWN)
    b.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)
    a.play.assert_not_called()


def test_play_announcer_dispatches_streak_key(manager):
    target = _inject(manager, "announcer_double_kill")
    manager.play_announcer("double_kill")
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_hit_queen_uses_female_pool(manager):
    female = _inject(manager, "announcer_hits_queen")
    male = _inject(manager, "announcer_hits")
    manager.play_hit(PieceType.QUEEN)
    female.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)
    male.play.assert_not_called()


@pytest.mark.parametrize("piece", [
    PieceType.PAWN, PieceType.KNIGHT, PieceType.BISHOP,
    PieceType.ROOK, PieceType.KING,
])
def test_play_hit_non_queen_uses_male_pool(manager, piece):
    male = _inject(manager, "announcer_hits")
    female = _inject(manager, "announcer_hits_queen")
    manager.play_hit(piece)
    male.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)
    female.play.assert_not_called()


def test_play_hit_no_victim_uses_male_pool(manager):
    male = _inject(manager, "announcer_hits")
    manager.play_hit()
    male.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_menu_gun_uses_master_times_menu_volume(manager):
    manager.master_volume = 0.5
    manager.set_menu_volume(0.2)
    target = _inject(manager, "gun_blunderbuss")
    manager.play_menu_gun("blunderbuss")
    target.set_volume.assert_called_once_with(pytest.approx(0.1))
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_menu_gun_unknown_gun_is_silent(manager):
    with patch.object(manager, "_play_at") as play:
        manager.play_menu_gun("no_such_gun")
    play.assert_not_called()


def test_play_menu_gun_disabled_is_noop():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    with patch.object(sm, "_play_at") as play:
        sm.play_menu_gun("revolver")
    play.assert_not_called()


def test_menu_volume_defaults_from_env(manager):
    assert 0.0 <= manager.menu_volume <= 1.0


@pytest.mark.parametrize("enabled,sounds_nonempty,should_play", [
    pytest.param(False, True, False, id="disabled_with_sounds_no_op"),
    pytest.param(True, False, False, id="enabled_empty_list_no_op"),
    pytest.param(True, True, True, id="enabled_with_sounds_plays"),
])
def test_play_random_helper_guards_both_branches(enabled, sounds_nonempty, should_play):
    sm = SoundManager(SOUNDS_DIR, enabled=enabled, master_volume=1.0,
                      heartbeat_channel=MagicMock())
    target = MagicMock()
    sm._play_random([target] if sounds_nonempty else [])
    if should_play:
        target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)
    else:
        target.play.assert_not_called()


DISABLED_NOOP_METHODS = [
    "play_check", "play_checkmate", "play_castle", "play_undo",
    "play_game_start", "play_flag_fall", "play_online_game_start",
    "play_give_time", "play_resign", "play_hit",
    "play_you_win", "play_you_lose", "play_draw", "play_toast", "play_flip",
    "play_pickup", "play_drop", "play_swear", "play_ui_click",
    "play_skillcheck_appear", "play_skillcheck_win", "play_skillcheck_miss",
    "play_wheel_tick", "play_aim_lock", "play_aim_beep",
    "play_drum_tick", "play_turret_ratchet", "play_card_toggle",
    "play_rail_click", "play_focus_action",
]


@pytest.mark.parametrize("method", DISABLED_NOOP_METHODS)
def test_disabled_manager_play_method_does_not_reach_playback(method):
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    with patch.object(sm, "_play_with_master") as play:
        getattr(sm, method)()
    play.assert_not_called()


def test_disabled_manager_keyed_methods_do_not_reach_playback():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    with patch.object(sm, "_play_with_master") as play:
        sm.play_move(PieceType.QUEEN)
        sm.play_capture(PieceType.PAWN)
        sm.play_announcer("double_kill")
        sm.play_hit(PieceType.QUEEN)
    play.assert_not_called()


def test_disabled_manager_heartbeat_and_stop_all_touch_no_channel():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._heartbeat_channel is None
    sm.update_heartbeat(0.05, paused=False)
    sm.stop_all()
    assert sm._state == STATE_OFF


def test_reserve_channel_marks_channel_as_reserved_in_pg_mixer():
    with patch.object(pg.mixer, "set_reserved") as set_reserved:
        SoundManager._reserve_channel(0)
    set_reserved.assert_called_once_with(1)


def test_real_construction_reserves_channel_zero(tmp_path):
    with patch.object(pg.mixer, "set_reserved") as set_reserved:
        SoundManager(tmp_path, master_volume=1.0)
    set_reserved.assert_called_once_with(1)


def _slow_fraction(cfg):
    return (cfg.fast_fraction + cfg.start_fraction) / 2.0


def _fast_fraction(cfg):
    return cfg.fast_fraction / 2.0


def test_heartbeat_starts_off(manager):
    assert manager._state == STATE_OFF


def test_heartbeat_off_above_threshold(manager, fake_channel):
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    fake_channel.play.assert_not_called()


def test_heartbeat_slow_between_fast_and_start(manager, fake_channel):
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=False)
    assert manager._state == STATE_SLOW
    played = fake_channel.play.call_args[0][0]
    assert played is manager._slots["heartbeat_slow"][0]


def test_heartbeat_fast_at_or_below_fast_fraction(manager, fake_channel):
    manager.update_heartbeat(_fast_fraction(manager.heartbeat), paused=False)
    assert manager._state == STATE_FAST
    played = fake_channel.play.call_args[0][0]
    assert played is manager._slots["heartbeat_fast"][0]


def test_heartbeat_loop_kwargs(manager, fake_channel):
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=False)
    _, kwargs = fake_channel.play.call_args
    assert kwargs.get("loops") == -1
    assert kwargs.get("fade_ms") == manager.heartbeat.fade_in_ms


def test_heartbeat_off_when_paused(manager):
    manager.update_heartbeat(0.01, paused=True)
    assert manager._state == STATE_OFF


def test_heartbeat_off_when_fraction_none(manager):
    manager.update_heartbeat(None, paused=False)
    assert manager._state == STATE_OFF


def test_heartbeat_slow_to_fast_swaps_loop_on_one_channel(manager, fake_channel):
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=False)
    fake_channel.play.reset_mock()
    fake_channel.fadeout.reset_mock()
    manager.update_heartbeat(_fast_fraction(manager.heartbeat), paused=False)
    assert manager._state == STATE_FAST
    played = fake_channel.play.call_args[0][0]
    assert played is manager._slots["heartbeat_fast"][0]
    fake_channel.fadeout.assert_not_called()


def test_heartbeat_fast_to_slow_swaps_back(manager, fake_channel):
    manager.update_heartbeat(_fast_fraction(manager.heartbeat), paused=False)
    fake_channel.play.reset_mock()
    fake_channel.fadeout.reset_mock()
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=False)
    assert manager._state == STATE_SLOW
    played = fake_channel.play.call_args[0][0]
    assert played is manager._slots["heartbeat_slow"][0]
    fake_channel.fadeout.assert_not_called()


def test_heartbeat_transition_to_off_fades(manager, fake_channel):
    manager.update_heartbeat(_fast_fraction(manager.heartbeat), paused=False)
    fake_channel.fadeout.reset_mock()
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    fake_channel.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)


def test_heartbeat_pause_then_resume(manager, fake_channel):
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=False)
    fake_channel.fadeout.reset_mock()
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=True)
    fake_channel.fadeout.assert_called_once()
    fake_channel.play.reset_mock()
    manager.update_heartbeat(_slow_fraction(manager.heartbeat), paused=False)
    fake_channel.play.assert_called_once()


@pytest.mark.parametrize("fraction_of,expected_of", [
    pytest.param(lambda c: c.start_fraction - 1e-9, lambda c: c.min_volume,
                 id="just_below_threshold_is_min"),
    pytest.param(lambda c: 0.0, lambda c: c.max_volume, id="empty_clock_is_max"),
    pytest.param(lambda c: c.start_fraction / 2.0,
                 lambda c: c.min_volume + 0.5 * (c.max_volume - c.min_volume),
                 id="halfway_lerps_to_midpoint"),
])
def test_heartbeat_volume_lerps(manager, fake_channel, fraction_of, expected_of):
    cfg = manager.heartbeat
    manager.update_heartbeat(fraction_of(cfg), paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(expected_of(cfg), abs=1e-3)


def test_heartbeat_scaled_by_master_volume(manager, fake_channel):
    manager.master_volume = 0.5
    manager.update_heartbeat(0.0, paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.max_volume * 0.5)


def test_custom_volume_bounds(fake_channel):
    cfg = HeartbeatConfig(min_volume=0.3, max_volume=0.7)
    sm = SoundManager(SOUNDS_DIR, heartbeat=cfg, heartbeat_channel=fake_channel,
                      master_volume=1.0)
    sm._slots["heartbeat_slow"] = [MagicMock()]
    sm._slots["heartbeat_fast"] = [MagicMock()]
    sm.update_heartbeat(cfg.start_fraction - 1e-9, paused=False)
    assert fake_channel.set_volume.call_args[0][0] == pytest.approx(0.3, abs=1e-3)
    sm.update_heartbeat(0.0, paused=False)
    assert fake_channel.set_volume.call_args[0][0] == pytest.approx(0.7, abs=1e-3)


def test_stop_all_fades_heartbeat(manager, fake_channel):
    manager.update_heartbeat(_fast_fraction(manager.heartbeat), paused=False)
    fake_channel.fadeout.reset_mock()
    manager.stop_all()
    fake_channel.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)
    assert manager._state == STATE_OFF


def test_heartbeat_disabled_is_noop():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    sm.update_heartbeat(0.05, paused=False)
    assert sm._state == STATE_OFF


def test_set_enabled_false_calls_stop_all_via_real_channel():
    sm = SoundManager(SOUNDS_DIR, heartbeat_channel=MagicMock(), master_volume=1.0)
    stopped = []
    sm.stop_all = lambda: stopped.append(True)
    sm.set_enabled(False)
    assert stopped == [True]
    assert sm.enabled is False


def test_set_enabled_true_does_not_stop():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    stopped = []
    sm.stop_all = lambda: stopped.append(True)
    sm.set_enabled(True)
    assert stopped == []
    assert sm.enabled is True


def test_unmuting_a_manager_built_without_a_mixer_can_still_load_slots():
    """Frontend builds the manager with enabled=pg.mixer.get_init() is not None, so
    a box with no audio device gets enabled=False. The user can still hit the mute
    toggle (audio panel / options), which flips enabled back on — lazy slot loading
    then dereferences _sounds_dir, so it must never have been None."""
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._sounds_dir is not None

    sm.set_enabled(True)
    sm.preload()

    assert sm._slot_pool("checkmate") is not None
    sm.play_checkmate()
