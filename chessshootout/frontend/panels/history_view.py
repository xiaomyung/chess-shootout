import time
from collections import OrderedDict
from collections.abc import Callable
from typing import cast

import pygame as pg

from chessshootout.backend.pieces import Piece, PieceColor, PieceType
from chessshootout.domain.pgn.load import (
    NO_CLOCK_LABEL, PgnSummary, format_relative_time, group_by_csmatchid, result_mark,
    scan_pgn_summaries, time_category,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    blit_centered, cut_rect_surface, infinity_surface, rounded_rect_surface, supersample,
)
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.icons import piece_png_path
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.widgets import build_shell


PGN_PATTERN = "*.pgn"

FILTER_OPTIONS = [("All", "all"), ("Online", "online"), ("Bot", "bot"), ("Local", "local")]
FILTER_TYPE = {"online": "Online", "bot": "Bot", "local": "Local"}
SCROLL_STEP = 56
SCROLLBAR_GUTTER = 14
CARD_GAP = 9
CARD_CACHE_MAX = 64

CARD_INNER_PAD = 3
CARD_TEXT_INSET = 16
CARD_TEXT_VPAD = 12
CARD_BADGE_SIZE = 44
CARD_BADGE_CUT = 8
GAME_BADGE_SIZE = 22
GAME_BADGE_CUT = 4
STAT_CARD_INSET = 14
STAT_CARD_TOP = 12
CHIP_PAD_X = 26
CHIP_GAP = 6
TYPE_PILL_PAD_X = 16
TYPE_PILL_PAD_Y = 5

_BADGE_TEXT = {"win": "W", "loss": "L", "draw": "½",
               "spec_win": "W", "spec_loss": "L"}
_BADGE_COLOR = {"win": Colors.win, "loss": Colors.loss, "draw": Colors.text_dim,
                "spec_win": Colors.text_dim, "spec_loss": Colors.text_dim}
_NEUTRAL_BADGES = {"draw", "spec_win", "spec_loss"}


def _game_outcome(game: PgnSummary, nickname: str | None) -> str:
    """
    Decide how one saved game is badged from the reading player's point of
    view -- won, lost or drawn -- and mark a game they did not play in as a
    neutral spectator result instead. The verdict is read from the file's own
    [Result] tag, never counted up from the moves

    :param game: summary of one saved game
    :param nickname: the local player's name, None when they have not set one
    :returns: the badge class, one of win, loss, draw, spec_win or spec_loss
    """
    symbol, code = result_mark(game.result_code, game.white, game.black, nickname)
    if code != "neutral":
        return code
    if symbol == "W":
        return "spec_win"
    if symbol == "L":
        return "spec_loss"
    return "draw"


def _game_ko(game: PgnSummary, nickname: str | None) -> tuple[int, int]:
    """
    Split one saved game's capture counts into the reading player's and their
    opponent's, which is what the KO score on a history card adds up. A game
    the player did not appear in is read from White's side

    :param game: summary of one saved game
    :param nickname: the local player's name, None when they have not set one
    :returns: captures made by the reading player and by their opponent
    """
    if nickname == game.black:
        return game.black_captures, game.white_captures
    return game.white_captures, game.black_captures


class MatchGroup:
    """
    One card in the saved-game list: either a single game or the whole rematch
    chain of an online series, gathered under the match id its games share. It
    folds their results into one verdict and adds up their KO counts, and the
    history list, the recent-games card and the profile stats all read these
    """

    def __init__(self, match_id: str | None, games: list[PgnSummary],
                 nickname: str | None) -> None:
        """
        Fold one series' games into a single card. The players, the clock and
        the timestamp are taken from the newest game, so the card reads as
        where that series stands now rather than where it started

        :param match_id: id shared by every game of an online series, None for
            a game that stands on its own
        :param games: the series' games, newest first
        :param nickname: the local player's name, which decides whose side each
            result is read from
        """
        self.match_id = match_id
        self.games = games
        newest = games[0]
        self.white = newest.white
        self.black = newest.black
        self.type = newest.type
        self.time_control = newest.time_control
        self.category = time_category(newest.time_control)
        self.sort_key = newest.sort_key
        self.outcomes = [_game_outcome(g, nickname) for g in games]
        kos = [_game_ko(g, nickname) for g in games]
        self.ko_you = sum(k[0] for k in kos)
        self.ko_opp = sum(k[1] for k in kos)
        self.reason = newest.reason
        self.time_ago = ""

    @property
    def result(self) -> str:
        """
        The single verdict the card shows for a whole series: whoever took more
        of its games. A series level on the games the player was in falls
        through to the ones they only watched, and anything still level reads
        as a draw

        :returns: the badge class, one of win, loss, draw, spec_win or spec_loss
        """
        wins = self.outcomes.count("win")
        losses = self.outcomes.count("loss")
        if wins > losses:
            return "win"
        if losses > wins:
            return "loss"
        spec_wins = self.outcomes.count("spec_win")
        spec_losses = self.outcomes.count("spec_loss")
        if spec_wins > spec_losses:
            return "spec_win"
        if spec_losses > spec_wins:
            return "spec_loss"
        return "draw"


def build_match_groups(summaries: list[PgnSummary], nickname: str | None) -> list[MatchGroup]:
    """
    Turn a flat list of saved-game summaries into the cards the history list,
    the recent-games card and the profile stats all draw, with an online
    series' rematches gathered under one card instead of listed separately

    :param summaries: game summaries, already in the order they will be shown
    :param nickname: the local player's name, which decides whose side each
        result is read from
    :returns: one group per card, in the order the summaries arrived
    """
    return [MatchGroup(mid, games, nickname)
            for mid, games in group_by_csmatchid(summaries)]


def load_match_groups(directory: str, pattern: str, nickname: str | None) -> list[MatchGroup]:
    """
    Read a folder of saved games straight into history cards -- the one call
    the History sub-view, the menu's recent-games card and the profile stats
    all start from. Files that cannot be read are skipped rather than fatal

    :param directory: folder the saved PGN files live in
    :param pattern: filename glob to match, in practice *.pgn
    :param nickname: the local player's name, which decides whose side each
        result is read from
    :returns: one group per card, newest first
    """
    return build_match_groups(scan_pgn_summaries(directory, pattern), nickname)


class HistoryView(ScrollHost):
    """
    The saved-game browser: a filter bar, a win/loss/draw summary and a
    scrolling list of match cards, where an online series folds open into its
    individual games and clicking any game opens it for review. The shell owns
    one of these and the menu's History sub-view shows and hides it
    """

    def __init__(self, window: pg.Surface, on_open: Callable[[str], None] | None) -> None:
        """
        Build the browser empty and hidden. Nothing is loaded until it is
        shown, so starting the app never goes near the games folder

        :param window: the app window this browser paints into
        :param on_open: called with the path of the game the player picked,
            which the shell turns into a review; None leaves the rows inert
        """
        self.window = window
        self.on_open = on_open
        self.rect = pg.Rect(0, 0, 0, 0)
        self.visible = False
        self.nickname: str | None = None
        self.filter = "all"
        self.expanded_match_id: str | None = None
        self._scroll_px = 0.0
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self._list_rect, self._content_h),
            wheel_step_px=SCROLL_STEP,
        )
        self._groups: list[MatchGroup] = []
        self._filter_rects: dict[str, pg.Rect] = {}
        self._row_hits: list[tuple[pg.Rect, tuple[str, str | None]]] = []
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._content_h = 0
        self._pawn_orig: dict[PieceColor, pg.Surface] | None = None
        self._pawn_cache: dict[tuple[PieceColor, int], pg.Surface] = {}
        self._arrow_cache: dict[tuple[int, str, str], pg.Surface] = {}
        self._rescale(1.0)

    def _pawn(self, color: PieceColor, size: int) -> pg.Surface:
        """
        The little pawn drawn beside each player's name on a card, taken from
        the same artwork the board uses. It is trimmed to its ink and scaled by
        height, so both pawns line up whatever size the card's font is, and
        every size is kept once it has been built

        :param color: side the pawn is drawn for
        :param size: wanted pawn height in pixels
        :returns: the scaled pawn image
        """
        if self._pawn_orig is None:
            self._pawn_orig = {
                c: pg.image.load(piece_png_path(Piece(PieceType.PAWN, c))).convert_alpha()
                for c in (PieceColor.WHITE, PieceColor.BLACK)
            }
        key = (color, size)
        if key not in self._pawn_cache:
            img = self._pawn_orig[color]
            img = img.subsurface(img.get_bounding_rect()).copy()
            scale = size / img.get_height()
            self._pawn_cache[key] = pg.transform.smoothscale(
                img, (max(int(img.get_width() * scale), 1), size))
        return self._pawn_cache[key]

    def _arrow(self, size: int, color: str, pointing: str) -> pg.Surface:
        """
        The chevron at the right of a card, pointing down while a series is
        folded open and right while it is shut. It is supersampled and cached
        per size, colour and direction, so it stays clean at any card size

        :param size: arrow box size in pixels; the sprite is square
        :param color: arrow colour as a hex string
        :param pointing: "down" for a series showing its games, anything else
            for one that is shut
        :returns: the arrow sprite
        """
        key = (size, color, pointing)
        if key not in self._arrow_cache:
            def render(surf: pg.Surface, k: int) -> None:
                """
                Draw the triangle on the oversized surface the supersampler
                hands in, its points given as fractions of that surface so the
                shape fits whatever size was asked for

                :param surf: oversized surface to draw on
                :param k: supersampling factor, not needed here because the
                    points are already relative to the surface
                """
                w, h = surf.get_size()
                if pointing == "down":
                    pts = [(w * 0.18, h * 0.34), (w * 0.82, h * 0.34), (w * 0.5, h * 0.7)]
                else:
                    pts = [(w * 0.34, h * 0.16), (w * 0.34, h * 0.84), (w * 0.74, h * 0.5)]
                pg.draw.polygon(surf, pg.Color(color), pts)
            self._arrow_cache[key] = supersample((size, size), render)
        return self._arrow_cache[key]

    def _rescale(self, scale: float) -> None:
        """
        Rebuild every font and every derived size for a new browser width,
        which is how the whole list grows and shrinks with the window. The card
        surface cache is emptied here, since everything in it was drawn at the
        old sizes

        :param scale: size multiplier for this width, 1.0 at the reference
            width and never below the browser's own floor
        """
        def sz(base: int, minimum: int) -> int:
            """
            Scale one base size, never letting it shrink past the point where
            the text stops being readable

            :param base: size in pixels at the reference width
            :param minimum: smallest size to allow
            :returns: the size to build this font at
            """
            return max(int(base * scale), minimum)
        self._title_font = get_display_font(sz(26, 16))
        self._filter_font = get_font(sz(12, 10), bold=True)
        self._count_font = get_mono_font(sz(12, 10), bold=True)
        self._stat_num_font = get_mono_font(sz(22, 15), bold=True)
        self._stat_label_font = get_font(sz(10, 8), bold=True)
        self._name_font = get_font(sz(14, 11), bold=True)
        self._vs_font = get_font(sz(12, 9), bold=True)
        self._sub_font = get_font(sz(11, 9))
        self._pill_font = get_font(sz(10, 8), bold=True)
        self._tc_font = get_mono_font(sz(13, 10), bold=True)
        self._series_font = get_mono_font(sz(17, 12), bold=True)
        self._kolbl_font = get_font(sz(9, 8), bold=True)
        self._time_font = get_mono_font(sz(11, 9))
        self._badge_font = get_display_font(sz(20, 13))
        self._gnum_font = get_font(sz(11, 9), bold=True)
        self._gbadge_font = get_display_font(sz(12, 10))
        self._greason_font = get_font(sz(13, 10))
        self._gko_font = get_font(sz(10, 8), bold=True)
        self._card_h = max(int(self._name_font.get_height()
                               + self._sub_font.get_height() + 32), 64)
        self._game_h = max(int(self._greason_font.get_height() * 1.9), 34)
        self._chip_cut = sz(6, 4)
        self._stat_cut = sz(8, 5)
        self._card_cut = sz(8, 5)
        self._card_cache: OrderedDict[tuple[str, int, bool], pg.Surface] = OrderedDict()

    def set_rect(self, rect: pg.Rect) -> None:
        """
        Place the browser in the menu's sub-view slot and rescale everything it
        draws to that width, which the menu does on every layout pass

        :param rect: the area the browser occupies, in window pixels
        """
        self.rect = pg.Rect(rect)
        if rect.width > 0:
            self._rescale(max(min(rect.width / 860, 1.0), 0.72))

    def show(self, directory: str, pattern: str, nickname: str | None = None) -> None:
        """
        Open the browser on a folder of saved games, reading and summarising
        every one of them, so the list is fresh each time the player lands on
        History. The filter, the folded-open series and the scroll position all
        start over from the top

        :param directory: folder the saved PGN files live in
        :param pattern: filename glob to match, in practice *.pgn
        :param nickname: the local player's name, which decides whose side each
            result is read from
        """
        self.nickname = nickname
        self._groups = load_match_groups(directory, pattern, nickname)
        now = time.time()
        for group in self._groups:
            group.time_ago = format_relative_time(group.sort_key, now)
        self.filter = "all"
        self.expanded_match_id = None
        self._scroll_px = 0.0
        self.scroll.cancel()
        self.visible = True

    def hide(self) -> None:
        """
        Close the browser and let go of everything it had loaded -- the games,
        the row hit boxes and the cached card surfaces -- so a list nobody is
        looking at costs nothing
        """
        self.visible = False
        self.scroll.cancel()
        self._groups = []
        self._row_hits = []
        self._card_cache.clear()

    def is_visible(self) -> bool:
        """
        Whether the browser is on screen, which is what makes the scroll host
        ignore wheel and drag gestures while History is not the sub-view
        showing

        :returns: True while the browser is showing
        """
        return self.visible

    def _visible_groups(self) -> list[MatchGroup]:
        """
        The cards the current filter lets through -- all of them, or only the
        online, bot or local games

        :returns: the groups to draw, in the order they were loaded
        """
        if self.filter == "all":
            return self._groups
        want = FILTER_TYPE[self.filter]
        return [g for g in self._groups if g.type == want]

    def _stats(self) -> tuple[int, int, int]:
        """
        Count wins, losses and draws across the cards the filter lets through,
        which is what the three tiles above the list print. Games the player
        only watched are counted with the draws, being neither of theirs

        :returns: wins, losses and draws for the current filter
        """
        groups = self._visible_groups()
        return (sum(1 for g in groups if g.result == "win"),
                sum(1 for g in groups if g.result == "loss"),
                sum(1 for g in groups if g.result in _NEUTRAL_BADGES))

    def draw_onto(self, surface: pg.Surface) -> None:
        """
        Draw the browser onto a surface other than the window, which the menu
        needs while it composites a sub-view transition onto a scratch surface.
        The usual target is put back afterwards, whatever happens

        :param surface: surface to draw on for this call only
        """
        prev = self.window
        self.window = surface
        try:
            self.draw()
        finally:
            self.window = prev

    def draw(self) -> None:
        """
        Paint the browser for this frame: the title row with its filter chips,
        the three summary tiles, then the scrolling list of cards filling
        whatever height is left. A hidden browser, or one with no width yet,
        draws nothing
        """
        if not self.visible or self.rect.width <= 0:
            return
        self.scroll.tick()
        x, w = self.rect.x, self.rect.width
        header_h = max(int(self._title_font.get_height() * 1.25), 34)
        self._draw_header(x, self.rect.y, w, header_h)
        stats_y = self.rect.y + header_h + 18
        stat_text = self._stat_num_font.get_height() + self._stat_label_font.get_height()
        stats_h = max(stat_text + 27, 58)
        self._draw_stats(x, stats_y, w, stats_h)
        list_top = stats_y + stats_h + 18
        self._list_rect = pg.Rect(x, list_top, w, max(self.rect.bottom - list_top, 0))
        self._draw_list()

    def _draw_header(self, x: int, y: int, w: int, h: int) -> None:
        """
        Draw the row above the list: the HISTORY title on the left, the filter
        chips along the right, and the chip counting how many games the filter
        left standing

        :param x: left edge of the browser in window pixels
        :param y: top edge of the header
        :param w: browser width in pixels
        :param h: header height in pixels
        """
        cy = y + h // 2
        title = self._title_font.render("HISTORY", True, Colors.text)
        self.window.blit(title, (x, cy - title.get_height() // 2))

        right = x + w
        right = self._draw_filters(right, cy)
        self._draw_count_chip(right - 12, cy)

    def _draw_filters(self, right: int, cy: int) -> int:
        """
        Draw the All, Online, Bot and Local chips right-aligned in the header,
        the chosen one lit and the hovered one raised, and remember where each
        landed so a later click can be matched against them

        :param right: right edge the chip row ends at, in window pixels
        :param cy: vertical centre of the header
        :returns: the left edge of the chip row, which is where the count chip
            is hung from
        """
        self._filter_rects = {}
        chips = []
        for label, key in FILTER_OPTIONS:
            tw = self._filter_font.size(label)[0]
            chips.append((label, key, tw + CHIP_PAD_X))
        total = sum(c[2] for c in chips) + CHIP_GAP * (len(chips) - 1)
        cx = right - total
        left_edge = cx
        for label, key, cw in chips:
            rect = pg.Rect(cx, cy - 15, cw, 30)
            on = key == self.filter
            hovered = rect.collidepoint(pg.mouse.get_pos())
            if on:
                bg, border, color = Colors.surface_active, Colors.accent, Colors.text
            elif hovered:
                bg, border, color = Colors.surface_hover, Colors.border, Colors.text
            else:
                bg, border, color = Colors.surface, Colors.border, Colors.text_dim
            self.window.blit(cut_rect_surface(rect.size, self._chip_cut, bg, border=border,
                                              border_width=1, corners=("tr", "bl")),
                             rect.topleft)
            surf = self._filter_font.render(label, True, color)
            self.window.blit(surf, (rect.centerx - surf.get_width() // 2,
                                    rect.centery - surf.get_height() // 2))
            self._filter_rects[key] = rect
            cx += cw + CHIP_GAP
        return left_edge

    def _draw_count_chip(self, right: int, cy: int) -> None:
        """
        Draw the small chip saying how many games the current filter is showing

        :param right: right edge the chip is hung from, in window pixels
        :param cy: vertical centre of the header
        """
        text = f"{len(self._visible_groups())} games"
        surf = self._count_font.render(text, True, Colors.text_dim)
        w = surf.get_width() + 14
        h = surf.get_height() + 6
        rect = pg.Rect(right - w, cy - h // 2, w, h)
        self.window.blit(rounded_rect_surface(rect.size, 4, Colors.surface_hover), rect.topleft)
        self.window.blit(surf, (rect.x + 7, rect.centery - surf.get_height() // 2))

    def _draw_stats(self, x: int, y: int, w: int, h: int) -> None:
        """
        Draw the three tiles between the header and the list, counting the
        wins, losses and draws of whatever the filter is showing

        :param x: left edge of the tile row in window pixels
        :param y: top edge of the row
        :param w: total width the three tiles share
        :param h: tile height in pixels
        """
        wins, losses, draws = self._stats()
        gap = 10
        card_w = (w - 2 * gap) / 3
        cards = ((wins, "WINS", Colors.win), (losses, "LOSSES", Colors.loss),
                 (draws, "DRAWS", Colors.text))
        for i, (value, label, color) in enumerate(cards):
            rect = pg.Rect(int(x + i * (card_w + gap)), y, int(card_w), h)
            self.window.blit(cut_rect_surface(rect.size, self._stat_cut, Colors.surface,
                                              border=Colors.border, border_width=1,
                                              corners=("tr", "bl")),
                             rect.topleft)
            num = self._stat_num_font.render(str(value), True, color)
            self.window.blit(num, (rect.x + STAT_CARD_INSET, rect.y + STAT_CARD_TOP))
            lab = self._stat_label_font.render(label, True, Colors.text_muted)
            self.window.blit(lab, (rect.x + STAT_CARD_INSET,
                                   rect.y + STAT_CARD_TOP + num.get_height() + 3))

    def _compute_layout(self, groups: list[MatchGroup]) -> tuple[
            list[tuple[MatchGroup, bool, int]], int]:
        """
        Measure the list before any of it is drawn: how tall each card's block
        is, a folded-open series growing by one row per game it holds, and how
        tall the whole list therefore comes to. The scroll range is worked out
        from that total

        :param groups: the cards to measure, already filtered
        :returns: each card with whether it is folded open and how tall its
            whole block is, and the total content height in pixels
        """
        blocks = []
        for g in groups:
            expanded = self.expanded_match_id == g.match_id and len(g.games) > 1
            detail_h = len(g.games) * self._game_h if expanded else 0
            blocks.append((g, expanded, self._card_h + detail_h))
        content_h = sum(bh for _, _, bh in blocks) + CARD_GAP * len(blocks)
        return blocks, content_h

    def _draw_list(self) -> None:
        """
        Draw the scrolling list and record where every row ended up, so a click
        can be matched to a card or to one game inside a folded-open series.
        Rows scrolled out of sight are still measured and registered but not
        painted, which is what keeps a long history cheap to scroll, and an
        empty list says so rather than showing nothing
        """
        self._row_hits = []
        groups = self._visible_groups()
        if not groups:
            surf = self._greason_font.render("No games yet — go start a shootout.",
                                             True, Colors.text_muted)
            self.window.blit(surf, (self._list_rect.centerx - surf.get_width() // 2,
                                    self._list_rect.y + 40))
            self._content_h = 0
            return

        blocks, self._content_h = self._compute_layout(groups)
        max_offset = max(0, self._content_h - self._list_rect.height)
        self._scroll_px = max(0.0, min(self._scroll_px, max_offset))
        row_w = self._list_rect.width - (SCROLLBAR_GUTTER if max_offset > 0 else 0)
        mouse = pg.mouse.get_pos()

        prev_clip = self.window.get_clip()
        self.window.set_clip(self._list_rect)
        try:
            y = self._list_rect.y - self._scroll_px
            for group, expanded, block_h in blocks:
                on_screen = (y + block_h >= self._list_rect.y
                             and y <= self._list_rect.bottom)
                card_rect = pg.Rect(self._list_rect.x, y, row_w, self._card_h)
                if on_screen:
                    self._blit_card(card_rect, group, block_h, expanded, mouse)
                if len(group.games) > 1:
                    self._row_hits.append((card_rect, ("toggle", group.match_id)))
                else:
                    self._row_hits.append((card_rect, ("open", group.games[0].path)))
                if expanded:
                    for i, game in enumerate(group.games):
                        row_rect = pg.Rect(self._list_rect.x, y + self._card_h + i * self._game_h,
                                           row_w, self._game_h)
                        if on_screen:
                            self._draw_game_row(row_rect, group, game, i)
                        self._row_hits.append((row_rect, ("open", game.path)))
                y += block_h + CARD_GAP
        finally:
            self.window.set_clip(prev_clip)
        self._draw_scroll_indicator()

    def _blit_card(self, rect: pg.Rect, group: MatchGroup, block_h: int, expanded: bool,
                   mouse: tuple[int, int]) -> None:
        """
        Put one card on screen. A shut card comes straight out of the surface
        cache, while a folded-open one is drawn live because its height changes
        with the number of games hanging under it

        :param rect: the card's own row in window pixels, the head of its block
        :param group: the series this card stands for
        :param block_h: full height of the card and any games under it
        :param expanded: True while this series is showing its games
        :param mouse: cursor position in window pixels, for the hover state
        """
        hovered = rect.collidepoint(mouse)
        if expanded:
            self._draw_card(rect, group, block_h, hovered)
            return
        surf = self._card_surface(group, rect.width, hovered)
        self.window.blit(surf, rect.topleft)

    def _card_surface(self, group: MatchGroup, render_width: int, hovered: bool) -> pg.Surface:
        """
        The pre-drawn surface for one shut card, kept in a small
        most-recently-used cache so scrolling the list blits instead of
        redrawing. Hovering counts as a different card, since it changes the
        fill, and the oldest entry is dropped once the cache is full

        :param group: the series this card stands for
        :param render_width: card width in pixels
        :param hovered: True while the cursor is over it
        :returns: the finished card surface
        """
        key = (group.match_id or group.games[0].path, render_width, hovered)
        surf = self._card_cache.get(key)
        if surf is not None:
            self._card_cache.move_to_end(key)
            return surf
        surf = pg.Surface((render_width, self._card_h), pg.SRCALPHA)
        prev_window = self.window
        self.window = surf
        try:
            self._draw_card(pg.Rect(0, 0, render_width, self._card_h),
                            group, self._card_h, hovered)
        finally:
            self.window = prev_window
        self._card_cache[key] = surf
        if len(self._card_cache) > CARD_CACHE_MAX:
            self._card_cache.popitem(last=False)
        return surf

    def _draw_card(self, rect: pg.Rect, group: MatchGroup, block_h: int,
                   hovered: bool) -> None:
        """
        Draw one card: the coloured edge that states its result at a glance,
        the panel over it, the result badge, both players and the line of
        detail under them, then the KO score, the clock, the type pill and the
        chevron down the right-hand side

        :param rect: the card's own row in window pixels
        :param group: the series this card stands for
        :param block_h: full height of the block, taller than the row while the
            series is folded open
        :param hovered: True while the cursor is over it
        """
        inner_x = rect.x + CARD_INNER_PAD
        inner_w = rect.width - CARD_INNER_PAD
        expanded = block_h > rect.height
        bg = Colors.surface_hover if hovered else Colors.surface
        self.window.blit(cut_rect_surface((rect.width, block_h), self._card_cut,
                                          _BADGE_COLOR[group.result], corners=("tr", "bl")),
                         rect.topleft)
        if expanded:
            self.window.blit(
                cut_rect_surface((inner_w, block_h), self._card_cut, Colors.surface_raised,
                                 border=Colors.border, border_width=1, corners=("tr", "bl")),
                (inner_x, rect.y))
            self.window.blit(cut_rect_surface((inner_w, rect.height), self._card_cut, bg,
                                              corners=("tr", "bl")),
                             (inner_x, rect.y))
        else:
            self.window.blit(
                cut_rect_surface((inner_w, rect.height), self._card_cut, bg,
                                 border=Colors.border, border_width=1, corners=("tr", "bl")),
                (inner_x, rect.y))

        badge = pg.Rect(rect.x + CARD_TEXT_INSET, rect.centery - CARD_BADGE_SIZE // 2,
                        CARD_BADGE_SIZE, CARD_BADGE_SIZE)
        self._draw_badge(badge, group.result, self._badge_font, CARD_BADGE_CUT)

        text_x = badge.right + CARD_TEXT_INSET
        self._draw_matchup(text_x, rect.y + CARD_TEXT_VPAD, group)
        meta = (f"{group.category} · {len(group.games)} games" if len(group.games) > 1
                else f"{group.category} · {group.reason}")
        sub = self._sub_font.render(meta, True, Colors.text_muted)
        self.window.blit(sub, (text_x, rect.bottom - sub.get_height() - CARD_TEXT_VPAD))

        self._draw_card_right(rect, group)

    def _draw_badge(self, rect: pg.Rect, result: str, font: pg.font.Font, cut: int) -> None:
        """
        Draw the letter badge that states a result at a glance, tinted with
        that result's own colour. A draw and a game the player only watched are
        left neutral, so only their own wins and losses stand out

        :param rect: the badge's box in window pixels
        :param result: badge class, one of win, loss, draw, spec_win or
            spec_loss
        :param font: font the letter is drawn in
        :param cut: corner cut in pixels for the badge's shell
        """
        color = _BADGE_COLOR[result]
        if result in _NEUTRAL_BADGES:
            bg, border, ink = Colors.surface_hover, Colors.border, Colors.text_dim
        else:
            bg, border, ink = color + "26", color + "5c", color
        self.window.blit(cut_rect_surface(rect.size, cut, bg, border=border, border_width=1,
                                          corners=("tr", "bl")), rect.topleft)
        letter = font.render(_BADGE_TEXT[result], True, ink)
        blit_centered(self.window, letter, rect.center)

    def _draw_matchup(self, x: int, y: int, group: MatchGroup) -> None:
        """
        Draw the line naming who played: White's pawn and name, the vs, then
        Black's, both read from the PGN header tags

        :param x: left edge of the line in window pixels
        :param y: top of the line
        :param group: the series whose players are being named
        """
        cy = y + self._name_font.get_height() // 2
        x = self._draw_player(x, cy, PieceColor.WHITE,
                              group.white, group.white == self.nickname)
        vs = self._vs_font.render("vs", True, Colors.text_muted)
        x += 2
        self.window.blit(vs, (x, cy - vs.get_height() // 2))
        x += vs.get_width() + 8
        self._draw_player(x, cy, PieceColor.BLACK,
                          group.black, group.black == self.nickname)

    def _draw_player(self, x: int, cy: int, color: PieceColor, name: str, is_me: bool) -> int:
        """
        Draw one side's pawn and name, the reading player's own name picked out
        in amber so their seat in the game is obvious, and report where the
        next thing along may start

        :param x: left edge in window pixels
        :param cy: vertical centre of the line
        :param color: side this player had, which picks the pawn
        :param name: display name from the PGN header tag
        :param is_me: True when this is the reading player, which colours the
            name
        :returns: the x to carry on from
        """
        pawn = self._pawn(color, int(self._name_font.get_height() * 1.25))
        self.window.blit(pawn, (x, cy - pawn.get_height() // 2))
        x += pawn.get_width() + 6
        nsurf = self._name_font.render(name, True,
                                       Colors.amber_hi if is_me else Colors.text)
        self.window.blit(nsurf, (x, cy - nsurf.get_height() // 2))
        return x + nsurf.get_width() + 8

    def _draw_card_right(self, rect: pg.Rect, group: MatchGroup) -> None:
        """
        Draw the right-hand end of a card: the KO score with its label, when
        the game was played, the clock it was played at -- an infinity mark
        when it had none -- the type pill and the chevron

        :param rect: the card's own row in window pixels
        :param group: the series this card stands for
        """
        chev_cx = rect.right - 14
        self._draw_chevron(chev_cx, rect.centery, len(group.games) > 1,
                           self.expanded_match_id == group.match_id)

        when_right = chev_cx - 18
        series = self._series_font.render(f"{group.ko_you}-{group.ko_opp}", True, Colors.text)
        kolbl = self._kolbl_font.render("KO", True, Colors.text_muted)
        timesurf = self._time_font.render(group.time_ago, True, Colors.text_muted)
        line1_w = series.get_width() + 5 + kolbl.get_width()
        block_w = max(line1_w, timesurf.get_width())
        bx = when_right - block_w
        self.window.blit(series, (when_right - line1_w, rect.centery - series.get_height() - 1))
        self.window.blit(kolbl, (when_right - kolbl.get_width(),
                                 rect.centery - series.get_height() + 4))
        self.window.blit(timesurf, (when_right - timesurf.get_width(), rect.centery + 4))

        meta_right = bx - 18
        if group.time_control == NO_CLOCK_LABEL:
            tc = infinity_surface(max(int(self._tc_font.get_height() * 0.6), 8), Colors.text)
        else:
            tc = self._tc_font.render(group.time_control, True, Colors.text)
        self.window.blit(tc, (meta_right - tc.get_width(), rect.centery + 4))
        self._draw_type_pill(meta_right, rect.centery - 3, group.type)

    def _draw_type_pill(self, right: int, bottom: int, type_label: str) -> None:
        """
        Draw the pill saying what kind of game this was, an online one standing
        out in amber against the muted local and bot ones

        :param right: right edge the pill is hung from, in window pixels
        :param bottom: bottom edge of the pill
        :param type_label: the kind as the summary read it off the filename,
            e.g. Online
        """
        text = type_label.upper()
        online = type_label == "Online"
        color = Colors.amber_hi if online else Colors.text_dim
        bg = (Colors.amber + "1a") if online else Colors.surface_raised
        border = (Colors.amber + "57") if online else Colors.border
        surf = self._pill_font.render(text, True, color)
        w = surf.get_width() + TYPE_PILL_PAD_X
        h = surf.get_height() + TYPE_PILL_PAD_Y
        rect = pg.Rect(right - w, bottom - h, w, h)
        self.window.blit(rounded_rect_surface(rect.size, h // 2, bg,
                                              border=border, border_width=1), rect.topleft)
        self.window.blit(surf, (rect.centerx - surf.get_width() // 2,
                                rect.centery - surf.get_height() // 2))

    def _draw_chevron(self, x: int, cy: int, multi: bool, expanded: bool) -> None:
        """
        Draw the arrow at the right of a card: down and in the accent colour
        while a series is showing its games, right and muted otherwise, so a
        card that can be folded open looks the same as one that cannot until it
        is opened

        :param x: horizontal centre of the arrow in window pixels
        :param cy: vertical centre of the card
        :param multi: True when the series holds more than one game
        :param expanded: True while this series is the folded-open one
        """
        size = max(int(self._name_font.get_height() * 0.8), 10)
        if multi and expanded:
            arrow = self._arrow(size, Colors.accent, "down")
        else:
            arrow = self._arrow(size, Colors.text_muted, "right")
        self.window.blit(arrow, (x - arrow.get_width() // 2, cy - arrow.get_height() // 2))

    def _draw_game_row(self, rect: pg.Rect, group: MatchGroup, game: PgnSummary,
                       index: int) -> None:
        """
        Draw one game of a folded-open series: its number in the series, its
        own result badge, how it ended and its KO score, on a row that lights
        up under the cursor because clicking it opens that game for review

        :param rect: the row's box in window pixels
        :param group: the series this game belongs to, not read for the row
            itself
        :param game: summary of the game on this row
        :param index: position within the series, which numbers the row
        """
        if rect.collidepoint(pg.mouse.get_pos()):
            hov = pg.Rect(rect.x + 5, rect.y + 1, rect.width - 12, rect.height - 2)
            self.window.blit(rounded_rect_surface(hov.size, 6, Colors.surface_hover),
                             hov.topleft)
        pg.draw.line(self.window, Colors.border,
                     (rect.x + 12, rect.y), (rect.right - 12, rect.y), 1)
        gnum_shell_w = max(int(rect.height * 0.16), 4)
        gnum_shell_h = max(int(rect.height * 0.42), 9)
        gnum_shell = build_shell(gnum_shell_w, gnum_shell_h)
        self.window.blit(gnum_shell, (rect.x + 14, rect.centery - gnum_shell.get_height() // 2))
        gnum = self._gnum_font.render(f"GAME {index + 1}", True, Colors.text_muted)
        self.window.blit(gnum, (rect.x + 20 + gnum_shell_w,
                                rect.centery - gnum.get_height() // 2))
        outcome = _game_outcome(game, self.nickname)
        badge = pg.Rect(rect.x + 96 + gnum_shell_w, rect.centery - GAME_BADGE_SIZE // 2,
                        GAME_BADGE_SIZE, GAME_BADGE_SIZE)
        self._draw_badge(badge, outcome, self._gbadge_font, GAME_BADGE_CUT)
        reason = self._greason_font.render(game.reason, True, Colors.text_dim)
        self.window.blit(reason, (badge.right + 14, rect.centery - reason.get_height() // 2))
        you, opp = _game_ko(game, self.nickname)
        ko = self._gko_font.render(f"{you}-{opp} KO", True, Colors.text_muted)
        shell_h = max(int(ko.get_height() * 0.9), 9)
        shell = build_shell(max(int(shell_h * 0.5), 5), shell_h)
        self.window.blit(shell, (rect.right - ko.get_width() - shell.get_width() - 36,
                                 rect.centery - shell.get_height() // 2))
        self.window.blit(ko, (rect.right - ko.get_width() - 28,
                              rect.centery - ko.get_height() // 2))

    def _draw_scroll_indicator(self) -> None:
        """
        Draw the list's scrollbar, which fades itself out a couple of seconds
        after the last scroll so a settled list stays clean
        """
        self.scroll.draw_thumb(self.window)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a click on the browser: a filter chip switches which games are
        listed, a card holding several games folds them open or shut, and any
        single game is handed to the shell to open for review. A click that
        lands on the browser but hits nothing is still swallowed, so it never
        falls through to the menu behind

        :param pos: click position in window pixels
        :returns: True when the click landed on the browser
        """
        if not self.visible:
            return False
        for key, rect in self._filter_rects.items():
            if rect.collidepoint(pos):
                self.filter = key
                self.expanded_match_id = None
                self._scroll_px = 0.0
                self.scroll.cancel()
                return True
        if self._list_rect.collidepoint(pos):
            for row_rect, action in self._row_hits:
                if not row_rect.collidepoint(pos):
                    continue
                kind, value = action
                if kind == "toggle":
                    self.expanded_match_id = None if self.expanded_match_id == value else value
                elif self.on_open is not None:
                    self.on_open(cast(str, value))
                return True
        return self.rect.collidepoint(pos)
