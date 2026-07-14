import pygame as pg

from chessshootout import paths
from chessshootout.infra import countries, env
from chessshootout.domain.pgn.load import scan_pgn_summaries
from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.panels.history_view import build_match_groups
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import DISPLAY, get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import AvatarBadge, avatar_palette


PGN_PATTERN = "*.pgn"
NICKNAME_REJECT_TOAST = "Please use ASCII symbols only"
NICKNAME_MAX_CHARS = 20

TITLE_TOP_FRAC = 0.05
AVATAR_SIZE = 64
PANEL_CUT = 8
ROW_H = 52
STAT_GAP = 10
STAT_H = 66


class ProfileView(MenuView):

    name = "profile"

    def __init__(self, app):
        super().__init__(app)
        self._rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._wins = self._losses = self._draws = self._kos = 0
        self._avatar = AvatarBadge()
        self._flag_cache = {}
        self._nickname_rect = pg.Rect(0, 0, 0, 0)
        self._country_rect = pg.Rect(0, 0, 0, 0)
        self._nickname_input = TextInput(
            app.window, max_chars=NICKNAME_MAX_CHARS, placeholder="Enter a nickname",
            on_commit=self._commit_nickname, ascii_only=True, on_reject=self._reject_ascii)
        self._nickname_input.text = env.get_nickname()

    def enter(self, payload=None):
        self._nickname_input.text = env.get_nickname()
        self._refresh_stats()

    def exit(self):
        self._nickname_input.focused = False

    def _refresh_stats(self):
        groups = build_match_groups(
            scan_pgn_summaries(str(paths.get_games_dir()), PGN_PATTERN), env.get_nickname())
        self._wins = sum(1 for g in groups if g.result == "win")
        self._losses = sum(1 for g in groups if g.result == "loss")
        self._draws = len(groups) - self._wins - self._losses
        self._kos = sum(g.ko_you for g in groups)

    def _commit_nickname(self, text):
        env.set_nickname(text)

    def _reject_ascii(self):
        self.app.toast.show(NICKNAME_REJECT_TOAST)

    def _apply_country(self, code):
        env.set_country(code)

    def _s(self, value, floor=1):
        return max(int(value * self._scale), floor)

    def relayout(self, menu_layout):
        self._rect = pg.Rect(menu_layout.subview_rect)
        self._scale = menu_layout.scale
        self._layout_rows()

    def _layout_rows(self):
        rect = self._rect
        title_top = rect.y + int(rect.height * TITLE_TOP_FRAC)
        self._title_top = title_top
        self._title_font = get_display_font(self._s(28, 20))
        top = title_top + self._title_font.get_height() + self._s(20, 12)
        panel_h = self._s(ROW_H, 40) * 2
        panel = pg.Rect(rect.x, top, rect.width, panel_h)
        av_size = self._s(AVATAR_SIZE, 44)
        pad = self._s(18, 12)
        self._identity_panel = panel
        self._avatar_rect = pg.Rect(panel.x + pad, panel.centery - av_size // 2,
                                    av_size, av_size)
        input_x = self._avatar_rect.right + self._s(16, 10)
        input_w = panel.width - (input_x - panel.x) - pad
        input_h = self._s(34, 26)
        self._nickname_rect = pg.Rect(input_x, panel.y + self._s(14, 10), input_w, input_h)
        self._nickname_input.set_rect(self._nickname_rect)
        country_y = self._nickname_rect.bottom + self._s(10, 6)
        self._country_rect = pg.Rect(input_x, country_y, input_w,
                                     panel.bottom - self._s(14, 10) - country_y)

        stats_top = panel.bottom + self._s(24, 16)
        stat_w = (rect.width - 3 * self._s(STAT_GAP, 8)) / 4
        self._stat_rects = []
        for i in range(4):
            x = rect.x + i * (stat_w + self._s(STAT_GAP, 8))
            self._stat_rects.append(pg.Rect(int(x), stats_top, int(stat_w), self._s(STAT_H, 50)))

        self._uuid_y = self._stat_rects[0].bottom + self._s(28, 18)

        self._avatar_letter_font = get_font(self._s(22, 16), family=DISPLAY)
        self._country_font = get_font(self._s(12, 10), bold=True)
        self._stat_num_font = get_mono_font(self._s(22, 16), bold=True)
        self._stat_label_font = get_font(self._s(10, 8), bold=True)
        self._uuid_font = get_mono_font(self._s(11, 9))

    def draw(self, window, menu_layout):
        rect = self._rect
        if rect.width <= 0:
            return
        title = render_text(self._title_font, "PROFILE", Colors.text)
        window.blit(title, (rect.x, self._title_top))
        self._draw_identity_panel(window)
        self._draw_stats(window)
        self._draw_uuid(window)

    def _draw_identity_panel(self, window):
        window.blit(cut_rect_surface(self._identity_panel.size, self._s(PANEL_CUT, 6),
                                     Colors.surface, border=Colors.border, border_width=1,
                                     corners=("tr", "bl")), self._identity_panel.topleft)
        self._avatar.draw(window, self._avatar_rect, env.get_nickname() or "?",
                          self._avatar_letter_font, avatar_palette())
        self._nickname_input.draw()
        self._draw_country_row(window)

    def _draw_country_row(self, window):
        rect = self._country_rect
        hovered = rect.collidepoint(pg.mouse.get_pos())
        fill = Colors.surface_hover if hovered else Colors.surface_raised
        window.blit(cut_rect_surface(rect.size, self._s(6, 4), fill, border=Colors.border,
                                     border_width=1, corners=("tr", "bl")), rect.topleft)
        pad = self._s(10, 6)
        code = env.get_country()
        flag = self._flag_surface(code)
        x = rect.x + pad
        if flag is not None:
            window.blit(flag, (x, rect.centery - flag.get_height() // 2))
            x += flag.get_width() + self._s(8, 5)
        label = countries.name_for(code) or "Set your country"
        color = Colors.text if code else Colors.text_muted
        label_surf = render_text(self._country_font, label, color)
        window.blit(label_surf, (x, rect.centery - label_surf.get_height() // 2))

    def _flag_surface(self, code):
        char = countries.flag_emoji(code)
        if not char:
            return None
        size = self._s(15, 11)
        key = (char, size)
        if key not in self._flag_cache:
            self._flag_cache[key] = emoji_surface(char, size)
        return self._flag_cache[key]

    def _draw_stats(self, window):
        cards = ((self._wins, "WINS", Colors.win), (self._losses, "LOSSES", Colors.loss),
                 (self._draws, "DRAWS", Colors.text), (self._kos, "KOS", Colors.amber_hi))
        for rect, (value, label, color) in zip(self._stat_rects, cards):
            window.blit(cut_rect_surface(rect.size, self._s(7, 5), Colors.surface,
                                         border=Colors.border, border_width=1,
                                         corners=("tr", "bl")), rect.topleft)
            num = render_text(self._stat_num_font, str(value), color)
            window.blit(num, (rect.x + self._s(12, 8), rect.y + self._s(10, 6)))
            lab = render_text(self._stat_label_font, label, Colors.text_muted)
            window.blit(lab, (rect.x + self._s(12, 8),
                              rect.y + self._s(10, 6) + num.get_height() + self._s(3, 2)))

    def _draw_uuid(self, window):
        text = f"CLIENT ID  {env.get_or_create_client_uuid()}"
        surf = render_text(self._uuid_font, text, Colors.text_muted)
        window.blit(surf, (self._rect.x, self._uuid_y))

    def handle_click(self, pos):
        if self._nickname_rect.collidepoint(pos):
            self._nickname_input.handle_click(pos)
            return True
        if self._nickname_input.focused:
            self._nickname_input.focused = False
        if self._country_rect.collidepoint(pos):
            self.app.country_picker.show(env.get_country(), self._apply_country)
            return True
        return self._rect.collidepoint(pos)

    def handle_key(self, event):
        return self._nickname_input.handle_key(event)
