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
from chessshootout.frontend.menu.menu_battle import MenuBattle
from chessshootout.frontend.panels.history_view import HistoryView
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.confirm import ConfirmModal
from chessshootout.frontend.modals.country_picker import CountryPicker
from chessshootout.frontend.modals.directory_browser import DirectoryBrowser
from chessshootout.frontend.settings import SettingsController
from chessshootout.frontend.modals.help import HelpModal, HOTKEYS
from chessshootout.frontend.visual.toast import Toast
from chessshootout.frontend.visual import cache
from chessshootout.frontend.frame_pacer import FramePacer
from chessshootout.frontend.input_router import InputRouter
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.screens.base import Nav, assert_plain_payload
from chessshootout.frontend.screens.menu import MenuScreen
from chessshootout.frontend.screens.game import GameScreen
from chessshootout.frontend.screens.review import ReviewScreen
from chessshootout.frontend.window_chrome import (
    WindowChrome, WINDOW_FLAGS, WINDOW_TITLE, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.online_coordinator import OnlineCoordinator
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.online.news import NewsClient


PERF_SAMPLE_COUNT = 240
PERF_1PCT_PERCENTILE = 0.99
PERF_1PCT_MIN_SAMPLES = 100
STAT_SLOT_FPS = 7
STAT_SLOT_1PCT = 9
STAT_SLOT_FRAME = 13
STAT_SLOT_PING = 10

KEY_REPEAT_DELAY_MS = 400
KEY_REPEAT_INTERVAL_MS = 35


def _stat_slot(label, value, width):
    return f"{label} {value}".ljust(width)


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
        pg.key.set_repeat(KEY_REPEAT_DELAY_MS, KEY_REPEAT_INTERVAL_MS)
        icon = _load_window_icon()
        if icon is not None:
            pg.display.set_icon(icon)
        self._pre_fullscreen_size = None
        self.settings = SettingsController(self)
        self.chrome = WindowChrome(self.window, on_fullscreen=self._apply_fullscreen)
        self.pacer = FramePacer(self.target_fps)

        self._needs_full_present = True
        self._frame_times = deque(maxlen=PERF_SAMPLE_COUNT)
        self._last_work_ms = 0.0
        self._last_frame_start = None

        self.sound_manager = SoundManager(paths.SOUNDS_DIR, enabled=pg.mixer.get_init() is not None)
        self.coordinator = OnlineCoordinator(self)
        self.confirm_modal = ConfirmModal(self.window)
        self.history_view = HistoryView(self.window, on_open=self._open_pgn_review)
        self.help_modal = HelpModal(self.window)
        self.country_picker = CountryPicker(self.window)
        self.directory_browser = DirectoryBrowser(self.window)
        self.toast = Toast(self.window)
        self.toast.top_inset = self.chrome.HEIGHT
        self.toast.on_new = lambda: self.sound_manager.play_toast()
        if env.normalize_stored_nickname():
            self.toast.show("Your nickname contained non ASCII symbols, I cleaned them :3")
        if not env.get_profile_hint_shown():
            env.set_profile_hint_shown()
            self.toast.show("Set your name in Profile >", kind="hype")
        self.news_client = NewsClient()
        self.input_router = InputRouter(self)
        self._modal_registry = [
            ModalSpec(self.confirm_modal, on_dismiss=self.input_router._dismiss_confirm),
            ModalSpec(self.coordinator.wait_modal, on_dismiss=self.coordinator._on_online_cancel),
            ModalSpec(self.coordinator.match_found_modal, esc_dismiss=False),
            ModalSpec(self.coordinator.reconnecting_modal, esc_dismiss=False),
            ModalSpec(self.country_picker),
            ModalSpec(self.directory_browser),
        ]
        self.menu_battle = MenuBattle(sound_manager=self.sound_manager)
        self._pending_nav = None

        self.menu = MenuScreen(self)
        self.game = GameScreen(self)
        self.review = ReviewScreen(self)
        self.screens = {
            "menu": self.menu,
            "game": self.game,
            "review": self.review,
        }
        self.screen = self.screens["menu"]

        self._apply_launch_mode()
        self.game.board.load_assets()
        self.review.board.load_assets()
        self._compute_layout()
        self._settle_window()
        self.coordinator._spawn_reconnect_probe()
        self.news_client.fetch_once()

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
            self.game.result_flow.finalize_result(pending_result)
        keep_online = (self.game.variant == Variant.ONLINE
                       and self.coordinator.is_connected()
                       and self.game.current_result() is not None)
        had_rematch_offer = self.coordinator._rematch_offered
        self.switch_to("menu")
        self.game._match_session_id = None
        self.coordinator._reconnect_probe_attempts = 0
        self.coordinator.retain_for_rematch(keep_online)
        self.coordinator.unbind_game_from_online()
        self.game._reset_to_new_game()
        if keep_online and had_rematch_offer:
            self.coordinator._reshow_rematch_banner()

    def _on_new_game(self):
        if self.game.variant == Variant.LOCAL:
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
        self.menu.hide_play_view()
        return True

    def _open_pgn_review(self, path):
        self.request_nav(Nav("review", {"pgn_path": str(path), "return_to": "menu"}))

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
        self.menu.hide_play_view()
        self.sound_manager.play_game_start()

    def run(self):
        self.menu.enter()
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
            self.pacer.wait()
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

    def _current_fps(self):
        recent = list(self._frame_times)[-10:]
        if len(recent) < 2:
            return 0.0
        avg = sum(recent) / len(recent)
        return 1000.0 / avg

    def _chrome_stats(self):
        parts = []
        need_sorted = env.get_show_frame_stats() or env.get_show_1pct_low()
        ordered = sorted(self._frame_times) if need_sorted and self._frame_times else []
        if env.get_show_fps():
            parts.append(_stat_slot("FPS", int(self._current_fps()), STAT_SLOT_FPS))
        if env.get_show_frame_stats() and ordered:
            avg = sum(ordered) / len(ordered)
            parts.append(_stat_slot("AVG", f"{1000.0 / avg:.0f}", STAT_SLOT_FPS))
            parts.append(_stat_slot("MIN", f"{1000.0 / ordered[-1]:.0f}", STAT_SLOT_FPS))
        if env.get_show_1pct_low() and len(ordered) >= PERF_1PCT_MIN_SAMPLES:
            p99 = ordered[int(len(ordered) * PERF_1PCT_PERCENTILE) - 1]
            parts.append(_stat_slot("1%LOW", f"{1000.0 / p99:.0f}", STAT_SLOT_1PCT))
        if env.get_show_frametime():
            parts.append(_stat_slot("FRAME", f"{self._last_work_ms:.1f}ms", STAT_SLOT_FRAME))
        if env.get_show_ping():
            ping = self.coordinator.ping_ms()
            value = f"{ping}ms" if ping is not None else "—"
            parts.append(_stat_slot("PING", value, STAT_SLOT_PING))
        return parts

    def _present(self, had_events):
        rects = self._present_rects(had_events)
        if rects is None:
            pg.display.flip()
        else:
            pg.display.update(rects)

    def _needs_full_redraw(self, had_events):
        return (had_events or self._needs_full_present or self._blocking_modal_visible()
                or self.toast.is_visible() or self.coordinator.offer_banners.needs_frames()
                or self.screen.dirty_rects() is None)

    def _present_rects(self, had_events):
        if self._needs_full_redraw(had_events):
            self._needs_full_present = False
            return None
        return [pg.Rect(0, 0, self.window_width, self.chrome.HEIGHT)] + self.screen.dirty_rects()

    def _active_modal_specs(self):
        return list(self._modal_registry) + self.screen.modals()

    def _blocking_modal_visible(self):
        return any(spec.modal.is_visible() for spec in self._active_modal_specs())

    def _recreate_window_surface(self, w, h):
        self.window = pg.display.set_mode((w, h), WINDOW_FLAGS)
        self.chrome.window = self.window
        self.chrome.reinit_sdl()

    def _finish_resize(self, w, h):
        self.window_width = w
        self.window_height = h
        self.input_router._cancel_all_scroll()
        self._compute_layout()

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
            self.screen.on_resize()
            self._finish_resize(win_w, win_h)

    def draw_frame(self):
        if os.name == "nt" and not self.chrome.is_fullscreen():
            self._sync_window_surface()

        now = pg.time.get_ticks()
        self.coordinator.update(now)

        self.game.give_time.update_give_time_hold()
        self.settings._flush_deferred_env_writes()

        nav = self.screen.update(now)
        if nav is not None:
            self.request_nav(nav)

        if self.screen.uses_battle_backdrop:
            self.menu_battle.update(now)
            self.menu_battle.draw(self.window)
            self.menu_battle.draw_scrim(self.window)

        self.screen.draw()

        self.coordinator.offer_banners.draw(self._banner_rect())
        for spec in reversed(self._active_modal_specs()):
            spec.modal.draw()
        self.toast.draw(
            center_x=self.game.board.rect.centerx if self.screen is self.game else None)
        self.game.skillcheck_overlay.update(now)
        self.game.skillcheck_overlay.draw(self.window)

    def _banner_rect(self):
        if self.screen is self.game:
            return self.game.board.rect
        return pg.Rect(0, WindowChrome.HEIGHT, self.window_width,
                       self.window_height - WindowChrome.HEIGHT)

    def _apply_launch_mode(self):
        mode = env.get_launch_mode()
        if mode == "fullscreen":
            self.chrome.toggle_fullscreen()
        elif mode == "maximized":
            self._maximize_window()

    def _maximize_window(self):
        if self.chrome.maximize():
            self._settle_maximized()
            return
        sizes = pg.display.get_desktop_sizes()
        if not sizes:
            return
        w = max(sizes[0][0], MIN_WINDOW_WIDTH)
        h = max(sizes[0][1], MIN_WINDOW_HEIGHT)
        self._recreate_window_surface(w, h)
        self.window_width, self.window_height = self.window.get_size()

    def _settle_maximized(self):
        size = self.chrome.client_size()
        if size is None:
            return
        w = max(size[0], MIN_WINDOW_WIDTH)
        h = max(size[1], MIN_WINDOW_HEIGHT)
        self._recreate_window_surface(w, h)
        self._finish_resize(*self.window.get_size())

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
        self._finish_resize(*self.window.get_size())
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
        self.help_modal.set_rect(r.result_rect)
        for screen in self.screens.values():
            screen.relayout(size)
        self.menu_battle.top_inset = r.top
        self.menu_battle.set_rect(r.window_rect)
        self.country_picker.set_rect(r.wide_overlay_rect)
        self.directory_browser.set_rect(r.wide_overlay_rect)
        self._needs_full_present = True
