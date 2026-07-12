import logging
import os
import random
import time
from collections import deque

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import SINGLE_SCREEN, ONLINE
from chessshootout.backend.backend import Backend
from chessshootout.backend.fen import apply_fen
from chessshootout.infra import env
from chessshootout.frontend.panels.audio import AudioPanel
from chessshootout.frontend.menu.menu_battle import MenuBattle
from chessshootout.frontend.menu.history import HistoryView
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.confirm import ConfirmModal
from chessshootout.frontend.modals.country_picker import CountryPicker
from chessshootout.frontend.modals.directory_browser import DirectoryBrowser
from chessshootout.frontend.modals.options import OptionsModal
from chessshootout.frontend.settings import SettingsController
from chessshootout.frontend.modals.help import HelpModal, HOTKEYS
from chessshootout.frontend.visual.toast import Toast
from chessshootout.frontend.visual import cache
from chessshootout.frontend.input_router import InputRouter
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.screens.base import Nav, assert_plain_payload
from chessshootout.frontend.screens.menu import MenuScreen
from chessshootout.frontend.screens.game import GameScreen
from chessshootout.frontend.screens.history import HistoryScreen
from chessshootout.frontend.screens.review import ReviewScreen
from chessshootout.frontend.window_chrome import (
    WindowChrome, WINDOW_FLAGS, WINDOW_TITLE, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from chessshootout.infra.open_external import open_with_default_app
from chessshootout.frontend.online_coordinator import OnlineCoordinator
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.modals.start import StartMenu
from chessshootout.domain.pgn.load import latest_pgn_in_dir
from chessshootout.paths import SOUNDS_DIR


PERF_SAMPLE_COUNT = 240
PERF_1PCT_PERCENTILE = 0.99
PERF_1PCT_MIN_SAMPLES = 100


def _games_dir():
    return str(paths.get_games_dir())


log = logging.getLogger("chess.frontend")


_ICON_CACHE = cache.new_cache()


def _load_window_icon():
    def build():
        try:
            return pg.image.load(str(paths.resource_path("assets", "icons", "icon.png")))
        except (pg.error, OSError):
            return None
    return cache.memoized_surface(_ICON_CACHE, "icon", build)


class Frontend:

    def __init__(self, window_width: int, window_height: int):
        self.running = True
        self.target_fps = 300
        self.window_width = max(window_width, MIN_WINDOW_WIDTH)
        self.window_height = max(window_height, MIN_WINDOW_HEIGHT)
        self.window = pg.display.set_mode(
            (self.window_width, self.window_height), WINDOW_FLAGS)
        pg.key.set_repeat(400, 35)
        icon = _load_window_icon()
        if icon is not None:
            pg.display.set_icon(icon)
        self._pre_fullscreen_size = None
        self.settings = SettingsController(self)
        self.chrome = WindowChrome(self.window, on_fullscreen=self._apply_fullscreen)
        self.clock = pg.time.Clock()

        self._needs_full_present = True
        self._frame_times = deque(maxlen=PERF_SAMPLE_COUNT)
        self._last_work_ms = 0.0
        self._last_frame_start = None
        self._prev_screen_used_backdrop = False

        self.sound_manager = SoundManager(SOUNDS_DIR, enabled=pg.mixer.get_init() is not None)
        self.coordinator = OnlineCoordinator(self)
        self.start_menu = StartMenu(self.window, {
            "start_game": self._on_start_game,
            "load_pgn": self._on_open_history,
            "fen": self._on_open_fen_modal,
            "reconnect": self.coordinator.reconnect,
            "options": self.settings._on_open_options,
            "open_url": open_with_default_app,
            "toast": lambda msg: self.toast.show(msg),
        })
        self.audio_panel = AudioPanel(self.window, self.sound_manager)
        self.confirm_modal = ConfirmModal(self.window)
        self.history_view = HistoryView(self.window, on_open=self._open_pgn_review,
                                        on_back=self._on_menu_back)
        self.help_modal = HelpModal(self.window)
        self.options_modal = OptionsModal(self.window)
        self.country_picker = CountryPicker(self.window)
        self.directory_browser = DirectoryBrowser(self.window)
        self.toast = Toast(self.window)
        self.toast.top_inset = self.chrome.HEIGHT
        self.toast.on_new = lambda: self.sound_manager.play_toast()
        if env.normalize_stored_nickname():
            self.start_menu.text_input.text = env.get_nickname()
            self.toast.show("Your nickname contained non ASCII symbols, I cleaned them :3")
        self.input_router = InputRouter(self)
        self._modal_registry = [
            ModalSpec(self.confirm_modal, on_dismiss=self.input_router._dismiss_confirm),
            ModalSpec(self.coordinator.wait_modal, on_dismiss=self.coordinator._on_online_cancel),
            ModalSpec(self.coordinator.match_found_modal, esc_dismiss=False),
            ModalSpec(self.coordinator.reconnecting_modal, esc_dismiss=False),
            ModalSpec(self.country_picker),
            ModalSpec(self.directory_browser),
            ModalSpec(self.options_modal, on_dismiss=self.settings._dismiss_options),
        ]
        self.menu_battle = MenuBattle(self.window, sound_manager=self.sound_manager)
        self._pending_nav = None

        self.menu = MenuScreen(self)
        self.game = GameScreen(self)
        self.history = HistoryScreen(self)
        self.review = ReviewScreen(self)
        self.screens = {
            "menu": self.menu,
            "game": self.game,
            "history": self.history,
            "review": self.review,
        }
        self.screen = self.screens["menu"]

        self.game.board.load_assets()
        self.review.board.load_assets()
        self._compute_layout()
        self._refresh_load_pgn_availability()
        self._settle_window()
        self.coordinator._spawn_reconnect_probe()

        pg.display.set_caption(WINDOW_TITLE)

    def switch_to(self, name, **payload):
        if name not in self.screens:
            raise KeyError(f"unknown screen: {name!r}")
        assert_plain_payload(payload)
        screen = self.screens[name]
        previous = self.screen
        log.info("screen switch %s -> %s", previous.name, name)
        previous.exit()
        log.debug("screen exited %s", previous.name)
        self.screen = screen
        screen.enter(**payload)
        log.debug("screen entered %s payload_keys=%s", name, sorted(payload))
        self._compute_layout()
        pg.display.set_caption(screen.caption() or WINDOW_TITLE)

    def request_nav(self, nav):
        if self._pending_nav is not None:
            log.warning("nav intent overwritten: %s -> %s",
                        self._pending_nav.name, nav.name)
        self._pending_nav = nav
        log.debug("nav queued %s", nav.name)

    def _execute_pending_nav(self):
        if self._pending_nav is None:
            return
        nav = self._pending_nav
        self._pending_nav = None
        self.switch_to(nav.name, **nav.payload)

    def _on_back_to_menu(self):
        pending_result = self.game.current_result()
        if pending_result is not None:
            self.game.result_flow._finalize_result(pending_result)
        keep_online = (self.game.variant == "online" and self.coordinator.client is not None
                       and self.game.current_result() is not None)
        had_rematch_offer = self.coordinator._rematch_offered
        self.switch_to("menu")
        self.game._match_session_id = None
        self.coordinator._reconnect_probe_attempts = 0
        self.coordinator.retain_for_rematch(keep_online)
        self.game.variant = "local"
        self.game.match.local_color = None
        self.game.match.on_local_move_applied = None
        self.game.right_menu.set_game_info(None)
        self.game.result_menu.set_online_mode(False)
        self.game._first_move_deadline_ms = None
        self.game._opp_disconnected_at_ms = None
        self.game._local_disconnected_at_ms = None
        self.coordinator._prev_online_state = None
        self.game._reset_to_new_game()
        self._refresh_load_pgn_availability()
        if keep_online and had_rematch_offer:
            self.coordinator._reshow_rematch_banner()

    def _on_new_game(self):
        if self.game.variant == "local":
            self.game._chosen_side = (
                "black" if self.game._chosen_side == "white" else "white")
            self.game.white_name, self.game.black_name = (
                self.game.black_name, self.game.white_name)
            self.game.white_country, self.game.black_country = (
                self.game.black_country, self.game.white_country)
        self.game._reset_to_new_game()
        self.sound_manager.play_game_start()

    def _on_help(self):
        self.help_modal.show(HOTKEYS)

    def _refresh_load_pgn_availability(self):
        self.start_menu.load_pgn_available = self._latest_pgn_path() is not None

    def _latest_pgn_path(self):
        return latest_pgn_in_dir(_games_dir())

    def _on_open_history(self):
        self.history_view.show(
            _games_dir(), "*.pgn",
            on_open=self._open_pgn_review,
            nickname=env.get_nickname(),
        )
        self.request_nav(Nav("history"))

    def _on_menu_back(self):
        self.history_view.hide()
        self.request_nav(Nav("menu"))

    def _on_open_fen_modal(self):
        self.menu.fen_input_modal.show(on_submit=self._start_game_from_fen)

    def _start_game_from_fen(self, fen):
        try:
            apply_fen(Backend(), fen)
        except (ValueError, KeyError):
            return False
        self.game.match.local_color = None
        self.coordinator._drop_post_game_online_session()
        self.request_nav(Nav("game", {"fen": fen}))
        self._execute_pending_nav()
        self.menu.fen_input_modal.hide()
        self.start_menu.hide()
        return True

    def _open_pgn_review(self, path):
        self.request_nav(Nav("review", {"pgn_path": str(path), "return_to": "history"}))

    def _on_start_game(self, config):
        env.set_last_mode(config["mode"])
        env.set_nickname(config.get("nickname") or "")
        if config["mode"] == ONLINE:
            self.coordinator._begin_online_flow(config)
            return
        if config["mode"] != SINGLE_SCREEN:
            return

        side = config["side"]
        if side == "random":
            side = random.choice(["white", "black"])

        self.game.match.local_color = None
        self.coordinator._drop_post_game_online_session()

        log.info("game start mode=%s side=%s tc=%s+%s",
                 config["mode"], side, config["time_minutes"], config["increment_seconds"])
        self.request_nav(Nav("game", {
            "side": side,
            "nickname": config.get("nickname") or "",
            "time_minutes": config["time_minutes"],
            "increment_seconds": config["increment_seconds"],
        }))
        self._execute_pending_nav()
        self.start_menu.hide()
        self.sound_manager.play_game_start()

    def run(self):
        while self.running:
            frame_start = time.perf_counter()
            if self._last_frame_start is not None:
                self._frame_times.append((frame_start - self._last_frame_start) * 1000.0)
            self._last_frame_start = frame_start
            had_events = self.input_router.check_events()
            self._execute_pending_nav()
            self.draw_frame()
            self._execute_pending_nav()
            self.chrome.draw(self._chrome_stats())
            work_before_present = time.perf_counter() - frame_start
            self.clock.tick(self.target_fps)
            present_start = time.perf_counter()
            self._present(had_events)
            self._last_work_ms = (
                work_before_present + time.perf_counter() - present_start) * 1000.0

        for screen in self.screens.values():
            screen.on_app_exit()
        self.coordinator.on_app_exit()
        self.settings._flush_deferred_env_writes(force=True)
        self.chrome.shutdown()
        cache.clear_all()
        pg.quit()

    def _chrome_stats(self):
        parts = []
        need_sorted = env.get_show_frame_stats() or env.get_show_1pct_low()
        ordered = sorted(self._frame_times) if need_sorted and self._frame_times else []
        if env.get_show_fps():
            parts.append(f"FPS {int(self.clock.get_fps())}")
        if env.get_show_frame_stats() and ordered:
            avg = sum(ordered) / len(ordered)
            parts.append(f"AVG {1000.0 / avg:.0f}")
            parts.append(f"MIN {1000.0 / ordered[-1]:.0f}")
        if env.get_show_1pct_low() and len(ordered) >= PERF_1PCT_MIN_SAMPLES:
            p99 = ordered[int(len(ordered) * PERF_1PCT_PERCENTILE) - 1]
            parts.append(f"1%LOW {1000.0 / p99:.0f}")
        if env.get_show_frametime():
            parts.append(f"FRAME {self._last_work_ms:.1f}ms")
        if env.get_show_ping():
            ping = (self.coordinator.client.get_ping_ms()
                    if self.coordinator.client is not None else None)
            parts.append(f"PING {ping}ms" if ping is not None else "PING —")
        return parts

    def _present(self, had_events):
        rects = self._present_rects(had_events)
        if rects is None:
            pg.display.flip()
        else:
            pg.display.update(rects)

    def _needs_full_redraw(self, had_events):
        return (had_events or self._needs_full_present or self._blocking_modal_visible()
                or self.toast.is_visible() or not self.coordinator.offer_banners.is_empty()
                or self.screen.dirty_rects() is None)

    def _present_rects(self, had_events):
        if self._needs_full_redraw(had_events):
            self._needs_full_present = False
            return None
        return [pg.Rect(0, 0, self.window_width, self.chrome.HEIGHT)] + self.screen.dirty_rects()

    def _active_modal_specs(self):
        return list(self._modal_registry) + self.screen.modals()

    def _blocking_modal_visible(self):
        return any(spec.obj.is_visible() for spec in self._active_modal_specs())

    def _recreate_window_surface(self, w, h):
        self.window = pg.display.set_mode((w, h), WINDOW_FLAGS)
        self.chrome.window = self.window
        self.chrome.reinit_sdl()

    def _settle_window(self):
        if os.name != "nt" or self.chrome.client_size() is None:
            return
        self._recreate_window_surface(self.window_width, self.window_height)
        self.window_width, self.window_height = self.window.get_size()
        self._compute_layout()

    def _sync_window_surface(self):
        size = self.chrome.client_size() or pg.display.get_window_size()
        win_w = max(size[0], MIN_WINDOW_WIDTH)
        win_h = max(size[1], MIN_WINDOW_HEIGHT)
        if (win_w, win_h) != self.window.get_size():
            if os.environ.get("CHESS_DEBUG_RESIZE"):
                log.debug("resize-sync win32=%s gws=%s surf=%s -> set_mode(%d,%d)",
                          self.chrome.client_size(), pg.display.get_window_size(),
                          self.window.get_size(), win_w, win_h)
            self._recreate_window_surface(win_w, win_h)
            self.window_width = win_w
            self.window_height = win_h
            self.input_router._cancel_all_scroll()
            self.screen.on_resize()
            self._compute_layout()

    def draw_frame(self):
        if os.name == "nt" and not self.chrome.is_fullscreen():
            self._sync_window_surface()

        now = pg.time.get_ticks()
        self.coordinator.update(now)

        self.game.give_time._update_give_time_hold()
        self.settings._flush_deferred_env_writes()

        nav = self.screen.update(now)
        if nav is not None:
            self.request_nav(nav)

        if self.screen.uses_battle_backdrop:
            if self.screen.name == "menu" and not self._prev_screen_used_backdrop:
                self.menu_battle.begin_intro()
            self.menu_battle.update(now)
            self.menu_battle.draw(self.window)
            self.menu_battle.draw_scrim(self.window)
        self._prev_screen_used_backdrop = self.screen.uses_battle_backdrop

        self.screen.draw()

        if self.screen.uses_battle_backdrop:
            self.menu_battle.draw_intro_overlay(self.window)

        self.coordinator.offer_banners.draw(self._banner_rect())
        for spec in reversed(self._active_modal_specs()):
            spec.obj.draw()
        self.toast.draw(
            center_x=self.game.board.rect.centerx if self.screen is self.game else None)
        self.game.skillcheck_overlay.update(now)
        self.game.skillcheck_overlay.draw(self.window)

    def _banner_rect(self):
        if self.screen is not self.menu:
            return self.game.board.rect
        return pg.Rect(0, WindowChrome.HEIGHT, self.window_width,
                       self.window_height - WindowChrome.HEIGHT)

    def _apply_fullscreen(self, enable):
        if enable and not self.chrome.is_fullscreen():
            self._pre_fullscreen_size = self.window.get_size()
        if not self.chrome.apply_fullscreen(enable):
            return False
        self.window = pg.display.get_surface()
        if not enable and self._pre_fullscreen_size is not None:
            w, h = self._pre_fullscreen_size
            self.window = pg.display.set_mode((w, h), WINDOW_FLAGS)
            self.chrome.reinit_sdl()
            self._pre_fullscreen_size = None
        self.chrome.window = self.window
        self.window_width, self.window_height = self.window.get_size()
        self.input_router._cancel_all_scroll()
        self._compute_layout()
        return True

    def _compute_layout(self):
        window_width, window_height = self.window.get_size()
        size = (window_width, window_height)
        if size != getattr(self, "_last_layout_size", None):
            self._last_layout_size = size
            cache.clear_size_keyed()
        board_visible_mode = "game" if self.screen is self.game else "menu"
        r = compute_layout(
            window_width, window_height, mode=board_visible_mode,
            focus_mode=self.game.focus_mode, focus_show=self.game._focus_show(),
            board_size=self.game.board.SIZE)

        self.confirm_modal.set_rect(r.result_modal_rect)
        self.coordinator.wait_modal.set_rect(r.flex_rect)
        self.coordinator.match_found_modal.set_rect(r.flex_rect)
        self.coordinator.reconnecting_modal.set_rect(r.board_rect)
        self.start_menu.set_rect(r.start_rect)
        self.help_modal.set_rect(r.result_rect)
        for screen in self.screens.values():
            screen.relayout(size)
        self.menu_battle.top_inset = r.top
        self.menu_battle.set_rect(r.window_rect)
        self.options_modal.set_rect(r.options_rect)
        self.country_picker.set_rect(r.wide_overlay_rect)
        self.directory_browser.set_rect(r.wide_overlay_rect)
        self._needs_full_present = True
