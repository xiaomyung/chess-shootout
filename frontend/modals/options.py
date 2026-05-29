import pygame as pg

from frontend.modals.base import BaseModal
from frontend.visual.colors import Colors
from frontend.visual.widgets import draw_button, wrap_path


class PathRow:

    def __init__(self, label, value_getter, on_change, on_reset):
        self.label = label
        self.value_getter = value_getter
        self.on_change = on_change
        self.on_reset = on_reset
        self._change_rect = pg.Rect(0, 0, 0, 0)
        self._reset_rect = pg.Rect(0, 0, 0, 0)

    def draw(self, window, x, y, w, label_font, value_font, button_font):
        label_surf = label_font.render(self.label, True, Colors.white)
        window.blit(label_surf, (x, y))
        yy = y + label_surf.get_height() + 4

        for line in wrap_path(str(self.value_getter()), value_font, w):
            window.blit(value_font.render(line, True, Colors.white), (x, yy))
            yy += value_font.get_height() + 2
        yy += 8

        btn_h = max(value_font.get_height() + 12, 26)
        btn_w = max(int(w * 0.26), 90)
        gap = 8
        self._change_rect = pg.Rect(x, yy, btn_w, btn_h)
        self._reset_rect = pg.Rect(x + btn_w + gap, yy, btn_w, btn_h)
        draw_button(window, self._change_rect, "Change", button_font)
        draw_button(window, self._reset_rect, "Reset", button_font)
        return yy + btn_h

    def handle_click(self, pos):
        if self._change_rect.collidepoint(pos):
            self.on_change()
            return True
        if self._reset_rect.collidepoint(pos):
            self.on_reset()
            return True
        return False


class OptionsModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.visible = False
        self.title = "Options"
        self.rows = []
        self.on_close = None
        self._close_rect = pg.Rect(0, 0, 0, 0)
        self._on_rect_changed()

    def _on_rect_changed(self):
        self.title_font = self.font(factor=9, min_size=20)
        self.label_font = self.font(factor=18, min_size=14)
        self.value_font = self.font(factor=22, min_size=13, bold=False)
        self.button_font = self.font(factor=22, min_size=13)

    def show(self, rows, on_close=None):
        self.rows = rows
        self.on_close = on_close
        self.visible = True

    def hide(self):
        self.visible = False

    def is_visible(self):
        return self.visible

    def draw(self):
        if not self.visible:
            return
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)

        pad = self.padding
        title_surf = self.title_font.render(self.title, True, Colors.white)
        self.window.blit(
            title_surf, (self.rect.centerx - title_surf.get_width() / 2, self.rect.y + pad),
        )
        title_bottom = self.rect.y + pad + title_surf.get_height()

        close_h = max(int(self.rect.height * 0.1), 30)
        close_w = max(int(self.rect.width * 0.3), 100)
        self._close_rect = pg.Rect(
            self.rect.centerx - close_w // 2, self.rect.bottom - pad - close_h, close_w, close_h,
        )
        draw_button(self.window, self._close_rect, "Close", self.button_font)

        y = title_bottom + pad
        for row in self.rows:
            y = row.draw(
                self.window, self.rect.x + pad, y, self.rect.width - 2 * pad,
                self.label_font, self.value_font, self.button_font,
            )
            y += pad

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._close_rect.collidepoint(pos):
            self.hide()
            if self.on_close is not None:
                self.on_close()
            return True
        for row in self.rows:
            if row.handle_click(pos):
                return True
        return True
