import random
from dataclasses import dataclass
from pathlib import Path

import pygame as pg

from frontend.visual.clock_visual import LOW_TIME_FRACTION
from frontend.visual.gunfx import PIECE_GUN


@dataclass
class HeartbeatConfig:
    start_fraction: float = LOW_TIME_FRACTION
    min_volume: float = 0.10
    max_volume: float = 1.0
    fade_in_ms: int = 400
    fade_out_ms: int = 300


STATE_OFF = "off"
STATE_HEARTBEAT = "heartbeat"

ONESHOT_FADE_MS = 20

GUNS_DIR = "guns"

ANNOUNCER_DIR = "announcer"

ONE_SHOT_FILES = {
    "checkmate": "metal_pipe_falling.ogg",
    "undo": "rewind.ogg",
    "game_start": "game_start.ogg",
    "heartbeat": "heartbeat.ogg",
    "castle": "castle_sound.ogg",
    "you_lose": "you_lose.ogg",
    "online_game_start": "online_game_start.ogg",
    "executed": "executed.ogg",
    "give_time": "give_time.ogg",
    "surrender": "surrender.ogg",
}

ANNOUNCER_FILES = {
    key: f"{ANNOUNCER_DIR}/{key}.ogg" for key in (
        "first_blood", "double_kill", "triple_kill", "quadra_kill",
        "rampage", "unstoppable", "godlike",
    )
}

VARIANT_DIRS = {
    "move": "piece_moves",
    "reload": f"{GUNS_DIR}/shotgun_reloads",
    "hit": f"{ANNOUNCER_DIR}/hits",
}


def _clamp_volume(value):
    return max(0.0, min(1.0, float(value)))


class SoundManager:

    def __init__(self, sounds_dir, *, enabled=True, heartbeat=None,
                 heartbeat_channel=None, master_volume=None, menu_volume=None):
        from frontend import env
        self.enabled = enabled
        self.master_volume = (
            env.get_master_volume() if master_volume is None
            else _clamp_volume(master_volume)
        )
        self.menu_volume = (
            env.get_menu_volume() if menu_volume is None
            else _clamp_volume(menu_volume)
        )
        self.heartbeat = heartbeat or HeartbeatConfig()
        self._state = STATE_OFF

        if not self.enabled:
            self._variants = {}
            self._gun_shots = {}
            self._oneshots = {}
            self._heartbeat_channel = None
            return

        sounds_dir = Path(sounds_dir)
        self._variants = {key: self._load_variants(sounds_dir / rel)
                          for key, rel in VARIANT_DIRS.items()}
        self._gun_shots = self._load_gun_shots(sounds_dir / GUNS_DIR)
        self._oneshots = {key: self._safe_load(sounds_dir / rel)
                          for key, rel in {**ONE_SHOT_FILES, **ANNOUNCER_FILES}.items()}
        self._heartbeat_channel = (
            heartbeat_channel if heartbeat_channel is not None
            else self._reserve_channel(0)
        )

    def _load_variants(self, dir_path):
        if not dir_path.is_dir():
            return []
        return [s for p in sorted(dir_path.glob("*.ogg"))
                if (s := self._safe_load(p)) is not None]

    def _load_gun_shots(self, guns_dir):
        return {gun: s for gun in sorted(set(PIECE_GUN.values()))
                if (s := self._safe_load(guns_dir / f"{gun}_shot.ogg")) is not None}

    @staticmethod
    def _safe_load(path):
        try:
            return pg.mixer.Sound(str(path))
        except (pg.error, FileNotFoundError):
            return None

    @staticmethod
    def _reserve_channel(idx):
        try:
            channel = pg.mixer.Channel(idx)
            pg.mixer.set_reserved(idx + 1)
            return channel
        except pg.error:
            return None

    def set_master_volume(self, value):
        self.master_volume = _clamp_volume(value)

    def set_menu_volume(self, value):
        self.menu_volume = _clamp_volume(value)

    def set_enabled(self, value):
        new_enabled = bool(value)
        if not new_enabled and self.enabled:
            self.stop_all()
        self.enabled = new_enabled

    def _play_at(self, sound, volume):
        sound.set_volume(volume)
        sound.play(fade_ms=ONESHOT_FADE_MS)

    def _play_with_master(self, sound):
        self._play_at(sound, self.master_volume)

    def play_menu_gun(self, gun):
        if not self.enabled:
            return
        sound = self._gun_shots.get(gun)
        if sound is not None:
            self._play_at(sound, self.master_volume * self.menu_volume)

    def _play_random(self, sounds):
        if not self.enabled or not sounds:
            return
        self._play_with_master(random.choice(sounds))

    def play_move(self):
        self._play_random(self._variants.get("move", []))

    def play_premove_queued(self):
        self._play_random(self._variants.get("move", []))

    def play_check(self):
        self._play_random(self._variants.get("reload", []))

    def play_capture(self, piece_type=None):
        if not self.enabled:
            return
        gun = PIECE_GUN.get(piece_type.value) if piece_type is not None else None
        sound = self._gun_shots.get(gun)
        if sound is None and self._gun_shots:
            sound = next(iter(self._gun_shots.values()))
        if sound is not None:
            self._play_with_master(sound)

    def play_checkmate(self):
        self._play_one_shot("checkmate")

    def play_castle(self):
        self._play_one_shot("castle")

    def play_undo(self):
        self._play_one_shot("undo")

    def play_game_start(self):
        self._play_one_shot("game_start")

    def play_flag_fall(self):
        self._play_one_shot("you_lose")

    def play_online_game_start(self):
        self._play_one_shot("online_game_start")

    def play_announcer(self, key):
        self._play_one_shot(key)

    def play_hit(self):
        self._play_random(self._variants.get("hit", []))

    def play_mate_sting(self):
        self._play_one_shot("executed")

    def play_give_time(self):
        self._play_one_shot("give_time")

    def play_surrender(self):
        self._play_one_shot("surrender")

    def _play_one_shot(self, key):
        if not self.enabled:
            return
        sound = self._oneshots.get(key)
        if sound is not None:
            self._play_with_master(sound)

    def update_heartbeat(self, fraction_remaining, paused):
        if not self.enabled:
            return
        desired = self._desired_state(fraction_remaining, paused)
        self._transition_to(desired)
        if desired == STATE_HEARTBEAT and self._heartbeat_channel is not None:
            self._heartbeat_channel.set_volume(self._heartbeat_volume(fraction_remaining))

    def _desired_state(self, fraction, paused):
        cfg = self.heartbeat
        if paused or fraction is None or fraction > cfg.start_fraction:
            return STATE_OFF
        return STATE_HEARTBEAT

    def _transition_to(self, desired):
        if desired == self._state:
            return
        cfg = self.heartbeat
        if desired == STATE_OFF and self._heartbeat_channel is not None:
            self._heartbeat_channel.fadeout(cfg.fade_out_ms)
        elif desired == STATE_HEARTBEAT:
            self._start_heartbeat()
        self._state = desired

    def _start_heartbeat(self):
        sound = self._oneshots.get("heartbeat")
        if self._heartbeat_channel is None or sound is None:
            return
        cfg = self.heartbeat
        self._heartbeat_channel.play(sound, loops=-1, fade_ms=cfg.fade_in_ms)

    def _heartbeat_volume(self, fraction):
        cfg = self.heartbeat
        if cfg.start_fraction <= 0:
            return cfg.max_volume * self.master_volume
        progress = (cfg.start_fraction - fraction) / cfg.start_fraction
        progress = max(0.0, min(progress, 1.0))
        base = cfg.min_volume + (cfg.max_volume - cfg.min_volume) * progress
        return base * self.master_volume

    def stop_all(self):
        if not self.enabled:
            return
        cfg = self.heartbeat
        if self._heartbeat_channel is not None:
            self._heartbeat_channel.fadeout(cfg.fade_out_ms)
        self._state = STATE_OFF
