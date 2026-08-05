import time
from datetime import datetime

import pygame as pg

from chessshootout import paths
from chessshootout.infra import env
from chessshootout.domain.pgn.load import format_relative_time
from chessshootout.frontend.menu.view import scale_floor, seeded_avatar_palette
from chessshootout.frontend.panels.history_view import PGN_PATTERN, load_match_groups
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


def _elide(font, text, max_w):
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


def _opponent(group, nickname):
    if nickname and nickname == group.white:
        return group.black
    if nickname and nickname == group.black:
        return group.white
    return group.black


def _valid_news_date(value):
    try:
        datetime.strptime(value, NEWS_DATE_FORMAT)
        return True
    except (ValueError, TypeError):
        return False


def _item_key(item):
    return (item.get("date", ""), item.get("title", ""))


class NewsBox(ScrollHost):

    def __init__(self, stack):
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

    def is_visible(self):
        return (self._stack.news_expanded() and self._stack._rect.width > 0
                and self._rect.height > 0)

    def tick(self):
        self.scroll.tick()

    def reset(self):
        self._scroll_px = 0.0
        self.scroll.cancel()

    def handle_click(self, pos):
        return self._stack._handle_news_item_click(pos)


class CardStack(ScrollHost):

    def __init__(self, app):
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

    def is_visible(self):
        return True

    def news_generation(self):
        return self._news_generation

    def refresh(self):
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

    def _news_item_keys(self):
        return {_item_key(item) for item in self._news_items}

    def news_expanded(self):
        return self._open == "news"

    def _visible_card_keys(self):
        keys = ["profile"]
        if self._recent_groups:
            keys.append("recent")
        if self._news_items:
            keys.append("news")
        return keys

    def _s(self, value, floor=1):
        return scale_floor(value, self._scale, floor)

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
        self._news_title_font = get_font(self._s(17, 15), bold=True)
        self._news_body_font = get_font(self._s(15, 13))
        self._headline_font = get_font(self._s(13, 12))
        self._fonts_ready = True
        self._body_lines_cache = {}
        self._compute_layout()

    def _news_body_lines(self, item, max_w):
        key = (item.get("date", ""), item.get("title", ""), item["body"], max_w)
        cached = self._body_lines_cache.get(key)
        if cached is None:
            cached = self._build_news_body_lines(item, max_w)
            self._body_lines_cache[key] = cached
        return cached

    def _build_news_body_lines(self, item, max_w):
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

    def _news_content_w(self):
        return self._rect.width - 2 * self._s(PAD_X, 10) - self._s(NEWS_GUTTER, 10)

    def _news_body_block_h(self, item):
        lines = self._news_body_lines(item, self._news_content_w())
        line_h = self._news_body_font.get_height() + self._s(NEWS_LINE_GAP, 2)
        return self._s(NEWS_TITLE_GAP, 4) + len(lines) * line_h + self._s(NEWS_PAD_Y, 8)

    def _news_layout_rows(self):
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

    def _card_height(self, key):
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

    def _compute_layout(self):
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

    def draw(self, window, now_ms):
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

    def _right_chevron(self, color):
        up = chevron_surface(self._s(CHEVRON_SIZE, 9), color, up=True)
        return pg.transform.rotate(up, -90)

    def _flag_surface(self, code):
        return flag_surface(code, self._s(FLAG_SIZE, 11))

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

    def _draw_news_badge(self, window, header, count):
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

    def _draw_news_items(self, window, inner, mouse):
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

    def _draw_news_item_header(self, window, row, item, mouse):
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

    def _draw_news_item_body(self, window, rect, item):
        pad = self._s(PAD_X, 10)
        y = rect.y + self._s(NEWS_TITLE_GAP, 4)
        for indent, line in self._news_body_lines(item, self._news_content_w()):
            line_surf = render_text(self._news_body_font, line, Colors.text_muted)
            window.blit(line_surf, (rect.x + pad + indent, y))
            y += line_surf.get_height() + self._s(NEWS_LINE_GAP, 2)

    def _last_seen(self):
        value = env.get_news_last_seen()
        return value if _valid_news_date(value) else ""

    def _unread_count(self):
        last_seen = self._last_seen()
        return sum(1 for date in self._valid_news_dates if date > last_seen)

    def _newest_news_date(self):
        return max(self._valid_news_dates, default="")

    def handle_click(self, pos):
        if not self._rect.collidepoint(pos):
            return False
        for key, y, h in self._cards:
            top = self._rect.y + y - self._scroll_px
            card_rect = pg.Rect(self._rect.x, round(top), self._rect.width, h)
            if not card_rect.collidepoint(pos):
                continue
            return self._handle_card_click(key, card_rect, pos)
        return True

    def _handle_card_click(self, key, card_rect, pos):
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

    def _handle_news_item_click(self, pos):
        for rect, item_key in self._news_item_hits:
            if rect.collidepoint(pos):
                self._toggle_news_item(item_key)
                return True
        return False

    def _toggle_news_item(self, item_key):
        self._open_news_item = None if self._open_news_item == item_key else item_key
        self.app.input_router.suppress_click_sound()
        self.app.sound_manager.play_card_toggle()
        self._compute_layout()

    def _handle_recent_body_click(self, card_rect, header, pos):
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

    def _toggle(self, key):
        self._open = None if self._open == key else key
        self.app.input_router.suppress_click_sound()
        self.app.sound_manager.play_card_toggle()
        if self._open == "news":
            self._on_news_expanded()
        self._compute_layout()

    def _on_news_expanded(self):
        newest = self._newest_news_date()
        if newest > self._last_seen():
            env.set_news_last_seen(newest)
        self._open_news_item = _item_key(self._news_items[0]) if self._news_items else None
        self.news_box.reset()
