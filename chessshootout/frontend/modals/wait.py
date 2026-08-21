import math
from collections.abc import Callable

import pygame as pg

from chessshootout.frontend.modals.base import BaseModal, MODAL_MAX_WIDTH, MODAL_RAIL
from chessshootout.frontend.visual.clock_visual import format_countdown
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample, rounded_rect_surface, circle_surface
from chessshootout.frontend.visual.widgets import draw_button_row
from chessshootout.frontend.visual.fonts import (
    fonts_for_width, get_display_font, get_font, get_mono_font,
)


RADAR_SWEEP_MS = 1400
RADAR_PING_MS = 1600
_SWEEP_CACHE = {}

PILL_VPAD = 12
PILL_INSET = 14
PILL_GAP = 8
PILL_HPAD = 28


def _radar_sweep(size: int, color: str) -> pg.Surface:
    """
    Build, and from then on reuse, the radar's sweeping wedge: an arc that
    fades out behind its leading edge, with a hole in the middle. It is drawn
    once per size and colour and only rotated after that

    :param size: sweep diameter in pixels
    :param color: sweep colour as a hex string
    :returns: sweep surface, brightest along its leading edge
    """
    key = (size, color)
    if key not in _SWEEP_CACHE:
        def render(surf: pg.Surface, k: int) -> None:
            """
            Draw the sweep at supersampled scale as a fan of thin wedges, each
            a little more opaque than the last, then punch the centre out

            :param surf: oversized surface being drawn into
            :param k: supersample factor every size must be multiplied by
            """
            s = surf.get_width()
            cx = cy = s / 2
            outer = s / 2
            inner = s * 0.40
            base = pg.Color(color)
            steps = 120
            for i in range(steps):
                frac = i / steps
                if frac < 0.55:
                    continue
                alpha = int(210 * (frac - 0.55) / 0.45)
                a0 = math.radians(i * 360 / steps)
                a1 = math.radians((i + 1) * 360 / steps)
                col = pg.Color(base.r, base.g, base.b, alpha)
                pg.draw.polygon(surf, col, [
                    (cx, cy),
                    (cx + outer * math.cos(a0), cy + outer * math.sin(a0)),
                    (cx + outer * math.cos(a1), cy + outer * math.sin(a1)),
                ])
            pg.draw.circle(surf, (0, 0, 0, 0), (int(cx), int(cy)), int(inner))
        _SWEEP_CACHE[key] = supersample(int(size), render)
    return _SWEEP_CACHE[key]


class WaitModal(BaseModal):
    """
    The card shown while matchmaking is looking for an opponent: a radar
    sweep, the mode and time control being searched for, and how long it has
    been going. The online coordinator owns it, it wears the shared modal
    shell, and Esc cancels the search through it
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build the card once at startup; it stays hidden until a search
        actually starts

        :param window: the app window surface this modal draws onto
        """
        super().__init__(window)
        self.mode_label = ""
        self.tc_text = ""
        self.elapsed = 0
        self.on_cancel = None
        self.button_rects = {}
        self._font_cache = {}

    def show(self, mode_label: str, tc_text: str, on_cancel: Callable[[], None]) -> None:
        """
        Open the card on the match being looked for, with the elapsed counter
        back at zero

        :param mode_label: speed category being searched, such as Blitz
        :param tc_text: time control as text, such as 5 + 0
        :param on_cancel: run when the player calls the search off
        """
        super().show()
        self.mode_label = mode_label
        self.tc_text = tc_text
        self.elapsed = 0
        self.on_cancel = on_cancel

    def set_elapsed(self, seconds: int) -> None:
        """
        Update how long the search has been running, which the coordinator
        works out each frame from when the search began

        :param seconds: whole seconds since the search started
        """
        self.elapsed = seconds

    def hide(self) -> None:
        """
        Close the card and forget the cancel callback, so a late click cannot
        call off a search that has already found somebody
        """
        super().hide()
        self.on_cancel = None
        self.button_rects = {}

    def _draw_radar(self, cx: float, cy: float, size: int) -> None:
        """
        Draw the radar that gives the wait a pulse: a faint ring, an expanding
        ping, the rotating sweep and the dot at the centre, all animated from
        the frame clock

        :param cx: horizontal centre in window pixels
        :param cy: vertical centre in window pixels
        :param size: radar diameter in pixels
        """
        now = pg.time.get_ticks()
        lsize = int(size * 1.4)
        pt = (now % RADAR_PING_MS) / RADAR_PING_MS

        def render(surf: pg.Surface, k: int) -> None:
            """
            Draw the ring and the ping expanding out of it at supersampled
            scale, both fading as the ping travels

            :param surf: oversized surface being drawn into
            :param k: supersample factor every size must be multiplied by
            """
            s = surf.get_width()
            c = (s / 2, s / 2)
            r = (size / 2) * k
            stroke = max(int(2 * k), 2)
            ring = pg.Color(Colors.accent)
            ring.a = 80
            pg.draw.circle(surf, ring, c, int(r - k), stroke)
            ping = pg.Color(Colors.accent)
            ping.a = int(180 * (1 - pt))
            pg.draw.circle(surf, ping, c, max(int(r * (0.7 + 0.55 * pt)), 1), stroke)
        self.window.blit(supersample(lsize, render),
                         (cx - lsize / 2, cy - lsize / 2))
        sweep = pg.transform.rotozoom(
            _radar_sweep(int(size), Colors.accent),
            -(now % RADAR_SWEEP_MS) / RADAR_SWEEP_MS * 360, 1.0)
        self.window.blit(sweep, (cx - sweep.get_width() / 2, cy - sweep.get_height() / 2))
        dot = circle_surface(max(int(size * 0.12), 6), Colors.accent)
        self.window.blit(dot, (cx - dot.get_width() / 2, cy - dot.get_height() / 2))

    def _fonts(self, panel_w: int) -> tuple[pg.font.Font, pg.font.Font, pg.font.Font,
                                            pg.font.Font, pg.font.Font, pg.font.Font]:
        """
        Fetch the card's six fonts for the current panel width, rebuilt only
        when that width changes so no font is loaded per frame

        :param panel_w: panel width in pixels the fonts are sized from
        :returns: title, sub-line, mode, time-control, elapsed and button fonts
        """
        return fonts_for_width(self._font_cache, panel_w, self._build_fonts)

    def _build_fonts(self, panel_w: int) -> tuple[pg.font.Font, pg.font.Font, pg.font.Font,
                                                  pg.font.Font, pg.font.Font, pg.font.Font]:
        """
        Size all six fonts from the panel width, each with a floor so the card
        stays readable in a small window

        :param panel_w: panel width in pixels
        :returns: title, sub-line, mode, time-control, elapsed and button fonts
        """
        return (
            get_display_font(max(int(panel_w * 0.06), 20)),
            get_font(max(int(panel_w * 0.03), 12), bold=False),
            get_font(max(int(panel_w * 0.024), 9), bold=True),
            get_mono_font(max(int(panel_w * 0.034), 13), bold=True),
            get_mono_font(max(int(panel_w * 0.03), 11)),
            get_font(max(int(panel_w * 0.034), 13), bold=True),
        )

    def draw(self) -> None:
        """
        Paint the card: radar, heading, the pill holding the mode and time
        control, the elapsed counter and the Cancel search button, in a panel
        sized to exactly what is drawn. Drawing is also what fixes the button
        rect clicks are tested against
        """
        if not self.visible or self.rect.width <= 0:
            self.button_rects = {}
            return
        pad = self.padding
        panel_w = min(self.rect.width, MODAL_MAX_WIDTH)
        (title_font, sub_font, mode_font, tc_font,
         elapsed_font, button_font) = self._fonts(panel_w)
        radar = min(68, max(int(panel_w * 0.15), 52))

        title = title_font.render("SEARCHING…", True, Colors.text)
        sub = sub_font.render("Finding you an opponent", True, Colors.text_dim)
        elapsed = elapsed_font.render(
            f"elapsed {format_countdown(self.elapsed)}", True, Colors.text_muted)
        mode = mode_font.render(self.mode_label.upper(), True, Colors.amber_hi)
        tc = tc_font.render(self.tc_text, True, Colors.text)
        pill_h = max(mode.get_height(), tc.get_height()) + PILL_VPAD
        pill_w = mode.get_width() + PILL_GAP + tc.get_width() + PILL_HPAD

        g = max(int(panel_w * 0.03), 12)
        g2 = max(int(panel_w * 0.012), 5)
        btn_h = max(int(panel_w * 0.11), 38)
        panel_h = (MODAL_RAIL + pad + radar + g + title.get_height() + g2
                   + sub.get_height() + g + pill_h + g2 + elapsed.get_height()
                   + g + btn_h + pad)
        panel = pg.Rect(0, 0, panel_w, panel_h)
        panel.center = self.rect.center

        self.draw_shell(None, panel)
        content = self.content_rect(panel)
        cx = content.centerx
        y = content.y
        self._draw_radar(cx, y + radar / 2, radar)
        y += radar + g
        self.window.blit(title, (cx - title.get_width() / 2, y))
        y += title.get_height() + g2
        self.window.blit(sub, (cx - sub.get_width() / 2, y))
        y += sub.get_height() + g

        pill = rounded_rect_surface((int(pill_w), int(pill_h)), pill_h // 2,
                                    Colors.surface, border=Colors.border)
        px = cx - pill_w / 2
        self.window.blit(pill, (px, y))
        pcy = y + pill_h / 2
        self.window.blit(mode, (px + PILL_INSET, pcy - mode.get_height() / 2))
        self.window.blit(tc, (px + PILL_INSET + mode.get_width() + PILL_GAP,
                              pcy - tc.get_height() / 2))
        y += pill_h + g2
        self.window.blit(elapsed, (cx - elapsed.get_width() / 2, y))

        row = pg.Rect(content.x, content.bottom - btn_h, content.width, btn_h)
        self.button_rects = draw_button_row(
            self.window, row, [("Cancel search", "cancel")], button_font, pad, cut=True)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Turn a click on Cancel search into calling the search off, with the
        card hidden first so the callback finds it already gone

        :param pos: click position in window pixels
        :returns: True when the button took the click
        """
        if not self.visible:
            return False
        for key, br in self.button_rects.items():
            if br.collidepoint(pos):
                callback = self.on_cancel
                self.hide()
                if callback is not None:
                    callback()
                return True
        return False
