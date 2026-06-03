import os

import pygame as pg

import paths
from frontend.modals.base import BaseModal, MODAL_RAIL
from frontend.visual.colors import Colors
from frontend.visual.draw import rounded_rect_surface
from frontend.visual.emoji import blit_emoji
from frontend.visual.fonts import get_display_font, get_font, get_mono_font
from frontend.visual.icons import draw_eye, draw_file, draw_folder, draw_folder_plus
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import draw_button, draw_scroll_thumb, fit_text_to_rect


ROW_ICON_BOX_W = 24
ROW_ICON_INSET = 6
ROW_TEXT_INSET = 8
ROW_META_INSET = 10


class DirectoryBrowser(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.visible = False
        self.current = os.path.expanduser("~")
        self.entries = []
        self.show_hidden = False
        self.creating = False
        self.on_select = None
        self.on_error = None
        self.scroll_offset = 0
        self.new_folder_input = TextInput(window, max_chars=64, placeholder="new folder")
        self._row_rects = []
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._max_visible = 0
        self._row_h = 1
        self._last_scroll_activity_ms = 0
        self._up_rect = pg.Rect(0, 0, 0, 0)
        self._newfolder_rect = pg.Rect(0, 0, 0, 0)
        self._hidden_rect = pg.Rect(0, 0, 0, 0)
        self._cancel_rect = pg.Rect(0, 0, 0, 0)
        self._choose_rect = pg.Rect(0, 0, 0, 0)
        self._input_rect = pg.Rect(0, 0, 0, 0)
        self._on_rect_changed()

    def _on_rect_changed(self):
        h = max(self.rect.height, 1)
        self.padding = max(int(self.rect.width * 0.032), 12)
        self.tool_side = max(int(h * 0.05), 26)
        self.title_font = get_display_font(max(int(h * 0.044), 16))
        self.crumb_font = get_mono_font(max(int(h * 0.024), 11))
        self.up_font = get_font(max(int(h * 0.024), 11), bold=True)
        self.row_font = get_font(max(int(h * 0.027), 13), bold=True)
        self.meta_font = get_mono_font(max(int(h * 0.021), 10))
        self.sel_label_font = get_font(max(int(h * 0.019), 10), bold=True)
        self.sel_val_font = get_mono_font(max(int(h * 0.03), 14))
        self.button_font = get_font(max(int(h * 0.028), 12), bold=True)

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

    @staticmethod
    def _human_size(size):
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{round(size / 1024)} KB"
        return f"{round(size / (1024 * 1024), 1)} MB"

    def _meta(self, path, is_dir):
        try:
            if is_dir:
                count = sum(1 for _ in os.scandir(path))
                return f"{count} item" + ("" if count == 1 else "s")
            return self._human_size(os.path.getsize(path))
        except OSError:
            return ""

    def _reload(self):
        self.scroll_offset = 0
        dirs, files = [], []
        try:
            for name in sorted(os.listdir(self.current), key=str.lower):
                if not self.show_hidden and name.startswith("."):
                    continue
                full = os.path.join(self.current, name)
                if os.path.isdir(full):
                    dirs.append((name, full, True))
                elif os.path.isfile(full):
                    files.append((name, full, False))
        except OSError:
            dirs, files = [], []
        self.entries = [(name, full, is_dir, self._meta(full, is_dir))
                        for name, full, is_dir in dirs + files]

    def _enter(self, path):
        if os.path.isdir(path):
            self.current = os.path.abspath(path)
            self._reload()

    def _at_root(self):
        parent = os.path.dirname(self.current)
        return not parent or parent == self.current

    def _go_up(self):
        if not self._at_root():
            self._enter(os.path.dirname(self.current))

    def _writable(self, directory):
        return paths.is_writable_dir(directory)

    def _select_current(self):
        if not self._writable(self.current):
            if self.on_error is not None:
                self.on_error("That folder isn't writable")
            return
        cb = self.on_select
        path = os.path.normpath(os.path.abspath(self.current))
        self.hide()
        if cb is not None:
            cb(path)

    def _start_creating(self):
        self.creating = True
        self.new_folder_input.text = ""
        self.new_folder_input.focused = True
        self.scroll_offset = 0

    def _cancel_creating(self):
        self.creating = False
        self.new_folder_input.text = ""
        self.new_folder_input.focused = False

    def _create_folder(self):
        name = self.new_folder_input.text.strip()
        if not name:
            self._cancel_creating()
            return
        try:
            os.makedirs(os.path.join(self.current, name), exist_ok=False)
        except OSError:
            if self.on_error is not None:
                self.on_error("Could not create folder")
            return
        self._cancel_creating()
        self._reload()

    def draw(self):
        if not self.visible or self.rect.width <= 0:
            return
        self.draw_shell()
        r = self.rect
        pad = self.padding
        list_top = self._draw_header(r, pad)
        foot_top = self._draw_footer(r, pad)
        self._list_rect = pg.Rect(r.x + pad, list_top, r.width - 2 * pad,
                                  max(foot_top - int(pad * 0.4) - list_top, 1))
        self._row_h = self.row_font.get_height() + 16
        self._max_visible = max(self._list_rect.height // self._row_h, 1)
        rows = len(self.entries) + (1 if self.creating else 0)
        max_offset = max(0, rows - self._max_visible)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
        self._draw_list()

    def _draw_header(self, r, pad):
        top = r.y + MODAL_RAIL
        title_surf = self.title_font.render("CHOOSE DATA FOLDER", True, Colors.white)
        band = max(title_surf.get_height(), self.tool_side)
        head_y = top + int(pad * 0.55)
        self.window.blit(title_surf,
                         (r.x + pad, head_y + (band - title_surf.get_height()) // 2))
        ty = head_y + (band - self.tool_side) // 2
        self._hidden_rect = pg.Rect(r.right - pad - self.tool_side, ty,
                                    self.tool_side, self.tool_side)
        self._newfolder_rect = pg.Rect(self._hidden_rect.x - 6 - self.tool_side, ty,
                                       self.tool_side, self.tool_side)
        self._draw_tool(self._newfolder_rect, draw_folder_plus, self.creating)
        self._draw_tool(self._hidden_rect, draw_eye, self.show_hidden, off=self.show_hidden)
        head_bottom = head_y + band + int(pad * 0.45)

        up_h = self.up_font.get_height() + 12
        bar_y = head_bottom + int(pad * 0.35)
        self._up_rect = pg.Rect(r.x + pad, bar_y, max(int(r.width * 0.16), 64), up_h)
        draw_button(self.window, self._up_rect, "↑ Up", self.up_font, disabled=self._at_root())
        crumb_x = self._up_rect.right + 10
        self._blit_breadcrumb(crumb_x, self._up_rect.centery, r.right - pad - crumb_x)
        bar_bottom = bar_y + up_h + int(pad * 0.4)
        pg.draw.line(self.window, Colors.button_border,
                     (r.x + pad, bar_bottom), (r.right - pad, bar_bottom))
        return bar_bottom + int(pad * 0.45)

    def _draw_tool(self, rect, icon_fn, on, off=False):
        hovered = rect.collidepoint(pg.mouse.get_pos())
        if on:
            self.window.blit(rounded_rect_surface(rect.size, 8, Colors.button_pressed,
                                                  border=Colors.accent, border_width=1),
                             rect.topleft)
            color = Colors.accent
        elif hovered:
            self.window.blit(rounded_rect_surface(rect.size, 8, Colors.button_hover),
                             rect.topleft)
            color = Colors.white
        else:
            color = Colors.text_mute
        if off:
            icon_fn(self.window, rect, color, off=True)
        else:
            icon_fn(self.window, rect, color)

    def _blit_breadcrumb(self, x, cy, avail):
        if avail <= 0:
            return
        parts = [p for p in self.current.replace("\\", "/").split("/") if p] or ["/"]
        tail = self.crumb_font.render(parts[-1], True, Colors.white)
        disp = parts[:]
        truncated = False
        while True:
            head = ("… / " if truncated else "")
            if len(disp) > 1:
                head += " / ".join(disp[:-1]) + " / "
            if self.crumb_font.size(head)[0] + tail.get_width() <= avail or len(disp) <= 1:
                break
            disp.pop(0)
            truncated = True
        head_surf = self.crumb_font.render(head, True, Colors.text_dim)
        y = cy - tail.get_height() // 2
        self.window.blit(head_surf, (x, y))
        self.window.blit(tail, (x + head_surf.get_width(), y))

    def _fit_left(self, text, font, max_w):
        if font.size(text)[0] <= max_w:
            return text
        while text and font.size("…" + text)[0] > max_w:
            text = text[1:]
        return "…" + text

    def _draw_footer(self, r, pad):
        btn_h = max(self.button_font.get_height() + 14, 32)
        btn_y = r.bottom - pad - btn_h
        btn_w = max(int(r.width * 0.30), 96)
        self._choose_rect = pg.Rect(r.right - pad - btn_w, btn_y, btn_w, btn_h)
        self._cancel_rect = pg.Rect(self._choose_rect.x - 10 - btn_w, btn_y, btn_w, btn_h)
        draw_button(self.window, self._cancel_rect, "Cancel", self.button_font)
        draw_button(self.window, self._choose_rect, "Choose folder", self.button_font,
                    primary=True)
        dest = os.path.join(self.current, paths.GAMES_SUBDIR)
        val_surf = self.sel_val_font.render(
            self._fit_left(dest, self.sel_val_font, r.width - 2 * pad), True, Colors.text_dim)
        label_surf = self.sel_label_font.render("SAVES TO", True, Colors.text_mute)
        block_h = label_surf.get_height() + 3 + val_surf.get_height()
        block_y = btn_y - int(pad * 0.7) - block_h
        self.window.blit(label_surf, (r.x + pad, block_y))
        self.window.blit(val_surf, (r.x + pad, block_y + label_surf.get_height() + 3))
        foot_top = block_y - int(pad * 0.6)
        pg.draw.line(self.window, Colors.button_border,
                     (r.x + pad, foot_top), (r.right - pad, foot_top))
        return foot_top

    def _draw_list(self):
        self._row_rects = []
        self._input_rect = pg.Rect(0, 0, 0, 0)
        rows_total = len(self.entries) + (1 if self.creating else 0)
        max_offset = max(0, rows_total - self._max_visible)
        gutter = 16 if max_offset else 0
        content_w = self._list_rect.width - gutter
        prev_clip = self.window.get_clip()
        self.window.set_clip(self._list_rect)
        try:
            mouse_pos = pg.mouse.get_pos()
            rows = ([None] if self.creating else []) + self.entries
            visible = rows[self.scroll_offset:self.scroll_offset + self._max_visible]
            for i, entry in enumerate(visible):
                row_rect = pg.Rect(self._list_rect.x, self._list_rect.y + i * self._row_h,
                                   content_w, self._row_h)
                if entry is None:
                    self._draw_input_row(row_rect)
                else:
                    self._draw_entry_row(row_rect, entry, mouse_pos)
        finally:
            self.window.set_clip(prev_clip)
        if max_offset:
            draw_scroll_thumb(self.window, self._list_rect, rows_total, self._max_visible,
                              self.scroll_offset / max_offset, self._last_scroll_activity_ms)

    def _draw_row_icon(self, icon_box, is_dir):
        char = "📁" if is_dir else "📄"
        if blit_emoji(self.window, char, icon_box.center, int(icon_box.height * 0.6)):
            return
        if is_dir:
            draw_folder(self.window, icon_box, Colors.amber)
        else:
            draw_file(self.window, icon_box, Colors.text_mute)

    def _draw_input_row(self, row_rect):
        icon_box = pg.Rect(row_rect.x + ROW_ICON_INSET, row_rect.y, ROW_ICON_BOX_W,
                           row_rect.height)
        self._draw_row_icon(icon_box, True)
        self._input_rect = pg.Rect(icon_box.right + ROW_TEXT_INSET, row_rect.y + 4,
                                   row_rect.right - icon_box.right - 14, row_rect.height - 8)
        self.new_folder_input.set_rect(self._input_rect)
        self.new_folder_input.draw()

    def _draw_entry_row(self, row_rect, entry, mouse_pos):
        name, path, is_dir, meta = entry
        if row_rect.collidepoint(mouse_pos):
            pg.draw.rect(self.window, Colors.button_hover, row_rect, border_radius=8)
        icon_box = pg.Rect(row_rect.x + ROW_ICON_INSET, row_rect.y, ROW_ICON_BOX_W,
                           row_rect.height)
        self._draw_row_icon(icon_box, is_dir)
        self._row_rects.append((row_rect, path, is_dir))
        meta_surf = self.meta_font.render(meta, True, Colors.text_mute)
        meta_x = row_rect.right - ROW_META_INSET - meta_surf.get_width()
        self.window.blit(meta_surf, (meta_x, row_rect.centery - meta_surf.get_height() // 2))
        name_color = Colors.white if is_dir else Colors.text_dim
        name_surf = fit_text_to_rect(
            self.row_font.render(name, True, name_color),
            pg.Rect(0, 0, max(meta_x - icon_box.right - 16, 1), row_rect.height))
        self.window.blit(name_surf,
                         (icon_box.right + ROW_TEXT_INSET,
                          row_rect.centery - name_surf.get_height() // 2))

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self.creating:
            if self._input_rect.collidepoint(pos):
                self.new_folder_input.handle_click(pos)
                return True
            self._create_folder()
            return True
        if self._newfolder_rect.collidepoint(pos):
            self._start_creating()
            return True
        if self._hidden_rect.collidepoint(pos):
            self.show_hidden = not self.show_hidden
            self._reload()
            return True
        if self._up_rect.collidepoint(pos):
            self._go_up()
            return True
        if self._choose_rect.collidepoint(pos):
            self._select_current()
            return True
        if self._cancel_rect.collidepoint(pos):
            self.hide()
            return True
        for row_rect, path, is_dir in self._row_rects:
            if row_rect.collidepoint(pos):
                if is_dir:
                    self._enter(path)
                return True
        return True

    def handle_scroll(self, pos, dy):
        if not self.visible or not self._list_rect.collidepoint(pos):
            return False
        rows_total = len(self.entries) + (1 if self.creating else 0)
        max_offset = max(0, rows_total - self._max_visible)
        if max_offset == 0:
            return False
        self.scroll_offset = max(0, min(self.scroll_offset - dy, max_offset))
        self._last_scroll_activity_ms = pg.time.get_ticks()
        return True

    def handle_key(self, event):
        if not self.visible or not self.creating:
            return False
        if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
            self._create_folder()
            return True
        return self.new_folder_input.handle_key(event)
