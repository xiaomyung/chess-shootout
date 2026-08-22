import math
from collections.abc import Callable
from typing import Any, cast

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
    """
    The stack of short status messages the app drops in at the top of the
    window -- a game saved, time given, a rematch withdrawn, an online hiccup.
    Every screen reports through the single shared instance, which dedupes by
    key, stacks newest on top and fades each message out on its own timer
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build the shared toast stack the app shell hands to every screen. It
        starts empty; the shell sets the top inset and the arrival sound right
        afterwards

        :param window: surface the bubbles are drawn on, the app window
        """
        self.window = window
        self.top_inset = 0
        self.font = get_font(16, bold=True)
        self._bubbles: list[dict[str, Any]] = []
        self._last_ms = 0
        self.on_new: Callable[[], None] | None = None

    def show(self, message: str, duration_ms: int | None = None, kind: str = "info",
             key: str | None = None) -> None:
        """
        Tell the player something. A message shown under a key already on
        screen refreshes that bubble and restarts its timer instead of
        stacking a second copy, which is how a repeating warning stays one
        line. Durations are floored, so nothing flashes past too fast to read

        :param message: text shown in the bubble
        :param duration_ms: hold time in milliseconds, raised to the minimum,
            or None for the default hold
        :param kind: info for the plain look, hype for the accent-filled one
        :param key: identity used for deduping and for dismissing later,
            defaulting to the message itself
        """
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

    def _top(self, now: int | None = None) -> dict[str, Any] | None:
        """
        The bubble a caller means when it asks what is showing: the newest one
        still inside its lifetime

        :param now: pygame tick count in milliseconds, or None to read the
            clock
        :returns: the newest live bubble, or None when nothing is showing
        """
        if now is None:
            now = pg.time.get_ticks()
        for b in reversed(self._bubbles):
            if self._active(b, now):
                return b
        return None

    @property
    def message(self) -> str | None:
        """
        The text on screen right now, the simple read screens and tests use to
        see what the player was last told

        :returns: the newest live message, or None when nothing is showing
        """
        top = self._top()
        return top["message"] if top is not None else None

    def dismiss(self, key: str) -> None:
        """
        Take one message away early, used when what it reported is over -- a
        failed save that has since succeeded, for instance

        :param key: key the message was shown under; unknown keys do nothing
        """
        self._bubbles = [b for b in self._bubbles if b["key"] != key]

    def hide(self) -> None:
        """
        Clear every message at once, the hard reset for when nothing on screen
        should carry into what comes next
        """
        self._bubbles = []

    def _active(self, b: dict[str, Any], now: int) -> bool:
        """
        Whether a bubble is still inside its hold plus its fade -- the one
        liveness test that drawing, reaping and is_visible all share

        :param b: the bubble record
        :param now: pygame tick count in milliseconds
        :returns: True while the bubble still belongs on screen
        """
        return cast(bool, now - b["shown_at_ms"] < b["duration_ms"] + FADE_OUT_MS)

    def is_visible(self, now_ms: int | None = None) -> bool:
        """
        Whether anything is showing, which the shell reads to know it must
        keep drawing frames while a message is still fading

        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        :returns: True while at least one bubble is alive
        """
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        return any(self._active(b, now_ms) for b in self._bubbles)

    def _alpha(self, b: dict[str, Any], now: int) -> int:
        """
        Work out how solid a bubble is at this moment: it fades in when it
        arrives and back out as it expires, and never brightens again

        :param b: the bubble record
        :param now: pygame tick count in milliseconds
        :returns: alpha from 0 fully clear to 255 fully solid
        """
        age = now - b["enter_at_ms"]
        remaining = b["duration_ms"] - (now - b["shown_at_ms"])
        fade_in = 255 if age >= ENTER_MS else int(255 * max(0, age) / ENTER_MS)
        fade_out = 255 if remaining >= 0 else max(
            0, int(255 * (FADE_OUT_MS + remaining) / FADE_OUT_MS))
        return max(0, min(fade_in, fade_out))

    def _render_bubble(self, b: dict[str, Any], now: int) -> pg.Surface:
        """
        Get a bubble's picture ready for this frame, drawing it once and then
        only changing its alpha, so a message on screen costs almost nothing
        per frame

        :param b: the bubble record; its cached picture is filled in here
        :param now: pygame tick count in milliseconds
        :returns: the bubble surface with this frame's alpha applied
        """
        if b.get("overlay") is None:
            b["overlay"] = self._build_bubble_overlay(b)
        overlay: pg.Surface = b["overlay"]
        overlay.set_alpha(self._alpha(b, now))
        return overlay

    def _build_bubble_overlay(self, b: dict[str, Any]) -> pg.Surface:
        """
        Draw one bubble: the cut-corner panel with its text, plus the leading
        dot and the shouted upper-case treatment that mark a hype message out
        from an ordinary one

        :param b: the bubble record to render
        :returns: the finished bubble surface, ready to be alpha-faded
        """
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

    def draw(self, now_ms: int | None = None, center_x: int | None = None) -> None:
        """
        Drop expired bubbles and paint the rest, newest at the top, each one
        easing toward its slot so a message leaving does not make the others
        jump. On the game screen the stack is centered over the board instead
        of over the window, which keeps it clear of the side panel

        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        :param center_x: window x the stack is centered on, or None for the
            middle of the window
        """
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
