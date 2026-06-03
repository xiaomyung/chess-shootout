import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.fonts import get_font, get_mono_font

CURSOR_BLINK_MS = 530
DOUBLE_CLICK_MS = 400
DOUBLE_CLICK_PX = 6


class TextInput:

    def __init__(self, window, max_chars=20, placeholder="nickname", mono=False,
                 bg=None, radius=4, rest_align="start"):
        self.window = window
        self.max_chars = max_chars
        self.placeholder = placeholder
        self.mono = mono
        self.bg = bg
        self.radius = radius
        self.rest_align = rest_align
        self._text = ""
        self.cursor = 0
        self.sel_anchor = None
        self._focused = False
        self.rect = pg.Rect(0, 0, 0, 0)
        self.font_factor = 1.6
        self.font = self._font(16)
        self.padding = 8
        self.scroll = 0
        self._last_action_ms = 0
        self._last_click_ms = -DOUBLE_CLICK_MS
        self._last_click_x = 0
        self._dragging = False

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = (value or "")[:self.max_chars]
        self.cursor = len(self._text)
        self.sel_anchor = None
        self.scroll = 0

    @property
    def focused(self):
        return self._focused

    @focused.setter
    def focused(self, value):
        value = bool(value)
        if value and not self._focused:
            self._touch()
        if not value:
            self._dragging = False
        self._focused = value

    def _font(self, size):
        return get_mono_font(size) if self.mono else get_font(size, bold=True)

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        size = max(int(rect.height / self.font_factor), 10)
        self.font = self._font(size)

    def _touch(self):
        self._last_action_ms = pg.time.get_ticks()

    def _sel_range(self):
        if self.sel_anchor is None or self.sel_anchor == self.cursor:
            return None
        return (min(self.sel_anchor, self.cursor), max(self.sel_anchor, self.cursor))

    def _set_cursor(self, pos, extend):
        pos = max(0, min(pos, len(self._text)))
        if extend:
            if self.sel_anchor is None:
                self.sel_anchor = self.cursor
        else:
            self.sel_anchor = None
        self.cursor = pos
        self._touch()

    def _word_left(self, pos):
        i = pos
        while i > 0 and self._text[i - 1].isspace():
            i -= 1
        while i > 0 and not self._text[i - 1].isspace():
            i -= 1
        return i

    def _word_right(self, pos):
        n = len(self._text)
        i = pos
        while i < n and not self._text[i].isspace():
            i += 1
        while i < n and self._text[i].isspace():
            i += 1
        return i

    def _arrow(self, direction, ctrl, shift):
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

    def _delete_selection(self):
        sel = self._sel_range()
        if not sel:
            return False
        self._text = self._text[:sel[0]] + self._text[sel[1]:]
        self.cursor = sel[0]
        self.sel_anchor = None
        self._touch()
        return True

    def _insert(self, text):
        self._delete_selection()
        room = self.max_chars - len(self._text)
        if room <= 0:
            return
        text = text[:room]
        self._text = self._text[:self.cursor] + text + self._text[self.cursor:]
        self.cursor += len(text)
        self._touch()

    def _select_word_at(self, pos):
        self.sel_anchor = self._word_left(min(pos + 1, len(self._text)))
        self.cursor = self._word_right(pos)
        self._touch()

    def handle_click(self, pos):
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

    def handle_key(self, event):
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

    def _copy_selection(self):
        sel = self._sel_range()
        if sel:
            _copy_to_clipboard(self._text[sel[0]:sel[1]])

    def _field_width(self):
        return max(self.rect.width - 2 * self.padding, 1)

    def _pos_at_x(self, x):
        rel = x - (self.rect.x + self.padding) + self.scroll
        best, best_dist = 0, abs(rel)
        for i in range(1, len(self._text) + 1):
            w = self.font.size(self._text[:i])[0]
            dist = abs(w - rel)
            if dist < best_dist:
                best, best_dist = i, dist
        return best

    def _cursor_visible(self):
        if not self._focused:
            return False
        elapsed = pg.time.get_ticks() - self._last_action_ms
        if elapsed < CURSOR_BLINK_MS:
            return True
        return (pg.time.get_ticks() // CURSOR_BLINK_MS) % 2 == 0

    def draw(self):
        bg = self.bg if self.bg is not None else Colors.surface_raised
        pg.draw.rect(self.window, bg, self.rect, border_radius=self.radius)
        border_color = Colors.accent if self._focused else Colors.border
        border_width = 2 if self._focused else 1
        pg.draw.rect(self.window, border_color, self.rect, border_width,
                     border_radius=self.radius)

        if self._dragging:
            if pg.mouse.get_pressed()[0]:
                self.cursor = self._pos_at_x(pg.mouse.get_pos()[0])
                self._touch()
            else:
                self._dragging = False

        field_w = self._field_width()
        cursor_x = self.font.size(self._text[:self.cursor])[0]
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

        prev_clip = self.window.get_clip()
        self.window.set_clip(self.rect if prev_clip is None else self.rect.clip(prev_clip))
        sel = self._sel_range()
        if sel and self._focused:
            sx = base_x + self.font.size(self._text[:sel[0]])[0]
            ex = base_x + self.font.size(self._text[:sel[1]])[0]
            band = pg.Surface((max(int(ex - sx), 1), glyph_h), pg.SRCALPHA)
            band.fill(pg.Color(Colors.text_selection))
            self.window.blit(band, (sx, cy - glyph_h / 2))
        if self._text:
            surf = self.font.render(self._text, True, Colors.text)
            self.window.blit(surf, (base_x, cy - surf.get_height() / 2))
        elif not self._focused:
            surf = self.font.render(self.placeholder, True, Colors.border)
            self.window.blit(surf, (self.rect.x + self.padding, cy - surf.get_height() / 2))
        if self._cursor_visible():
            cx = base_x + cursor_x
            pg.draw.line(self.window, Colors.text,
                         (cx, cy - glyph_h / 2), (cx, cy + glyph_h / 2), 2)
        self.window.set_clip(prev_clip)


def _copy_to_clipboard(text):
    import shutil
    import subprocess
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


def _paste_from_clipboard():
    import shutil
    import subprocess
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
        try:
            text = result.stdout.decode("utf-8", errors="replace")
        except Exception:
            continue
        return _sanitise(text)
    try:
        pg.scrap.init()
        raw = pg.scrap.get(pg.SCRAP_TEXT)
        if raw is None:
            return ""
        return _sanitise(raw.decode("utf-8", errors="replace"))
    except (pg.error, AttributeError):
        return ""


def _sanitise(text):
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return "".join(ch for ch in text if ch.isprintable() or ch == " ").strip()
