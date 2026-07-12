import logging

import pygame as pg

from chessshootout.backend.pieces import PieceColor, opponent_of
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
from chessshootout.frontend.panels.right import RightMenu, REVIEW_BUTTONS
from chessshootout.frontend.panels.review_strip import ReviewStrip
from chessshootout.frontend.pgn_open import open_pgn_or_toast
from chessshootout.frontend.screens.base import Nav, Screen
from chessshootout.frontend.visual import backdrop
from chessshootout.skillcheck.types import KIND_LABEL, SkillCheckOutcome


log = logging.getLogger("chess.frontend")

REVIEW_HOTKEY_KEYS = ("?", "← →", "Home", "End", "F", "F11", "Esc")
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
        self._return_to = "history"
        self._skillcheck_log = []
        self._bg_cache = None
        self._pgn_path = None

        self.match = Match()
        self.board = Board(window, self.match)
        self.board.read_only = True
        self.right_menu = RightMenu(window, self.match, {
            "menu": self._on_menu,
            "flip": self._on_flip,
            "open_pgn": self._on_open_pgn,
        }, board=self.board, buttons_provider=lambda: REVIEW_BUTTONS,
            audio_panel=app.audio_panel, whiffs_provider=self._skillcheck_whiffs)
        self.strip_top = ReviewStrip(window)
        self.strip_bottom = ReviewStrip(window)

    @property
    def window(self):
        return self.app.window

    def enter(self, **payload):
        self._return_to = payload.get("return_to", "history")
        path = payload["pgn_path"]
        self._pgn_path = path
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
        self._draw_background()
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
        self.board.set_rect(r.board_rect)
        self.right_menu.set_rect(r.menu_rect)
        self.strip_top.set_rect(r.top_strip_rect)
        self.strip_bottom.set_rect(r.bottom_strip_rect)
        self._refresh_capture_icons(r.strip_height)

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
            self._step(-1)
            return True
        if event.key == pg.K_RIGHT:
            self._step(1)
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

    def _step(self, delta):
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

    def _on_menu(self):
        self.app.request_nav(Nav(self._return_to))

    def _on_flip(self):
        self.board.cancel_drag_physics()
        self.board.flipped = not self.board.flipped
        self.app.sound_manager.play_flip()

    def _on_open_pgn(self):
        open_pgn_or_toast(self.app.toast, self._pgn_path)

    def _compute_game_info(self):
        tc = format_time_control(self._time_control) or "∞"
        return {"mode": "Review", "time_control": tc, "lines": [self._pgn_result_tag or "*"]}

    def _refresh_capture_icons(self, strip_height):
        if not self.board.piece_images_original:
            return
        target = max(int(strip_height * 0.42), 1)
        icons = {
            key: pg.transform.smoothscale(surface, (target, target))
            for key, surface in self.board.piece_images_original.items()
        }
        self.strip_top.set_piece_icons(icons)
        self.strip_bottom.set_piece_icons(icons)

    def _strip_color_top(self):
        return PieceColor.WHITE if self.board.flipped else PieceColor.BLACK

    def _update_strips(self):
        top_color = self._strip_color_top()
        bottom_color = opponent_of(top_color)
        self.strip_top.set_state(**self._strip_state(top_color))
        self.strip_bottom.set_state(**self._strip_state(bottom_color))

    def _name_for_color(self, color):
        is_white = color in (PieceColor.WHITE, "white")
        return self.white_name if is_white else self.black_name

    def _strip_state(self, color):
        captured, advantage = self._capture_summary(color)
        return {
            "name": self._name_for_color(color),
            "player_color": color,
            "captured": captured,
            "advantage": advantage,
            "captured_color": opponent_of(color),
        }

    def _capture_summary(self, color):
        history = self.match.move_history
        if self.board.review_ply is not None:
            history = history[:self.board.review_ply]
        return captured_by(history, color), material_advantage(history, color)

    def _rebuild_skillcheck_log(self, move_comments):
        self._skillcheck_log = []
        for index, comment in enumerate(move_comments):
            for kind, won, san in parse_comment(comment):
                self._skillcheck_log.append(SkillCheckOutcome(index + 1, kind, won, san))

    def _skillcheck_whiffs(self):
        whiffs = {}
        for outcome in self._skillcheck_log:
            if not outcome.won:
                whiffs.setdefault(outcome.ply, []).append(
                    (KIND_LABEL.get(outcome.kind, outcome.kind), outcome.san))
        return whiffs

    def _draw_background(self):
        size = self.window.get_size()
        w, h = size
        if w <= 0 or h <= 0:
            return
        bc = self.board.rect.center
        center = (bc[0] / w, bc[1] / h)
        key = (size, bc)
        if self._bg_cache is None or self._bg_cache[0] != key:
            self._bg_cache = (key, backdrop.arena_background(size, center).convert())
        self.window.blit(self._bg_cache[1], (0, 0))
