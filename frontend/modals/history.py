import time

import pygame as pg

from backend.pieces import Piece, PieceColor, PieceType
from frontend.pgn.load import (
    NO_CLOCK_LABEL, format_relative_time, group_by_csmatchid, scan_pgn_summaries,
    time_category,
)
from frontend.visual.colors import Colors
from frontend.visual.draw import (
    blit_centered, infinity_surface, rounded_rect_surface, supersample,
)
from frontend.visual.fonts import get_display_font, get_font, get_mono_font
from frontend.visual.widgets import build_shell, draw_scroll_thumb


FILTER_OPTIONS = [("All", "all"), ("Online", "online"), ("Bot", "bot"), ("Local", "local")]
FILTER_TYPE = {"online": "Online", "bot": "Bot", "local": "Local"}
SCROLL_STEP = 56
SCROLLBAR_GUTTER = 14

CARD_RADIUS = 12
CARD_INNER_PAD = 3
CARD_TEXT_INSET = 16
CARD_TEXT_VPAD = 12
CARD_BADGE_SIZE = 44
CARD_BADGE_RADIUS = 11
GAME_BADGE_SIZE = 22
GAME_BADGE_RADIUS = 6
STAT_CARD_RADIUS = 11
STAT_CARD_INSET = 14
STAT_CARD_TOP = 12
CHIP_PAD_X = 26
CHIP_GAP = 6
CHIP_RADIUS = 15
TYPE_PILL_PAD_X = 16
TYPE_PILL_PAD_Y = 5

_BADGE_TEXT = {"win": "W", "loss": "L", "draw": "½"}
_BADGE_COLOR = {"win": Colors.result_win, "loss": Colors.result_loss,
                "draw": Colors.result_neutral}


def _game_outcome(game, nickname):
    if nickname == game.black:
        won, lost = "0-1", "1-0"
    else:
        won, lost = "1-0", "0-1"
    if game.result_code == won:
        return "win"
    if game.result_code == lost:
        return "loss"
    return "draw"


def _game_ko(game, nickname):
    if nickname == game.black:
        return game.black_captures, game.white_captures
    return game.white_captures, game.black_captures


class MatchGroup:

    def __init__(self, match_id, games, nickname):
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
    def result(self):
        wins = self.outcomes.count("win")
        losses = self.outcomes.count("loss")
        if wins > losses:
            return "win"
        if losses > wins:
            return "loss"
        return "draw"


def build_match_groups(summaries, nickname):
    return [MatchGroup(mid, games, nickname)
            for mid, games in group_by_csmatchid(summaries)]


class HistoryView:

    def __init__(self, window, on_open, on_back):
        self.window = window
        self.on_open = on_open
        self.on_back = on_back
        self.rect = pg.Rect(0, 0, 0, 0)
        self.visible = False
        self.nickname = None
        self.filter = "all"
        self.expanded_match_id = None
        self.scroll_offset = 0
        self._groups = []
        self._menu_rect = pg.Rect(0, 0, 0, 0)
        self._filter_rects = {}
        self._row_hits = []
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._content_h = 0
        self._last_scroll_activity_ms = 0
        self._pawn_orig = None
        self._pawn_cache = {}
        self._arrow_cache = {}
        self._rescale(1.0)

    def _pawn(self, color, size):
        if self._pawn_orig is None:
            self._pawn_orig = {
                c: pg.image.load(Piece(PieceType.PAWN, c).img_path).convert_alpha()
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

    def _arrow(self, size, color, pointing):
        key = (size, color, pointing)
        if key not in self._arrow_cache:
            def render(surf, k):
                w, h = surf.get_size()
                if pointing == "down":
                    pts = [(w * 0.18, h * 0.34), (w * 0.82, h * 0.34), (w * 0.5, h * 0.7)]
                elif pointing == "left":
                    pts = [(w * 0.66, h * 0.16), (w * 0.66, h * 0.84), (w * 0.26, h * 0.5)]
                else:
                    pts = [(w * 0.34, h * 0.16), (w * 0.34, h * 0.84), (w * 0.74, h * 0.5)]
                pg.draw.polygon(surf, pg.Color(color), pts)
            self._arrow_cache[key] = supersample((size, size), render)
        return self._arrow_cache[key]

    def _rescale(self, scale):
        def sz(base, minimum):
            return max(int(base * scale), minimum)
        self._title_font = get_display_font(sz(26, 16))
        self._menu_font = get_font(sz(13, 11), bold=True)
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

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        if rect.width > 0:
            self._rescale(max(min(rect.width / 860, 1.0), 0.72))

    def show(self, directory, pattern, on_open=None, nickname=None):
        if on_open is not None:
            self.on_open = on_open
        self.nickname = nickname
        self._groups = build_match_groups(
            scan_pgn_summaries(directory, pattern), nickname)
        now = time.time()
        for group in self._groups:
            group.time_ago = format_relative_time(group.sort_key, now)
        self.filter = "all"
        self.expanded_match_id = None
        self.scroll_offset = 0
        self.visible = True

    def hide(self):
        self.visible = False
        self._groups = []
        self._row_hits = []

    def is_visible(self):
        return self.visible

    def _visible_groups(self):
        if self.filter == "all":
            return self._groups
        want = FILTER_TYPE[self.filter]
        return [g for g in self._groups if g.type == want]

    def _stats(self):
        groups = self._visible_groups()
        return (sum(1 for g in groups if g.result == "win"),
                sum(1 for g in groups if g.result == "loss"),
                sum(1 for g in groups if g.result == "draw"))

    def draw(self):
        if not self.visible or self.rect.width <= 0:
            return
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

    def _draw_header(self, x, y, w, h):
        cy = y + h // 2
        self._menu_rect = pg.Rect(x, cy - 16, 92, 32)
        hovered = self._menu_rect.collidepoint(pg.mouse.get_pos())
        bg = Colors.button_hover if hovered else Colors.surface_inset
        fg = Colors.white if hovered else Colors.text_dim
        self.window.blit(rounded_rect_surface(self._menu_rect.size, 8, bg,
                                              border=Colors.button_border, border_width=1),
                         self._menu_rect.topleft)
        arrow = self._arrow(max(int(self._menu_font.get_height() * 0.8), 9), fg, "left")
        menu_surf = self._menu_font.render("Menu", True, fg)
        gap = 6
        start_x = self._menu_rect.centerx - (arrow.get_width() + gap + menu_surf.get_width()) // 2
        self.window.blit(arrow, (start_x, cy - arrow.get_height() // 2))
        self.window.blit(menu_surf, (start_x + arrow.get_width() + gap,
                                     cy - menu_surf.get_height() // 2))

        title = self._title_font.render("HISTORY", True, Colors.white)
        self.window.blit(title, (self._menu_rect.right + 16, cy - title.get_height() // 2))

        right = x + w
        right = self._draw_filters(right, cy)
        self._draw_count_chip(right - 12, cy)

    def _draw_filters(self, right, cy):
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
                bg, border, color = Colors.button_pressed, Colors.accent, Colors.white
            elif hovered:
                bg, border, color = Colors.button_hover, Colors.button_border, Colors.white
            else:
                bg, border, color = Colors.surface, Colors.button_border, Colors.text_dim
            self.window.blit(rounded_rect_surface(rect.size, CHIP_RADIUS, bg,
                                                  border=border, border_width=1), rect.topleft)
            surf = self._filter_font.render(label, True, color)
            self.window.blit(surf, (rect.centerx - surf.get_width() // 2,
                                    rect.centery - surf.get_height() // 2))
            self._filter_rects[key] = rect
            cx += cw + CHIP_GAP
        return left_edge

    def _draw_count_chip(self, right, cy):
        text = f"{len(self._visible_groups())} games"
        surf = self._count_font.render(text, True, Colors.text_dim)
        w = surf.get_width() + 14
        h = surf.get_height() + 6
        rect = pg.Rect(right - w, cy - h // 2, w, h)
        self.window.blit(rounded_rect_surface(rect.size, 4, Colors.button_hover), rect.topleft)
        self.window.blit(surf, (rect.x + 7, rect.centery - surf.get_height() // 2))

    def _draw_stats(self, x, y, w, h):
        wins, losses, draws = self._stats()
        gap = 10
        card_w = (w - 2 * gap) / 3
        cards = ((wins, "WINS", Colors.result_win), (losses, "LOSSES", Colors.result_loss),
                 (draws, "DRAWS", Colors.white))
        for i, (value, label, color) in enumerate(cards):
            rect = pg.Rect(int(x + i * (card_w + gap)), y, int(card_w), h)
            self.window.blit(rounded_rect_surface(rect.size, STAT_CARD_RADIUS, Colors.surface,
                                                  border=Colors.button_border, border_width=1),
                             rect.topleft)
            num = self._stat_num_font.render(str(value), True, color)
            self.window.blit(num, (rect.x + STAT_CARD_INSET, rect.y + STAT_CARD_TOP))
            lab = self._stat_label_font.render(label, True, Colors.text_mute)
            self.window.blit(lab, (rect.x + STAT_CARD_INSET,
                                   rect.y + STAT_CARD_TOP + num.get_height() + 3))

    def _draw_list(self):
        self._row_hits = []
        groups = self._visible_groups()
        if not groups:
            surf = self._greason_font.render("No games yet — go start a shootout.",
                                             True, Colors.text_mute)
            self.window.blit(surf, (self._list_rect.centerx - surf.get_width() // 2,
                                    self._list_rect.y + 40))
            self._content_h = 0
            return

        card_h = max(int(self._name_font.get_height() + self._sub_font.get_height() + 32), 64)
        game_h = max(int(self._greason_font.get_height() * 1.9), 34)
        gap = 9
        blocks = []
        for g in groups:
            expanded = self.expanded_match_id == g.match_id and len(g.games) > 1
            detail_h = len(g.games) * game_h if expanded else 0
            blocks.append((g, expanded, card_h + detail_h))

        self._content_h = sum(b[2] for b in blocks) + gap * len(blocks)
        max_offset = max(0, self._content_h - self._list_rect.height)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
        row_w = self._list_rect.width - (SCROLLBAR_GUTTER if max_offset > 0 else 0)

        prev_clip = self.window.get_clip()
        self.window.set_clip(self._list_rect)
        try:
            y = self._list_rect.y - self.scroll_offset
            for group, expanded, block_h in blocks:
                on_screen = (y + block_h >= self._list_rect.y
                             and y <= self._list_rect.bottom)
                card_rect = pg.Rect(self._list_rect.x, y, row_w, card_h)
                if on_screen:
                    self._draw_card(card_rect, group, block_h)
                if len(group.games) > 1:
                    self._row_hits.append((card_rect, ("toggle", group.match_id)))
                else:
                    self._row_hits.append((card_rect, ("open", group.games[0].path)))
                if expanded:
                    for i, game in enumerate(group.games):
                        row_rect = pg.Rect(self._list_rect.x, y + card_h + i * game_h,
                                           row_w, game_h)
                        if on_screen:
                            self._draw_game_row(row_rect, group, game, i)
                        self._row_hits.append((row_rect, ("open", game.path)))
                y += block_h + gap
        finally:
            self.window.set_clip(prev_clip)
        self._draw_scroll_indicator()

    def _draw_card(self, rect, group, block_h):
        inner_x = rect.x + CARD_INNER_PAD
        inner_w = rect.width - CARD_INNER_PAD
        expanded = block_h > rect.height
        hovered = rect.collidepoint(pg.mouse.get_pos())
        bg = Colors.button_hover if hovered else Colors.surface
        self.window.blit(rounded_rect_surface((rect.width, block_h), CARD_RADIUS,
                                              _BADGE_COLOR[group.result]), rect.topleft)
        if expanded:
            self.window.blit(
                rounded_rect_surface((inner_w, block_h), CARD_RADIUS, Colors.surface_inset,
                                     border=Colors.button_border, border_width=1),
                (inner_x, rect.y))
            self.window.blit(rounded_rect_surface((inner_w, rect.height), CARD_RADIUS, bg),
                             (inner_x, rect.y))
        else:
            self.window.blit(
                rounded_rect_surface((inner_w, rect.height), CARD_RADIUS, bg,
                                     border=Colors.button_border, border_width=1),
                (inner_x, rect.y))

        badge = pg.Rect(rect.x + CARD_TEXT_INSET, rect.centery - CARD_BADGE_SIZE // 2,
                        CARD_BADGE_SIZE, CARD_BADGE_SIZE)
        self._draw_badge(badge, group.result, self._badge_font, CARD_BADGE_RADIUS)

        text_x = badge.right + CARD_TEXT_INSET
        self._draw_matchup(text_x, rect.y + CARD_TEXT_VPAD, group)
        meta = (f"{group.category} · {len(group.games)} games" if len(group.games) > 1
                else f"{group.category} · {group.reason}")
        sub = self._sub_font.render(meta, True, Colors.text_mute)
        self.window.blit(sub, (text_x, rect.bottom - sub.get_height() - CARD_TEXT_VPAD))

        self._draw_card_right(rect, group)

    def _draw_badge(self, rect, result, font, radius):
        color = _BADGE_COLOR[result]
        if result == "draw":
            bg, border, ink = Colors.button_hover, Colors.button_border, Colors.text_dim
        else:
            bg, border, ink = color + "26", color + "5c", color
        self.window.blit(rounded_rect_surface(rect.size, radius, bg,
                                              border=border, border_width=1), rect.topleft)
        letter = font.render(_BADGE_TEXT[result], True, ink)
        blit_centered(self.window, letter, rect.center)

    def _draw_matchup(self, x, y, group):
        cy = y + self._name_font.get_height() // 2
        x = self._draw_player(x, cy, PieceColor.WHITE,
                              group.white, group.white == self.nickname)
        vs = self._vs_font.render("vs", True, Colors.text_mute)
        x += 2
        self.window.blit(vs, (x, cy - vs.get_height() // 2))
        x += vs.get_width() + 8
        self._draw_player(x, cy, PieceColor.BLACK,
                          group.black, group.black == self.nickname)

    def _draw_player(self, x, cy, color, name, is_me):
        pawn = self._pawn(color, int(self._name_font.get_height() * 1.25))
        self.window.blit(pawn, (x, cy - pawn.get_height() // 2))
        x += pawn.get_width() + 6
        nsurf = self._name_font.render(name, True,
                                       Colors.amber_hi if is_me else Colors.white)
        self.window.blit(nsurf, (x, cy - nsurf.get_height() // 2))
        return x + nsurf.get_width() + 8

    def _draw_card_right(self, rect, group):
        chev_cx = rect.right - 14
        self._draw_chevron(chev_cx, rect.centery, len(group.games) > 1,
                           self.expanded_match_id == group.match_id)

        when_right = chev_cx - 18
        series = self._series_font.render(f"{group.ko_you}-{group.ko_opp}", True, Colors.white)
        kolbl = self._kolbl_font.render("KO", True, Colors.text_mute)
        timesurf = self._time_font.render(group.time_ago, True, Colors.text_mute)
        line1_w = series.get_width() + 5 + kolbl.get_width()
        block_w = max(line1_w, timesurf.get_width())
        bx = when_right - block_w
        self.window.blit(series, (when_right - line1_w, rect.centery - series.get_height() - 1))
        self.window.blit(kolbl, (when_right - kolbl.get_width(),
                                 rect.centery - series.get_height() + 4))
        self.window.blit(timesurf, (when_right - timesurf.get_width(), rect.centery + 4))

        meta_right = bx - 18
        if group.time_control == NO_CLOCK_LABEL:
            tc = infinity_surface(max(int(self._tc_font.get_height() * 0.6), 8), Colors.white)
        else:
            tc = self._tc_font.render(group.time_control, True, Colors.white)
        self.window.blit(tc, (meta_right - tc.get_width(), rect.centery + 4))
        self._draw_type_pill(meta_right, rect.centery - 3, group.type)

    def _draw_type_pill(self, right, bottom, type_label):
        text = type_label.upper()
        online = type_label == "Online"
        color = Colors.amber_hi if online else Colors.text_dim
        bg = (Colors.amber + "1a") if online else Colors.surface_inset
        border = (Colors.amber + "57") if online else Colors.button_border
        surf = self._pill_font.render(text, True, color)
        w = surf.get_width() + TYPE_PILL_PAD_X
        h = surf.get_height() + TYPE_PILL_PAD_Y
        rect = pg.Rect(right - w, bottom - h, w, h)
        self.window.blit(rounded_rect_surface(rect.size, h // 2, bg,
                                              border=border, border_width=1), rect.topleft)
        self.window.blit(surf, (rect.centerx - surf.get_width() // 2,
                                rect.centery - surf.get_height() // 2))

    def _draw_chevron(self, x, cy, multi, expanded):
        size = max(int(self._name_font.get_height() * 0.8), 10)
        if multi and expanded:
            arrow = self._arrow(size, Colors.accent, "down")
        else:
            arrow = self._arrow(size, Colors.text_mute, "right")
        self.window.blit(arrow, (x - arrow.get_width() // 2, cy - arrow.get_height() // 2))

    def _draw_game_row(self, rect, group, game, index):
        if rect.collidepoint(pg.mouse.get_pos()):
            hov = pg.Rect(rect.x + 5, rect.y + 1, rect.width - 12, rect.height - 2)
            self.window.blit(rounded_rect_surface(hov.size, 6, Colors.button_hover),
                             hov.topleft)
        pg.draw.line(self.window, Colors.button_border,
                     (rect.x + 12, rect.y), (rect.right - 12, rect.y), 1)
        gnum = self._gnum_font.render(f"GAME {index + 1}", True, Colors.text_mute)
        self.window.blit(gnum, (rect.x + 20, rect.centery - gnum.get_height() // 2))
        outcome = _game_outcome(game, self.nickname)
        badge = pg.Rect(rect.x + 96, rect.centery - GAME_BADGE_SIZE // 2,
                        GAME_BADGE_SIZE, GAME_BADGE_SIZE)
        self._draw_badge(badge, outcome, self._gbadge_font, GAME_BADGE_RADIUS)
        reason = self._greason_font.render(game.reason, True, Colors.text_dim)
        self.window.blit(reason, (badge.right + 14, rect.centery - reason.get_height() // 2))
        you, opp = _game_ko(game, self.nickname)
        ko = self._gko_font.render(f"{you}-{opp} KO", True, Colors.text_mute)
        shell_h = max(int(ko.get_height() * 0.9), 9)
        shell = build_shell(max(int(shell_h * 0.5), 5), shell_h)
        self.window.blit(shell, (rect.right - ko.get_width() - shell.get_width() - 36,
                                 rect.centery - shell.get_height() // 2))
        self.window.blit(ko, (rect.right - ko.get_width() - 28,
                              rect.centery - ko.get_height() // 2))

    def _draw_scroll_indicator(self):
        max_offset = max(0, self._content_h - self._list_rect.height)
        if max_offset == 0:
            return
        draw_scroll_thumb(self.window, self._list_rect, self._content_h,
                          self._list_rect.height, self.scroll_offset / max_offset,
                          self._last_scroll_activity_ms)

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._menu_rect.collidepoint(pos):
            self.on_back()
            return True
        for key, rect in self._filter_rects.items():
            if rect.collidepoint(pos):
                self.filter = key
                self.expanded_match_id = None
                self.scroll_offset = 0
                return True
        if self._list_rect.collidepoint(pos):
            for row_rect, action in self._row_hits:
                if not row_rect.collidepoint(pos):
                    continue
                kind, value = action
                if kind == "toggle":
                    self.expanded_match_id = None if self.expanded_match_id == value else value
                elif self.on_open is not None:
                    self.on_open(value)
                return True
        return self.rect.collidepoint(pos)

    def handle_scroll(self, pos, dy):
        if not self.visible or not self._list_rect.collidepoint(pos):
            return False
        max_offset = max(0, self._content_h - self._list_rect.height)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset - dy * SCROLL_STEP, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True
