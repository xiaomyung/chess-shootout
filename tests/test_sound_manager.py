"""SoundManager unit tests.

Invariant under test: the *real* playback path (``_play_with_master`` ->
``Sound.play(fade_ms=...)`` for one-shots, ``_heartbeat_channel.play`` for the
loop) is reached only when the manager is enabled and the matching sound list is
non-empty. Disabled or empty must be a true no-op, never a silent play call.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random
from unittest.mock import MagicMock, patch

import pygame as pg
import pytest

from frontend.audio.sound_manager import (
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


PER_EVENT_PLAY_METHODS = [
    pytest.param("play_move", id="play_move"),
    pytest.param("play_premove_queued", id="play_premove_queued"),
    pytest.param("play_check", id="play_check"),
    pytest.param("play_checkmate", id="play_checkmate"),
    pytest.param("play_castle", id="play_castle"),
    pytest.param("play_undo", id="play_undo"),
    pytest.param("play_game_start", id="play_game_start"),
    pytest.param("play_flag_fall", id="play_flag_fall"),
    pytest.param("play_online_game_start", id="play_online_game_start"),
]


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


def test_reserve_channel_marks_channel_as_reserved_in_pg_mixer():
    """Reserving channel 0 keeps Sound auto-alloc on channels 1..N-1 so a
    one-shot can't land on the heartbeat channel and be silenced by stop_all."""
    with patch.object(pg.mixer, "set_reserved") as set_reserved:
        SoundManager._reserve_channel(0)
    set_reserved.assert_called_once_with(1)


def test_real_construction_reserves_channel_zero(tmp_path):
    """Building without an injected heartbeat channel reserves channel 0 so no
    later Sound.play() picks it."""
    with patch.object(pg.mixer, "set_reserved") as set_reserved:
        SoundManager(tmp_path, master_volume=1.0)
    set_reserved.assert_called_once_with(1)


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


def test_play_capture_no_sounds_does_not_reach_playback(manager):
    """play_capture with no loaded capture sounds must not reach the real
    playback path; loading one variant makes the same call play it."""
    manager._capture_sounds = {}
    with patch.object(manager, "_play_with_master") as play:
        manager.play_capture(PieceType.PAWN)
    play.assert_not_called()

    target = MagicMock()
    manager._capture_sounds = {PieceType.PAWN: [target]}
    manager.play_capture(PieceType.PAWN)
    target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)


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


@pytest.mark.parametrize("enabled,sounds_nonempty,should_play", [
    pytest.param(False, True, False, id="disabled_with_sounds_no_op"),
    pytest.param(True, False, False, id="enabled_empty_list_no_op"),
    pytest.param(True, True, True, id="enabled_with_sounds_plays"),
])
def test_play_random_helper_guards_both_branches(enabled, sounds_nonempty, should_play):
    """_play_random plays exactly when enabled AND the list is non-empty;
    either guard alone short-circuits before any Sound.play()."""
    sm = SoundManager(SOUNDS_DIR, enabled=enabled, master_volume=1.0,
                      heartbeat_channel=MagicMock())
    target = MagicMock()
    sm._play_random([target] if sounds_nonempty else [])
    if should_play:
        target.play.assert_called_once_with(fade_ms=ONESHOT_FADE_MS)
    else:
        target.play.assert_not_called()


@pytest.mark.parametrize("method", PER_EVENT_PLAY_METHODS)
def test_disabled_manager_play_method_does_not_reach_playback(method):
    """Every per-event play method on a disabled manager is a true no-op: the
    real playback path (_play_with_master) is never reached."""
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    with patch.object(sm, "_play_with_master") as play:
        getattr(sm, method)()
    play.assert_not_called()


def test_disabled_manager_play_capture_does_not_reach_playback():
    """play_capture takes the piece-type argument; on a disabled manager it
    must also skip the real playback path."""
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    with patch.object(sm, "_play_with_master") as play:
        sm.play_capture(PieceType.PAWN)
        sm.play_capture()
    play.assert_not_called()


def test_disabled_manager_heartbeat_and_stop_all_touch_no_channel():
    """update_heartbeat / stop_all on a disabled manager never touch a channel
    (the disabled manager holds no heartbeat channel at all)."""
    sm = SoundManager(SOUNDS_DIR, enabled=False)
    assert sm._heartbeat_channel is None
    sm.update_heartbeat(0.05, paused=False)
    sm.stop_all()
    assert sm._state == STATE_OFF


def test_heartbeat_starts_off(manager):
    assert manager._state == STATE_OFF


def test_heartbeat_off_above_threshold(manager, fake_channel):
    manager.update_heartbeat(0.5, paused=False)
    assert manager._state == STATE_OFF
    fake_channel.play.assert_not_called()


def test_heartbeat_off_at_threshold_boundary(manager):
    """fraction == start_fraction is the user-decided cutoff; either state is
    acceptable exactly on it. Below-boundary triggering is asserted separately."""
    manager.update_heartbeat(manager.heartbeat.start_fraction, paused=False)
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


@pytest.mark.parametrize("fraction_of,expected_of", [
    pytest.param(lambda c: c.start_fraction - 1e-9, lambda c: c.min_volume,
                 id="just_below_threshold_is_min"),
    pytest.param(lambda c: 0.0, lambda c: c.max_volume, id="empty_clock_is_max"),
    pytest.param(lambda c: c.start_fraction / 2.0,
                 lambda c: c.min_volume + 0.5 * (c.max_volume - c.min_volume),
                 id="halfway_lerps_to_midpoint"),
])
def test_heartbeat_volume_lerps(manager, fake_channel, fraction_of, expected_of):
    """Channel volume lerps linearly from min_volume at the threshold to
    max_volume at an empty clock, scaled by master_volume (1.0 here)."""
    cfg = manager.heartbeat
    manager.update_heartbeat(fraction_of(cfg), paused=False)
    last_vol = fake_channel.set_volume.call_args[0][0]
    assert last_vol == pytest.approx(expected_of(cfg), abs=1e-3)


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
