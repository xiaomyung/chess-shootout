import glob
import logging
import os
import random
import time
import uuid
from collections import deque

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import Match, SINGLE_SCREEN, BOT, ONLINE
from chessshootout.backend.backend import Backend
from chessshootout.backend.fen import apply_fen
from chessshootout.infra import countries, env
from chessshootout.frontend.panels.audio import AudioPanel
from chessshootout.frontend.board import Board
from chessshootout.frontend.skillcheck.overlay import SkillCheckOverlay
from chessshootout.skillcheck.coordinator import SkillCheckCoordinator
from chessshootout.skillcheck.online import SKILLCHECK_DEADLINE_MS
from chessshootout.frontend.menu.menu_battle import MenuBattle
from chessshootout.domain.capture_summary import captured_by, material_advantage
from chessshootout.frontend.menu.menu_page import MenuPage, PAGE_CARD, PAGE_HISTORY
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
from chessshootout.frontend.visual import backdrop
from chessshootout.frontend.visual import cache
from chessshootout.frontend.visual.effects import TAKEOVER_TOTAL_MS
from chessshootout.frontend.focus.arrow import (
    FocusArrow, FOCUS_EDGE_ZONE_PX, FOCUS_ARROW_D, LONG_AGO_MS)
from chessshootout.frontend.focus.time_line import TimeLine
from chessshootout.frontend.focus.transition import FocusTransition
from chessshootout.frontend.input_router import InputRouter
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.screens.base import assert_plain_payload
from chessshootout.frontend.screens.menu import MenuScreen
from chessshootout.frontend.screens.game import GameScreen
from chessshootout.frontend.window_chrome import (
    WindowChrome, WINDOW_FLAGS, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from chessshootout.online.client import OnlineClient, RECONNECT_TOTAL_SECONDS
from chessshootout.frontend.online.events import REMATCH_STATE_TOAST_KEY, OnlineEventsMixin
from chessshootout.frontend.reconnect_probe import ReconnectProbe
from chessshootout.frontend.give_time import GiveTimeHold
from chessshootout.frontend.skillcheck_session import SkillcheckSession
from chessshootout.frontend.result_flow import (
    ResultFlow, AUTOSAVE_THROTTLE_MS, _open_with_default_app, _score_str,
)
from chessshootout.frontend.panels.player_strip import (
    AUTO_END_RED_THRESHOLD_SECONDS, PlayerStrip,
)
from chessshootout.frontend.modals.wait import WaitModal
from chessshootout.frontend.modals.match_found import MatchFoundModal
from chessshootout.frontend.online.banners import OfferBanners
from chessshootout.frontend.panels.right import (
    RightMenu,
    BUTTONS as RIGHT_MENU_BUTTONS,
    UNTIMED_BUTTONS as RIGHT_MENU_UNTIMED_BUTTONS,
    REVIEW_BUTTONS as RIGHT_MENU_REVIEW_BUTTONS,
)
from chessshootout.frontend.modals.result import ResultMenu
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.modals.start import StartMenu
from chessshootout.domain.pgn.load import (
    load_pgn_into_backend, parse_time_control, format_time_control,
)
from chessshootout.paths import SOUNDS_DIR
from chessshootout.backend.pieces import PieceColor, PieceType, opponent_of
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS


OPPONENT_NAME_FOR_MODE = {
    SINGLE_SCREEN: "Player 2",
    BOT: "Bot",
}

PLACEHOLDER_RATING = "1500"

MODE_PILL_LABELS = {
    SINGLE_SCREEN: "Local",
    BOT: "Bot",
    ONLINE: "Online",
}


FOCUS_OFF_LINGER_MS = 2000
FOCUS_HINT_MS = 1600
FOCUS_EDGE_ARROW_MARGIN = 16
FOCUS_ARROW_OFF_GAP = 6

AUTO_FLIP_DELAY_MS = 200
RESULT_FADE_MS = 400
PERF_SAMPLE_COUNT = 240
PERF_1PCT_PERCENTILE = 0.99
PERF_1PCT_MIN_SAMPLES = 100
PRESENT_SETTLE_MS = 120
RESULT_MODAL_DELAY_MS = 500
RESULT_TAKEOVER_MS = TAKEOVER_TOTAL_MS
RESULT_FADE_MAX_ALPHA = 140

AUTO_END_GATE_FRACTION = 0.1

ANIM_MS_DEFAULT = 180
ANIM_MS_MIN = 140
ANIM_MS_MAX = 280
ANIM_MS_PER_SECOND = 0.5

RESYNC_TIMEOUT_MS = 8000
SKILLCHECK_WATCHDOG_SLACK_MS = 4000
RECONNECT_MODAL_DEBOUNCE_MS = 500

ONLINE_DEFAULT_TIME_MINUTES = 5

WINDOW_TITLE = "Chess Shootout"


def _games_dir():
    return str(paths.get_games_dir())


def compute_animation_ms(initial_seconds):
    if initial_seconds is None or initial_seconds <= 0:
        return ANIM_MS_DEFAULT
    return max(ANIM_MS_MIN, min(ANIM_MS_MAX, int(initial_seconds * ANIM_MS_PER_SECOND)))


log = logging.getLogger("chess.frontend")

_RESULT_FADE_CACHE = cache.new_size_cache()


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
        self.result_flow = ResultFlow(self)
        self.chrome = WindowChrome(self.window, on_fullscreen=self._apply_fullscreen)
        self.clock = pg.time.Clock()

        self.mode = "menu"
        self.manual_result = None
        self._last_turn_for_flip = None
        self.white_name = "Player 1"
        self.black_name = "Player 2"
        self.white_country = ""
        self.black_country = ""
        self._chosen_side = "white"
        self._time_control = None
        self._online_config = None
        self.pgn_review = False
        self._flag_fall_played = False
        self._game_bg_cache = None
        self._needs_full_present = True
        self._frame_times = deque(maxlen=PERF_SAMPLE_COUNT)
        self._last_work_ms = 0.0
        self._last_frame_start = None
        self._strip_memo = {}
        self._result_first_seen_at_ms = None
        self._pgn_result_tag = None
        self._match_session_id = None
        self._review_return_page = None
        self._resyncing = False
        self._resync_started_at_ms = 0
        self._last_heartbeat_sent_ms = 0
        self.give_time = GiveTimeHold(self)
        self._first_move_deadline_ms = None
        self._opp_disconnected_at_ms = None
        self._local_disconnected_at_ms = None
        self._prev_online_state = None
        self._prev_battle_mode = None

        self.match = Match()
        self.sound_manager = SoundManager(SOUNDS_DIR, enabled=pg.mixer.get_init() is not None)
        self.board = Board(self.window, self.match,
                           move_landed_callback=self._on_move_landed,
                           on_premove_queued=self.sound_manager.play_premove_queued,
                           shot_callback=self._on_shot_fired,
                           announce_callback=self._on_kill_announced)
        self.skillcheck = SkillCheckCoordinator()
        self.skillcheck_overlay = SkillCheckOverlay()
        self.skillcheck_session = SkillcheckSession(self)
        self.board.skillcheck_gate = self.skillcheck_session._skillcheck_gate
        self.board.skillcheck_armed = lambda: self.skillcheck.enabled
        self.board.locked_targets = self.skillcheck.is_locked
        self.result_menu = ResultMenu(self.window, {
            "new_game": self._on_new_game,
            "open_pgn": self.result_flow._on_open_pgn,
            "menu": self._on_back_to_menu,
            "rematch": self._on_rematch,
        })
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
        self.right_menu = RightMenu(self.window, self.match, {
            "undo": self._on_undo,
            "resign": self._on_resign,
            "draw": self._on_draw,
            "flip": self._on_flip,
            "menu": self._on_back_to_menu,
            "help": self._on_help,
            "give_time": self.give_time._on_give_time,
        }, board=self.board, buttons_provider=self._right_menu_buttons,
            audio_panel=self.audio_panel,
            disabled_keys_provider=self._right_menu_disabled_keys,
            whiffs_provider=self.skillcheck_session._skillcheck_whiffs)
        self.confirm_modal = ConfirmModal(self.window)
        self.history_view = HistoryView(self.window, on_open=self._load_pgn_from_path,
                                        on_back=self._on_menu_back)
        self.menu_page = MenuPage(self.window, self.start_menu, self.history_view)
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
        self.result_flow._probe_games_dir_writable()
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
        self.player_strip_top = PlayerStrip(self.window)
        self.player_strip_bottom = PlayerStrip(self.window)
        self.menu_battle = MenuBattle(self.window, sound_manager=self.sound_manager)
        self.focus_mode = False
        self.focus_transition = None
        self.focus_arrow = FocusArrow()
        self.time_line = TimeLine()
        self._focus_panel_hover_ms = LONG_AGO_MS
        self._focus_hint_until_ms = 0
        self._focus_prev_mode = "menu"
        self._entering_menu = False
        self._pending_nav = None

        self.screens = {"menu": MenuScreen(self), "game": GameScreen(self)}
        self.screen = self.screens["menu"]

        self.match.new_game()
        self.board.load_assets()
        self._compute_layout()
        self._refresh_load_pgn_availability()
        self._settle_window()
        self.reconnect_probe._spawn_reconnect_probe()

        pg.display.set_caption(WINDOW_TITLE)

    def switch_to(self, name, **payload):
        if name not in self.screens:
            raise KeyError(f"unknown screen: {name!r}")
        assert_plain_payload(payload)
        mode = payload.get("mode", name)
        self.screen.exit()
        self.screen = self.screens[name]
        self.mode = mode
        self.screen.enter(**payload)
        self._compute_layout()

    def request_nav(self, nav):
        if self._pending_nav is not None:
            log.warning("nav intent overwritten: %s -> %s",
                        self._pending_nav.name, nav.name)
        self._pending_nav = nav

    def _execute_pending_nav(self):
        if self._pending_nav is None:
            return
        nav = self._pending_nav
        self._pending_nav = None
        self.switch_to(nav.name, **nav.payload)

    @property
    def backend(self):
        return self.match.backend

    def current_result(self):
        return self.result_flow.current_result()

    def result_text(self):
        return self.result_flow.result_text()

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

    def game_live(self):
        return self.mode != "menu" and self.current_result() is None

    def board_interactive(self):
        return not self.pgn_review and self.current_result() is None

    @staticmethod
    def _is_white(color):
        return color in (PieceColor.WHITE, "white")

    def _name_for_color(self, color):
        return self.white_name if self._is_white(color) else self.black_name

    def _country_for_color(self, color):
        return self.white_country if self._is_white(color) else self.black_country

    def _on_new_game(self):
        if self.mode == SINGLE_SCREEN:
            self._chosen_side = "black" if self._chosen_side == "white" else "white"
            self.white_name, self.black_name = self.black_name, self.white_name
            self.white_country, self.black_country = self.black_country, self.white_country
        self._reset_to_new_game()
        self.sound_manager.play_game_start()

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
        return_page = self._review_return_page or PAGE_CARD
        self._review_return_page = None
        self._reset_to_new_game()
        self._refresh_load_pgn_availability()
        self.start_menu.show()
        if return_page == PAGE_HISTORY:
            self._on_open_history()
        else:
            self.menu_page.set_page(PAGE_CARD)
        if keep_online and had_rematch_offer:
            self._reshow_rematch_banner()

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
        self.menu_page.set_page(PAGE_HISTORY)

    def _on_menu_back(self):
        self.history_view.hide()
        self.menu_page.set_page(PAGE_CARD)

    def _on_open_fen_modal(self):
        self.fen_input_modal.show(on_submit=self._start_game_from_fen)

    def _start_game_from_fen(self, fen):
        try:
            apply_fen(Backend(), fen)
        except (ValueError, KeyError):
            return False
        self.switch_to("game", mode=SINGLE_SCREEN)
        self._drop_post_game_online_session()
        self._time_control = None
        self._chosen_side = "white"
        self.white_name = "Player 1"
        self.black_name = "Player 2"
        self.white_country = env.get_country()
        self.black_country = countries.random_code()
        self.match.mode = SINGLE_SCREEN
        self.match.local_color = None
        log.info("game start mode=fen")
        self._ensure_local_session()
        self._reset_to_new_game()
        apply_fen(self.match.backend, fen)
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
            self.switch_to("menu")
            self.menu_page.set_page(PAGE_HISTORY)
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
        self._review_return_page = PAGE_HISTORY
        self.start_menu.hide()

    def _on_start_game(self, config):
        env.set_last_mode(config["mode"])
        env.set_nickname(config.get("nickname") or "")
        if config["mode"] == ONLINE:
            self._begin_online_flow(config)
            return
        if config["mode"] != SINGLE_SCREEN:
            return

        self.switch_to("game", mode=SINGLE_SCREEN)
        self.match.local_color = None
        self._drop_post_game_online_session()

        side = config["side"]
        if side == "random":
            side = random.choice(["white", "black"])
        self._chosen_side = side

        nickname = (config.get("nickname") or "").strip() or "Player 1"
        opponent_name = OPPONENT_NAME_FOR_MODE[config["mode"]]
        self.white_name, self.black_name = (
            (nickname, opponent_name) if side == "white"
            else (opponent_name, nickname)
        )
        my_country = env.get_country()
        opp_country = countries.random_code()
        self.white_country, self.black_country = (
            (my_country, opp_country) if side == "white"
            else (opp_country, my_country)
        )

        self._time_control = (
            (config["time_minutes"] * 60, config["increment_seconds"])
            if config["time_minutes"] is not None else None
        )

        self.skillcheck.reset(
            enabled=True,
            seed="local-{}-{}".format(pg.time.get_ticks(), random.randint(0, 1 << 30)))

        log.info("game start mode=%s side=%s tc=%s white=%s black=%s",
                 config["mode"], side, self._time_control, self.white_name, self.black_name)
        self._ensure_local_session()
        self._reset_to_new_game()
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
        self.menu_page.set_page(PAGE_CARD)

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

    def _right_menu_buttons(self):
        if self.pgn_review:
            return RIGHT_MENU_REVIEW_BUTTONS
        if self.match.clock is None:
            return RIGHT_MENU_UNTIMED_BUTTONS
        return RIGHT_MENU_BUTTONS

    def _right_menu_disabled_keys(self):
        if self.pgn_review:
            return set()
        if self.current_result() is not None:
            return {"undo", "resign", "draw", "flip", "give_time"}
        disabled = set()
        clock = self.match.clock
        if clock is None or clock.flagged is not None:
            disabled.add("give_time")
        if self.give_time._give_time_on_cooldown():
            disabled.add("give_time")
        return disabled

    def _reset_to_new_game(self):
        self._force_focus_off_instant()
        self.pgn_review = False
        self.board.read_only = False
        self._review_return_page = None
        self.offer_banners.clear()
        self._rematch_offered = False
        self.result_menu.reset()
        self.sound_manager.stop_all()
        self.give_time._cancel_give_time_hold()
        self.manual_result = None
        self._flag_fall_played = False
        self.result_flow._result_cache_key = None
        self.result_flow._result_cache = None
        self._strip_memo = {}
        self._result_first_seen_at_ms = None
        self._pgn_result_tag = None
        self.result_flow._last_saved_pgn_path = None
        self.result_flow._last_saved_result_tag = None
        self.result_flow._result_await_since_ms = None
        self.result_flow._result_logged = False
        self.result_flow._series_score_awarded = False
        self.result_flow._save_failed = False
        self.result_flow._save_error_toast_shown = False
        self.result_flow._final_save_attempted_for = None
        self.result_flow._autosave_last_write_ms = -AUTOSAVE_THROTTLE_MS
        self.result_flow._autosave_last_ply = 0
        self.right_menu.reset_for_new_game()
        self.match.new_game()
        if self._time_control is not None:
            initial, incr = self._time_control
            self.match.setup_clock(initial, incr)
            self.board.animation_duration_ms = compute_animation_ms(initial)
        else:
            self.board.animation_duration_ms = ANIM_MS_DEFAULT
        self.board.reset_for_new_game()
        self.skillcheck_overlay.cancel()
        self.skillcheck.clear_locks()
        self.skillcheck_session._clear_online_skillcheck_state()
        self.skillcheck_session._skillcheck_log = []
        self.confirm_modal.hide()
        self._last_turn_for_flip = None

    def _focus_show(self):
        return env.get_focus_show()

    def _focus_available(self):
        return (self.mode != "menu"
                and self.board_interactive()
                and not self.skillcheck_overlay.is_active()
                and not self.board.is_dragging()
                and self.board.pending_promotion_square is None
                and not self._menu_overlay_active())

    def _focus_arrow_allowed(self):
        return (self.board_interactive()
                and not self.skillcheck_overlay.is_active()
                and not self._menu_overlay_active())

    def _toggle_focus(self, on):
        if self.focus_transition is not None:
            return
        if self.skillcheck_overlay.is_active() and self.current_result() is None:
            return
        if on == self.focus_mode:
            return
        if on and not self._focus_available():
            return
        log.info("focus mode toggled on=%s", on)
        self.board.cancel_drag_physics()
        self.focus_transition = FocusTransition(self)
        if on:
            self.focus_transition.begin_collapse(self._focus_show())
        else:
            self.focus_transition.begin_expand(self._focus_show())
        self.focus_arrow.reset()
        self._needs_full_present = True

    def _finalize_focus_transition(self):
        self.focus_transition = None
        self._needs_full_present = True

    def _abort_transition_for_resize(self):
        if self.focus_transition is not None:
            self.focus_transition.cancel()
            self.focus_transition = None
            self._needs_full_present = True

    def _force_focus_off_instant(self):
        if not self.focus_mode and self.focus_transition is None:
            return
        if self.focus_transition is not None:
            self.focus_transition.cancel()
            self.focus_transition = None
        self.focus_mode = False
        self.focus_arrow.reset()
        self._focus_panel_hover_ms = LONG_AGO_MS
        self._focus_hint_until_ms = 0
        self._compute_layout()
        self._needs_full_present = True

    def _draw_game_scene(self, *, show_panel, show_strips, arrow_hook=None, after_board=None):
        self.skillcheck_session._sync_aim_check_gun()
        self._draw_game_background()
        self.board.draw_board()
        if after_board is not None:
            after_board()
        if show_strips:
            self._update_player_strips()
            self.player_strip_top.draw()
            self.player_strip_bottom.draw()
        if show_panel:
            self._refresh_game_info()
        if arrow_hook is not None:
            arrow_hook()
        if show_panel:
            self.right_menu.draw_menu()

    def _focus_edge_zone_rect(self):
        board_r = self.board.rect
        w = self.window.get_width()
        return pg.Rect(w - FOCUS_EDGE_ZONE_PX, board_r.top, FOCUS_EDGE_ZONE_PX, board_r.height)

    def _focus_arrow_off_anchor(self):
        x = self.right_menu.outer_rect.x - FOCUS_ARROW_D // 2 - FOCUS_ARROW_OFF_GAP
        return (x, self.board.rect.centery)

    def _update_focus_arrow_off(self, now):
        if not self._focus_arrow_allowed():
            self.focus_arrow.reset()
            return
        mp = pg.mouse.get_pos()
        if self.right_menu.outer_rect.collidepoint(mp):
            self._focus_panel_hover_ms = now
        anchor = self._focus_arrow_off_anchor()
        shown = (now < self._focus_hint_until_ms
                 or now - self._focus_panel_hover_ms < FOCUS_OFF_LINGER_MS)
        self.focus_arrow.update(now, shown, anchor, mp, False)
        self.focus_arrow.draw(self.window)

    def _draw_focus_edge_arrow(self, now):
        mp = pg.mouse.get_pos()
        zone = self._focus_edge_zone_rect()
        reveal = self._focus_arrow_allowed() and zone.collidepoint(mp)
        anchor = (self.window.get_width() - FOCUS_EDGE_ARROW_MARGIN - FOCUS_ARROW_D // 2,
                  self.board.rect.centery)
        self.focus_arrow.update(now, reveal, anchor, mp, True)
        self.focus_arrow.draw(self.window)

    def _draw_time_lines(self, board_rect=None, alpha=1.0):
        if self._focus_show() != "line" or self._time_control is None:
            return
        self.time_line.draw(self.window, self.board, self.match.clock,
                            self.match.current_turn(), board_rect or self.board.rect, alpha)

    def _ensure_local_session(self):
        if self._match_session_id is None:
            self._match_session_id = str(uuid.uuid4())

    def _session_id_for_online(self):
        if self.online_client is not None and self.online_client.room_id:
            return self.online_client.room_id
        return str(uuid.uuid4())

    def _on_undo(self):
        if not self.board_interactive():
            return
        if self.mode == ONLINE and self.online_client is not None:
            log.info("takeback requested")
            self.online_client.send_takeback_request()
            return
        self.board.selected_square = None
        self.board.clear_premoves()
        self.skillcheck.clear_locks()
        self.board.clear_annotations()
        self.board.review_ply = None
        self.board.cancel_animations()
        if not self.match.move_history:
            return
        log.info("undo ply=%d", len(self.match.move_history))
        self.sound_manager.play_undo()
        self.skillcheck_session._drop_skillcheck_log_from(len(self.match.move_history))
        move = self.match.move_history[-1].move
        self.match.undo()
        self.board.start_undo_animation(move)

    def _on_resign(self):
        if not self.board_interactive():
            return
        self.confirm_modal.show(
            "Tap out?", on_yes=self._perform_resign,
            sub="The pieces are watching.",
            yes_label="I'm done", no_label="Keep fighting", danger=True, emoji="🏳️",
        )

    def _perform_resign(self):
        if self.current_result() is not None:
            return
        if self.mode == ONLINE and self.online_client is not None:
            self.online_client.send_resign()
            return
        loser = self.match.current_turn()
        self._auto_complete_pending_promotion()
        self.manual_result = (
            "black_wins_by_resignation" if loser == PieceColor.WHITE
            else "white_wins_by_resignation"
        )
        self.board.clear_premoves()
        self.board.clear_annotations()
        self.result_flow._on_result_final(self.manual_result)

    def _on_draw(self):
        if not self.board_interactive():
            return
        self.confirm_modal.show(
            "Offer a draw?", on_yes=self._perform_draw,
            sub="Propose splitting the point. No shots fired, no glory either.",
            yes_label="Offer draw", no_label="Nevermind", emoji="🤝",
        )

    def _perform_draw(self):
        if self.current_result() is not None:
            return
        if self.mode == ONLINE and self.online_client is not None:
            log.info("draw offer sent")
            self.online_client.send_draw_offer()
            return
        self._auto_complete_pending_promotion()
        self.manual_result = "draw_agreement"
        self.board.clear_premoves()
        self.board.clear_annotations()
        self.result_flow._on_result_final(self.manual_result)

    def _auto_complete_pending_promotion(self):
        if self.board.pending_promotion_square is None:
            return
        if self.board.cancel_unapplied_promotion():
            return
        self.match.promote(self.board.pending_promotion_square, PieceType.QUEEN)
        self.board.pending_promotion_square = None

    def _on_flip(self):
        if self.current_result() is not None and not self.pgn_review:
            return
        self.board.cancel_drag_physics()
        self.board.flipped = not self.board.flipped
        self.sound_manager.play_flip()

    def _on_help(self):
        self.help_modal.show()

    def _on_move_landed(self, entry):
        self._first_move_deadline_ms = None
        if entry.gives_checkmate:
            self.sound_manager.play_checkmate()
        elif entry.move.is_castle:
            self.sound_manager.play_castle()
        else:
            self.sound_manager.play_move(entry.move.piece.type)
        if entry.gives_check and not entry.gives_checkmate:
            self.sound_manager.play_check()
            self.board.show_check_gun(entry)
        self._maybe_flash_increment_for(entry.move.piece.color)
        self.skillcheck.clear_locks()

    def _on_shot_fired(self, entry):
        self.sound_manager.play_capture(entry.move.piece.type)

    def _on_kill_announced(self, key, victim=None):
        if key == "hit":
            self.sound_manager.play_hit(victim.type if victim is not None else None)
        elif self.current_result() is None:
            self.sound_manager.play_announcer(key)

    def _maybe_flash_increment_for(self, mover_color):
        clock = self.match.clock
        if clock is None or clock.increment_seconds <= 0:
            return
        self._strip_for_color(mover_color).flash_increment()

    def _strip_for_color(self, color):
        is_white = self._is_white(color)
        top_is_white = self._strip_color_top() == PieceColor.WHITE
        return (self.player_strip_top if is_white == top_is_white
                else self.player_strip_bottom)

    def _strip_color_top(self):
        return PieceColor.WHITE if self.board.flipped else PieceColor.BLACK

    def run(self):
        while self.running:
            frame_start = time.perf_counter()
            if self._last_frame_start is not None:
                self._frame_times.append((frame_start - self._last_frame_start) * 1000.0)
            self._last_frame_start = frame_start
            had_events = self.input_router.check_events()
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

        if self.game_live():
            self.match.tick_clock()

        self.give_time._update_give_time_hold()
        self.settings._flush_deferred_env_writes()
        self._maybe_play_flag_fall()
        self._update_heartbeat()

        now = pg.time.get_ticks()
        post_animation_settled = (
            not self.board.is_animating()
            and not self.board.effects.captures
            and now - self.board.last_animation_completed_at_ms >= AUTO_FLIP_DELAY_MS
        )
        if (self.mode == SINGLE_SCREEN
                and self.current_result() is None
                and post_animation_settled):
            current = self.match.current_turn()
            if current != self._last_turn_for_flip:
                self.board.flipped = (current == PieceColor.BLACK)
                self._last_turn_for_flip = current

        if (self.game_live()
                and post_animation_settled
                and self.skillcheck_session._pending_online_move is None
                and not self.skillcheck_session._skillcheck_swallows_input()):
            self.board.try_apply_next_premove()

        nav = self.screen.update(now)
        if nav is not None:
            self.request_nav(nav)

        self._entering_menu = self.mode == "menu" and self._prev_battle_mode != "menu"
        self._prev_battle_mode = self.mode
        self.reconnect_probe._refresh_reconnect_button()

        self.screen.draw()

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

    def _refresh_game_info(self):
        info = self._compute_game_info()
        if info != self.right_menu.game_info:
            self.right_menu.set_game_info(info)

    def _compute_game_info(self):
        if self.mode == "menu":
            return None
        tc = format_time_control(self._time_control) or "∞"
        rnd = self._current_round()
        if self.pgn_review:
            return {"mode": "Review", "time_control": tc, "round": rnd,
                    "lines": [self._pgn_result_tag or "*"]}
        info = {"mode": MODE_PILL_LABELS.get(self.mode, "Local"),
                "time_control": tc, "round": rnd, "lines": []}
        if self.mode == ONLINE:
            white_score = self.result_flow._series_scores.get(self.white_name, 0.0)
            black_score = self.result_flow._series_scores.get(self.black_name, 0.0)
            info["lines"] = [
                f"{self.white_name}  {_score_str(white_score)} – "
                f"{_score_str(black_score)}  {self.black_name}",
            ]
        return info

    def _current_round(self):
        total = (self.result_flow._series_scores.get(self.white_name, 0.0)
                 + self.result_flow._series_scores.get(self.black_name, 0.0))
        return int(total) + 1

    def _update_player_strips(self):
        top_color = self._strip_color_top()
        bottom_color = opponent_of(top_color)
        turn = self.match.current_turn()
        over = self.current_result() is not None
        self.player_strip_top.set_state(**self._strip_state(top_color, turn, over))
        self.player_strip_bottom.set_state(**self._strip_state(bottom_color, turn, over))

    def _trigger_result_effects(self):
        code = self.current_result()
        if code is None:
            return
        if code.startswith("draw"):
            self.sound_manager.play_draw()
            return
        if code.startswith("white_wins"):
            winner, loser = PieceColor.WHITE, PieceColor.BLACK
        elif code.startswith("black_wins"):
            winner, loser = PieceColor.BLACK, PieceColor.WHITE
        else:
            return
        is_mate = code in ("white_wins", "black_wins")
        is_resign = code.endswith("_by_resignation")
        if is_mate or is_resign:
            self.board.show_surrender_flag(loser)
        if is_mate:
            self.board.show_checkmate_takeover(winner.value.upper())
        if is_mate or is_resign:
            if self._local_won(winner):
                self.sound_manager.play_you_win()
            elif is_resign:
                self.sound_manager.play_surrender()
            elif is_mate:
                self.sound_manager.play_you_lose()

    def _local_won(self, winner):
        return self.mode != ONLINE or self.match.local_color == winner

    def _result_elapsed_ms(self):
        if self._result_first_seen_at_ms is None:
            return None
        return pg.time.get_ticks() - self._result_first_seen_at_ms

    def _result_modal_should_show(self):
        elapsed = self._result_elapsed_ms()
        if elapsed is None:
            return False
        delay = RESULT_TAKEOVER_MS if self.board.effects.has_takeover() else RESULT_MODAL_DELAY_MS
        return elapsed >= delay

    def _draw_game_background(self):
        size = self.window.get_size()
        w, h = size
        if w <= 0 or h <= 0:
            return
        bc = self.board.rect.center
        center = (bc[0] / w, bc[1] / h)
        key = (size, bc)
        if self._game_bg_cache is None or self._game_bg_cache[0] != key:
            self._game_bg_cache = (key, backdrop.arena_background(size, center).convert())
        self.window.blit(self._game_bg_cache[1], (0, 0))

    def _result_fade_surface(self, size):
        def build():
            surf = pg.Surface(size)
            surf.fill((0, 0, 0))
            return surf
        return cache.memoized_surface(_RESULT_FADE_CACHE, size, build)

    def _draw_result_fade_overlay(self):
        elapsed = self._result_elapsed_ms()
        if elapsed is None:
            return
        alpha = min(RESULT_FADE_MAX_ALPHA,
                    int(RESULT_FADE_MAX_ALPHA * elapsed / RESULT_FADE_MS))
        if alpha <= 0:
            return
        overlay = self._result_fade_surface(self.window.get_size())
        overlay.set_alpha(alpha)
        self.window.blit(overlay, (0, 0))

    def _skip_result_fade(self):
        if self._result_first_seen_at_ms is None:
            return
        self.board.effects.clear_takeover()
        self._result_first_seen_at_ms = pg.time.get_ticks() - RESULT_MODAL_DELAY_MS

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

    def _strip_capture_summary(self, color):
        key = (len(self.match.move_history), self.board.review_ply, color)
        cached = self._strip_memo.get(color)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        history = self.match.move_history
        if self.board.review_ply is not None:
            history = history[:self.board.review_ply]
        captured = captured_by(history, color)
        advantage = material_advantage(history, color)
        self._strip_memo[color] = (key, captured, advantage)
        return captured, advantage

    def _strip_state(self, color, turn, over):
        name = self._name_for_color(color)
        seconds = (self.match.clock.remaining(color)
                   if self.match.clock is not None else None)
        initial_seconds = (self.match.clock.initial_seconds
                           if self.match.clock is not None else None)
        active = (color == turn) and not over
        captured, advantage = self._strip_capture_summary(color)
        connection_state = None
        if (self.mode == ONLINE and self.online_client is not None
                and self.match.local_color is not None
                and color != self.match.local_color):
            connection_state = self.online_client.opp_state
        auto_end_label, auto_end_seconds = self._compute_auto_end(color, over)
        is_bot = self.mode == BOT and name == OPPONENT_NAME_FOR_MODE[BOT]
        return {
            "name": name,
            "player_color": color,
            "is_bot": is_bot,
            "rating": PLACEHOLDER_RATING,
            "clock_seconds": seconds,
            "active": active,
            "captured": captured,
            "advantage": advantage,
            "captured_color": opponent_of(color),
            "ko_count": len(captured),
            "connection_state": connection_state,
            "country": self._country_for_color(color),
            "clock_initial_seconds": initial_seconds,
            "auto_end_label": auto_end_label,
            "auto_end_seconds": auto_end_seconds,
        }

    def _compute_auto_end(self, color, over):
        if (self.mode != ONLINE or over or self.match.local_color is None):
            return None, None
        now = pg.time.get_ticks()
        is_local = (color == self.match.local_color)
        if is_local and self._local_disconnected_at_ms is not None:
            return self._auto_end_remaining(
                "Aborting in", self._local_disconnected_at_ms,
                RECONNECT_TOTAL_SECONDS, now,
            )
        if (not is_local
                and self._opp_disconnected_at_ms is not None):
            return self._auto_end_remaining(
                "Abandon in", self._opp_disconnected_at_ms, GRACE_SECONDS, now,
            )
        if (color == self.match.current_turn()
                and not self.match.move_history
                and self._first_move_deadline_ms is not None):
            remaining_ms = self._first_move_deadline_ms - now
            if remaining_ms <= 0:
                return None, None
            remaining = remaining_ms / 1000.0
            elapsed = FIRST_MOVE_ABORT_SECONDS - remaining
            if elapsed < AUTO_END_GATE_FRACTION * FIRST_MOVE_ABORT_SECONDS:
                return None, None
            return "Abort in", remaining
        return None, None

    def _auto_end_remaining(self, label, snap_ms, total_seconds, now_ms):
        elapsed = (now_ms - snap_ms) / 1000.0
        if elapsed < AUTO_END_GATE_FRACTION * total_seconds:
            return None, None
        remaining = total_seconds - elapsed
        if remaining <= 0:
            return None, None
        return label, remaining

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

        self.board.set_rect(r.board_rect)
        self.result_menu.set_rect(r.result_rect)
        self.confirm_modal.set_rect(r.result_modal_rect)
        self.wait_modal.set_rect(r.flex_rect)
        self.match_found_modal.set_rect(r.flex_rect)
        self.reconnecting_modal.set_rect(r.board_rect)
        self.menu_page.set_rect(r.window_rect, r.top, r.start_rect)
        self.menu_battle.top_inset = r.top
        self.menu_battle.set_rect(r.window_rect)
        self.menu_battle.set_avoid_rect(self.menu_page.avoid_rect())
        self.help_modal.set_rect(r.result_rect)
        self.fen_input_modal.set_rect(r.flex_rect)
        self.options_modal.set_rect(r.options_rect)
        self.directory_browser.set_rect(r.wide_overlay_rect)
        self.country_picker.set_rect(r.wide_overlay_rect)
        self._last_layout_mode = self.mode
        self._needs_full_present = True
        self.right_menu.set_rect(r.menu_rect)
        self.player_strip_top.set_rect(r.top_strip_rect)
        self.player_strip_bottom.set_rect(r.bottom_strip_rect)
        skillcheck_target = self.skillcheck_session._skillcheck_target
        if self.skillcheck_overlay.is_active() and skillcheck_target is not None:
            self.skillcheck_overlay.relayout(self.board.cell_rect(skillcheck_target))
            self.skillcheck_overlay.set_board_rect(self.board.rect)
        self._refresh_capture_icons(r.strip_height)

    def _refresh_capture_icons(self, strip_height):
        if not self.board.piece_images_original:
            return
        target = max(int(strip_height * 0.42), 1)
        icons = {
            key: pg.transform.smoothscale(surface, (target, target))
            for key, surface in self.board.piece_images_original.items()
        }
        self.player_strip_top.set_piece_icons(icons)
        self.player_strip_bottom.set_piece_icons(icons)
