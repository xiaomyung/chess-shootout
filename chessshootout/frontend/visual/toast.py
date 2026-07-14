import math

import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.fonts import get_font


MIN_DURATION_MS = 3000
DEFAULT_DURATION_MS = MIN_DURATION_MS
FADE_OUT_MS = 300
ENTER_MS = 200
TOP_OFFSET_PX = 12
STACK_GAP_PX = 8
PADDING_X = 16
PADDING_Y = 8
SPARK_GAP_PX = 6
SETTLE_TAU_MS = 70
MAX_FRAME_DT_MS = 100


class Toast:

    def __init__(self, window):
        self.window = window
        self.top_inset = 0
        self.font = get_font(16, bold=True)
        self._bubbles = []
        self._last_ms = 0
        self.on_new = None

    def show(self, message, duration_ms=None, kind="info", key=None):
        now = pg.time.get_ticks()
        duration = max(duration_ms or DEFAULT_DURATION_MS, MIN_DURATION_MS)
        if key is None:
            key = message
        for b in self._bubbles:
            if b["key"] == key:
                if b["message"] != message or b["kind"] != kind:
                    b["overlay"] = None
                b["message"] = message
                b["kind"] = kind
                b["shown_at_ms"] = now
                b["duration_ms"] = duration
                return
        self._bubbles.append({
            "message": message, "kind": kind, "key": key,
            "enter_at_ms": now, "shown_at_ms": now, "duration_ms": duration, "y": None,
        })
        if self.on_new is not None:
            self.on_new()

    def _top(self, now=None):
        if now is None:
            now = pg.time.get_ticks()
        for b in reversed(self._bubbles):
            if self._active(b, now):
                return b
        return None

    @property
    def message(self):
        top = self._top()
        return top["message"] if top is not None else None

    def dismiss(self, key):
        self._bubbles = [b for b in self._bubbles if b["key"] != key]

    def hide(self):
        self._bubbles = []

    def _active(self, b, now):
        return now - b["shown_at_ms"] < b["duration_ms"] + FADE_OUT_MS

    def is_visible(self, now_ms=None):
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        return any(self._active(b, now_ms) for b in self._bubbles)

    def _alpha(self, b, now):
        age = now - b["enter_at_ms"]
        remaining = b["duration_ms"] - (now - b["shown_at_ms"])
        fade_in = 255 if age >= ENTER_MS else int(255 * max(0, age) / ENTER_MS)
        if remaining >= 0:
            fade_out = 255
        else:
            fade_out = max(0, int(255 * (FADE_OUT_MS + remaining) / FADE_OUT_MS))
        return max(0, min(fade_in, fade_out))

    def _render_bubble(self, b, now):
        if b.get("overlay") is None:
            b["overlay"] = self._build_bubble_overlay(b)
        overlay = b["overlay"]
        overlay.set_alpha(self._alpha(b, now))
        return overlay

    def _build_bubble_overlay(self, b):
        hype = b["kind"] == "hype"
        label = b["message"].upper() if hype else b["message"]
        text_color = Colors.on_accent if hype else Colors.text_dim
        bg_color = pg.Color(Colors.accent if hype else Colors.surface)
        border_color = pg.Color(Colors.accent_hi if hype else Colors.border)
        text_surf = self.font.render(label, True, text_color)
        spark_d = text_surf.get_height() // 2 if hype else 0
        spark_gap = spark_d + SPARK_GAP_PX if hype else 0
        w = text_surf.get_width() + 2 * PADDING_X + spark_gap
        h = text_surf.get_height() + 2 * PADDING_Y
        cut = max(int(h * 0.28), 4)
        overlay = pg.Surface((w, h), pg.SRCALPHA)
        shape = cut_rect_surface((w, h), cut, bg_color, border=border_color,
                                 border_width=1, corners=("tr", "bl"))
        overlay.blit(shape, (0, 0))
        if hype:
            spark = pg.Color(Colors.on_accent)
            pg.draw.circle(overlay, spark, (PADDING_X + spark_d // 2, h // 2), spark_d // 2)
        overlay.blit(text_surf, (PADDING_X + spark_gap, h // 2 - text_surf.get_height() // 2))
        return overlay

    def draw(self, now_ms=None, center_x=None):
        now = pg.time.get_ticks() if now_ms is None else now_ms
        self._bubbles = [b for b in self._bubbles if self._active(b, now)]
        if not self._bubbles:
            self._last_ms = now
            return
        dt = min(MAX_FRAME_DT_MS, max(0, now - self._last_ms))
        self._last_ms = now
        smooth = 1.0 - math.exp(-dt / SETTLE_TAU_MS) if dt > 0 else 0.0
        cx = self.window.get_width() / 2 if center_x is None else center_x
        y_cursor = self.top_inset + TOP_OFFSET_PX
        for b in reversed(self._bubbles):
            surf = self._render_bubble(b, now)
            target_y = y_cursor
            if b["y"] is None:
                b["y"] = float(target_y - surf.get_height())
            b["y"] += (target_y - b["y"]) * smooth
            x = int(cx - surf.get_width() / 2)
            x = max(0, min(x, self.window.get_width() - surf.get_width()))
            self.window.blit(surf, (x, int(b["y"])))
            y_cursor += surf.get_height() + STACK_GAP_PX
