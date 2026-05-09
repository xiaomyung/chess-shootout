import random
from dataclasses import dataclass
from pathlib import Path

import pygame as pg

from backend.pieces import PieceType
from frontend.visual.clock_visual import LOW_TIME_FRACTION


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

CAPTURE_SOUND_BY_PIECE = {
    PieceType.PAWN: "pawn_shot",
    PieceType.KNIGHT: "knight_shot",
    PieceType.BISHOP: "bishop_shot",
    PieceType.ROOK: "rook_shot",
    PieceType.QUEEN: "queen_shot",
    PieceType.KING: "king_capture",
}


class SoundManager:

    def __init__(self, sounds_dir, *, enabled=True, heartbeat=None,
                 heartbeat_channel=None, master_volume=None):
        from frontend import env
        self.enabled = enabled
        self.master_volume = (
            env.get_master_volume() if master_volume is None
            else max(0.0, min(1.0, float(master_volume)))
        )
        self.heartbeat = heartbeat or HeartbeatConfig()
        self._state = STATE_OFF

        if not self.enabled:
            self._piece_move_sounds = []
            self._reload_sounds = []
            self._capture_sounds = {}
            self._sounds = {}
            self._heartbeat_channel = None
            return

        sounds_dir = Path(sounds_dir)
        self._piece_move_sounds = self._load_variants(sounds_dir / "piece_moves")
        self._reload_sounds = self._load_variants(sounds_dir / "shotgun_reloads")
        self._capture_sounds = self._load_capture_sounds(sounds_dir)
        self._sounds = {
            "checkmate": self._safe_load(sounds_dir / "metal_pipe_falling.ogg"),
            "undo": self._safe_load(sounds_dir / "rewind.ogg"),
            "game_start": self._safe_load(sounds_dir / "game_start.ogg"),
            "heartbeat": self._safe_load(sounds_dir / "heartbeat.ogg"),
            "castle": self._safe_load(sounds_dir / "castle_sound.ogg"),
            "you_lose": self._safe_load(sounds_dir / "you_lose.ogg"),
            "online_game_start": self._safe_load(sounds_dir / "online_game_start.ogg"),
        }
        self._heartbeat_channel = (
            heartbeat_channel if heartbeat_channel is not None
            else self._reserve_channel(0)
        )

    def _load_variants(self, dir_path):
        if not dir_path.is_dir():
            return []
        return [s for p in sorted(dir_path.glob("*.ogg"))
                if (s := self._safe_load(p)) is not None]

    def _load_capture_sounds(self, sounds_dir):
        result = {}
        capture_dir = sounds_dir / "capture_sounds"
        for piece_type, name in CAPTURE_SOUND_BY_PIECE.items():
            variants = self._load_variant_pack(capture_dir, name)
            if variants:
                result[piece_type] = variants
        return result

    def _load_variant_pack(self, parent, name):
        pack_dir = parent / name
        if pack_dir.is_dir():
            variants = self._load_variants(pack_dir)
            if variants:
                return variants
        single = self._safe_load(parent / f"{name}.ogg")
        return [single] if single is not None else []

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
        self.master_volume = max(0.0, min(1.0, float(value)))

    def set_enabled(self, value):
        new_enabled = bool(value)
        if not new_enabled and self.enabled:
            self.stop_all()
        self.enabled = new_enabled

    def _play_with_master(self, sound):
        sound.set_volume(self.master_volume)
        sound.play(fade_ms=ONESHOT_FADE_MS)

    def _play_random(self, sounds):
        if not self.enabled or not sounds:
            return
        self._play_with_master(random.choice(sounds))

    def play_move(self):
        self._play_random(self._piece_move_sounds)

    def play_premove_queued(self):
        self._play_random(self._piece_move_sounds)

    def play_check(self):
        self._play_random(self._reload_sounds)

    def play_capture(self, piece_type=None):
        variants = self._capture_sounds.get(piece_type)
        if not variants and self._capture_sounds:
            variants = next(iter(self._capture_sounds.values()))
        self._play_random(variants or [])

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

    def _play_one_shot(self, key):
        if not self.enabled:
            return
        sound = self._sounds.get(key)
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
        sound = self._sounds.get("heartbeat")
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
