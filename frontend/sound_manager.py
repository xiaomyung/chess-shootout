import io
import random
from dataclasses import dataclass
from pathlib import Path

import pygame as pg

from backend.pieces import PieceType


@dataclass
class HeartbeatConfig:
    mild_start_fraction: float = 0.20
    deep_start_fraction: float = 0.10
    min_volume: float = 0.5
    max_volume: float = 1.0
    fade_in_ms: int = 400
    crossfade_ms: int = 300
    fade_out_ms: int = 300
    deep_speed_max: float = 2.0
    deep_speed_step: float = 0.05


STATE_OFF = "off"
STATE_MILD = "mild"
STATE_DEEP = "deep"

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
                 mild_channel=None, deep_channel=None):
        self.enabled = enabled
        self.master_volume = 1.0
        self.heartbeat = heartbeat or HeartbeatConfig()
        self._state = STATE_OFF
        self._deep_speed_bucket = -1

        if not self.enabled:
            self._piece_move_sounds = []
            self._reload_sounds = []
            self._capture_sounds = {}
            self._sounds = {}
            self._deep_source_path = Path()
            self._deep_variants = []
            self._mild_channel = None
            self._deep_channel = None
            return

        sounds_dir = Path(sounds_dir)
        self._piece_move_sounds = self._load_variants(sounds_dir / "piece_moves")
        self._reload_sounds = self._load_variants(sounds_dir / "shotgun_reloads")
        self._capture_sounds = self._load_capture_sounds(sounds_dir)
        self._sounds = {
            "checkmate": self._safe_load(sounds_dir / "metal_pipe_falling.mp3"),
            "undo": self._safe_load(sounds_dir / "rewind.mp3"),
            "game_start": self._safe_load(sounds_dir / "game_start.mp3"),
            "heartbeat_mild": self._safe_load(sounds_dir / "heartbeat_mild.mp3"),
            "castle": self._safe_load(sounds_dir / "castle_sound.mp3"),
        }
        self._deep_source_path = sounds_dir / "heartbeat_deep.mp3"
        self._deep_variants = None
        self._mild_channel = mild_channel if mild_channel is not None else self._reserve_channel(0)
        self._deep_channel = deep_channel if deep_channel is not None else self._reserve_channel(1)

    def _ensure_deep_variants(self):
        if self._deep_variants is None:
            self._deep_variants = self._build_deep_variants(self._deep_source_path)
        return self._deep_variants

    def _load_variants(self, dir_path):
        if not dir_path.is_dir():
            return []
        return [s for p in sorted(dir_path.glob("*.mp3"))
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
        single = self._safe_load(parent / f"{name}.mp3")
        return [single] if single is not None else []

    def _build_deep_variants(self, source_path):
        if not source_path.exists():
            return []
        try:
            from pydub import AudioSegment
            from pydub.effects import speedup
        except ImportError:
            single = self._safe_load(source_path)
            return [single] if single is not None else []

        try:
            base = AudioSegment.from_mp3(str(source_path))
        except Exception:
            single = self._safe_load(source_path)
            return [single] if single is not None else []

        cfg = self.heartbeat
        speeds = []
        s = 1.0
        while s <= cfg.deep_speed_max + 1e-9:
            speeds.append(round(s, 4))
            s += cfg.deep_speed_step

        variants = []
        for speed in speeds:
            try:
                seg = base if abs(speed - 1.0) < 1e-9 else speedup(base, playback_speed=speed)
                buf = io.BytesIO()
                seg.export(buf, format="wav")
                buf.seek(0)
                variants.append(pg.mixer.Sound(buffer=buf.read()))
            except Exception:
                continue
        return variants

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
        self._transition_to(desired, fraction_remaining)
        if desired == STATE_MILD and self._mild_channel is not None:
            self._mild_channel.set_volume(self._mild_volume(fraction_remaining))
        elif desired == STATE_DEEP and self._deep_channel is not None:
            self._deep_channel.set_volume(self._deep_volume(fraction_remaining))
            self._update_deep_speed(fraction_remaining)

    def _desired_state(self, fraction, paused):
        cfg = self.heartbeat
        if paused or fraction is None or fraction > cfg.mild_start_fraction:
            return STATE_OFF
        if fraction > cfg.deep_start_fraction:
            return STATE_MILD
        return STATE_DEEP

    def _transition_to(self, desired, fraction):
        if desired == self._state:
            return
        cfg = self.heartbeat
        prev = self._state
        if desired == STATE_OFF:
            if prev == STATE_MILD and self._mild_channel is not None:
                self._mild_channel.fadeout(cfg.fade_out_ms)
            elif prev == STATE_DEEP and self._deep_channel is not None:
                self._deep_channel.fadeout(cfg.fade_out_ms)
            self._deep_speed_bucket = -1
        elif desired == STATE_MILD:
            if prev == STATE_DEEP and self._deep_channel is not None:
                self._deep_channel.fadeout(cfg.crossfade_ms)
            self._start_mild()
            self._deep_speed_bucket = -1
        elif desired == STATE_DEEP:
            if prev == STATE_MILD and self._mild_channel is not None:
                self._mild_channel.fadeout(cfg.crossfade_ms)
            self._start_deep(fraction)
        self._state = desired

    def _start_mild(self):
        sound = self._sounds.get("heartbeat_mild")
        if self._mild_channel is None or sound is None:
            return
        cfg = self.heartbeat
        self._mild_channel.play(sound, loops=-1, fade_ms=cfg.fade_in_ms)

    def _start_deep(self, fraction):
        variants = self._ensure_deep_variants()
        if self._deep_channel is None or not variants:
            return
        bucket = self._desired_deep_bucket(fraction)
        self._deep_speed_bucket = bucket
        sound = variants[bucket]
        cfg = self.heartbeat
        self._deep_channel.play(sound, loops=-1, fade_ms=cfg.crossfade_ms)

    def _update_deep_speed(self, fraction):
        variants = self._ensure_deep_variants()
        if self._deep_channel is None or not variants:
            return
        target = self._desired_deep_bucket(fraction)
        if target == self._deep_speed_bucket:
            return
        self._deep_speed_bucket = target
        sound = variants[target]
        self._deep_channel.play(sound, loops=-1, fade_ms=ONESHOT_FADE_MS)

    def _desired_deep_bucket(self, fraction):
        cfg = self.heartbeat
        n = len(self._ensure_deep_variants())
        if n <= 1 or cfg.deep_start_fraction <= 0:
            return 0
        progress = (cfg.deep_start_fraction - fraction) / cfg.deep_start_fraction
        progress = max(0.0, min(progress, 1.0))
        return min(int(progress * (n - 1) + 0.5), n - 1)

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
        base = cfg.min_volume + (cfg.max_volume - cfg.min_volume) * progress
        return base * self.master_volume

    def stop_all(self):
        if not self.enabled:
            return
        cfg = self.heartbeat
        if self._mild_channel is not None:
            self._mild_channel.fadeout(cfg.fade_out_ms)
        if self._deep_channel is not None:
            self._deep_channel.fadeout(cfg.fade_out_ms)
        self._state = STATE_OFF
        self._deep_speed_bucket = -1
