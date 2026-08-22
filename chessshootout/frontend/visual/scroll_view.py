import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pygame as pg

from chessshootout.frontend.visual.widgets import draw_scroll_thumb, scroll_thumb_rect


SCROLL_DRAG_THRESHOLD_PX = 6
FLING_MIN_VELOCITY = 60.0
FLING_FRICTION_TAU = 0.32
FLING_STOP_VELOCITY = 8.0
FLING_MAX_VELOCITY = 4000.0
VELOCITY_EMA_ALPHA = 0.35
FLING_MAX_DT = 0.05
THUMB_HIT_PAD_X = 10


class ScrollHost:
    """
    Mixin that turns a widget owning a ScrollView into the scrollable the app
    shell asks a screen for. It supplies the whole duck type the input router
    drives -- handle_scroll, handle_press, handle_motion, handle_release and
    is_visible -- while the widget itself provides the `scroll` view, the
    `_scroll_px` offset, `is_visible` and its own `handle_click`
    """

    if TYPE_CHECKING:
        scroll: "ScrollView"

        def is_visible(self) -> bool:
            """
            Supplied by the host widget: whether it is on screen at all, which
            is what lets a hidden list leave the wheel and the press alone

            :returns: True while the host widget is showing
            """
            ...

    def _store_scroll(self, value: float) -> None:
        """
        Take a new offset from the view; hosts pass this in as the setter when
        they build their ScrollView, so the offset lives on the widget

        :param value: new offset in pixels down from the top of the content
        """
        self._scroll_px = value

    @property
    def scroll_offset(self) -> float:
        """
        How far this list is scrolled right now, which its drawing code
        subtracts from every row's y to place it

        :returns: pixels scrolled down from the top of the content
        """
        return self._scroll_px

    def handle_scroll(self, pos: tuple[int, int], dy: int) -> bool:
        """
        Take a mouse-wheel notch over this widget. A widget that is not on
        screen ignores it, so a collapsed card never eats the wheel

        :param pos: cursor position in window pixels
        :param dy: wheel notches, positive scrolling back toward the start
        :returns: True when the wheel moved this widget
        """
        if not self.is_visible():
            return False
        return self.scroll.handle_wheel(pos, dy)

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Begin a drag on the content or on the scrollbar thumb. Answering True
        makes the router route the rest of the gesture here, so the screen
        underneath never sees a scroll drag

        :param pos: press position in window pixels
        :returns: True when the press started a scroll gesture
        """
        if not self.is_visible():
            return False
        return self.scroll.handle_press(pos) is not None

    def handle_motion(self, pos: tuple[int, int]) -> bool:
        """
        Carry on the drag this widget claimed, moving content or thumb with
        the cursor

        :param pos: cursor position in window pixels
        :returns: True while one of our gestures is in flight
        """
        return self.scroll.handle_motion(pos)

    def handle_release(self, pos: tuple[int, int]) -> bool:
        """
        Finish the drag and let a quick flick coast on. Answering False tells
        the router the gesture was really a tap, which it then delivers to
        this widget as a click instead

        :param pos: release position in window pixels, not needed here since
            the view tracks the drag itself
        :returns: True when the gesture actually scrolled
        """
        return self.scroll.handle_release()


class ScrollView:
    """
    The single scrolling engine behind every list in the app -- options rows,
    saved games, the move list, news, the country picker. It owns wheel
    stepping, grab-and-pull content dragging with a kinetic fling, and
    scrollbar-thumb dragging, reading and writing the host's offset through
    the callbacks it was built with rather than storing layout of its own
    """

    def __init__(self, get_offset_px: Callable[[], float],
                 set_offset_px: Callable[[float], None],
                 get_metrics: Callable[[], tuple[pg.Rect, float]], *,
                 wheel_step_px: float | Callable[[], float]) -> None:
        """
        Wire the view to whoever owns the scroll offset and the layout. It
        keeps no copy of either, so a host that relays out mid-gesture stays
        consistent instead of scrolling against stale numbers

        :param get_offset_px: reads the host's current offset in pixels
        :param set_offset_px: writes a clamped offset back to the host
        :param get_metrics: reads the viewport rect and the full content
            height in pixels
        :param wheel_step_px: pixels moved per wheel notch, or a callable read
            each time for hosts whose row height follows the window size
        """
        self._get = get_offset_px
        self._set = set_offset_px
        self._metrics = get_metrics
        self._wheel_step_px = wheel_step_px
        self.last_activity_ms = 0
        self._grab: Any = None
        self._thumb: Any = None
        self._vel = 0.0
        self._flinging = False
        self._fling_px = 0.0
        self._fling_last_ms = 0

    def _now(self, now_ms: int | None) -> int:
        """
        Settle which clock reading to work from, so callers may inject one and
        the tests can drive a whole fling on a scripted timeline

        :param now_ms: caller-supplied pygame tick count in milliseconds, or
            None to read the real clock
        :returns: the millisecond timestamp to use for this step
        """
        return pg.time.get_ticks() if now_ms is None else now_ms

    def _wheel_step(self) -> float:
        """
        Settle how far one wheel notch scrolls, asking the host's provider
        when the step depends on the current layout

        :returns: pixels to move per wheel notch
        """
        step = self._wheel_step_px
        return step() if callable(step) else step

    def _max_px(self) -> float:
        """
        How far this list can travel at all -- the content that sticks out
        past the viewport. Zero means everything fits and no gesture may move
        anything

        :returns: the largest valid offset, in pixels
        """
        viewport, content_px = self._metrics()
        return max(0.0, content_px - viewport.height)

    def _clamp(self, px: float) -> float:
        """
        Hold an offset inside the scrollable range. Every write back to the
        host goes through here, so no gesture can push content past its ends

        :param px: proposed offset in pixels
        :returns: that offset clamped into the valid range
        """
        return max(0.0, min(px, self._max_px()))

    def scrollable(self) -> bool:
        """
        Whether the content is taller than its viewport, which is what a host
        asks before offering any scroll affordance

        :returns: True when there is something to scroll
        """
        return self._max_px() > 0

    def offset_fraction(self) -> float:
        """
        Where the view sits between the start and the end of its content,
        which is what places the scrollbar thumb along its track

        :returns: 0.0 at the top through 1.0 at the bottom, 0.0 when nothing
            can scroll
        """
        m = self._max_px()
        return (self._get() / m) if m else 0.0

    def row_window(self, viewport: pg.Rect, row_h: int) -> tuple[int, float, int]:
        """
        Work out which rows of an evenly spaced list are on screen, so a long
        list draws only its visible slice instead of every row it holds

        :param viewport: the visible box of the list
        :param row_h: height of one row in pixels
        :returns: index of the first visible row, how many pixels of that row
            are scrolled off the top, and how many rows to draw
        """
        offset = self._get()
        first = int(offset // row_h)
        sub = offset - first * row_h
        n_draw = int((viewport.height + sub) // row_h) + 1
        return first, sub, n_draw

    def is_active(self) -> bool:
        """
        Whether a gesture or a fling is still running, which the shell reads
        to know it must keep drawing frames rather than idling

        :returns: True while dragging, thumb-dragging or coasting
        """
        return self._flinging or self._grab is not None or self._thumb is not None

    def thumb_rect(self) -> pg.Rect | None:
        """
        The scrollbar thumb's hit box, widened sideways so the thin visible
        thumb is still comfortable to grab with a mouse

        :returns: the padded thumb rect, or None when nothing can scroll
        """
        viewport, content_px = self._metrics()
        rect = scroll_thumb_rect(viewport, content_px, viewport.height, self.offset_fraction())
        if rect is None:
            return None
        return rect.inflate(THUMB_HIT_PAD_X, 0)

    def draw_thumb(self, window: pg.Surface) -> None:
        """
        Draw this list's scrollbar, which fades itself out a couple of seconds
        after the last scroll so a settled panel stays clean

        :param window: surface drawn to, normally the app window
        """
        viewport, content_px = self._metrics()
        draw_scroll_thumb(window, viewport, content_px, viewport.height,
                          self.offset_fraction(), self.last_activity_ms)

    def _stop_fling(self) -> None:
        """
        End any coasting motion and forget the speed behind it
        """
        self._flinging = False
        self._vel = 0.0

    def cancel(self) -> None:
        """
        Drop every gesture at once -- content drag, thumb drag and fling. The
        shell calls it on a window resize and hosts call it when their content
        is replaced, so no stale drag survives into a new layout
        """
        self._grab = None
        self._thumb = None
        self._stop_fling()

    def handle_wheel(self, pos: tuple[int, int], notches: int) -> bool:
        """
        Scroll by wheel while the cursor is over this list. A wheel notch also
        kills a fling that was still coasting, so the wheel always wins over
        leftover momentum

        :param pos: cursor position in window pixels
        :param notches: wheel notches, positive scrolling back toward the start
        :returns: True when this list took the wheel event
        """
        viewport, _ = self._metrics()
        if not viewport.collidepoint(pos) or self._max_px() == 0:
            return False
        self._stop_fling()
        self._set(self._clamp(self._get() - notches * self._wheel_step()))
        self.last_activity_ms = self._now(None)
        return True

    def handle_press(self, pos: tuple[int, int], now_ms: int | None = None) -> str | None:
        """
        Start a scroll gesture: a press on the thumb becomes a thumb drag,
        anywhere else inside the viewport becomes a content drag that only
        counts as scrolling once it passes the click threshold, which is what
        keeps a tap on a list row a tap

        :param pos: press position in window pixels
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock; the tests inject it to script a fling
        :returns: which gesture began, thumb or content, or None when the
            press does not belong to this list
        """
        if self._max_px() == 0:
            return None
        self._stop_fling()
        thumb = self.thumb_rect()
        if thumb is not None and thumb.collidepoint(pos):
            self._thumb = {"grab_y": pos[1], "grab_off": float(self._get())}
            self.last_activity_ms = self._now(now_ms)
            return "thumb"
        viewport, _ = self._metrics()
        if viewport.collidepoint(pos):
            now = self._now(now_ms)
            self._grab = {"start": pos, "last": pos, "moved": False,
                          "px": float(self._get()), "last_ms": now, "vsampled": False}
            self._vel = 0.0
            return "content"
        return None

    def handle_motion(self, pos: tuple[int, int], now_ms: int | None = None) -> bool:
        """
        Move whichever gesture is in flight and keep sampling the speed that a
        release may turn into a fling

        :param pos: cursor position in window pixels
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        :returns: True while a gesture of this list's is in flight
        """
        if self._thumb is not None:
            self._drag_thumb(pos, now_ms)
            return True
        if self._grab is not None:
            self._drag_content(pos, now_ms)
            return True
        return False

    def _drag_thumb(self, pos: tuple[int, int], now_ms: int | None) -> None:
        """
        Drag the scrollbar thumb, mapping how far it moved along its track
        onto the whole scrollable range so the content keeps up with it

        :param pos: cursor position in window pixels
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        """
        viewport, content_px = self._metrics()
        m = self._max_px()
        thumb = scroll_thumb_rect(viewport, content_px, viewport.height, self.offset_fraction())
        travel = (viewport.height - thumb.height) if thumb is not None else 0
        if travel <= 0 or m == 0:
            return
        dy = pos[1] - self._thumb["grab_y"]
        self._set(self._clamp(self._thumb["grab_off"] + (dy / travel) * m))
        self.last_activity_ms = self._now(now_ms)

    def _drag_content(self, pos: tuple[int, int], now_ms: int | None) -> None:
        """
        Drag the content itself -- the grab-and-pull gesture. The list follows
        the cursor one for one once the press has moved past the click
        threshold, and the running speed is smoothed as it goes so a release
        has a stable velocity to fling with

        :param pos: cursor position in window pixels
        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        """
        now = self._now(now_ms)
        sy = self._grab["start"][1]
        if not self._grab["moved"]:
            dx = pos[0] - self._grab["start"][0]
            dy = pos[1] - sy
            if dx * dx + dy * dy < SCROLL_DRAG_THRESHOLD_PX * SCROLL_DRAG_THRESHOLD_PX:
                return
            self._grab["moved"] = True
            self._grab["last"] = pos
            self._grab["last_ms"] = now
        dt = (now - self._grab["last_ms"]) / 1000.0
        if dt > 0 and pos[1] != self._grab["last"][1]:
            inst = -(pos[1] - self._grab["last"][1]) / dt
            if self._grab["vsampled"]:
                self._vel += (inst - self._vel) * VELOCITY_EMA_ALPHA
            else:
                self._vel = inst
                self._grab["vsampled"] = True
        self._set(self._clamp(self._grab["px"] - (pos[1] - sy)))
        self._grab["last"] = pos
        self._grab["last_ms"] = now
        self.last_activity_ms = now

    def handle_release(self, now_ms: int | None = None) -> bool:
        """
        End the gesture. A content drag let go while still moving launches a
        fling; a thumb drag never coasts; and a press that never passed the
        click threshold reports False, which is how the host knows to treat it
        as a click on whatever was under the cursor

        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        :returns: True when the gesture scrolled rather than being a tap
        """
        if self._thumb is not None:
            self._thumb = None
            return True
        if self._grab is not None:
            moved: bool = self._grab["moved"]
            self._grab = None
            if moved and abs(self._vel) >= FLING_MIN_VELOCITY:
                self._flinging = True
                self._fling_px = float(self._get())
                self._fling_last_ms = self._now(now_ms)
                self._vel = max(-FLING_MAX_VELOCITY, min(self._vel, FLING_MAX_VELOCITY))
            return moved
        return False

    def tick(self, now_ms: int | None = None) -> None:
        """
        Advance a fling by one frame -- the coasting a list keeps doing after
        the cursor has let go. Hosts call it on every frame they draw; friction
        eats the speed, and reaching either end stops the motion dead instead
        of bouncing

        :param now_ms: pygame tick count in milliseconds, or None to read the
            clock
        """
        if not self._flinging:
            return
        now = self._now(now_ms)
        dt = (now - self._fling_last_ms) / 1000.0
        self._fling_last_ms = now
        if dt <= 0:
            return
        dt = min(dt, FLING_MAX_DT)
        target = self._fling_px + self._vel * dt
        clamped = self._clamp(target)
        self._fling_px = clamped
        self._set(clamped)
        self.last_activity_ms = now
        if clamped != target:
            self._stop_fling()
            return
        self._vel *= math.exp(-dt / FLING_FRICTION_TAU)
        if abs(self._vel) < FLING_STOP_VELOCITY:
            self._stop_fling()
