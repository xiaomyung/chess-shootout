from collections.abc import Callable
from typing import Any, cast

import pygame as pg

from chessshootout.frontend.modals.base import BaseModal
from chessshootout.frontend.visual.clock_visual import format_clock
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    cut_rect_surface, blit_centered, stroked_text, soft_blur)
from chessshootout.frontend.visual.widgets import (
    draw_button_row, fit_text_to_rect, draw_series_chip)
from chessshootout.frontend.visual.fonts import get_font, get_display_font


BUTTONS = [("New Game", "new_game"), ("Open PGN", "open_pgn"), ("Menu", "menu")]
ONLINE_BUTTONS = [("Rematch", "rematch"), ("Open PGN", "open_pgn"), ("Menu", "menu")]

SCORE_SEP = "–"
STRIP_CUT = 9
CARD_CUT = 8
HIGHLIGHT_PAD_RATIO = 0.3

OUTCOME_COLOR = {
    "win": Colors.win,
    "loss": Colors.loss,
    "draw": Colors.text,
}


def _glow_behind(text_surf: pg.Surface, color: str) -> pg.Surface:
    """
    Build the coloured bloom that sits behind the outcome word, so winning or
    losing lands loudly instead of reading like a flat label

    :param text_surf: the rendered outcome word the glow is shaped from
    :param color: glow colour as a hex string
    :returns: blurred, tinted copy to blit behind the word
    """
    glow = soft_blur(text_surf)
    tint = pg.Surface(glow.get_size(), pg.SRCALPHA)
    tint.fill((*pg.Color(color)[:3], 130))
    glow.blit(tint, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    return glow


class ResultMenu(BaseModal):
    """
    The end-of-game card: the outcome word, how the game ended, the running
    series score online, the play of the game and the stat grid, sitting over
    the buttons that decide what happens next. It wears the shared modal
    shell, but the game screen draws it and routes its clicks itself, so
    unlike the other modals it is not in the shell's registry
    """

    def __init__(self, window: pg.Surface, callbacks: dict[str, Callable[[], None]],
                 pgn_available_provider: Callable[[], bool]) -> None:
        """
        Build the card the game screen keeps for its whole life, wired to the
        actions its buttons stand for. Nothing shows until a result is set

        :param window: the app window surface this modal draws onto
        :param callbacks: button key to the action it runs, keyed by new_game,
            open_pgn, menu and rematch
        :param pgn_available_provider: asked while drawing whether a saved PGN
            exists, which decides if Open PGN is offered at all
        """
        super().__init__(window)
        self.callbacks = callbacks
        self.pgn_available_provider = pgn_available_provider
        self.online_mode = False
        self.outcome: str | None = None
        self.intent = "draw"
        self.reason = ""
        self.stats: dict[str, Any] | None = None
        self.series: tuple[str, str, str] | None = None
        self.rematch_offered = False
        self.button_rects: dict[str, pg.Rect] = {}
        self.outcome_font = get_display_font(48)
        self.reason_font = get_font(12, bold=True)
        self.value_font = get_font(20, bold=True, mono=True)
        self.label_font = get_font(10, bold=True)
        self.button_font = get_font(14, bold=True)
        self.series_name_font = get_font(12, bold=True)
        self.series_score_font = get_font(16, mono=True)
        self._outcome_cache: tuple[tuple[str | None, str, int],
                                   pg.Surface, pg.Surface | None] | None = None

    def _on_rect_changed(self) -> None:
        """
        Rebuild every font from the card's height and throw the cached outcome
        word away, since it was rendered at the old size
        """
        h = self.rect.height
        self.outcome_font = get_display_font(max(int(h * 0.14), 26))
        self.reason_font = get_font(max(int(h * 0.05), 14), bold=True)
        self.detail_font = get_font(max(int(h * 0.032), 11), bold=True)
        self.value_font = get_font(max(int(h * 0.052), 13), bold=True, mono=True)
        self.label_font = get_font(max(int(h * 0.026), 8), bold=True)
        self.button_font = get_font(max(int(h * 0.04), 11), bold=True)
        self.series_name_font = get_font(max(int(h * 0.032), 11), bold=True)
        self.series_score_font = get_font(max(int(h * 0.042), 13), mono=True)
        self._outcome_cache = None

    def set_result(self, outcome: str | None, intent: str, reason: str,
                   stats: dict[str, Any] | None = None) -> None:
        """
        Fill the card in with how the game ended, which is also what makes it
        visible. The game screen feeds this while a result stands, so the card
        keeps up with a takeback or a resync undoing one

        :param outcome: the big word (VICTORY, DEFEAT, DRAW), None to clear
            the card and hide it again
        :param intent: win, loss or draw, which colours the word and the rail
        :param reason: line under the word saying how it ended and after how
            many moves
        :param stats: figures for the stat grid and the play of the game, None
            to leave the grid out
        """
        self.outcome = outcome
        self.intent = intent or "draw"
        self.reason = reason or ""
        self.stats = stats

    def set_series(self, name_a: str | None, name_b: str | None, score_a: str | None,
                   score_b: str | None) -> None:
        """
        Set the running score between these two players, which only online
        games keep. Passing no names clears the chip, which is what a local
        game does

        :param name_a: first player's nickname, None to hide the chip
        :param name_b: second player's nickname, None to hide the chip
        :param score_a: first player's score as text, halves included
        :param score_b: second player's score as text, halves included
        """
        if name_a is None or name_b is None:
            self.series = None
        else:
            self.series = (name_a, name_b, f"{score_a}{SCORE_SEP}{score_b}")

    def set_online_mode(self, online: bool) -> None:
        """
        Switch the card between its local and online faces, which decides
        whether the first button reads New Game or Rematch and whether the
        series chip may show at all

        :param online: True while this is an online game
        """
        self.online_mode = online

    def set_rematch_offered(self, offered: bool) -> None:
        """
        Note that the opponent has already asked for a rematch, which takes
        the player's own Rematch button off the row -- they answer through the
        banner over the board instead

        :param offered: True while a rematch offer from the opponent stands
        """
        self.rematch_offered = offered

    def reset(self) -> None:
        """
        Clear the card completely between games. Every pre-board overlay has
        to be reset this way, since a card left half set once left invisible
        buttons clickable over a fresh board
        """
        self.set_result(None, "draw", "")
        self.button_rects = {}
        self.rematch_offered = False

    def is_visible(self) -> bool:
        """
        Say whether the card is showing; the outcome word is the state here,
        there is no separate flag to keep in step with it

        :returns: True once a result has been set
        """
        return self.outcome is not None

    def draw(self) -> None:
        """
        Paint the card top to bottom -- outcome, reason, series chip,
        highlight strip, stat grid and buttons -- each block reporting where
        the next one may start. Drawing is also what fixes the button rects
        clicks are tested against
        """
        if not self.is_visible() or self.rect.width <= 0:
            self.button_rects = {}
            return
        self.draw_shell(self.intent)
        content = self.content_rect()
        y = content.y + max(int(self.rect.height * 0.02), 4)
        y = self._draw_outcome(content, y)
        y = self._draw_reason(content, y)
        y = self._draw_series(content, y)
        y = self._draw_highlight(content, y)
        self._draw_stats(content, y)
        self._draw_buttons(content)

    def _draw_outcome(self, content: pg.Rect, y: int) -> int:
        """
        Draw the big outcome word with its outline and, for a win or a loss,
        its glow. The rendered word is cached, since it is expensive and only
        changes with the result or the card's size

        :param content: usable area inside the shell, in window pixels
        :param y: top of this block in window pixels
        :returns: y where the next block starts, in window pixels
        """
        sw = max(int(self.outcome_font.get_height() * 0.035), 2)
        key = (self.outcome, self.intent, self.outcome_font.get_height())
        if self._outcome_cache is None or self._outcome_cache[0] != key:
            color = OUTCOME_COLOR.get(self.intent, Colors.text)
            text = stroked_text(self.outcome_font, cast(str, self.outcome).upper(),
                                color, Colors.outcome_stroke, sw)
            text = fit_text_to_rect(
                text, pg.Rect(0, 0, content.width, int(content.height * 0.3)))
            glow = _glow_behind(text, color) if self.intent != "draw" else None
            self._outcome_cache = (key, text, glow)
        _, text, glow = self._outcome_cache
        cx = content.centerx
        if glow is not None:
            self.window.blit(glow, (cx - glow.get_width() / 2, y))
        self.window.blit(text, (cx - text.get_width() / 2, y))
        return y + text.get_height() + max(int(self.rect.height * 0.012), 3)

    def _draw_reason(self, content: pg.Rect, y: int) -> int:
        """
        Draw the line explaining how the game ended and after how many moves,
        skipped entirely when there is nothing to say

        :param content: usable area inside the shell, in window pixels
        :param y: top of this block in window pixels
        :returns: y where the next block starts, in window pixels
        """
        if not self.reason:
            return y
        surf = self.reason_font.render(self.reason.upper(), True, Colors.text_dim)
        surf = fit_text_to_rect(surf, pg.Rect(0, 0, content.width, surf.get_height()))
        self.window.blit(surf, (content.centerx - surf.get_width() / 2, y))
        return y + surf.get_height() + max(int(self.rect.height * 0.03), 8)

    def _draw_series(self, content: pg.Rect, y: int) -> int:
        """
        Draw the chip holding the running score between the two players, which
        only an online game with a set series keeps

        :param content: usable area inside the shell, in window pixels
        :param y: top of this block in window pixels
        :returns: y where the next block starts, in window pixels
        """
        if not self.online_mode or self.series is None:
            return y
        name_a, name_b, score = self.series
        chip = draw_series_chip(
            self.window, (content.centerx, y + self.series_score_font.get_height()),
            name_a, name_b, score, self.series_name_font, self.series_score_font)
        return chip.bottom + max(int(self.rect.height * 0.02), 5)

    def _draw_highlight(self, content: pg.Rect, y: int) -> int:
        """
        Draw the play-of-the-game strip, the one moment the finished game
        picks out as worth remembering. Games without one skip the strip

        :param content: usable area inside the shell, in window pixels
        :param y: top of this block in window pixels
        :returns: y where the next block starts, in window pixels
        """
        potg = self.stats.get("play_of_the_game") if self.stats else None
        if not potg:
            return y
        h = max(int(self.rect.height * 0.085), 28)
        strip = cut_rect_surface((content.width, h), STRIP_CUT, Colors.potg_bg,
                                 border=Colors.potg_border, border_width=1,
                                 corners=("tr", "bl"))
        self.window.blit(strip, (content.x, y))
        pad = max(int(h * HIGHLIGHT_PAD_RATIO), 8)
        cy = y + h / 2
        label = self.detail_font.render("HIGHLIGHT", True, Colors.amber_hi)
        self.window.blit(label, (content.x + pad, cy - label.get_height() / 2))
        detail_x = content.x + pad + label.get_width() + max(int(h * HIGHLIGHT_PAD_RATIO), 8)
        detail = self.detail_font.render(potg, True, Colors.text)
        max_w = content.right - pad - detail_x
        if detail.get_width() > max_w > 0:
            detail = fit_text_to_rect(detail, pg.Rect(0, 0, max_w, detail.get_height()))
        self.window.blit(detail, (detail_x, cy - detail.get_height() / 2))
        return y + h + max(int(self.rect.height * 0.025), 6)

    def _stat_cells(self) -> list[tuple[str, str, str]]:
        """
        Lay the game's figures out as the six cells of the grid, in the order
        they are drawn: KOs, best streak, checks, moves, clock left and
        material

        :returns: value, suffix and label per cell, the suffix empty on the
            cells that do not use one
        """
        s = cast(dict[str, Any], self.stats)
        mine, theirs = s["kos"]
        mat = s["material"]
        mat_str = f"+{mat}" if mat > 0 else str(mat)
        return [
            (str(mine), f"/{theirs}", "KOs"),
            (f"×{s['streak']}", "", "Best streak"),
            (str(s["checks"]), "", "Checks"),
            (str(s["moves"]), "", "Moves"),
            (format_clock(s["clock_left"]), "", "Clock left"),
            (mat_str, "", "Material"),
        ]

    def _draw_stats(self, content: pg.Rect, y: int) -> None:
        """
        Draw the six stat cards as a three by two grid filling whatever is
        left between the blocks above and the buttons. Too little room and the
        grid is dropped rather than squashed

        :param content: usable area inside the shell, in window pixels
        :param y: top of the grid in window pixels
        """
        if not self.stats:
            return
        cols, rows = 3, 2
        gap = max(int(content.width * 0.02), 6)
        cell_w = (content.width - gap * (cols - 1)) / cols
        avail = self._buttons_top(content) - y - gap
        cell_h = (avail - gap * (rows - 1)) / rows
        if cell_h <= 0:
            return
        for i, (value, vs, label) in enumerate(self._stat_cells()):
            cx = content.x + (i % cols) * (cell_w + gap)
            cy = y + (i // cols) * (cell_h + gap)
            cell = pg.Rect(int(cx), int(cy), int(cell_w), int(cell_h))
            bg = cut_rect_surface(cell.size, CARD_CUT, Colors.surface,
                                  border=Colors.border, border_width=1,
                                  corners=("tr", "bl"))
            self.window.blit(bg, cell.topleft)
            value_surf = self.value_font.render(value, True, Colors.text)
            total_w = value_surf.get_width()
            vs_surf = None
            if vs:
                vs_surf = self.detail_font.render(vs, True, Colors.text_muted)
                total_w += vs_surf.get_width()
            vx = cell.centerx - total_w / 2
            vy = cell.y + cell_h * 0.28
            self.window.blit(value_surf, (vx, vy - value_surf.get_height() / 2))
            if vs_surf is not None:
                self.window.blit(vs_surf, (vx + value_surf.get_width(),
                                           vy - vs_surf.get_height() / 2))
            label_surf = self.label_font.render(label.upper(), True, Colors.text_muted)
            blit_centered(self.window, label_surf, (cell.centerx, cell.y + cell_h * 0.72))

    def _button_height(self) -> int:
        """
        Height of the button row, scaled off the card with a floor so the
        buttons stay comfortably clickable in a small window

        :returns: button height in pixels
        """
        return max(int(self.rect.height * 0.1), 30)

    def _buttons_top(self, content: pg.Rect) -> int:
        """
        Top edge of the button row, which is also the ceiling the stat grid
        has to fit above

        :param content: usable area inside the shell, in window pixels
        :returns: y of the top of the button row, in window pixels
        """
        btn_h = self._button_height()
        return content.bottom - btn_h

    def _draw_buttons(self, content: pg.Rect) -> None:
        """
        Draw the row of what to do next, which differs by game: Rematch online
        and New Game locally, with Rematch dropped while the opponent's own
        offer is standing and Open PGN dropped when nothing has been saved yet

        :param content: usable area inside the shell, in window pixels
        """
        btn_h = self._button_height()
        gap = max(int(content.width * 0.02), 6)
        row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        buttons = ONLINE_BUTTONS if self.online_mode else BUTTONS
        if self.online_mode and self.rematch_offered:
            buttons = [b for b in ONLINE_BUTTONS if b[1] != "rematch"]
        if not self.pgn_available_provider():
            buttons = [b for b in buttons if b[1] != "open_pgn"]
        self.button_rects = draw_button_row(
            self.window, row, buttons, self.button_font, gap,
            primary_keys={buttons[0][1]}, cut=True,
        )

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Run the action behind whichever button was clicked. The game screen
        calls this from its own click handling, since the card is not one of
        the shell's registered modals

        :param pos: click position in window pixels
        :returns: True when a button took the click
        """
        if not self.is_visible():
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                self.callbacks[key]()
                return True
        return False
