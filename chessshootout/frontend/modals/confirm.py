import pygame as pg

from chessshootout.frontend.modals.base import BaseModal, MODAL_MAX_WIDTH, MODAL_RAIL
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import rounded_rect_surface
from chessshootout.frontend.visual.emoji import blit_emoji
from chessshootout.frontend.visual.fonts import fonts_for_width, get_display_font, get_font
from chessshootout.frontend.visual.widgets import draw_button_row, fit_text_to_rect, wrap_words


TITLE_SUB_GAP = 8
TITLE_TILE_RADIUS = 13
SUB_MAX_LINES = 3


class ConfirmModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self.title = None
        self.sub = ""
        self.danger = False
        self.emoji = None
        self.on_yes = None
        self.on_no = None
        self.on_extra = None
        self.yes_label = "Confirm"
        self.no_label = "Cancel"
        self.extra_label = "Cancel"
        self.button_rects = {}
        self._panel = pg.Rect(0, 0, 0, 0)
        self._font_cache = {}

    def show(self, title, on_yes, on_no=None, yes_label="Confirm", no_label="Cancel",
             on_extra=None, extra_label="Cancel", sub="", danger=False, emoji=None):
        self.title = title
        self.sub = sub
        self.danger = danger
        self.emoji = emoji
        self.on_yes = on_yes
        self.on_no = on_no
        self.on_extra = on_extra
        self.yes_label = yes_label
        self.no_label = no_label
        self.extra_label = extra_label

    def hide(self):
        self.title = None
        self.emoji = None
        self.on_yes = None
        self.on_no = None
        self.on_extra = None
        self.button_rects = {}

    def is_visible(self):
        return self.title is not None

    def _fonts(self, panel_w):
        return fonts_for_width(self._font_cache, panel_w, self._build_fonts)

    def _build_fonts(self, panel_w):
        return (
            get_display_font(max(int(panel_w * 0.07), 22)),
            get_font(max(int(panel_w * 0.032), 13), bold=False),
            get_font(max(int(panel_w * 0.034), 13), bold=True),
        )

    def draw(self):
        if not self.is_visible() or self.rect.width <= 0:
            self.button_rects = {}
            return
        pad = self.padding
        panel_w = min(self.rect.width, MODAL_MAX_WIDTH)
        inner_w = panel_w - 2 * pad
        title_font, sub_font, button_font = self._fonts(panel_w)
        btn_h = max(int(panel_w * 0.11), 40)

        title_surf = fit_text_to_rect(
            title_font.render(self.title.upper(), True, Colors.text),
            pg.Rect(0, 0, inner_w, title_font.get_height()))
        sub_lines = wrap_words(self.sub, sub_font, inner_w, SUB_MAX_LINES) if self.sub else []
        line_h = sub_font.get_linesize()

        icon_side = max(int(panel_w * 0.12), 40) if self.emoji else 0
        gap_icon = max(int(panel_w * 0.03), 12) if self.emoji else 0
        gap_title = TITLE_SUB_GAP if sub_lines else 0
        block_h = (icon_side + gap_icon + title_surf.get_height()
                   + (gap_title + line_h * len(sub_lines) if sub_lines else 0))
        panel_h = MODAL_RAIL + pad + block_h + max(int(panel_w * 0.05), 18) + btn_h + pad
        panel = pg.Rect(0, 0, panel_w, panel_h)
        panel.center = self.rect.center
        self._panel = panel

        self.draw_shell("loss" if self.danger else None, panel)
        content = self.content_rect(panel)
        y = content.y
        if self.emoji:
            tile = pg.Rect(content.centerx - icon_side // 2, y, icon_side, icon_side)
            fill = Colors.surface_hover
            border = Colors.border
            if self.danger:
                fill = pg.Color(Colors.loss).lerp(pg.Color(Colors.surface_hover), 0.84)
                border = pg.Color(Colors.loss).lerp(pg.Color(Colors.surface_raised), 0.6)
            self.window.blit(rounded_rect_surface(tile.size, TITLE_TILE_RADIUS, fill,
                                                  border=border, border_width=1), tile.topleft)
            blit_emoji(self.window, self.emoji, tile.center, int(icon_side * 0.62))
            y += icon_side + gap_icon
        self.window.blit(title_surf, (content.centerx - title_surf.get_width() / 2, y))
        y += title_surf.get_height() + gap_title
        for line in sub_lines:
            surf = sub_font.render(line, True, Colors.text_dim)
            self.window.blit(surf, (content.centerx - surf.get_width() / 2, y))
            y += line_h

        row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        buttons = [(self.no_label, "no"), (self.yes_label, "yes")]
        if self.on_extra is not None:
            buttons.append((self.extra_label, "extra"))
        self.button_rects = draw_button_row(
            self.window, row, buttons, button_font, pad, primary_keys={"yes"})

    def handle_click(self, pos):
        if not self.is_visible():
            return False
        callbacks = {"yes": self.on_yes, "no": self.on_no, "extra": self.on_extra}
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                callback = callbacks.get(key)
                self.hide()
                if callback is not None:
                    callback()
                return True
        return False
