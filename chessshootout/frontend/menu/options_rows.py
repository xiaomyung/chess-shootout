import pygame as pg

from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    cut_rect_surface, infinity_surface, notch_geometry, notch_value_from_click,
    notch_readout_slot_w,
)
from chessshootout.frontend.visual.fonts import get_mono_font
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import draw_toggle


CARD_CUT = 8
CARD_PAD_X = 16
ROW_PAD_Y = 13
LABEL_DESC_GAP = 3
CONTROL_GAP = 18
SECTION_LABEL_GAP = 9
SECTION_GAP = 18
SCROLLBAR_RESERVE = 14
OPTIONS_WHEEL_STEP = 30

TOGGLE_W = 46
TOGGLE_H = 24
TOGGLE_HIT_PAD_X = 16
TOGGLE_HIT_PAD_Y = 14
TOGGLE_SNAP_EPS = 0.02
TOGGLE_LERP = 0.3

NOTCH_COUNT = 10
NOTCH_CELL_W = 13
NOTCH_CELL_H = 22
NOTCH_GAP = 4
NOTCH_CELL_CUT = 3
NOTCH_READOUT_GAP = 12
NOTCH_HIT_PAD_X = 14
NOTCH_HIT_PAD_Y = 16

SEG_MIN_H = 30
SEG_PAD_X = 14
SEG_GAP = 8
SEG_CUT = 6
CELL_GAP = 6
CELL_CUT = 5
CELL_PAD_X = 10

FIELD_H = 34
BTN_PAD_X = 14
BTN_GAP = 8
RESET_PAD_X = 10
FIELD_LEFT_FRAC = 0.40

REVEAL_LERP = 0.24
REVEAL_SNAP_EPS = 0.01

ACTION_STATUS_GAP = 12
ACTION_MIN_LABEL_W = 120

_STATUS_TONES = {"ok": Colors.win, "warn": Colors.loss, "idle": Colors.text_muted}


class Fonts:
    __slots__ = ("title", "desc", "section", "value", "button")

    def __init__(self, title, desc, section, value, button):
        self.title = title
        self.desc = desc
        self.section = section
        self.value = value
        self.button = button


def _blit_clip(window, surf, pos, max_w):
    if surf.get_width() > max_w > 0:
        surf = surf.subsurface(pg.Rect(0, 0, int(max_w), surf.get_height()))
    window.blit(surf, pos)


def _fitting_ellipsis(font):
    metrics = font.metrics(chr(0x2026))
    if not metrics or metrics[0] is None or metrics == font.metrics(chr(0xE000)):
        return "..."
    return "…"


def _elide_left(font, text, max_w):
    if font.size(text)[0] <= max_w:
        return text
    ell = _fitting_ellipsis(font)
    budget = max(max_w - font.size(ell)[0], 0)
    while text and font.size(text)[0] > budget:
        text = text[1:]
    return ell + text


def _seg_glyph(font, label, color):
    if label == "∞":
        return infinity_surface(int(font.get_height() * 0.82), color)
    return render_text(font, label, color)


class _Row:

    def __init__(self, title, desc=""):
        self.title = title
        self.desc = desc

    def tick(self):
        pass

    def animating(self):
        return False

    def _control_h(self, fonts):
        return 0

    def _label_h(self, fonts):
        h = fonts.title.get_height()
        if self.desc:
            h += fonts.desc.get_height() + LABEL_DESC_GAP
        return h

    def height(self, fonts):
        return 2 * ROW_PAD_Y + max(self._label_h(fonts), self._control_h(fonts))

    def full_height(self, fonts):
        return self.height(fonts)

    def draw(self, window, rect, fonts):
        control_left = self._draw_control(window, rect, fonts)
        self._draw_label(window, rect, fonts, control_left - CONTROL_GAP)

    def _draw_label(self, window, rect, fonts, max_right):
        x = rect.x
        avail = max(max_right - x, 1)
        y = rect.centery - self._label_h(fonts) // 2
        _blit_clip(window, render_text(fonts.title, self.title, Colors.text), (x, y), avail)
        if self.desc:
            _blit_clip(window, render_text(fonts.desc, self.desc, Colors.text_muted),
                       (x, y + fonts.title.get_height() + LABEL_DESC_GAP), avail)

    def _draw_control(self, window, rect, fonts):
        return rect.right

    def handle_click(self, pos):
        return False

    def contains_control(self, pos):
        return False

    def handle_key(self, event):
        return False

    def cancel_edit(self):
        return False


class ToggleRow(_Row):

    def __init__(self, title, desc, getter, setter):
        super().__init__(title, desc)
        self.getter = getter
        self.setter = setter
        self._ctl = pg.Rect(0, 0, 0, 0)
        self._pos = None

    def _control_h(self, fonts):
        return TOGGLE_H

    def _draw_control(self, window, rect, fonts):
        self._ctl = pg.Rect(rect.right - TOGGLE_W, rect.centery - TOGGLE_H // 2,
                            TOGGLE_W, TOGGLE_H)
        target = 1.0 if self.getter() else 0.0
        if self._pos is None or abs(self._pos - target) < TOGGLE_SNAP_EPS:
            self._pos = target
        else:
            self._pos += (target - self._pos) * TOGGLE_LERP
        draw_toggle(window, self._ctl, self._pos)
        return self._ctl.x

    def handle_click(self, pos):
        if self.contains_control(pos):
            self.setter(not self.getter())
            return True
        return False

    def contains_control(self, pos):
        return self._ctl.inflate(TOGGLE_HIT_PAD_X, TOGGLE_HIT_PAD_Y).collidepoint(pos)


class NotchRow(_Row):

    def __init__(self, title, desc, getter, setter, on_tick=None, on_release=None):
        super().__init__(title, desc)
        self.getter = getter
        self.setter = setter
        self.on_tick = on_tick
        self.on_release = on_release
        self._band = pg.Rect(0, 0, 0, 0)

    def _control_h(self, fonts):
        return max(NOTCH_CELL_H, fonts.value.get_height())

    def _draw_control(self, window, rect, fonts):
        value = max(0.0, min(1.0, self.getter()))
        readout = render_text(fonts.value, f"{int(round(value * 100))}%", Colors.text_dim)
        slot_w = notch_readout_slot_w(fonts.value)
        window.blit(readout, (rect.right - readout.get_width(),
                              rect.centery - readout.get_height() // 2))
        x0, total_w = notch_geometry(rect.width, NOTCH_COUNT, NOTCH_CELL_W, NOTCH_GAP,
                                     slot_w, NOTCH_READOUT_GAP)
        cx = rect.x + x0
        cy = rect.centery - NOTCH_CELL_H // 2
        filled = int(round(value * NOTCH_COUNT))
        for i in range(NOTCH_COUNT):
            cell = pg.Rect(cx + i * (NOTCH_CELL_W + NOTCH_GAP), cy, NOTCH_CELL_W, NOTCH_CELL_H)
            if i < filled:
                window.blit(cut_rect_surface(cell.size, NOTCH_CELL_CUT, Colors.accent,
                                             corners=("tr",)), cell.topleft)
            else:
                window.blit(cut_rect_surface(cell.size, NOTCH_CELL_CUT, Colors.surface_raised,
                                             border=Colors.border, border_width=1,
                                             corners=("tr",)), cell.topleft)
        self._band = pg.Rect(cx, cy, total_w, NOTCH_CELL_H)
        return cx

    def handle_click(self, pos):
        if not self.contains_control(pos):
            return False
        step = NOTCH_CELL_W + NOTCH_GAP
        target = notch_value_from_click(pos[0], self._band.x, step, NOTCH_COUNT,
                                        self.getter())
        self.setter(target)
        if self.on_tick is not None:
            self.on_tick()
        if self.on_release is not None:
            self.on_release()
        return True

    def contains_control(self, pos):
        return self._band.inflate(NOTCH_HIT_PAD_X, NOTCH_HIT_PAD_Y).collidepoint(pos)


class SegmentedRow(_Row):

    def __init__(self, title, desc, options, getter, setter, mono=False, variant="chips"):
        super().__init__(title, desc)
        self.options = options
        self.getter = getter
        self.setter = setter
        self.mono = mono
        self.variant = variant
        self._rects = {}
        self._mono_font = None
        self._layout_cache = None

    def _seg_h(self, fonts):
        return max(fonts.button.get_height() + 12, SEG_MIN_H)

    def _control_h(self, fonts):
        return self._seg_h(fonts)

    def _font(self, fonts):
        if not self.mono:
            return fonts.button
        size = max(int(fonts.button.get_height() * 0.9), 13)
        if self._mono_font is None or self._mono_font[0] != size:
            self._mono_font = (size, get_mono_font(size, bold=True))
        return self._mono_font[1]

    def _layout(self, font, h):
        key = (id(font), h)
        if self._layout_cache is not None and self._layout_cache[0] == key:
            return self._layout_cache[1]
        if self.variant == "cells":
            cell_w = max(h, max(_seg_glyph(font, label, Colors.text_dim).get_width()
                                for label, _ in self.options) + 2 * CELL_PAD_X)
            result = ([cell_w] * len(self.options), CELL_CUT, CELL_GAP)
        else:
            widths = [_seg_glyph(font, label, Colors.text_dim).get_width() + 2 * SEG_PAD_X
                      for label, _ in self.options]
            result = (widths, SEG_CUT, SEG_GAP)
        self._layout_cache = (key, result)
        return result

    def _draw_control(self, window, rect, fonts):
        font = self._font(fonts)
        h = self._seg_h(fonts)
        y = rect.centery - h // 2
        widths, cut, gap = self._layout(font, h)
        x = rect.right - (sum(widths) + gap * (len(widths) - 1))
        left = x
        self._rects = {}
        for (label, key), w in zip(self.options, widths):
            sr = pg.Rect(round(x), y, round(w), h)
            selected = key == self.getter()
            fill = Colors.surface_raised if selected else Colors.surface
            border = Colors.accent if selected else Colors.border
            color = Colors.text if selected else Colors.text_dim
            window.blit(cut_rect_surface(sr.size, cut, fill, border=border,
                                         border_width=1, corners=("tr",)), sr.topleft)
            glyph = _seg_glyph(font, label, color)
            window.blit(glyph, (sr.centerx - glyph.get_width() // 2,
                                sr.centery - glyph.get_height() // 2))
            self._rects[key] = sr
            x += w + gap
        return int(left)

    def handle_click(self, pos):
        for key, r in self._rects.items():
            if r.collidepoint(pos):
                self.setter(key)
                return True
        return False

    def contains_control(self, pos):
        return any(r.collidepoint(pos) for r in self._rects.values())


class PathRow(_Row):

    def __init__(self, label, desc, window, value_getter, on_change, on_reset, suffix=""):
        super().__init__(label, desc)
        self.value_getter = value_getter
        self.on_change = on_change
        self.on_reset = on_reset
        self.suffix = suffix
        self.input = TextInput(window, max_chars=512, placeholder="data folder path",
                               mono=True, bg=Colors.bg, radius=6, rest_align="end")
        self.input.padding = 10
        self.input.text = str(value_getter())
        self._change_rect = pg.Rect(0, 0, 0, 0)
        self._reset_rect = pg.Rect(0, 0, 0, 0)
        self._field_rect = pg.Rect(0, 0, 0, 0)
        self._rest_cache = None

    def _control_h(self, fonts):
        return FIELD_H

    def _draw_control(self, window, rect, fonts):
        y = rect.centery - FIELD_H // 2
        if not self.input.focused and self.input.text != str(self.value_getter()):
            self.input.text = str(self.value_getter())
        reset_surf = render_text(fonts.button, "Reset", Colors.text_dim)
        reset_w = reset_surf.get_width() + 2 * RESET_PAD_X
        self._reset_rect = pg.Rect(rect.right - reset_w, y, reset_w, FIELD_H)
        change_w = fonts.button.size("Change")[0] + 2 * BTN_PAD_X
        self._change_rect = pg.Rect(self._reset_rect.x - BTN_GAP - change_w, y,
                                    change_w, FIELD_H)
        field_left = rect.x + int(rect.width * FIELD_LEFT_FRAC)
        self._field_rect = pg.Rect(field_left, y,
                                   max(self._change_rect.x - BTN_GAP - field_left, 1), FIELD_H)
        self.input.set_rect(self._field_rect)
        self.input.font = fonts.value
        if self.input.focused:
            self.input.draw(window)
        else:
            self._draw_rest_path(window, fonts)
        window.blit(cut_rect_surface(self._change_rect.size, 6, Colors.surface_raised,
                                     border=Colors.border, border_width=1, corners=("tr",)),
                    self._change_rect.topleft)
        ct = render_text(fonts.button, "Change", Colors.text)
        window.blit(ct, (self._change_rect.centerx - ct.get_width() // 2,
                         self._change_rect.centery - ct.get_height() // 2))
        window.blit(reset_surf, (self._reset_rect.centerx - reset_surf.get_width() // 2,
                                 self._reset_rect.centery - reset_surf.get_height() // 2))
        return self._field_rect.x

    def _draw_rest_path(self, window, fonts):
        fr = self._field_rect
        suffix_surf = render_text(fonts.value, self.suffix, Colors.text_dim) \
            if self.suffix else None
        suffix_w = suffix_surf.get_width() if suffix_surf else 0
        avail = max(fr.width - suffix_w, 1)
        key = (id(fonts.value), self.input.text, avail)
        if self._rest_cache is None or self._rest_cache[0] != key:
            path_text = _elide_left(fonts.value, self.input.text, avail)
            self._rest_cache = (key, render_text(fonts.value, path_text, Colors.text_muted))
        path_surf = self._rest_cache[1]
        total = path_surf.get_width() + suffix_w
        prev = window.get_clip()
        window.set_clip(fr.clip(prev))
        x = fr.right - total
        window.blit(path_surf, (x, fr.centery - path_surf.get_height() // 2))
        if suffix_surf:
            window.blit(suffix_surf, (x + path_surf.get_width(),
                                      fr.centery - suffix_surf.get_height() // 2))
        window.set_clip(prev)

    def current_text(self):
        return self.input.text.strip()

    def handle_click(self, pos):
        if self._change_rect.collidepoint(pos):
            self.input.focused = False
            self.on_change()
            return True
        if self._reset_rect.collidepoint(pos):
            self.input.focused = False
            self.on_reset()
            return True
        if self._field_rect.collidepoint(pos):
            self.input.handle_click(pos)
            return True
        self.input.focused = False
        return False

    def contains_control(self, pos):
        return (self._change_rect.collidepoint(pos) or self._reset_rect.collidepoint(pos)
                or self._field_rect.collidepoint(pos))

    def handle_key(self, event):
        return self.input.handle_key(event)

    def cancel_edit(self):
        if not self.input.focused:
            return False
        self.input.focused = False
        self.input.text = str(self.value_getter())
        return True


class TextRow(_Row):

    def __init__(self, label, desc, window, value_getter, placeholder="", on_commit=None):
        super().__init__(label, desc)
        self.value_getter = value_getter
        self.on_commit = on_commit
        self.input = TextInput(window, max_chars=128, placeholder=placeholder,
                               mono=True, bg=Colors.bg, radius=6)
        self.input.padding = 11
        self.input.text = str(value_getter())
        self._edited = False
        self._field_rect = pg.Rect(0, 0, 0, 0)

    def _control_h(self, fonts):
        return FIELD_H

    def _draw_control(self, window, rect, fonts):
        y = rect.centery - FIELD_H // 2
        if not self.input.focused and not self._edited \
                and self.input.text != str(self.value_getter()):
            self.input.text = str(self.value_getter())
        field_left = rect.x + int(rect.width * FIELD_LEFT_FRAC)
        self._field_rect = pg.Rect(field_left, y, rect.right - field_left, FIELD_H)
        self.input.set_rect(self._field_rect)
        self.input.font = fonts.value
        self.input.draw(window)
        return self._field_rect.x

    def current_text(self):
        return self.input.text.strip()

    def handle_click(self, pos):
        if self._field_rect.collidepoint(pos):
            self.input.handle_click(pos)
            return True
        self.input.focused = False
        return False

    def contains_control(self, pos):
        return self._field_rect.collidepoint(pos)

    def handle_key(self, event):
        if not self.input.focused:
            return False
        handled = self.input.handle_key(event)
        if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
            self._edited = False
            if self.on_commit is not None:
                self.on_commit(self.current_text())
        elif handled:
            self._edited = True
        return handled

    def cancel_edit(self):
        if not self.input.focused and not self._edited:
            return False
        self._edited = False
        self.input.focused = False
        self.input.text = str(self.value_getter())
        return True


class RevealRow(_Row):

    def __init__(self, inner, visible_getter):
        super().__init__(inner.title, inner.desc)
        self.inner = inner
        self.visible_getter = visible_getter
        self._t = 1.0 if visible_getter() else 0.0
        self._collapse_cancelled = self._t == 0.0
        self._rect = pg.Rect(0, 0, 0, 0)

    def tick(self):
        visible = self.visible_getter()
        if visible:
            self._collapse_cancelled = False
        elif not self._collapse_cancelled:
            self._collapse_cancelled = True
            self.inner.cancel_edit()
        target = 1.0 if visible else 0.0
        if abs(self._t - target) < REVEAL_SNAP_EPS:
            self._t = target
        else:
            self._t += (target - self._t) * REVEAL_LERP

    def animating(self):
        return 0.0 < self._t < 1.0

    def height(self, fonts):
        return int(round(self.inner.height(fonts) * self._t))

    def full_height(self, fonts):
        return self.inner.height(fonts)

    def draw(self, window, rect, fonts):
        self._rect = pg.Rect(rect)
        full_h = self.inner.height(fonts)
        prev = window.get_clip()
        window.set_clip(rect.clip(prev))
        self.inner.draw(window, pg.Rect(rect.x, rect.centery - full_h // 2,
                                        rect.width, full_h), fonts)
        window.set_clip(prev)

    def _live(self, pos):
        return self._t > 0.0 and self._rect.collidepoint(pos)

    def handle_click(self, pos):
        if self._live(pos):
            return self.inner.handle_click(pos)
        if self._t > 0.0 and not self.inner.contains_control(pos):
            self.inner.handle_click(pos)
        return False

    def contains_control(self, pos):
        return self.inner.contains_control(pos) if self._live(pos) else False

    def handle_key(self, event):
        return self.inner.handle_key(event) if self.visible_getter() else False

    def cancel_edit(self):
        return self.inner.cancel_edit() if self._t > 0.0 else False


class ActionRow(_Row):

    def __init__(self, title, desc, button_label_getter, on_press, status_getter):
        super().__init__(title, desc)
        self.button_label_getter = button_label_getter
        self.on_press = on_press
        self.status_getter = status_getter
        self._button_rect = pg.Rect(0, 0, 0, 0)
        self._status_cache = None

    def _control_h(self, fonts):
        return FIELD_H

    def _draw_control(self, window, rect, fonts):
        y = rect.centery - FIELD_H // 2
        label = self.button_label_getter()
        btn_w = fonts.button.size(label)[0] + 2 * BTN_PAD_X
        self._button_rect = pg.Rect(rect.right - btn_w, y, btn_w, FIELD_H)
        window.blit(cut_rect_surface(self._button_rect.size, 6, Colors.surface_raised,
                                     border=Colors.border, border_width=1, corners=("tr",)),
                    self._button_rect.topleft)
        bt = render_text(fonts.button, label, Colors.text)
        window.blit(bt, (self._button_rect.centerx - bt.get_width() // 2,
                         self._button_rect.centery - bt.get_height() // 2))
        tone, text = self.status_getter()
        left = self._button_rect.x
        avail = self._button_rect.x - ACTION_STATUS_GAP \
            - (rect.x + ACTION_MIN_LABEL_W + CONTROL_GAP)
        if text and avail > 0:
            key = (id(fonts.value), tone, text, avail)
            if self._status_cache is None or self._status_cache[0] != key:
                shown = _elide_left(fonts.value, text, avail)
                self._status_cache = (key, render_text(fonts.value, shown,
                                                       _STATUS_TONES[tone]))
            surf = self._status_cache[1]
            left = self._button_rect.x - ACTION_STATUS_GAP - surf.get_width()
            _blit_clip(window, surf, (max(left, rect.x), rect.centery - surf.get_height() // 2),
                       avail)
        return int(left)

    def handle_click(self, pos):
        if self._button_rect.collidepoint(pos):
            self.on_press()
            return True
        return False

    def contains_control(self, pos):
        return self._button_rect.collidepoint(pos)


class OptionsBody(ScrollHost):

    def __init__(self):
        self.sections = []
        self.rect = pg.Rect(0, 0, 0, 0)
        self.fonts = None
        self._card_rects = []
        self._scroll_px = 0.0
        self._content_h = 0
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self.rect, self._content_h),
            wheel_step_px=OPTIONS_WHEEL_STEP,
        )

    def is_visible(self):
        return True

    def set_sections(self, sections):
        self.sections = sections
        self._scroll_px = 0.0
        self.scroll.cancel()

    def draw(self, window, rect, fonts):
        self.scroll.tick()
        self.rect = pg.Rect(rect)
        self.fonts = fonts
        self._scroll_px = max(0.0, min(self._scroll_px, self._max_scroll()))
        prev = window.get_clip()
        window.set_clip(rect)
        card_w = rect.width - SCROLLBAR_RESERVE
        y = rect.y - self._scroll_px
        self._card_rects = []
        for label, rows in self.sections:
            window.blit(render_text(fonts.section, label.upper(), Colors.text_muted),
                        (rect.x, y))
            y += fonts.section.get_height() + SECTION_LABEL_GAP
            y = self._draw_card(window, rect.x, y, card_w, rows, fonts)
            y += SECTION_GAP
        self._content_h = (y - SECTION_GAP + self._scroll_px) - rect.y
        window.set_clip(prev)
        self.scroll.draw_thumb(window)

    def _draw_card(self, window, x, y, card_w, rows, fonts):
        for row in rows:
            row.tick()
        heights = [row.height(fonts) for row in rows]
        card = pg.Rect(x, round(y), card_w, sum(heights))
        self._card_rects.append(card)
        bg_h = card.height
        if any(row.animating() for row in rows):
            bg_h = sum(row.full_height(fonts) for row in rows)
        bg = cut_rect_surface((card_w, bg_h), CARD_CUT, Colors.surface, border=Colors.border,
                              border_width=1, corners=("tr",))
        if bg_h == card.height:
            window.blit(bg, card.topleft)
        else:
            window.blit(bg, card.topleft, pg.Rect(0, 0, card.width, card.height))
        content_x = card.x + CARD_PAD_X
        content_w = card.width - 2 * CARD_PAD_X
        ry = y
        drawn_any = False
        for row, h in zip(rows, heights):
            if h <= 0:
                continue
            if drawn_any:
                pg.draw.line(window, pg.Color(Colors.border), (content_x, round(ry)),
                             (content_x + content_w, round(ry)))
            row.draw(window, pg.Rect(content_x, round(ry), content_w, h), fonts)
            ry += h
            drawn_any = True
        return card.bottom

    def _max_scroll(self):
        return max(0, self._content_h - self.rect.height)

    def handle_click(self, pos):
        if not self.rect.collidepoint(pos):
            return False
        for _, rows in self.sections:
            for row in rows:
                if row.handle_click(pos):
                    return True
        return True

    def handle_press(self, pos):
        if not self.rect.collidepoint(pos):
            return False
        for _, rows in self.sections:
            for row in rows:
                if row.contains_control(pos):
                    return False
        return super().handle_press(pos)

    def handle_key(self, event):
        for _, rows in self.sections:
            for row in rows:
                if row.handle_key(event):
                    return True
        return False

    def cancel_focused_edit(self):
        for _, rows in self.sections:
            for row in rows:
                if row.cancel_edit():
                    return True
        return False
