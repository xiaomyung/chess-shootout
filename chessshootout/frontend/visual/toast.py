import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font


DEFAULT_DURATION_MS = 1800
FADE_OUT_MS = 250
TOP_OFFSET_PX = 12
PADDING_X = 16
PADDING_Y = 8
SPARK_GAP_PX = 6


class Toast:

    def __init__(self, window):
        self.window = window
        self.message = None
        self.kind = "info"
        self.top_inset = 0
        self._shown_at_ms = 0
        self.duration_ms = DEFAULT_DURATION_MS
        self.font = get_font(16, bold=True)

    def show(self, message, duration_ms=None, kind="info"):
        self.message = message
        self.kind = kind
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
        hype = self.kind == "hype"
        label = self.message.upper() if hype else self.message
        text_color = Colors.on_accent if hype else Colors.text_dim
        bg_color = pg.Color(Colors.accent if hype else Colors.surface)
        border_color = pg.Color(Colors.accent_hi if hype else Colors.border)
        text_surf = self.font.render(label, True, text_color)
        spark_d = text_surf.get_height() // 2 if hype else 0
        spark_gap = spark_d + SPARK_GAP_PX if hype else 0
        toast_w = text_surf.get_width() + 2 * PADDING_X + spark_gap
        toast_h = text_surf.get_height() + 2 * PADDING_Y
        radius = toast_h // 2
        win_w = self.window.get_width()
        rect = pg.Rect((win_w - toast_w) // 2, self.top_inset + TOP_OFFSET_PX, toast_w, toast_h)
        alpha = self._alpha(now_ms)
        overlay = pg.Surface(rect.size, pg.SRCALPHA)
        bg_color.a = alpha
        border_color.a = alpha
        pg.draw.rect(overlay, bg_color, overlay.get_rect(), border_radius=radius)
        pg.draw.rect(overlay, border_color, overlay.get_rect(), 1, border_radius=radius)
        text_surf.set_alpha(alpha)
        text_x = PADDING_X + spark_gap
        if hype:
            spark = pg.Color(Colors.on_accent)
            spark.a = alpha
            pg.draw.circle(overlay, spark, (PADDING_X + spark_d // 2, toast_h // 2), spark_d // 2)
        overlay.blit(text_surf, (text_x, rect.height // 2 - text_surf.get_height() // 2))
        self.window.blit(overlay, rect.topleft)
