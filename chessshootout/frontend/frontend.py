import logging
import os
import random
import time
from collections import deque
from typing import Any, cast

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import SINGLE_SCREEN, ONLINE
from chessshootout.backend.backend import Backend
from chessshootout.backend.fen import apply_fen
from chessshootout.backend.utils import BOARD_SIZE
from chessshootout.infra import env
from chessshootout.frontend.menu.menu_battle import MenuBattle
from chessshootout.frontend.panels.history_view import HistoryView
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.confirm import ConfirmModal
from chessshootout.frontend.modals.country_picker import CountryPicker
from chessshootout.frontend.modals.directory_browser import DirectoryBrowser
from chessshootout.frontend.pgn_open import PgnOpener
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


def _stat_slot(label: str, value: int | str, width: int) -> str:
    """
    Format one title-bar readout to a fixed width, so a number that changes
    every frame cannot shuffle the readouts beside it along the bar

    :param label: short name of the readout, such as FPS or PING
    :param value: the number or already-formatted text to show
    :param width: width to pad the whole slot out to, in characters
    :returns: the padded label and value
    """
    return f"{label} {value}".ljust(width)


log = logging.getLogger("chess.frontend")


_WINDOW_ICON_CACHE = cache.new_cache()


def _load_window_icon() -> pg.Surface | None:
    """
    The icon the window and the taskbar show, read from disk only the first
    time it is asked for. A missing or unreadable file is not fatal: the game
    simply runs with the platform's default icon

    :returns: the icon image, or None when it could not be loaded
    """
    def build() -> pg.Surface | None:
        """
        Read the icon file off disk, the miss path of the cache around it

        :returns: the loaded image, or None when the file is missing or
            cannot be read as an image
        """
        try:
            return pg.image.load(str(paths.resource_path("assets", "icons", "icon.png")))
        except (pg.error, OSError):
            return None
    return cache.memoized_surface(_WINDOW_ICON_CACHE, "icon", build)


class Frontend:
    """
    The app shell. It owns the window, the frame loop and whichever screen is
    showing, plus everything the screens share -- sound, toasts, the app-wide
    cards, the online coordinator and the settings. It knows no chess of its
    own: the screens play the game and this drives them
    """

    def __init__(self, window_width: int, window_height: int) -> None:
        """
        Build the entire client: open the window, start the services, create
        every screen once, lay them all out and land on the menu. This runs
        once at launch, and by the time it returns the game is ready to draw

        :param window_width: wanted window width in pixels, raised to the
            minimum the interface needs
        :param window_height: wanted window height in pixels, raised to the
            minimum the interface needs
        """
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
        self._pre_fullscreen_size: tuple[int, int] | None = None
        self.settings = SettingsController(self)
        self.chrome = WindowChrome(self.window, on_fullscreen=self._apply_fullscreen)
        self.pacer = FramePacer(self.target_fps)

        self._needs_full_present = True
        self._last_layout_size: tuple[int, int] | None = None
        self._frame_times: deque[float] = deque(maxlen=PERF_SAMPLE_COUNT)
        self._last_work_ms = 0.0
        self._last_frame_start: float | None = None

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
        self.pgn_opener = PgnOpener(self.toast)
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
        self._pending_nav: Nav | None = None

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

    def switch_to(self, name: str, **payload: Any) -> None:
        """
        Change screens -- the one place in the app where that happens. The
        screen being left exits before the new one enters, the whole window is
        laid out again and the title is refreshed. An unknown name raises
        rather than failing quietly, and switching to the screen already
        showing runs the full exit-then-enter cycle, which is exactly what a
        rematch or a review reload wants

        :param name: registry name of the screen to open
        :param payload: plain-data payload handed to the new screen, checked
            before it is allowed across the boundary
        """
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

    def request_nav(self, nav: Nav) -> None:
        """
        Queue a screen change for the shell to run once the current frame's
        dispatch is finished, which is how a screen asks to be replaced
        without disappearing in the middle of handling its own event. Only one
        can be queued at a time; a second overwrites the first and says so in
        the log

        :param nav: the navigation intent, naming the screen and its payload
        """
        if self._pending_nav is not None:
            log.warning("nav intent overwritten: %s -> %s",
                        self._pending_nav.name, nav.name)
        self._pending_nav = nav
        log.debug("nav queued %s", nav.name)

    def _execute_pending_nav(self) -> None:
        """
        Run the queued screen change, if one is waiting. The frame loop calls
        this after the input dispatch pass and again after drawing, so an
        intent raised anywhere in a frame is honoured before the next begins
        """
        if self._pending_nav is None:
            return
        nav = self._pending_nav
        self._pending_nav = None
        self.switch_to(nav.name, **nav.payload)

    def _on_back_to_menu(self) -> None:
        """
        Leave the game for the menu, behind both the rail's menu button and
        the result card. A result nobody has adopted yet is finalised first so
        the game is still scored and saved, and a finished online game keeps
        its session alive on the way back so a rematch is still possible --
        including an offer already made, whose banner is put up again
        """
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

    def _on_new_game(self) -> None:
        """
        Start another game on the same screen, offered once one has ended. In
        a local game the two players trade sides along with their names and
        countries, so whoever just played black opens the next one
        """
        if self.game.variant == Variant.LOCAL:
            self.game._chosen_side = (
                "black" if self.game._chosen_side == "white" else "white")
            self.game.white_name, self.game.black_name = (
                self.game.black_name, self.game.white_name)
            self.game.white_country, self.game.black_country = (
                self.game.black_country, self.game.white_country)
        self.game._reset_to_new_game()
        self.sound_manager.play_game_start()

    def _on_help(self) -> None:
        """
        Open the help card with the full list of keyboard and mouse controls
        """
        self.help_modal.show(HOTKEYS)

    def _on_open_fen_modal(self) -> None:
        """
        Open the card for pasting a position, so a game can start from a
        given FEN instead of the normal opening position
        """
        self.menu.fen_input_modal.show(on_submit=self._start_game_from_fen)

    def _start_game_from_fen(self, fen: str) -> bool:
        """
        Start a local game from a pasted position, but only after checking the
        text really is a position the engine can set up. A bad FEN is refused
        so the card can keep the text and say so, rather than dropping the
        player into a broken game

        :param fen: the position as typed, in FEN notation
        :returns: True when the game started, False when the text was rejected
        """
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

    def _open_pgn_review(self, path: str) -> None:
        """
        Open a saved game for review, behind both a row in the History list
        and the recent-games card. Closing the review returns to the menu

        :param path: full path of the PGN file to open
        """
        self.request_nav(Nav("review", {"pgn_path": str(path), "return_to": "menu"}))

    def _on_start_game(self, config: dict[str, Any]) -> None:
        """
        Act on the Play panel's start button. The chosen mode and nickname are
        stored first so the next launch opens the same way; an online game
        then hands over to the coordinator to go and find an opponent, while a
        local one settles the side -- resolving a random pick here -- and
        opens the game screen straight away

        :param config: the Play panel's settings: mode, nickname, side and the
            time control as minutes plus increment seconds
        """
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

    def run(self) -> None:
        """
        The game's main loop, entered once at launch and left only when the
        player quits. Every pass pumps input, runs whatever screen change that
        asked for, draws the frame, waits out the frame budget and presents.
        On the way out each screen gets to flush unsaved work first, before
        the online connection is dropped and pygame is shut down
        """
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

    def _current_fps(self) -> float:
        """
        The frame rate over the last handful of frames, for the title-bar
        readout. Averaged over a short window so the number stays readable
        instead of flickering with every frame

        :returns: frames per second, 0.0 until enough frames have been timed
        """
        recent = list(self._frame_times)[-10:]
        if len(recent) < 2:
            return 0.0
        avg = sum(recent) / len(recent)
        return 1000.0 / avg

    def _chrome_stats(self) -> list[str]:
        """
        Build the performance readouts across the title bar, each switched on
        separately in Options: frame rate, its average and worst, the 1% low
        that exposes stutter, render time per frame, and the ping to the
        server. All of them are off by default, so most runs build nothing

        :returns: the readouts to draw, in order, empty when all are off
        """
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

    def _present(self, had_events: bool) -> None:
        """
        Push the finished frame to the display, either the whole window or
        only the regions that changed

        :param had_events: True when this frame processed input, which forces
            a full present
        """
        rects = self._present_rects(had_events)
        if rects is None:
            pg.display.flip()
        else:
            pg.display.update(rects)

    def _needs_full_redraw(self, had_events: bool) -> bool:
        """
        Decide whether this frame has to be presented whole. Anything drawn
        over the screen -- a modal, a toast, an animating offer banner --
        forces it, as does input this frame and a screen that cannot say which
        regions it touched

        :param had_events: True when this frame processed input
        :returns: True when the whole window must be presented
        """
        return (had_events or self._needs_full_present or self._blocking_modal_visible()
                or self.toast.is_visible() or self.coordinator.offer_banners.needs_frames()
                or self.screen.dirty_rects() is None)

    def _present_rects(self, had_events: bool) -> list[pg.Rect] | None:
        """
        Work out which regions of the window to present. Where a partial
        present is safe the title bar always goes along with whatever the
        screen reported, since its readouts can change every frame

        :param had_events: True when this frame processed input
        :returns: rects to present, or None to present the whole window
        """
        if self._needs_full_redraw(had_events):
            self._needs_full_present = False
            return None
        return ([pg.Rect(0, 0, self.window_width, self.chrome.HEIGHT)]
                + cast(list[pg.Rect], self.screen.dirty_rects()))

    def _active_modal_specs(self) -> list[ModalSpec]:
        """
        The app's modals as one merged list: the shell's global ones first,
        then the active screen's. That single order answers Esc and clicks
        alike, and drawing walks it backwards so the global ones land on top.
        Nothing anywhere else may hand-order modals

        :returns: every live modal spec, topmost first
        """
        return list(self._modal_registry) + self.screen.modals()

    def _blocking_modal_visible(self) -> bool:
        """
        Whether anything modal is open, which is what stops presses and hover
        from reaching the screen underneath

        :returns: True while any global or screen modal is showing
        """
        return any(spec.modal.is_visible() for spec in self._active_modal_specs())

    def _recreate_window_surface(self, w: int, h: int) -> None:
        """
        Replace the drawing surface at a new size and point the chrome at the
        new one, which also reinstalls the borderless window's drag and resize
        handling

        :param w: new surface width in pixels
        :param h: new surface height in pixels
        """
        self.window = pg.display.set_mode((w, h), WINDOW_FLAGS)
        self.chrome.window = self.window
        self.chrome.reinit_sdl()

    def _finish_resize(self, w: int, h: int) -> None:
        """
        Settle the app after the window has changed size: record the new size,
        cancel every scroll that was mid-drag over content which has just
        moved, and lay the whole interface out again

        :param w: new window width in pixels
        :param h: new window height in pixels
        """
        self.window_width = w
        self.window_height = h
        self.input_router._cancel_all_scroll()
        self._compute_layout()

    def _settle_window(self) -> None:
        """
        On Windows, reconcile the drawing surface with the size the borderless
        window really ended up at during startup, which can differ from the
        size that was asked for. A no-op on every other platform
        """
        if os.name != "nt" or self.chrome.client_size() is None:
            return
        self._recreate_window_surface(self.window_width, self.window_height)
        self.window_width, self.window_height = self.window.get_size()
        self._compute_layout()

    def _sync_window_surface(self) -> None:
        """
        Keep the drawing surface the same size as the borderless window while
        it is being dragged by an edge on Windows, where resize events do not
        arrive during the drag. Checked every frame, acted on only once the
        two have actually drifted apart
        """
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

    def draw_frame(self) -> None:
        """
        Draw one whole frame, bottom layer to top. The online coordinator is
        stepped before the screen is, so a move that just arrived from the
        opponent is already applied when the screen updates and a queued
        premove can answer it in the same frame. Then come the menu backdrop
        where a screen asks for one, the screen itself, the offer banners, the
        modals, the toast, and the skill-check overlay last of all
        """
        if os.name == "nt" and not self.chrome.is_fullscreen():
            self._sync_window_surface()

        now = pg.time.get_ticks()
        self.coordinator.update(now)

        self.game.give_time.update_give_time_hold()
        self.settings._flush_deferred_env_writes()
        self.pgn_opener.update()

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

    def _banner_rect(self) -> pg.Rect:
        """
        Where the offer banners -- draw, takeback and rematch -- are laid out.
        Over the board during a game, so an offer appears where the player is
        already looking, and over the whole content area anywhere else

        :returns: the rect the banners position themselves inside
        """
        if self.screen is self.game:
            return self.game.board.rect
        return pg.Rect(0, WindowChrome.HEIGHT, self.window_width,
                       self.window_height - WindowChrome.HEIGHT)

    def _apply_launch_mode(self) -> None:
        """
        Open the window the way the player asked for it in Options --
        windowed, maximised or fullscreen -- applied once during startup
        """
        mode = env.get_launch_mode()
        if mode == "fullscreen":
            self.chrome.toggle_fullscreen()
        elif mode == "maximized":
            self._maximize_window()

    def _maximize_window(self) -> None:
        """
        Fill the desktop with the window while keeping its title bar. The
        system is asked to maximise it properly; where that is not available
        the surface is simply grown to the desktop size instead
        """
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

    def _settle_maximized(self) -> None:
        """
        Match the drawing surface to the size the system actually gave the
        maximised window, which is only knowable once it has been maximised
        """
        size = self.chrome.client_size()
        if size is None:
            return
        w = max(size[0], MIN_WINDOW_WIDTH)
        h = max(size[1], MIN_WINDOW_HEIGHT)
        self._recreate_window_surface(w, h)
        self._finish_resize(*self.window.get_size())

    def _apply_fullscreen(self, enable: bool) -> bool:
        """
        Go into or come out of fullscreen. The windowed size is remembered on
        the way in so leaving restores exactly that rather than guessing, and
        the interface is laid out again at the new size before this returns

        :param enable: True to go fullscreen, False to return to a window
        :returns: True when the change was made
        """
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

    def _compute_layout(self) -> None:
        """
        Lay the whole app out for the window as it is now: the app-wide rects
        and the modal slots, then every screen in turn, the hidden ones
        included so none of them is ever caught with stale geometry. Run at
        startup, on every window resize and on every screen switch. A size
        that really changed also clears the caches keyed by size, since every
        surface in them was drawn for the old one
        """
        window_width, window_height = self.window.get_size()
        size = (window_width, window_height)
        if size != self._last_layout_size:
            self._last_layout_size = size
            cache.clear_size_keyed()
        board_visible_mode = "game" if self.screen is self.game else "menu"
        r = compute_layout(
            window_width, window_height, mode=board_visible_mode,
            focus_mode=self.game.focus_mode, focus_show=self.game._focus_show(),
            board_size=BOARD_SIZE)

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
