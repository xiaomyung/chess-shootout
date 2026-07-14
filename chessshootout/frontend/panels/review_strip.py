import pygame as pg

from chessshootout.backend.pieces import PieceColor
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font, DISPLAY
from chessshootout.frontend.visual.widgets import AvatarBadge, avatar_palette


class ReviewStrip:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.name = ""
        self.player_color = PieceColor.WHITE
        self.captured = []
        self.advantage = 0
        self.captured_color = None
        self.icons = {}
        self.name_font = get_font(14, bold=True)
        self.advantage_font = get_font(12, bold=True)
        self.letter_font = get_font(18, family=DISPLAY)
        self._avatar = AvatarBadge()
        self._avatar_palette = None
        self._avatar_palette_seed = None

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        h = rect.height
        ih = max(int(h * 0.68), 1)
        self.name_font = get_font(max(int(ih * 0.42), 11), bold=True)
        self.advantage_font = get_font(max(int(ih * 0.26), 8), bold=True)
        self.letter_font = get_font(max(int(ih * 0.5), 11), family=DISPLAY)
        self._avatar.reset()

    def set_piece_icons(self, icons):
        self.icons = icons

    def set_state(self, name, player_color, captured=None, advantage=0, captured_color=None):
        self.name = name
        self.player_color = player_color
        self.captured = captured or []
        self.advantage = advantage
        self.captured_color = captured_color

    def draw(self):
        h = self.rect.height
        if h <= 0 or self.rect.width <= 0:
            return
        pad = max(int(h * 0.16), 4)
        radius = max(int(h * 0.17), 5)
        pg.draw.rect(self.window, Colors.surface, self.rect, border_radius=radius)

        av_size = max(h - 2 * pad, 1)
        avatar_rect = pg.Rect(self.rect.x + pad, self.rect.y + pad, av_size, av_size)
        self._draw_avatar(avatar_rect)

        gap = max(int(h * 0.18), 6)
        self._draw_name_and_captures(avatar_rect.right + gap, av_size)

        pg.draw.rect(self.window, Colors.border, self.rect, width=1, border_radius=radius)

    def _draw_avatar(self, rect):
        if self._avatar_palette is None or self._avatar_palette_seed != self.name:
            self._avatar_palette_seed = self.name
            self._avatar_palette = avatar_palette(self.name)
        self._avatar.draw(self.window, rect, self.name, self.letter_font, self._avatar_palette)

    def _draw_name_and_captures(self, x, ih):
        top_y = self.rect.y + max(int(self.rect.height * 0.18), 4)
        name_surf = self.name_font.render(self.name, True, Colors.text)
        max_name_w = max(self.rect.right - x - 8, 1)
        if name_surf.get_width() > max_name_w:
            name_surf = name_surf.subsurface(pg.Rect(0, 0, max_name_w, name_surf.get_height()))
        self.window.blit(name_surf, (x, top_y))
        bottom_cy = self.rect.bottom - max(int(self.rect.height * 0.22), 8)
        self._draw_captured(x, bottom_cy, ih)

    def _draw_captured(self, x, cy, ih):
        cursor = x
        last_right = x
        right_bound = self.rect.right - 8
        size = max(int(ih * 0.5), 6)
        for piece_type in self.captured:
            icon = self.icons.get((piece_type, self.captured_color))
            if icon is None:
                continue
            if icon.get_height() != size:
                icon = pg.transform.smoothscale(icon, (size, size))
            if cursor + icon.get_width() > right_bound:
                break
            self.window.blit(icon, (cursor, cy - icon.get_height() / 2))
            last_right = cursor + icon.get_width()
            cursor += icon.get_width() - icon.get_width() // 3
        if self.advantage > 0:
            self._draw_advantage_pill(last_right + max(int(ih * 0.18), 5), cy, right_bound)

    def _draw_advantage_pill(self, x, cy, right_bound):
        text = self.advantage_font.render(f"+{self.advantage}", True, Colors.on_accent)
        pad_x, pad_y = 6, 3
        w = text.get_width() + 2 * pad_x
        h = text.get_height() + 2 * pad_y
        if x + w > right_bound:
            return
        rect = pg.Rect(x, round(cy - h / 2), w, h)
        pg.draw.rect(self.window, Colors.amber, rect, border_radius=h // 2)
        self.window.blit(text, (rect.centerx - text.get_width() / 2,
                                rect.centery - text.get_height() / 2))
