import logging
from typing import Any

import pygame as pg

from chessshootout.backend.pieces import PieceColor, opponent_of
from chessshootout.domain import openings
from chessshootout.domain.capture_summary import captured_by, material_advantage
from chessshootout.domain.match import Match
from chessshootout.domain.pgn.load import (
    format_time_control, load_pgn_into_backend, parse_comment, parse_time_control,
)
from chessshootout.infra import env
from chessshootout.frontend import signal_controls
from chessshootout.frontend.board import Board
from chessshootout.frontend.layout import compute_layout
from chessshootout.frontend.modal_registry import ModalSpec
from chessshootout.frontend.modals.help import HOTKEYS
from chessshootout.frontend.panels.player_strip import (
    is_white, top_strip_color, refresh_capture_icons,
)
from chessshootout.frontend.panels.right import RightMenu, REVIEW_CAPS
from chessshootout.frontend.panels.review_strip import ReviewStrip
from chessshootout.frontend.screens.base import Nav, Screen
from chessshootout.frontend.visual.backdrop import ArenaBackdrop
from chessshootout.skillcheck.types import SkillCheckOutcome, whiffs_by_ply


log = logging.getLogger("chess.frontend")

REVIEW_HOTKEY_KEYS = ("?", "Left / Right", "Home", "End", "F", "F11", "Esc")
REVIEW_HOTKEYS = [row for row in HOTKEYS if row[0] in REVIEW_HOTKEY_KEYS]


class ReviewScreen(Screen):
    """
    The screen that replays a saved game. It owns its own Match and a read-only
    Board built from the PGN it was handed, and opens at ply 0 so the game is
    walked forward from the start rather than landed on at the end. It is
    reached as Nav("review", {pgn_path, return_to}) and Esc leaves it with
    Nav(return_to), back to whichever screen opened it
    """

    name = "review"

    def __init__(self, app: Any) -> None:
        """
        Build the screen once at startup with its own game, board, command rail
        and player strips, none of which are shared with the game screen. No
        PGN is loaded yet -- entering with a file path is what fills it

        :param app: the Frontend shell, this screen's route to the window,
            sound, toasts and the PGN opener
        """
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
        self._debut = openings.DebutTracker(self._reviewed_sans)
        self.backdrop = ArenaBackdrop()

        self.match = Match()
        self.board = Board(window, self.match)
        self.board.read_only = True
        self.right_menu = RightMenu(window, self.match, {
            "menu": self._on_menu,
            "flip": self._on_flip,
            "open_pgn": self._on_open_pgn,
            "sound_toggle": lambda: signal_controls.toggle_sound(app),
            "set_volume": lambda value: signal_controls.set_signal_volume(app, value),
        }, board=self.board, buttons_provider=lambda: REVIEW_CAPS,
            whiffs_provider=self._skillcheck_whiffs,
            debut_provider=self._debut_line,
            signals_provider=self._signals_provider,
            sounds=app.sound_manager, caps_stacked=True,
            suppress_click=app.input_router.suppress_click_sound)
        self.strip_top = ReviewStrip(window)
        self.strip_bottom = ReviewStrip(window)

    @property
    def window(self) -> pg.Surface:
        """
        The window this screen paints into, read back through the shell each
        time so a resize that replaces the surface is picked up without
        anything here being rebound

        :returns: the current display surface
        """
        return self.app.window

    def enter(self, **payload: Any) -> None:
        """
        Open a saved game: read the PGN, replay it into this screen's own Match
        and show the starting position, so the player walks forward through the
        game from ply 0. The names, the clock and the result all come from the
        file's own header tags -- nothing is worked out again from the moves --
        and a file that cannot be read or replayed toasts and navigates back

        :param payload: navigation payload carrying pgn_path, the file to open,
            and return_to, the screen Esc and the Menu button go back to
        """
        openings.preload()
        self._return_to = payload.get("return_to", "menu")
        path = payload["pgn_path"]
        self._pgn_path = path
        self._debut.reset()
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
    def _read_pgn(path: str) -> str | None:
        """
        Read a saved game off disk, answering None instead of raising when the
        file has been moved or cannot be read, which is what lets entry fail
        politely rather than crashing the app

        :param path: full path of the PGN file to read
        :returns: the file's text, or None when it could not be read
        """
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def _fail(self, path: str, reason: str) -> None:
        """
        Give up on a PGN that could not be read or replayed: say so in a toast
        and send the player straight back where they came from, so the screen
        is never left showing half a game

        :param path: the file that failed, logged for diagnosis
        :param reason: short description of what went wrong, logged rather than
            shown to the player
        """
        log.warning("review enter path=%s failed: %s", path, reason)
        self.app.toast.show("Could not load PGN")
        self.app.request_nav(Nav(self._return_to))

    def exit(self) -> None:
        """
        Hand the window back and put everything to a clean baseline -- the
        browse position, the board and the command rail -- so the next PGN
        opened here starts from nothing rather than from the last game
        """
        super().exit()
        self.board.jump_to_review_ply(None)
        self.board.reset_for_new_game()
        self.right_menu.reset_for_new_game()

    def draw(self) -> None:
        """
        Paint the review screen for this frame: the arena behind the board, the
        board itself with any piece in flight over it, then both player strips
        and the command rail down the right
        """
        self.backdrop.draw(self.window, self.board.rect)
        self.board.draw_board()
        self.board.draw_drag_overlay()
        self._update_strips()
        self.strip_top.draw()
        self.strip_bottom.draw()
        self.right_menu.draw_menu()

    def relayout(self, size: tuple[int, int]) -> None:
        """
        Recompute every rect this screen owns for a new window size -- board,
        command rail and both strips -- and rescale the captured-piece icons to
        the new strip height. Focus mode never applies here, so the review
        always gets the full layout

        :param size: window width and height in pixels
        """
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

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a left click. The command rail gets first refusal, where clicking
        a move in the log jumps the board to that ply; a click on a square is
        handed to the board, which refuses it while read-only, so the position
        on screen only ever moves through the rail and the keyboard

        :param pos: click position in window pixels
        :returns: True when the rail consumed the click
        """
        if self.right_menu.handle_click(pos):
            return True
        square = self.board.cell_at(pos)
        if square is not None:
            self.board.handle_click(square)
        return False

    def handle_right_press(self, pos: tuple[int, int]) -> bool:
        """
        Start a right-button gesture on the board, which draws a highlight or
        an arrow. The marks stay available while reviewing, so a line can be
        talked through over the saved position

        :param pos: press position in window pixels
        :returns: True always, since this screen owns the whole right button
        """
        if self.board.cell_at(pos) is not None:
            self.board.begin_right_press(pos)
        self.app.sound_manager.play_ui_click()
        return True

    def handle_right_release(self, pos: tuple[int, int]) -> bool:
        """
        Finish the right-button gesture and commit whatever mark it drew, a
        coloured square or an arrow

        :param pos: release position in window pixels
        :returns: True always, matching the press
        """
        self.board.end_right_press(pos)
        return True

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Handle this screen's own hotkeys: left and right walk the game a ply at
        a time, Home and End jump to the first and last position, F flips the
        board, A and S fold the rail's sections, and ? opens the help card
        listing exactly these. Esc and F11 never reach here

        :param event: pygame KEYDOWN event, key code and unicode both readable
        :returns: True when the key was one of this screen's
        """
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

    def active_scrollable(self) -> RightMenu:
        """
        Name the command rail as what the mouse wheel should move here, its
        move log being the only list on this screen

        :returns: the command rail
        """
        return self.right_menu

    def escape(self) -> Nav:
        """
        Leave the review and go back to whoever opened it, which is all Esc
        means on this screen -- there is nothing here to cancel first

        :returns: a navigation intent for the screen named in the entry payload
        """
        return Nav(self._return_to)

    def modals(self) -> list[ModalSpec]:
        """
        The help card this screen owns, listing the review hotkeys. The shell
        merges it behind its own global modals and uses that merged order for
        Esc, for clicks and for drawing

        :returns: this screen's modal specs, topmost first
        """
        return [ModalSpec(self.app.help_modal)]

    def scrollables(self) -> list[RightMenu]:
        """
        List the command rail so the shell can cancel its scrolling along with
        every other list when the window is resized

        :returns: the scrollable widgets this screen owns
        """
        return [self.right_menu]

    def debug_state(self) -> dict[str, Any]:
        """
        Summarise the review for the crash log: which file is open and which
        ply the player was looking at when things went wrong

        :returns: readable key/value summary of this screen's state
        """
        return {"pgn_path": self._pgn_path, "review_ply": self.board.review_ply}

    def _on_menu(self) -> None:
        """
        Leave for the screen that opened the review, behind the command rail's
        Menu button and the same intent Esc produces
        """
        self.app.request_nav(Nav(self._return_to))

    def _on_flip(self) -> None:
        """
        Turn the board round so the game can be watched from the other side,
        behind both the rail's Flip button and the F key
        """
        self.board.cancel_drag_physics()
        self.board.flipped = not self.board.flipped
        self.app.sound_manager.play_flip()

    def _on_open_pgn(self) -> None:
        """
        Hand the file being reviewed to whatever the operating system opens
        .pgn files with, behind the rail's Open PGN button. Nothing is exported
        or copied -- the saved file is opened where it already lives
        """
        self.app.pgn_opener.open(self._pgn_path)

    def _signals_provider(self) -> dict[str, Any]:
        """
        Tell the command rail what its SIGNALS section holds while reviewing:
        only the sound toggle and the volume, since there is no opponent to
        share marks with and no move to auto-queen. The review flag is what
        switches the rail to its reduced set of chips

        :returns: this frame's signal state for the rail
        """
        sm = self.app.sound_manager
        return {
            "share_on": False,
            "share_enabled": False,
            "auto_q": False,
            "sound_on": sm.enabled,
            "volume": sm.master_volume,
            "review": True,
        }

    def _compute_game_info(self) -> dict[str, Any]:
        """
        Build the header block at the top of the command rail for a reviewed
        game: the Review label, the clock the game was played at, and the
        result exactly as the file's [Result] tag reads it -- never worked out
        again from the moves

        :returns: the rail's header block of mode, time control and lines
        """
        tc = format_time_control(self._time_control) or "∞"
        return {"mode": "Review", "time_control": tc, "lines": [self._pgn_result_tag or "*"]}

    def _update_strips(self) -> None:
        """
        Push this frame's state into both player strips, with the top and
        bottom sides read off the board's orientation so flipping the board
        swaps the two players over
        """
        top_color = top_strip_color(self.board.flipped)
        bottom_color = opponent_of(top_color)
        self.strip_top.set_state(**self._strip_state(top_color))
        self.strip_bottom.set_state(**self._strip_state(bottom_color))

    def _name_for_color(self, color: PieceColor) -> str:
        """
        Name the player who had one side, read from the PGN's White and Black
        header tags rather than from anything on screen

        :param color: side to name
        :returns: that player's display name, a placeholder when the file named
            nobody
        """
        return self.white_name if is_white(color) else self.black_name

    def _strip_state(self, color: PieceColor) -> dict[str, Any]:
        """
        Work out everything one strip shows for the position being browsed: the
        player's name, the pieces they had taken by that ply and the material
        lead they held there. Browsing back therefore rewinds the strips too

        :param color: side the strip belongs to
        :returns: the keyword state to hand to ReviewStrip.set_state
        """
        history = self.board.reviewed_history()
        return {
            "name": self._name_for_color(color),
            "player_color": color,
            "captured": captured_by(history, color),
            "advantage": material_advantage(history, color),
            "captured_color": opponent_of(color),
        }

    def _reviewed_sans(self) -> list[str]:
        """
        The moves of the game as far as the player has browsed, which is what
        the opening lookup reads. Each one is the SAN the PGN was replayed with
        and carried on its history entry, never rebuilt from the position

        :returns: the moves in play order up to the browsed ply
        """
        return [entry.san for entry in self.board.reviewed_history()]

    def _debut_line(self) -> tuple[str, str] | None:
        """
        Name the opening reached in the position on screen, for the line under
        the rail's move log. A game that began from a custom position has no
        opening to name, so nothing is shown for it

        :returns: the ECO code and opening name, or None when there is none
        """
        if self._custom_start:
            return None
        return self._debut.line((len(self.match.move_history), self.board.review_ply))

    def _rebuild_skillcheck_log(self, move_comments: list[str]) -> None:
        """
        Read the skill checks back out of the PGN's move comments, so a
        reviewed game shows the same hits and misses it was saved with. The
        comments arrive aligned with the moves, which is what puts each check
        on the ply it fired on

        :param move_comments: the comment saved beside each move, in play order
        """
        self._skillcheck_log = []
        for index, comment in enumerate(move_comments):
            for kind, won, san in parse_comment(comment):
                self._skillcheck_log.append(SkillCheckOutcome(index + 1, kind, won, san))

    def _skillcheck_whiffs(self) -> dict[int, list[tuple[str, str]]]:
        """
        Group the checks this game lost by ply for the command rail, which
        draws them struck through under the move they were attempted on

        :returns: ply number to its misses as display label and SAN pairs
        """
        return whiffs_by_ply(self._skillcheck_log)
