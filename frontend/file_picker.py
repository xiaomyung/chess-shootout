import os

import pygame as pg

from frontend.colors import Colors
from frontend.widgets import _draw_button


SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18


class FilePicker:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.visible = False
        self.title = "Load PGN"
        self.entries = []
        self.on_select = None
        self.on_cancel = None
        self.scroll_offset = 0
        self.padding = 14
        self.row_gap = 4
        self.title_font = pg.font.SysFont("Arial", 22, bold=True)
        self.row_font = pg.font.SysFont("monospace", 14)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self._row_rects = []
        self._cancel_rect = pg.Rect(0, 0, 0, 0)
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._max_visible = 0
        self._last_scroll_activity_ms = 0

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self.title_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 14), 14), bold=True,
        )
        self.row_font = pg.font.SysFont(
            "monospace", max(int(rect.height / 22), 12),
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 24), 12), bold=True,
        )

    def show(self, directory, pattern, on_select, on_cancel=None):
        self.entries = self._scan(directory, pattern)
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.scroll_offset = 0
        self.visible = True

    def hide(self):
        self.visible = False
        self.entries = []
        self.on_select = None
        self.on_cancel = None
        self._row_rects = []
        self._cancel_rect = pg.Rect(0, 0, 0, 0)

    def is_visible(self):
        return self.visible

    def draw(self):
        if not self.visible:
            return

        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)

        title_surf = self.title_font.render(self.title, True, Colors.white)
        self.window.blit(
            title_surf,
            (self.rect.centerx - title_surf.get_width() / 2,
             self.rect.y + self.padding),
        )

        list_top = self.rect.y + self.padding * 2 + title_surf.get_height()
        btn_h = max(int(self.rect.height * 0.1), 28)
        list_bottom = self.rect.bottom - self.padding * 2 - btn_h
        list_height = max(list_bottom - list_top, 0)
        row_h = self.row_font.get_linesize() + self.row_gap
        max_visible = max(int(list_height // row_h), 1)
        self._max_visible = max_visible
        self._list_rect = pg.Rect(
            self.rect.x + self.padding,
            list_top,
            self.rect.width - 2 * self.padding,
            max_visible * row_h,
        )
        self._row_rects = []

        max_offset = max(0, len(self.entries) - max_visible)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

        if not self.entries:
            empty_surf = self.row_font.render(
                "No saved games found", True, Colors.button_border,
            )
            self.window.blit(
                empty_surf,
                (self.rect.centerx - empty_surf.get_width() / 2,
                 list_top + self.padding),
            )
        else:
            visible = self.entries[
                self.scroll_offset: self.scroll_offset + max_visible
            ]
            for i, (name, path) in enumerate(visible):
                row_rect = pg.Rect(
                    self.rect.x + self.padding,
                    list_top + i * row_h,
                    self.rect.width - 2 * self.padding,
                    row_h - self.row_gap,
                )
                self._row_rects.append((row_rect, path))
                hovered = row_rect.collidepoint(pg.mouse.get_pos())
                if hovered:
                    pg.draw.rect(self.window, Colors.button_hover, row_rect,
                                 border_radius=3)
                surf = self.row_font.render(name, True, Colors.white)
                self.window.blit(
                    surf,
                    (row_rect.x + 6,
                     row_rect.centery - surf.get_height() / 2),
                )

        self._draw_scroll_indicator()

        cancel_rect = pg.Rect(
            self.rect.x + self.padding,
            self.rect.bottom - self.padding - btn_h,
            self.rect.width - 2 * self.padding,
            btn_h,
        )
        self._cancel_rect = cancel_rect
        _draw_button(self.window, cancel_rect, "Cancel", self.button_font)

    def _draw_scroll_indicator(self):
        total = len(self.entries)
        max_offset = max(0, total - self._max_visible)
        if max_offset == 0:
            return
        if pg.time.get_ticks() - self._last_scroll_activity_ms > SCROLL_FADE_MS:
            return
        track_y = self._list_rect.y
        track_h = self._list_rect.height
        if track_h <= 0:
            return
        thumb_h = max(SCROLL_THUMB_MIN_HEIGHT,
                      int(track_h * self._max_visible / total))
        thumb_h = min(thumb_h, track_h)
        thumb_y = track_y + int(
            (track_h - thumb_h) * (self.scroll_offset / max_offset)
        )
        thumb_x = self._list_rect.right - SCROLL_THUMB_RIGHT_OFFSET - SCROLL_THUMB_WIDTH
        thumb_rect = pg.Rect(thumb_x, thumb_y, SCROLL_THUMB_WIDTH, thumb_h)
        pg.draw.rect(self.window, Colors.button_hover, thumb_rect,
                     border_radius=SCROLL_THUMB_WIDTH // 2)

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._cancel_rect.collidepoint(pos):
            cb = self.on_cancel
            self.hide()
            if cb is not None:
                cb()
            return True
        for row_rect, path in self._row_rects:
            if row_rect.collidepoint(pos):
                cb = self.on_select
                self.hide()
                if cb is not None:
                    cb(path)
                return True
        if self.rect.collidepoint(pos):
            return True
        return False

    def handle_scroll(self, pos, dy):
        if not self.visible:
            return False
        if not self._list_rect.collidepoint(pos):
            return False
        max_offset = max(0, len(self.entries) - self._max_visible)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset - dy, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True

    @staticmethod
    def _scan(directory, pattern):
        if not os.path.isdir(directory):
            return []
        matches = []
        suffix = pattern.lstrip("*")
        for name in os.listdir(directory):
            if not name.endswith(suffix):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            matches.append((name, path, os.path.getmtime(path)))
        matches.sort(key=lambda t: t[2], reverse=True)
        return [(name, path) for name, path, _ in matches]
