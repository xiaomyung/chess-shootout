import pygame as pg

from frontend.countries import flag_emoji
from frontend.modals.base import BaseModal, MODAL_RAIL
from frontend.visual.colors import Colors
from frontend.visual.draw import stroked_text
from frontend.visual.emoji import emoji_surface
from frontend.visual.fonts import get_display_font, get_font, get_mono_font
from frontend.visual.widgets import build_avatar, fit_text_to_rect


def _avatar_colors(side):
    if side in (Colors.white, "white", "w"):
        return (Colors.amber, Colors.accent, Colors.on_accent)
    return (Colors.avatar_slate_top, Colors.avatar_slate_bottom, Colors.avatar_letter_dark)


class MatchFoundModal(BaseModal):

    def __init__(self, window):
        super().__init__(window)
        self._active = False
        self.me_name = ""
        self.opp_name = ""
        self.me_side = "white"
        self.opp_side = "black"
        self.me_country = ""
        self.opp_country = ""
        self.rating = "1500"
        self.on_done = None
        self._started_at = 0
        self._seconds = 3
        self._flag_cache = {}

    def show(self, white_name, black_name, your_color, on_done, seconds=3, rating="1500",
             white_country="", black_country=""):
        if your_color == "white":
            self.me_name, self.me_side, self.me_country = white_name, "white", white_country
            self.opp_name, self.opp_side, self.opp_country = black_name, "black", black_country
        else:
            self.me_name, self.me_side, self.me_country = black_name, "black", black_country
            self.opp_name, self.opp_side, self.opp_country = white_name, "white", white_country
        self.rating = rating
        self.on_done = on_done
        self._seconds = seconds
        self._started_at = pg.time.get_ticks()
        self._active = True

    def hide(self):
        self._active = False
        self.on_done = None

    def is_visible(self):
        return self._active

    def update(self):
        if not self._active:
            return
        elapsed = (pg.time.get_ticks() - self._started_at) / 1000.0
        if elapsed >= self._seconds:
            done = self.on_done
            self.hide()
            if done is not None:
                done()

    def _remaining(self):
        elapsed = (pg.time.get_ticks() - self._started_at) / 1000.0
        return max(self._seconds - int(elapsed), 1)

    def draw(self):
        if not self._active or self.rect.width <= 0:
            return
        pad = self.padding
        panel_w = min(self.rect.width, 440)
        eyebrow_font = get_font(max(int(panel_w * 0.028), 11), bold=True)
        name_font = get_font(max(int(panel_w * 0.032), 13), bold=True)
        rating_font = get_mono_font(max(int(panel_w * 0.025), 10))
        vs_font = get_display_font(max(int(panel_w * 0.06), 22))
        cd_font = get_font(max(int(panel_w * 0.028), 11), bold=True)
        av = max(int(panel_w * 0.118), 44)
        letter_font = get_display_font(max(int(av * 0.42), 16))

        eyebrow = eyebrow_font.render("MATCH FOUND", True, Colors.text_dim)
        vs_surf = emoji_surface("⚔️", max(int(panel_w * 0.08), 30))
        if vs_surf is None:
            vs_surf = stroked_text(vs_font, "VS", Colors.accent, Colors.outcome_stroke,
                                   max(int(vs_font.get_height() * 0.04), 1))
        card_h = av + 8 + name_font.get_height() + 2 + rating_font.get_height()
        vs_block_h = max(card_h, vs_surf.get_height())
        cd_h = cd_font.get_height()

        g_eyebrow = max(int(panel_w * 0.014), 6)
        g_divider = max(int(panel_w * 0.036), 14)
        g_vs_bottom = max(int(panel_w * 0.04), 16)
        panel_h = (MODAL_RAIL + pad + eyebrow.get_height() + g_eyebrow + 1 + g_divider
                   + vs_block_h + g_vs_bottom + cd_h + pad)
        panel = pg.Rect(0, 0, panel_w, panel_h)
        panel.center = self.rect.center

        self.draw_shell("win", panel)
        content = self.content_rect(panel)
        y = content.y
        self.window.blit(eyebrow, (content.centerx - eyebrow.get_width() / 2, y))
        y += eyebrow.get_height() + g_eyebrow
        pg.draw.line(self.window, Colors.border_strong,
                     (content.x, y), (content.right, y))
        y += 1 + g_divider

        gap = max(int(panel_w * 0.027), 12)
        side_w = (content.width - vs_surf.get_width() - 2 * gap) / 2
        self._draw_card(content.x + side_w / 2, y, av, side_w, card_h, self.me_name,
                        self.me_side, self.me_country, name_font, rating_font, letter_font)
        self._draw_card(content.right - side_w / 2, y, av, side_w, card_h, self.opp_name,
                        self.opp_side, self.opp_country, name_font, rating_font, letter_font)
        self.window.blit(vs_surf, (content.centerx - vs_surf.get_width() / 2,
                                   y + (card_h - vs_surf.get_height()) / 2))
        y += vs_block_h + g_vs_bottom

        label = cd_font.render("STARTING IN ", True, Colors.text_dim)
        number = cd_font.render(str(self._remaining()), True, Colors.amber_hi)
        total_w = label.get_width() + number.get_width()
        cx = content.centerx - total_w / 2
        self.window.blit(label, (cx, y))
        self.window.blit(number, (cx + label.get_width(), y))

    def _flag(self, country, size):
        char = flag_emoji(country)
        if not char:
            return None
        key = (char, size)
        if key not in self._flag_cache:
            self._flag_cache[key] = emoji_surface(char, size)
        return self._flag_cache[key]

    def _draw_card(self, cx, y, av, side_w, card_h, name, side, country, name_font,
                   rating_font, letter_font):
        top, bottom, letter_color = _avatar_colors(side)
        self.window.blit(build_avatar(av, top, bottom), (cx - av / 2, y))
        letter = (name[:1].upper() if name else "?")
        glyph = letter_font.render(letter, True, letter_color)
        self.window.blit(glyph, (cx - glyph.get_width() / 2,
                                 y + av / 2 - glyph.get_height() / 2))
        flag = self._flag(country, name_font.get_height())
        flag_w = (flag.get_width() + 7) if flag is not None else 0
        name_surf = name_font.render(name, True, Colors.white)
        name_surf = fit_text_to_rect(
            name_surf, pg.Rect(0, 0, max(side_w - flag_w, 1), name_surf.get_height()),
            padding=0)
        ny = y + av + 8
        gx = cx - (flag_w + name_surf.get_width()) / 2
        if flag is not None:
            self.window.blit(flag, (gx, ny + name_surf.get_height() / 2 - flag.get_height() / 2))
            gx += flag.get_width() + 7
        self.window.blit(name_surf, (gx, ny))
        rating = rating_font.render(self.rating, True, Colors.text_mute)
        self.window.blit(rating, (cx - rating.get_width() / 2,
                                  ny + name_surf.get_height() + 2))

    def handle_click(self, pos):
        return False
