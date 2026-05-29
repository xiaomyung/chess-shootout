import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.widgets import fit_text_to_rect
from frontend.visual.fonts import get_font


DEFAULT_DURATION_MS = 1800
FADE_OUT_MS = 250
TOP_OFFSET_PX = 12
PADDING_X = 16
PADDING_Y = 8


class Toast:

    def __init__(self, window):
        self.window = window
        self.message = None
        self._shown_at_ms = 0
        self.duration_ms = DEFAULT_DURATION_MS
        self.font = get_font(16, bold=True)

    def show(self, message, duration_ms=None):
        self.message = message
        self._shown_at_ms = pg.time.get_ticks()
        if duration_ms is not None:
            self.duration_ms = duration_ms

    def hide(self):
        self.message = None

    def is_visible(self, now_ms=None):
        if self.message is None:
            return False
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        return now_ms - self._shown_at_ms < self.duration_ms

    def _alpha(self, now_ms):
        elapsed = now_ms - self._shown_at_ms
        remaining = self.duration_ms - elapsed
        if remaining <= 0:
            return 0
        if remaining >= FADE_OUT_MS:
            return 255
        return int(255 * remaining / FADE_OUT_MS)

    def draw(self):
        now_ms = pg.time.get_ticks()
        if not self.is_visible(now_ms):
            self.message = None
            return
        text_surf = self.font.render(self.message, True, Colors.white)
        toast_w = text_surf.get_width() + 2 * PADDING_X
        toast_h = text_surf.get_height() + 2 * PADDING_Y
        win_w = self.window.get_width()
        rect = pg.Rect(
            (win_w - toast_w) // 2, TOP_OFFSET_PX,
            toast_w, toast_h,
        )
        alpha = self._alpha(now_ms)
        overlay = pg.Surface(rect.size, pg.SRCALPHA)
        bg = pg.Color(Colors.dark_menu)
        bg.a = alpha
        pg.draw.rect(overlay, bg, overlay.get_rect(), border_radius=6)
        text_surf = fit_text_to_rect(text_surf, rect)
        text_surf.set_alpha(alpha)
        overlay.blit(
            text_surf,
            (rect.width // 2 - text_surf.get_width() // 2,
             rect.height // 2 - text_surf.get_height() // 2),
        )
        self.window.blit(overlay, rect.topleft)
