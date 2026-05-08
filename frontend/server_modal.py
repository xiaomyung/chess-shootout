import pygame as pg

from frontend.colors import Colors
from frontend.text_input import TextInput
from frontend.widgets import draw_button_row, fit_text_to_rect


class ServerAddressModal:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.padding = 12
        self.title = None
        self.on_connect = None
        self.on_cancel = None
        self.title_font = pg.font.SysFont("Arial", 22, bold=True)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self.input = TextInput(window, max_chars=64, placeholder="host:port")
        self.button_rects = {}

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        self.title_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 7), 12), bold=True,
        )
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.height / 14), 10), bold=True,
        )
        input_h = max(int(rect.height * 0.20), 30)
        self.input.set_rect(pg.Rect(
            rect.x + self.padding, rect.centery - input_h // 2,
            rect.width - 2 * self.padding, input_h,
        ))

    def show(self, prefilled, on_connect, on_cancel=None):
        self.title = "Connect to server"
        self.input.text = prefilled
        self.on_connect = on_connect
        self.on_cancel = on_cancel

    def hide(self):
        self.title = None
        self.on_connect = None
        self.on_cancel = None
        self.button_rects = {}

    def is_visible(self):
        return self.title is not None

    def draw(self):
        if not self.is_visible():
            return
        pg.draw.rect(self.window, Colors.light_grey_menu, self.rect, border_radius=8)
        pg.draw.rect(self.window, Colors.button_border, self.rect, 2, border_radius=8)
        title_band = pg.Rect(
            self.rect.x + self.padding, self.rect.y + self.padding * 2,
            self.rect.width - 2 * self.padding,
            int(self.rect.height * 0.25),
        )
        title_surf = fit_text_to_rect(
            self.title_font.render(self.title, True, Colors.white), title_band,
        )
        self.window.blit(
            title_surf,
            (self.rect.centerx - title_surf.get_width() / 2, title_band.y),
        )
        self.input.draw()
        gap = self.padding
        btn_h = max(self.rect.height * 0.22, 28)
        row_rect = pg.Rect(
            self.rect.x + gap,
            self.rect.bottom - gap - btn_h,
            self.rect.width - 2 * gap,
            btn_h,
        )
        self.button_rects = draw_button_row(
            self.window, row_rect,
            [("Connect", "connect"), ("Cancel", "cancel")],
            self.button_font, gap,
        )

    def handle_click(self, pos):
        if not self.is_visible():
            return False
        if self.input.handle_click(pos):
            return True
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                if key == "connect":
                    addr = self.input.text.strip()
                    callback = self.on_connect
                    self.hide()
                    if callback is not None:
                        callback(addr)
                else:
                    callback = self.on_cancel
                    self.hide()
                    if callback is not None:
                        callback()
                return True
        return False

    def handle_key(self, event):
        if not self.is_visible():
            return False
        if event.key == pg.K_RETURN and self.input.text.strip():
            addr = self.input.text.strip()
            callback = self.on_connect
            self.hide()
            if callback is not None:
                callback(addr)
            return True
        return self.input.handle_key(event)
