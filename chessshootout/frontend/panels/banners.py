from collections.abc import Callable
from typing import Any

import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cut_rect_surface
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_font


PAD_L = 18
PAD_R = 16
PAD_V = 13
GAP = 14
ACTS_GAP = 8
ICON_SIZE = 30
ICON_CUT = 4
TOP_MARGIN = 14
STACK_GAP = 9
BTN_MIN_W = 78
BTN_CUT = 6
BTN_PAD_X = 14
BTN_PAD_Y = 8
SLIDE_MS = 260
EXIT_MS = 200


def _button_surface(label: str, font: pg.font.Font, ok: bool) -> pg.Surface:
    """
    Draw one of the two answer buttons a banner carries, sized around its own
    label so Accept and Decline stay readable next to each other. The
    accepting button is filled with the accent colour, the declining one is a
    plain outlined chip

    :param label: button text, such as Accept or Deny
    :param font: font the label is rendered in
    :param ok: True for the accepting button, which gets the accent fill
    :returns: the finished button surface, ready to blit
    """
    text = font.render(label, True, Colors.on_accent if ok else Colors.text)
    w = max(text.get_width() + 2 * BTN_PAD_X, BTN_MIN_W)
    h = text.get_height() + 2 * BTN_PAD_Y
    if ok:
        shape = cut_rect_surface((w, h), BTN_CUT, Colors.accent, corners=("tr", "bl"))
    else:
        shape = cut_rect_surface((w, h), BTN_CUT, Colors.surface_raised,
                                 border=Colors.border, border_width=1, corners=("tr", "bl"))
    surf = pg.Surface((w, h), pg.SRCALPHA)
    surf.blit(shape, (0, 0))
    surf.blit(text, ((w - text.get_width()) / 2, (h - text.get_height()) / 2))
    return surf


class OfferBanners:
    """
    The stack of offers the opponent has made -- a draw, a takeback, a rematch
    -- shown as cards that slide down over the board with an Accept and a
    Decline button. The online coordinator owns them end to end: it pushes and
    dismisses them, while the app shell draws the stack and routes clicks here
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Start with an empty stack. One instance is built beside the online
        coordinator at startup and reused for every game

        :param window: the app window every banner is drawn onto
        """
        self.window = window
        self._banners = []

    def push(self, key: str, icon: str, name: str, verb: str, yes_label: str,
             no_label: str, on_yes: Callable[[], None],
             on_no: Callable[[], None]) -> None:
        """
        Put a new offer on screen, sliding in below whatever is already
        stacked. Pushing the same kind of offer twice replaces the first one,
        so a repeated request never leaves two banners asking the same thing

        :param key: offer kind, such as draw_offered, which also identifies it
            for a later dismiss
        :param icon: emoji shown in the banner's chip
        :param name: opponent's display name, shown before the verb
        :param verb: what they are asking, such as offers a draw
        :param yes_label: text on the accepting button
        :param no_label: text on the declining button
        :param on_yes: run when the accepting button is clicked
        :param on_no: run when the declining button is clicked
        """
        self._banners = [b for b in self._banners if b["key"] != key]
        self._banners.append({
            "key": key, "icon": icon, "name": name, "verb": verb,
            "yes_label": yes_label, "no_label": no_label,
            "on_yes": on_yes, "on_no": on_no,
            "pushed_at": pg.time.get_ticks(), "leaving_at": None,
            "ok_rect": pg.Rect(0, 0, 0, 0), "no_rect": pg.Rect(0, 0, 0, 0),
        })

    def clear(self) -> None:
        """
        Drop every banner at once with no exit animation, used when a game
        ends, a new one starts or the session is torn down
        """
        self._banners = []

    def dismiss(self, key: str) -> None:
        """
        Answer or withdraw one offer, sliding that banner back up out of view
        instead of making it vanish. A banner already on its way out is left
        alone, so its exit is never restarted

        :param key: offer kind to take down, as given to push
        """
        now = pg.time.get_ticks()
        for b in self._banners:
            if b["key"] == key and b["leaving_at"] is None:
                b["leaving_at"] = now

    def is_empty(self) -> bool:
        """
        Whether there is any offer still standing, which the input router asks
        before letting Esc dismiss the stack

        :returns: True when nothing is waiting to be answered
        """
        return self.count() == 0

    def needs_frames(self) -> bool:
        """
        Whether the stack still has something to animate, including banners
        that are only sliding out. The shell keeps presenting whole frames
        while this is true, so an exit is never left half drawn

        :returns: True while any banner is on screen or leaving
        """
        return bool(self._banners)

    def count(self) -> int:
        """
        How many offers are still waiting for an answer, counting only banners
        that have not started sliding out

        :returns: number of live offers
        """
        return sum(1 for b in self._banners if b["leaving_at"] is None)

    def _banner_height(self, name_font: pg.font.Font, btn_font: pg.font.Font) -> int:
        """
        Work out how tall every banner in the stack is, from the tallest thing
        it has to hold -- the icon chip, the message or the buttons. One height
        is shared by all of them so the stack spaces evenly

        :param name_font: font the opponent's name is rendered in
        :param btn_font: font the two button labels are rendered in
        :returns: banner height in pixels
        """
        content_h = max(ICON_SIZE, name_font.get_height(),
                        btn_font.get_height() + 2 * BTN_PAD_Y)
        return content_h + 2 * PAD_V

    def _fonts(self) -> tuple[pg.font.Font, pg.font.Font, pg.font.Font]:
        """
        Hand back the three fonts a banner is drawn with, building them the
        first time one is actually needed rather than at startup

        :returns: the name, verb and button fonts, in that order
        """
        if getattr(self, "_name_font", None) is None:
            self._name_font = get_font(13, bold=True)
            self._verb_font = get_font(13, bold=True)
            self._btn_font = get_font(12, bold=True)
        return self._name_font, self._verb_font, self._btn_font

    def draw(self, board_rect: pg.Rect) -> None:
        """
        Paint the whole stack across the top of the board, each banner eased
        down from above and each one that has been answered eased back up. A
        banner whose exit has finished is dropped here, so the stack tidies
        itself as it draws, and everything is clipped to the given area so
        nothing spills over the rest of the window

        :param board_rect: area the banners are centred over and clipped to,
            the board on the game screen and the whole content area elsewhere
        """
        if not self._banners or board_rect.width <= 0:
            return
        name_font, verb_font, btn_font = self._fonts()
        h = self._banner_height(name_font, btn_font)
        now = pg.time.get_ticks()
        self._banners = [b for b in self._banners if b["leaving_at"] is None
                         or now - b["leaving_at"] < EXIT_MS]
        prev_clip = self.window.get_clip()
        self.window.set_clip(board_rect)
        target_y = board_rect.top + TOP_MARGIN
        for b in self._banners:
            t = min(1.0, (now - b["pushed_at"]) / SLIDE_MS)
            eased = 1 - (1 - t) ** 3
            start_y = board_rect.top - h
            y = start_y + (target_y - start_y) * eased
            if b["leaving_at"] is not None:
                t2 = min(1.0, (now - b["leaving_at"]) / EXIT_MS)
                eased2 = 1 - (1 - t2) ** 3
                y = y + (start_y - y) * eased2
            self._draw_one(b, board_rect, y, h, name_font, verb_font, btn_font)
            target_y += h + STACK_GAP
        self.window.set_clip(prev_clip)

    def _draw_one(self, b: dict[str, Any], board_rect: pg.Rect, y: float, h: int,
                  name_font: pg.font.Font, verb_font: pg.font.Font,
                  btn_font: pg.font.Font) -> None:
        """
        Paint a single banner -- icon chip, "name asks this" message and the
        two buttons -- centred over the board and wide enough for whatever it
        says. It also records where the buttons landed, which is what makes
        them clickable, so a banner is only answerable once it has been drawn

        :param b: the banner record being drawn, updated in place with the two
            button rects
        :param board_rect: area the banner is centred over
        :param y: top edge in window pixels, wherever the slide has reached
        :param h: banner height in pixels, shared by the whole stack
        :param name_font: font for the opponent's name
        :param verb_font: font for what they are asking
        :param btn_font: font for the two button labels
        """
        name_surf = name_font.render(b["name"], True, Colors.amber_hi)
        verb_surf = verb_font.render(f" {b['verb']}", True, Colors.text)
        msg_w = name_surf.get_width() + verb_surf.get_width()
        no_surf = _button_surface(b["no_label"], btn_font, False)
        ok_surf = _button_surface(b["yes_label"], btn_font, True)
        acts_w = no_surf.get_width() + ACTS_GAP + ok_surf.get_width()
        w = PAD_L + ICON_SIZE + GAP + msg_w + GAP + acts_w + PAD_R
        x = board_rect.centerx - w / 2
        panel_cut = max(int(h * 0.22), 4)
        panel = cut_rect_surface((int(w), int(h)), panel_cut, Colors.surface,
                                 border=Colors.border_strong, border_width=1,
                                 corners=("tr", "bl"))
        self.window.blit(panel, (x, y))
        cy = y + h / 2
        ix = x + PAD_L
        chip = cut_rect_surface((ICON_SIZE, ICON_SIZE), ICON_CUT, Colors.icon_chip_bg,
                                corners=("tr", "bl"))
        self.window.blit(chip, (ix, cy - ICON_SIZE / 2))
        glyph = emoji_surface(b["icon"], 17)
        if glyph is not None:
            self.window.blit(glyph, (ix + (ICON_SIZE - glyph.get_width()) / 2,
                                     cy - glyph.get_height() / 2))
        mx = ix + ICON_SIZE + GAP
        self.window.blit(name_surf, (mx, cy - name_surf.get_height() / 2))
        self.window.blit(verb_surf, (mx + name_surf.get_width(),
                                     cy - verb_surf.get_height() / 2))
        ax = mx + msg_w + GAP
        self.window.blit(no_surf, (ax, cy - no_surf.get_height() / 2))
        ox = ax + no_surf.get_width() + ACTS_GAP
        self.window.blit(ok_surf, (ox, cy - ok_surf.get_height() / 2))
        b["no_rect"] = pg.Rect(ax, cy - no_surf.get_height() / 2,
                               no_surf.get_width(), no_surf.get_height())
        b["ok_rect"] = pg.Rect(ox, cy - ok_surf.get_height() / 2,
                               ok_surf.get_width(), ok_surf.get_height())

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Answer whichever banner button was clicked, which is how a draw,
        takeback or rematch is accepted or declined. The banner starts sliding
        out before its callback runs, so one answer can never be sent twice,
        and a banner already leaving ignores clicks altogether

        :param pos: click position in window pixels
        :returns: True when a button took the click, which stops it reaching
            the board underneath
        """
        for b in list(self._banners):
            if b["leaving_at"] is not None:
                continue
            if b["ok_rect"].collidepoint(pos):
                b["leaving_at"] = pg.time.get_ticks()
                b["on_yes"]()
                return True
            if b["no_rect"].collidepoint(pos):
                b["leaving_at"] = pg.time.get_ticks()
                b["on_no"]()
                return True
        return False
