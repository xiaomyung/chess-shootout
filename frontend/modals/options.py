import pygame as pg

from frontend.modals.base import BaseModal
from frontend.visual.colors import Colors
from frontend.visual.draw import supersample, rounded_rect_surface
from frontend.visual.fonts import get_display_font, get_font, get_mono_font
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import (
    draw_button, draw_button_row, draw_scroll_thumb, draw_segmented, draw_toggle,
)

ROW_PAD = 12
SECTION_GAP = 10
SCROLLBAR_RESERVE = 14
LABEL_GAP = 16


class _Fonts:
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


def _swatch_surface(size, top, bottom):
    def render(surf, k):
        w, h = surf.get_size()
        pg.draw.polygon(surf, pg.Color(top), [(0, 0), (w, 0), (0, h)])
        pg.draw.polygon(surf, pg.Color(bottom), [(w, 0), (w, h), (0, h)])
        mask = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_radius=max(int(8 * k), 1))
        surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    return supersample(size, render)


class _Row:

    def __init__(self, title, desc=""):
        self.title = title
        self.desc = desc

    def height(self, fonts):
        h = fonts.title.get_height()
        if self.desc:
            h += fonts.desc.get_height() + 2
        return h + 2 * ROW_PAD

    def draw(self, window, rect, fonts):
        control_left = self._draw_control(window, rect, fonts)
        self._draw_label(window, rect, fonts, control_left - LABEL_GAP)

    def _draw_label(self, window, rect, fonts, max_right):
        x = rect.x
        y = rect.y + ROW_PAD
        avail = max(max_right - x, 1)
        _blit_clip(window, fonts.title.render(self.title, True, Colors.white), (x, y), avail)
        if self.desc:
            _blit_clip(window, fonts.desc.render(self.desc, True, Colors.text_mute),
                       (x, y + fonts.title.get_height() + 2), avail)

    def _draw_control(self, window, rect, fonts):
        return rect.right

    def handle_click(self, pos):
        return False

    def handle_key(self, event):
        return False


class ToggleRow(_Row):

    def __init__(self, title, desc, getter, setter):
        super().__init__(title, desc)
        self.getter = getter
        self.setter = setter
        self._ctl = pg.Rect(0, 0, 0, 0)
        self._pos = None

    def _draw_control(self, window, rect, fonts):
        self._ctl = pg.Rect(rect.right - 46, rect.centery - 12, 46, 24)
        target = 1.0 if self.getter() else 0.0
        if self._pos is None:
            self._pos = target
        elif abs(self._pos - target) < 0.02:
            self._pos = target
        else:
            self._pos += (target - self._pos) * 0.3
        draw_toggle(window, self._ctl, self._pos)
        return self._ctl.x

    def handle_click(self, pos):
        if self._ctl.inflate(16, 14).collidepoint(pos):
            self.setter(not self.getter())
            return True
        return False


class SegmentedRow(_Row):

    def __init__(self, title, desc, options, getter, setter, mono=False):
        super().__init__(title, desc)
        self.options = options
        self.getter = getter
        self.setter = setter
        self.mono = mono
        self._rects = {}

    def _seg_h(self, fonts):
        return max(fonts.button.get_height() + 12, 28)

    def height(self, fonts):
        base = fonts.title.get_height() + (fonts.desc.get_height() + 2 if self.desc else 0)
        return ROW_PAD + base + 8 + self._seg_h(fonts) + ROW_PAD

    def draw(self, window, rect, fonts):
        x = rect.x
        y = rect.y + ROW_PAD
        window.blit(fonts.title.render(self.title, True, Colors.white), (x, y))
        yy = y + fonts.title.get_height() + 2
        if self.desc:
            window.blit(fonts.desc.render(self.desc, True, Colors.text_mute), (x, yy))
            yy += fonts.desc.get_height() + 2
        yy += 8
        font = (get_mono_font(max(int(fonts.button.get_height() * 0.82), 14))
                if self.mono else fonts.button)
        sr = pg.Rect(x, yy, rect.width, self._seg_h(fonts))
        self._rects = draw_segmented(window, sr, self.options, self.getter(), font)

    def handle_click(self, pos):
        for key, r in self._rects.items():
            if r.collidepoint(pos):
                self.setter(key)
                return True
        return False


class SliderRow(_Row):

    def __init__(self, title, desc, getter, setter):
        super().__init__(title, desc)
        self.getter = getter
        self.setter = setter
        self._track = pg.Rect(0, 0, 0, 0)
        self._dragging = False

    def _draw_control(self, window, rect, fonts):
        if self._dragging:
            if pg.mouse.get_pressed()[0]:
                self._set_from_x(pg.mouse.get_pos()[0])
            else:
                self._dragging = False
        value = max(0.0, min(1.0, self.getter()))
        readout = fonts.value.render(str(int(round(value * 100))), True, Colors.text_dim)
        window.blit(readout, (rect.right - readout.get_width(),
                              rect.centery - readout.get_height() / 2))
        slider_w = min(int(rect.width * 0.46), 200)
        track_h = 6
        track_right = rect.right - 44
        self._track = pg.Rect(track_right - slider_w, rect.centery - track_h // 2,
                              slider_w, track_h)
        pg.draw.rect(window, Colors.surface_inset, self._track, border_radius=track_h // 2)
        fill_w = int(self._track.width * value)
        if fill_w > 0:
            pg.draw.rect(window, Colors.accent,
                         pg.Rect(self._track.x, self._track.y, fill_w, track_h),
                         border_radius=track_h // 2)
        pg.draw.circle(window, Colors.white,
                       (self._track.x + fill_w, self._track.centery), 7)
        return self._track.x - 8

    def _set_from_x(self, x):
        if self._track.width <= 0:
            return
        ratio = (x - self._track.x) / self._track.width
        self.setter(max(0.0, min(1.0, ratio)))

    def handle_click(self, pos):
        if self._track.inflate(20, 22).collidepoint(pos):
            self._set_from_x(pos[0])
            self._dragging = True
            return True
        return False


class SwatchRow(_Row):

    def __init__(self, title, desc, swatches, getter, setter):
        super().__init__(title, desc)
        self.swatches = swatches
        self.getter = getter
        self.setter = setter
        self._rects = {}

    def height(self, fonts):
        return super().height(fonts) + 38

    def draw(self, window, rect, fonts):
        x = rect.x
        y = rect.y + ROW_PAD
        window.blit(fonts.title.render(self.title, True, Colors.white), (x, y))
        yy = y + fonts.title.get_height() + 2
        if self.desc:
            window.blit(fonts.desc.render(self.desc, True, Colors.text_mute), (x, yy))
            yy += fonts.desc.get_height() + 6
        self._rects = {}
        sw_w, sw_h, gap = 42, 30, 10
        sx = x
        for key, top, bottom, locked in self.swatches:
            r = pg.Rect(sx, yy, sw_w, sw_h)
            window.blit(_swatch_surface(r.size, top, bottom), r.topleft)
            if key == self.getter():
                window.blit(rounded_rect_surface(r.size, 8, "#00000000",
                                                 border=Colors.accent, border_width=2),
                            r.topleft)
            if locked:
                soon_font = get_font(max(int(sw_h * 0.38), 9), bold=True)
                shadow = soon_font.render("SOON", True, Colors.app_bg)
                tag = soon_font.render("SOON", True, Colors.white)
                tx = r.centerx - tag.get_width() / 2
                ty = r.centery - tag.get_height() / 2
                window.blit(shadow, (tx + 1, ty + 1))
                window.blit(tag, (tx, ty))
            self._rects[key] = (r, locked)
            sx += sw_w + gap

    def handle_click(self, pos):
        for key, (r, locked) in self._rects.items():
            if r.collidepoint(pos) and not locked:
                self.setter(key)
                return True
        return False


class PathRow(_Row):

    def __init__(self, label, desc, window, value_getter, on_change, on_reset, suffix=""):
        super().__init__(label, desc)
        self.value_getter = value_getter
        self.on_change = on_change
        self.on_reset = on_reset
        self.suffix = suffix
        self.input = TextInput(window, max_chars=512, placeholder="data folder path",
                               mono=True, bg=Colors.app_bg, radius=7, rest_align="end")
        self.input.padding = 11
        self.input.text = str(value_getter())
        self._change_rect = pg.Rect(0, 0, 0, 0)
        self._reset_rect = pg.Rect(0, 0, 0, 0)
        self._field_rect = pg.Rect(0, 0, 0, 0)

    def _field_h(self, fonts):
        return max(fonts.value.get_height() + 18, 34)

    def height(self, fonts):
        base = fonts.title.get_height() + (fonts.desc.get_height() + 2 if self.desc else 0)
        return ROW_PAD + base + 10 + self._field_h(fonts) + ROW_PAD

    def draw(self, window, rect, fonts):
        x = rect.x
        y = rect.y + ROW_PAD
        window.blit(fonts.title.render(self.title, True, Colors.white), (x, y))
        yy = y + fonts.title.get_height() + 2
        if self.desc:
            window.blit(fonts.desc.render(self.desc, True, Colors.text_mute), (x, yy))
            yy += fonts.desc.get_height() + 2
        yy += 10
        if not self.input.focused and self.input.text != str(self.value_getter()):
            self.input.text = str(self.value_getter())
        field_h = self._field_h(fonts)
        btn_w = max(int(rect.width * 0.17), 72)
        gap = 8
        self._reset_rect = pg.Rect(rect.right - btn_w, yy, btn_w, field_h)
        self._change_rect = pg.Rect(self._reset_rect.x - gap - btn_w, yy, btn_w, field_h)
        suffix_surf = fonts.value.render(self.suffix, True, Colors.text_mute) if self.suffix \
            else None
        suffix_w = suffix_surf.get_width() + 6 if suffix_surf else 0
        field_right = self._change_rect.x - gap - suffix_w
        self._field_rect = pg.Rect(x, yy, max(field_right - x, 1), field_h)
        self.input.set_rect(self._field_rect)
        self.input.font = fonts.value
        self.input.draw()
        if suffix_surf:
            window.blit(suffix_surf, (self._field_rect.right + 4,
                                      self._field_rect.centery - suffix_surf.get_height() // 2))
        draw_button(window, self._change_rect, "Change", fonts.button)
        draw_button(window, self._reset_rect, "Reset", fonts.button)

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

    def handle_key(self, event):
        return self.input.handle_key(event)


class TextRow(_Row):

    def __init__(self, label, desc, window, value_getter, placeholder=""):
        super().__init__(label, desc)
        self.value_getter = value_getter
        self.input = TextInput(window, max_chars=128, placeholder=placeholder,
                               mono=True, bg=Colors.app_bg, radius=7)
        self.input.padding = 11
        self.input.text = str(value_getter())
        self._field_rect = pg.Rect(0, 0, 0, 0)

    def _field_h(self, fonts):
        return max(fonts.value.get_height() + 18, 34)

    def height(self, fonts):
        base = fonts.title.get_height() + (fonts.desc.get_height() + 2 if self.desc else 0)
        return ROW_PAD + base + 10 + self._field_h(fonts) + ROW_PAD

    def draw(self, window, rect, fonts):
        x = rect.x
        y = rect.y + ROW_PAD
        window.blit(fonts.title.render(self.title, True, Colors.white), (x, y))
        yy = y + fonts.title.get_height() + 2
        if self.desc:
            window.blit(fonts.desc.render(self.desc, True, Colors.text_mute), (x, yy))
            yy += fonts.desc.get_height() + 2
        yy += 10
        if not self.input.focused and self.input.text != str(self.value_getter()):
            self.input.text = str(self.value_getter())
        self._field_rect = pg.Rect(x, yy, rect.width, self._field_h(fonts))
        self.input.set_rect(self._field_rect)
        self.input.font = fonts.value
        self.input.draw()

    def current_text(self):
        return self.input.text.strip()

    def handle_click(self, pos):
        if self._field_rect.collidepoint(pos):
            self.input.handle_click(pos)
            return True
        self.input.focused = False
        return False

    def handle_key(self, event):
        return self.input.handle_key(event)


class OptionsBody:

    def __init__(self):
        self.sections = []
        self.rect = pg.Rect(0, 0, 0, 0)
        self.fonts = None
        self.scroll = 0
        self._content_h = 0
        self._last_scroll_ms = 0

    def set_sections(self, sections):
        self.sections = sections
        self.scroll = 0

    def draw(self, window, rect, fonts):
        self.rect = pg.Rect(rect)
        self.fonts = fonts
        prev = window.get_clip()
        window.set_clip(rect)
        row_w = rect.width - SCROLLBAR_RESERVE
        y = rect.y - self.scroll
        for label, rows in self.sections:
            window.blit(fonts.section.render(label.upper(), True, Colors.text_mute),
                        (rect.x, y + 6))
            y += fonts.section.get_height() + 8
            for row in rows:
                h = row.height(fonts)
                row.draw(window, pg.Rect(rect.x, y, row_w, h), fonts)
                y += h
            y += SECTION_GAP
        y += ROW_PAD
        self._content_h = (y + self.scroll) - rect.y
        window.set_clip(prev)
        track = pg.Rect(rect.right - 6, rect.y, 6, rect.height)
        offset_fraction = (self.scroll / self._max_scroll()) if self._max_scroll() else 0
        draw_scroll_thumb(window, track, self._content_h, rect.height,
                          offset_fraction, self._last_scroll_ms)

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

    def handle_scroll(self, pos, dy):
        if self._max_scroll() == 0:
            return False
        self.scroll = max(0, min(self.scroll - dy * 30, self._max_scroll()))
        self._last_scroll_ms = pg.time.get_ticks()
        return True

    def handle_key(self, event):
        for _, rows in self.sections:
            for row in rows:
                if row.handle_key(event):
                    return True
        return False


class OptionsModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.visible = False
        self.on_close = None
        self.body = OptionsBody()
        self._close_rect = pg.Rect(0, 0, 0, 0)
        self.button_rects = {}
        self._on_rect_changed()

    def _on_rect_changed(self):
        self.title_font = get_display_font(max(int(self.rect.height * 0.05), 20))
        self.fonts = _Fonts(
            title=self.font(22, min_size=13),
            desc=self.font(30, min_size=10, bold=False),
            section=self.font(34, min_size=9),
            value=get_mono_font(max(int(self.rect.height * 0.028), 11)),
            button=self.font(28, min_size=11),
        )

    def show(self, sections, on_close=None):
        self.body.set_sections(sections)
        self.on_close = on_close
        self.visible = True

    def hide(self):
        self.visible = False

    def is_visible(self):
        return self.visible

    def draw(self):
        if not self.visible or self.rect.width <= 0:
            return
        self.draw_shell()
        content = self.content_rect()
        title_surf = self.title_font.render("OPTIONS", True, Colors.white)
        self.window.blit(title_surf, (content.centerx - title_surf.get_width() / 2, content.y))
        title_bottom = content.y + title_surf.get_height() + self.padding

        btn_h = max(int(self.rect.height * 0.09), 30)
        close_row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        self.button_rects = draw_button_row(
            self.window, close_row, [("Close", "close")], self.fonts.button, self.padding,
            primary_keys={"close"})

        body_rect = pg.Rect(content.x, title_bottom, content.width,
                            close_row.y - self.padding - title_bottom)
        self.body.draw(self.window, body_rect, self.fonts)

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self.button_rects.get("close") and self.button_rects["close"].collidepoint(pos):
            if self.on_close is not None and self.on_close() is False:
                return True
            self.hide()
            return True
        self.body.handle_click(pos)
        return True

    def handle_scroll(self, pos, dy):
        if not self.visible:
            return False
        return self.body.handle_scroll(pos, dy)

    def handle_key(self, event):
        if not self.visible:
            return False
        return self.body.handle_key(event)
