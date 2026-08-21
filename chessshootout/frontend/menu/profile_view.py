from typing import Any

import pygame as pg

from chessshootout import paths
from chessshootout.infra import countries, env
from chessshootout.frontend.menu.layout import MenuLayout
from chessshootout.frontend.menu.view import (
    MenuView, draw_subview_title, scale_floor, seeded_avatar_palette, subview_title_top)
from chessshootout.frontend.panels.history_view import PGN_PATTERN, load_match_groups
from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.emoji import flag_surface
from chessshootout.frontend.visual.fonts import DISPLAY, get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import AvatarBadge


NICKNAME_REJECT_TOAST = "Please use ASCII symbols only"
NICKNAME_MAX_CHARS = 20

AVATAR_SIZE = 64
CARD_CUT = 8
ROW_H = 52
STAT_GAP = 10
STAT_H = 66


class ProfileView(MenuView):
    """
    The player's own page: the name they play under, the country flag shown
    beside it, their lifetime wins, losses, draws and pieces taken counted
    from their saved games, and the client id the server knows them by. It is
    the one place those settings are edited, and it is opened from the profile
    card on the menu's right rail rather than from a rail row
    """

    name = "profile"

    def __init__(self, app: Any) -> None:
        """
        Build the page with its nickname field ready. The field is ASCII-only
        and commits when it loses focus, so a typed name is stored whether the
        player presses Enter or simply clicks away

        :param app: the Frontend shell, this view's route to the window, the
            toast and the shared country picker
        """
        super().__init__(app)
        self._rect = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._wins = self._losses = self._draws = self._kos = 0
        self._avatar = AvatarBadge()
        self._avatar_palette = None
        self._avatar_palette_seed = None
        self._nickname_rect = pg.Rect(0, 0, 0, 0)
        self._country_rect = pg.Rect(0, 0, 0, 0)
        self._nickname_input = TextInput(
            app.window, max_chars=NICKNAME_MAX_CHARS, placeholder="Enter a nickname",
            on_commit=self._commit_nickname, ascii_only=True, on_reject=self._reject_ascii)
        self._nickname_input.text = env.get_nickname()

    def enter(self, payload: dict[str, Any] | None = None) -> None:
        """
        Open the page on what is true right now: the stored nickname back in
        the field, and the totals counted again from the saved games, so a
        game finished since the last visit is already in them

        :param payload: unused here; the profile page is always opened plain
        """
        self._nickname_input.text = env.get_nickname()
        self._refresh_stats()

    def exit(self) -> None:
        """
        Leave the page and drop typing focus, which commits whatever name was
        in the field. That is what saves a nickname when the player wanders
        off through the rail instead of pressing Enter
        """
        self._nickname_input.focused = False

    def _refresh_stats(self) -> None:
        """
        Count the four numbers on this page from the saved games on disk --
        wins, losses, draws and pieces taken -- reading them through the same
        loader the History list uses, so the two can never disagree
        """
        groups = load_match_groups(
            str(paths.get_games_dir()), PGN_PATTERN, env.get_nickname())
        self._wins = sum(1 for g in groups if g.result == "win")
        self._losses = sum(1 for g in groups if g.result == "loss")
        self._draws = sum(1 for g in groups if g.result == "draw")
        self._kos = sum(g.ko_you for g in groups)

    def _commit_nickname(self, text: str) -> None:
        """
        Store the name the player typed, which the field hands over when it
        loses focus. Storing is what makes the name stick for the next launch
        and what the server is given when queueing for a game

        :param text: the name as typed, cleaned again before it is stored
        """
        env.set_nickname(text)

    def _reject_ascii(self) -> None:
        """
        Explain why a keystroke did not appear: the nickname field takes ASCII
        only, so a dropped character gets a toast rather than silence
        """
        self.app.toast.show(NICKNAME_REJECT_TOAST)

    def _apply_country(self, code: str) -> None:
        """
        Store the country picked in the shared picker, which changes the flag
        beside this player's name everywhere it is drawn

        :param code: two-letter country code, empty to fly no flag at all
        """
        env.set_country(code)

    def _s(self, value: int, floor: int = 1) -> int:
        """
        Scale one design measurement to this window, never letting it fall
        below the floor, so the page shrinks gracefully instead of collapsing

        :param value: measurement in pixels at the reference window size
        :param floor: smallest pixel value this measurement may take
        :returns: the scaled measurement in pixels
        """
        return scale_floor(value, self._scale, floor)

    def relayout(self, menu_layout: MenuLayout) -> None:
        """
        Take the space the menu gave this page and rebuild everything inside
        it for the new window size

        :param menu_layout: the menu's rects and scale for this window size
        """
        self._rect = pg.Rect(menu_layout.subview_rect)
        self._scale = menu_layout.scale
        self._layout_rows()

    def _layout_rows(self) -> None:
        """
        Place the page top to bottom -- heading, identity card with the avatar,
        nickname field and country row, the four stat tiles beneath it and the
        client id line at the foot -- and build every font once here, so
        drawing a frame only reads what this pass worked out
        """
        rect = self._rect
        title_top = subview_title_top(rect)
        self._title_top = title_top
        self._title_font = get_display_font(self._s(28, 20))
        top = title_top + self._title_font.get_height() + self._s(20, 12)
        card_h = self._s(ROW_H, 40) * 2
        card = pg.Rect(rect.x, top, rect.width, card_h)
        av_size = self._s(AVATAR_SIZE, 44)
        pad = self._s(18, 12)
        self._identity_card = card
        self._avatar_rect = pg.Rect(card.x + pad, card.centery - av_size // 2,
                                    av_size, av_size)
        input_x = self._avatar_rect.right + self._s(16, 10)
        input_w = card.width - (input_x - card.x) - pad
        input_h = self._s(34, 26)
        self._nickname_rect = pg.Rect(input_x, card.y + self._s(14, 10), input_w, input_h)
        self._nickname_input.set_rect(self._nickname_rect)
        country_y = self._nickname_rect.bottom + self._s(10, 6)
        self._country_rect = pg.Rect(input_x, country_y, input_w,
                                     card.bottom - self._s(14, 10) - country_y)

        stats_top = card.bottom + self._s(24, 16)
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

    def draw(self, window: pg.Surface, menu_layout: MenuLayout) -> None:
        """
        Paint the page: heading, identity card, stat tiles and the client id
        line. A page with no width -- a window too narrow to give it any -- is
        skipped entirely

        :param window: surface drawn to, the window or a transition scratch
            surface
        :param menu_layout: the menu's rects and scale, unused here since the
            rect and fonts were kept at relayout
        """
        rect = self._rect
        if rect.width <= 0:
            return
        draw_subview_title(window, self._title_font, "PROFILE", rect.x, self._title_top)
        self._draw_identity_card(window)
        self._draw_stats(window)
        self._draw_uuid(window)

    def _draw_identity_card(self, window: pg.Surface) -> None:
        """
        Draw who the player is: the avatar tile, the editable nickname field
        and the country row. The avatar's colors come from the shared
        name-seeded helper, so this tile matches the one on the right-hand
        profile card exactly

        :param window: surface drawn to, the window or a scratch surface
        """
        window.blit(cut_rect_surface(self._identity_card.size, self._s(CARD_CUT, 6),
                                     Colors.surface, border=Colors.border, border_width=1,
                                     corners=("tr", "bl")), self._identity_card.topleft)
        nickname = env.get_nickname()
        self._avatar_palette_seed, self._avatar_palette = seeded_avatar_palette(
            nickname, self._avatar_palette_seed, self._avatar_palette)
        self._avatar.draw(window, self._avatar_rect, nickname or "?",
                          self._avatar_letter_font, self._avatar_palette)
        self._nickname_input.draw(window)
        self._draw_country_row(window)

    def _draw_country_row(self, window: pg.Surface) -> None:
        """
        Draw the row that opens the country picker: the flag and country name
        once one is chosen, or an invitation to pick one while none is set. It
        lights up under the cursor, since the whole row is the button

        :param window: surface drawn to, the window or a scratch surface
        """
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

    def _flag_surface(self, code: str) -> pg.Surface | None:
        """
        Fetch the little flag for the country row at this window's size, from
        the one shared place flags are drawn from

        :param code: two-letter country code, empty or unknown allowed
        :returns: the shared flag picture, or None when there is no flag to
            show
        """
        return flag_surface(code, self._s(15, 11))

    def _draw_stats(self, window: pg.Surface) -> None:
        """
        Draw the four tiles summing up this player's record -- wins, losses,
        draws and pieces taken -- each in its own colour so the row reads at a
        glance

        :param window: surface drawn to, the window or a scratch surface
        """
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

    def _draw_uuid(self, window: pg.Surface) -> None:
        """
        Print the identity this installation plays under. It is the id the
        server keys a player on, so showing it gives the player something to
        quote when a game needs looking into

        :param window: surface drawn to, the window or a scratch surface
        """
        text = f"CLIENT ID  {env.get_or_create_client_uuid()}"
        surf = render_text(self._uuid_font, text, Colors.text_muted)
        window.blit(surf, (self._rect.x, self._uuid_y))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a click on the page: into the nickname field, or onto the
        country row, which opens the shared picker. A click anywhere else on
        the page drops typing focus first, which commits a name in progress,
        and is then swallowed so it cannot fall through to the menu

        :param pos: click position in window pixels
        :returns: True when the click landed anywhere on this page
        """
        if self._nickname_rect.collidepoint(pos):
            self._nickname_input.handle_click(pos)
            return True
        if self._nickname_input.focused:
            self._nickname_input.focused = False
        if self._country_rect.collidepoint(pos):
            self.app.country_picker.show(env.get_country(), self._apply_country)
            return True
        return self._rect.collidepoint(pos)

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Hand a key press to the nickname field, which is the only thing on
        this page that takes typing. It ignores everything while it is not
        focused, so keys reach the page harmlessly

        :param event: pygame KEYDOWN event, key code and unicode both readable
        :returns: True when the nickname field took the key
        """
        return self._nickname_input.handle_key(event)
