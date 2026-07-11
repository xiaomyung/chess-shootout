import glob
import logging
import os
import random
import time
import uuid
from collections import deque

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import SINGLE_SCREEN, ONLINE
from chessshootout.backend.backend import Backend
from chessshootout.backend.fen import apply_fen
from chessshootout.infra import env
from chessshootout.frontend.panels.audio import AudioPanel
from chessshootout.skillcheck.online import SKILLCHECK_DEADLINE_MS
from chessshootout.frontend.menu.menu_battle import MenuBattle
from chessshootout.frontend.menu.history import HistoryView
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.confirm import ConfirmModal
from chessshootout.frontend.modals.directory_browser import DirectoryBrowser
from chessshootout.frontend.modals.country_picker import CountryPicker
from chessshootout.frontend.modals.fen_input import FenInputModal
from chessshootout.frontend.modals.options import OptionsModal
from chessshootout.frontend.settings import SettingsController
from chessshootout.frontend.modals.help import HelpModal
from chessshootout.frontend.modals.reconnecting import ReconnectingModal
from chessshootout.frontend.visual.toast import Toast
from chessshootout.frontend.visual import cache
from chessshootout.frontend.input_router import InputRouter
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.screens.base import Nav, assert_plain_payload
from chessshootout.frontend.screens.menu import MenuScreen
from chessshootout.frontend.screens.game import GameScreen
from chessshootout.frontend.screens.history import HistoryScreen
from chessshootout.frontend.window_chrome import (
    WindowChrome, WINDOW_FLAGS, WINDOW_TITLE, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from chessshootout.online.client import OnlineClient, RECONNECT_TOTAL_SECONDS
from chessshootout.frontend.online.events import REMATCH_STATE_TOAST_KEY, OnlineEventsMixin
from chessshootout.frontend.reconnect_probe import ReconnectProbe
from chessshootout.frontend.result_flow import _open_with_default_app
from chessshootout.frontend.panels.player_strip import AUTO_END_RED_THRESHOLD_SECONDS
from chessshootout.frontend.modals.wait import WaitModal
from chessshootout.frontend.modals.match_found import MatchFoundModal
from chessshootout.frontend.online.banners import OfferBanners
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.modals.start import StartMenu
from chessshootout.domain.pgn.load import load_pgn_into_backend, parse_time_control
from chessshootout.paths import SOUNDS_DIR
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS


PERF_SAMPLE_COUNT = 240
PERF_1PCT_PERCENTILE = 0.99
PERF_1PCT_MIN_SAMPLES = 100
PRESENT_SETTLE_MS = 120

FOCUS_HINT_MS = 1600

RESYNC_TIMEOUT_MS = 8000
SKILLCHECK_WATCHDOG_SLACK_MS = 4000
RECONNECT_MODAL_DEBOUNCE_MS = 500

ONLINE_DEFAULT_TIME_MINUTES = 5


def _games_dir():
    return str(paths.get_games_dir())


log = logging.getLogger("chess.frontend")


class Frontend(OnlineEventsMixin):

    def __init__(self, window_width: int, window_height: int):
        self.running = True
        self.target_fps = 300
        self.window_width = max(window_width, MIN_WINDOW_WIDTH)
        self.window_height = max(window_height, MIN_WINDOW_HEIGHT)
        self.window = pg.display.set_mode(
            (self.window_width, self.window_height), WINDOW_FLAGS)
        pg.key.set_repeat(400, 35)
        try:
            icon = pg.image.load(str(paths.resource_path("assets", "icons", "icon.png")))
            pg.display.set_icon(icon)
        except (pg.error, OSError):
            pass
        self._pre_fullscreen_size = None
        self.settings = SettingsController(self)
        self.chrome = WindowChrome(self.window, on_fullscreen=self._apply_fullscreen)
        self.clock = pg.time.Clock()

        self.mode = "menu"
        self._online_config = None
        self._needs_full_present = True
        self._frame_times = deque(maxlen=PERF_SAMPLE_COUNT)
        self._last_work_ms = 0.0
        self._last_frame_start = None
        self._resyncing = False
        self._resync_started_at_ms = 0
        self._last_heartbeat_sent_ms = 0
        self._review_return_page = None
        self._prev_screen_used_backdrop = False
        self._focus_prev_mode = "menu"

        self.sound_manager = SoundManager(SOUNDS_DIR, enabled=pg.mixer.get_init() is not None)
        self.reconnect_probe = ReconnectProbe(self)
        self.start_menu = StartMenu(self.window, {
            "start_game": self._on_start_game,
            "load_pgn": self._on_open_history,
            "fen": self._on_open_fen_modal,
            "reconnect": self.reconnect_probe._on_reconnect_active_game,
            "options": self.settings._on_open_options,
            "open_url": _open_with_default_app,
            "toast": lambda msg: self.toast.show(msg),
        })
        self.audio_panel = AudioPanel(self.window, self.sound_manager)
        self.confirm_modal = ConfirmModal(self.window)
        self.history_view = HistoryView(self.window, on_open=self._load_pgn_from_path,
                                        on_back=self._on_menu_back)
        self.help_modal = HelpModal(self.window)
        self.fen_input_modal = FenInputModal(self.window)
        self.options_modal = OptionsModal(self.window)
        self.directory_browser = DirectoryBrowser(self.window)
        self.country_picker = CountryPicker(self.window)
        self.toast = Toast(self.window)
        self.toast.top_inset = self.chrome.HEIGHT
        self.toast.on_new = lambda: self.sound_manager.play_toast()
        if env.normalize_stored_nickname():
            self.start_menu.text_input.text = env.get_nickname()
            self.toast.show("Your nickname contained non ASCII symbols, I cleaned them :3")
        self.wait_modal = WaitModal(self.window)
        self.match_found_modal = MatchFoundModal(self.window)
        self.reconnecting_modal = ReconnectingModal(self.window)
        self.offer_banners = OfferBanners(self.window)
        self.input_router = InputRouter(self)
        self._modal_registry = [
            ModalSpec(self.confirm_modal, on_dismiss=self.input_router._dismiss_confirm),
            ModalSpec(self.help_modal),
            ModalSpec(self.fen_input_modal),
            ModalSpec(self.wait_modal, on_dismiss=self._on_online_cancel),
            ModalSpec(self.match_found_modal, esc_dismiss=False),
            ModalSpec(self.reconnecting_modal, esc_dismiss=False),
            ModalSpec(self.country_picker),
            ModalSpec(self.directory_browser),
            ModalSpec(self.options_modal, on_dismiss=self.settings._dismiss_options),
        ]
        self._wait_started_at_ms = None
        self._match_found_at_ms = None
        self._pending_game_start_payload = None
        self._rematch_offered = False
        self.online_client = None
        self.menu_battle = MenuBattle(self.window, sound_manager=self.sound_manager)
        self._pending_nav = None

        self.menu = MenuScreen(self)
        self.game = GameScreen(self)
        self.history = HistoryScreen(self)
        self.screens = {
            "menu": self.menu,
            "game": self.game,
            "history": self.history,
        }
        self.screen = self.screens["menu"]

        self.game.board.load_assets()
        self._compute_layout()
        self._refresh_load_pgn_availability()
        self._settle_window()
        self.reconnect_probe._spawn_reconnect_probe()

        pg.display.set_caption(WINDOW_TITLE)

    def switch_to(self, name, **payload):
        if name not in self.screens:
            raise KeyError(f"unknown screen: {name!r}")
        assert_plain_payload(payload)
        screen = self.screens[name]
        mode = payload.get("mode") or screen.legacy_mode or name
        previous = self.screen
        log.info("screen switch %s -> %s mode=%s", previous.name, name, mode)
        previous.exit()
        log.debug("screen exited %s", previous.name)
        self.screen = screen
        self.mode = mode
        screen.enter(**payload)
        log.debug("screen entered %s payload_keys=%s", name, sorted(payload))
        self._compute_layout()

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

    # -- transitional bridge: delegates to the owning GameScreen for modules that
    # haven't been migrated yet (OnlineEventsMixin, input_router, layout, modals).
    # Dies across steps 5-6 as those callers move to app.game.X directly.
    @property
    def match(self):
        return self.game.match

    @property
    def board(self):
        return self.game.board

    @property
    def right_menu(self):
        return self.game.right_menu

    @property
    def result_menu(self):
        return self.game.result_menu

    @property
    def player_strip_top(self):
        return self.game.player_strip_top

    @property
    def player_strip_bottom(self):
        return self.game.player_strip_bottom

    @property
    def result_flow(self):
        return self.game.result_flow

    @property
    def skillcheck_session(self):
        return self.game.skillcheck_session

    @property
    def give_time(self):
        return self.game.give_time

    @property
    def skillcheck(self):
        return self.game.skillcheck

    @property
    def skillcheck_overlay(self):
        return self.game.skillcheck_overlay

    @property
    def focus_mode(self):
        return self.game.focus_mode

    @focus_mode.setter
    def focus_mode(self, value):
        self.game.focus_mode = value

    @property
    def focus_transition(self):
        return self.game.focus_transition

    @property
    def focus_arrow(self):
        return self.game.focus_arrow

    @property
    def time_line(self):
        return self.game.time_line

    @property
    def white_name(self):
        return self.game.white_name

    @white_name.setter
    def white_name(self, value):
        self.game.white_name = value

    @property
    def black_name(self):
        return self.game.black_name

    @black_name.setter
    def black_name(self, value):
        self.game.black_name = value

    @property
    def white_country(self):
        return self.game.white_country

    @white_country.setter
    def white_country(self, value):
        self.game.white_country = value

    @property
    def black_country(self):
        return self.game.black_country

    @black_country.setter
    def black_country(self, value):
        self.game.black_country = value

    @property
    def _chosen_side(self):
        return self.game._chosen_side

    @_chosen_side.setter
    def _chosen_side(self, value):
        self.game._chosen_side = value

    @property
    def _time_control(self):
        return self.game._time_control

    @_time_control.setter
    def _time_control(self, value):
        self.game._time_control = value

    @property
    def pgn_review(self):
        return self.game.pgn_review

    @pgn_review.setter
    def pgn_review(self, value):
        self.game.pgn_review = value

    @property
    def manual_result(self):
        return self.game.manual_result

    @manual_result.setter
    def manual_result(self, value):
        self.game.manual_result = value

    @property
    def _flag_fall_played(self):
        return self.game._flag_fall_played

    @_flag_fall_played.setter
    def _flag_fall_played(self, value):
        self.game._flag_fall_played = value

    @property
    def _result_first_seen_at_ms(self):
        return self.game._result_first_seen_at_ms

    @_result_first_seen_at_ms.setter
    def _result_first_seen_at_ms(self, value):
        self.game._result_first_seen_at_ms = value

    @property
    def _pgn_result_tag(self):
        return self.game._pgn_result_tag

    @_pgn_result_tag.setter
    def _pgn_result_tag(self, value):
        self.game._pgn_result_tag = value

    @property
    def _match_session_id(self):
        return self.game._match_session_id

    @_match_session_id.setter
    def _match_session_id(self, value):
        self.game._match_session_id = value

    @property
    def _first_move_deadline_ms(self):
        return self.game._first_move_deadline_ms

    @_first_move_deadline_ms.setter
    def _first_move_deadline_ms(self, value):
        self.game._first_move_deadline_ms = value

    @property
    def _opp_disconnected_at_ms(self):
        return self.game._opp_disconnected_at_ms

    @_opp_disconnected_at_ms.setter
    def _opp_disconnected_at_ms(self, value):
        self.game._opp_disconnected_at_ms = value

    @property
    def _local_disconnected_at_ms(self):
        return self.game._local_disconnected_at_ms

    @_local_disconnected_at_ms.setter
    def _local_disconnected_at_ms(self, value):
        self.game._local_disconnected_at_ms = value

    @property
    def _prev_online_state(self):
        return self.game._prev_online_state

    @_prev_online_state.setter
    def _prev_online_state(self, value):
        self.game._prev_online_state = value

    @property
    def _focus_hint_until_ms(self):
        return self.game._focus_hint_until_ms

    @_focus_hint_until_ms.setter
    def _focus_hint_until_ms(self, value):
        self.game._focus_hint_until_ms = value

    @property
    def _focus_panel_hover_ms(self):
        return self.game._focus_panel_hover_ms

    @_focus_panel_hover_ms.setter
    def _focus_panel_hover_ms(self, value):
        self.game._focus_panel_hover_ms = value

    def current_result(self):
        return self.game.current_result()

    def result_text(self):
        return self.game.result_text()

    def game_live(self):
        return self.game.game_live()

    def board_interactive(self):
        return self.game.board_interactive()

    def _reset_to_new_game(self):
        self.game._reset_to_new_game()

    def _name_for_color(self, color):
        return self.game._name_for_color(color)

    def _strip_for_color(self, color):
        return self.game._strip_for_color(color)

    def _toggle_focus(self, on):
        self.game._toggle_focus(on)

    def _force_focus_off_instant(self):
        self.game._force_focus_off_instant()

    def _abort_transition_for_resize(self):
        self.game._abort_transition_for_resize()

    def _focus_show(self):
        return self.game._focus_show()

    def _focus_available(self):
        return self.game._focus_available()

    def _focus_arrow_allowed(self):
        return self.game._focus_arrow_allowed()

    def _result_modal_should_show(self):
        return self.game._result_modal_should_show()

    def _result_elapsed_ms(self):
        return self.game._result_elapsed_ms()

    def _draw_result_fade_overlay(self):
        self.game._draw_result_fade_overlay()

    def _skip_result_fade(self):
        self.game._skip_result_fade()

    def _focus_edge_zone_rect(self):
        return self.game._focus_edge_zone_rect()

    def _trigger_result_effects(self):
        self.game._trigger_result_effects()

    def _local_won(self, winner):
        return self.game._local_won(winner)

    def _on_flip(self):
        self.game._on_flip()

    def _on_resign(self):
        self.game._on_resign()

    def _perform_resign(self):
        self.game._perform_resign()

    def _on_draw(self):
        self.game._on_draw()

    def _perform_draw(self):
        self.game._perform_draw()

    def _on_undo(self):
        self.game._on_undo()

    def _on_move_landed(self, entry):
        self.game._on_move_landed(entry)

    def _on_kill_announced(self, key, victim=None):
        self.game._on_kill_announced(key, victim=victim)

    def _update_player_strips(self):
        self.game._update_player_strips()

    def _strip_state(self, color, turn, over):
        return self.game._strip_state(color, turn, over)

    def _strip_capture_summary(self, color):
        return self.game._strip_capture_summary(color)

    def _compute_game_info(self):
        return self.game._compute_game_info()

    def _right_menu_buttons(self):
        return self.game._right_menu_buttons()

    def _right_menu_disabled_keys(self):
        return self.game._right_menu_disabled_keys()

    def _on_new_game(self):
        if self.mode == SINGLE_SCREEN:
            self.game._chosen_side = (
                "black" if self.game._chosen_side == "white" else "white")
            self.game.white_name, self.game.black_name = (
                self.game.black_name, self.game.white_name)
            self.game.white_country, self.game.black_country = (
                self.game.black_country, self.game.white_country)
        self._reset_to_new_game()
        self.sound_manager.play_game_start()

    @property
    def backend(self):
        return self.match.backend

    def phase(self):
        if self.wait_modal.is_visible():
            return "searching"
        if self.match_found_modal.is_visible():
            return "match_found"
        if self.mode == "menu":
            return "menu"
        if self.pgn_review or self.board.read_only:
            return "review"
        if self.current_result() is not None:
            return "finished"
        return "playing"

    def _on_back_to_menu(self):
        if not self.pgn_review:
            pending_result = self.current_result()
            if pending_result is not None:
                self.result_flow._finalize_result(pending_result)
        keep_online = (self.mode == ONLINE and self.online_client is not None
                       and self.current_result() is not None)
        had_rematch_offer = self._rematch_offered
        self.switch_to("menu")
        self._match_session_id = None
        self.reconnect_probe._reconnect_probe_attempts = 0
        pg.display.set_caption(WINDOW_TITLE)
        if keep_online:
            self.online_client.send_left_result()
        elif self.online_client is not None:
            self.online_client.disconnect()
            self.online_client = None
        self.match.mode = SINGLE_SCREEN
        self.match.local_color = None
        self.match.on_local_move_applied = None
        self.right_menu.set_game_info(None)
        self.result_menu.set_online_mode(False)
        self._first_move_deadline_ms = None
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self._prev_online_state = None
        return_screen = self._review_return_page or "menu"
        self._review_return_page = None
        self._reset_to_new_game()
        self._refresh_load_pgn_availability()
        self.start_menu.show()
        if return_screen == "history":
            self._on_open_history()
        if keep_online and had_rematch_offer:
            self._reshow_rematch_banner()

    def _on_help(self):
        self.help_modal.show()

    def _session_id_for_online(self):
        if self.online_client is not None and self.online_client.room_id:
            return self.online_client.room_id
        return str(uuid.uuid4())

    def _refresh_load_pgn_availability(self):
        self.start_menu.load_pgn_available = self._latest_pgn_path() is not None

    def _latest_pgn_path(self):
        files = glob.glob(os.path.join(_games_dir(), "*.pgn"))
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    def _on_open_history(self):
        self.history_view.show(
            _games_dir(), "*.pgn",
            on_open=self._load_pgn_from_path,
            nickname=env.get_nickname(),
        )
        self.request_nav(Nav("history"))

    def _on_menu_back(self):
        self.history_view.hide()
        self.request_nav(Nav("menu"))

    def _on_open_fen_modal(self):
        self.fen_input_modal.show(on_submit=self._start_game_from_fen)

    def _start_game_from_fen(self, fen):
        try:
            apply_fen(Backend(), fen)
        except (ValueError, KeyError):
            return False
        self.match.local_color = None
        self._drop_post_game_online_session()
        self.request_nav(Nav("game", {"mode": SINGLE_SCREEN, "fen": fen}))
        self._execute_pending_nav()
        self.fen_input_modal.hide()
        self.start_menu.hide()
        return True

    def _load_pgn_from_path(self, path):
        log.info("pgn load path=%s", path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.switch_to("game", mode=SINGLE_SCREEN)
        self._drop_post_game_online_session()
        self._time_control = None
        self._reset_to_new_game()
        parsed, ok = load_pgn_into_backend(self.match, text)
        if not ok:
            log.warning("pgn load failed path=%s", path)
            self.switch_to("history")
            self.toast.show("Could not load PGN")
            return
        self.skillcheck_session._rebuild_skillcheck_log(parsed.move_comments)
        self._pgn_result_tag = parsed.result
        self.white_name = parsed.headers.get("White", "Player 1")
        self.black_name = parsed.headers.get("Black", "Player 2")
        self.white_country = ""
        self.black_country = ""
        self._time_control = parse_time_control(parsed.headers.get("TimeControl", "-"))
        if self.match.move_history:
            self.board.review_ply = 0
        self.pgn_review = True
        self.board.read_only = True
        self._review_return_page = "history"
        self.start_menu.hide()

    def _on_start_game(self, config):
        env.set_last_mode(config["mode"])
        env.set_nickname(config.get("nickname") or "")
        if config["mode"] == ONLINE:
            self._begin_online_flow(config)
            return
        if config["mode"] != SINGLE_SCREEN:
            return

        side = config["side"]
        if side == "random":
            side = random.choice(["white", "black"])

        self.match.local_color = None
        self._drop_post_game_online_session()

        log.info("game start mode=%s side=%s tc=%s+%s",
                 config["mode"], side, config["time_minutes"], config["increment_seconds"])
        self.request_nav(Nav("game", {
            "mode": SINGLE_SCREEN,
            "side": side,
            "nickname": config.get("nickname") or "",
            "time_minutes": config["time_minutes"],
            "increment_seconds": config["increment_seconds"],
        }))
        self._execute_pending_nav()
        self.start_menu.hide()
        self.sound_manager.play_game_start()

    def _begin_online_flow(self, config):
        log.info("online flow begin tc=%s+%s side=%s",
                 config.get("time_minutes"), config.get("increment_seconds"),
                 config.get("side"))
        self._online_config = config
        self.start_menu.hide()
        self._on_server_addr_connect(env.get_server_addr())

    def _on_server_addr_connect(self, addr):
        log.info("connect to %s", addr)
        if not addr:
            self._on_online_cancel()
            return
        if self.online_client is not None:
            self.online_client.disconnect()
            self.online_client = None
        self.offer_banners.dismiss("rematch_request")
        self._rematch_offered = False
        self.online_client = OnlineClient()
        request = {
            "nickname": (self._online_config.get("nickname") or "").strip() or "Player",
            "client_uuid": env.get_or_create_client_uuid(),
            "time_minutes": self._online_config["time_minutes"] or ONLINE_DEFAULT_TIME_MINUTES,
            "increment_seconds": self._online_config["increment_seconds"],
            "side_preference": self._online_config["side"],
            "country": env.get_country() or None,
        }
        self.online_client.connect(addr, request)
        mode_label, tc_text = self._search_labels()
        self.wait_modal.show(mode_label, tc_text, self._on_online_cancel)
        self._wait_started_at_ms = pg.time.get_ticks()
        self._match_found_at_ms = None
        self._pending_game_start_payload = None

    def _search_labels(self):
        minutes = self._online_config.get("time_minutes") or ONLINE_DEFAULT_TIME_MINUTES
        incr = self._online_config.get("increment_seconds", 0) or 0
        if minutes < 3:
            mode = "Bullet"
        elif minutes < 10:
            mode = "Blitz"
        else:
            mode = "Rapid"
        return mode, f"{minutes} + {incr}"

    def _on_online_cancel(self):
        log.info("online flow cancel")
        if self.online_client is not None:
            self.online_client.cancel_queue()
            self.online_client = None
        self.match.on_local_move_applied = None
        self.right_menu.set_game_info(None)
        self.wait_modal.hide()
        self.match_found_modal.hide()
        self.offer_banners.clear()
        self._wait_started_at_ms = None
        self._match_found_at_ms = None
        self._pending_game_start_payload = None
        self._return_to_menu_card()

    def _on_rematch(self):
        if self.online_client is None:
            return
        if self._rematch_offered:
            self._rematch_offered = False
            self.result_menu.set_rematch_offered(False)
            log.info("rematch response sent accepted=True")
            self.online_client.send_rematch_response(True)
        else:
            log.info("rematch requested")
            self.online_client.send_rematch_request()
            self.toast.show(f"Rematch sent — waiting for {self._opp_name()}…",
                            key=REMATCH_STATE_TOAST_KEY)

    def _drop_post_game_online_session(self):
        if self.online_client is None:
            return
        self.online_client.disconnect()
        self.online_client = None
        self.result_menu.set_online_mode(False)
        self._first_move_deadline_ms = None
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self._prev_online_state = None

    def _tear_down_online_session(self, reason="unspecified"):
        log.info("online session teardown reason=%s", reason)
        self.result_flow._auto_save_pgn()
        if self.online_client is not None:
            self.online_client.disconnect()
            self.online_client = None
        self.reconnecting_modal.hide()
        self.match_found_modal.hide()
        self.offer_banners.clear()
        self._pending_game_start_payload = None
        self._match_found_at_ms = None
        self.match.on_local_move_applied = None
        self.right_menu.set_game_info(None)
        self.result_menu.set_online_mode(False)
        self.match.mode = SINGLE_SCREEN
        self.match.local_color = None
        self.switch_to("menu")
        pg.display.set_caption(WINDOW_TITLE)
        self._reset_to_new_game()
        self._refresh_load_pgn_availability()

    def _return_to_menu_card(self):
        self.switch_to("menu")
        self.reconnect_probe._reconnect_probe_attempts = 0
        self.start_menu.show()

    def _abandon_online_game(self):
        self._tear_down_online_session("reconnect_cancelled")
        self._return_to_menu_card()

    def _restart_online_search(self):
        self._tear_down_online_session("restart_search")
        if self._online_config is not None:
            self._begin_online_flow(self._online_config)
        else:
            self._return_to_menu_card()

    def _update_online_phase(self):
        if self.wait_modal.is_visible() and self._match_found_at_ms is None:
            if self._wait_started_at_ms is not None:
                self.wait_modal.set_elapsed(
                    (pg.time.get_ticks() - self._wait_started_at_ms) // 1000)
        self.match_found_modal.update()
        self._track_local_online_state()
        self._send_heartbeat_if_due()
        now = pg.time.get_ticks()
        reconnecting = (self.mode == ONLINE and self.current_result() is None
                        and self.online_client is not None
                        and self.online_client.state == "reconnecting")
        if reconnecting:
            since = self._local_disconnected_at_ms
            if (not self.reconnecting_modal.is_visible() and since is not None
                    and now - since >= RECONNECT_MODAL_DEBOUNCE_MS):
                self.reconnecting_modal.show(
                    since, on_cancel=self._abandon_online_game)
        elif self.reconnecting_modal.is_visible():
            self.reconnecting_modal.hide()
        if self._resyncing:
            if pg.time.get_ticks() - self._resync_started_at_ms > RESYNC_TIMEOUT_MS:
                self._resyncing = False
                if (self.online_client is not None
                        and self.online_client.state == "connected"):
                    log.info("resync timed out; escalating to reconnect")
                    self.online_client.force_reconnect()
            else:
                self.toast.show("Resyncing…")
        self._tick_skillcheck_watchdog()

    def _tick_skillcheck_watchdog(self):
        if (self.skillcheck_session._online_skillcheck is None
                or self.skillcheck_session._online_skillcheck_opened_ms is None
                or not self.skillcheck_overlay.is_active()):
            return
        elapsed = pg.time.get_ticks() - self.skillcheck_session._online_skillcheck_opened_ms
        if elapsed > SKILLCHECK_DEADLINE_MS + SKILLCHECK_WATCHDOG_SLACK_MS:
            log.warning("skillcheck verdict lost; resyncing")
            self.skillcheck_session._teardown_skillcheck_overlay()
            self._begin_resync()

    def _send_heartbeat_if_due(self):
        if self.online_client is None or not self.online_client.is_connected():
            return
        if self.online_client.is_server_silent():
            log.info("server heartbeat silent; escalating to reconnect")
            self.online_client.force_reconnect()
            return
        if self.skillcheck_session._online_verdict_action is not None:
            return
        now = pg.time.get_ticks()
        if now - self._last_heartbeat_sent_ms >= self.online_client.heartbeat_interval() * 1000:
            self._last_heartbeat_sent_ms = now
            self.online_client.send_ping(len(self.match.move_history))

    def _track_local_online_state(self):
        current = self.online_client.state if self.online_client is not None else None
        prev = self._prev_online_state
        if current == "reconnecting" and prev != "reconnecting":
            self._local_disconnected_at_ms = pg.time.get_ticks()
        elif current != "reconnecting" and prev == "reconnecting":
            self._local_disconnected_at_ms = None
        self._prev_online_state = current

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

        if not self.pgn_review and self.current_result() is not None:
            self.result_flow._auto_save_pgn()
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
            ping = (self.online_client.get_ping_ms()
                    if self.online_client is not None else None)
            parts.append(f"PING {ping}ms" if ping is not None else "PING —")
        return parts

    def _present(self, had_events):
        rects = self._present_rects(had_events)
        if rects is None:
            pg.display.flip()
        else:
            pg.display.update(rects)

    def _needs_full_redraw(self, had_events):
        return (had_events or self._needs_full_present or self.mode == "menu"
                or self.focus_transition is not None
                or self._menu_overlay_active() or self.toast.is_visible()
                or not self.offer_banners.is_empty()
                or self.skillcheck_overlay.is_active()
                or self.current_result() is not None
                or self.give_time._give_time_holding
                or self.board.is_dragging()
                or self.board.effects.is_active()
                or self.board.is_restoring()
                or self.board.pending_promotion_square is not None)

    def _present_rects(self, had_events):
        if self._needs_full_redraw(had_events):
            self._needs_full_present = False
            return None
        rects = [
            pg.Rect(0, 0, self.window_width, self.chrome.HEIGHT),
            self.player_strip_top.rect,
            self.player_strip_bottom.rect,
            self.right_menu.outer_rect,
        ]
        now = pg.time.get_ticks()
        if (self.board.is_animating()
                or now - self.board.last_animation_completed_at_ms < PRESENT_SETTLE_MS):
            rects.append(self.board.animation_dirty_rect())
        if self.focus_arrow.is_visible():
            rects.append(self.focus_arrow.dirty_rect())
        if self.focus_mode and self._focus_show() == "line":
            top_line, bottom_line = self.time_line.rects_for(self.board, self.board.rect)
            rects.extend([top_line, bottom_line])
        return rects

    def _menu_overlay_active(self):
        return any(spec.obj.is_visible() for spec in self._modal_registry)

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
                log.info("resize-sync win32=%s gws=%s surf=%s -> set_mode(%d,%d)",
                         self.chrome.client_size(), pg.display.get_window_size(),
                         self.window.get_size(), win_w, win_h)
            self._recreate_window_surface(win_w, win_h)
            self.window_width = win_w
            self.window_height = win_h
            self.input_router._cancel_all_scroll()
            self._abort_transition_for_resize()
            self._compute_layout()

    def draw_frame(self):
        if os.name == "nt" and not self.chrome.is_fullscreen():
            self._sync_window_surface()
        if getattr(self, "_last_layout_mode", None) != self.mode:
            self._compute_layout()
        if self.mode == "menu" and (self.focus_mode or self.focus_transition is not None):
            self._force_focus_off_instant()
        if self.mode != "menu" and self._focus_prev_mode == "menu":
            self._focus_hint_until_ms = pg.time.get_ticks() + FOCUS_HINT_MS
        self._focus_prev_mode = self.mode

        self._drain_online_inbound()

        self.give_time._update_give_time_hold()
        self.settings._flush_deferred_env_writes()
        self._maybe_play_flag_fall()
        self._update_heartbeat()

        now = pg.time.get_ticks()
        nav = self.screen.update(now)
        if nav is not None:
            self.request_nav(nav)

        self.reconnect_probe._refresh_reconnect_button()

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

        self.offer_banners.draw(self._banner_rect())
        for spec in reversed(self._modal_registry):
            spec.obj.draw()
        self.toast.draw(center_x=None if self.mode == "menu" else self.board.rect.centerx)
        if self.skillcheck_overlay.is_active() and (
                self.mode == "menu" or self.current_result() is not None):
            self.skillcheck_session._teardown_skillcheck_overlay()
        self.skillcheck_overlay.update(now)
        self.skillcheck_overlay.draw(self.window)
        self._update_online_phase()

    def _maybe_play_flag_fall(self):
        if self._flag_fall_played or self.mode == "menu":
            return
        clock = self.match.clock
        if clock is None or clock.flagged is None:
            return
        self._flag_fall_played = True
        local = self.match.local_color
        if self.mode == ONLINE and local is not None and clock.flagged != local:
            self.sound_manager.play_you_win()
        else:
            self.sound_manager.play_flag_fall()

    def _update_heartbeat(self):
        clock = self.match.clock
        paused = (self.mode == "menu"
                  or self.current_result() is not None
                  or clock is None)
        if paused or clock.initial_seconds <= 0:
            fraction = None
        else:
            fraction = clock.remaining(self.match.current_turn()) / clock.initial_seconds
        auto_end_fraction = self._auto_end_heartbeat_fraction()
        if auto_end_fraction is not None:
            fraction = (auto_end_fraction if fraction is None
                        else min(fraction, auto_end_fraction))
        self.sound_manager.update_heartbeat(fraction, paused)

    def _auto_end_heartbeat_fraction(self):
        if self.mode != ONLINE:
            return None
        now = pg.time.get_ticks()
        candidates = []
        for snap_ms, total in (
            (self._opp_disconnected_at_ms, GRACE_SECONDS),
            (self._local_disconnected_at_ms, RECONNECT_TOTAL_SECONDS),
        ):
            if snap_ms is None:
                continue
            remaining = total - (now - snap_ms) / 1000.0
            if remaining <= 0:
                continue
            candidates.append((remaining, total))
        if (self._first_move_deadline_ms is not None
                and not self.match.move_history):
            remaining_ms = self._first_move_deadline_ms - now
            if remaining_ms > 0:
                candidates.append((remaining_ms / 1000.0, FIRST_MOVE_ABORT_SECONDS))
        if not candidates:
            return None
        remaining, total = min(candidates, key=lambda r: r[0])
        if remaining < AUTO_END_RED_THRESHOLD_SECONDS:
            return 0.0
        return remaining / total

    def _banner_rect(self):
        if self.mode != "menu":
            return self.board.rect
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
        r = compute_layout(
            window_width, window_height, mode=self.mode, focus_mode=self.focus_mode,
            focus_show=self._focus_show(), board_size=self.board.SIZE)

        self.confirm_modal.set_rect(r.result_modal_rect)
        self.wait_modal.set_rect(r.flex_rect)
        self.match_found_modal.set_rect(r.flex_rect)
        self.reconnecting_modal.set_rect(r.board_rect)
        self.start_menu.set_rect(r.start_rect)
        for screen in self.screens.values():
            screen.relayout(size)
        self.menu_battle.top_inset = r.top
        self.menu_battle.set_rect(r.window_rect)
        self.help_modal.set_rect(r.result_rect)
        self.fen_input_modal.set_rect(r.flex_rect)
        self.options_modal.set_rect(r.options_rect)
        self.directory_browser.set_rect(r.wide_overlay_rect)
        self.country_picker.set_rect(r.wide_overlay_rect)
        self._last_layout_mode = self.mode
        self._needs_full_present = True
