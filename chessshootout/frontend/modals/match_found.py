from collections.abc import Callable
from typing import Any, cast

import pygame as pg

from chessshootout.frontend.modals.base import BaseModal, MODAL_MAX_WIDTH, MODAL_RAIL
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import stroked_text
from chessshootout.frontend.visual.emoji import emoji_surface, flag_surface
from chessshootout.frontend.visual.fonts import (
    fonts_for_width, get_display_font, get_font, get_mono_font,
)
from chessshootout.frontend.visual.widgets import (
    avatar_palette, build_flat_avatar, fit_text_to_rect,
)


FLAG_NAME_GAP = 7
AVATAR_NAME_GAP = 8
NAME_RATING_GAP = 2


class MatchFoundModal(BaseModal):
    """
    The card that introduces the two players once matchmaking pairs them and
    counts down to the first move, drawn in the shared modal shell. The online
    coordinator owns it, Esc cannot dismiss it, and its arrival chime is the
    one sound played by the coordinator rather than by the consumer
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build the card once at startup with nobody on it; every field is
        filled in when a pairing actually arrives

        :param window: the app window surface this modal draws onto
        """
        super().__init__(window)
        self.me_name = ""
        self.opp_name = ""
        self.me_side = "white"
        self.opp_side = "black"
        self.me_country = ""
        self.opp_country = ""
        self.rating = "1500"
        self.rematch = False
        self.on_done: Callable[[], None] | None = None
        self.me_palette: tuple[pg.Color, pg.Color] | None = None
        self.opp_palette: tuple[pg.Color, pg.Color] | None = None
        self._started_at = 0
        self._seconds = 3
        self._font_cache: dict[str, Any] = {}

    def show(self, white_name: str, black_name: str,  # type: ignore[override]
             your_color: str,
             on_done: Callable[[], None], seconds: int = 3, white_country: str = "",
             black_country: str = "", rematch: bool = False) -> None:
        """
        Introduce the pairing and start the countdown, arranging the pair so
        the local player is always on the left. The card starts the game
        itself once the countdown runs out

        :param white_name: nickname of the player with white
        :param black_name: nickname of the player with black
        :param your_color: white or black, the side this client was given
        :param on_done: run when the countdown ends, which starts the game
        :param seconds: length of the countdown in seconds
        :param white_country: ISO country code for white's flag, empty for none
        :param black_country: ISO country code for black's flag, empty for none
        :param rematch: True to greet a rematch instead of a fresh pairing
        """
        self.rematch = rematch
        if your_color == "white":
            self.me_name, self.me_side, self.me_country = white_name, "white", white_country
            self.opp_name, self.opp_side, self.opp_country = black_name, "black", black_country
        else:
            self.me_name, self.me_side, self.me_country = black_name, "black", black_country
            self.opp_name, self.opp_side, self.opp_country = white_name, "white", white_country
        self.on_done = on_done
        self._seconds = seconds
        self._started_at = pg.time.get_ticks()
        self.me_palette = avatar_palette(self.me_name)
        self.opp_palette = avatar_palette(self.opp_name)
        super().show()

    def hide(self) -> None:
        """
        Close the card and forget the start callback, so one pairing can never
        start two games
        """
        super().hide()
        self.on_done = None

    def update(self) -> None:
        """
        Advance the countdown once per frame and fire the start callback the
        moment it runs out, with the card hidden first. The coordinator calls
        this every frame while an online session exists
        """
        if not self.visible:
            return
        elapsed = (pg.time.get_ticks() - self._started_at) / 1000.0
        if elapsed >= self._seconds:
            done = self.on_done
            self.hide()
            if done is not None:
                done()

    def _remaining(self) -> int:
        """
        Work out the number the countdown should be showing, floored at one so
        the card never reads zero in the frame before it closes

        :returns: whole seconds still to go
        """
        elapsed = (pg.time.get_ticks() - self._started_at) / 1000.0
        return max(self._seconds - int(elapsed), 1)

    def _fonts(self, panel_w: int) -> tuple[pg.font.Font, pg.font.Font, pg.font.Font,
                                            pg.font.Font, pg.font.Font, pg.font.Font]:
        """
        Fetch the card's six fonts for the current panel width, rebuilt only
        when that width changes so no font is loaded per frame

        :param panel_w: panel width in pixels the fonts are sized from
        :returns: eyebrow, name, rating, versus, countdown and avatar-letter
            fonts
        """
        return cast(tuple[pg.font.Font, pg.font.Font, pg.font.Font,
                          pg.font.Font, pg.font.Font, pg.font.Font],
                    fonts_for_width(self._font_cache, panel_w, self._build_fonts))

    def _build_fonts(self, panel_w: float) -> tuple[pg.font.Font, pg.font.Font, pg.font.Font,
                                                    pg.font.Font, pg.font.Font, pg.font.Font]:
        """
        Size all six fonts from the panel width, each with a floor so nothing
        becomes unreadable in a small window

        :param panel_w: panel width in pixels
        :returns: eyebrow, name, rating, versus, countdown and avatar-letter
            fonts
        """
        av = max(int(panel_w * 0.118), 44)
        return (
            get_font(max(int(panel_w * 0.028), 11), bold=True),
            get_font(max(int(panel_w * 0.032), 13), bold=True),
            get_mono_font(max(int(panel_w * 0.025), 10)),
            get_display_font(max(int(panel_w * 0.06), 22)),
            get_font(max(int(panel_w * 0.028), 11), bold=True),
            get_display_font(max(int(av * 0.42), 16)),
        )

    def draw(self) -> None:
        """
        Paint the card: the MATCH FOUND or REMATCH line at the top, the two
        players either side of the crossed-swords mark, and the countdown
        underneath, in a panel sized to exactly what is drawn
        """
        if not self.visible or self.rect.width <= 0:
            return
        pad = self.padding
        panel_w = min(self.rect.width, MODAL_MAX_WIDTH)
        (eyebrow_font, name_font, rating_font, vs_font,
         cd_font, letter_font) = self._fonts(panel_w)
        av = max(int(panel_w * 0.118), 44)

        eyebrow_label = "REMATCH!" if self.rematch else "MATCH FOUND"
        eyebrow = eyebrow_font.render(eyebrow_label, True, Colors.text_dim)
        vs_surf = emoji_surface("⚔️", max(int(panel_w * 0.08), 30))
        if vs_surf is None:
            vs_surf = stroked_text(vs_font, "VS", Colors.accent, Colors.outcome_stroke,
                                   max(int(vs_font.get_height() * 0.04), 1))
        card_h = (av + AVATAR_NAME_GAP + name_font.get_height() + NAME_RATING_GAP
                  + rating_font.get_height())
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
                        self.me_country, name_font, rating_font, letter_font,
                        cast(tuple[pg.Color, pg.Color], self.me_palette))
        self._draw_card(content.right - side_w / 2, y, av, side_w, card_h, self.opp_name,
                        self.opp_country, name_font, rating_font, letter_font,
                        cast(tuple[pg.Color, pg.Color], self.opp_palette))
        self.window.blit(vs_surf, (content.centerx - vs_surf.get_width() / 2,
                                   y + (card_h - vs_surf.get_height()) / 2))
        y += vs_block_h + g_vs_bottom

        label = cd_font.render("STARTING IN ", True, Colors.text_dim)
        number = cd_font.render(str(self._remaining()), True, Colors.amber_hi)
        total_w = label.get_width() + number.get_width()
        cx = content.centerx - total_w / 2
        self.window.blit(label, (cx, y))
        self.window.blit(number, (cx + label.get_width(), y))

    def _draw_card(self, cx: float, y: float, av: int, side_w: float, card_h: int,
                   name: str, country: str, name_font: pg.font.Font,
                   rating_font: pg.font.Font, letter_font: pg.font.Font,
                   palette: tuple[pg.Color, pg.Color]) -> None:
        """
        Draw one of the two players: their avatar with their initial on it,
        then their flag and nickname, then the rating line underneath

        :param cx: horizontal centre of this player's half, in window pixels
        :param y: top of the player block, in window pixels
        :param av: avatar width and height in pixels
        :param side_w: width this half may use, which the nickname is fitted to
        :param card_h: full height of the player block in pixels
        :param name: nickname to show
        :param country: ISO country code for the flag, empty for none
        :param name_font: font for the nickname
        :param rating_font: font for the rating line
        :param letter_font: font for the initial drawn on the avatar
        :param palette: avatar fill colour and the colour of the initial on it
        """
        fill, letter_color = palette
        self.window.blit(build_flat_avatar(av, fill), (cx - av / 2, y))
        letter = (name[:1].upper() if name else "?")
        glyph = letter_font.render(letter, True, letter_color)
        self.window.blit(glyph, (cx - glyph.get_width() / 2,
                                 y + av / 2 - glyph.get_height() / 2))
        flag = flag_surface(country, name_font.get_height())
        flag_w = (flag.get_width() + FLAG_NAME_GAP) if flag is not None else 0
        name_surf = name_font.render(name, True, Colors.text)
        name_surf = fit_text_to_rect(
            name_surf, pg.Rect(0, 0, max(side_w - flag_w, 1), name_surf.get_height()),
            padding=0)
        ny = y + av + AVATAR_NAME_GAP
        gx = cx - (flag_w + name_surf.get_width()) / 2
        if flag is not None:
            self.window.blit(flag, (gx, ny + name_surf.get_height() / 2 - flag.get_height() / 2))
            gx += flag.get_width() + FLAG_NAME_GAP
        self.window.blit(name_surf, (gx, ny))
        rating = rating_font.render(self.rating, True, Colors.text_muted)
        self.window.blit(rating, (cx - rating.get_width() / 2,
                                  ny + name_surf.get_height() + NAME_RATING_GAP))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Ignore clicks: the card has no buttons and cannot be dismissed, so the
        countdown is the only way past it. The shell still swallows the click
        while the card is topmost, so nothing behind it reacts either

        :param pos: click position in window pixels
        :returns: always False, since nothing here acts on a click
        """
        return False
