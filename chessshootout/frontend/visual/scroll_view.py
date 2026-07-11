import math

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

    def _store_scroll(self, value):
        self._scroll_px = value

    @property
    def scroll_offset(self):
        return self._scroll_px

    def handle_scroll(self, pos, dy):
        if not self.is_visible():
            return False
        return self.scroll.handle_wheel(pos, dy)

    def handle_press(self, pos):
        if not self.is_visible():
            return False
        return self.scroll.handle_press(pos) is not None

    def handle_motion(self, pos):
        return self.scroll.handle_motion(pos)

    def handle_release(self, pos):
        return self.scroll.handle_release()


class ScrollView:

    def __init__(self, get_offset_px, set_offset_px, get_metrics, *, wheel_step_px):
        self._get = get_offset_px
        self._set = set_offset_px
        self._metrics = get_metrics
        self._wheel_step_px = wheel_step_px
        self.last_activity_ms = 0
        self._grab = None
        self._thumb = None
        self._vel = 0.0
        self._flinging = False
        self._fling_px = 0.0
        self._fling_last_ms = 0

    def _now(self, now_ms):
        return pg.time.get_ticks() if now_ms is None else now_ms

    def _wheel_step(self):
        step = self._wheel_step_px
        return step() if callable(step) else step

    def _max_px(self):
        viewport, content_px = self._metrics()
        return max(0.0, content_px - viewport.height)

    def _clamp(self, px):
        return max(0.0, min(px, self._max_px()))

    def scrollable(self):
        return self._max_px() > 0

    def offset_fraction(self):
        m = self._max_px()
        return (self._get() / m) if m else 0.0

    def row_window(self, viewport, row_h):
        offset = self._get()
        first = int(offset // row_h)
        sub = offset - first * row_h
        n_draw = int((viewport.height + sub) // row_h) + 1
        return first, sub, n_draw

    def is_active(self):
        return self._flinging or self._grab is not None or self._thumb is not None

    def thumb_rect(self):
        viewport, content_px = self._metrics()
        rect = scroll_thumb_rect(viewport, content_px, viewport.height, self.offset_fraction())
        if rect is None:
            return None
        return rect.inflate(THUMB_HIT_PAD_X, 0)

    def draw_thumb(self, window):
        viewport, content_px = self._metrics()
        draw_scroll_thumb(window, viewport, content_px, viewport.height,
                          self.offset_fraction(), self.last_activity_ms)

    def _stop_fling(self):
        self._flinging = False
        self._vel = 0.0

    def cancel(self):
        self._grab = None
        self._thumb = None
        self._stop_fling()

    def handle_wheel(self, pos, notches):
        viewport, _ = self._metrics()
        if not viewport.collidepoint(pos) or self._max_px() == 0:
            return False
        self._stop_fling()
        self._set(self._clamp(self._get() - notches * self._wheel_step()))
        self.last_activity_ms = self._now(None)
        return True

    def handle_press(self, pos, now_ms=None):
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

    def handle_motion(self, pos, now_ms=None):
        if self._thumb is not None:
            self._drag_thumb(pos, now_ms)
            return True
        if self._grab is not None:
            self._drag_content(pos, now_ms)
            return True
        return False

    def _drag_thumb(self, pos, now_ms):
        viewport, content_px = self._metrics()
        m = self._max_px()
        thumb = scroll_thumb_rect(viewport, content_px, viewport.height, self.offset_fraction())
        travel = (viewport.height - thumb.height) if thumb is not None else 0
        if travel <= 0 or m == 0:
            return
        dy = pos[1] - self._thumb["grab_y"]
        self._set(self._clamp(self._thumb["grab_off"] + (dy / travel) * m))
        self.last_activity_ms = self._now(now_ms)

    def _drag_content(self, pos, now_ms):
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

    def handle_release(self, now_ms=None):
        if self._thumb is not None:
            self._thumb = None
            return True
        if self._grab is not None:
            moved = self._grab["moved"]
            self._grab = None
            if moved and abs(self._vel) >= FLING_MIN_VELOCITY:
                self._flinging = True
                self._fling_px = float(self._get())
                self._fling_last_ms = self._now(now_ms)
                self._vel = max(-FLING_MAX_VELOCITY, min(self._vel, FLING_MAX_VELOCITY))
            return moved
        return False

    def tick(self, now_ms=None):
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
