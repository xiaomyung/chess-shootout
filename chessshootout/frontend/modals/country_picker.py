import pygame as pg

from chessshootout.infra import countries
from chessshootout.frontend.modals.base import BaseModal, MODAL_RAIL
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import rounded_rect_surface
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import draw_button, draw_scroll_thumb


ROW_VPAD = 16
SCROLLBAR_GUTTER = 16
ROW_FLAG_INSET = 10
ROW_FLAG_GAP = 12
ROW_CODE_INSET = 10


class CountryPicker(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.visible = False
        self.on_pick = None
        self.current = ""
        self.scroll_offset = 0
        self.search = TextInput(window, max_chars=32, placeholder="Search countries",
                                bg=Colors.bg, radius=7)
        self.search.padding = 11
        self._filtered = list(countries.COUNTRIES)
        self._row_rects = []
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._search_rect = pg.Rect(0, 0, 0, 0)
        self._cancel_rect = pg.Rect(0, 0, 0, 0)
        self._max_visible = 0
        self._row_h = 1
        self._last_scroll_activity_ms = 0
        self._flag_cache = {}
        self._on_rect_changed()

    def _on_rect_changed(self):
        h = max(self.rect.height, 1)
        self.padding = max(int(self.rect.width * 0.032), 12)
        self.title_font = get_display_font(max(int(h * 0.044), 16))
        self.row_font = get_font(max(int(h * 0.027), 13), bold=True)
        self.code_font = get_mono_font(max(int(h * 0.022), 10))
        self.button_font = get_font(max(int(h * 0.028), 12), bold=True)
        self.search_font = get_font(max(int(h * 0.028), 12))

    def show(self, current_code, on_pick):
        self.current = countries.normalize(current_code)
        self.on_pick = on_pick
        self.search.text = ""
        self.search.focused = True
        self.scroll_offset = 0
        self._apply_filter()
        self.visible = True

    def hide(self):
        self.visible = False
        self.search.focused = False

    def is_visible(self):
        return self.visible

    def _apply_filter(self):
        raw = self.search.text.strip()
        self.scroll_offset = 0
        if not raw:
            self._filtered = list(countries.COUNTRIES)
            return
        folded = countries.fold(raw)
        upper = raw.upper()
        self._filtered = [(code, name) for code, name in countries.COUNTRIES
                          if folded in countries.fold(name) or upper in code]

    def _entries(self):
        rows = []
        if not self.search.text.strip():
            rows.append(("", "No flag"))
        rows.extend(self._filtered)
        return rows

    def _flag_for(self, code, size):
        char = countries.flag_emoji(code)
        if not char:
            return None
        key = (char, size)
        if key not in self._flag_cache:
            self._flag_cache[key] = emoji_surface(char, size)
        return self._flag_cache[key]

    def draw(self):
        if not self.visible or self.rect.width <= 0:
            return
        self.draw_shell()
        r = self.rect
        pad = self.padding
        top = r.y + MODAL_RAIL + int(pad * 0.55)
        title = self.title_font.render("PICK A COUNTRY", True, Colors.text)
        self.window.blit(title, (r.x + pad, top))
        sy = top + title.get_height() + int(pad * 0.5)
        field_h = max(self.search_font.get_height() + 16, 32)
        self._search_rect = pg.Rect(r.x + pad, sy, r.width - 2 * pad, field_h)
        self.search.set_rect(self._search_rect)
        self.search.font = self.search_font
        self.search.draw()
        btn_h = max(self.button_font.get_height() + 14, 32)
        btn_y = r.bottom - pad - btn_h
        btn_w = max(int(r.width * 0.34), 96)
        self._cancel_rect = pg.Rect(r.right - pad - btn_w, btn_y, btn_w, btn_h)
        draw_button(self.window, self._cancel_rect, "Cancel", self.button_font)
        list_top = self._search_rect.bottom + int(pad * 0.5)
        list_bottom = btn_y - int(pad * 0.5)
        self._list_rect = pg.Rect(r.x + pad, list_top, r.width - 2 * pad,
                                  max(list_bottom - list_top, 1))
        self._row_h = self.row_font.get_height() + ROW_VPAD
        self._max_visible = max(self._list_rect.height // self._row_h, 1)
        entries = self._entries()
        max_offset = max(0, len(entries) - self._max_visible)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
        self._draw_list(entries)

    def _draw_list(self, entries):
        self._row_rects = []
        max_offset = max(0, len(entries) - self._max_visible)
        gutter = SCROLLBAR_GUTTER if max_offset else 0
        content_w = self._list_rect.width - gutter
        prev = self.window.get_clip()
        self.window.set_clip(self._list_rect)
        try:
            mouse = pg.mouse.get_pos()
            visible = entries[self.scroll_offset:self.scroll_offset + self._max_visible]
            for i, (code, label) in enumerate(visible):
                row_rect = pg.Rect(self._list_rect.x, self._list_rect.y + i * self._row_h,
                                   content_w, self._row_h)
                self._draw_row(row_rect, code, label, mouse)
                self._row_rects.append((row_rect, code))
        finally:
            self.window.set_clip(prev)
        if max_offset:
            draw_scroll_thumb(self.window, self._list_rect, len(entries), self._max_visible,
                              self.scroll_offset / max_offset, self._last_scroll_activity_ms)

    def _draw_row(self, row_rect, code, label, mouse):
        selected = code == self.current
        if selected:
            self.window.blit(
                rounded_rect_surface(row_rect.size, 8, Colors.surface_active,
                                     border=Colors.accent, border_width=1),
                row_rect.topleft)
        elif row_rect.collidepoint(mouse):
            pg.draw.rect(self.window, Colors.surface_hover, row_rect, border_radius=8)
        x = row_rect.x + ROW_FLAG_INSET
        flag_size = max(int(self._row_h * 0.5), 12)
        flag = self._flag_for(code, flag_size)
        if flag is not None:
            self.window.blit(flag, (x, row_rect.centery - flag.get_height() // 2))
        x += flag_size + ROW_FLAG_GAP
        name_color = Colors.accent if selected else Colors.text
        name_surf = self.row_font.render(label, True, name_color)
        self.window.blit(name_surf, (x, row_rect.centery - name_surf.get_height() // 2))
        if code:
            code_surf = self.code_font.render(code, True, Colors.text_muted)
            self.window.blit(code_surf, (row_rect.right - ROW_CODE_INSET - code_surf.get_width(),
                                         row_rect.centery - code_surf.get_height() // 2))

    def _pick(self, code):
        cb = self.on_pick
        self.hide()
        if cb is not None:
            cb(code)

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._search_rect.collidepoint(pos):
            self.search.handle_click(pos)
            return True
        if self._cancel_rect.collidepoint(pos):
            self.hide()
            return True
        for row_rect, code in self._row_rects:
            if row_rect.collidepoint(pos):
                self._pick(code)
                return True
        return True

    def handle_scroll(self, pos, dy):
        if not self.visible or not self._list_rect.collidepoint(pos):
            return False
        max_offset = max(0, len(self._entries()) - self._max_visible)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset - dy, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True

    def handle_key(self, event):
        if not self.visible:
            return False
        consumed = self.search.handle_key(event)
        if consumed:
            self._apply_filter()
        return consumed
