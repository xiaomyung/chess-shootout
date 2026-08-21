import time
from datetime import datetime
from typing import Any

import pygame as pg

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.domain.pgn.load import format_relative_time
from chessshootout.frontend.menu.view import scale_floor, seeded_avatar_palette
from chessshootout.frontend.panels.history_view import (
    MatchGroup, PGN_PATTERN, load_match_groups)
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import chevron_surface, cut_rect_surface
from chessshootout.frontend.visual.emoji import flag_surface
from chessshootout.frontend.visual.fonts import get_font, get_mono_font
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.widgets import draw_avatar, wrap_words
from chessshootout.online.news import NEWS_DATE_FORMAT, format_news_date


RECENT_MATCHES_LIMIT = 3
NEWS_BULLET = "• "
NEWS_GUTTER = 14
ELLIPSIS = "…"

CARD_GAP = 12
CARD_CUT = 8
PAD_X = 14
HEADER_H = 44
PROFILE_H = 70
BODY_ROW_H = 42
FOOTER_H = 32
NEWS_PAD_Y = 12
NEWS_TITLE_GAP = 6
NEWS_LINE_GAP = 4
HEADLINE_ROW_H = 26
AVATAR_SIZE = 40
CHEVRON_SIZE = 11
FLAG_SIZE = 14

_BADGE_LETTER = {"win": "W", "loss": "L", "draw": "½", "spec_win": "W", "spec_loss": "L"}
_BADGE_COLOR = {"win": Colors.win, "loss": Colors.loss, "draw": Colors.text_dim,
                "spec_win": Colors.text_dim, "spec_loss": Colors.text_dim}


def _elide(font: pg.font.Font, text: str, max_w: int) -> str:
    """
    Cut a label down to the width it has and end it with an ellipsis, so a
    long opponent name or headline is shortened rather than spilling out of
    its card. The cut is found by binary search on the rendered width, which
    is what makes it land right in a proportional font

    :param font: the face the label will be drawn in
    :param text: label as it would ideally read
    :param max_w: room available for it, in pixels
    :returns: the original text when it fits, otherwise a shortened form
        ending in an ellipsis
    """
    if font.size(text)[0] <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(text[:mid] + ELLIPSIS)[0] <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ELLIPSIS


def _opponent(group: MatchGroup, nickname: str) -> str:
    """
    Name the other player in a saved match, which is the one name a recent
    match row has room for. A game this player was not in -- one they watched
    -- has no other player, and reads as the black side

    :param group: a saved match, its two player names already read from the
        PGN tags
    :param nickname: the name this player is currently going by
    :returns: the name to print on the row
    """
    if nickname and nickname == group.white:
        return group.black
    if nickname and nickname == group.black:
        return group.white
    return group.black


def _valid_news_date(value: object) -> bool:
    """
    Whether a date can be compared with the others, which is what keeps the
    unread count honest. Both the feed and the stored last-seen marker come
    from outside the app, so anything that will not parse is left out of the
    count rather than being guessed at

    :param value: a date from the feed or from the stored settings, of any
        shape
    :returns: True when it is a date in the feed's own format
    """
    try:
        datetime.strptime(value, NEWS_DATE_FORMAT)
        return True
    except (ValueError, TypeError):
        return False


def _item_key(item: dict[str, Any]) -> tuple[str, str]:
    """
    Identify one news item by its date and headline. Items carry no id of
    their own and the whole list is replaced when a fetch lands, so this is
    how the card remembers which item the player had open

    :param item: one news item as the news client hands it over
    :returns: the date and title pair that stands for this item
    """
    return (item.get("date", ""), item.get("title", ""))


class NewsBox(ScrollHost):
    """
    The scrolling inside of the expanded News card. The card can only grow
    into the space the other cards leave, so an open item is often taller than
    the card itself; this is what the wheel is handed then, which is why the
    news scrolls within its card instead of pushing the other headers away
    """

    def __init__(self, stack: "CardStack") -> None:
        """
        Wire the box to the card column that owns it. It keeps no layout of
        its own worth the name -- its rect and content height are stamped on
        it by the column each time the news is drawn

        :param stack: the card column this box lives inside
        """
        self._stack = stack
        self._rect = pg.Rect(0, 0, 0, 0)
        self._content_h = 0
        self._scroll_px = 0.0
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self._rect, self._content_h),
            wheel_step_px=lambda: self._stack._s(BODY_ROW_H, 32),
        )

    def is_visible(self) -> bool:
        """
        Whether the wheel may move this box at all. Only an expanded News card
        with real room on screen qualifies, so a collapsed card -- or a window
        too short to leave the news any height -- never swallows the wheel

        :returns: True while the box is showing and can be scrolled
        """
        return (self._stack.news_expanded() and self._stack._rect.width > 0
                and self._rect.height > 0)

    def tick(self) -> None:
        """
        Advance a fling by one frame, called by the column on every frame it
        draws so a flick keeps coasting
        """
        self.scroll.tick()

    def reset(self) -> None:
        """
        Send the news back to the top and drop any motion, done when the card
        is expanded so it always opens on the newest item rather than wherever
        it was last left
        """
        self._scroll_px = 0.0
        self.scroll.cancel()

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Deliver a tap that turned out not to be a scroll drag, which opens or
        closes the news item under the cursor. This is the path a click takes
        once this box has claimed the press

        :param pos: click position in window pixels
        :returns: True when an item was opened or closed
        """
        return self._stack._handle_news_item_click(pos)


class CardStack(ScrollHost):
    """
    The column of cards down the right of the Play view: the player's profile
    row, their recent matches and the news feed. It is a strict accordion --
    every card starts collapsed and opening one closes the other -- and a card
    with nothing to say is not built at all, so Recent matches stays away
    until a game has been saved and News until the feed has items
    """

    def __init__(self, app: Any) -> None:
        """
        Build the column empty. It holds nothing until the menu gives it a
        rect and calls refresh, which the menu does every time the player
        lands on Play

        :param app: the Frontend shell, this column's route to the news
            client, the sounds, the menu's navigation and PGN review
        """
        self.app = app
        self._rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._recent_groups = []
        self._news_items = []
        self._news_generation = -1
        self._open = None
        self._open_news_item = None
        self._news_item_hits = []
        self._valid_news_dates = []
        self._body_lines_cache = {}
        self.news_box = NewsBox(self)
        self._cards = []
        self._content_h = 0
        self._scroll_px = 0.0
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self._rect, self._content_h),
            wheel_step_px=BODY_ROW_H,
        )
        self._fonts_ready = False
        self._profile_avatar_palette = None
        self._profile_avatar_seed = None

    def is_visible(self) -> bool:
        """
        Whether the wheel may reach this column. It is only ever drawn on the
        Play view, so whenever it exists on screen it is scrollable

        :returns: True always
        """
        return True

    def news_generation(self) -> int:
        """
        Which version of the feed these cards were built from. The menu
        compares it against the news client's own counter every frame and
        rebuilds the column when a background fetch has landed since

        :returns: the feed version the cards currently show
        """
        return self._news_generation

    def refresh(self) -> None:
        """
        Rebuild the column from what is true right now: the saved games, how
        long ago each was played, and the news. Anything that has gone away is
        closed rather than left open on nothing, so a card or a news item that
        no longer exists cannot keep the accordion open
        """
        nickname = env.get_nickname()
        groups = load_match_groups(str(paths.get_games_dir()), PGN_PATTERN, nickname)
        now = time.time()
        for group in groups:
            group.time_ago = format_relative_time(group.sort_key, now)
        self._recent_groups = groups[:RECENT_MATCHES_LIMIT]
        self._news_items = self.app.news_client.items()
        self._news_generation = self.app.news_client.generation()
        self._valid_news_dates = [item["date"] for item in self._news_items
                                  if _valid_news_date(item.get("date", ""))]
        self._body_lines_cache = {}
        if self._open not in self._visible_card_keys():
            self._open = None
        if self._open_news_item not in self._news_item_keys():
            self._open_news_item = None
        self._compute_layout()

    def _news_item_keys(self) -> set[tuple[str, str]]:
        """
        Which items the feed holds at the moment, used after a refresh to see
        whether the item the player had open is still there

        :returns: the date and title pair of every current item
        """
        return {_item_key(item) for item in self._news_items}

    def news_expanded(self) -> bool:
        """
        Whether News is the card that is open, which is how the menu knows the
        inner news box may be handed the wheel

        :returns: True while the News card is expanded
        """
        return self._open == "news"

    def _visible_card_keys(self) -> list[str]:
        """
        Which cards exist at all, in the order they stack. Profile is always
        there; Recent matches appears once a game has been saved and News once
        the feed has items, so the column never shows an empty card

        :returns: the card keys to build, top to bottom
        """
        keys = ["profile"]
        if self._recent_groups:
            keys.append("recent")
        if self._news_items:
            keys.append("news")
        return keys

    def _s(self, value: int, floor: int = 1) -> int:
        """
        Scale one design measurement to this window, never letting it fall
        below the floor, so the cards shrink gracefully instead of collapsing

        :param value: measurement in pixels at the reference window size
        :param floor: smallest pixel value this measurement may take
        :returns: the scaled measurement in pixels
        """
        return scale_floor(value, self._scale, floor)

    def set_rect(self, rect: pg.Rect, scale: float) -> None:
        """
        Take the column's space and build every font for it, then stack the
        cards again. Fonts are made here and only read while drawing, so no
        frame ever pays to build one

        :param rect: the column the cards fill, from the menu layout
        :param scale: interface scale for this window size, 1.0 at the
            reference window
        """
        self._rect = pg.Rect(rect)
        self._scale = scale
        self._title_font = get_font(self._s(11, 9), bold=True)
        self._summary_font = get_font(self._s(11, 9))
        self._name_font = get_font(self._s(14, 11), bold=True)
        self._avatar_font = get_font(self._s(19, 14), bold=True)
        self._meta_font = get_font(self._s(11, 9))
        self._time_font = get_mono_font(self._s(10, 8))
        self._badge_font = get_font(self._s(13, 10), bold=True)
        self._link_font = get_font(self._s(11, 9), bold=True)
        self._date_font = get_mono_font(self._s(10, 8), bold=True)
        self._news_title_font = get_font(self._s(17, 15), bold=True)
        self._news_body_font = get_font(self._s(15, 13))
        self._headline_font = get_font(self._s(13, 12))
        self._fonts_ready = True
        self._body_lines_cache = {}
        self._compute_layout()

    def _news_body_lines(self, item: dict[str, Any], max_w: int) -> list[tuple[int, str]]:
        """
        The wrapped lines of one item's body, kept from the last time they
        were worked out. Wrapping measures text, so a card that stays open for
        hundreds of frames does that work once rather than every frame

        :param item: the news item whose body is being drawn
        :param max_w: room available for the text, in pixels
        :returns: each line with the pixel indent it is drawn at
        """
        key = (item.get("date", ""), item.get("title", ""), item["body"], max_w)
        cached = self._body_lines_cache.get(key)
        if cached is None:
            cached = self._build_news_body_lines(item, max_w)
            self._body_lines_cache[key] = cached
        return cached

    def _build_news_body_lines(self, item: dict[str, Any],
                               max_w: int) -> list[tuple[int, str]]:
        """
        Wrap one item's body for real. News bodies are written as plain
        paragraphs and lines starting with a dash; a dashed line is drawn as a
        bullet whose continuation lines hang under the text rather than under
        the bullet, and blank lines are dropped

        :param item: the news item whose body is being wrapped
        :param max_w: room available for the text, in pixels
        :returns: each line with the pixel indent it is drawn at
        """
        lines = []
        for raw in item["body"].split("\n"):
            raw = raw.strip()
            if not raw:
                continue
            if raw.startswith("- "):
                indent = self._news_body_font.size(NEWS_BULLET)[0]
                wrapped = wrap_words(raw[2:], self._news_body_font, max_w - indent)
                if wrapped:
                    lines.append((0, NEWS_BULLET + wrapped[0]))
                    lines.extend((indent, cont) for cont in wrapped[1:])
            else:
                lines.extend((0, line)
                             for line in wrap_words(raw, self._news_body_font, max_w))
        return lines

    def _news_content_w(self) -> int:
        """
        How wide news text may be: the card less its side padding and the
        gutter kept free down the right for the inner scrollbar

        :returns: the text width in pixels
        """
        return self._rect.width - 2 * self._s(PAD_X, 10) - self._s(NEWS_GUTTER, 10)

    def _news_body_block_h(self, item: dict[str, Any]) -> int:
        """
        How tall an open item's body is, which is what the news accordion adds
        under that item's header when the player opens it

        :param item: the news item being measured
        :returns: the block's height in pixels, padding included
        """
        lines = self._news_body_lines(item, self._news_content_w())
        line_h = self._news_body_font.get_height() + self._s(NEWS_LINE_GAP, 2)
        return self._s(NEWS_TITLE_GAP, 4) + len(lines) * line_h + self._s(NEWS_PAD_Y, 8)

    def _news_layout_rows(self) -> tuple[list[tuple[str, dict[str, Any], int, int]], int]:
        """
        Lay the feed out inside the News card: one dated header row per item,
        plus a body block under whichever single item is open. Positions are
        measured from the top of the news area rather than the window, so the
        inner scroll can shift the whole lot without laying it out again

        :returns: the rows to draw, each a kind, its item, its y and its
            height, together with the full height they come to
        """
        rows = []
        y = self._s(NEWS_PAD_Y, 8)
        row_h = self._s(HEADLINE_ROW_H, 20)
        for item in self._news_items:
            rows.append(("header", item, y, row_h))
            y += row_h
            if _item_key(item) == self._open_news_item:
                block_h = self._news_body_block_h(item)
                rows.append(("body", item, y, block_h))
                y += block_h
        return rows, y

    def _card_height(self, key: str) -> int:
        """
        How tall one card wants to be. The profile row is a fixed strip that
        never expands, and every other card is only its header until it is the
        open one, which is what makes the column read as an accordion

        :param key: which card is being measured, profile, recent or news
        :returns: the card's natural height in pixels
        """
        if key == "profile":
            return self._s(PROFILE_H, 56)
        header_h = self._s(HEADER_H, 34)
        if self._open != key:
            return header_h
        if key == "recent":
            rows = len(self._recent_groups)
            return header_h + rows * self._s(BODY_ROW_H, 32) + self._s(FOOTER_H, 24)
        _, content_h = self._news_layout_rows()
        return header_h + content_h

    def _compute_layout(self) -> None:
        """
        Stack the cards top to bottom and settle their heights. An open News
        card is the one that flexes: it takes only what the other cards leave,
        so their headers stay on screen and a long feed scrolls inside its own
        card instead of pushing them off the bottom
        """
        if not self._fonts_ready or self._rect.width <= 0:
            self._cards = []
            self._content_h = 0
            return
        gap = self._s(CARD_GAP, 8)
        keys = self._visible_card_keys()
        heights = {key: self._card_height(key) for key in keys}
        if self._open == "news" and "news" in heights:
            others = sum(h for k, h in heights.items() if k != "news")
            available = self._rect.height - others - gap * max(len(keys) - 1, 0)
            header_h = self._s(HEADER_H, 34)
            heights["news"] = max(header_h, min(heights["news"], available))
        cards = []
        y = 0
        for key in keys:
            h = heights[key]
            cards.append((key, y, h))
            y += h + gap
        self._cards = cards
        self._content_h = max(y - gap, 0)

    def draw(self, window: pg.Surface, now_ms: int) -> None:
        """
        Paint the column, clipped to its own space and shifted by how far it
        is scrolled, with cards that fall outside skipped. Both flings are
        stepped here too -- the column's own and the news box's -- so a flick
        keeps coasting for as long as the menu is drawing

        :param window: surface drawn to, the window or a transition scratch
            surface
        :param now_ms: pygame tick count in milliseconds since pygame init
        """
        if self._rect.width <= 0:
            return
        self.scroll.tick()
        self.news_box.tick()
        max_offset = max(0, self._content_h - self._rect.height)
        self._scroll_px = max(0.0, min(self._scroll_px, max_offset))
        prev_clip = window.get_clip()
        window.set_clip(self._rect)
        try:
            mouse = pg.mouse.get_pos()
            for key, y, h in self._cards:
                top = self._rect.y + y - self._scroll_px
                if top + h < self._rect.y or top > self._rect.bottom:
                    continue
                rect = pg.Rect(self._rect.x, round(top), self._rect.width, h)
                self._draw_card(window, key, rect, mouse)
        finally:
            window.set_clip(prev_clip)
        self.scroll.draw_thumb(window)

    def _draw_card(self, window: pg.Surface, key: str, rect: pg.Rect,
                   mouse: tuple[int, int]) -> None:
        """
        Draw whichever card this key names, in the space the layout gave it

        :param window: surface drawn to, the window or a scratch surface
        :param key: which card to draw, profile, recent or news
        :param rect: where it goes, already offset by the column's scroll
        :param mouse: cursor position in window pixels, for hover states
        """
        if key == "profile":
            self._draw_profile_card(window, rect, mouse)
        elif key == "recent":
            self._draw_recent_card(window, rect, mouse)
        else:
            self._draw_news_card(window, rect, mouse)

    def _draw_panel(self, window: pg.Surface, rect: pg.Rect, hovered: bool) -> None:
        """
        Draw the cut-cornered panel every card sits on, lit while the cursor
        is over it so the whole card reads as pressable

        :param window: surface drawn to, the window or a scratch surface
        :param rect: the panel's place in the window
        :param hovered: True to draw the lit fill
        """
        fill = Colors.surface_hover if hovered else Colors.surface
        window.blit(cut_rect_surface(rect.size, self._s(CARD_CUT, 5), fill,
                                     border=Colors.border, border_width=1,
                                     corners=("tr", "bl")), rect.topleft)

    def _draw_profile_card(self, window: pg.Surface, rect: pg.Rect,
                           mouse: tuple[int, int]) -> None:
        """
        Draw the card at the top of the column: this player's avatar, their
        name -- or an invitation to set one -- their flag, and a chevron
        pointing on. It is a way into the Profile page, not an accordion, so
        it never expands in place. The avatar colors come from the shared
        name-seeded helper, so this tile matches the Profile page's

        :param window: surface drawn to, the window or a scratch surface
        :param rect: where the card goes, already offset by the scroll
        :param mouse: cursor position in window pixels, for hover states
        """
        hovered = rect.collidepoint(mouse)
        self._draw_panel(window, rect, hovered)
        pad = self._s(PAD_X, 10)
        av_size = self._s(AVATAR_SIZE, 30)
        av_rect = pg.Rect(rect.x + pad, rect.centery - av_size // 2, av_size, av_size)
        nickname = env.get_nickname()
        self._profile_avatar_seed, self._profile_avatar_palette = seeded_avatar_palette(
            nickname, self._profile_avatar_seed, self._profile_avatar_palette)
        draw_avatar(window, av_rect, nickname, self._avatar_font,
                    *self._profile_avatar_palette)
        x = av_rect.right + self._s(12, 8)
        nickname = env.get_nickname() or "Set nickname"
        color = Colors.text if env.get_nickname() else Colors.text_muted
        name_surf = render_text(self._name_font, nickname, color)
        flag = self._flag_surface(env.get_country())
        cy = rect.centery - self._s(8, 4)
        window.blit(name_surf, (x, cy - name_surf.get_height() // 2))
        if flag is not None:
            window.blit(flag, (x + name_surf.get_width() + self._s(6, 4),
                               cy - flag.get_height() // 2))
        meta = render_text(self._meta_font, "View profile", Colors.text_dim)
        window.blit(meta, (x, rect.centery + self._s(8, 4) - meta.get_height() // 2))
        chevron = self._right_chevron(Colors.text_dim if not hovered else Colors.text)
        window.blit(chevron, (rect.right - pad - chevron.get_width(),
                              rect.centery - chevron.get_height() // 2))

    def _right_chevron(self, color: str) -> pg.Surface:
        """
        Build the chevron that points onward, the mark rows that lead
        somewhere wear instead of the up-down one an accordion header shows

        :param color: chevron color, a palette hex string
        :returns: the chevron turned to point right
        """
        up = chevron_surface(self._s(CHEVRON_SIZE, 9), color, up=True)
        return pg.transform.rotate(up, -90)

    def _flag_surface(self, code: str) -> pg.Surface | None:
        """
        Fetch the little flag drawn beside the player's name at this window's
        size, from the one shared place flags come from

        :param code: two-letter country code, empty or unknown allowed
        :returns: the shared flag picture, or None when there is no flag to
            show
        """
        return flag_surface(code, self._s(FLAG_SIZE, 11))

    def _draw_header(self, window: pg.Surface, rect: pg.Rect, title: str, summary: str,
                     expanded: bool, hovered: bool) -> None:
        """
        Draw the header the two expandable cards share: its title, a chevron
        showing which way it is facing, and -- only while collapsed, and only
        when there is room for it -- a one-line summary of what is inside,
        shortened to fit

        :param window: surface drawn to, the window or a scratch surface
        :param rect: the header's place in the window
        :param title: card name, drawn upper case
        :param summary: the collapsed one-liner, empty for none
        :param expanded: True when this card is the open one
        :param hovered: True while the cursor is over the header
        """
        self._draw_panel(window, rect, hovered)
        pad = self._s(PAD_X, 10)
        title_surf = render_text(self._title_font, title.upper(), Colors.text_dim)
        window.blit(title_surf, (rect.x + pad, rect.centery - title_surf.get_height() // 2))
        chevron = chevron_surface(self._s(CHEVRON_SIZE, 9), Colors.text_dim, up=expanded)
        cx = rect.right - pad - chevron.get_width()
        window.blit(chevron, (cx, rect.centery - chevron.get_height() // 2))
        if summary and not expanded:
            avail = cx - self._s(8, 6) - (rect.x + pad + title_surf.get_width() + self._s(10, 6))
            if avail > 10:
                text = _elide(self._summary_font, summary, avail)
                summ_surf = render_text(self._summary_font, text, Colors.text_muted)
                window.blit(summ_surf, (cx - self._s(8, 6) - summ_surf.get_width(),
                                        rect.centery - summ_surf.get_height() // 2))

    def _recent_summary(self) -> str:
        """
        The one-liner on the collapsed Recent matches header: how the newest
        saved match went for this player and who it was against

        :returns: the summary line, empty when no games have been saved
        """
        if not self._recent_groups:
            return ""
        g = self._recent_groups[0]
        letter = _BADGE_LETTER[g.result]
        return f"{letter} · {_opponent(g, env.get_nickname())}"

    def _draw_recent_card(self, window: pg.Surface, rect: pg.Rect,
                          mouse: tuple[int, int]) -> None:
        """
        Draw the recent matches card: its header alone while collapsed, and
        when open a row for each of the last few saved games with a link to
        the full History beneath them

        :param window: surface drawn to, the window or a scratch surface
        :param rect: where the card goes, already offset by the scroll
        :param mouse: cursor position in window pixels, for hover states
        """
        header = pg.Rect(rect.x, rect.y, rect.width, self._s(HEADER_H, 34))
        expanded = self._open == "recent"
        self._draw_header(window, header, "Recent matches", self._recent_summary(),
                          expanded, header.collidepoint(mouse))
        if not expanded:
            return
        pad = self._s(PAD_X, 10)
        row_h = self._s(BODY_ROW_H, 32)
        y = header.bottom
        nickname = env.get_nickname()
        for group in self._recent_groups:
            row = pg.Rect(rect.x, y, rect.width, row_h)
            self._draw_match_row(window, row, group, nickname, pad, mouse)
            y += row_h
        footer = pg.Rect(rect.x, y, rect.width, self._s(FOOTER_H, 24))
        self._draw_view_all(window, footer, pad, mouse)

    def _draw_match_row(self, window: pg.Surface, row: pg.Rect, group: MatchGroup,
                        nickname: str, pad: int, mouse: tuple[int, int]) -> None:
        """
        Draw one saved match: a win, loss or draw badge coloured for how it
        went from this player's side, the opponent's name shortened to fit,
        and how long ago it was played. The result is the one read out of the
        saved game, never guessed from anything else

        :param window: surface drawn to, the window or a scratch surface
        :param row: the row's place in the window
        :param group: the saved match this row stands for
        :param nickname: the name this player is currently going by, which
            decides which side of the game is theirs
        :param pad: side padding in pixels, already scaled
        :param mouse: cursor position in window pixels, for hover states
        """
        if row.collidepoint(mouse):
            window.blit(cut_rect_surface(row.size, self._s(6, 4), Colors.surface_hover,
                                         corners=("tr", "bl")), row.topleft)
        badge_d = self._s(22, 16)
        badge = pg.Rect(row.x + pad, row.centery - badge_d // 2, badge_d, badge_d)
        color = _BADGE_COLOR[group.result]
        window.blit(cut_rect_surface(badge.size, self._s(4, 3), color + "26",
                                     border=color + "5c", border_width=1,
                                     corners=("tr", "bl")), badge.topleft)
        letter = render_text(self._badge_font, _BADGE_LETTER[group.result], color)
        window.blit(letter, (badge.centerx - letter.get_width() // 2,
                             badge.centery - letter.get_height() // 2))
        time_surf = render_text(self._time_font, group.time_ago, Colors.text_muted)
        name_right = row.right - pad - time_surf.get_width() - self._s(8, 6)
        name_x = badge.right + self._s(10, 6)
        name_text = _elide(self._name_font, _opponent(group, nickname), name_right - name_x)
        name_surf = render_text(self._name_font, name_text, Colors.text)
        window.blit(name_surf, (name_x, row.centery - name_surf.get_height() // 2))
        window.blit(time_surf, (row.right - pad - time_surf.get_width(),
                                row.centery - time_surf.get_height() // 2))

    def _draw_view_all(self, window: pg.Surface, footer: pg.Rect, pad: int,
                       mouse: tuple[int, int]) -> None:
        """
        Draw the link under the match rows that opens the full History, the
        way out of the three games this card has room for

        :param window: surface drawn to, the window or a scratch surface
        :param footer: the strip under the last match row
        :param pad: side padding in pixels, already scaled
        :param mouse: cursor position in window pixels, for hover states
        """
        hovered = footer.collidepoint(mouse)
        color = Colors.text if hovered else Colors.text_dim
        text = render_text(self._link_font, "View all", color)
        x = footer.x + pad
        window.blit(text, (x, footer.centery - text.get_height() // 2))
        chevron = self._right_chevron(color)
        window.blit(chevron, (x + text.get_width() + self._s(6, 4),
                              footer.centery - chevron.get_height() // 2))

    def _news_summary(self) -> str:
        """
        The newest headline, shown on the collapsed News header when there is
        nothing unread to announce instead

        :returns: the newest item's title, empty when the feed has no items
        """
        if not self._news_items:
            return ""
        return self._news_items[0]["title"]

    def _draw_news_card(self, window: pg.Surface, rect: pg.Rect,
                        mouse: tuple[int, int]) -> None:
        """
        Draw the News card: its header carrying either a count of unread items
        or the newest headline, and, once open, the feed itself in whatever
        room the card was given. Collapsed, it also forgets its item hit boxes
        so nothing off screen can be clicked

        :param window: surface drawn to, the window or a scratch surface
        :param rect: where the card goes, already offset by the scroll
        :param mouse: cursor position in window pixels, for hover states
        """
        header = pg.Rect(rect.x, rect.y, rect.width, self._s(HEADER_H, 34))
        expanded = self._open == "news"
        unread = 0 if expanded else self._unread_count()
        summary = "" if unread else self._news_summary()
        self._draw_header(window, header, "News", summary, expanded, header.collidepoint(mouse))
        if unread:
            self._draw_news_badge(window, header, unread)
        if not expanded:
            self._news_item_hits = []
            return
        inner = pg.Rect(rect.x, header.bottom, rect.width, max(rect.bottom - header.bottom, 0))
        self._draw_news_items(window, inner, mouse)

    def _draw_news_badge(self, window: pg.Surface, header: pg.Rect, count: int) -> None:
        """
        Draw how many news items the player has not read yet, tucked in beside
        the header's chevron so it reads as part of the header rather than as
        another control

        :param window: surface drawn to, the window or a scratch surface
        :param header: the News header this badge sits on
        :param count: how many items are newer than the last one seen
        """
        pad = self._s(PAD_X, 10)
        chevron_w = chevron_surface(self._s(CHEVRON_SIZE, 9), Colors.text_dim, up=False).get_width()
        label = render_text(self._badge_font, str(count), Colors.amber_hi)
        badge_w = label.get_width() + self._s(12, 8)
        badge_h = label.get_height() + self._s(4, 3)
        right = header.right - pad - chevron_w - self._s(8, 6)
        badge = pg.Rect(right - badge_w, header.centery - badge_h // 2, badge_w, badge_h)
        window.blit(cut_rect_surface(badge.size, self._s(4, 3), Colors.amber + "26",
                                     border=Colors.amber + "5c", border_width=1,
                                     corners=("tr", "bl")), badge.topleft)
        window.blit(label, (badge.centerx - label.get_width() // 2,
                            badge.centery - label.get_height() // 2))

    def _draw_news_items(self, window: pg.Surface, inner: pg.Rect,
                         mouse: tuple[int, int]) -> None:
        """
        Draw the feed inside the open card: every item's dated header and the
        body of whichever one is open, clipped to the card and shifted by the
        inner scroll. The inner box is handed its rect and content height
        here, and the header hit boxes are rebuilt as they are drawn, so a
        click always matches what is actually on screen

        :param window: surface drawn to, the window or a scratch surface
        :param inner: the area under the News header the feed lives in
        :param mouse: cursor position in window pixels, for hover states
        """
        self.news_box._rect = pg.Rect(inner)
        rows, content_h = self._news_layout_rows()
        self.news_box._content_h = content_h
        offset = max(0.0, min(self.news_box.scroll_offset, max(0, content_h - inner.height)))
        self.news_box._scroll_px = offset
        self._news_item_hits = []
        outer_clip = window.get_clip()
        window.set_clip(inner.clip(pg.Rect(outer_clip)) if outer_clip else inner)
        try:
            for kind, item, y_rel, h in rows:
                rect = pg.Rect(inner.x, round(inner.y + y_rel - offset), inner.width, h)
                on_screen = rect.bottom >= inner.y and rect.top <= inner.bottom
                if kind == "header":
                    if on_screen:
                        self._draw_news_item_header(window, rect, item, mouse)
                    self._news_item_hits.append((pg.Rect(rect), _item_key(item)))
                elif on_screen:
                    self._draw_news_item_body(window, rect, item)
        finally:
            window.set_clip(outer_clip)
        self.news_box.scroll.draw_thumb(window)

    def _draw_news_item_header(self, window: pg.Surface, row: pg.Rect,
                               item: dict[str, Any], mouse: tuple[int, int]) -> None:
        """
        Draw one item's row: its short date stamp, its headline shortened to
        whatever room is left, and a chevron. The open item is picked out in
        brighter colors, so which one is being read is obvious at a glance

        :param window: surface drawn to, the window or a scratch surface
        :param row: the row's place in the window
        :param item: the news item this row stands for
        :param mouse: cursor position in window pixels, for hover states
        """
        opened = _item_key(item) == self._open_news_item
        if row.collidepoint(mouse):
            window.blit(cut_rect_surface(row.size, self._s(6, 4), Colors.surface_hover,
                                         corners=("tr", "bl")), row.topleft)
        date_color = Colors.amber_hi if opened else Colors.text_dim
        date_surf = render_text(self._date_font, format_news_date(item["date"]), date_color)
        window.blit(date_surf, (row.x + self._s(PAD_X, 10),
                                row.centery - date_surf.get_height() // 2))
        chevron = chevron_surface(self._s(CHEVRON_SIZE, 9), Colors.text_dim, up=opened)
        cx = row.right - self._s(PAD_X, 10) - self._s(NEWS_GUTTER, 10) - chevron.get_width()
        window.blit(chevron, (cx, row.centery - chevron.get_height() // 2))
        title_x = row.x + self._s(PAD_X, 10) + date_surf.get_width() + self._s(10, 6)
        title_w = cx - self._s(6, 4) - title_x
        if title_w > 10:
            title_text = _elide(self._headline_font, item["title"], title_w)
            color = Colors.text if opened else Colors.text_dim
            title_surf = render_text(self._headline_font, title_text, color)
            window.blit(title_surf, (title_x, row.centery - title_surf.get_height() // 2))

    def _draw_news_item_body(self, window: pg.Surface, rect: pg.Rect,
                             item: dict[str, Any]) -> None:
        """
        Draw the open item's body in full, line by line, bullet lines hanging
        under their own text. Nothing is cut short here -- a body longer than
        the card scrolls inside it instead

        :param window: surface drawn to, the window or a scratch surface
        :param rect: the block under this item's header, already offset by the
            inner scroll
        :param item: the news item being read
        """
        pad = self._s(PAD_X, 10)
        y = rect.y + self._s(NEWS_TITLE_GAP, 4)
        for indent, line in self._news_body_lines(item, self._news_content_w()):
            line_surf = render_text(self._news_body_font, line, Colors.text_muted)
            window.blit(line_surf, (rect.x + pad + indent, y))
            y += line_surf.get_height() + self._s(NEWS_LINE_GAP, 2)

    def _last_seen(self) -> str:
        """
        How far through the news the player has already read, from their
        stored settings. A stored value that will not parse counts as having
        read nothing, so a hand-edited settings file cannot hide the cue

        :returns: the last-seen date, empty when nothing has been seen
        """
        value = env.get_news_last_seen()
        return value if _valid_news_date(value) else ""

    def _unread_count(self) -> int:
        """
        How many items are newer than what the player has read, which is the
        number the News header wears

        :returns: the unread count, zero when everything has been seen
        """
        last_seen = self._last_seen()
        return sum(1 for date in self._valid_news_dates if date > last_seen)

    def _newest_news_date(self) -> str:
        """
        The newest date the feed carries, which is what gets stored as read
        once the player opens the card

        :returns: the newest usable date, empty when the feed has none
        """
        return max(self._valid_news_dates, default="")

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a click in the column to the card under it, allowing for how far
        the column is scrolled. A click that lands in the column but misses
        every card is still taken, so it cannot fall through to the Play view
        behind

        :param pos: click position in window pixels
        :returns: True when the click landed anywhere in the column
        """
        if not self._rect.collidepoint(pos):
            return False
        for key, y, h in self._cards:
            top = self._rect.y + y - self._scroll_px
            card_rect = pg.Rect(self._rect.x, round(top), self._rect.width, h)
            if not card_rect.collidepoint(pos):
                continue
            return self._handle_card_click(key, card_rect, pos)
        return True

    def _handle_card_click(self, key: str, card_rect: pg.Rect,
                           pos: tuple[int, int]) -> bool:
        """
        Act on a click inside one card. The profile card leads to the Profile
        page, a click on any header opens or closes that card, and a click
        below an open header goes to that card's own rows

        :param key: which card was hit, profile, recent or news
        :param card_rect: the card's place in the window
        :param pos: click position in window pixels
        :returns: True always, since the click belonged to this card
        """
        if key == "profile":
            self.app.menu.goto_view("profile")
            return True
        header = pg.Rect(card_rect.x, card_rect.y, card_rect.width, self._s(HEADER_H, 34))
        if header.collidepoint(pos):
            self._toggle(key)
            return True
        if key == "recent" and self._open == "recent":
            self._handle_recent_body_click(card_rect, header, pos)
        elif key == "news" and self._open == "news":
            self._handle_news_item_click(pos)
        return True

    def _handle_news_item_click(self, pos: tuple[int, int]) -> bool:
        """
        Open or close the news item whose header was clicked, matched against
        the hit boxes the last draw laid down. It is also the path a tap takes
        when the inner box grabbed the press as a possible scroll first

        :param pos: click position in window pixels
        :returns: True when an item was opened or closed
        """
        for rect, item_key in self._news_item_hits:
            if rect.collidepoint(pos):
                self._toggle_news_item(item_key)
                return True
        return False

    def _toggle_news_item(self, item_key: tuple[str, str]) -> None:
        """
        Open one news item and close whichever was open, or close this one if
        it was already open -- inside the card the items are their own
        single-open accordion. The card sound stands in for the generic
        interface click, so the toggle sounds like a toggle

        :param item_key: the date and title pair identifying the item clicked
        """
        self._open_news_item = None if self._open_news_item == item_key else item_key
        self.app.input_router.suppress_click_sound()
        self.app.sound_manager.play_card_toggle()
        self._compute_layout()

    def _handle_recent_body_click(self, card_rect: pg.Rect, header: pg.Rect,
                                  pos: tuple[int, int]) -> None:
        """
        Act on a click below the Recent matches header: a match row opens that
        saved game for review, and the link at the foot goes to the full
        History

        :param card_rect: the card's place in the window
        :param header: its header strip, which the rows start beneath
        :param pos: click position in window pixels
        """
        row_h = self._s(BODY_ROW_H, 32)
        y = header.bottom
        for group in self._recent_groups:
            row = pg.Rect(card_rect.x, y, card_rect.width, row_h)
            if row.collidepoint(pos):
                self.app._open_pgn_review(group.games[0].path)
                return
            y += row_h
        footer = pg.Rect(card_rect.x, y, card_rect.width, self._s(FOOTER_H, 24))
        if footer.collidepoint(pos):
            self.app.menu.goto_history()

    def _toggle(self, key: str) -> None:
        """
        Open one card and close the other, or close this one if it was already
        open -- the strict accordion the whole column runs on. Opening News
        also counts as reading it

        :param key: the card being opened or closed, recent or news
        """
        self._open = None if self._open == key else key
        self.app.input_router.suppress_click_sound()
        self.app.sound_manager.play_card_toggle()
        if self._open == "news":
            self._on_news_expanded()
        self._compute_layout()

    def _on_news_expanded(self) -> None:
        """
        Settle what opening the News card means: the unread cue clears because
        the newest date is stored as read -- and only ever forwards, so a feed
        that rolls back cannot un-read anything -- the newest item is opened
        for reading, and the inner scroll starts at the top
        """
        newest = self._newest_news_date()
        if newest > self._last_seen():
            env.set_news_last_seen(newest)
        self._open_news_item = _item_key(self._news_items[0]) if self._news_items else None
        self.news_box.reset()
