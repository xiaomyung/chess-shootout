import time

import pygame as pg

from chessshootout import paths
from chessshootout.infra import countries, env
from chessshootout.domain.pgn.load import format_relative_time, scan_pgn_summaries
from chessshootout.frontend.panels.history_view import build_match_groups
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import chevron_surface, cut_rect_surface
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_font, get_mono_font
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.widgets import avatar_palette, draw_avatar, wrap_words
from chessshootout.online.news import format_news_date


PGN_PATTERN = "*.pgn"
RECENT_MATCHES_LIMIT = 3
NEWS_BODY_MAX_LINES = 4

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


def _elide(font, text, max_w):
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text + "…"


def _opponent(group, nickname):
    if nickname and nickname == group.white:
        return group.black
    if nickname and nickname == group.black:
        return group.white
    return group.black


class CardStack(ScrollHost):

    def __init__(self, app):
        self.app = app
        self.window = app.window
        self._rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._recent_groups = []
        self._news_items = []
        self._open = None
        self._blocks = []
        self._content_h = 0
        self._scroll_px = 0.0
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self._rect, self._content_h),
            wheel_step_px=BODY_ROW_H,
        )
        self._flag_cache = {}
        self._fonts_ready = False

    def is_visible(self):
        return True

    def refresh(self):
        nickname = env.get_nickname()
        groups = build_match_groups(
            scan_pgn_summaries(str(paths.get_games_dir()), PGN_PATTERN), nickname)
        now = time.time()
        for group in groups:
            group.time_ago = format_relative_time(group.sort_key, now)
        self._recent_groups = groups[:RECENT_MATCHES_LIMIT]
        self._news_items = self.app.news_client.items()
        if self._open not in self._visible_card_keys():
            self._open = None
        self._compute_layout()

    def _visible_card_keys(self):
        keys = ["profile"]
        if self._recent_groups:
            keys.append("recent")
        if self._news_items:
            keys.append("news")
        return keys

    def _s(self, value, floor=1):
        return max(int(value * self._scale), floor)

    def set_rect(self, rect, scale):
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
        self._news_title_font = get_font(self._s(13, 11), bold=True)
        self._news_body_font = get_font(self._s(11, 9))
        self._headline_font = get_font(self._s(11, 9))
        self._fonts_ready = True
        self._compute_layout()

    def _news_body_lines(self, item, max_w):
        return wrap_words(item["body"], self._news_body_font, max_w, NEWS_BODY_MAX_LINES)

    def _block_height(self, key):
        if key == "profile":
            return self._s(PROFILE_H, 56)
        header_h = self._s(HEADER_H, 34)
        if self._open != key:
            return header_h
        if key == "recent":
            rows = len(self._recent_groups)
            return header_h + rows * self._s(BODY_ROW_H, 32) + self._s(FOOTER_H, 24)
        newest, *older = self._news_items
        return header_h + self._news_expanded_extra_height(newest, older)

    def _news_expanded_extra_height(self, newest, older):
        gap = self._s(NEWS_PAD_Y, 8)
        title_gap = self._s(NEWS_TITLE_GAP, 4)
        line_gap = self._s(NEWS_LINE_GAP, 2)
        max_w = self._rect.width - 2 * self._s(PAD_X, 10)
        lines = self._news_body_lines(newest, max_w)
        body_h = len(lines) * (self._news_body_font.get_height() + line_gap)
        return (gap + self._news_title_font.get_height() + title_gap + body_h
                + gap + len(older) * self._s(HEADLINE_ROW_H, 20))

    def _compute_layout(self):
        if not self._fonts_ready or self._rect.width <= 0:
            self._blocks = []
            self._content_h = 0
            return
        blocks = []
        y = 0
        for key in self._visible_card_keys():
            h = self._block_height(key)
            blocks.append((key, y, h))
            y += h + self._s(CARD_GAP, 8)
        self._blocks = blocks
        self._content_h = max(y - self._s(CARD_GAP, 8), 0)

    def draw(self, window, now_ms):
        if self._rect.width <= 0:
            return
        self.scroll.tick()
        max_offset = max(0, self._content_h - self._rect.height)
        self._scroll_px = max(0.0, min(self._scroll_px, max_offset))
        prev_clip = window.get_clip()
        window.set_clip(self._rect)
        try:
            mouse = pg.mouse.get_pos()
            for key, y, h in self._blocks:
                top = self._rect.y + y - self._scroll_px
                if top + h < self._rect.y or top > self._rect.bottom:
                    continue
                rect = pg.Rect(self._rect.x, round(top), self._rect.width, h)
                self._draw_card(window, key, rect, mouse)
        finally:
            window.set_clip(prev_clip)
        self.scroll.draw_thumb(window)

    def _draw_card(self, window, key, rect, mouse):
        if key == "profile":
            self._draw_profile_card(window, rect, mouse)
        elif key == "recent":
            self._draw_recent_card(window, rect, mouse)
        else:
            self._draw_news_card(window, rect, mouse)

    def _draw_panel(self, window, rect, hovered):
        fill = Colors.surface_hover if hovered else Colors.surface
        window.blit(cut_rect_surface(rect.size, self._s(CARD_CUT, 5), fill,
                                     border=Colors.border, border_width=1,
                                     corners=("tr", "bl")), rect.topleft)

    def _draw_profile_card(self, window, rect, mouse):
        hovered = rect.collidepoint(mouse)
        self._draw_panel(window, rect, hovered)
        pad = self._s(PAD_X, 10)
        av_size = self._s(AVATAR_SIZE, 30)
        av_rect = pg.Rect(rect.x + pad, rect.centery - av_size // 2, av_size, av_size)
        draw_avatar(window, av_rect, env.get_nickname(), self._avatar_font, *avatar_palette())
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

    def _right_chevron(self, color):
        up = chevron_surface(self._s(CHEVRON_SIZE, 9), color, up=True)
        return pg.transform.rotate(up, -90)

    def _flag_surface(self, code):
        char = countries.flag_emoji(code)
        if not char:
            return None
        size = self._s(FLAG_SIZE, 11)
        key = (char, size)
        if key not in self._flag_cache:
            self._flag_cache[key] = emoji_surface(char, size)
        return self._flag_cache[key]

    def _draw_header(self, window, rect, title, summary, expanded, hovered):
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

    def _recent_summary(self):
        if not self._recent_groups:
            return ""
        g = self._recent_groups[0]
        letter = _BADGE_LETTER[g.result]
        return f"{letter} · {_opponent(g, env.get_nickname())}"

    def _draw_recent_card(self, window, rect, mouse):
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

    def _draw_match_row(self, window, row, group, nickname, pad, mouse):
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

    def _draw_view_all(self, window, footer, pad, mouse):
        hovered = footer.collidepoint(mouse)
        color = Colors.text if hovered else Colors.text_dim
        text = render_text(self._link_font, "View all", color)
        x = footer.x + pad
        window.blit(text, (x, footer.centery - text.get_height() // 2))
        chevron = self._right_chevron(color)
        window.blit(chevron, (x + text.get_width() + self._s(6, 4),
                              footer.centery - chevron.get_height() // 2))

    def _news_summary(self):
        if not self._news_items:
            return ""
        return self._news_items[0]["title"]

    def _draw_news_card(self, window, rect, mouse):
        header = pg.Rect(rect.x, rect.y, rect.width, self._s(HEADER_H, 34))
        expanded = self._open == "news"
        self._draw_header(window, header, "News", self._news_summary(),
                          expanded, header.collidepoint(mouse))
        if not expanded:
            return
        pad = self._s(PAD_X, 10)
        gap = self._s(NEWS_PAD_Y, 8)
        newest, *older = self._news_items
        y = header.bottom + gap
        date_surf = render_text(self._date_font, format_news_date(newest["date"]),
                                Colors.amber_hi)
        title_w = rect.width - 2 * pad - date_surf.get_width() - self._s(8, 6)
        title_text = _elide(self._news_title_font, newest["title"], title_w)
        title_surf = render_text(self._news_title_font, title_text, Colors.text)
        window.blit(title_surf, (rect.x + pad, y))
        window.blit(date_surf, (rect.right - pad - date_surf.get_width(), y))
        y += title_surf.get_height() + self._s(NEWS_TITLE_GAP, 4)
        max_w = rect.width - 2 * pad
        for line in self._news_body_lines(newest, max_w):
            line_surf = render_text(self._news_body_font, line, Colors.text_muted)
            window.blit(line_surf, (rect.x + pad, y))
            y += line_surf.get_height() + self._s(NEWS_LINE_GAP, 2)
        y += gap
        row_h = self._s(HEADLINE_ROW_H, 20)
        for item in older:
            self._draw_headline_row(window, pg.Rect(rect.x, y, rect.width, row_h), item, pad)
            y += row_h

    def _draw_headline_row(self, window, row, item, pad):
        date_surf = render_text(self._date_font, format_news_date(item["date"]), Colors.text_dim)
        window.blit(date_surf, (row.x + pad, row.centery - date_surf.get_height() // 2))
        title_x = row.x + pad + date_surf.get_width() + self._s(10, 6)
        title_w = row.right - pad - title_x
        title_text = _elide(self._headline_font, item["title"], title_w)
        title_surf = render_text(self._headline_font, title_text, Colors.text_dim)
        window.blit(title_surf, (title_x, row.centery - title_surf.get_height() // 2))

    def handle_click(self, pos):
        if not self._rect.collidepoint(pos):
            return False
        for key, y, h in self._blocks:
            top = self._rect.y + y - self._scroll_px
            block_rect = pg.Rect(self._rect.x, round(top), self._rect.width, h)
            if not block_rect.collidepoint(pos):
                continue
            return self._handle_block_click(key, block_rect, pos)
        return True

    def _handle_block_click(self, key, block_rect, pos):
        if key == "profile":
            self.app.menu.goto_view("profile")
            return True
        header = pg.Rect(block_rect.x, block_rect.y, block_rect.width, self._s(HEADER_H, 34))
        if header.collidepoint(pos):
            self._toggle(key)
            return True
        if key == "recent" and self._open == "recent":
            self._handle_recent_body_click(block_rect, header, pos)
        return True

    def _handle_recent_body_click(self, block_rect, header, pos):
        row_h = self._s(BODY_ROW_H, 32)
        y = header.bottom
        for group in self._recent_groups:
            row = pg.Rect(block_rect.x, y, block_rect.width, row_h)
            if row.collidepoint(pos):
                self.app._open_pgn_review(group.games[0].path)
                return
            y += row_h
        footer = pg.Rect(block_rect.x, y, block_rect.width, self._s(FOOTER_H, 24))
        if footer.collidepoint(pos):
            self.app.menu.goto_history()

    def _toggle(self, key):
        self._open = None if self._open == key else key
        self._compute_layout()
