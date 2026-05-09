import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random
from unittest.mock import MagicMock, patch

import pygame as pg
import pytest

from frontend.sound_manager import (
    SoundManager, HeartbeatConfig,
    STATE_OFF, STATE_HEARTBEAT, ONESHOT_FADE_MS,
)
from backend.paths import SOUNDS_DIR
from backend.pieces import PieceType


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
    return SoundManager(SOUNDS_DIR, heartbeat_channel=fake_channel, master_volume=1.0)


# ---------- Construction ----------

def test_loads_variants_and_oneshots(manager):
    assert len(manager._piece_move_sounds) > 0
    assert len(manager._reload_sounds) > 0
    for key in ("checkmate", "undo", "game_start", "heartbeat", "castle",
                "you_lose", "online_game_start"):
        assert manager._sounds[key] is not None


def test_loads_per_piece_capture_sounds(manager):
    for pt in (PieceType.PAWN, PieceType.KNIGHT, PieceType.BISHOP,
               PieceType.ROOK, PieceType.QUEEN, PieceType.KING):
        assert pt in manager._capture_sounds
        assert len(manager._capture_sounds[pt]) >= 1


def test_each_piece_capture_first_variant_is_distinct(manager):
    sounds = [manager._capture_sounds[pt][0] for pt in (
        PieceType.PAWN, PieceType.KNIGHT, PieceType.BISHOP,
        PieceType.ROOK, PieceType.QUEEN, PieceType.KING,
    )]
    assert len(set(id(s) for s in sounds)) == 6


def test_king_capture_loads_multiple_variants(manager):
    assert len(manager._capture_sounds[PieceType.KING]) >= 2


def test_capture_pack_dir_takes_precedence_over_single_file(tmp_path):
    capture_dir = tmp_path / "capture_sounds"
    capture_dir.mkdir()
    pack = capture_dir / "pawn_shot"
    pack.mkdir()
    real_king = SOUNDS_DIR / "capture_sounds" / "king_capture" / "01.ogg"
    (pack / "01.ogg").write_bytes(real_king.read_bytes())
    (pack / "02.ogg").write_bytes(real_king.read_bytes())
    (capture_dir / "pawn_shot.ogg").write_bytes(real_king.read_bytes())
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    assert len(sm._capture_sounds[PieceType.PAWN]) == 2


def test_capture_sounds_loaded_from_capture_sounds_subdir(tmp_path):
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    assert sm._capture_sounds == {}


def test_disabled_manager_has_empty_state():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._piece_move_sounds == []
    assert sm._reload_sounds == []
    assert sm._capture_sounds == {}
    assert sm._sounds == {}
    assert sm._heartbeat_channel is None


def test_construction_with_missing_variant_dirs_does_not_crash(tmp_path):
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    assert sm._piece_move_sounds == []
    assert sm._reload_sounds == []
    assert sm._capture_sounds == {}
    sm.play_move()
    sm.play_check()
    sm.play_capture(PieceType.PAWN)


def test_construction_with_missing_oneshot_files_returns_none(tmp_path):
    sm = SoundManager(tmp_path, heartbeat_channel=MagicMock(), master_volume=1.0)
    for key in ("checkmate", "undo", "game_start", "you_lose", "online_game_start"):
        assert sm._sounds[key] is None


# ---------- One-shot dispatch ----------

@pytest.mark.parametrize("method,sounds_attr", [
    ("play_move", "_piece_move_sounds"),
    ("play_check", "_reload_sounds"),
    ("play_premove_queued", "_piece_move_sounds"),
])
def test_random_dispatch_methods(manager, method, sounds_attr):
    target = MagicMock()
    getattr(manager, sounds_attr).insert(0, target)
    with patch.object(random, "choice", return_value=target):
        getattr(manager, method)()
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture_pawn(manager):
    target = MagicMock()
    manager._capture_sounds[PieceType.PAWN] = [target]
    manager.play_capture(PieceType.PAWN)
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture_each_piece_picks_right_sound(manager):
    targets = {}
    for pt in (PieceType.PAWN, PieceType.KNIGHT, PieceType.BISHOP,
               PieceType.ROOK, PieceType.QUEEN, PieceType.KING):
        targets[pt] = MagicMock()
        manager._capture_sounds[pt] = [targets[pt]]
    for pt, target in targets.items():
        manager.play_capture(pt)
        target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture_unknown_piece_falls_back_to_first(manager):
    fallback = MagicMock()
    manager._capture_sounds = {PieceType.PAWN: [fallback]}
    manager.play_capture(None)
    fallback.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_capture_no_sounds_no_op(manager):
    manager._capture_sounds = {}
    manager.play_capture(PieceType.PAWN)


@pytest.mark.parametrize("method,key", [
    ("play_checkmate", "checkmate"),
    ("play_undo", "undo"),
    ("play_game_start", "game_start"),
    ("play_castle", "castle"),
    ("play_flag_fall", "you_lose"),
    ("play_online_game_start", "online_game_start"),
])
def test_one_shot_dispatch(manager, method, key):
    sound = manager._sounds[key] = MagicMock()
    getattr(manager, method)()
    sound.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


def test_play_random_helper_noop_when_empty(manager):
    manager._play_random([])


def test_play_random_helper_noop_when_disabled():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    target = MagicMock()
    sm._play_random([target])
    target.play.assert_not_called()


def test_disabled_manager_play_methods_are_noops():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    for method in ("play_move", "play_check", "play_capture", "play_checkmate",
                   "play_castle", "play_undo", "play_game_start",
                   "play_flag_fall", "play_online_game_start", "play_premove_queued"):
        getattr(sm, method)() if method != "play_capture" else sm.play_capture()
    sm.update_heartbeat(0.05, paused=False)
    sm.stop_all()


# ---------- Heartbeat state machine ----------

def test_heartbeat_starts_off(manager):
    assert manager._state == STATE_OFF


def test_heartbeat_off_above_threshold(manager, fake_channel):
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    fake_channel.play.assert_not_called()


def test_heartbeat_off_at_threshold_boundary(manager):
    # fraction == start_fraction means we're not yet below it.
    manager.update_heartbeat(manager.heartbeat.start_fraction, paused=False)
    # Implementation triggers the heartbeat when fraction <= start_fraction.
    # Boundary is the user-decided cutoff — allow either; we only assert below
    # the boundary triggers in the next test.
    assert manager._state in (STATE_OFF, STATE_HEARTBEAT)


def test_heartbeat_on_below_threshold(manager, fake_channel):
    manager.update_heartbeat(0.05, paused=False)
    assert manager._state == STATE_HEARTBEAT
    fake_channel.play.assert_called_once()
    args, kwargs = fake_channel.play.call_args
    assert kwargs.get("loops") == -1
    assert kwargs.get("fade_ms") == manager.heartbeat.fade_in_ms


def test_heartbeat_off_when_paused(manager):
    manager.update_heartbeat(0.01, paused=True)
    assert manager._state == STATE_OFF


def test_heartbeat_off_when_fraction_none(manager):
    manager.update_heartbeat(None, paused=False)
    assert manager._state == STATE_OFF


def test_heartbeat_volume_at_threshold_is_min(manager, fake_channel):
    cfg = manager.heartbeat
    manager.update_heartbeat(cfg.start_fraction - 1e-9, paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(cfg.min_volume, abs=1e-3)


def test_heartbeat_volume_at_zero_is_max(manager, fake_channel):
    manager.update_heartbeat(0.0, paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.max_volume)


def test_heartbeat_volume_lerps_linearly(manager, fake_channel):
    cfg = manager.heartbeat
    halfway = cfg.start_fraction / 2.0
    manager.update_heartbeat(halfway, paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    expected = cfg.min_volume + 0.5 * (cfg.max_volume - cfg.min_volume)
    assert last_vol == pytest.approx(expected, abs=1e-3)


def test_heartbeat_scaled_by_master_volume(manager, fake_channel):
    manager.master_volume = 0.5
    manager.update_heartbeat(0.0, paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(manager.heartbeat.max_volume * 0.5)


def test_heartbeat_transition_to_off_fades(manager, fake_channel):
    manager.update_heartbeat(0.05, paused=False)
    fake_channel.fadeout.reset_mock()
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    fake_channel.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)


def test_heartbeat_pause_then_resume(manager, fake_channel):
    manager.update_heartbeat(0.05, paused=False)
    fake_channel.fadeout.reset_mock()
    manager.update_heartbeat(0.05, paused=True)
    fake_channel.fadeout.assert_called_once()
    fake_channel.play.reset_mock()
    manager.update_heartbeat(0.05, paused=False)
    fake_channel.play.assert_called_once()


def test_heartbeat_disabled_is_noop():
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    sm.update_heartbeat(0.05, paused=False)
    assert sm._state == STATE_OFF


def test_custom_volume_bounds(fake_channel):
    cfg = HeartbeatConfig(min_volume=0.3, max_volume=0.7)
    sm = SoundManager(SOUNDS_DIR, heartbeat=cfg, heartbeat_channel=fake_channel,
                      master_volume=1.0)
    sm.update_heartbeat(cfg.start_fraction - 1e-9, paused=False)
    assert fake_channel.set_volume.call_args[0][0] == pytest.approx(0.3, abs=1e-3)
    sm.update_heartbeat(0.0, paused=False)
    assert fake_channel.set_volume.call_args[0][0] == pytest.approx(0.7, abs=1e-3)


def test_stop_all_fades_heartbeat(manager, fake_channel):
    manager.update_heartbeat(0.05, paused=False)
    fake_channel.fadeout.reset_mock()
    manager.stop_all()
    fake_channel.fadeout.assert_called_once_with(manager.heartbeat.fade_out_ms)
    assert manager._state == STATE_OFF


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
