import pygame as pg

from frontend.visual.colors import Colors


class TextInput:

    def __init__(self, window, max_chars=20, placeholder="nickname"):
        self.window = window
        self.max_chars = max_chars
        self.placeholder = placeholder
        self.text = ""
        self.focused = False
        self.rect = pg.Rect(0, 0, 0, 0)
        self.font_factor = 1.6
        self.font = pg.font.SysFont("Arial", 16, bold=True)
        self.padding = 8

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        size = max(int(rect.height / self.font_factor), 10)
        self.font = pg.font.SysFont("Arial", size, bold=True)

    def draw(self):
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=4)
        border_color = Colors.button_pressed if self.focused else Colors.button_border
        border_width = 2 if self.focused else 1
        pg.draw.rect(self.window, border_color, self.rect, border_width, border_radius=4)

        if self.text:
            display = self.text + ("|" if self.focused else "")
            color = Colors.white
        elif self.focused:
            display = "|"
            color = Colors.white
        else:
            display = self.placeholder
            color = Colors.button_border

        surface = self.font.render(display, True, color)
        max_w = max(self.rect.width - 2 * self.padding, 0)
        if surface.get_width() > max_w > 0:
            crop = pg.Rect(
                surface.get_width() - max_w, 0, max_w, surface.get_height(),
            )
            surface = surface.subsurface(crop)
        prev_clip = self.window.get_clip()
        self.window.set_clip(self.rect)
        self.window.blit(
            surface,
            (self.rect.x + self.padding,
             self.rect.centery - surface.get_height() / 2),
        )
        self.window.set_clip(prev_clip)

    def handle_click(self, pos):
        inside = self.rect.collidepoint(pos)
        self.focused = inside
        return inside

    def handle_key(self, event):
        if not self.focused:
            return False
        if event.key == pg.K_ESCAPE:
            self.focused = False
            return True
        if event.key == pg.K_RETURN:
            self.focused = False
            return True
        if event.key == pg.K_BACKSPACE:
            if self.text:
                self.text = self.text[:-1]
            return True
        if event.key == pg.K_v and (event.mod & pg.KMOD_CTRL):
            pasted = _paste_from_clipboard()
            if pasted:
                room = self.max_chars - len(self.text)
                self.text += pasted[:room]
            return True
        char = getattr(event, "unicode", "")
        if char and char.isprintable() and len(self.text) < self.max_chars:
            self.text += char
            return True
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
