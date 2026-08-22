import shutil
import subprocess
from collections.abc import Callable

import pygame as pg

from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font, get_mono_font

CURSOR_BLINK_MS = 530
DOUBLE_CLICK_MS = 400
DOUBLE_CLICK_PX = 6


class TextInput:
    """
    The app's one editable text field -- nickname, pasted FEN, data folder,
    country search. It draws itself, owns the caret, the selection and the
    clipboard shortcuts, and reports finished values through the callbacks it
    was built with, so no screen has to deal with raw key events for text
    """

    def __init__(self, window: pg.Surface, max_chars: int = 20, placeholder: str = "nickname",
                 mono: bool = False, bg: str | None = None, radius: int = 4,
                 rest_align: str = "start", on_commit: Callable[[str], None] | None = None,
                 ascii_only: bool = False,
                 on_reject: Callable[[], None] | None = None) -> None:
        """
        Build a field ready to be placed. The caller sets its rect afterwards
        and the text size follows that rect, so the same field works at any
        window size

        :param window: default surface drawn to, normally the app window
        :param max_chars: hard limit on the stored value, applied on every
            insert and on assignment
        :param placeholder: grey hint shown while the field is empty and
            unfocused
        :param mono: True for the monospaced face, used for paths and FEN
        :param bg: fill color, or None for the standard raised surface
        :param radius: corner radius in pixels
        :param rest_align: start or end -- which end of an over-long value
            stays visible while the field is unfocused
        :param on_commit: called with the value when focus is given up, which
            is how a typed setting gets saved
        :param ascii_only: True to drop non-ASCII characters as they arrive
        :param on_reject: called once when ascii_only actually dropped
            something, so the screen can explain what happened
        """
        self.window = window
        self.max_chars = max_chars
        self.ascii_only = ascii_only
        self.on_reject = on_reject
        self.on_commit = on_commit
        self.placeholder = placeholder
        self.mono = mono
        self.bg = bg
        self.radius = radius
        self.rest_align = rest_align
        self._text = ""
        self.cursor = 0
        self.sel_anchor: int | None = None
        self._focused = False
        self.rect = pg.Rect(0, 0, 0, 0)
        self.font_factor = 1.6
        self._font_size = 16
        self.font = self._font(self._font_size)
        self.padding = 8
        self.scroll = 0
        self._last_action_ms = 0
        self._last_click_ms = -DOUBLE_CLICK_MS
        self._last_click_x = 0
        self._dragging = False
        self._cursor_width_cache: tuple[tuple[str, int], int] | None = None

    @property
    def text(self) -> str:
        """
        The value typed in the field right now, which is what a screen reads
        when the field commits

        :returns: the field's text, empty rather than None when unset
        """
        return self._text

    @text.setter
    def text(self, value: str | None) -> None:
        """
        Replace the whole value, used when a screen pushes a stored setting
        into the field. The caret lands at the end, any selection is dropped,
        and anything past the field's limit is cut off

        :param value: new text, None treated as empty
        """
        self._text = (value or "")[:self.max_chars]
        self.cursor = len(self._text)
        self.sel_anchor = None
        self.scroll = 0

    @property
    def focused(self) -> bool:
        """
        Whether this field is taking keystrokes at the moment, which also
        decides whether the caret is drawn

        :returns: True while the field holds focus
        """
        return self._focused

    @focused.setter
    def focused(self, value: bool) -> None:
        """
        Give the field focus or take it away. Losing focus ends any selection
        drag and fires the commit callback, so clicking away saves a typed
        value exactly like pressing Enter does

        :param value: True to focus the field, False to release it
        """
        value = bool(value)
        was = self._focused
        if value and not was:
            self._touch()
        if not value:
            self._dragging = False
        self._focused = value
        if was and not value and self.on_commit is not None:
            self.on_commit(self._text)

    def _font(self, size: int) -> pg.font.Font:
        """
        Load the face this field draws in: monospaced for paths and FEN, the
        bold sans everywhere else

        :param size: pixel size to load
        :returns: the font the value is rendered with
        """
        return get_mono_font(size) if self.mono else get_font(size, bold=True)

    def set_rect(self, rect: pg.Rect) -> None:
        """
        Place the field and size its text to that box, which is how a field
        follows the window. The font is only reloaded when the derived size
        actually changed, so a relayout is cheap

        :param rect: the field's box in window pixels
        """
        self.rect = pg.Rect(rect)
        size = max(int(rect.height / self.font_factor), 10)
        if size != self._font_size:
            self._font_size = size
            self.font = self._font(size)
            self._cursor_width_cache = None

    def _touch(self) -> None:
        """
        Note the moment of the last edit. That keeps the caret solid for a
        beat before it starts blinking again, and drops the cached caret
        position so the next frame measures the new text
        """
        self._last_action_ms = pg.time.get_ticks()
        self._cursor_width_cache = None

    def _sel_range(self) -> tuple[int, int] | None:
        """
        The selected span, ordered low to high whichever way the player
        dragged, which is what every selection-aware edit works from

        :returns: start and end character positions, or None when nothing is
            selected
        """
        if self.sel_anchor is None or self.sel_anchor == self.cursor:
            return None
        return (min(self.sel_anchor, self.cursor), max(self.sel_anchor, self.cursor))

    def _set_cursor(self, pos: int, extend: int) -> None:
        """
        Move the caret, growing or dropping the selection with it. Every
        keyboard caret move goes through here, so clamping to the text happens
        in exactly one place

        :param pos: target caret position, clamped into the text
        :param extend: nonzero, the Shift modifier bits, to extend the
            selection instead of clearing it
        """
        pos = max(0, min(pos, len(self._text)))
        if extend:
            if self.sel_anchor is None:
                self.sel_anchor = self.cursor
        else:
            self.sel_anchor = None
        self.cursor = pos
        self._touch()

    def _word_left(self, pos: int) -> int:
        """
        Find the start of the word before a position, where Ctrl+Left lands
        and how far Ctrl+Backspace deletes

        :param pos: caret position to search back from
        :returns: position of the start of the previous word
        """
        i = pos
        while i > 0 and self._text[i - 1].isspace():
            i -= 1
        while i > 0 and not self._text[i - 1].isspace():
            i -= 1
        return i

    def _word_right(self, pos: int) -> int:
        """
        Find where the next word begins, where Ctrl+Right lands and how far
        Ctrl+Delete deletes

        :param pos: caret position to search forward from
        :returns: position past the current word and the spaces after it
        """
        n = len(self._text)
        i = pos
        while i < n and not self._text[i].isspace():
            i += 1
        while i < n and self._text[i].isspace():
            i += 1
        return i

    def _arrow(self, direction: int, ctrl: int, shift: int) -> None:
        """
        Handle a Left or Right press with its modifiers. Without Shift, an
        arrow collapses an existing selection to that side instead of moving
        the caret, which is what a text field is expected to do

        :param direction: -1 for left, 1 for right
        :param ctrl: nonzero, the Ctrl modifier bits, to jump whole words
        :param shift: nonzero, the Shift modifier bits, to extend a selection
        """
        sel = self._sel_range()
        if sel and not shift:
            self.cursor = sel[0] if direction < 0 else sel[1]
            self.sel_anchor = None
            self._touch()
            return
        if ctrl:
            target = (self._word_left(self.cursor) if direction < 0
                      else self._word_right(self.cursor))
        else:
            target = self.cursor + direction
        self._set_cursor(target, shift)

    def _delete_selection(self) -> bool:
        """
        Cut the selected span out of the value, the shared first step of
        Backspace, Delete, Ctrl+X and typing over a selection

        :returns: True when there was a selection to remove
        """
        sel = self._sel_range()
        if not sel:
            return False
        self._text = self._text[:sel[0]] + self._text[sel[1]:]
        self.cursor = sel[0]
        self.sel_anchor = None
        self._touch()
        return True

    def _insert(self, text: str) -> None:
        """
        Put text in at the caret, whether typed one character at a time or
        pasted in one go, replacing any selection first. An ASCII-only field
        drops what it cannot accept and says so through the reject callback,
        and anything past the character limit is trimmed rather than refused

        :param text: text to insert at the caret
        """
        if self.ascii_only:
            filtered = "".join(ch for ch in text if ch.isascii() and ch.isprintable())
            if filtered != text and self.on_reject is not None:
                self.on_reject()
            text = filtered
        self._delete_selection()
        self.sel_anchor = None
        room = self.max_chars - len(self._text)
        if room <= 0:
            return
        text = text[:room]
        self._text = self._text[:self.cursor] + text + self._text[self.cursor:]
        self.cursor += len(text)
        self._touch()

    def _select_word_at(self, pos: int) -> None:
        """
        Select the whole word around a position, which is what a double click
        in the field does

        :param pos: character position the double click resolved to
        """
        self.sel_anchor = self._word_left(min(pos + 1, len(self._text)))
        self.cursor = self._word_right(pos)
        self._touch()

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Take a click. Inside the box it focuses the field and drops the caret
        where the player pointed; outside it releases focus, which is what
        commits the value. A double click selects a word and a Shift-click
        extends the selection

        :param pos: click position in window pixels
        :returns: True when the click landed inside this field
        """
        if not self.rect.collidepoint(pos):
            self.focused = False
            return False
        self.focused = True
        p = self._pos_at_x(pos[0])
        now = pg.time.get_ticks()
        shift = pg.key.get_mods() & pg.KMOD_SHIFT
        double = (now - self._last_click_ms < DOUBLE_CLICK_MS
                  and abs(pos[0] - self._last_click_x) < DOUBLE_CLICK_PX)
        self._last_click_ms = now
        self._last_click_x = pos[0]
        if double:
            self._select_word_at(p)
            self._dragging = False
        elif shift:
            if self.sel_anchor is None:
                self.sel_anchor = self.cursor
            self.cursor = p
            self._dragging = True
        else:
            self.cursor = p
            self.sel_anchor = p
            self._dragging = True
        self._touch()
        return True

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Handle one key press for a focused field: caret moves, word jumps,
        select-all, the clipboard shortcuts, both deletes and plain typing.
        Esc and Enter each release focus, which is what commits the value

        :param event: pygame KEYDOWN event; its unicode gives the character
        :returns: True when the field consumed the key
        """
        if not self._focused:
            return False
        key = event.key
        mod = event.mod
        ctrl = mod & pg.KMOD_CTRL
        shift = mod & pg.KMOD_SHIFT
        if key in (pg.K_ESCAPE, pg.K_RETURN, pg.K_KP_ENTER):
            self.focused = False
            return True
        if ctrl and key == pg.K_a:
            self.sel_anchor = 0
            self.cursor = len(self._text)
            self._touch()
            return True
        if ctrl and key == pg.K_c:
            self._copy_selection()
            return True
        if ctrl and key == pg.K_x:
            self._copy_selection()
            self._delete_selection()
            return True
        if ctrl and key == pg.K_v:
            pasted = _paste_from_clipboard()
            if pasted:
                self._insert(pasted)
            return True
        if key == pg.K_LEFT:
            self._arrow(-1, ctrl, shift)
            return True
        if key == pg.K_RIGHT:
            self._arrow(1, ctrl, shift)
            return True
        if key == pg.K_HOME:
            self._set_cursor(0, shift)
            return True
        if key == pg.K_END:
            self._set_cursor(len(self._text), shift)
            return True
        if key == pg.K_BACKSPACE:
            if not self._delete_selection():
                target = self._word_left(self.cursor) if ctrl else self.cursor - 1
                target = max(0, target)
                if target < self.cursor:
                    self._text = self._text[:target] + self._text[self.cursor:]
                    self.cursor = target
                    self._touch()
            return True
        if key == pg.K_DELETE:
            if not self._delete_selection():
                target = self._word_right(self.cursor) if ctrl else self.cursor + 1
                target = min(len(self._text), target)
                if target > self.cursor:
                    self._text = self._text[:self.cursor] + self._text[target:]
                    self._touch()
            return True
        char = getattr(event, "unicode", "")
        if char and char.isprintable():
            self._insert(char)
            return True
        return False

    def _copy_selection(self) -> None:
        """
        Put the selected text on the system clipboard, the step Ctrl+C and
        Ctrl+X share
        """
        sel = self._sel_range()
        if sel:
            _copy_to_clipboard(self._text[sel[0]:sel[1]])

    def _field_width(self) -> int:
        """
        How much width the text may actually use once padding is taken off,
        the measure a long value is scrolled against

        :returns: usable text width in pixels, at least 1
        """
        return max(self.rect.width - 2 * self.padding, 1)

    def _pos_at_x(self, x: int) -> int:
        """
        Turn a window x into the nearest caret position, which is how a click
        or a drag puts the caret between two characters

        :param x: window x in pixels
        :returns: the character position closest to that x
        """
        rel = x - (self.rect.x + self.padding) + self.scroll
        best, best_dist = 0, abs(rel)
        for i in range(1, len(self._text) + 1):
            w = self.font.size(self._text[:i])[0]
            dist = abs(w - rel)
            if dist < best_dist:
                best, best_dist = i, dist
        return best

    def _cursor_visible(self) -> bool:
        """
        Whether the caret is painted on this frame. It stays solid for a beat
        after every edit, so fast typing never blinks it away, and only then
        falls back into the steady blink

        :returns: True when the caret should be drawn
        """
        if not self._focused:
            return False
        elapsed = pg.time.get_ticks() - self._last_action_ms
        if elapsed < CURSOR_BLINK_MS:
            return True
        return (pg.time.get_ticks() // CURSOR_BLINK_MS) % 2 == 0

    def draw(self, surface: pg.Surface | None = None) -> None:
        """
        Paint the field -- frame, selection band, text and caret -- and keep
        the view scrolled so the caret stays inside the box. It also advances
        a selection drag, because motion events never reach this widget, and
        it clips its drawing to the field so nothing bleeds into the panel

        :param surface: surface to draw on, or None for the field's own window
        """
        window = self.window if surface is None else surface
        bg = self.bg if self.bg is not None else Colors.surface_raised
        pg.draw.rect(window, bg, self.rect, border_radius=self.radius)
        border_color = Colors.accent if self._focused else Colors.border
        border_width = 2 if self._focused else 1
        pg.draw.rect(window, border_color, self.rect, border_width,
                     border_radius=self.radius)

        if self._dragging:
            if pg.mouse.get_pressed()[0]:
                self.cursor = self._pos_at_x(pg.mouse.get_pos()[0])
                self._touch()
            else:
                self._dragging = False

        field_w = self._field_width()
        cursor_key = (self._text, self.cursor)
        if self._cursor_width_cache is not None and self._cursor_width_cache[0] == cursor_key:
            cursor_x = self._cursor_width_cache[1]
        else:
            cursor_x = self.font.size(self._text[:self.cursor])[0]
            self._cursor_width_cache = (cursor_key, cursor_x)
        if not self._focused:
            if self.rest_align == "end":
                self.scroll = max(0, self.font.size(self._text)[0] - field_w)
            else:
                self.scroll = 0
        else:
            if cursor_x - self.scroll > field_w:
                self.scroll = cursor_x - field_w
            if cursor_x - self.scroll < 0:
                self.scroll = cursor_x
        self.scroll = max(0, self.scroll)
        base_x = self.rect.x + self.padding - self.scroll
        cy = self.rect.centery
        glyph_h = self.font.get_height()

        prev_clip = window.get_clip()
        window.set_clip(self.rect if prev_clip is None else self.rect.clip(prev_clip))
        sel = self._sel_range()
        if sel and self._focused:
            sx = base_x + self.font.size(self._text[:sel[0]])[0]
            ex = base_x + self.font.size(self._text[:sel[1]])[0]
            band = pg.Surface((max(int(ex - sx), 1), glyph_h), pg.SRCALPHA)
            band.fill(pg.Color(Colors.text_selection))
            window.blit(band, (sx, cy - glyph_h / 2))
        if self._text:
            surf = render_text(self.font, self._text, Colors.text)
            window.blit(surf, (base_x, cy - surf.get_height() / 2))
        elif not self._focused:
            surf = render_text(self.font, self.placeholder, Colors.border)
            window.blit(surf, (self.rect.x + self.padding, cy - surf.get_height() / 2))
        if self._cursor_visible():
            cx = base_x + cursor_x
            pg.draw.line(window, Colors.text,
                         (cx, cy - glyph_h / 2), (cx, cy + glyph_h / 2), 2)
        window.set_clip(prev_clip)


def _copy_to_clipboard(text: str) -> bool:
    """
    Put text on the system clipboard, trying the desktop helpers in turn --
    Wayland, X11, macOS -- before falling back to pygame's own clipboard. The
    helpers come first because the pygame path is unreliable on a Wayland
    desktop

    :param text: text to place on the clipboard
    :returns: True when one of the methods accepted it
    """
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"], ["pbcopy"]):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), timeout=2, check=True)
            return True
        except (subprocess.SubprocessError, OSError):
            continue
    try:
        pg.scrap.init()
        pg.scrap.put(pg.SCRAP_TEXT, text.encode("utf-8"))
        return True
    except (pg.error, AttributeError):
        return False


def _paste_from_clipboard() -> str:
    """
    Read the system clipboard through the same desktop helpers, so pasting a
    FEN or a folder path works where pygame's clipboard alone would not, and
    clean whatever comes back before it reaches the field

    :returns: cleaned clipboard text, empty when nothing could be read
    """
    candidates = [
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["pbpaste"],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=2, check=True,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        return _sanitise(result.stdout.decode("utf-8", errors="replace"))
    try:
        pg.scrap.init()
        raw = pg.scrap.get(pg.SCRAP_TEXT)
        if raw is None:
            return ""
        return _sanitise(raw.decode("utf-8", errors="replace"))
    except (pg.error, AttributeError):
        return ""


def _sanitise(text: str) -> str:
    """
    Flatten pasted text into something a single-line field can hold: line
    breaks become spaces and unprintable characters are dropped. That is what
    stops a multi-line paste from turning into a stored setting spanning
    several lines

    :param text: raw clipboard text
    :returns: single-line printable text, trimmed at both ends
    """
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return "".join(ch for ch in text if ch.isprintable() or ch == " ").strip()
