import glob
import logging
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import Match, SINGLE_SCREEN, BOT, ONLINE
from chessshootout.backend.fen import apply_fen
from chessshootout.infra import countries, env
from chessshootout.frontend.panels.audio import AudioPanel
from chessshootout.frontend.board import Board
from chessshootout.frontend.skillcheck.overlay import SkillCheckOverlay
from chessshootout.frontend.skillcheck.registry import build_controller
from chessshootout.skillcheck.coordinator import SkillCheckCoordinator
from chessshootout.skillcheck.online import SKILLCHECK_DEADLINE_MS, skillcheck_deadline_ms
from chessshootout.skillcheck.types import KIND_LABEL, SkillCheckKind, SkillCheckOutcome
from chessshootout.skillcheck.wheel import period_for_diff, placement_square
from chessshootout.backend.utils import coord_from_square, PROMO_LETTER_BY_TYPE, Square
from chessshootout.frontend.menu.menu_battle import MenuBattle
from chessshootout.domain.capture_summary import captured_by, material_advantage
from chessshootout.domain.result_stats import compute_result_stats
from chessshootout.frontend.menu.menu_page import MenuPage, PAGE_CARD, PAGE_HISTORY
from chessshootout.frontend.menu.history import HistoryView
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.confirm import ConfirmModal
from chessshootout.frontend.modals.directory_browser import DirectoryBrowser
from chessshootout.frontend.modals.country_picker import CountryPicker
from chessshootout.frontend.modals.fen_input import FenInputModal
from chessshootout.frontend.modals.options import (
    OptionsModal, CountryRow, PathRow, TextRow, ToggleRow, SliderRow, SegmentedRow, SwatchRow,
)
from chessshootout.frontend.modals.help import HelpModal
from chessshootout.frontend.modals.reconnecting import ReconnectingModal
from chessshootout.frontend.visual.toast import Toast
from chessshootout.frontend.visual import backdrop
from chessshootout.frontend.visual import cache
from chessshootout.frontend.visual.effects import TAKEOVER_TOTAL_MS
from chessshootout.frontend.focus import layout as focus_layout
from chessshootout.frontend.focus.arrow import (
    FocusArrow, FOCUS_EDGE_ZONE_PX, FOCUS_ARROW_D, LONG_AGO_MS)
from chessshootout.frontend.focus.time_line import TimeLine
from chessshootout.frontend.focus.transition import FocusTransition
from chessshootout.frontend.window_chrome import (
    WindowChrome, WINDOW_FLAGS, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from chessshootout.online.client import (
    OnlineClient, RECONNECT_TOTAL_SECONDS, fetch_resume, probe_active_game,
)
from chessshootout.frontend.online.events import (
    ONLINE_HARD_FAILURE_LABELS, REMATCH_STATE_TOAST_KEY, OnlineEventsMixin)
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
from chessshootout.domain.pgn.generate import (
    format_annotations, generate_pgn, RESULT_CODES)
from chessshootout.domain.pgn.load import (
    load_pgn_into_backend, parse_comment, parse_time_control)
from chessshootout.paths import SOUNDS_DIR
from chessshootout.backend.pieces import PIECE_VALUES, PieceColor, PieceType, opponent_of
from chessshootout.server.protocol import (
    FIRST_MOVE_ABORT_SECONDS, GIVE_TIME_SECONDS, GIVE_TIME_TICK_MS, GRACE_SECONDS,
)


RESULT_TEXT = {
    "white_wins": ("White wins", "by checkmate"),
    "black_wins": ("Black wins", "by checkmate"),
    "white_wins_on_time": ("White wins", "on time"),
    "black_wins_on_time": ("Black wins", "on time"),
    "white_wins_by_resignation": ("White wins", "by resignation"),
    "black_wins_by_resignation": ("Black wins", "by resignation"),
    "white_wins_by_abandonment": ("White wins", "by abandonment"),
    "black_wins_by_abandonment": ("Black wins", "by abandonment"),
    "draw_stalemate": ("Draw", "by stalemate"),
    "draw_repetition": ("Draw", "by threefold repetition"),
    "draw_fifty_move": ("Draw", "by fifty-move rule"),
    "draw_insufficient_material": ("Draw", "by insufficient material"),
    "draw_agreement": ("Draw", "by agreement"),
    "aborted": ("Game aborted", "no moves played"),
    "aborted_disconnect": ("Game aborted", "opponent disconnected"),
    "server_shutdown": ("Game cancelled", "server shutting down"),
}


def _open_with_default_app(path):
    if sys.platform == "darwin":
        candidates = [["open", path]]
    elif sys.platform.startswith("win"):
        try:
            os.startfile(path)
            return True
        except OSError:
            return False
    else:
        candidates = [
            ["xdg-open", path],
            ["gio", "open", path],
        ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue
    return False


def _score_str(score):
    int_part = int(score)
    has_half = score - int_part >= 0.5 - 1e-9
    if int_part == 0 and has_half:
        return "½"
    if has_half:
        return f"{int_part}½"
    return str(int_part)


OPPONENT_NAME_FOR_MODE = {
    SINGLE_SCREEN: "Player 2",
    BOT: "Bot",
    ONLINE: "Opponent",
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
RIGHT_PANEL_WIDTH = 360
BOARD_AREA_MARGIN = 12
STRIP_MARGIN = 5
STRIP_HEIGHT_RATIO = 0.075
STRIP_GAP_RATIO = 0.015

AUTO_FLIP_DELAY_MS = 200
RESULT_FADE_MS = 400
PERF_SAMPLE_COUNT = 240
PERF_1PCT_PERCENTILE = 0.99
PERF_1PCT_MIN_SAMPLES = 100
PRESENT_SETTLE_MS = 120
RESULT_MODAL_DELAY_MS = 500
RESULT_TAKEOVER_MS = TAKEOVER_TOTAL_MS
RESULT_FADE_MAX_ALPHA = 140

GIVE_TIME_DEBOUNCE_MS = 500
GIVE_TIME_RATCHET_MS_SLOW = 150
GIVE_TIME_RATCHET_MS_FAST = 55
SETTINGS_WRITE_DELAY_MS = 400
AUTO_END_GATE_FRACTION = 0.1
AUTOSAVE_THROTTLE_MS = 1000

ANIM_MS_DEFAULT = 180
ANIM_MS_MIN = 140
ANIM_MS_MAX = 280
ANIM_MS_PER_SECOND = 0.5

PANEL_WIDTH_RATIO = 0.42
RESULT_HEIGHT_RATIO = 0.95
WAIT_HEIGHT_RATIO = 1.6
MENU_FOOTER_RESERVE = 22
MIN_MODAL_WIDTH = 360

RESYNC_TIMEOUT_MS = 8000
SKILLCHECK_WATCHDOG_SLACK_MS = 4000
RESULT_CONFIRM_TIMEOUT_MS = 4000
RECONNECT_MODAL_DEBOUNCE_MS = 500
RECONNECT_PROBE_INTERVAL_MS = 5000
RECONNECT_PROBE_MAX_ATTEMPTS = 3

ONLINE_DEFAULT_TIME_MINUTES = 5

WINDOW_TITLE = "Chess Shootout"


def _games_dir():
    return str(paths.get_games_dir())


PROMOTION_KEYS = {
    pg.K_q: PieceType.QUEEN,
    pg.K_r: PieceType.ROOK,
    pg.K_b: PieceType.BISHOP,
    pg.K_n: PieceType.KNIGHT,
}


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
        self._deferred_env_writes = {}
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
        self.pgn_review = False
        self._flag_fall_played = False
        self._click_sound_played = False
        self._game_bg_cache = None
        self._needs_full_present = True
        self._frame_times = deque(maxlen=PERF_SAMPLE_COUNT)
        self._last_work_ms = 0.0
        self._last_frame_start = None
        self._result_cache_key = None
        self._result_cache = None
        self._strip_memo = {}
        self._result_first_seen_at_ms = None
        self._pgn_result_tag = None
        self._match_session_id = None
        self._review_return_page = None
        self._series_scores = {}
        self._series_score_awarded = False
        self._save_failed = False
        self._save_error_toast_shown = False
        self._autosave_last_write_ms = -AUTOSAVE_THROTTLE_MS
        self._autosave_last_ply = 0
        self._resyncing = False
        self._resync_started_at_ms = 0
        self._last_heartbeat_sent_ms = 0
        self._last_give_time_at_ms = -GIVE_TIME_DEBOUNCE_MS
        self._give_time_holding = False
        self._give_time_hold_start_ms = 0
        self._give_time_hold_last_tick_ms = 0
        self._give_time_last_ratchet_ms = 0
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0
        self._give_time_hold_recipient = None
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
        self._clear_online_skillcheck_state()
        self._skillcheck_log = []
        self.board.skillcheck_gate = self._skillcheck_gate
        self.board.skillcheck_armed = lambda: self.skillcheck.enabled
        self.board.locked_targets = self.skillcheck.is_locked
        self.result_menu = ResultMenu(self.window, {
            "new_game": self._on_new_game,
            "open_pgn": self._on_open_pgn,
            "menu": self._on_back_to_menu,
            "rematch": self._on_rematch,
        })
        self.start_menu = StartMenu(self.window, {
            "start_game": self._on_start_game,
            "load_pgn": self._on_open_history,
            "fen": self._on_open_fen_modal,
            "reconnect": self._on_reconnect_active_game,
            "options": self._on_open_options,
            "open_url": _open_with_default_app,
            "toast": lambda msg: self.toast.show(msg),
        })
        self._pending_reconnect = None
        self._pending_reconnect_lock = threading.Lock()
        self._last_reconnect_probe_ms = 0
        self._reconnect_probe_inflight = False
        self._reconnect_probe_gen = 0
        self._reconnect_probe_attempts = 0
        self.audio_panel = AudioPanel(self.window, self.sound_manager)
        self.right_menu = RightMenu(self.window, self.match, {
            "undo": self._on_undo,
            "resign": self._on_resign,
            "draw": self._on_draw,
            "flip": self._on_flip,
            "menu": self._on_back_to_menu,
            "help": self._on_help,
            "give_time": self._on_give_time,
        }, board=self.board, buttons_provider=self._right_menu_buttons,
            audio_panel=self.audio_panel,
            disabled_keys_provider=self._right_menu_disabled_keys,
            whiffs_provider=self._skillcheck_whiffs)
        self.confirm_modal = ConfirmModal(self.window)
        self.history_view = HistoryView(self.window, on_open=self._load_pgn_from_path,
                                        on_back=self._on_menu_back)
        self.menu_page = MenuPage(self.window, self.start_menu, self.history_view)
        self.help_modal = HelpModal(self.window)
        self.fen_input_modal = FenInputModal(self.window)
        self.options_modal = OptionsModal(self.window)
        self.directory_browser = DirectoryBrowser(self.window)
        self.country_picker = CountryPicker(self.window)
        self._data_folder_row = None
        self._server_addr_row = None
        self.toast = Toast(self.window)
        self.toast.top_inset = self.chrome.HEIGHT
        self.toast.on_new = lambda: self.sound_manager.play_toast()
        if env.normalize_stored_nickname():
            self.start_menu.text_input.text = env.get_nickname()
            self.toast.show("Your nickname contained non ASCII symbols, I cleaned them :3")
        self._probe_games_dir_writable()
        self._last_saved_pgn_path = None
        self._last_saved_result_tag = None
        self._result_await_since_ms = None
        self.wait_modal = WaitModal(self.window)
        self.match_found_modal = MatchFoundModal(self.window)
        self.reconnecting_modal = ReconnectingModal(self.window)
        self.offer_banners = OfferBanners(self.window)
        self._modal_registry = [
            ModalSpec(self.confirm_modal, on_dismiss=self._dismiss_confirm),
            ModalSpec(self.help_modal),
            ModalSpec(self.fen_input_modal),
            ModalSpec(self.wait_modal, on_dismiss=self._on_online_cancel),
            ModalSpec(self.match_found_modal, esc_dismiss=False),
            ModalSpec(self.reconnecting_modal, esc_dismiss=False),
            ModalSpec(self.country_picker),
            ModalSpec(self.directory_browser),
            ModalSpec(self.options_modal, on_dismiss=self._dismiss_options),
        ]
        self._wait_started_at_ms = None
        self._match_found_at_ms = None
        self._pending_game_start_payload = None
        self._rematch_offered = False
        self.online_client = None
        self.player_strip_top = PlayerStrip(self.window)
        self.player_strip_bottom = PlayerStrip(self.window)
        self.menu_battle = MenuBattle(self.window, sound_manager=self.sound_manager)
        self._scroll_pressed = None
        self.focus_mode = False
        self.focus_transition = None
        self.focus_arrow = FocusArrow()
        self.time_line = TimeLine()
        self._focus_click_consumed = False
        self._focus_panel_hover_ms = LONG_AGO_MS
        self._focus_hint_until_ms = 0
        self._focus_prev_mode = "menu"

        self.match.new_game()
        self.board.load_assets()
        self._compute_layout()
        self._refresh_load_pgn_availability()
        self._settle_window()
        self._spawn_reconnect_probe()

        pg.display.set_caption(WINDOW_TITLE)

    @property
    def backend(self):
        return self.match.backend

    def current_result(self):
        clock = self.match.clock
        flagged = clock.flagged if clock is not None else None
        history = self.match.move_history
        last_move = history[-1].move if history else None
        key = (len(history), last_move, self.manual_result, flagged)
        if key != self._result_cache_key:
            self._result_cache_key = key
            self._result_cache = self.manual_result or self.match.game_result()
        return self._result_cache

    def result_text(self):
        code = self.current_result()
        if code is None:
            return None
        return RESULT_TEXT.get(code)

    def _feed_result_menu(self):
        code = self.current_result()
        text = self.result_text()
        if code is None or text is None:
            self.result_menu.set_result(None, "draw", "")
            return
        title, reason = text
        word, intent = self._outcome_word_intent(code, title)
        moves = (len(self.match.move_history) + 1) // 2
        full_reason = f"{reason} · {moves} moves" if reason else f"{moves} moves"
        subject = self._result_subject_color(code)
        stats = compute_result_stats(self.match.move_history, self.match.clock, subject)
        self.result_menu.set_result(word, intent, full_reason, stats)
        if self.mode == ONLINE:
            self.result_menu.set_series(
                self.white_name, self.black_name,
                _score_str(self._series_scores.get(self.white_name, 0.0)),
                _score_str(self._series_scores.get(self.black_name, 0.0)))
        else:
            self.result_menu.set_series(None, None, None, None)

    def _perspective_color(self):
        if self.mode in (ONLINE, BOT):
            return self.match.local_color
        return None

    def _outcome_word_intent(self, code, title):
        if code.startswith("draw"):
            return "DRAW", "draw"
        winner = PieceColor.WHITE if code.startswith("white_wins") else PieceColor.BLACK
        local = self._perspective_color()
        if local is not None:
            if winner == local:
                return "VICTORY", "win"
            return "DEFEAT", "loss"
        return title.upper(), "win"

    def _result_subject_color(self, code):
        local = self._perspective_color()
        if local is not None:
            return local
        if code.startswith("black_wins"):
            return PieceColor.BLACK
        return PieceColor.WHITE

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
                self._finalize_result(pending_result)
        keep_online = (self.mode == ONLINE and self.online_client is not None
                       and self.current_result() is not None)
        had_rematch_offer = self._rematch_offered
        self.mode = "menu"
        self._match_session_id = None
        self._reconnect_probe_attempts = 0
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

    def _on_open_options(self):
        self.options_modal.show(self._build_settings_sections(),
                                on_close=self._on_close_settings)

    def _on_close_settings(self):
        if not self._validate_data_folder_on_close():
            return False
        if self._server_addr_row is not None:
            env.set_server_addr(self._server_addr_row.current_text())
        self.start_menu.apply_default_time_settings()
        return True

    def _validate_data_folder_on_close(self):
        if self._data_folder_row is None:
            return True
        typed = self._data_folder_row.current_text()
        if not typed:
            return True
        typed = os.path.abspath(os.path.expanduser(typed))
        if os.path.normpath(typed) == os.path.normpath(str(paths.get_data_dir())):
            return True
        if not paths.is_writable_dir(typed):
            self.toast.show("That folder isn't writable")
            return False
        self._apply_data_folder_change(typed)
        return True

    def _set_master_volume(self, value):
        self.sound_manager.set_master_volume(value)

    def _set_menu_volume(self, value):
        self.sound_manager.set_menu_volume(value)

    def _commit_master_volume(self):
        env.set_master_volume(self.sound_manager.master_volume)

    def _commit_menu_volume(self):
        env.set_menu_volume(self.sound_manager.menu_volume)

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

    def _build_settings_sections(self):
        self._data_folder_row = PathRow(
            "Games folder", "Where PGNs are saved", self.window,
            lambda: str(paths.get_data_dir()),
            self._on_change_data_folder, self._on_reset_data_folder,
            suffix="/" + paths.GAMES_SUBDIR)
        self._server_addr_row = TextRow(
            "Server", "Where online games connect and reconnect",
            self.window, env.get_server_addr, placeholder="host or host:port")
        time_options = [(label, label) for label in env.TIME_CONTROL_VALUES]
        incr_options = [(label, label) for label in env.INCREMENT_VALUES]
        themes = [
            ("dark", "#7a818b", "#2f343b", False),
            ("wood", "#d8b483", "#8a5a3c", True),
            ("green", "#b9c4a0", "#516b3e", True),
            ("ice", "#b4c2d4", "#4a5a72", True),
        ]
        return [
            ("Profile", [
                CountryRow("Country", "Shows your flag on the player strip",
                           env.get_country, self._on_pick_country),
            ]),
            ("Audio", [
                SliderRow("Master volume", "", lambda: self.sound_manager.master_volume,
                          self._set_master_volume, on_tick=self.sound_manager.play_ui_tick,
                          on_release=lambda: self._defer_env_write(
                              "master_volume", self._commit_master_volume)),
                SliderRow("Menu volume", "", lambda: self.sound_manager.menu_volume,
                          self._set_menu_volume, on_tick=self.sound_manager.play_ui_tick,
                          on_release=lambda: self._defer_env_write(
                              "menu_volume", self._commit_menu_volume)),
                ToggleRow("Mute all sound", "Silence every shot and callout",
                          lambda: not self.sound_manager.enabled,
                          lambda muted: self.sound_manager.set_enabled(not muted)),
            ]),
            ("Appearance", [
                SwatchRow("Board theme", "More themes coming soon", themes,
                          env.get_theme, env.set_theme),
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
                             env.set_default_time_control, mono=True),
                SegmentedRow("Default increment", "Seconds added each move",
                             incr_options, env.get_default_increment,
                             env.set_default_increment, mono=True),
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

    def _on_pick_country(self):
        self.country_picker.show(env.get_country(), self._apply_country_choice)

    def _apply_country_choice(self, code):
        env.set_country(code)

    def _on_change_data_folder(self):
        self.directory_browser.show(
            str(paths.get_data_dir()),
            on_select=self._apply_data_folder_change,
            on_error=self.toast.show,
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
            self.confirm_modal.show(
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
        if to_default:
            env.set_data_dir(None)
        else:
            env.set_data_dir(new_dir)
        self._refresh_load_pgn_availability()
        self.toast.show("Data folder updated")

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
            self.toast.show("Could not move games")
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

    def _on_open_fen_modal(self):
        self.fen_input_modal.show(on_submit=self._start_game_from_fen)

    def _start_game_from_fen(self, fen):
        try:
            apply_fen(self.match.backend, fen)
        except (ValueError, KeyError):
            return False
        self.mode = SINGLE_SCREEN
        self._drop_post_game_online_session()
        self._time_control = None
        self._chosen_side = "white"
        self.white_name = "Player 1"
        self.black_name = "Player 2"
        self.white_country = env.get_country()
        self.black_country = countries.random_code()
        self.match.mode = SINGLE_SCREEN
        self.match.local_color = None
        self._ensure_local_session()
        self._reset_to_new_game()
        apply_fen(self.match.backend, fen)
        self.fen_input_modal.hide()
        self.start_menu.hide()
        return True

    def _load_pgn_from_path(self, path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.mode = SINGLE_SCREEN
        self._drop_post_game_online_session()
        self._time_control = None
        self._reset_to_new_game()
        parsed, ok = load_pgn_into_backend(self.match, text)
        if not ok:
            self.mode = "menu"
            self.menu_page.set_page(PAGE_HISTORY)
            self.toast.show("Could not load PGN")
            return
        self._rebuild_skillcheck_log(parsed.move_comments)
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

    def _spawn_reconnect_probe(self):
        addr = env.get_server_addr()
        client_uuid = env.get_or_create_client_uuid()
        if (not addr or not client_uuid or self._reconnect_probe_inflight
                or self._reconnect_probe_attempts >= RECONNECT_PROBE_MAX_ATTEMPTS):
            return
        with self._pending_reconnect_lock:
            if self._pending_reconnect is not None:
                return
        self._last_reconnect_probe_ms = pg.time.get_ticks()
        self._reconnect_probe_inflight = True
        with self._pending_reconnect_lock:
            self._reconnect_probe_gen += 1
            gen = self._reconnect_probe_gen
        thread = threading.Thread(
            target=self._reconnect_probe_worker,
            args=(addr, client_uuid, gen),
            daemon=True,
        )
        thread.start()

    def _reconnect_probe_worker(self, addr, client_uuid, gen):
        try:
            reclaim = probe_active_game(addr, client_uuid)
            resume = (fetch_resume(addr, reclaim["room_id"], reclaim["session_token"])
                      if reclaim is not None else None)
            with self._pending_reconnect_lock:
                if gen != self._reconnect_probe_gen:
                    return
                if reclaim is None or resume is None:
                    self._pending_reconnect = None
                    self._reconnect_probe_attempts += 1
                else:
                    self._pending_reconnect = {
                        "addr": addr,
                        "room_id": reclaim["room_id"],
                        "session_token": reclaim["session_token"],
                    }
        finally:
            self._reconnect_probe_inflight = False

    def _refresh_reconnect_button(self):
        if (self.mode == "menu" and self.online_client is None
                and pg.time.get_ticks() - self._last_reconnect_probe_ms
                >= RECONNECT_PROBE_INTERVAL_MS):
            self._spawn_reconnect_probe()
        with self._pending_reconnect_lock:
            available = self._pending_reconnect is not None
        self.start_menu.set_reconnect_available(available)

    def _on_reconnect_active_game(self):
        with self._pending_reconnect_lock:
            self._reconnect_probe_gen += 1
            pending = self._pending_reconnect
            self._pending_reconnect = None
        if pending is None:
            return
        self.start_menu.set_reconnect_available(False)
        resume = fetch_resume(
            pending["addr"], pending["room_id"], pending["session_token"],
        )
        if resume is None:
            log.warning("reconnect: fresh /resume failed; restoring pending entry")
            with self._pending_reconnect_lock:
                self._pending_reconnect = pending
            self.start_menu.set_reconnect_available(True)
            self.confirm_modal.show(
                ONLINE_HARD_FAILURE_LABELS["reconnect_failed"],
                on_yes=self._on_reconnect_active_game,
                on_no=lambda: None,
                yes_label="Retry", no_label="Cancel",
            )
            return
        nickname = (resume["white_name"] if resume["your_color"] == "white"
                    else resume["black_name"])
        self.start_menu.text_input.text = nickname
        self.start_menu.selected_mode = ONLINE
        self.start_menu.selected_time_minutes = resume["time_minutes"]
        self.start_menu.selected_increment_seconds = resume["increment_seconds"]
        self.start_menu.selected_side = resume["your_color"]
        self.online_client = OnlineClient()
        self.match.on_local_move_applied = self._on_local_move_applied
        self._start_online_game(resume)
        self._handle_game_resumed(resume)
        self.online_client.reconnect_to_existing(
            pending["addr"], pending["room_id"], pending["session_token"], resume,
        )
        self.start_menu.hide()

    def _on_start_game(self, config):
        env.set_last_mode(config["mode"])
        env.set_nickname(config.get("nickname") or "")
        if config["mode"] == ONLINE:
            self._begin_online_flow(config)
            return
        if config["mode"] != SINGLE_SCREEN:
            return

        self.mode = SINGLE_SCREEN
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
            self.online_client.send_rematch_response(True)
        else:
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

    def _tear_down_online_session(self):
        self._auto_save_pgn()
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
        self.mode = "menu"
        pg.display.set_caption(WINDOW_TITLE)
        self._reset_to_new_game()
        self._refresh_load_pgn_availability()

    def _return_to_menu_card(self):
        self.mode = "menu"
        self._reconnect_probe_attempts = 0
        self.start_menu.show()
        self.menu_page.set_page(PAGE_CARD)

    def _abandon_online_game(self):
        log.info("abandoning online game (reconnect cancelled)")
        self._tear_down_online_session()
        self._return_to_menu_card()

    def _restart_online_search(self):
        log.info("restarting online search")
        self._tear_down_online_session()
        if getattr(self, "_online_config", None) is not None:
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

    def _promote_awaited_result(self, engine_result):
        now = pg.time.get_ticks()
        if self._result_await_since_ms is None:
            self._result_await_since_ms = now
            return
        if now - self._result_await_since_ms < RESULT_CONFIRM_TIMEOUT_MS:
            return
        self._finalize_result(engine_result)
        log.info("promoted unconfirmed online result locally: %s", engine_result)

    def _award_series_win(self, winner):
        name = self._name_for_color(winner)
        self._series_scores[name] = self._series_scores.get(name, 0.0) + 1

    def _award_series_draw(self):
        for name in (self.white_name, self.black_name):
            self._series_scores[name] = self._series_scores.get(name, 0.0) + 0.5

    def _tick_skillcheck_watchdog(self):
        if (self._online_skillcheck is None
                or self._online_skillcheck_opened_ms is None
                or not self.skillcheck_overlay.is_active()):
            return
        elapsed = pg.time.get_ticks() - self._online_skillcheck_opened_ms
        if elapsed > SKILLCHECK_DEADLINE_MS + SKILLCHECK_WATCHDOG_SLACK_MS:
            log.warning("skillcheck verdict lost; resyncing")
            self._teardown_skillcheck_overlay()
            self._begin_resync()

    def _send_heartbeat_if_due(self):
        if self.online_client is None or not self.online_client.is_connected():
            return
        if self.online_client.is_server_silent():
            log.info("server heartbeat silent; escalating to reconnect")
            self.online_client.force_reconnect()
            return
        if self._online_verdict_action is not None:
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
        if self._give_time_on_cooldown():
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
        self._cancel_give_time_hold()
        self.manual_result = None
        self._flag_fall_played = False
        self._result_cache_key = None
        self._result_cache = None
        self._strip_memo = {}
        self._result_first_seen_at_ms = None
        self._pgn_result_tag = None
        self._last_saved_pgn_path = None
        self._last_saved_result_tag = None
        self._result_await_since_ms = None
        self._series_score_awarded = False
        self._save_failed = False
        self._save_error_toast_shown = False
        self._autosave_last_write_ms = -AUTOSAVE_THROTTLE_MS
        self._autosave_last_ply = 0
        self.right_menu.reset_for_new_game()
        self.match.new_game()
        if self._time_control is not None:
            initial, incr = self._time_control
            self.match.setup_clock(initial, incr)
            self.board.animation_duration_ms = compute_animation_ms(initial)
        else:
            self.board.animation_duration_ms = ANIM_MS_DEFAULT
        self.board.flipped = False
        self.board.selected_square = None
        self.board.pending_promotion_square = None
        self.board._promotion_from = None
        self.board.cancel_animations()
        self.board.effects.clear()
        self.board._clear_premoves()
        self.skillcheck_overlay.cancel()
        self.board.aim_suppressed_square = None
        self.skillcheck.clear_locks()
        self._clear_online_skillcheck_state()
        self._skillcheck_log = []
        self.board.clear_annotations()
        self.board.end_press()
        self.board.review_ply = None
        self.confirm_modal.hide()
        self._last_turn_for_flip = None

    def _focus_show(self):
        return env.get_focus_show()

    def _focus_available(self):
        return (self.mode != "menu"
                and not self.pgn_review
                and self.current_result() is None
                and not self.skillcheck_overlay.is_active()
                and not self.board.is_dragging()
                and self.board.pending_promotion_square is None
                and not self._menu_overlay_active())

    def _focus_arrow_allowed(self):
        return (not self.pgn_review
                and self.current_result() is None
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

    def _draw_game_children(self):
        self._sync_aim_check_gun()
        self._draw_game_background()
        self.board.draw_board()
        self._update_player_strips()
        self._refresh_game_info()
        self.player_strip_top.draw()
        self.player_strip_bottom.draw()
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

    def _draw_time_lines(self, board_rect=None, alpha=1.0):
        if self._focus_show() != "line" or self._time_control is None:
            return
        self.time_line.draw(self.window, self.board, self.match.clock,
                            self.match.current_turn(), board_rect or self.board.rect, alpha)

    def _on_open_pgn(self):
        path = self._last_saved_pgn_path
        if path is None or not os.path.exists(path):
            self.toast.show("No saved PGN")
            return
        if not _open_with_default_app(path):
            self.toast.show("Could not open PGN")

    def _probe_games_dir_writable(self):
        games_dir = _games_dir()
        try:
            os.makedirs(games_dir, exist_ok=True)
        except OSError:
            self.toast.show("Games folder isn't writable — check your data folder")
            return
        if not paths.is_writable_dir(games_dir):
            self.toast.show("Games folder isn't writable — check your data folder")

    def _show_save_error_toast_once(self):
        if self._save_error_toast_shown:
            return
        self._save_error_toast_shown = True
        self.toast.show("Could not save PGN — check games folder")

    def _remove_quietly(self, path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _reserve_pgn_path(self, directory, prefix):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            log.exception("pgn autosave: could not create games dir %s", directory)
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for suffix in range(1, 1000):
            name = (f"{prefix}-{stamp}.pgn" if suffix == 1
                    else f"{prefix}-{stamp}-{suffix}.pgn")
            candidate = os.path.join(directory, name)
            try:
                with open(candidate, "x", encoding="utf-8"):
                    pass
                return candidate
            except FileExistsError:
                continue
            except OSError:
                log.exception("pgn autosave: could not reserve %s", candidate)
                return None
        return None

    def _write_pgn_atomic(self, path, text):
        directory = os.path.dirname(path)
        tmp_path = os.path.join(directory, f".{os.path.basename(path)}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)
        except (OSError, UnicodeError):
            log.exception("pgn autosave: could not write %s", path)
            self._remove_quietly(tmp_path)
            return "hard_failure"
        try:
            os.replace(tmp_path, path)
        except PermissionError:
            log.debug("pgn autosave: replace skipped (permission) for %s", path)
            self._remove_quietly(tmp_path)
            return "permission_transient"
        except OSError:
            log.exception("pgn autosave: could not replace %s", path)
            self._remove_quietly(tmp_path)
            return "hard_failure"
        return "ok"

    def _commit_pgn_write(self, directory, prefix, text):
        path = self._last_saved_pgn_path
        if path is None or os.path.dirname(path) != os.path.normpath(directory):
            path = self._reserve_pgn_path(directory, prefix)
            if path is None:
                return "hard_failure"
            self._last_saved_pgn_path = path
        return self._write_pgn_atomic(path, text)

    def _auto_save_pgn(self):
        if not self.match.move_history:
            return None
        tag = RESULT_CODES.get(self.current_result(), "*")
        if self._last_saved_pgn_path is not None:
            already_final = self._last_saved_result_tag not in (None, "*")
            if already_final:
                return self._last_saved_pgn_path
        text = self._build_pgn_text()
        prefix = self._auto_save_prefix()
        primary_dir = _games_dir()
        outcome = self._commit_pgn_write(primary_dir, prefix, text)
        if outcome == "hard_failure":
            self._show_save_error_toast_once()
            fallback_dir = str(paths.get_fallback_data_dir() / paths.GAMES_SUBDIR)
            if os.path.normpath(fallback_dir) == os.path.normpath(primary_dir):
                self._save_failed = True
                return None
            self._last_saved_pgn_path = None
            outcome = self._commit_pgn_write(fallback_dir, prefix, text)
            if outcome != "ok":
                self._save_failed = True
                return None
        if outcome != "ok":
            return None
        self._save_failed = False
        path = self._last_saved_pgn_path
        self._last_saved_result_tag = tag
        if tag != "*":
            self.toast.show(f"Saved {os.path.basename(path)}")
        return path

    def _auto_save_prefix(self):
        if self.mode == ONLINE:
            return "online"
        if self.mode == BOT:
            return "bot"
        return "local"

    def _update_incremental_autosave(self):
        if (self.mode == "menu" or self.pgn_review or self._save_failed
                or self.current_result() is not None):
            return
        ply_count = len(self.match.move_history)
        if ply_count == 0 or ply_count == self._autosave_last_ply:
            return
        now = pg.time.get_ticks()
        if now - self._autosave_last_write_ms < AUTOSAVE_THROTTLE_MS:
            return
        self._autosave_last_write_ms = now
        self._autosave_last_ply = ply_count
        self._auto_save_pgn()

    def _on_result_final(self, code):
        if code is None:
            return
        if not self._series_score_awarded and self.mode == ONLINE:
            if code.startswith("white_wins"):
                self._award_series_win("white")
                self._series_score_awarded = True
            elif code.startswith("black_wins"):
                self._award_series_win("black")
                self._series_score_awarded = True
            elif code.startswith("draw"):
                self._award_series_draw()
                self._series_score_awarded = True
        self._auto_save_pgn()

    def _finalize_result(self, code):
        self._result_await_since_ms = None
        if self.manual_result is None:
            self.manual_result = code
        self._on_result_final(code)

    def _ensure_local_session(self):
        if self._match_session_id is None:
            self._match_session_id = str(uuid.uuid4())

    def _session_id_for_online(self):
        if self.online_client is not None and self.online_client.room_id:
            return self.online_client.room_id
        return str(uuid.uuid4())

    def _build_pgn_text(self):
        result = self.current_result()
        time_control = self._time_control
        return generate_pgn(
            self.match.move_history, result,
            white_name=self.white_name, black_name=self.black_name,
            time_control=time_control,
            match_id=self._match_session_id,
            annotations=format_annotations(self._skillcheck_log),
        )

    def _on_undo(self):
        if self.pgn_review or self.current_result() is not None:
            return
        if self.mode == ONLINE and self.online_client is not None:
            self.online_client.send_takeback_request()
            return
        self.board.selected_square = None
        self.board._clear_premoves()
        self.skillcheck.clear_locks()
        self.board.clear_annotations()
        self.board.review_ply = None
        self.board.cancel_animations()
        if not self.match.move_history:
            return
        self.sound_manager.play_undo()
        self._drop_skillcheck_log_from(len(self.match.move_history))
        move = self.match.move_history[-1].move
        self.match.undo()
        self.board.start_undo_animation(move)

    def _handle_escape(self):
        if self._skillcheck_swallows_input():
            return
        if self._dismiss_top_modal():
            return
        if self.mode == "menu":
            if self.menu_page.page != PAGE_CARD:
                self._on_menu_back()
            else:
                self._show_quit_modal()
            return
        if self.pgn_review or self.current_result() is not None:
            self._on_back_to_menu()
            return
        if self.focus_mode or self.focus_transition is not None:
            self._toggle_focus(False)
            return
        self._on_resign()

    def _dismiss_confirm(self):
        self.confirm_modal.hide()
        if self.mode == "menu":
            self.start_menu.show()

    def _dismiss_options(self):
        if self._on_close_settings() is not False:
            self.options_modal.hide()

    def _top_visible_modal(self):
        for spec in self._modal_registry:
            if spec.obj.is_visible():
                return spec
        return None

    def _dismiss_top_modal(self):
        for spec in self._modal_registry:
            if spec.esc_dismiss and spec.obj.is_visible():
                spec.on_dismiss()
                return True
        if not self.offer_banners.is_empty():
            if self._rematch_offered:
                self._decline_rematch()
            self.offer_banners.clear()
            return True
        return False

    def _show_quit_modal(self):
        self.start_menu.hide()
        self.confirm_modal.show(
            "Leaving so soon?", on_yes=self._quit_app, on_no=self._cancel_quit,
            yes_label="See ya!", no_label="Cancel")

    def _quit_app(self):
        self.running = False

    def _cancel_quit(self):
        self.start_menu.show()

    def _on_resign(self):
        if self.pgn_review or self.current_result() is not None:
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
        self.board._clear_premoves()
        self.board.clear_annotations()
        self._on_result_final(self.manual_result)

    def _on_draw(self):
        if self.pgn_review or self.current_result() is not None:
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
            self.online_client.send_draw_offer()
            return
        self._auto_complete_pending_promotion()
        self.manual_result = "draw_agreement"
        self.board._clear_premoves()
        self.board.clear_annotations()
        self._on_result_final(self.manual_result)

    def _give_time_on_cooldown(self):
        return pg.time.get_ticks() - self._last_give_time_at_ms < GIVE_TIME_DEBOUNCE_MS

    def _on_give_time(self):
        if self._give_time_holding:
            return
        if self.pgn_review or self.current_result() is not None:
            return
        if self._give_time_on_cooldown():
            return
        clock = self.match.clock
        if clock is None or clock.flagged is not None:
            return
        recipient = self._give_time_recipient()
        if clock.initial_seconds - clock.remaining(recipient) <= 0:
            self._give_time_toast_for_giver(recipient, 0)
            return
        now = pg.time.get_ticks()
        self._give_time_holding = True
        self._give_time_hold_start_ms = now
        self._give_time_hold_last_tick_ms = now
        self._give_time_last_ratchet_ms = now
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0
        self._give_time_hold_recipient = recipient

    def _update_give_time_hold(self):
        if not self._give_time_holding:
            return
        clock = self.match.clock
        if (self.pgn_review or self.current_result() is not None
                or self._resyncing or self.skillcheck_overlay.is_active()
                or self._menu_overlay_active()
                or clock is None or clock.flagged is not None):
            self._cancel_give_time_hold()
            return
        if not pg.mouse.get_pressed()[0] or not self._pointer_over_give_button():
            self._end_give_time_hold()
            return
        now = pg.time.get_ticks()
        recipient = self._give_time_hold_recipient
        while now - self._give_time_hold_last_tick_ms >= GIVE_TIME_TICK_MS:
            self._give_time_hold_last_tick_ms += GIVE_TIME_TICK_MS
            added = clock.add_time(recipient, GIVE_TIME_SECONDS)
            if added <= 0:
                self._end_give_time_hold()
                return
            self._give_time_hold_added += added
            self._give_time_hold_ticks += 1
        self._maybe_play_give_ratchet(now, recipient, clock)

    def _maybe_play_give_ratchet(self, now, recipient, clock):
        fill = 1.0
        if clock.initial_seconds > 0:
            fill = min(1.0, clock.remaining(recipient) / clock.initial_seconds)
        interval = (GIVE_TIME_RATCHET_MS_SLOW
                    + (GIVE_TIME_RATCHET_MS_FAST - GIVE_TIME_RATCHET_MS_SLOW) * fill)
        if now - self._give_time_last_ratchet_ms >= interval:
            self._give_time_last_ratchet_ms = now
            self.sound_manager.play_give_ratchet()

    def _end_give_time_hold(self):
        if not self._give_time_holding:
            return
        recipient = self._give_time_hold_recipient
        now = pg.time.get_ticks()
        hold_ms = now - self._give_time_hold_start_ms
        clock = self.match.clock
        if self._give_time_hold_ticks == 0 and clock is not None:
            added = clock.add_time(recipient, GIVE_TIME_SECONDS)
            if added > 0:
                self._give_time_hold_added += added
                self._give_time_hold_ticks = 1
        total = self._give_time_hold_added
        self._give_time_holding = False
        self._give_time_hold_recipient = None
        self._last_give_time_at_ms = now
        if self.mode == ONLINE and self.online_client is not None:
            self.online_client.send_give_time(hold_ms)
            return
        self._give_time_toast_for_giver(recipient, total)

    def _cancel_give_time_hold(self):
        self._give_time_holding = False
        self._give_time_hold_recipient = None
        self._give_time_hold_ticks = 0
        self._give_time_hold_added = 0.0

    def _pointer_over_give_button(self):
        rect = self.right_menu.button_rects.get("give_time")
        return rect is not None and rect.collidepoint(pg.mouse.get_pos())

    def _give_time_recipient(self):
        if self.mode == ONLINE and self.match.local_color is not None:
            return opponent_of(self.match.local_color)
        return self.match.current_turn()

    def _give_time_toast_for_giver(self, recipient_color, added):
        name = self._name_for_color(recipient_color)
        if added <= 0:
            self.toast.show(f"{name} already at maximum time")
        else:
            self._strip_for_color(recipient_color).flash_increment(added)
            self.toast.show(f"Gave {int(round(added))} sec to {name}")
            self.sound_manager.play_give_time()

    def _give_time_toast_for_receiver(self, giver_color, added):
        if added <= 0:
            return
        if self.match.local_color is not None:
            self._strip_for_color(self.match.local_color).flash_increment(added)
        name = self._name_for_color(giver_color)
        self.toast.show(f"{name} gave you {int(round(added))} seconds")
        self.sound_manager.play_give_time()

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

    def _skillcheck_gate(self, from_sq, to_sq, promo_type=None):
        if self.skillcheck.is_locked(from_sq, to_sq) or self._skillcheck_swallows_input():
            return True
        if self.mode == ONLINE:
            return self._online_move_gate(from_sq, to_sq, promo_type)
        kind = self.skillcheck.select(self.match.backend, from_sq, to_sq)
        if kind == SkillCheckKind.NONE:
            return False
        diff = self._capture_value_diff(from_sq, to_sq, promo_type)
        seed = "{}:{}:{}{}{}{}:{}".format(
            self.skillcheck.seed, len(self.match.move_history),
            from_sq.row, from_sq.col, to_sq.row, to_sq.col, kind.value)
        return self._open_skillcheck_overlay(
            kind, seed, diff, self._skillcheck_deadline_ms(),
            from_sq, to_sq, promo_type, online=False)

    def _online_move_gate(self, from_sq, to_sq, promo_type=None):
        if to_sq not in self.match.legal_moves_from(from_sq):
            return False
        piece = self.match.piece_at(from_sq)
        is_capture = self.board._capture_victim_square(piece, from_sq, to_sq) is not None
        is_promotion = (piece.type == PieceType.PAWN
                        and to_sq.row in (0, self.board.SIZE - 1))
        if not (is_capture or is_promotion):
            return False
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type is not None else None
        if self.online_client is not None:
            self.online_client.send_move(
                coord_from_square(from_sq), coord_from_square(to_sq), promo_letter)
        self._pending_online_move = (from_sq, to_sq, promo_type)
        return True

    def _open_skillcheck_overlay(self, kind, seed, value_diff, deadline_ms,
                                 from_sq, to_sq, promo_type, *, online,
                                 elapsed_ms=0, miss_count=0, passive=False):
        target = self._skillcheck_render_square(kind, seed, value_diff, from_sq, to_sq)
        capturer = self.match.piece_at(from_sq)
        controller = build_controller(
            kind, seed=seed, cell_rect=self.board.cell_rect(target),
            now_ms=pg.time.get_ticks() - int(elapsed_ms), deadline_ms=deadline_ms,
            period_ms=period_for_diff(value_diff), value_diff=value_diff,
            victim_surface=self._victim_surface(target), board_rect=self.board.rect,
            geom=lambda sq: self.board.cell_rect(sq).center, from_sq=from_sq,
            victim_sq=target, attacker_type=capturer.type.value if capturer else None,
            shot_sound=self._shot_sound_for(capturer),
            on_shot=None if passive else (self._send_skillcheck_shot if online else None),
            miss_count=miss_count, passive=passive, audio=self.sound_manager)
        if controller is None:
            return False
        self._skillcheck_target = target
        self.board.aim_suppressed_square = target if kind == SkillCheckKind.AIM else None
        on_done = self._on_online_skillcheck_done if online else self._on_skillcheck_done
        self.skillcheck_overlay.start(
            controller, (from_sq, to_sq, promo_type, kind), on_done)
        return True

    def _open_spectate_overlay(self, kind, seed, value_diff, deadline_ms,
                               from_sq, to_sq, promo_type, *, elapsed_ms=0, miss_count=0):
        self.board.jump_to_review_ply(None)
        self._pending_online_move = None
        self._online_skillcheck = (from_sq, to_sq, promo_type, kind)
        self._online_spectate_kind = kind
        self._online_skillcheck_opened_ms = pg.time.get_ticks() - int(elapsed_ms)
        self._open_skillcheck_overlay(
            kind, seed, value_diff, deadline_ms, from_sq, to_sq, promo_type,
            online=True, passive=True, elapsed_ms=elapsed_ms, miss_count=miss_count)

    def _skillcheck_swallows_input(self):
        return self.skillcheck_overlay.is_active() and not self.skillcheck_overlay.is_passive()

    def _sync_aim_check_gun(self):
        fx = self.board.effects
        victim = self.board.aim_suppressed_square
        if victim is not None and self.skillcheck_overlay.is_active():
            fx.aim_victim = victim
            fx.aim_victim_scale = self.skillcheck_overlay.aim_victim_scale()
        else:
            fx.aim_victim = None
            fx.aim_victim_scale = 1.0

    def _send_skillcheck_shot(self, client_elapsed_ms):
        if self.online_client is not None:
            self.online_client.send_skill_check_shot(client_elapsed_ms)

    def _clear_online_skillcheck_state(self):
        self._skillcheck_target = None
        self._pending_online_move = None
        self._online_skillcheck = None
        self._online_spectate_kind = None
        self._online_skillcheck_opened_ms = None
        self._online_verdict_action = None

    def _teardown_skillcheck_overlay(self):
        self.skillcheck_overlay.cancel()
        self.board.aim_suppressed_square = None
        self._skillcheck_target = None
        self._online_skillcheck = None
        self._online_spectate_kind = None
        self._online_skillcheck_opened_ms = None
        self._online_verdict_action = None

    def _on_online_skillcheck_done(self, context, landed):
        action = self._online_verdict_action
        self._online_verdict_action = None
        self.board.aim_suppressed_square = None
        self._skillcheck_target = None
        if action is not None:
            action()

    def _skillcheck_render_square(self, kind, seed, value_diff, from_sq, to_sq):
        if kind == SkillCheckKind.AIM:
            capturer = self.match.piece_at(from_sq)
            if capturer is not None:
                victim_sq = self.board._capture_victim_square(capturer, from_sq, to_sq)
                if victim_sq is not None:
                    return victim_sq
            return to_sq
        square = placement_square(seed, value_diff,
                                  self._placement_exclusions(from_sq, to_sq), self.board.SIZE)
        return Square(square[0], square[1]) if square is not None else to_sq

    def _placement_exclusions(self, from_sq, to_sq):
        return {(from_sq.row, from_sq.col), (to_sq.row, to_sq.col)}

    def _victim_surface(self, square):
        piece = self.match.piece_at(square)
        if piece is None:
            return None
        return self.board.piece_images_scaled.get((piece.type, piece.color))

    def _shot_sound_for(self, capturer):
        if capturer is None:
            return None
        piece_type = capturer.type
        return lambda: self.sound_manager.play_capture(piece_type)

    def _capture_value_diff(self, from_sq, to_sq, promo_type):
        if promo_type is not None:
            return PIECE_VALUES[PieceType.PAWN] - PIECE_VALUES.get(promo_type, 0)
        capturer = self.match.piece_at(from_sq)
        if capturer is None:
            return 0
        victim_sq = self.board._capture_victim_square(capturer, from_sq, to_sq)
        if victim_sq is not None:
            victim = self.match.piece_at(victim_sq)
            return PIECE_VALUES.get(capturer.type, 0) - (
                PIECE_VALUES.get(victim.type, 0) if victim is not None else 0)
        return 0

    def _on_skillcheck_done(self, context, landed):
        from_sq, to_sq = context[0], context[1]
        promo_type = context[2] if len(context) > 2 else None
        kind = context[3] if len(context) > 3 else None
        aim_victim = self.board.aim_suppressed_square
        self.board.aim_suppressed_square = None
        if landed:
            self.board.apply_gated_move(from_sq, to_sq, promo_type)
            self._record_skillcheck(kind, True, len(self.match.move_history))
        else:
            promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
            self._record_skillcheck(
                kind, False, len(self.match.move_history) + 1,
                self.match.backend.preview_san(from_sq, to_sq, promo_letter))
            self.skillcheck.lock(from_sq, to_sq)
            self.board.selected_square = None
            if self.board.premove_color == self.match.current_turn():
                self.board._clear_premoves()
            self.board.trigger_skillcheck_fail(from_sq, to_sq,
                                               on_fire=self._on_skillcheck_miss_fire)
            if aim_victim is not None:
                self.board.restore_piece(aim_victim)

    def _on_skillcheck_miss_fire(self, piece_type):
        self.sound_manager.play_capture(piece_type)

    def _record_skillcheck(self, kind, won, ply, san=""):
        if kind is None:
            return
        kind_value = kind.value if isinstance(kind, SkillCheckKind) else kind
        self._skillcheck_log.append(SkillCheckOutcome(ply, kind_value, won, san))

    def _drop_skillcheck_log_from(self, ply):
        self._skillcheck_log = [e for e in self._skillcheck_log if e.ply < ply]

    def _record_online_fail(self, pending, from_sq, to_sq):
        if pending is None:
            return
        promo_type = pending[2]
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
        self._record_skillcheck(
            pending[3], False, len(self.match.move_history) + 1,
            self.match.backend.preview_san(from_sq, to_sq, promo_letter))

    def _apply_resumed_skillcheck_log(self, wire):
        self._skillcheck_log = [
            SkillCheckOutcome(e["ply"], e["kind"], e["won"], e.get("san", ""))
            for e in wire]

    def _rebuild_skillcheck_log(self, move_comments):
        self._skillcheck_log = []
        for index, comment in enumerate(move_comments):
            for kind, won, san in parse_comment(comment):
                self._skillcheck_log.append(
                    SkillCheckOutcome(index + 1, kind, won, san))

    def _skillcheck_whiffs(self):
        whiffs = {}
        for outcome in self._skillcheck_log:
            if not outcome.won:
                whiffs.setdefault(outcome.ply, []).append(
                    (KIND_LABEL.get(outcome.kind, outcome.kind), outcome.san))
        return whiffs

    def _skillcheck_deadline_ms(self):
        time_control = getattr(self, "_time_control", None)
        initial = time_control[0] if time_control and time_control[0] else 0
        return int(skillcheck_deadline_ms(initial))

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
            had_events = self.check_events()
            self.draw_frame()
            self.chrome.draw(self._chrome_stats())
            work_before_present = time.perf_counter() - frame_start
            self.clock.tick(self.target_fps)
            present_start = time.perf_counter()
            self._present(had_events)
            self._last_work_ms = (
                work_before_present + time.perf_counter() - present_start) * 1000.0

        if not self.pgn_review and self.current_result() is not None:
            self._auto_save_pgn()
        self._flush_deferred_env_writes(force=True)
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
                or self._give_time_holding
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
            self._cancel_all_scroll()
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

        if self.mode != "menu" and self.current_result() is None:
            self.match.tick_clock()

        self._update_give_time_hold()
        self._flush_deferred_env_writes()
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

        if (self.mode != "menu"
                and self.current_result() is None
                and post_animation_settled
                and self._pending_online_move is None
                and not self._skillcheck_swallows_input()):
            self.board.try_apply_next_premove()

        if self.mode != "menu":
            if self.current_result() is not None and self.focus_mode:
                if self.focus_transition is None:
                    self._toggle_focus(False)
                elif self.focus_transition.collapsing:
                    self._force_focus_off_instant()
            if self.focus_transition is not None:
                tr = self.focus_transition
                tr.draw(now)
                if self._focus_show() == "line" and tr.cur_board_rect is not None:
                    alpha = tr.cur_e if tr.collapsing else 1.0 - tr.cur_e
                    self._draw_time_lines(tr.cur_board_rect, alpha)
                if tr.done(now):
                    self._finalize_focus_transition()
            elif self.focus_mode:
                self._sync_aim_check_gun()
                self._draw_game_background()
                self.board.draw_board()
                show = self._focus_show()
                if show == "strips":
                    self._update_player_strips()
                    self.player_strip_top.draw()
                    self.player_strip_bottom.draw()
                elif show == "line":
                    self._draw_time_lines()
                mp = pg.mouse.get_pos()
                zone = self._focus_edge_zone_rect()
                reveal = self._focus_arrow_allowed() and zone.collidepoint(mp)
                anchor = (self.window.get_width() - FOCUS_EDGE_ARROW_MARGIN - FOCUS_ARROW_D // 2,
                          self.board.rect.centery)
                self.focus_arrow.update(now, reveal, anchor, mp, True)
                self.focus_arrow.draw(self.window)
                self.board.draw_drag_overlay()
                if self.board.effects.has_takeover():
                    self.board.effects.draw_takeover(self.window, now)
                self._update_result_pending()
            else:
                self._sync_aim_check_gun()
                self._draw_game_background()
                self.board.draw_board()
                self._update_player_strips()
                self._refresh_game_info()
                self.player_strip_top.draw()
                self.player_strip_bottom.draw()
                self._update_focus_arrow_off(now)
                self.right_menu.draw_menu()
                self.board.draw_drag_overlay()
                self._update_result_pending()
                if not self.match_found_modal.is_visible():
                    show_modal = self._result_modal_should_show() and not self.pgn_review
                    if not show_modal and self.board.effects.has_takeover():
                        self.board.effects.draw_takeover(self.window, now)
                    else:
                        self._draw_result_fade_overlay()
                    if show_modal:
                        self.board.effects.clear_takeover()
                        self._feed_result_menu()
                        self.result_menu.draw()
        entering_menu = self.mode == "menu" and self._prev_battle_mode != "menu"
        self._prev_battle_mode = self.mode
        if self.mode == "menu":
            if entering_menu and self.menu_page.page == PAGE_CARD:
                self.menu_battle.begin_intro()
            self.menu_battle.set_avoid_rect(self.menu_page.avoid_rect())
            self.menu_battle.set_logo_rect(self.menu_page.logo_rect())
            self.menu_battle.update(now)
            self.menu_battle.draw(self.window)
            self.menu_battle.draw_scrim(self.window)
        self._refresh_reconnect_button()
        if self.mode == "menu" and not self._menu_overlay_active():
            self.menu_page.draw_foreground()
        if self.mode == "menu":
            self.menu_battle.draw_intro_overlay(self.window)
        self.offer_banners.draw(self._banner_rect())
        for spec in reversed(self._modal_registry):
            spec.obj.draw()
        self.toast.draw(center_x=None if self.mode == "menu" else self.board.rect.centerx)
        if self.skillcheck_overlay.is_active() and (
                self.mode == "menu" or self.current_result() is not None):
            self._teardown_skillcheck_overlay()
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
        tc = self._format_time_control() or "∞"
        rnd = self._current_round()
        if self.pgn_review:
            return {"mode": "Review", "time_control": tc, "round": rnd,
                    "lines": [self._pgn_result_tag or "*"]}
        info = {"mode": MODE_PILL_LABELS.get(self.mode, "Local"),
                "time_control": tc, "round": rnd, "lines": []}
        if self.mode == ONLINE:
            white_score = self._series_scores.get(self.white_name, 0.0)
            black_score = self._series_scores.get(self.black_name, 0.0)
            info["lines"] = [
                f"{self.white_name}  {_score_str(white_score)} – "
                f"{_score_str(black_score)}  {self.black_name}",
            ]
        return info

    def _current_round(self):
        total = (self._series_scores.get(self.white_name, 0.0)
                 + self._series_scores.get(self.black_name, 0.0))
        return int(total) + 1

    def _format_time_control(self):
        if self._time_control is None:
            return None
        initial, incr = self._time_control
        return f"{int(initial // 60)}+{int(incr)}"

    def _update_player_strips(self):
        top_color = self._strip_color_top()
        bottom_color = opponent_of(top_color)
        turn = self.match.current_turn()
        over = self.current_result() is not None
        self.player_strip_top.set_state(**self._strip_state(top_color, turn, over))
        self.player_strip_bottom.set_state(**self._strip_state(bottom_color, turn, over))

    def _move_visually_settled(self):
        return not self.board.is_animating() and not self.board.effects.captures

    def _update_result_pending(self):
        self._update_incremental_autosave()
        result = self.current_result()
        if result is None or self.pgn_review:
            self._result_first_seen_at_ms = None
            self._result_await_since_ms = None
            return
        if self.mode == ONLINE and self.manual_result is None:
            if not self._resyncing:
                self._promote_awaited_result(result)
            return
        if self.mode == ONLINE and self._resyncing:
            return
        if RESULT_CODES.get(result) is not None:
            self._on_result_final(result)
        if self._result_first_seen_at_ms is None and self._move_visually_settled():
            self._result_first_seen_at_ms = pg.time.get_ticks()
            try:
                self._trigger_result_effects()
            except Exception:
                log.exception("result effects failed")

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
        self._cancel_all_scroll()
        self._compute_layout()
        return True

    def _compute_layout(self):
        window_width, window_height = self.window.get_size()
        size = (window_width, window_height)
        if size != getattr(self, "_last_layout_size", None):
            self._last_layout_size = size
            cache.clear_size_keyed()
        top = WindowChrome.HEIGHT
        avail_height = window_height - top
        panel_w = min(RIGHT_PANEL_WIDTH, int(window_width * PANEL_WIDTH_RATIO))
        board_area_w = max(window_width - panel_w, 200)

        board_size_px, strip_height, strip_gap, stack_h = focus_layout.square_stack(
            board_area_w, avail_height, True, STRIP_HEIGHT_RATIO, STRIP_GAP_RATIO,
            BOARD_AREA_MARGIN)

        board_x = (board_area_w - board_size_px) / 2
        board_y = top + (avail_height - stack_h) / 2 + strip_height + strip_gap

        board_rect = pg.Rect(board_x, board_y, board_size_px, board_size_px)
        focus_strip_override = None
        if self.focus_mode:
            board_rect = focus_layout.focus_square(
                (window_width, window_height), top, self._focus_show())
            board_x, board_y = board_rect.x, board_rect.y
            board_size_px = board_rect.width
            if self._focus_show() == "strips":
                sh, sg = focus_layout.focus_strip_metrics(
                    (window_width, window_height), top)
                focus_strip_override = focus_layout.focus_strip_rects(
                    board_rect, sh, sg)

        cell_size = board_size_px / self.board.SIZE
        result_width = min(440, board_size_px * 0.92)
        result_height = min(int(result_width * RESULT_HEIGHT_RATIO),
                            avail_height - 2 * BOARD_AREA_MARGIN)
        result_rect = pg.Rect(
            board_x + board_size_px / 2 - result_width / 2,
            board_y + board_size_px / 2 - result_height / 2,
            result_width,
            result_height
        )
        wait_width = max(result_width, MIN_MODAL_WIDTH)
        wait_height = max(cell_size * WAIT_HEIGHT_RATIO, 200)
        wait_rect = pg.Rect(
            board_x + board_size_px / 2 - wait_width / 2,
            board_y + board_size_px / 2 - wait_height / 2,
            wait_width,
            wait_height,
        )

        usable_menu_h = max(avail_height - MENU_FOOTER_RESERVE, 200)
        start_width = min(440, window_width - 24)
        start_height = min(max(usable_menu_h - 24, 200), 660)
        start_rect = pg.Rect(
            window_width / 2 - start_width / 2,
            top + usable_menu_h / 2 - start_height / 2,
            start_width,
            start_height
        )

        wide_overlay_width = min(window_width * 0.9, 1100)
        wide_overlay_height = min(window_height * 0.85, 760)
        wide_overlay_rect = pg.Rect(
            window_width / 2 - wide_overlay_width / 2,
            top + avail_height / 2 - wide_overlay_height / 2,
            wide_overlay_width,
            wide_overlay_height,
        )

        menu_modal_width = min(start_width, max(result_width, MIN_MODAL_WIDTH))
        menu_modal_height = min(start_height, max(cell_size * WAIT_HEIGHT_RATIO, 200))
        menu_modal_rect = pg.Rect(
            window_width / 2 - menu_modal_width / 2,
            top + avail_height / 2 - menu_modal_height / 2,
            menu_modal_width,
            menu_modal_height,
        )

        board_visible = self.mode != "menu"
        flex_rect = wait_rect if board_visible else menu_modal_rect
        result_modal_rect = result_rect if board_visible else menu_modal_rect

        menu_rect = pg.Rect(
            window_width - panel_w,
            top,
            panel_w,
            avail_height
        )

        strip_x = STRIP_MARGIN
        strip_w = board_area_w - 2 * STRIP_MARGIN
        top_strip_rect = pg.Rect(
            strip_x,
            board_y - strip_height - strip_gap,
            strip_w,
            strip_height,
        )
        bottom_strip_rect = pg.Rect(
            strip_x,
            board_y + board_size_px + strip_gap,
            strip_w,
            strip_height,
        )
        if focus_strip_override is not None:
            top_strip_rect, bottom_strip_rect = focus_strip_override

        self.board.set_rect(board_rect)
        self.result_menu.set_rect(result_rect)
        self.confirm_modal.set_rect(result_modal_rect)
        self.wait_modal.set_rect(flex_rect)
        self.match_found_modal.set_rect(flex_rect)
        self.reconnecting_modal.set_rect(board_rect)
        self.menu_page.set_rect(pg.Rect(0, 0, window_width, window_height), top, start_rect)
        self.menu_battle.top_inset = top
        self.menu_battle.set_rect(pg.Rect(0, 0, window_width, window_height))
        self.menu_battle.set_avoid_rect(self.menu_page.avoid_rect())
        self.help_modal.set_rect(result_rect)
        self.fen_input_modal.set_rect(flex_rect)
        options_width = min(int(window_width * 0.7), 520)
        options_height = min(int(window_height * 0.82), 620)
        self.options_modal.set_rect(pg.Rect(
            window_width / 2 - options_width / 2,
            top + avail_height / 2 - options_height / 2,
            options_width, options_height,
        ))
        self.directory_browser.set_rect(wide_overlay_rect)
        self.country_picker.set_rect(wide_overlay_rect)
        self._last_layout_mode = self.mode
        self._needs_full_present = True
        self.right_menu.set_rect(menu_rect)
        self.player_strip_top.set_rect(top_strip_rect)
        self.player_strip_bottom.set_rect(bottom_strip_rect)
        if self.skillcheck_overlay.is_active() and self._skillcheck_target is not None:
            self.skillcheck_overlay.relayout(self.board.cell_rect(self._skillcheck_target))
            self.skillcheck_overlay.set_board_rect(self.board.rect)
        self._refresh_capture_icons(strip_height)

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

    def _right_click_pressed(self, pos):
        if self.mode == "menu" or self.current_result() is not None:
            self.sound_manager.play_ui_click()
            return
        sq = self.board.cell_at(pos)
        if sq is None:
            self.sound_manager.play_ui_click()
            return
        if self.board.dragging_from is not None:
            if not self.board.queue_premove_from_drag(sq):
                self.sound_manager.play_ui_click()
            return
        self.board._right_drag_start_square = sq
        self.sound_manager.play_ui_click()

    def _right_click_released(self, pos):
        start = self.board._right_drag_start_square
        self.board._right_drag_start_square = None
        if self.mode == "menu" or start is None:
            return
        end = self.board.cell_at(pos)
        if end is None:
            return
        if end == start:
            self.board.toggle_highlight(start)
        else:
            self.board.toggle_arrow(start, end)

    def _active_scrollable(self):
        top = self._top_visible_modal()
        if top is not None:
            return top.obj if top.scrollable else None
        if self._result_modal_should_show():
            return None
        if self.mode == "menu":
            return self.menu_page
        if self.focus_mode or self.focus_transition is not None:
            return None
        return self.right_menu

    def _cancel_all_scroll(self):
        self._scroll_pressed = None
        self.right_menu.scroll.cancel()
        self.history_view.scroll.cancel()
        for spec in self._modal_registry:
            if spec.scrollable:
                spec.obj.scroll.cancel()

    def _handle_left_drag_motion(self, pos):
        if self._scroll_pressed is not None:
            if not self._scroll_pressed.is_visible():
                self._scroll_pressed = None
            elif self._scroll_pressed.handle_motion(pos):
                return
        if not self.audio_panel.handle_drag(pos, True):
            self.board.update_drag_motion(pos)

    def mouse_left_clicked(self, pos, *, ui_click=True):
        self._click_sound_played = False
        self._dispatch_left_click(pos)
        if ui_click and not self._click_sound_played:
            self.sound_manager.play_ui_click()

    def _dispatch_left_click(self, pos):
        if self.chrome.handle_click(pos):
            return
        if self.focus_transition is not None:
            return
        if (self.current_result() is not None
                and self._result_first_seen_at_ms is not None
                and not self._result_modal_should_show()):
            self._skip_result_fade()
            return
        top = self._top_visible_modal()
        if top is not None:
            top.obj.handle_click(pos)
            return
        if self.offer_banners.handle_click(pos):
            return
        if self.mode == "menu":
            self.menu_page.handle_click(pos)
            return
        if (self.focus_arrow.is_visible() and self._focus_arrow_allowed()
                and self.focus_arrow.handle_click(pos)):
            self._toggle_focus(not self.focus_mode)
            self._focus_click_consumed = True
            self._click_sound_played = True
            return
        if not self.focus_mode and self.result_menu.handle_click(pos):
            return
        if not self.focus_mode and self.right_menu.handle_click(pos):
            return
        if self.current_result() is not None:
            return
        if self.board.pending_promotion_square is not None:
            self.board.pick_promotion_at(pos)
            self._click_sound_played = True
            return
        square = self.board.cell_at(pos)
        if square is not None:
            if self.board.review_ply is None and not self.board.is_square_annotated(square):
                self.board.clear_annotations()
            signal = self.board.handle_click(square)
            if signal:
                self._click_sound_played = True
                if signal == "select":
                    self.sound_manager.play_pickup()

    def _handle_shortcut_key(self, event):
        if self._menu_overlay_active():
            return False
        if self._handle_promotion_key(event):
            return True
        if event.key == pg.K_h:
            self._toggle_focus(not self.focus_mode)
            return True
        if getattr(event, "unicode", "") == "?":
            self.help_modal.show()
            return True
        if event.key == pg.K_f:
            self._on_flip()
            return True
        if event.key == pg.K_r:
            self._on_resign()
            return True
        if event.key == pg.K_d:
            self._on_draw()
            return True
        if event.key == pg.K_z and (event.mod & pg.KMOD_CTRL):
            self._on_undo()
            return True
        if event.key == pg.K_LEFT:
            self._step_review(-1)
            return True
        if event.key == pg.K_RIGHT:
            self._step_review(1)
            return True
        if event.key == pg.K_HOME:
            self.board.jump_to_review_ply(0)
            return True
        if event.key == pg.K_END:
            self.board.jump_to_review_ply(None)
            return True
        return False

    def _handle_promotion_key(self, event):
        if self.board.pending_promotion_square is None:
            return False
        chosen = PROMOTION_KEYS.get(event.key)
        if chosen is None:
            return False
        self.board.pick_promotion(chosen)
        return True

    def _step_review(self, delta):
        history_len = len(self.match.move_history)
        if history_len == 0:
            return
        current = self.board.review_anchor(history_len)
        new_ply = max(0, min(history_len, current + delta))
        if new_ply == current:
            return
        if delta > 0:
            self.board.animate_review_ply(new_ply)
        else:
            self.board.jump_to_review_ply(new_ply)

    def _mouse_left_pressed(self, pos):
        self._focus_click_consumed = False
        scrollable = self._active_scrollable()
        if scrollable is not None and scrollable.handle_press(pos):
            self._scroll_pressed = scrollable
            return
        self.mouse_left_clicked(pos)
        if (self.mode != "menu"
                and pos[1] >= self.chrome.HEIGHT
                and self.current_result() is None
                and self.board.pending_promotion_square is None
                and not self._menu_overlay_active()
                and not self._focus_click_consumed
                and self.focus_transition is None):
            self.board.begin_press(pos)

    def _mouse_left_released(self, pos):
        self.audio_panel.end_drag()
        if self._scroll_pressed is not None:
            scrollable = self._scroll_pressed
            self._scroll_pressed = None
            dragged = scrollable.handle_release(pos)
            if not dragged and scrollable.is_visible():
                scrollable.handle_click(pos)
            return
        was_dragging = self.board.dragging_from is not None
        if was_dragging and self.current_result() is None:
            self.mouse_left_clicked(pos, ui_click=False)
        self.board.end_press()
        if was_dragging and self.current_result() is None:
            self.sound_manager.play_drop()

    def check_events(self):
        events = pg.event.get()
        for event in events:
            if event.type == pg.QUIT:
                self.running = False

            elif event.type == pg.KEYDOWN:
                if not self._skillcheck_swallows_input():
                    self.sound_manager.play_ui_click()
                if event.key == pg.K_ESCAPE:
                    self._handle_escape()
                    continue
                if event.key == pg.K_F11:
                    self.chrome.toggle_fullscreen()
                    continue
                if self._skillcheck_swallows_input():
                    self.skillcheck_overlay.handle_event(event)
                    continue
                top = self._top_visible_modal()
                if top is not None:
                    if top.handles_keys:
                        top.obj.handle_key(event)
                    continue
                if self.mode == "menu":
                    self.menu_page.handle_key(event)
                    continue
                self._handle_shortcut_key(event)

            elif event.type == pg.MOUSEBUTTONDOWN:
                if self._skillcheck_swallows_input():
                    if event.button == 1 and self.chrome.handle_click(event.pos):
                        continue
                    self.skillcheck_overlay.handle_event(event)
                    continue
                if event.button == 1:
                    self._mouse_left_pressed(event.pos)
                elif event.button == 3:
                    self._right_click_pressed(event.pos)

            elif event.type == pg.MOUSEBUTTONUP:
                if self._skillcheck_swallows_input():
                    continue
                if event.button == 1:
                    self.chrome.clear_title_press()
                    self._mouse_left_released(event.pos)
                elif event.button == 3:
                    self._right_click_released(event.pos)

            elif event.type == pg.MOUSEMOTION:
                self.chrome.update_cursor(event.pos)
                if event.buttons[0]:
                    self.chrome.handle_title_motion(event.pos)
                    self._handle_left_drag_motion(event.pos)

            elif event.type == pg.MOUSEWHEEL:
                scrollable = self._active_scrollable()
                if scrollable is not None:
                    scrollable.handle_scroll(pg.mouse.get_pos(), event.y)

            elif event.type == pg.VIDEORESIZE:
                w = max(event.w, MIN_WINDOW_WIDTH)
                h = max(event.h, MIN_WINDOW_HEIGHT)
                if os.name == "nt" or (w, h) != (event.w, event.h):
                    self._recreate_window_surface(w, h)
                self.window_width = w
                self.window_height = h
                self._cancel_all_scroll()
                self._abort_transition_for_resize()
                self._compute_layout()
        return bool(events)
