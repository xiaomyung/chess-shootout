import pygame as pg

from frontend.modals.base import BaseModal
from frontend.visual.colors import Colors
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import draw_button_row, fit_text_to_rect
from frontend.visual.fonts import get_font


FEN_INPUT_MAX_CHARS = 100


class FenInputModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self.on_submit = None
        self.error = ""
        self.button_rects = {}
        self.text_input = TextInput(window, max_chars=FEN_INPUT_MAX_CHARS,
                                    placeholder="paste FEN…")
        self.title_font = get_font(20, bold=True)
        self.error_font = get_font(14, bold=False)
        self.button_font = get_font(14, bold=True)

    def _on_rect_changed(self):
        self.title_font = self.font(factor=8, min_size=18, bold=True)
        self.error_font = self.font(factor=14, min_size=12, bold=False)
        self.button_font = self.font(factor=14, min_size=12, bold=True)

    def show(self, on_submit):
        self._visible = True
        self.on_submit = on_submit
        self.error = ""
        self.text_input.text = ""
        self.text_input.focused = True

    def hide(self):
        self._visible = False
        self.on_submit = None
        self.text_input.focused = False
        self.button_rects = {}

    def is_visible(self):
        return self._visible

    def set_error(self, msg):
        self.error = msg

    def draw(self):
        if not self._visible:
            return
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)

        pad = self.padding
        title_band = pg.Rect(
            self.rect.x + pad, self.rect.y + pad,
            self.rect.width - 2 * pad, self.title_font.get_height() + 6,
        )
        title_surf = fit_text_to_rect(
            self.title_font.render("Start from FEN", True, Colors.white),
            title_band,
        )
        self.window.blit(
            title_surf,
            (self.rect.centerx - title_surf.get_width() / 2, title_band.y),
        )

        button_h = self.button_font.get_height() + 16
        button_row = pg.Rect(
            self.rect.x + pad, self.rect.bottom - pad - button_h,
            self.rect.width - 2 * pad, button_h,
        )

        input_h = max(int(self.rect.height * 0.20), 32)
        input_rect = pg.Rect(
            self.rect.x + pad,
            title_band.bottom + pad,
            self.rect.width - 2 * pad,
            input_h,
        )
        self.text_input.set_rect(input_rect)
        self.text_input.draw()

        if self.error:
            error_rect = pg.Rect(
                input_rect.x, input_rect.bottom + pad // 2,
                input_rect.width, button_row.y - input_rect.bottom - pad,
            )
            error_surf = fit_text_to_rect(
                self.error_font.render(self.error, True, Colors.selection_red),
                error_rect,
            )
            self.window.blit(
                error_surf,
                (error_rect.x, error_rect.y),
            )

        self.button_rects = draw_button_row(
            self.window, button_row,
            [("Start", "start"), ("Cancel", "cancel")],
            self.button_font, pad,
        )

    def handle_click(self, pos):
        if not self._visible:
            return False
        if self.text_input.rect.collidepoint(pos):
            self.text_input.focused = True
            return True
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                if key == "start":
                    self._submit()
                else:
                    self.hide()
                return True
        self.text_input.focused = False
        return True

    def handle_key(self, event):
        if not self._visible:
            return False
        if event.key == pg.K_RETURN:
            self._submit()
            return True
        return self.text_input.handle_key(event)

    def _submit(self):
        text = self.text_input.text.strip()
        if not text:
            self.set_error("FEN is empty")
            return
        if self.on_submit is None:
            return
        if not self.on_submit(text):
            self.set_error("Invalid FEN")
