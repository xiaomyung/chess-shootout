from collections.abc import Iterable
from typing import Any

import pygame as pg

from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.frontend.board import Board
from chessshootout.infra.countries import flag_emoji, name_for
from chessshootout.frontend.visual.clock_visual import (
    LOW_TIME_FRACTION, format_clock, format_countdown,
)
from chessshootout.frontend.visual.cache import new_cache, memoized_surface, render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    rounded_rect_surface, blit_centered, circle_surface, cut_rect_surface, scale_floor,
    cosine_pulse, build_tooltip_bubble,
)
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_font, DISPLAY
from chessshootout.frontend.visual.widgets import (
    StripAvatar, build_ko_badge, KO_WINK_MS, strip_frame_metrics, draw_captured_row,
)


AUTO_END_RED_THRESHOLD_SECONDS = 10
AUTO_END_BADGE_FONT_SCALE = 0.75

GIVE_TIME_FLASH_MS = 520
GIVE_TIME_FLASH_PEAK_ALPHA = 150
GIVE_TIME_FLOAT_MS = 1000
TWO_ROW_MIN_IH = 26
TOOLTIP_EASE = 0.22
GIVE_TIME_FADE_IN_FRACTION = 0.3
GIVE_TIME_FADE_OUT_FRACTION = 1 - GIVE_TIME_FADE_IN_FRACTION
GIVE_TIME_FLOAT_RISE_PX = 6
GIVE_TIME_FLOAT_TRAVEL_PX = 28
PILL_HEIGHT_UNCAPPED = 10 ** 6
TOOLTIP_RISE_PX = 5
TOOLTIP_GAP_PX = 5
TOOLTIP_EDGE_MARGIN_PX = 2
STRIP_FRAME_CUT = 12
STRIP_PULSE_MS = 1000
PULSE_QUANT_STEPS = 16
CLOCK_WELL_RADIUS = 7
CLOCK_WELL_PAD_X = 13
CLOCK_WELL_PAD_Y = 5
CLOCK_RIGHT_MARGIN = 8
SHARING_PILL_TEXT = "SHARING MARKS"
SHARING_DOT_PULSE_MS = 1600
SHARING_DOT_MIN_ALPHA = 90

_TOOLTIP_BASE_CACHE = new_cache()


def is_white(color: PieceColor | str) -> bool:
    """
    Say whether a colour is White, accepting either the engine's own colour or
    the plain "white" the server and the screens pass around. The game and
    review screens lean on it to decide which player goes on which strip

    :param color: side to test, as a piece colour or as "white" or "black"
    :returns: True when that side is White
    """
    return color in (PieceColor.WHITE, "white")


def top_strip_color(flipped: bool) -> PieceColor:
    """
    Say which colour sits on the top strip for the board's current
    orientation. Black is on top with White at the bottom, and flipping the
    board swaps the two

    :param flipped: True when the board is turned so Black is at the bottom
    :returns: the colour shown on the top strip
    """
    return PieceColor.WHITE if flipped else PieceColor.BLACK


def give_time_float_alpha(progress: float) -> int:
    """
    Shape the fade of the "+0:15" label that floats up when a player is handed
    clock time: a quick fade in, then a longer fade out. Anything outside the
    animation is fully transparent, which is what stops it drawing at all

    :param progress: how far through the float animation, 0 at the start and 1
        at the end
    :returns: alpha from 0 to 255 for this moment of the animation
    """
    if progress < 0 or progress >= 1:
        return 0
    ramp = (progress / GIVE_TIME_FADE_IN_FRACTION
            if progress < GIVE_TIME_FADE_IN_FRACTION
            else (1 - progress) / GIVE_TIME_FADE_OUT_FRACTION)
    return max(0, min(255, int(255 * ramp)))


def refresh_capture_icons(board: Board, strip_height: float,
                          strips: Iterable[Any]) -> None:
    """
    Hand both strips a set of captured-piece icons scaled for their new
    height, so the little pieces beside a player's name stay crisp after a
    resize. The board owns the artwork, and until it has loaded its pieces
    there is nothing to share, so the strips simply keep what they had

    :param board: board the piece artwork is scaled from
    :param strip_height: height of one player strip in pixels
    :param strips: the strips to update, game or review flavour alike
    """
    icons = board.scaled_capture_icons(strip_height)
    if icons is None:
        return
    for strip in strips:
        strip.set_piece_icons(icons)


class PlayerStrip:
    """
    One player's band above or below the board: avatar, name, flag, rating,
    the pieces they have taken, their material lead, their clock and any
    countdown that is about to end the game. The game screen pushes the whole
    state in every frame and this only draws it -- it decides nothing itself
    """

    def __init__(self, window: pg.Surface) -> None:
        """
        Build an empty strip with placeholder fonts. Two of these are made
        once when the game screen is created and reused for every game, so
        every field here is overwritten before anything is drawn

        :param window: the app window this strip paints into
        """
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.name = ""
        self.player_color = PieceColor.WHITE
        self.is_bot = False
        self.rating = None
        self.clock_seconds = None
        self.clock_initial_seconds = None
        self.active = False
        self.captured = []
        self.advantage = 0
        self.captured_color = None
        self.connection_state = None
        self.country = None
        self.auto_end_label = None
        self.auto_end_seconds = None
        self.ko_count = 0
        self._flash_until_ms = 0
        self._give_time_start_ms = 0
        self._give_time_amount = 0
        self._ko_wink_until_ms = 0
        self.scale = 1.0
        self.sharing = False
        self.sharing_color = None
        self.name_font = get_font(14, bold=True)
        self.rating_font = get_font(11, bold=True, mono=True)
        self._clock_px = 16
        self.clock_font = get_font(16, bold=True, mono=True)
        self.sharing_font = get_font(9, bold=True, mono=True)
        self.advantage_font = get_font(12, bold=True)
        self.ko_font = get_font(10, bold=True)
        self.letter_font = get_font(18, family=DISPLAY)
        self.auto_end_font = get_font(11, bold=True)
        self._give_time_float_font = get_font(11, bold=True, mono=True)
        self.icons = {}
        self._avatar = StripAvatar()
        self._flag_cache = None
        self._flag_rect = pg.Rect(0, 0, 0, 0)
        self._tooltip_alpha = 0.0
        self.tooltip_font = get_font(10, mono=True)
        self._clock_cache = None
        self._sharing_dot_cache = None
        self._tooltip_owned = None
        self._auto_end_cache = None
        self._name_clip_cache = None

    def set_rect(self, rect: pg.Rect, scale: float = 1.0) -> None:
        """
        Place the strip and rebuild every font against its new height, which
        is how the whole band scales with the window. Each cached surface that
        was sized for the old fonts is dropped here, so nothing stale survives
        a resize

        :param rect: the strip's area in window pixels
        :param scale: the layout's global scale factor, 1.0 at the reference
            window size
        """
        self.scale = scale
        self.rect = pg.Rect(rect)
        h = rect.height
        ih = max(int(h * 0.68), 1)
        self._clock_px = max(int(h * 0.5), 14)
        self.name_font = get_font(max(int(ih * 0.42), 11), bold=True)
        self.rating_font = get_font(max(int(ih * 0.26), 8), bold=True, mono=True)
        self.clock_font = get_font(self._clock_px, bold=True, mono=True)
        self.sharing_font = get_font(max(int(ih * 0.22), 8), bold=True, mono=True)
        self.advantage_font = get_font(max(int(ih * 0.26), 8), bold=True)
        self.ko_font = get_font(max(int(ih * 0.3), 8), bold=True)
        self.letter_font = get_font(max(int(ih * 0.5), 11), family=DISPLAY)
        self.auto_end_font = get_font(
            max(int(ih * 0.42 * AUTO_END_BADGE_FONT_SCALE), 9), bold=True)
        self.tooltip_font = get_font(scale_floor(10, scale, 9), mono=True)
        self._give_time_float_font = get_font(
            max(int(h * 0.24), 11), bold=True, mono=True)
        self._avatar.reset()
        self._clock_cache = None
        self._auto_end_cache = None
        self._name_clip_cache = None

    def set_piece_icons(self, icons: dict[tuple[PieceType, PieceColor], pg.Surface]) -> None:
        """
        Adopt the captured-piece artwork the board scaled for this strip's
        height, used to draw the row of pieces a player has taken

        :param icons: piece type and colour to its scaled sprite
        """
        self.icons = icons

    def set_state(self, name: str, clock_seconds: float | None, active: bool,
                  captured: list[PieceType] | None = None, advantage: int = 0,
                  captured_color: PieceColor | None = None,
                  connection_state: str | None = None,
                  clock_initial_seconds: float | None = None,
                  auto_end_label: str | None = None,
                  auto_end_seconds: float | None = None,
                  player_color: PieceColor = PieceColor.WHITE,
                  is_bot: bool = False, rating: str | None = None, ko_count: int = 0,
                  country: str | None = None,
                  sharing: bool = False, sharing_color: str | None = None) -> None:
        """
        Take this frame's whole picture of one player from the game screen.
        Every field is replaced outright, so the strip never holds an opinion
        of its own; the one thing it notices is the KO count going up, which
        winks the badge

        :param name: display name shown beside the avatar
        :param clock_seconds: time that side has left in seconds, None when the
            game is untimed
        :param active: True when it is that side's turn, which lights the frame
        :param captured: pieces this player has taken, strongest first
        :param advantage: material lead in pawn units; only a positive number
            shows a badge
        :param captured_color: colour of the taken pieces, which picks their
            artwork
        :param connection_state: opponent's connection as connected,
            reconnecting or resyncing; None hides the dot
        :param clock_initial_seconds: starting time per side in seconds, what
            the low-time warning is measured against
        :param auto_end_label: wording of the countdown badge, such as Resign
            in; None when nothing is counting down
        :param auto_end_seconds: seconds left on that countdown
        :param player_color: side this strip belongs to
        :param is_bot: True when this seat is played by the bot
        :param rating: rating shown in the pill beside the name, None to hide
            it
        :param ko_count: how many pieces this player has taken, shown as the KO
            badge
        :param country: two-letter country code for the flag, blank for none
        :param sharing: True while this player is broadcasting their board
            marks
        :param sharing_color: colour of the sharing pill, each side having its
            own accent
        """
        self.name = name
        self.player_color = player_color
        self.is_bot = is_bot
        self.rating = rating
        self.country = country
        self.sharing = sharing
        self.sharing_color = sharing_color
        self.clock_seconds = clock_seconds
        self.clock_initial_seconds = clock_initial_seconds
        self.active = active
        self.captured = captured or []
        self.advantage = advantage
        self.captured_color = captured_color
        self.connection_state = connection_state
        self.auto_end_label = auto_end_label
        self.auto_end_seconds = auto_end_seconds
        if ko_count > self.ko_count:
            self._ko_wink_until_ms = pg.time.get_ticks() + KO_WINK_MS
        self.ko_count = ko_count

    def flash_increment(self, seconds: float = 0, now_ms: int | None = None) -> None:
        """
        Light this player's clock up for a moment because time has just gone
        back on it. An ordinary increment only flashes the well, while time a
        player was given also floats the amount above the clock

        :param seconds: seconds granted, 0 for a plain move increment
        :param now_ms: pygame tick count to start from, None to read the clock
        """
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        self._flash_until_ms = now_ms + GIVE_TIME_FLASH_MS
        if seconds > 0:
            self._give_time_start_ms = now_ms
            self._give_time_amount = seconds

    def draw(self) -> None:
        """
        Paint the whole strip for this frame: frame border, clock well, KO
        badge, avatar and then everything about the player that fits in the
        space those leave. A strip with no room yet -- before the first layout
        -- draws nothing
        """
        h = self.rect.height
        if h <= 0 or self.rect.width <= 0:
            return
        self._flag_rect = pg.Rect(0, 0, 0, 0)
        now_ms = pg.time.get_ticks()
        pad, _radius, av_size, gap = strip_frame_metrics(h)
        border_color, border_width = self._frame_border(now_ms)
        frame = cut_rect_surface(self.rect.size, scale_floor(STRIP_FRAME_CUT, self.scale, 8),
                                 Colors.surface, border=border_color,
                                 border_width=border_width, corners=("tr",))
        self.window.blit(frame, self.rect.topleft)

        clock_rect = self._draw_clock(pad, av_size)
        ko_left = self._draw_ko(clock_rect.x - gap, av_size)

        avatar_rect = pg.Rect(self.rect.x + pad, self.rect.y + pad, av_size, av_size)
        self._avatar.draw(self.window, avatar_rect, self.name, self.letter_font)

        who_x = avatar_rect.right + gap
        who_right = (ko_left if ko_left is not None else clock_rect.x) - gap
        self._draw_who(who_x, who_right, av_size)

        self._draw_give_time_float(clock_rect)
        self._draw_flag_tooltip()

    def _frame_border(self, now_ms: int) -> tuple[str | pg.Color, int]:
        """
        Choose how the strip's outline reads at a glance: an accent frame for
        the side to move, a red one for a player running out of time, and a
        pulsing red when both are true at once

        :param now_ms: pygame tick count in milliseconds, which drives the
            pulse
        :returns: the border colour and its width in pixels
        """
        low = self._is_low_time()
        if self.active:
            if low:
                return self._pulse_border(now_ms), 2
            return Colors.accent, 2
        if low:
            return Colors.loss, 1
        return Colors.border, 1

    def _pulse_border(self, now_ms: int) -> pg.Color:
        """
        Breathe the border between the two low-time reds so a player about to
        flag cannot miss it. The blend is quantised into a handful of steps,
        which keeps the surface cache from being asked for a new colour on
        every single frame

        :param now_ms: pygame tick count in milliseconds
        :returns: the border colour for this point of the pulse
        """
        frac = cosine_pulse(now_ms, STRIP_PULSE_MS)
        step = round(frac * (PULSE_QUANT_STEPS - 1)) / (PULSE_QUANT_STEPS - 1)
        return pg.Color(Colors.clock_low_time).lerp(pg.Color(Colors.loss), step)

    def _flag_surface(self, height: int) -> pg.Surface | None:
        """
        Fetch this player's country flag at the size the strip needs, kept in
        a one-entry cache so a flag is only rendered when the country or the
        strip height actually changes

        :param height: wanted flag height in pixels
        :returns: the flag image, or None when the player has no country set
        """
        char = flag_emoji(self.country)
        if not char:
            return None
        key = (char, height)
        if self._flag_cache is None or self._flag_cache[0] != key:
            self._flag_cache = (key, emoji_surface(char, height))
        return self._flag_cache[1]

    def _advance_tooltip(self, hovering: bool) -> float:
        """
        Ease the country tooltip towards being shown or hidden by one frame's
        worth, and snap it to the end once it is close enough so it settles
        instead of creeping

        :param hovering: True while the cursor is over the flag
        :returns: the tooltip's opacity from 0 to 1 after this step
        """
        target = 1.0 if hovering else 0.0
        self._tooltip_alpha += (target - self._tooltip_alpha) * TOOLTIP_EASE
        if abs(self._tooltip_alpha - target) < 0.01:
            self._tooltip_alpha = target
        return self._tooltip_alpha

    def _draw_flag_tooltip(self) -> None:
        """
        Name the country when the cursor rests on the flag, which is the only
        way to read a two-letter code as a place. A player with no country, or
        one whose flag did not fit this frame, has nothing to hover
        """
        name = name_for(self.country)
        if not name or self._flag_rect.width == 0:
            self._tooltip_alpha = 0.0
            return
        hovering = self._flag_rect.collidepoint(pg.mouse.get_pos())
        self._advance_tooltip(hovering)
        if self._tooltip_alpha <= 0.02:
            return
        self._blit_tooltip(name)

    def _blit_tooltip(self, name: str) -> None:
        """
        Draw the country bubble beside the flag, below the flag on a top strip
        and above it on a bottom one so it always points into the window. The
        shared bubble is copied once per label because the fade sets an alpha
        on it, and it is nudged back inside the window edges

        :param name: country name to show, rendered in capitals
        """
        label = name.upper()
        key = (label, self.tooltip_font.get_height(), round(self.scale, 3))
        base = memoized_surface(
            _TOOLTIP_BASE_CACHE, key,
            lambda: build_tooltip_bubble(self.tooltip_font, label, self.scale))
        if self._tooltip_owned is None or self._tooltip_owned[0] != key:
            self._tooltip_owned = (key, base.copy())
        bubble = self._tooltip_owned[1]
        bubble.set_alpha(int(max(0.0, min(1.0, self._tooltip_alpha)) * 255))
        w, h = bubble.get_size()
        rise = int(TOOLTIP_RISE_PX * (1 - self._tooltip_alpha))
        if self.rect.centery < self.window.get_height() / 2:
            by = self._flag_rect.bottom + TOOLTIP_GAP_PX + rise
        else:
            by = self._flag_rect.top - h - TOOLTIP_GAP_PX - rise
        bx = self._flag_rect.centerx - w // 2
        bx = max(TOOLTIP_EDGE_MARGIN_PX,
                 min(bx, self.window.get_width() - w - TOOLTIP_EDGE_MARGIN_PX))
        self.window.blit(bubble, (bx, by))

    def _draw_who(self, x: int, right: int, ih: int) -> None:
        """
        Lay out everything between the avatar and the clock: connection dot,
        flag, name, rating, sharing pill and the captured pieces. A tall
        enough strip splits that over two rows with the captures underneath,
        while a short one squeezes it all onto one, and anything that would
        overrun the space is dropped rather than overlapped

        :param x: left edge of the area, just right of the avatar
        :param right: right edge, just left of the clock or the KO badge
        :param ih: inner height of the strip in pixels, which every size here
            is derived from
        """
        if right <= x:
            return
        two_row = ih >= TWO_ROW_MIN_IH
        base = self.rect.y + (self.rect.height - ih) // 2
        if two_row:
            top_cy = base + int(ih * 0.25)
            bottom_cy = base + int(ih * 0.76)
            pill_max = max(bottom_cy - top_cy - 2, 8)
        else:
            top_cy = bottom_cy = self.rect.centery
            pill_max = ih
        badge_x = self._draw_auto_end_badge(right, self.rect.centery)
        name_right = (badge_x - 8) if badge_x is not None else right
        cursor = x
        if self.connection_state is not None:
            dot_r = max(int(ih * 0.11), 3)
            color = getattr(Colors, "dot_" + self.connection_state, Colors.dot_unknown)
            dot = circle_surface(dot_r * 2, color)
            self.window.blit(dot, (cursor, top_cy - dot_r))
            cursor += dot_r * 2 + max(int(ih * 0.12), 4)
        flag = self._flag_surface(max(int(ih * 0.42), 10))
        if flag is not None and cursor + flag.get_width() <= name_right:
            self.window.blit(flag, (cursor, top_cy - flag.get_height() // 2))
            self._flag_rect = pg.Rect(cursor, top_cy - flag.get_height() // 2,
                                      flag.get_width(), flag.get_height())
            cursor += flag.get_width() + max(int(ih * 0.1), 4)
        name_surf = render_text(self.name_font, self.name, Colors.text)
        max_name_w = max(name_right - cursor, 1)
        if name_surf.get_width() > max_name_w:
            name_surf = self._clipped_name(name_surf, max_name_w)
        self.window.blit(name_surf, (cursor, top_cy - name_surf.get_height() / 2))
        cursor += name_surf.get_width() + max(int(ih * 0.14), 5)
        if two_row:
            row1 = cursor
            if self.rating is not None:
                row1 = self._draw_rating_pill(cursor, top_cy, name_right, pill_max)
            self._draw_sharing_pill(row1, top_cy, name_right, pill_max)
            self._draw_captured(x, bottom_cy, right, ih, pill_max)
        else:
            if self.rating is not None:
                cursor = self._draw_rating_pill(cursor, bottom_cy, right, pill_max)
            cursor = self._draw_sharing_pill(cursor, bottom_cy, right, pill_max)
            self._draw_captured(cursor, bottom_cy, right, ih, pill_max)

    def _clipped_name(self, name_surf: pg.Surface, max_w: int) -> pg.Surface:
        """
        Cut a long nickname down to the room it has, keeping the cut version
        for as long as the name and the width hold still so the subsurface is
        not carved out again every frame

        :param name_surf: the fully rendered name
        :param max_w: width available for it in pixels
        :returns: the name cropped to that width
        """
        key = (self.name, max_w)
        if self._name_clip_cache is None or self._name_clip_cache[0] != key:
            clip = name_surf.subsurface(pg.Rect(0, 0, max_w, name_surf.get_height()))
            self._name_clip_cache = (key, clip)
        return self._name_clip_cache[1]

    def _draw_text_pill(self, x: int, cy: int, right: int, text: pg.Surface, bg: str, *,
                        pad_ratio: float, pad_min: int, radius_div: int, radius_min: int,
                        max_h: int) -> int | None:
        """
        Draw one rounded chip with a label centred in it -- the shape both the
        rating and the material-lead badges are made of. A chip that will not
        fit before the right edge is not drawn at all, which is how the strip
        sheds detail as it gets narrower

        :param x: left edge of the chip in window pixels
        :param cy: vertical centre the chip is drawn around
        :param right: hard right edge the chip must stay inside
        :param text: the already rendered label
        :param bg: chip fill colour
        :param pad_ratio: horizontal padding as a share of the text height
        :param pad_min: smallest horizontal padding in pixels
        :param radius_div: chip height is divided by this for the corner radius
        :param radius_min: smallest corner radius in pixels
        :param max_h: height ceiling, so a chip stays inside its row
        :returns: the x to carry on from, or None when it did not fit
        """
        pad_x = max(int(text.get_height() * pad_ratio), pad_min)
        w = text.get_width() + 2 * pad_x
        h = min(text.get_height() + 2, max_h)
        if x + w > right:
            return None
        pill = rounded_rect_surface((w, h), max(h // radius_div, radius_min), bg)
        self.window.blit(pill, (x, round(cy - h / 2)))
        blit_centered(self.window, text, (x + w / 2, cy))
        return x + w

    def _draw_rating_pill(self, x: int, cy: int, right: int,
                          max_h: int = PILL_HEIGHT_UNCAPPED) -> int:
        """
        Draw the muted chip carrying the player's rating, which sits between
        the name and whatever follows it

        :param x: left edge of the chip in window pixels
        :param cy: vertical centre of the row it belongs to
        :param right: hard right edge the chip must stay inside
        :param max_h: height ceiling for the chip, uncapped on a single-row
            strip
        :returns: the x to carry on from, unchanged when the chip did not fit
        """
        text = self.rating_font.render(str(self.rating), True, Colors.text_dim)
        end = self._draw_text_pill(x, cy, right, text, Colors.surface_hover,
                                   pad_ratio=0.45, pad_min=3, radius_div=3, radius_min=4,
                                   max_h=max_h)
        if end is None:
            return x
        return end + max(int(self.rect.height * 0.06), 4)

    def _draw_sharing_pill(self, x: int, cy: int, right: int,
                           max_h: int = PILL_HEIGHT_UNCAPPED) -> int:
        """
        Show that this player is broadcasting their board marks, as a pulsing
        dot and a SHARING MARKS label in that side's own accent. When the full
        pill will not fit the dot is shown alone, so the fact never disappears
        just because the window is narrow

        :param x: left edge of the pill in window pixels
        :param cy: vertical centre of the row it belongs to
        :param right: hard right edge the pill must stay inside
        :param max_h: height ceiling for the pill
        :returns: the x to carry on from, unchanged when nothing fitted
        """
        if not self.sharing:
            return x
        color = self.sharing_color or Colors.accent
        dot_d = max(int(self.rect.height * 0.07), 4)
        dot = self._sharing_dot(color, dot_d)
        dot.set_alpha(self._sharing_dot_alpha(pg.time.get_ticks()))
        text = render_text(self.sharing_font, SHARING_PILL_TEXT, pg.Color(color))
        pad_x = max(int(text.get_height() * 0.5), 4)
        gap = max(int(dot_d * 0.7), 3)
        h = min(text.get_height() + 4, max_h)
        w = 2 * pad_x + dot_d + gap + text.get_width()
        if x + w <= right:
            pill = rounded_rect_surface((w, h), h, Colors.surface,
                                        border=color + "80", border_width=1)
            self.window.blit(pill, (x, round(cy - h / 2)))
            self.window.blit(dot, (x + pad_x, round(cy - dot_d / 2)))
            self.window.blit(text, (x + pad_x + dot_d + gap,
                                    round(cy - text.get_height() / 2)))
            return x + w + max(int(self.rect.height * 0.06), 4)
        if x + dot_d <= right:
            self.window.blit(dot, (x, round(cy - dot_d / 2)))
            return x + dot_d
        return x

    def _sharing_dot(self, color: str, diameter: int) -> pg.Surface:
        """
        Keep this strip's own copy of the sharing dot, since the pulse writes
        an alpha straight onto it and the shared cache must not be scribbled
        on. It is rebuilt only when the colour or the size changes

        :param color: dot colour, this side's sharing accent
        :param diameter: dot size in pixels
        :returns: the dot surface this strip owns
        """
        key = (color, diameter)
        if self._sharing_dot_cache is None or self._sharing_dot_cache[0] != key:
            self._sharing_dot_cache = (key, circle_surface(diameter, color).copy())
        return self._sharing_dot_cache[1]

    def _sharing_dot_alpha(self, now_ms: int) -> int:
        """
        Breathe the sharing dot so it reads as live rather than as a static
        badge, never letting it fade out completely

        :param now_ms: pygame tick count in milliseconds
        :returns: alpha from the floor up to 255 for this point of the pulse
        """
        frac = cosine_pulse(now_ms, SHARING_DOT_PULSE_MS)
        return int(SHARING_DOT_MIN_ALPHA + (255 - SHARING_DOT_MIN_ALPHA) * frac)

    def _draw_captured(self, x: int, cy: int, right: int, ih: int,
                       max_h: int = PILL_HEIGHT_UNCAPPED) -> None:
        """
        Draw the overlapping row of pieces this player has taken and, when
        they are ahead on material, the +N badge that closes it off. Being
        level or behind shows no badge, so only a lead is ever advertised

        :param x: left edge of the row in window pixels
        :param cy: vertical centre of the row
        :param right: hard right edge the row must stay inside
        :param ih: inner height of the strip, which sizes the icons
        :param max_h: height ceiling for the advantage badge
        """
        last_right = draw_captured_row(
            self.window, self.icons, self.captured, self.captured_color, x, cy, right, ih)
        if self.advantage > 0:
            self._draw_advantage_pill(last_right + max(int(ih * 0.18), 5), cy, right, max_h)

    def _draw_advantage_pill(self, x: int, cy: int, right: int,
                             max_h: int = PILL_HEIGHT_UNCAPPED) -> None:
        """
        Draw the amber +N chip that states how far ahead on material this
        player is, in pawn units

        :param x: left edge of the chip in window pixels
        :param cy: vertical centre of the row it belongs to
        :param right: hard right edge the chip must stay inside
        :param max_h: height ceiling for the chip
        """
        text = self.advantage_font.render(f"+{self.advantage}", True, Colors.on_accent)
        self._draw_text_pill(x, cy, right, text, Colors.amber,
                             pad_ratio=0.55, pad_min=4, radius_div=2, radius_min=0, max_h=max_h)

    def _draw_ko(self, right: int, ih: int) -> int | None:
        """
        Draw the KO badge counting the pieces this player has shot, tucked
        just left of the clock. It winks for a moment each time the count goes
        up, and a player who has taken nothing has no badge at all

        :param right: right edge the badge is hung from, in window pixels
        :param ih: inner height of the strip, which sizes the badge
        :returns: the badge's left edge, or None when there is no badge, which
            tells the caller how much room the name row has
        """
        if self.ko_count <= 0:
            return None
        winking = pg.time.get_ticks() < self._ko_wink_until_ms
        badge = build_ko_badge(self.ko_count, self.ko_font, ih, winking)
        x = right - badge.get_width()
        cy = self.rect.y + self.rect.height // 2
        self.window.blit(badge, (x, cy - badge.get_height() // 2))
        return x

    def _draw_clock(self, pad: int, av_size: int) -> pg.Rect:
        """
        Draw this side's remaining time in its well at the right of the strip,
        tinting the well while an increment flashes. The digits are kept from
        one frame to the next until the reading itself changes, since the
        clock is redrawn every single frame

        :param pad: strip padding in pixels, the inset from the right edge
        :param av_size: avatar size in pixels, which caps the well's height
        :returns: the clock well's rect, which the KO badge and the floating
            give-time label are placed against
        """
        text = format_clock(self.clock_seconds)
        color = self._clock_text_color()
        key = (text, color, self.clock_font)
        if self._clock_cache is None or self._clock_cache[0] != key:
            self._clock_cache = (key, self.clock_font.render(text, True, color))
        surf = self._clock_cache[1]
        hpad = scale_floor(CLOCK_WELL_PAD_X, self.scale, 9)
        vpad = scale_floor(CLOCK_WELL_PAD_Y, self.scale, 3)
        margin = scale_floor(CLOCK_RIGHT_MARGIN, self.scale, 6)
        box_w = surf.get_width() + 2 * hpad
        box_h = min(av_size, surf.get_height() + 2 * vpad)
        box = pg.Rect(self.rect.right - pad - margin - box_w,
                      round(self.rect.centery - box_h / 2), box_w, box_h)
        radius = scale_floor(CLOCK_WELL_RADIUS, self.scale, 5)
        self.window.blit(rounded_rect_surface(box.size, radius, Colors.bg,
                                              border=self._clock_border_color(),
                                              border_width=1), box.topleft)
        flash = self._flash_alpha()
        if flash > 0:
            tint = pg.Surface(box.size, pg.SRCALPHA)
            col = pg.Color(Colors.clock_increment_flash)
            col.a = flash
            pg.draw.rect(tint, col, tint.get_rect(), border_radius=radius)
            self.window.blit(tint, box.topleft)
        self.window.blit(surf, (box.centerx - surf.get_width() / 2,
                                box.centery - surf.get_height() / 2))
        return box

    def _is_low_time(self) -> bool:
        """
        Whether this side is into its last tenth of the starting time, the
        moment the strip starts warning about the clock. Untimed games are
        never low

        :returns: True when the clock is inside the low-time threshold
        """
        frac = self._clock_fraction()
        return frac is not None and frac < LOW_TIME_FRACTION

    def _clock_text_color(self) -> str:
        """
        The colour the digits are drawn in, which turns to the warning shade
        once the clock is low

        :returns: hex colour for the clock text
        """
        if self._is_low_time():
            return Colors.clock_low_text
        return Colors.text

    def _clock_border_color(self) -> str:
        """
        The colour of the well around the digits, which also picks up the
        warning shade when time is short

        :returns: hex colour for the clock well border
        """
        if self._is_low_time():
            return Colors.clock_low_time
        return Colors.dial_border

    def _draw_give_time_float(self, clock_rect: pg.Rect) -> None:
        """
        Float the granted amount up from the clock when this player is handed
        seconds by their opponent, fading as it climbs, so the gift is visible
        and not just a number that jumped

        :param clock_rect: the clock well the label rises from
        """
        if self._give_time_start_ms <= 0:
            return
        progress = (pg.time.get_ticks() - self._give_time_start_ms) / GIVE_TIME_FLOAT_MS
        alpha = give_time_float_alpha(progress)
        if alpha <= 0:
            return
        text = f"+0:{int(self._give_time_amount):02d}"
        surf = self._give_time_float_font.render(text, True, Colors.clock_increment_flash)
        surf.set_alpha(alpha)
        rise = int(GIVE_TIME_FLOAT_RISE_PX - GIVE_TIME_FLOAT_TRAVEL_PX * progress)
        self.window.blit(surf, (clock_rect.centerx - surf.get_width() / 2,
                                clock_rect.y - surf.get_height() + rise))

    def _draw_auto_end_badge(self, right: int, cy: int) -> int | None:
        """
        Show the countdown that is about to end the game without a move being
        played -- an abort, an abandonment or an idle resignation -- and turn
        it red in its final seconds. The game screen decides when one is
        running; this only prints it

        :param right: right edge the badge is hung from, in window pixels
        :param cy: vertical centre of the strip
        :returns: the badge's left edge, or None when nothing is counting
            down, which tells the name row how much width it has
        """
        if self.auto_end_label is None or self.auto_end_seconds is None:
            return None
        text = f"{self.auto_end_label} {format_countdown(self.auto_end_seconds)}"
        color = (Colors.loss
                 if self.auto_end_seconds < AUTO_END_RED_THRESHOLD_SECONDS
                 else Colors.text)
        key = (text, color)
        if self._auto_end_cache is None or self._auto_end_cache[0] != key:
            self._auto_end_cache = (key, self.auto_end_font.render(text, True, color))
        surf = self._auto_end_cache[1]
        badge_x = right - surf.get_width()
        self.window.blit(surf, (badge_x, cy - surf.get_height() / 2))
        return badge_x

    def _clock_fraction(self) -> float | None:
        """
        How much of this side's starting time is still on its clock, which is
        what the low-time warning is judged on rather than a fixed number of
        seconds -- a bullet game and a long game run out at different speeds

        :returns: share of the starting time left, or None when the game is
            untimed
        """
        if (self.clock_seconds is None or self.clock_initial_seconds is None
                or self.clock_initial_seconds <= 0):
            return None
        return max(0.0, self.clock_seconds / self.clock_initial_seconds)

    def _flash_alpha(self, now_ms: int | None = None) -> int:
        """
        Fade the tint over the clock well after time has been added, from its
        brightest at the moment of the increment down to nothing

        :param now_ms: pygame tick count to measure from, None to read the
            clock
        :returns: alpha for the tint, 0 once the flash is over
        """
        if self._flash_until_ms <= 0:
            return 0
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        remaining = self._flash_until_ms - now_ms
        if remaining <= 0:
            return 0
        progress = remaining / GIVE_TIME_FLASH_MS
        return int(GIVE_TIME_FLASH_PEAK_ALPHA * max(0.0, min(1.0, progress)))
