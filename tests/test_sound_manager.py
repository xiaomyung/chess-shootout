import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random
from unittest.mock import MagicMock, patch

import pygame as pg
import pytest

from frontend.sound_manager import (
    SoundManager, HeartbeatConfig,
    STATE_OFF, STATE_MILD, STATE_DEEP, ONESHOT_FADE_MS,
)
from paths import SOUNDS_DIR


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.mixer.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def fake_channels():
    return MagicMock(name="mild"), MagicMock(name="deep")


@pytest.fixture
def manager(fake_channels):
    mild, deep = fake_channels
    return SoundManager(SOUNDS_DIR, mild_channel=mild, deep_channel=deep)


# ---------- Construction ----------

def test_loads_variants_and_oneshots(manager):
    assert len(manager._piece_move_sounds) > 0
    assert len(manager._reload_sounds) > 0
    for key in ("capture", "checkmate", "undo", "game_start",
                "heartbeat_mild", "heartbeat_deep"):
        assert manager._sounds[key] is not None


def test_disabled_manager_has_empty_state():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._piece_move_sounds == []
    assert sm._reload_sounds == []
    assert sm._sounds == {}
    assert sm._mild_channel is None
    assert sm._deep_channel is None


def test_construction_with_missing_variant_dirs_does_not_crash(tmp_path):
    sm = SoundManager(tmp_path)
    assert sm._piece_move_sounds == []
    assert sm._reload_sounds == []
    sm.play_move()  # must not raise
    sm.play_check()


def test_construction_with_missing_oneshot_files_returns_none(tmp_path):
    sm = SoundManager(tmp_path)
    for key in ("capture", "checkmate", "undo", "game_start"):
        assert sm._sounds[key] is None


# ---------- One-shot dispatch ----------

def test_play_move_calls_play_with_fade_ms(manager):
    target = manager._piece_move_sounds[0] = MagicMock()
    with patch.object(random, "choice", return_value=target):
        manager.play_move()
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_check_picks_from_reloads(manager):
    target = manager._reload_sounds[0] = MagicMock()
    with patch.object(random, "choice", return_value=target):
        manager.play_check()
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture(manager):
    sound = manager._sounds["capture"] = MagicMock()
    manager.play_capture()
    sound.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_checkmate(manager):
    sound = manager._sounds["checkmate"] = MagicMock()
    manager.play_checkmate()
    sound.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_undo(manager):
    sound = manager._sounds["undo"] = MagicMock()
    manager.play_undo()
    sound.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_game_start(manager):
    sound = manager._sounds["game_start"] = MagicMock()
    manager.play_game_start()
    sound.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_disabled_manager_play_methods_are_noops():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    # None of these should raise.
    sm.play_move()
    sm.play_check()
    sm.play_capture()
    sm.play_checkmate()
    sm.play_undo()
    sm.play_game_start()
    sm.update_heartbeat(0.05, paused=False)
    sm.stop_all()


# ---------- Heartbeat state machine ----------

def test_heartbeat_starts_off(manager):
    assert manager._state == STATE_OFF


def test_heartbeat_off_when_above_mild_threshold(manager):
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    manager._mild_channel.play.assert_not_called()


def test_heartbeat_off_when_paused(manager):
    manager.update_heartbeat(0.05, paused=True)
    assert manager._state == STATE_OFF


def test_heartbeat_off_when_fraction_none(manager):
    manager.update_heartbeat(None, paused=False)
    assert manager._state == STATE_OFF


def test_heartbeat_transitions_off_to_mild(manager, fake_channels):
    mild, _ = fake_channels
    manager.update_heartbeat(0.18, paused=False)
    assert manager._state == STATE_MILD
    mild.play.assert_called_once()
    args, kwargs = mild.play.call_args
    assert kwargs.get("loops") == -1
    assert kwargs.get("fade_ms") == manager.heartbeat.fade_in_ms
    mild.set_volume.assert_called()


def test_heartbeat_mild_volume_at_start_is_min(manager, fake_channels):
    mild, _ = fake_channels
    manager.update_heartbeat(0.20, paused=False)
    last_vol = mild.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.min_volume)


def test_heartbeat_mild_volume_at_midpoint(manager, fake_channels):
    mild, _ = fake_channels
    manager.update_heartbeat(0.15, paused=False)
    last_vol = mild.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(0.75)


def test_heartbeat_mild_to_deep_simultaneous_crossfade(manager, fake_channels):
    mild, deep = fake_channels
    manager.update_heartbeat(0.18, paused=False)  # OFF -> MILD
    mild.play.reset_mock()
    deep.play.reset_mock()
    manager.update_heartbeat(0.099, paused=False)  # MILD -> DEEP
    assert manager._state == STATE_DEEP
    mild.fadeout.assert_called_once_with(manager.heartbeat.crossfade_ms)
    deep.play.assert_called_once()
    args, kwargs = deep.play.call_args
    assert kwargs.get("loops") == -1
    assert kwargs.get("fade_ms") == manager.heartbeat.crossfade_ms


def test_heartbeat_deep_volume_at_zero_is_max(manager, fake_channels):
    _, deep = fake_channels
    manager.update_heartbeat(0.099, paused=False)  # transition into DEEP first
    manager.update_heartbeat(0.0, paused=False)
    last_vol = deep.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.max_volume)


def test_heartbeat_deep_volume_at_boundary_is_min(manager, fake_channels):
    _, deep = fake_channels
    manager.update_heartbeat(0.099, paused=False)  # transition first
    deep.set_volume.reset_mock()
    manager.update_heartbeat(0.10, paused=False)
    assert manager._state == STATE_DEEP
    last_vol = deep.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.min_volume)


def test_heartbeat_deep_to_off_on_pause(manager, fake_channels):
    _, deep = fake_channels
    manager.update_heartbeat(0.05, paused=False)
    manager.update_heartbeat(0.05, paused=True)
    assert manager._state == STATE_OFF
    deep.fadeout.assert_called_with(manager.heartbeat.fade_out_ms)


def test_heartbeat_mild_to_off_on_recovery(manager, fake_channels):
    mild, _ = fake_channels
    manager.update_heartbeat(0.18, paused=False)
    mild.fadeout.reset_mock()
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    mild.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)


def test_heartbeat_deep_to_mild_reverse_crossfade(manager, fake_channels):
    mild, deep = fake_channels
    manager.update_heartbeat(0.05, paused=False)  # OFF -> DEEP (skip MILD via direct entry)
    mild.play.reset_mock()
    deep.fadeout.reset_mock()
    manager.update_heartbeat(0.18, paused=False)  # DEEP -> MILD
    assert manager._state == STATE_MILD
    deep.fadeout.assert_called_once_with(manager.heartbeat.crossfade_ms)
    mild.play.assert_called_once()


def test_heartbeat_volume_clamps_at_max(manager, fake_channels):
    mild, _ = fake_channels
    manager.update_heartbeat(0.05, paused=False)  # below mild range
    # The volume, if mild, would be clamped — but state is DEEP here.
    # Re-test mild clamp:
    mild.set_volume.reset_mock()
    manager._state = STATE_OFF  # reset
    manager.update_heartbeat(0.10001, paused=False)
    last_vol = mild.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.max_volume, abs=0.01)


# ---------- HeartbeatConfig overrides ----------

def test_custom_thresholds(fake_channels):
    mild, deep = fake_channels
    cfg = HeartbeatConfig(mild_start_fraction=0.5, deep_start_fraction=0.25)
    sm = SoundManager(SOUNDS_DIR, heartbeat=cfg, mild_channel=mild, deep_channel=deep)
    sm.update_heartbeat(0.4, paused=False)
    assert sm._state == STATE_MILD
    sm.update_heartbeat(0.2, paused=False)
    assert sm._state == STATE_DEEP


def test_custom_volume_bounds(fake_channels):
    mild, deep = fake_channels
    cfg = HeartbeatConfig(min_volume=0.3, max_volume=0.7)
    sm = SoundManager(SOUNDS_DIR, heartbeat=cfg, mild_channel=mild, deep_channel=deep)
    sm.update_heartbeat(0.20, paused=False)  # MILD start
    assert mild.set_volume.call_args[0][0] == pytest.approx(0.3)
    sm.update_heartbeat(0.10001, paused=False)  # MILD end
    assert mild.set_volume.call_args[0][0] == pytest.approx(0.7, abs=0.01)


def test_custom_crossfade_ms(fake_channels):
    mild, deep = fake_channels
    cfg = HeartbeatConfig(crossfade_ms=500)
    sm = SoundManager(SOUNDS_DIR, heartbeat=cfg, mild_channel=mild, deep_channel=deep)
    sm.update_heartbeat(0.18, paused=False)
    sm.update_heartbeat(0.099, paused=False)
    mild.fadeout.assert_called_with(500)
    deep.play.assert_called_with(sm._sounds["heartbeat_deep"], loops=-1, fade_ms=500)


def test_custom_fade_in_ms(fake_channels):
    mild, deep = fake_channels
    cfg = HeartbeatConfig(fade_in_ms=1000)
    sm = SoundManager(SOUNDS_DIR, heartbeat=cfg, mild_channel=mild, deep_channel=deep)
    sm.update_heartbeat(0.18, paused=False)
    args, kwargs = mild.play.call_args
    assert kwargs["fade_ms"] == 1000


# ---------- stop_all ----------

def test_stop_all_fades_both_channels(manager, fake_channels):
    mild, deep = fake_channels
    manager.update_heartbeat(0.18, paused=False)  # MILD active
    mild.fadeout.reset_mock()
    deep.fadeout.reset_mock()
    manager.stop_all()
    assert manager._state == STATE_OFF
    mild.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)
    deep.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)


def test_stop_all_does_not_stop_oneshots(manager):
    capture_sound = manager._sounds["capture"] = MagicMock()
    manager.play_capture()
    manager.stop_all()
    capture_sound.stop.assert_not_called()


def test_stop_all_disabled_is_noop():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    sm.stop_all()  # must not raise
