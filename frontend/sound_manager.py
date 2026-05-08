import random
from dataclasses import dataclass, field
from pathlib import Path

import pygame as pg


@dataclass
class HeartbeatConfig:
    mild_start_fraction: float = 0.20
    deep_start_fraction: float = 0.10
    min_volume: float = 0.5
    max_volume: float = 1.0
    fade_in_ms: int = 400
    crossfade_ms: int = 300
    fade_out_ms: int = 300


STATE_OFF = "off"
STATE_MILD = "mild"
STATE_DEEP = "deep"

ONESHOT_FADE_MS = 20


class SoundManager:

    def __init__(self, sounds_dir, *, enabled=True, heartbeat=None,
                 mild_channel=None, deep_channel=None):
        self.enabled = enabled
        self.heartbeat = heartbeat or HeartbeatConfig()
        self._state = STATE_OFF

        if not self.enabled:
            self._piece_move_sounds = []
            self._reload_sounds = []
            self._sounds = {}
            self._mild_channel = None
            self._deep_channel = None
            return

        sounds_dir = Path(sounds_dir)
        self._piece_move_sounds = self._load_variants(sounds_dir / "piece_moves")
        self._reload_sounds = self._load_variants(sounds_dir / "shotgun_reloads")
        self._sounds = {
            "capture": self._safe_load(sounds_dir / "shotgun_fire.mp3"),
            "checkmate": self._safe_load(sounds_dir / "metal_pipe_falling.mp3"),
            "undo": self._safe_load(sounds_dir / "rewind.mp3"),
            "game_start": self._safe_load(sounds_dir / "game_start.mp3"),
            "heartbeat_mild": self._safe_load(sounds_dir / "heartbeat_mild.mp3"),
            "heartbeat_deep": self._safe_load(sounds_dir / "heartbeat_deep.mp3"),
        }
        self._mild_channel = mild_channel if mild_channel is not None else self._reserve_channel(0)
        self._deep_channel = deep_channel if deep_channel is not None else self._reserve_channel(1)

    def _load_variants(self, dir_path):
        if not dir_path.is_dir():
            return []
        return [self._safe_load(p) for p in sorted(dir_path.glob("*.mp3"))
                if self._safe_load(p) is not None]

    @staticmethod
    def _safe_load(path):
        try:
            return pg.mixer.Sound(str(path))
        except (pg.error, FileNotFoundError):
            return None

    @staticmethod
    def _reserve_channel(idx):
        try:
            return pg.mixer.Channel(idx)
        except pg.error:
            return None

    def play_move(self):
        if not self.enabled or not self._piece_move_sounds:
            return
        random.choice(self._piece_move_sounds).play(fade_ms=ONESHOT_FADE_MS)

    def play_check(self):
        if not self.enabled or not self._reload_sounds:
            return
        random.choice(self._reload_sounds).play(fade_ms=ONESHOT_FADE_MS)

    def play_capture(self):
        self._play_one_shot("capture")

    def play_checkmate(self):
        self._play_one_shot("checkmate")

    def play_undo(self):
        self._play_one_shot("undo")

    def play_game_start(self):
        self._play_one_shot("game_start")

    def _play_one_shot(self, key):
        if not self.enabled:
            return
        sound = self._sounds.get(key)
        if sound is not None:
            sound.play(fade_ms=ONESHOT_FADE_MS)

    def update_heartbeat(self, fraction_remaining, paused):
        if not self.enabled:
            return
        cfg = self.heartbeat
        desired = self._desired_state(fraction_remaining, paused)
        self._transition_to(desired)
        if desired == STATE_MILD and self._mild_channel is not None:
            self._mild_channel.set_volume(self._mild_volume(fraction_remaining))
        elif desired == STATE_DEEP and self._deep_channel is not None:
            self._deep_channel.set_volume(self._deep_volume(fraction_remaining))

    def _desired_state(self, fraction, paused):
        cfg = self.heartbeat
        if paused or fraction is None or fraction > cfg.mild_start_fraction:
            return STATE_OFF
        if fraction > cfg.deep_start_fraction:
            return STATE_MILD
        return STATE_DEEP

    def _transition_to(self, desired):
        if desired == self._state:
            return
        cfg = self.heartbeat
        prev = self._state
        if desired == STATE_OFF:
            if prev == STATE_MILD and self._mild_channel is not None:
                self._mild_channel.fadeout(cfg.fade_out_ms)
            elif prev == STATE_DEEP and self._deep_channel is not None:
                self._deep_channel.fadeout(cfg.fade_out_ms)
        elif desired == STATE_MILD:
            if prev == STATE_DEEP and self._deep_channel is not None:
                self._deep_channel.fadeout(cfg.crossfade_ms)
            self._start_mild()
        elif desired == STATE_DEEP:
            if prev == STATE_MILD and self._mild_channel is not None:
                self._mild_channel.fadeout(cfg.crossfade_ms)
            self._start_deep()
        self._state = desired

    def _start_mild(self):
        sound = self._sounds.get("heartbeat_mild")
        if self._mild_channel is None or sound is None:
            return
        cfg = self.heartbeat
        self._mild_channel.play(sound, loops=-1, fade_ms=cfg.fade_in_ms)

    def _start_deep(self):
        sound = self._sounds.get("heartbeat_deep")
        if self._deep_channel is None or sound is None:
            return
        cfg = self.heartbeat
        self._deep_channel.play(sound, loops=-1, fade_ms=cfg.crossfade_ms)

    def _mild_volume(self, fraction):
        cfg = self.heartbeat
        span = cfg.mild_start_fraction - cfg.deep_start_fraction
        if span <= 0:
            return cfg.max_volume
        progress = (cfg.mild_start_fraction - fraction) / span
        return self._lerp_volume(progress)

    def _deep_volume(self, fraction):
        cfg = self.heartbeat
        span = cfg.deep_start_fraction
        if span <= 0:
            return cfg.max_volume
        progress = (cfg.deep_start_fraction - fraction) / span
        return self._lerp_volume(progress)

    def _lerp_volume(self, progress):
        cfg = self.heartbeat
        progress = max(0.0, min(progress, 1.0))
        return cfg.min_volume + (cfg.max_volume - cfg.min_volume) * progress

    def stop_all(self):
        if not self.enabled:
            return
        cfg = self.heartbeat
        if self._mild_channel is not None:
            self._mild_channel.fadeout(cfg.fade_out_ms)
        if self._deep_channel is not None:
            self._deep_channel.fadeout(cfg.fade_out_ms)
        self._state = STATE_OFF
