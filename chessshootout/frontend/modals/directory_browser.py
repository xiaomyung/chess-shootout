import os
from collections.abc import Callable

import pygame as pg

from chessshootout import paths
from chessshootout.frontend.modals.base import BaseModal, MODAL_RAIL
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.emoji import blit_emoji
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.icons import draw_eye, draw_file, draw_folder, draw_folder_plus
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import draw_button, fit_text_to_rect


ROW_ICON_BOX_W = 24
ROW_ICON_INSET = 6
ROW_TEXT_INSET = 8
ROW_META_INSET = 10
TOOL_CUT = 4
ROW_VPAD = 16
SCROLLBAR_GUTTER = 16


class DirectoryBrowser(BaseModal, ScrollHost):
    """
    The folder chooser Options uses to move where the game keeps its saved
    games, drawn inside the app in the shared modal shell rather than handed
    to a system file dialog. It is a global modal with a scrolling listing of
    its own, so the wheel belongs to it while it is open
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build the browser once at startup, parked on the home folder and
        listing nothing until it is actually opened

        :param window: the app window surface this modal draws onto
        """
        super().__init__(window)
        self.current = os.path.expanduser("~")
        self.entries = []
        self.show_hidden = False
        self.creating = False
        self.on_select = None
        self.on_error = None
        self._scroll_px = 0.0
        self._content_px = 0
        self.new_folder_input = TextInput(window, max_chars=64, placeholder="new folder")
        self._row_rects = []
        self._list_rect = pg.Rect(0, 0, 0, 0)
        self._row_h = 1
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self._list_rect, self._content_px),
            wheel_step_px=lambda: self._row_h,
        )
        self._up_rect = pg.Rect(0, 0, 0, 0)
        self._newfolder_rect = pg.Rect(0, 0, 0, 0)
        self._hidden_rect = pg.Rect(0, 0, 0, 0)
        self._cancel_rect = pg.Rect(0, 0, 0, 0)
        self._choose_rect = pg.Rect(0, 0, 0, 0)
        self._input_rect = pg.Rect(0, 0, 0, 0)
        self._on_rect_changed()

    def _on_rect_changed(self) -> None:
        """
        Rebuild the padding, the tool-button size and every font from the new
        size, so the whole browser scales with the window
        """
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

    def show(self, start_dir: str, on_select: Callable[[str], None],
             on_error: Callable[[str], None] | None = None) -> None:
        """
        Open the browser on a starting folder and list what is inside it. A
        missing or unusable starting folder falls back to the home folder
        instead of opening on nothing

        :param start_dir: folder to open on, ignored when it is not a directory
        :param on_select: run with the absolute path the player settles on
        :param on_error: run with a short message the player should see, such
            as a folder that cannot be written to, or None to stay quiet
        """
        start = start_dir if start_dir and os.path.isdir(start_dir) else os.path.expanduser("~")
        self.current = os.path.abspath(start)
        self.on_select = on_select
        self.on_error = on_error
        self.show_hidden = False
        self.creating = False
        self.new_folder_input.text = ""
        self._reload()
        super().show()

    def hide(self) -> None:
        """
        Close the browser, abandon a half-typed new folder name and stop any
        scroll still gliding
        """
        super().hide()
        self.creating = False
        self.scroll.cancel()

    @staticmethod
    def _human_size(size: int) -> str:
        """
        Spell a file size the way a listing row shows it -- bytes, kilobytes
        or megabytes -- so the column reads at a glance

        :param size: file size in bytes
        :returns: short readable size, such as 12 KB
        """
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{round(size / 1024)} KB"
        return f"{round(size / (1024 * 1024), 1)} MB"

    def _meta(self, path: str, is_dir: bool) -> str:
        """
        Describe one entry for the right-hand column: how many things a folder
        holds, or how large a file is. Anything that cannot be read gets an
        empty description rather than breaking the listing

        :param path: absolute path of the entry
        :param is_dir: True when the entry is a folder
        :returns: short description for the row, empty when it cannot be read
        """
        try:
            if is_dir:
                count = sum(1 for _ in os.scandir(path))
                return f"{count} item{'' if count == 1 else 's'}"
            return self._human_size(os.path.getsize(path))
        except OSError:
            return ""

    def _reload(self) -> None:
        """
        Re-read the current folder into the listing, folders before files and
        each group alphabetically, with hidden entries only while the eye tool
        is on. A folder that cannot be read simply lists as empty
        """
        self._scroll_px = 0.0
        self.scroll.cancel()
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

    def _enter(self, path: str) -> None:
        """
        Step into a folder and list it, which is what clicking a folder row
        does. Anything that is not a folder is ignored

        :param path: folder to move into
        """
        if os.path.isdir(path):
            self.current = os.path.abspath(path)
            self._reload()

    def _at_root(self) -> bool:
        """
        Say whether the current folder has nowhere further up, which is what
        greys the Up button out

        :returns: True when the current folder is the top of its tree
        """
        parent = os.path.dirname(self.current)
        return not parent or parent == self.current

    def _go_up(self) -> None:
        """
        Move to the parent folder, the Up button's action, and do nothing at
        all once the top of the tree is reached
        """
        if not self._at_root():
            self._enter(os.path.dirname(self.current))

    def _writable(self, directory: str) -> bool:
        """
        Say whether the game could really save games into a folder, asked
        before a choice is accepted rather than after the first failed save

        :param directory: folder to test
        :returns: True when the folder can be written to
        """
        return paths.is_writable_dir(directory)

    def _select_current(self) -> None:
        """
        Accept the current folder as the answer. One the game cannot write to
        is refused and reported through the error callback; otherwise the
        browser closes first and only then hands the path over
        """
        if not self._writable(self.current):
            if self.on_error is not None:
                self.on_error("That folder isn't writable")
            return
        cb = self.on_select
        path = os.path.normpath(os.path.abspath(self.current))
        self.hide()
        if cb is not None:
            cb(path)

    def _start_creating(self) -> None:
        """
        Turn the first row of the listing into a text field for a new folder
        name, which is the New Folder tool's action, with the list scrolled
        back to the top so the field is in view
        """
        self.creating = True
        self.new_folder_input.text = ""
        self.new_folder_input.focused = True
        self._scroll_px = 0.0
        self.scroll.cancel()

    def _cancel_creating(self) -> None:
        """
        Abandon the new-folder row and its half-typed name, leaving the plain
        listing behind
        """
        self.creating = False
        self.new_folder_input.text = ""
        self.new_folder_input.focused = False

    def _create_folder(self) -> None:
        """
        Make the folder the player named and show it in the listing. An empty
        name simply cancels, and a name that cannot be created is reported
        through the error callback with the row left open to be corrected
        """
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

    def draw(self) -> None:
        """
        Paint the browser: shell, header with its tools, the listing and the
        footer, with the listing taking whatever the header and footer leave
        between them. Drawing is also what fixes the rects clicks are tested
        against
        """
        if not self.visible or self.rect.width <= 0:
            return
        self.scroll.tick()
        self.draw_shell()
        r = self.rect
        pad = self.padding
        list_top = self._draw_header(r, pad)
        foot_top = self._draw_footer(r, pad)
        self._list_rect = pg.Rect(r.x + pad, list_top, r.width - 2 * pad,
                                  max(foot_top - int(pad * 0.4) - list_top, 1))
        self._row_h = self.row_font.get_height() + ROW_VPAD
        rows_total = len(self.entries) + (1 if self.creating else 0)
        self._content_px = rows_total * self._row_h
        self._draw_list()

    def _draw_header(self, r: pg.Rect, pad: int) -> int:
        """
        Draw the title, the New Folder and hidden-files tools, the Up button
        and the breadcrumb of the folder being looked at

        :param r: the modal's whole rect in window pixels
        :param pad: padding in pixels between the shell edge and its contents
        :returns: y where the listing may start, in window pixels
        """
        top = r.y + MODAL_RAIL
        title_surf = self.title_font.render("CHOOSE DATA FOLDER", True, Colors.text)
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
        draw_button(self.window, self._up_rect, "Up", self.up_font, disabled=self._at_root(),
                    cut=True)
        crumb_x = self._up_rect.right + 10
        self._blit_breadcrumb(crumb_x, self._up_rect.centery, r.right - pad - crumb_x)
        bar_bottom = bar_y + up_h + int(pad * 0.4)
        pg.draw.line(self.window, Colors.border,
                     (r.x + pad, bar_bottom), (r.right - pad, bar_bottom))
        return bar_bottom + int(pad * 0.45)

    def _draw_tool(self, rect: pg.Rect, icon_fn: Callable[..., None], on: bool,
                   off: bool = False) -> None:
        """
        Draw one small tool button in the header, framed while the mode it
        controls is on and lit while the cursor is over it

        :param rect: button area in window pixels
        :param icon_fn: icon drawing function, called with the window, the
            rect and the colour to draw in
        :param on: True when the mode this button controls is active
        :param off: True to ask the icon for its struck-through form
        """
        hovered = rect.collidepoint(pg.mouse.get_pos())
        if on:
            self.window.blit(cut_rect_surface(rect.size, TOOL_CUT, Colors.surface_active,
                                              border=Colors.accent, border_width=1,
                                              corners=("tr", "bl")),
                             rect.topleft)
            color = Colors.accent
        elif hovered:
            self.window.blit(cut_rect_surface(rect.size, TOOL_CUT, Colors.surface_hover,
                                              corners=("tr", "bl")),
                             rect.topleft)
            color = Colors.text
        else:
            color = Colors.text_muted
        if off:
            icon_fn(self.window, rect, color, off=True)
        else:
            icon_fn(self.window, rect, color)

    def _blit_breadcrumb(self, x: int, cy: int, avail: int) -> None:
        """
        Draw the path down to the current folder, dropping folders off the
        front behind a leading ellipsis until it fits, so the folder actually
        being looked at is the part that always survives

        :param x: left edge of the breadcrumb in window pixels
        :param cy: centre line the breadcrumb sits on, in window pixels
        :param avail: width the breadcrumb may take, in pixels
        """
        if avail <= 0:
            return
        parts = [p for p in self.current.replace("\\", "/").split("/") if p] or ["/"]
        tail = self.crumb_font.render(parts[-1], True, Colors.text)
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

    def _fit_left(self, text: str, font: pg.font.Font, max_w: int) -> str:
        """
        Trim text from the left until it fits, which keeps the end of a long
        path -- the part that identifies it -- on screen instead of the start

        :param text: text to fit, normally a folder path
        :param font: font the text will be drawn in
        :param max_w: width available in pixels
        :returns: the text, or a left-trimmed version led by an ellipsis
        """
        if font.size(text)[0] <= max_w:
            return text
        while text and font.size("…" + text)[0] > max_w:
            text = text[1:]
        return "…" + text

    def _draw_footer(self, r: pg.Rect, pad: int) -> int:
        """
        Draw the Cancel and Choose buttons and, above them, the exact folder
        saved games would land in, so the player sees the result of the choice
        before making it

        :param r: the modal's whole rect in window pixels
        :param pad: padding in pixels between the shell edge and its contents
        :returns: y where the footer starts, in window pixels
        """
        btn_h = max(self.button_font.get_height() + 14, 32)
        btn_y = r.bottom - pad - btn_h
        btn_w = max(int(r.width * 0.30), 96)
        self._choose_rect = pg.Rect(r.right - pad - btn_w, btn_y, btn_w, btn_h)
        self._cancel_rect = pg.Rect(self._choose_rect.x - 10 - btn_w, btn_y, btn_w, btn_h)
        draw_button(self.window, self._cancel_rect, "Cancel", self.button_font, cut=True)
        draw_button(self.window, self._choose_rect, "Choose folder", self.button_font,
                    primary=True, cut=True)
        dest = os.path.join(self.current, paths.GAMES_SUBDIR)
        val_surf = self.sel_val_font.render(
            self._fit_left(dest, self.sel_val_font, r.width - 2 * pad), True, Colors.text_dim)
        label_surf = self.sel_label_font.render("SAVES TO", True, Colors.text_muted)
        block_h = label_surf.get_height() + 3 + val_surf.get_height()
        block_y = btn_y - int(pad * 0.7) - block_h
        self.window.blit(label_surf, (r.x + pad, block_y))
        self.window.blit(val_surf, (r.x + pad, block_y + label_surf.get_height() + 3))
        foot_top = block_y - int(pad * 0.6)
        pg.draw.line(self.window, Colors.border,
                     (r.x + pad, foot_top), (r.right - pad, foot_top))
        return foot_top

    def _draw_list(self) -> None:
        """
        Draw the slice of the listing that is on screen, clipped to the list
        area, with the new-folder field taking the first row while one is
        being created. Row rects are remembered here so a click can be matched
        to an entry
        """
        self._row_rects = []
        self._input_rect = pg.Rect(0, 0, 0, 0)
        max_px = max(0, self._content_px - self._list_rect.height)
        self._scroll_px = max(0.0, min(self._scroll_px, max_px))
        gutter = SCROLLBAR_GUTTER if max_px > 0 else 0
        content_w = self._list_rect.width - gutter
        rows = ([None] if self.creating else []) + self.entries
        first, sub, n_draw = self.scroll.row_window(self._list_rect, self._row_h)
        prev_clip = self.window.get_clip()
        self.window.set_clip(self._list_rect)
        try:
            mouse_pos = pg.mouse.get_pos()
            y0 = self._list_rect.y - sub
            for i, entry in enumerate(rows[first:first + n_draw]):
                row_rect = pg.Rect(self._list_rect.x, y0 + i * self._row_h,
                                   content_w, self._row_h)
                if entry is None:
                    self._draw_input_row(row_rect)
                else:
                    self._draw_entry_row(row_rect, entry, mouse_pos)
        finally:
            self.window.set_clip(prev_clip)
        self.scroll.draw_thumb(self.window)

    def _draw_row_icon(self, icon_box: pg.Rect, is_dir: bool) -> None:
        """
        Draw the little folder or file mark at the start of a row, falling
        back to a vector icon when the emoji artwork is unavailable

        :param icon_box: square area for the icon in window pixels
        :param is_dir: True for a folder icon, False for a file icon
        """
        char = "📁" if is_dir else "📄"
        if blit_emoji(self.window, char, icon_box.center, int(icon_box.height * 0.6)):
            return
        if is_dir:
            draw_folder(self.window, icon_box, Colors.amber)
        else:
            draw_file(self.window, icon_box, Colors.text_muted)

    def _draw_input_row(self, row_rect: pg.Rect) -> None:
        """
        Draw the row where a new folder is being named: a folder icon followed
        by the live text field

        :param row_rect: area of the row in window pixels
        """
        icon_box = pg.Rect(row_rect.x + ROW_ICON_INSET, row_rect.y, ROW_ICON_BOX_W,
                           row_rect.height)
        self._draw_row_icon(icon_box, True)
        self._input_rect = pg.Rect(icon_box.right + ROW_TEXT_INSET, row_rect.y + 4,
                                   row_rect.right - icon_box.right - 14, row_rect.height - 8)
        self.new_folder_input.set_rect(self._input_rect)
        self.new_folder_input.draw()

    def _draw_entry_row(self, row_rect: pg.Rect, entry: tuple[str, str, bool, str],
                        mouse_pos: tuple[int, int]) -> None:
        """
        Draw one listing row -- icon, name, and size or item count on the
        right -- and remember where it landed so a click can open it. Files
        are drawn dimmer than folders, since only folders can be entered

        :param row_rect: area of the row in window pixels
        :param entry: the entry's name, absolute path, folder flag and
            right-hand description
        :param mouse_pos: cursor position in window pixels, for the hover state
        """
        name, path, is_dir, meta = entry
        if row_rect.collidepoint(mouse_pos):
            pg.draw.rect(self.window, Colors.surface_hover, row_rect, border_radius=8)
        icon_box = pg.Rect(row_rect.x + ROW_ICON_INSET, row_rect.y, ROW_ICON_BOX_W,
                           row_rect.height)
        self._draw_row_icon(icon_box, is_dir)
        self._row_rects.append((row_rect, path, is_dir))
        meta_surf = self.meta_font.render(meta, True, Colors.text_muted)
        meta_x = row_rect.right - ROW_META_INSET - meta_surf.get_width()
        self.window.blit(meta_surf, (meta_x, row_rect.centery - meta_surf.get_height() // 2))
        name_color = Colors.text if is_dir else Colors.text_dim
        name_surf = fit_text_to_rect(
            self.row_font.render(name, True, name_color),
            pg.Rect(0, 0, max(meta_x - icon_box.right - 16, 1), row_rect.height))
        self.window.blit(name_surf,
                         (icon_box.right + ROW_TEXT_INSET,
                          row_rect.centery - name_surf.get_height() // 2))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a click to the tools, the Up button, the footer buttons or a
        listing row, with a new-folder field taking priority while one is open
        -- clicking away from it is what creates the folder. The browser
        claims every click while it is open

        :param pos: click position in window pixels
        :returns: True whenever the browser is open
        """
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
        if self._list_rect.collidepoint(pos):
            for row_rect, path, is_dir in self._row_rects:
                if row_rect.collidepoint(pos):
                    if is_dir:
                        self._enter(path)
                    return True
        return True

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Feed typing to the new-folder field, with Enter creating the folder.
        Keys do nothing at all while no folder is being named

        :param event: pygame KEYDOWN event
        :returns: True when the key was used
        """
        if not self.visible or not self.creating:
            return False
        if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
            self._create_folder()
            return True
        return self.new_folder_input.handle_key(event)
