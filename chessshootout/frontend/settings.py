import os
import shutil

import pygame as pg

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.frontend.menu.options_rows import (
    PathRow, TextRow, ToggleRow, NotchRow, SegmentedRow,
)


SETTINGS_WRITE_DELAY_MS = 400


class SettingsController:

    def __init__(self, frontend):
        self.frontend = frontend
        self._deferred_env_writes = {}
        self._data_folder_row = None
        self._server_addr_row = None

    def commit_options_exit(self):
        self._validate_data_folder_on_exit()
        if self._server_addr_row is not None:
            env.set_server_addr(self._server_addr_row.current_text())
        self.frontend.menu.apply_default_time_settings()
        self._flush_deferred_env_writes(force=True)

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
        self._server_addr_row = TextRow(
            "Server", "Where online games connect and reconnect",
            window, env.get_server_addr, placeholder="host or host:port")
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
                self._server_addr_row,
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
