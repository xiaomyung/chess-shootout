import random
from dataclasses import dataclass
from pathlib import Path

import pygame as pg

from chessshootout.infra import env
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION
from chessshootout.frontend.audio.slots import SLOTS, move_slot, gun_slot, hit_slot


@dataclass
class HeartbeatConfig:
    start_fraction: float = LOW_TIME_FRACTION
    fast_fraction: float = 0.05
    min_volume: float = 0.10
    max_volume: float = 1.0
    fade_in_ms: int = 400
    fade_out_ms: int = 300


STATE_OFF = "off"
STATE_SLOW = "slow"
STATE_FAST = "fast"

ONESHOT_FADE_MS = 20


def _clamp_volume(value):
    return max(0.0, min(1.0, float(value)))


class SoundManager:

    def __init__(self, sounds_dir, *, enabled=True, heartbeat=None,
                 heartbeat_channel=None, master_volume=None, menu_volume=None):
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
        self._slots = {}

        self._sounds_dir = Path(sounds_dir)

        if not self.enabled:
            self._heartbeat_channel = None
            return

        self._heartbeat_channel = (
            heartbeat_channel if heartbeat_channel is not None
            else self._reserve_channel(0)
        )

    def preload(self):
        for name in SLOTS:
            self._slot_pool(name)

    def _slot_pool(self, name):
        if not self.enabled:
            return []
        pool = self._slots.get(name)
        if pool is None:
            spec = SLOTS.get(name)
            pool = self._load_pool(self._sounds_dir / spec.dst) if spec else []
            self._slots[name] = pool
        return pool

    def _load_pool(self, dir_path):
        if not dir_path.is_dir():
            return []
        return [s for p in sorted(dir_path.glob("*.ogg"))
                if (s := self._safe_load(p)) is not None]

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

    def _play_random_at(self, sounds, volume):
        if not self.enabled or not sounds:
            return
        self._play_at(random.choice(sounds), volume)

    def _play_random(self, sounds):
        if not self.enabled or not sounds:
            return
        self._play_with_master(random.choice(sounds))

    def _play(self, slot):
        self._play_random(self._slot_pool(slot))

    def play_move(self, piece_type=None):
        if piece_type is None:
            return
        self._play(move_slot(piece_type.value))

    def play_premove_queued(self, piece_type=None):
        self.play_move(piece_type)

    def play_capture(self, piece_type=None):
        if piece_type is None:
            return
        self._play(gun_slot(piece_type.value))

    def play_menu_gun(self, gun):
        self._play_random_at(self._slot_pool(f"gun_{gun}"),
                             self.master_volume * self.menu_volume)

    def play_check(self):
        self._play("reload_check")

    def play_announcer(self, key):
        self._play(f"announcer_{key}")

    def play_hit(self, victim=None):
        slot = hit_slot(victim.value) if victim is not None else "announcer_hits"
        self._play(slot)

    def play_checkmate(self):
        self._play("checkmate")

    def play_castle(self):
        self._play("castle")

    def play_undo(self):
        self._play("undo")

    def play_game_start(self):
        self._play("game_start")

    def play_online_game_start(self):
        self._play("online_game_start")

    def play_give_time(self):
        self._play("give_time")

    def play_you_win(self):
        self._play("you_win")

    def play_you_lose(self):
        self._play("you_lose")

    def play_flag_fall(self):
        self._play("you_lose")

    def play_draw(self):
        self._play("draw")

    def play_surrender(self):
        self._play("resign")

    def play_toast(self):
        self._play("toast")

    def play_flip(self):
        self._play("board_flip")

    def play_pickup(self):
        self._play("pickup")

    def play_drop(self):
        self._play("drop")

    def play_swear(self):
        self._play("swear")

    def play_ui_click(self):
        self._play("ui_click")

    def play_ui_tick(self):
        self._play("ui_tick")

    def play_give_ratchet(self):
        self._play("give_ratchet")

    def play_drum_tick(self):
        self._play("drum_tick")

    def play_turret_ratchet(self):
        self._play("turret_ratchet")

    def play_card_toggle(self):
        self._play("card_toggle")

    def play_rail_click(self):
        self._play("rail_click")

    def play_focus_action(self):
        self._play("focus_action")

    def play_skillcheck_appear(self):
        self._play("sc_appear")

    def play_skillcheck_win(self):
        self._play("sc_win")

    def play_skillcheck_miss(self):
        self._play("sc_miss")

    def play_wheel_tick(self):
        self._play("wheel_tick")

    def play_aim_lock(self):
        self._play("aim_lock")

    def play_aim_beep(self):
        self._play("aim_beep")

    def update_heartbeat(self, fraction_remaining, paused):
        if not self.enabled:
            return
        desired = self._desired_state(fraction_remaining, paused)
        self._transition_to(desired)
        if desired in (STATE_SLOW, STATE_FAST) and self._heartbeat_channel is not None:
            self._heartbeat_channel.set_volume(self._heartbeat_volume(fraction_remaining))

    def _desired_state(self, fraction, paused):
        cfg = self.heartbeat
        if paused or fraction is None or fraction > cfg.start_fraction:
            return STATE_OFF
        if fraction > cfg.fast_fraction:
            return STATE_SLOW
        return STATE_FAST

    def _transition_to(self, desired):
        if desired == self._state:
            return
        cfg = self.heartbeat
        if desired == STATE_OFF:
            if self._heartbeat_channel is not None:
                self._heartbeat_channel.fadeout(cfg.fade_out_ms)
        else:
            self._start_heartbeat(desired)
        self._state = desired

    def _start_heartbeat(self, state):
        channel = self._heartbeat_channel
        if channel is None:
            return
        slot = "heartbeat_fast" if state == STATE_FAST else "heartbeat_slow"
        pool = self._slot_pool(slot)
        if not pool:
            return
        channel.play(random.choice(pool), loops=-1, fade_ms=self.heartbeat.fade_in_ms)

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
