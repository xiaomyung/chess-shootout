import logging

import pygame as pg

from chessshootout.backend.pieces import opponent_of
from chessshootout.domain import openings
from chessshootout.domain.capture_summary import captured_by, material_advantage
from chessshootout.domain.match import Match
from chessshootout.domain.pgn.load import (
    format_time_control, load_pgn_into_backend, parse_comment, parse_time_control,
)
from chessshootout.infra import env
from chessshootout.frontend.board import Board
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.help import HOTKEYS
from chessshootout.frontend.panels.player_strip import (
    is_white, top_strip_color, refresh_capture_icons,
)
from chessshootout.frontend.panels.right import RightMenu, REVIEW_CAPS
from chessshootout.frontend.panels.review_strip import ReviewStrip
from chessshootout.frontend.pgn_open import open_pgn_or_toast
from chessshootout.frontend.screens.base import Nav, Screen
from chessshootout.frontend.visual.backdrop import ArenaBackdrop
from chessshootout.skillcheck.types import SkillCheckOutcome, whiffs_by_ply


log = logging.getLogger("chess.frontend")

REVIEW_HOTKEY_KEYS = ("?", "Left / Right", "Home", "End", "F", "F11", "Esc")
REVIEW_HOTKEYS = [row for row in HOTKEYS if row[0] in REVIEW_HOTKEY_KEYS]


class ReviewScreen(Screen):

    name = "review"

    def __init__(self, app):
        super().__init__(app)
        window = app.window

        self.white_name = "Player 1"
        self.black_name = "Player 2"
        self._time_control = None
        self._pgn_result_tag = None
        self._return_to = "menu"
        self._skillcheck_log = []
        self._pgn_path = None
        self._custom_start = False
        self._debut_memo = None
        self.backdrop = ArenaBackdrop()

        self.match = Match()
        self.board = Board(window, self.match)
        self.board.read_only = True
        self.right_menu = RightMenu(window, self.match, {
            "menu": self._on_menu,
            "flip": self._on_flip,
            "open_pgn": self._on_open_pgn,
            "sound_toggle": self._toggle_sound,
            "set_volume": self._set_signal_volume,
        }, board=self.board, buttons_provider=lambda: REVIEW_CAPS,
            whiffs_provider=self._skillcheck_whiffs,
            debut_provider=self._debut_line,
            signals_provider=self._signals_provider,
            sounds=app.sound_manager, caps_stacked=True)
        self.strip_top = ReviewStrip(window)
        self.strip_bottom = ReviewStrip(window)

    @property
    def window(self):
        return self.app.window

    def enter(self, **payload):
        openings.preload()
        self._return_to = payload.get("return_to", "menu")
        path = payload["pgn_path"]
        self._pgn_path = path
        self._debut_memo = None
        text = self._read_pgn(path)
        if text is None:
            self._fail(path, "could not read file")
            return
        parsed, ok = load_pgn_into_backend(self.match, text)
        if not ok:
            self._fail(path, "pgn failed to parse")
            return
        self.white_name = parsed.headers.get("White", "Player 1")
        self.black_name = parsed.headers.get("Black", "Player 2")
        self._time_control = parse_time_control(parsed.headers.get("TimeControl", "-"))
        self._pgn_result_tag = parsed.result
        self._custom_start = (parsed.headers.get("SetUp") == "1"
                              or "FEN" in parsed.headers)
        self._rebuild_skillcheck_log(parsed.move_comments)
        self.board.reset_for_new_game()
        self.right_menu.reset_for_new_game()
        self.right_menu.set_game_info(self._compute_game_info())
        if self.match.move_history:
            self.board.jump_to_review_ply(0)
        log.info("review enter path=%s", path)

    @staticmethod
    def _read_pgn(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def _fail(self, path, reason):
        log.warning("review enter path=%s failed: %s", path, reason)
        self.app.toast.show("Could not load PGN")
        self.app.request_nav(Nav(self._return_to))

    def exit(self):
        super().exit()
        self.board.jump_to_review_ply(None)
        self.board.reset_for_new_game()
        self.right_menu.reset_for_new_game()

    def draw(self):
        self.backdrop.draw(self.window, self.board.rect)
        self.board.draw_board()
        self.board.draw_drag_overlay()
        self._update_strips()
        self.strip_top.draw()
        self.strip_bottom.draw()
        self.right_menu.draw_menu()

    def relayout(self, size):
        window_width, window_height = size
        r = compute_layout(
            window_width, window_height, mode=self.name, focus_mode=False,
            focus_show=env.get_focus_show(), board_size=self.board.SIZE)
        self.board.set_rect(r.board_rect, scale=r.scale)
        self.right_menu.set_rect(r.menu_rect, scale=r.scale)
        self.strip_top.set_rect(r.top_strip_rect, scale=r.scale)
        self.strip_bottom.set_rect(r.bottom_strip_rect, scale=r.scale)
        refresh_capture_icons(self.board, r.strip_height,
                              (self.strip_top, self.strip_bottom))

    def handle_click(self, pos):
        if self.right_menu.handle_click(pos):
            return True
        square = self.board.cell_at(pos)
        if square is not None:
            self.board.handle_click(square)
        return False

    def handle_right_press(self, pos):
        if self.board.cell_at(pos) is not None:
            self.board.begin_right_press(pos)
        self.app.sound_manager.play_ui_click()
        return True

    def handle_right_release(self, pos):
        self.board.end_right_press(pos)
        return True

    def handle_key(self, event):
        if event.key == pg.K_LEFT:
            self.board.step_review(-1)
            return True
        if event.key == pg.K_RIGHT:
            self.board.step_review(1)
            return True
        if event.key == pg.K_HOME:
            self.board.jump_to_review_ply(0)
            return True
        if event.key == pg.K_END:
            self.board.jump_to_review_ply(None)
            return True
        if event.key == pg.K_f:
            self._on_flip()
            return True
        if event.key == pg.K_a:
            self.right_menu.toggle_section("actions")
            return True
        if event.key == pg.K_s:
            self.right_menu.toggle_section("signals")
            return True
        if getattr(event, "unicode", "") == "?":
            self.app.help_modal.show(REVIEW_HOTKEYS)
            return True
        return False

    def active_scrollable(self):
        return self.right_menu

    def escape(self):
        return Nav(self._return_to)

    def modals(self):
        return [ModalSpec(self.app.help_modal)]

    def scrollables(self):
        return [self.right_menu]

    def debug_state(self):
        return {"pgn_path": self._pgn_path, "review_ply": self.board.review_ply}

    def _on_menu(self):
        self.app.request_nav(Nav(self._return_to))

    def _on_flip(self):
        self.board.cancel_drag_physics()
        self.board.flipped = not self.board.flipped
        self.app.sound_manager.play_flip()

    def _on_open_pgn(self):
        open_pgn_or_toast(self.app.toast, self._pgn_path)

    def _signals_provider(self):
        sm = self.app.sound_manager
        return {
            "share_on": False,
            "share_enabled": False,
            "auto_q": False,
            "sound_on": sm.enabled,
            "volume": sm.master_volume,
            "review": True,
        }

    def _toggle_sound(self):
        sm = self.app.sound_manager
        sm.set_enabled(not sm.enabled)

    def _set_signal_volume(self, value):
        self.app.sound_manager.set_master_volume(value)
        self.app.settings.defer_master_volume_write()

    def _compute_game_info(self):
        tc = format_time_control(self._time_control) or "∞"
        return {"mode": "Review", "time_control": tc, "lines": [self._pgn_result_tag or "*"]}

    def _update_strips(self):
        top_color = top_strip_color(self.board.flipped)
        bottom_color = opponent_of(top_color)
        self.strip_top.set_state(**self._strip_state(top_color))
        self.strip_bottom.set_state(**self._strip_state(bottom_color))

    def _name_for_color(self, color):
        return self.white_name if is_white(color) else self.black_name

    def _strip_state(self, color):
        history = self.board.reviewed_history()
        return {
            "name": self._name_for_color(color),
            "player_color": color,
            "captured": captured_by(history, color),
            "advantage": material_advantage(history, color),
            "captured_color": opponent_of(color),
        }

    def _debut_line(self):
        if self._custom_start:
            return None
        key = (len(self.match.move_history), self.board.review_ply)
        if self._debut_memo is not None and self._debut_memo[0] == key:
            return self._debut_memo[1]
        sans = [entry.san for entry in self.board.reviewed_history()]
        result = openings.lookup(sans)
        self._debut_memo = (key, result)
        return result

    def _rebuild_skillcheck_log(self, move_comments):
        self._skillcheck_log = []
        for index, comment in enumerate(move_comments):
            for kind, won, san in parse_comment(comment):
                self._skillcheck_log.append(SkillCheckOutcome(index + 1, kind, won, san))

    def _skillcheck_whiffs(self):
        return whiffs_by_ply(self._skillcheck_log)
