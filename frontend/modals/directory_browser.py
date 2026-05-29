import os

import pygame as pg

import paths
from frontend.visual.colors import Colors
from frontend.visual.fonts import get_font
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import draw_button, draw_scroll_thumb, fit_text_to_rect, wrap_path

ROW_PAD_Y = 8
_WRITE_TEST_NAME = ".chess_write_test"


class DirectoryBrowser:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.visible = False
        self.title = "Choose data folder"
        self.current = os.path.expanduser("~")
        self.entries = []
        self.show_hidden = False
        self.creating = False
        self.on_select = None
        self.on_error = None
        self.scroll_offset = 0
        self.padding = 14
        self.new_folder_input = TextInput(window, max_chars=64, placeholder="new folder name")
        self.title_font = get_font(22, bold=True)
        self.path_label_font = get_font(11)
        self.path_font = get_font(15)
        self.row_font = get_font(14)
        self.button_font = get_font(14, bold=True)
        self._row_rects = []
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._max_visible = 0
        self._last_scroll_activity_ms = 0
        self._hidden_rect = pg.Rect(0, 0, 0, 0)
        self._newfolder_rect = pg.Rect(0, 0, 0, 0)
        self._select_rect = pg.Rect(0, 0, 0, 0)
        self._cancel_rect = pg.Rect(0, 0, 0, 0)
        self._create_rect = pg.Rect(0, 0, 0, 0)
        self._create_cancel_rect = pg.Rect(0, 0, 0, 0)
        self._input_rect = pg.Rect(0, 0, 0, 0)

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self.title_font = get_font(max(int(rect.height / 18), 16), bold=True)
        self.path_label_font = get_font(max(int(rect.height / 42), 10))
        self.path_font = get_font(max(int(rect.height / 28), 14))
        self.row_font = get_font(max(int(rect.height / 28), 13))
        self.button_font = get_font(max(int(rect.height / 32), 12), bold=True)

    def show(self, start_dir, on_select, on_error=None):
        start = start_dir if start_dir and os.path.isdir(start_dir) else os.path.expanduser("~")
        self.current = os.path.abspath(start)
        self.on_select = on_select
        self.on_error = on_error
        self.show_hidden = False
        self.creating = False
        self.new_folder_input.text = ""
        self._reload()
        self.visible = True

    def hide(self):
        self.visible = False
        self.creating = False

    def is_visible(self):
        return self.visible

    def _reload(self):
        self.scroll_offset = 0
        names = []
        try:
            for name in sorted(os.listdir(self.current), key=str.lower):
                full = os.path.join(self.current, name)
                if not os.path.isdir(full):
                    continue
                if not self.show_hidden and name.startswith("."):
                    continue
                names.append(name)
        except OSError:
            names = []
        entries = []
        parent = os.path.dirname(self.current)
        if parent and parent != self.current:
            entries.append(("..", parent))
        for name in names:
            entries.append((name, os.path.join(self.current, name)))
        self.entries = entries

    def _enter(self, path):
        if os.path.isdir(path):
            self.current = os.path.abspath(path)
            self._reload()

    def _writable(self, directory):
        if not os.path.isdir(directory) or not os.access(directory, os.W_OK):
            return False
        test = os.path.join(directory, _WRITE_TEST_NAME)
        try:
            with open(test, "w"):
                pass
            os.remove(test)
        except OSError:
            return False
        return True

    def _select_current(self):
        if not self._writable(self.current):
            if self.on_error is not None:
                self.on_error("Folder not writable")
            return
        cb = self.on_select
        path = os.path.normpath(os.path.abspath(self.current))
        self.hide()
        if cb is not None:
            cb(path)

    def _create_folder(self):
        name = self.new_folder_input.text.strip()
        if not name:
            return
        try:
            os.makedirs(os.path.join(self.current, name), exist_ok=False)
        except OSError:
            if self.on_error is not None:
                self.on_error("Could not create folder")
            return
        self.creating = False
        self.new_folder_input.text = ""
        self._reload()

    def draw(self):
        if not self.visible:
            return
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)
        pad = self.padding
        inner_x = self.rect.x + pad
        inner_w = self.rect.width - 2 * pad

        title_surf = self.title_font.render(self.title, True, Colors.white)
        self.window.blit(
            title_surf, (self.rect.centerx - title_surf.get_width() / 2, self.rect.y + pad),
        )
        y = self.rect.y + pad + title_surf.get_height() + 6

        label_surf = self.path_label_font.render(
            "Games will be saved to:", True, Colors.button_border,
        )
        self.window.blit(label_surf, (inner_x, y))
        y += label_surf.get_height() + 4
        dest = os.path.join(self.current, paths.GAMES_SUBDIR)
        for line in wrap_path(dest, self.path_font, inner_w):
            line_surf = self.path_font.render(line, True, Colors.white)
            self.window.blit(line_surf, (inner_x, y))
            y += self.path_font.get_height() + 2
        y += 8

        btn_h = max(int(self.rect.height * 0.08), 30)
        bar_y = self.rect.bottom - pad - btn_h
        self._layout_bottom_bar(inner_x, inner_w, bar_y, btn_h)

        self._list_rect = pg.Rect(inner_x, y, inner_w, max(bar_y - pad - y, 1))
        row_h = self.row_font.get_height() + ROW_PAD_Y
        self._max_visible = max(self._list_rect.height // row_h, 1)
        max_offset = max(0, len(self.entries) - self._max_visible)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
        self._draw_list(row_h)
        self._draw_bottom_bar()

    def _layout_bottom_bar(self, inner_x, inner_w, bar_y, btn_h):
        gap = 8
        if self.creating:
            bw = max(int(inner_w * 0.18), 80)
            self._create_rect = pg.Rect(inner_x + inner_w - 2 * bw - gap, bar_y, bw, btn_h)
            self._create_cancel_rect = pg.Rect(inner_x + inner_w - bw, bar_y, bw, btn_h)
            self._input_rect = pg.Rect(inner_x, bar_y, inner_w - 2 * bw - 2 * gap, btn_h)
        else:
            bw = (inner_w - gap * 3) // 4
            self._hidden_rect = pg.Rect(inner_x, bar_y, bw, btn_h)
            self._newfolder_rect = pg.Rect(inner_x + (bw + gap), bar_y, bw, btn_h)
            self._select_rect = pg.Rect(inner_x + 2 * (bw + gap), bar_y, bw, btn_h)
            self._cancel_rect = pg.Rect(
                inner_x + 3 * (bw + gap), bar_y, inner_w - 3 * (bw + gap), btn_h,
            )

    def _draw_bottom_bar(self):
        if self.creating:
            self.new_folder_input.set_rect(self._input_rect)
            self.new_folder_input.draw()
            draw_button(self.window, self._create_rect, "Create", self.button_font)
            draw_button(self.window, self._create_cancel_rect, "Cancel", self.button_font)
        else:
            draw_button(
                self.window, self._hidden_rect, "Show hidden", self.button_font,
                force_pressed=self.show_hidden,
            )
            draw_button(self.window, self._newfolder_rect, "New Folder", self.button_font)
            draw_button(self.window, self._select_rect, "Select this folder", self.button_font)
            draw_button(self.window, self._cancel_rect, "Cancel", self.button_font)

    def _draw_list(self, row_h):
        self._row_rects = []
        visible = self.entries[self.scroll_offset:self.scroll_offset + self._max_visible]
        prev_clip = self.window.get_clip()
        self.window.set_clip(self._list_rect)
        try:
            mouse_pos = pg.mouse.get_pos()
            for i, (name, path) in enumerate(visible):
                row_rect = pg.Rect(
                    self._list_rect.x, self._list_rect.y + i * row_h,
                    self._list_rect.width, row_h,
                )
                self._row_rects.append((row_rect, path))
                if row_rect.collidepoint(mouse_pos):
                    pg.draw.rect(self.window, Colors.button_hover, row_rect)
                label = name if name == ".." else name + "/"
                text = fit_text_to_rect(
                    self.row_font.render(label, True, Colors.white),
                    pg.Rect(0, 0, row_rect.width - 12, row_rect.height),
                )
                self.window.blit(
                    text, (row_rect.x + 6, row_rect.centery - text.get_height() / 2),
                )
        finally:
            self.window.set_clip(prev_clip)
        max_offset = max(0, len(self.entries) - self._max_visible)
        if max_offset:
            draw_scroll_thumb(
                self.window, self._list_rect, len(self.entries), self._max_visible,
                self.scroll_offset / max_offset, self._last_scroll_activity_ms,
            )

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self.creating:
            if self._input_rect.collidepoint(pos):
                self.new_folder_input.handle_click(pos)
                return True
            if self._create_rect.collidepoint(pos):
                self._create_folder()
                return True
            if self._create_cancel_rect.collidepoint(pos):
                self.creating = False
                self.new_folder_input.text = ""
                return True
            return True
        if self._hidden_rect.collidepoint(pos):
            self.show_hidden = not self.show_hidden
            self._reload()
            return True
        if self._newfolder_rect.collidepoint(pos):
            self.creating = True
            self.new_folder_input.text = ""
            self.new_folder_input.focused = True
            return True
        if self._select_rect.collidepoint(pos):
            self._select_current()
            return True
        if self._cancel_rect.collidepoint(pos):
            self.hide()
            return True
        for row_rect, path in self._row_rects:
            if row_rect.collidepoint(pos):
                self._enter(path)
                return True
        return True

    def handle_scroll(self, pos, dy):
        if not self.visible or not self._list_rect.collidepoint(pos):
            return False
        max_offset = max(0, len(self.entries) - self._max_visible)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset - dy, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True

    def handle_key(self, event):
        if not self.visible or not self.creating:
            return False
        if event.key == pg.K_RETURN:
            self._create_folder()
            return True
        return self.new_folder_input.handle_key(event)
