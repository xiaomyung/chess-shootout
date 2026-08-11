import logging
import os
import shutil
import threading
import time

import pygame as pg

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.online.client import probe_server_health
from chessshootout.server.protocol import PROTOCOL_VERSION
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.menu.options_rows import (
    ActionRow, PathRow, RevealRow, TextRow, ToggleRow, NotchRow, SegmentedRow,
    TONE_IDLE, TONE_OK, TONE_WARN,
)


log = logging.getLogger("chess.frontend")

SETTINGS_WRITE_DELAY_MS = 400
SERVER_PROBE_BUTTON_IDLE = "Test"
SERVER_PROBE_BUTTON_PENDING = "Testing…"
SERVER_SWITCH_BLOCKED_MESSAGE = "Leave the online session to switch servers"
INVALID_SERVER_ADDR_MESSAGE = "Invalid server address"


class SettingsController:

    def __init__(self, frontend):
        self.frontend = frontend
        self._deferred_env_writes = {}
        self._data_folder_row = None
        self._custom_server_row = None
        self._server_probe_lock = threading.Lock()
        self._server_probe_pending = False
        self._server_probe_result = None
        self._server_probe_gen = 0

    def commit_options_exit(self):
        self._validate_data_folder_on_exit()
        if self._custom_server_row is not None:
            self._commit_custom_server_addr(self._custom_server_row.current_text())
        self._reset_server_probe()
        self.frontend.menu.apply_default_time_settings()
        self._flush_deferred_env_writes(force=True)

    def _online_session_active(self):
        return self.frontend.coordinator.is_connected()

    def _apply_server_mode(self, mode):
        if mode == env.get_server_mode():
            return
        if self._online_session_active():
            self.frontend.toast.show(SERVER_SWITCH_BLOCKED_MESSAGE)
            return
        env.set_server_mode(mode)
        self._announce_server_target_change()

    def _commit_custom_server_addr(self, typed):
        if not typed or typed == env.get_custom_server_addr():
            return
        if self._online_session_active():
            self.frontend.toast.show(SERVER_SWITCH_BLOCKED_MESSAGE)
            return
        if not env.set_custom_server_addr(typed):
            self.frontend.toast.show(INVALID_SERVER_ADDR_MESSAGE)
            return
        self._announce_server_target_change()
        if env.get_server_mode() == env.SERVER_MODE_CUSTOM:
            self.frontend.toast.show(f"Server set to {env.get_server_addr()}")

    def _announce_server_target_change(self):
        self._reset_server_probe()
        self.frontend.coordinator.on_server_target_changed()
        log.info("server target set mode=%s addr=%s", env.get_server_mode(),
                 env.get_server_addr())

    def _on_test_server(self):
        with self._server_probe_lock:
            if self._server_probe_pending:
                return
            self._server_probe_gen += 1
            gen = self._server_probe_gen
            self._server_probe_pending = True
            self._server_probe_result = None
        addr = self._probe_target_addr()
        threading.Thread(target=self._server_probe_worker, args=(addr, gen),
                         daemon=True).start()

    def _probe_target_addr(self):
        if env.get_server_mode() != env.SERVER_MODE_CUSTOM:
            return env.get_server_addr()
        if self._custom_server_row is None:
            return env.get_custom_server_addr()
        return self._custom_server_row.current_text() or env.get_custom_server_addr()

    def _server_probe_worker(self, addr, gen):
        try:
            started = time.monotonic()
            health = probe_server_health(addr)
            latency_ms = int((time.monotonic() - started) * 1000)
            outcome = self._describe_health(health, latency_ms)
            with self._server_probe_lock:
                if gen != self._server_probe_gen:
                    return
                self._server_probe_result = (addr, outcome)
            log.debug("server probe addr=%s outcome=%s", addr, outcome[1])
        finally:
            with self._server_probe_lock:
                if gen == self._server_probe_gen:
                    self._server_probe_pending = False

    def _describe_health(self, health, latency_ms):
        if health is None:
            return (TONE_WARN, "Unreachable")
        version = health.get("version")
        if version != PROTOCOL_VERSION:
            seen = "?" if version is None else version
            return (TONE_WARN,
                    f"Protocol mismatch: server v{seen} ≠ client v{PROTOCOL_VERSION}")
        app_version = health.get("app_version") or ""
        suffix = f" · v{app_version}" if app_version else ""
        return (TONE_OK, f"OK · {latency_ms} ms{suffix}")

    def _probe_button_label(self):
        with self._server_probe_lock:
            pending = self._server_probe_pending
        return SERVER_PROBE_BUTTON_PENDING if pending else SERVER_PROBE_BUTTON_IDLE

    def _probe_status(self):
        with self._server_probe_lock:
            pending = self._server_probe_pending
            probed = self._server_probe_result
        if pending or probed is None:
            return (TONE_IDLE, "")
        addr, outcome = probed
        if addr != self._probe_target_addr():
            return (TONE_IDLE, "")
        return outcome

    def _reset_server_probe(self):
        with self._server_probe_lock:
            self._server_probe_gen += 1
            self._server_probe_pending = False
            self._server_probe_result = None

    def _validate_data_folder_on_exit(self):
        if self._data_folder_row is None:
            return
        typed = self._data_folder_row.current_text()
        if not typed:
            return
        typed = os.path.abspath(os.path.expanduser(typed))
        if os.path.normpath(typed) == os.path.normpath(str(paths.get_data_dir())):
            return
        if not paths.is_writable_dir(typed):
            self.frontend.toast.show("That folder isn't writable")
            return
        self._apply_data_folder_change(typed)

    def apply_hide_opp_marks(self, value):
        env.set_hide_opp_marks(value)
        game = self.frontend.game
        coordinator = self.frontend.coordinator
        if coordinator.is_connected() and game.variant == Variant.ONLINE:
            coordinator.set_marks_visibility(value)
        if value:
            game.apply_opp_marks_shield()

    def _set_master_volume(self, value):
        self.frontend.sound_manager.set_master_volume(value)

    def _set_menu_volume(self, value):
        self.frontend.sound_manager.set_menu_volume(value)

    def _commit_master_volume(self):
        env.set_master_volume(self.frontend.sound_manager.master_volume)

    def defer_master_volume_write(self):
        self._defer_env_write("master_volume", self._commit_master_volume)

    def _commit_menu_volume(self):
        env.set_menu_volume(self.frontend.sound_manager.menu_volume)

    def _defer_env_write(self, key, commit):
        self._deferred_env_writes[key] = (commit, pg.time.get_ticks() + SETTINGS_WRITE_DELAY_MS)

    def _flush_deferred_env_writes(self, force=False):
        if not self._deferred_env_writes:
            return
        now = pg.time.get_ticks()
        for key in list(self._deferred_env_writes):
            commit, due = self._deferred_env_writes[key]
            if force or now >= due:
                del self._deferred_env_writes[key]
                commit()

    def build_settings_sections(self):
        window = self.frontend.window
        sound_manager = self.frontend.sound_manager
        self._data_folder_row = PathRow(
            "Games folder", "Where PGNs are saved", window,
            lambda: str(paths.get_data_dir()),
            self._on_change_data_folder, self._on_reset_data_folder,
            suffix="/" + paths.GAMES_SUBDIR)
        self._custom_server_row = TextRow(
            "Custom address", "Host or host:port of the server you run",
            window, env.get_custom_server_addr, placeholder="host or host:port",
            on_commit=self._commit_custom_server_addr)
        time_options = [(label, label) for label in env.TIME_CONTROL_VALUES]
        incr_options = [(label, label) for label in env.INCREMENT_VALUES]
        return [
            ("Audio", [
                NotchRow("Master volume", "", lambda: sound_manager.master_volume,
                         self._set_master_volume, on_tick=sound_manager.play_ui_tick,
                         on_release=lambda: self._defer_env_write(
                             "master_volume", self._commit_master_volume)),
                NotchRow("Menu volume", "", lambda: sound_manager.menu_volume,
                         self._set_menu_volume, on_tick=sound_manager.play_ui_tick,
                         on_release=lambda: self._defer_env_write(
                             "menu_volume", self._commit_menu_volume)),
                ToggleRow("Mute all sound", "Silence every shot and callout",
                          lambda: not sound_manager.enabled,
                          lambda muted: sound_manager.set_enabled(not muted)),
            ]),
            ("Display", [
                SegmentedRow("Launch mode",
                             "How the window opens — applies on next launch",
                             [("Windowed", "windowed"), ("Maximized", "maximized"),
                              ("Fullscreen", "fullscreen")],
                             env.get_launch_mode, env.set_launch_mode),
            ]),
            ("Focus mode", [
                SegmentedRow("Show in focus",
                             "What stays on screen when the panel is hidden",
                             [("Nothing", "nothing"), ("Time Line", "line"),
                              ("Full strips", "strips")],
                             env.get_focus_show, env.set_focus_show),
            ]),
            ("Game", [
                SegmentedRow("Default time", "Minutes on the clock, or untimed",
                             time_options, env.get_default_time_control,
                             env.set_default_time_control, mono=True, variant="cells"),
                SegmentedRow("Default increment", "Seconds added each move",
                             incr_options, env.get_default_increment,
                             env.set_default_increment, mono=True, variant="cells"),
                ToggleRow("Auto-queen",
                          "Promotions auto-pick the queen — the skill check still fires",
                          env.get_auto_queen, env.set_auto_queen),
                self._data_folder_row,
            ]),
            ("Online", [
                SegmentedRow("Server", "Official servers, or your own address",
                             [("Official", env.SERVER_MODE_OFFICIAL),
                              ("Custom", env.SERVER_MODE_CUSTOM)],
                             env.get_server_mode, self._apply_server_mode),
                RevealRow(self._custom_server_row,
                          lambda: env.get_server_mode() == env.SERVER_MODE_CUSTOM),
                ActionRow("Connection", "Check the server answers before you queue",
                          self._probe_button_label, self._on_test_server,
                          self._probe_status),
                ToggleRow("Hide opponent's marks",
                          "Never show the arrows and highlights they share",
                          env.get_hide_opp_marks, self.apply_hide_opp_marks),
            ]),
            ("Performance", [
                ToggleRow("Show FPS", "Frame rate in the title bar",
                          env.get_show_fps, env.set_show_fps),
                ToggleRow("Show avg / min FPS", "Rolling render-rate over recent frames",
                          env.get_show_frame_stats, env.set_show_frame_stats),
                ToggleRow("Show 1% low FPS", "Worst-1% frames — the stutter metric",
                          env.get_show_1pct_low, env.set_show_1pct_low),
                ToggleRow("Show frame time", "Milliseconds of render work per frame",
                          env.get_show_frametime, env.set_show_frametime),
                ToggleRow("Show ping", "Network latency in the title bar",
                          env.get_show_ping, env.set_show_ping),
            ]),
        ]

    def _on_change_data_folder(self):
        self.frontend.directory_browser.show(
            str(paths.get_data_dir()),
            on_select=self._apply_data_folder_change,
            on_error=self.frontend.toast.show,
        )

    def _on_reset_data_folder(self):
        default = paths.get_default_data_dir()
        self._apply_data_folder_change(str(default), to_default=True)

    def _apply_data_folder_change(self, new_dir, to_default=False):
        old_games = str(paths.get_games_dir())
        new_games = os.path.join(new_dir, paths.GAMES_SUBDIR)
        if os.path.normpath(old_games) == os.path.normpath(new_games):
            self._commit_data_dir(new_dir, to_default, None)
            return
        if os.path.isdir(old_games):
            pgns = [f for f in os.listdir(old_games) if f.endswith(".pgn")]
        else:
            pgns = []
        if pgns:
            count = len(pgns)
            suffix = "s" if count != 1 else ""
            self.frontend.confirm_modal.show(
                f"Move {count} saved game{suffix} to the new folder?",
                on_yes=lambda: self._commit_data_dir(new_dir, to_default, old_games),
                on_no=lambda: self._commit_data_dir(new_dir, to_default, None),
                yes_label="Move", no_label="Don't move",
                on_extra=lambda: None, extra_label="Cancel", emoji="📁",
            )
        else:
            self._commit_data_dir(new_dir, to_default, None)

    def _commit_data_dir(self, new_dir, to_default, move_from):
        new_games = os.path.join(new_dir, paths.GAMES_SUBDIR)
        if move_from is not None and not self._move_pgns(move_from, new_games):
            return
        env.set_data_dir(None if to_default else new_dir)
        self.frontend.toast.show("Data folder updated")

    def _move_pgns(self, src, dst):
        try:
            os.makedirs(dst, exist_ok=True)
            for name in os.listdir(src):
                if not name.endswith(".pgn"):
                    continue
                target = os.path.join(dst, name)
                if os.path.exists(target):
                    target = self._unique_pgn_name(dst, name)
                shutil.move(os.path.join(src, name), target)
        except OSError:
            self.frontend.toast.show("Could not move games")
            return False
        try:
            os.rmdir(src)
        except OSError:
            pass
        return True

    def _unique_pgn_name(self, dst, name):
        base, ext = os.path.splitext(name)
        i = 1
        while True:
            candidate = os.path.join(dst, f"{base}-{i}{ext}")
            if not os.path.exists(candidate):
                return candidate
            i += 1
