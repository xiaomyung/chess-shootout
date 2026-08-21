from typing import Any

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import SINGLE_SCREEN, BOT, ONLINE
from chessshootout.infra import env
from chessshootout.frontend.menu.layout import MenuLayout
from chessshootout.frontend.menu.time_picker import CHAMBERS, INCREMENTS, TimePicker
from chessshootout.frontend.menu.view import MenuView, scale_floor
from chessshootout.frontend.visual.cache import (
    memoized_surface, new_cache, new_size_cache, render_text)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    chevron_surface, circle_surface, cut_rect_surface, dashed_rounded_rect_surface,
    infinity_surface)
from chessshootout.frontend.visual.emoji import blit_emoji
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.icons import draw_clock
from chessshootout.frontend.visual.tween import Tween, out_back, out_cubic


TITLE = "READY UP."
TAGLINE = "PAWNS GET WHAT THEY DESERVE"
COMING_SOON = "Hold ya horses, I am cooking that..."
COMING_SOON_KEY = "coming_soon"

MODE_CHIPS = (
    ("Local", SINGLE_SCREEN, False),
    ("Online", ONLINE, False),
    ("Bot", BOT, True),
    ("Puzzles", "puzzles", True),
)
SELECTABLE_MODES = (SINGLE_SCREEN, ONLINE)

SIDE_OPTIONS = (
    ("White", "white"),
    ("Random", "random"),
    ("Black", "black"),
)

TITLE_TOP = 60
TITLE_FONT = 60
TITLE_CAP_H = 56
TAGLINE_FONT = 11
TAGLINE_TRACK = 2
TAGLINE_H = 16
TAGLINE_GAP = 26
MODE_GAP = 30
CHIP_H = 44
CHIP_CUT = 8
MODE_CHIP_PAD_X = 16
MODE_CHIP_GAP = 8
SUMMARY_GAP = 14
CTA_H = 78
CTA_FONT = 34
CTA_CUT = 18
CTA_BOTTOM = 16
LINK_H = 24
FEN_GAP = 10
RECON_H = 46
RECON_GAP = 12
TIME_POPOVER_W = 644
TIME_POPOVER_H = 414
POPOVER_OPEN_MS = 160
POPOVER_CLOSE_MS = 120
POPOVER_OPEN_SCALE = 0.92
SIDE_POPOVER_PAD = 18
SIDE_TILE = 110
SIDE_TILE_GAP = 14
SIDE_TILE_CUT = 10
SIDE_TILE_ART_FRAC = 0.46
SIDE_TILE_ART_CY_FRAC = 0.40
SIDE_TILE_LABEL_BOTTOM = 15
SIDE_READOUT_H = 42
SIDE_READOUT_GAP = 12
SIDE_READOUT_INSET = 14
SIDE_READOUT_LABEL_FONT = 10
SIDE_READOUT_VALUE_FONT = 15

SUMMARY_CHIP_PAD_X = 12
SUMMARY_CHIP_GAP = 7
SUMMARY_CHIP_ICON = 32
SUMMARY_CHIP_CHEVRON = 11
SUMMARY_CHIP_SPACING = 12
SIDE_ICON_SPREAD = 1.55
DASH_LEN = 5
DASH_GAP = 4
PRESS_OFFSET_PX = 1


_HERO_ART_CACHE = new_cache()
_HERO_SCALED_CACHE = new_size_cache()


def _side_image(color: str) -> pg.Surface | None:
    """
    Load the pawn artwork the Play panel uses to picture a side, kept in a
    process-wide cache so the file is read once per colour instead of per
    frame. Missing or unreadable art gives back nothing at all, which every
    caller copes with rather than crashing

    :param color: side to picture, white or black
    :returns: the loaded pawn image, or None when the art could not be read
    """
    def build() -> pg.Surface | None:
        """
        Read the pawn PNG off disk on a cache miss and convert it into the
        window's own pixel format, so later blits are cheap

        :returns: the loaded pawn image, or None when the file is missing or
            unreadable
        """
        try:
            img = pg.image.load(
                str(paths.resource_path("assets", "pieces_png", f"pawn_{color}.png")))
            return img.convert_alpha()
        except (pg.error, OSError):
            return None
    return memoized_surface(_HERO_ART_CACHE, ("side", color), build)


def _scaled_side_image(color: str, size: int) -> pg.Surface | None:
    """
    Give the pawn artwork at the exact pixel size a chip or a side tile needs.
    Every pawn drawn on the Play panel comes from here, and the scaling is
    cached per colour and size so a window resize pays for it once

    :param color: side to picture, white or black
    :param size: wanted width and height in pixels
    :returns: the scaled pawn image, or None when there is no art to scale
    """
    def build() -> pg.Surface | None:
        """
        Smoothscale the loaded pawn to the wanted size on a cache miss,
        passing a missing-art answer straight through

        :returns: the scaled pawn image, or None when the art is missing
        """
        img = _side_image(color)
        if img is None:
            return None
        return pg.transform.smoothscale(img, (size, size))
    return memoized_surface(_HERO_SCALED_CACHE, (color, size), build)


def _tracked_surface(font: pg.font.Font, text: str, color: str,
                     tracking: int) -> pg.Surface:
    """
    Render a line of text with air wedged between the letters, which is how the
    Play panel's tagline gets its wide spaced-out look. Pygame cannot letter
    space a rendered line, so the glyphs are drawn one at a time and the result
    is cached like any other drawable

    :param font: the loaded font each glyph is rendered with
    :param text: the line to draw, one glyph per character
    :param color: ink colour as a hex token from Colors
    :param tracking: extra pixels inserted between neighbouring glyphs
    :returns: the whole spaced-out line as one surface, shared with every later
        caller of the same text and size
    """
    def build() -> pg.Surface:
        """
        Lay the glyphs side by side with the tracking gap between them on a
        cache miss, sizing the surface to what they add up to

        :returns: the spaced-out line as one surface
        """
        glyphs = [render_text(font, ch, color) for ch in text]
        width = sum(g.get_width() for g in glyphs) + tracking * max(len(glyphs) - 1, 0)
        height = max((g.get_height() for g in glyphs), default=1)
        surf = pg.Surface((max(width, 1), height), pg.SRCALPHA)
        x = 0
        for g in glyphs:
            surf.blit(g, (x, 0))
            x += g.get_width() + tracking
        return surf
    key = ("tagline", text, font.get_height(), str(color), tracking)
    return memoized_surface(_HERO_ART_CACHE, key, build)


class _PopoverAnim:
    """
    The pop-in and pop-out of one Play-panel popover, held as a small state
    machine of closed, opening, open and closing. It owns nothing but the scale
    and the fade of the panel, so the picker or the tiles inside know nothing
    about the transition playing around them
    """

    def __init__(self) -> None:
        """
        Start out closed with no tweens built, since a popover that has never
        been opened must cost nothing
        """
        self.mode = "closed"
        self._scale_tween = None
        self._alpha_tween = None

    def open(self) -> None:
        """
        Begin showing the popover, which grows from slightly small to full size
        as it fades in. The tweens are built on the first frame that draws it,
        so the animation starts from that frame rather than from this call
        """
        self.mode = "opening"
        self._scale_tween = None
        self._alpha_tween = None

    def close(self) -> None:
        """
        Begin hiding the popover, playing the grow and the fade backwards.
        Closing one that is already closed does nothing
        """
        if self.mode == "closed":
            return
        self.mode = "closing"
        self._scale_tween = None
        self._alpha_tween = None

    def snap(self) -> None:
        """
        Cut an animation in flight short and land on whichever state it was
        heading for. A window resize does this, because the rects it was
        animating between no longer exist
        """
        if self.mode == "opening":
            self.mode = "open"
        elif self.mode == "closing":
            self.mode = "closed"
        self._scale_tween = None
        self._alpha_tween = None

    def advance(self, now: int) -> None:
        """
        Step the animation for this frame: build the scale and fade tweens on
        the first frame after it was armed, then finish the transition once
        they run out. Called from the drawing pass, which is what makes the
        animation start when the popover is first painted

        :param now: pygame tick count in milliseconds since pygame init
        """
        if self.mode == "opening":
            if self._scale_tween is None:
                self._scale_tween = Tween(
                    POPOVER_OPEN_SCALE, 1.0, POPOVER_OPEN_MS, now, ease=out_back)
                self._alpha_tween = Tween(0.0, 255.0, POPOVER_OPEN_MS, now, ease=out_cubic)
            if self._scale_tween.done(now):
                self.mode = "open"
                self._scale_tween = None
                self._alpha_tween = None
        elif self.mode == "closing":
            if self._scale_tween is None:
                self._scale_tween = Tween(
                    1.0, POPOVER_OPEN_SCALE, POPOVER_CLOSE_MS, now, ease=out_cubic)
                self._alpha_tween = Tween(255.0, 0.0, POPOVER_CLOSE_MS, now, ease=out_cubic)
            if self._scale_tween.done(now):
                self.mode = "closed"
                self._scale_tween = None
                self._alpha_tween = None

    def scale(self, now: int) -> float:
        """
        How big the popover should be drawn this frame, as a multiplier on the
        size it was laid out at

        :param now: pygame tick count in milliseconds since pygame init
        :returns: size multiplier, 1.0 whenever nothing is animating
        """
        return self._scale_tween.value(now) if self._scale_tween is not None else 1.0

    def alpha(self, now: int) -> int:
        """
        How solid the popover should be drawn this frame, which is what makes
        it fade rather than appear

        :param now: pygame tick count in milliseconds since pygame init
        :returns: alpha from 0 to 255, fully opaque whenever nothing is
            animating
        """
        return int(self._alpha_tween.value(now)) if self._alpha_tween is not None else 255


class PlayView(MenuView):
    """
    The hero of the menu and the way into every game: the mode chips, the time
    and side popovers, the big start button, the start-from-FEN link and the
    Reconnect banner for a game the player walked away from. The shell opens
    the menu on it, and the online coordinator hides and shows it around a
    search for an opponent
    """

    name = "play"

    def __init__(self, app: Any) -> None:
        """
        Build the panel once at startup with the mode from last time and the
        stored default time control already chosen, so the player finds their
        previous session waiting. No rect is known yet -- the shell lays the
        menu out before it is ever shown

        :param app: the Frontend shell, this view's route to the window, sound,
            toasts, the input router and the online coordinator
        """
        super().__init__(app)
        self.visible = True
        self.reconnect_available = False
        last_mode = env.get_last_mode()
        self.selected_mode = last_mode if last_mode in SELECTABLE_MODES else SINGLE_SCREEN
        self.selected_time_minutes = 10
        self.selected_increment_seconds = 5
        self.selected_side = "random"
        self.apply_default_time_settings()

        self._picker = TimePicker(on_change=self._on_picker_change,
                                  on_tick=app.sound_manager.play_drum_tick,
                                  on_ratchet=app.sound_manager.play_turret_ratchet)
        self._time_open = False
        self._side_open = False
        self._time_anim = _PopoverAnim()
        self._side_anim = _PopoverAnim()
        self._popover_scratches = {}

        self._menu_layout = None
        self._scale = 1.0
        self._hero_rect = pg.Rect(0, 0, 0, 0)
        self._recon_rect = pg.Rect(0, 0, 0, 0)
        self._recon_button = pg.Rect(0, 0, 0, 0)
        self._title_pos = (0, 0)
        self._tagline_pos = (0, 0)
        self._title_block = pg.Rect(0, 0, 0, 0)
        self._mode_rects = {}
        self._time_chip = pg.Rect(0, 0, 0, 0)
        self._side_chip = pg.Rect(0, 0, 0, 0)
        self._cta_rect = pg.Rect(0, 0, 0, 0)
        self._fen_rect = pg.Rect(0, 0, 0, 0)
        self._fen_above = True
        self._time_popover = pg.Rect(0, 0, 0, 0)
        self._side_popover = pg.Rect(0, 0, 0, 0)
        self._side_readout = pg.Rect(0, 0, 0, 0)
        self._side_rects = {}
        self._hover_target = None
        self._press_target = None

        self._title_font = get_display_font(TITLE_FONT)
        self._tagline_font = get_mono_font(TAGLINE_FONT, bold=True)
        self._chip_font = get_font(13, bold=True)
        self._value_font = get_mono_font(13, bold=True)
        self._cta_font = get_display_font(CTA_FONT)
        self._link_font = get_font(12, bold=True)
        self._recon_font = get_font(12, bold=True)
        self._side_readout_label_font = get_mono_font(SIDE_READOUT_LABEL_FONT, bold=True)
        self._side_readout_value_font = get_mono_font(SIDE_READOUT_VALUE_FONT, bold=True)

    def show(self) -> None:
        """
        Put the panel back on offer, which is how the online coordinator
        returns the menu to its idle state once a search or a session ends
        """
        self.visible = True

    def hide(self) -> None:
        """
        Take the panel off screen while a search or a game start is running, so
        a menu behind a waiting card is not still offering another match. Any
        open popover is closed and hover and press are forgotten, so it comes
        back cold
        """
        self.visible = False
        self._close_popovers()
        self._hover_target = None
        self._press_target = None

    def is_visible(self) -> bool:
        """
        Whether the panel is currently on offer, which is how the coordinator
        tells an idle menu from one busy with a search

        :returns: True while the panel is showing
        """
        return self.visible

    def enter(self, payload: dict[str, Any] | None = None) -> None:
        """
        Show the panel as the menu switches onto it, called by the shell on
        every visit. Nothing else is restored, because every choice on it
        survives between visits anyway

        :param payload: navigation payload from the menu shell; this view takes
            no arguments and ignores it
        """
        self.show()

    def exit(self) -> None:
        """
        Stand down as the menu leaves for another sub-view, closing any open
        popover and hiding the panel so none of this visit is still on screen
        underneath the next one
        """
        self._close_popovers()
        self.hide()

    def apply_default_time_settings(self) -> None:
        """
        Take the default time control and increment from the stored settings,
        which is how a change made in Options reaches the panel. Values the
        drum and turret cannot show are ignored, and an untimed default drops
        the increment to zero because there is no clock to add it to
        """
        minutes = env.get_default_time_minutes()
        if minutes in [value for value, _ in CHAMBERS]:
            self.selected_time_minutes = minutes
        seconds = env.get_default_increment_seconds()
        if seconds in INCREMENTS:
            self.selected_increment_seconds = seconds
        if self.selected_time_minutes is None:
            self.selected_increment_seconds = 0

    def apply_resume_config(self, resume: dict[str, Any]) -> None:
        """
        Dress the panel to match a game being rejoined -- online, the same time
        control, the same side -- so the menu behind the reconnect tells the
        truth about what the player is going back to

        :param resume: the server's resume snapshot, read here for the time
            control and for which colour this player has
        """
        self.selected_mode = ONLINE
        self.selected_time_minutes = resume["time_minutes"]
        self.selected_increment_seconds = resume["increment_seconds"]
        self.selected_side = resume["your_color"]

    def set_reconnect_available(self, available: bool) -> None:
        """
        Show or hide the Reconnect banner above the title, driven by the
        coordinator's probe for a game the player left behind. The banner takes
        a strip off the top of the column, so switching it reflows everything
        below it

        :param available: True when there is a game waiting to be rejoined
        """
        if self.reconnect_available == available:
            return
        self.reconnect_available = available
        if self._menu_layout is not None:
            self._relayout()

    def cta_label(self) -> str:
        """
        Word the big button for the chosen mode: online there is an opponent to
        go and find first, locally the game starts the moment it is pressed

        :returns: the label to draw on the button
        """
        return "FIND MATCH" if self.selected_mode == ONLINE else "START MATCH"

    def build_config(self) -> dict[str, Any]:
        """
        Gather every choice made on the panel into the settings block the shell
        starts a game from. The same block is what the coordinator remembers,
        so a New Search after a failure repeats exactly this request

        :returns: the chosen mode, the player's nickname, the time control as
            minutes plus increment seconds, and the side preference
        """
        return {
            "mode": self.selected_mode,
            "nickname": env.get_nickname(),
            "time_minutes": self.selected_time_minutes,
            "increment_seconds": self.selected_increment_seconds,
            "side": self.selected_side,
        }

    def _on_picker_change(self) -> None:
        """
        Adopt whatever the drum and the turret have settled on as the panel's
        time control, the callback handed to the picker when it is built. The
        panel is laid out again afterwards, so nothing downstream is left
        measured against the old value
        """
        self.selected_time_minutes = self._picker.selected_minutes
        self.selected_increment_seconds = self._picker.selected_increment
        if self._menu_layout is not None:
            self._relayout()

    def relayout(self, menu_layout: MenuLayout) -> None:
        """
        Take the menu's fresh geometry and rebuild every rect the panel owns.
        A popover animation in flight is snapped to its end state, since it was
        moving between rects that no longer exist, and a popover that is open
        is refitted into the new window

        :param menu_layout: the menu's computed rects and UI scale for the
            current window size
        """
        self._menu_layout = menu_layout
        self._scale = menu_layout.scale
        self._relayout()
        self._time_anim.snap()
        self._side_anim.snap()
        if self._time_open:
            self._layout_time_popover()
        elif self._side_open:
            self._layout_side_popover()

    def _s(self, value: int) -> int:
        """
        Fit one design-time size to the window the player actually has, the
        single place this panel's constants meet the menu's UI scale

        :param value: size in design pixels, the way the module constants at
            the top of this file spell it
        :returns: the size in real pixels for this window, never below 1
        """
        return scale_floor(value, self._scale)

    def _relayout(self) -> None:
        """
        Lay the hero column out top to bottom: the Reconnect banner when there
        is one, the title and tagline, the mode chips, the two summary chips,
        and the start button pinned to the bottom with the FEN link beside it.
        Every rect the panel draws and hit-tests is decided here
        """
        hero = self._menu_layout.hero_rect
        self._hero_rect = pg.Rect(hero)
        self._fit_fonts()
        x = hero.x
        w = hero.width
        top = hero.y + self._s(TITLE_TOP)
        if self.reconnect_available:
            self._recon_rect = pg.Rect(x, top, w, self._s(RECON_H))
            btn_w = self._s(96)
            self._recon_button = pg.Rect(self._recon_rect.right - self._s(12) - btn_w,
                                         self._recon_rect.y + self._s(8),
                                         btn_w, self._s(RECON_H) - self._s(16))
            top = self._recon_rect.bottom + self._s(RECON_GAP)
        else:
            self._recon_rect = pg.Rect(0, 0, 0, 0)
            self._recon_button = pg.Rect(0, 0, 0, 0)
        self._title_pos = (x, top)
        self._tagline_pos = (x, top + self._s(TITLE_CAP_H) + self._s(TAGLINE_GAP))
        self._layout_title_block()

        mode_y = self._tagline_pos[1] + self._s(TAGLINE_H) + self._s(MODE_GAP)
        self._layout_mode_chips(x, mode_y)
        summary_y = mode_y + self._s(CHIP_H) + self._s(SUMMARY_GAP)
        self._layout_summary_chips(x, summary_y)

        cta_h = self._s(CTA_H)
        cta_bottom = hero.bottom - self._s(CTA_BOTTOM)
        self._cta_rect = pg.Rect(x, cta_bottom - cta_h, w, cta_h)
        self._layout_fen_link()

    def _fit_fonts(self) -> None:
        """
        Rebuild every font the panel draws with at the current UI scale. Fonts
        are remade on layout rather than kept across sizes, so a resize can
        never leave a label rendered at the size before it
        """
        self._title_font = get_display_font(self._s(TITLE_FONT))
        self._tagline_font = get_mono_font(self._s(TAGLINE_FONT), bold=True)
        self._chip_font = get_font(self._s(13), bold=True)
        self._value_font = get_mono_font(self._s(13), bold=True)
        self._cta_font = get_display_font(self._s(CTA_FONT))
        self._link_font = get_font(self._s(12), bold=True)
        self._recon_font = get_font(self._s(12), bold=True)
        self._side_readout_label_font = get_mono_font(self._s(SIDE_READOUT_LABEL_FONT), bold=True)
        self._side_readout_value_font = get_mono_font(self._s(SIDE_READOUT_VALUE_FONT), bold=True)

    def _layout_title_block(self) -> None:
        """
        Measure the title and the tagline together as one block, the panel's
        record of how much room its headline takes. The Play panel deliberately
        reserves no space from the menu backdrop, so the pieces skirmishing
        behind it still fight across this block
        """
        x, top = self._title_pos
        title_w = self._title_font.size(TITLE)[0]
        tagline = self._tagline_surface()
        block_w = max(title_w, tagline.get_width())
        bottom = self._tagline_pos[1] + tagline.get_height()
        self._title_block = pg.Rect(x, top, block_w, bottom - top)

    def _tagline_surface(self) -> pg.Surface:
        """
        The spaced-out line under the title, rendered once per size and shared
        from the cache on every frame after that

        :returns: the tagline as one surface, ready to blit
        """
        return _tracked_surface(self._tagline_font, TAGLINE, Colors.text_muted,
                                self._s(TAGLINE_TRACK))

    def _layout_mode_chips(self, x: int, y: int) -> None:
        """
        Lay the mode chips -- Local, Online and the locked ones -- in a row from
        the left edge of the column, each sized to its own label so the row
        reads as a set of buttons rather than a grid

        :param x: left edge of the row in window pixels
        :param y: top edge of the row in window pixels
        """
        pad = self._s(MODE_CHIP_PAD_X)
        gap = self._s(MODE_CHIP_GAP)
        h = self._s(CHIP_H)
        self._mode_rects = {}
        cx = x
        for label, key, locked in MODE_CHIPS:
            w = self._chip_font.size(label)[0] + 2 * pad
            self._mode_rects[key] = pg.Rect(cx, y, w, h)
            cx += w + gap

    def _time_value_surface(self) -> pg.Surface:
        """
        Draw the chosen time control the way the summary chip shows it, as
        minutes plus increment. An untimed game has no numbers, so it gets the
        drawn figure of eight instead

        :returns: the time control as one surface, ready to blit
        """
        if self.selected_time_minutes is None:
            return infinity_surface(self._value_font.get_height(), Colors.amber_hi)
        text = f"{self.selected_time_minutes}+{self.selected_increment_seconds}"
        return render_text(self._value_font, text, Colors.amber_hi)

    def _side_label_text(self) -> str:
        """
        Name the chosen side the way the chip and the popover readout print it

        :returns: the side in capitals, WHITE, RANDOM or BLACK
        """
        return {"white": "WHITE", "random": "RANDOM", "black": "BLACK"}[self.selected_side]

    def _side_icon_width(self, icon_size: int) -> int:
        """
        How much room the side chip's artwork needs, which is wider for Random
        because that draws both pawns overlapping instead of one

        :param icon_size: height of a single pawn in pixels
        :returns: width the artwork occupies in pixels
        """
        if self.selected_side == "random":
            return round(icon_size * SIDE_ICON_SPREAD)
        return icon_size

    def _max_time_value_w(self) -> int:
        """
        Measure the widest time control the picker can produce, so the summary
        chip is sized once for all of them and never resizes under the player
        as they turn the drum

        :returns: width in pixels of the widest possible reading
        """
        widest = infinity_surface(self._value_font.get_height(), Colors.amber_hi).get_width()
        for minutes, _ in CHAMBERS:
            if minutes is None:
                continue
            for inc in INCREMENTS:
                text = f"{minutes}+{inc}"
                widest = max(widest, render_text(self._value_font, text,
                                                 Colors.amber_hi).get_width())
        return widest

    def _max_side_label_w(self) -> int:
        """
        Measure the widest side label, for the same reason as the time one --
        the side chip keeps one width whichever side is picked

        :returns: width in pixels of the widest side label
        """
        return max(render_text(self._chip_font, label, Colors.text).get_width()
                   for label in ("WHITE", "RANDOM", "BLACK"))

    def _layout_summary_chips(self, x: int, y: int) -> None:
        """
        Lay the two chips that say what the next game will be -- the time
        control and the side -- side by side under the mode row. Both are sized
        from their widest possible contents, so neither jumps about as the
        player changes their mind

        :param x: left edge of the row in window pixels
        :param y: top edge of the row in window pixels
        """
        pad = self._s(SUMMARY_CHIP_PAD_X)
        gap = self._s(SUMMARY_CHIP_GAP)
        icon = self._s(SUMMARY_CHIP_ICON)
        chevron = self._s(SUMMARY_CHIP_CHEVRON)
        h = self._s(CHIP_H)
        chip_gap = self._s(SUMMARY_CHIP_SPACING)

        time_w = pad + icon + gap + self._max_time_value_w() + gap + chevron + pad
        self._time_chip = pg.Rect(x, y, time_w, h)

        side_icon_w = round(icon * SIDE_ICON_SPREAD)
        side_w = pad + side_icon_w + gap + self._max_side_label_w() + gap + chevron + pad
        self._side_chip = pg.Rect(x + time_w + chip_gap, y, side_w, h)

    def _layout_fen_link(self) -> None:
        """
        Place the start-from-FEN link relative to the start button, below it
        when the column has the room and just above it when it does not, so the
        link is never pushed off the bottom of a short window
        """
        x = self._hero_rect.x
        w = self._hero_rect.width
        link_h = self._s(LINK_H)
        below_top = self._cta_rect.bottom + self._s(FEN_GAP)
        if below_top + link_h <= self._hero_rect.bottom:
            self._fen_rect = pg.Rect(x, below_top, w, link_h)
            self._fen_above = False
        else:
            self._fen_rect = pg.Rect(x, self._cta_rect.top - self._s(FEN_GAP) - link_h, w, link_h)
            self._fen_above = True

    def _fit_popover(self, base_w: int, base_h: int, anchor_left: int,
                     chip: pg.Rect) -> tuple[pg.Rect, float]:
        """
        Find the biggest a popover can be and still fit the window, and where
        to hang it off the chip that opened it. It prefers to drop below the
        chip and flips above when there is no room, shrinking everything by one
        shared factor rather than clipping

        :param base_w: wanted width in window pixels at full size
        :param base_h: wanted height in window pixels at full size
        :param anchor_left: preferred left edge, pulled inside the hero column
            and the window
        :param chip: the chip the popover hangs from
        :returns: the rect it should occupy and the factor everything inside it
            must be scaled by
        """
        win_w, win_h = self.app.window.get_size()
        top_limit = self.app.chrome.HEIGHT
        hero = self._hero_rect
        gap = self._s(8)
        below = (win_h - 4) - (chip.bottom + gap)
        above = (chip.top - gap) - (top_limit + 4)
        avail_v = max(below, above, 1)
        avail_w = max(hero.width, 1)
        shrink = min(1.0, avail_w / base_w, avail_v / base_h)
        pw = min(int(base_w * shrink), avail_w)
        ph = int(base_h * shrink)
        px = min(max(anchor_left, hero.left), hero.right - pw)
        px = min(max(px, 4), win_w - pw - 4)
        if chip.bottom + gap + ph <= win_h - 4:
            py = chip.bottom + gap
        else:
            py = max(chip.top - gap - ph, top_limit + 4)
        return pg.Rect(px, py, max(pw, 1), max(ph, 1)), shrink

    def _layout_time_popover(self) -> None:
        """
        Fit the time popover under its chip and hand the picker the room left
        inside the padding. The picker lays its own drum, turret and readout
        out from that rect, so this is the only geometry it is ever given
        """
        self._time_popover, shrink = self._fit_popover(
            self._s(TIME_POPOVER_W), self._s(TIME_POPOVER_H),
            self._hero_rect.x, self._time_chip)
        pad = max(int(self._s(14) * shrink), 4)
        self._picker.set_rect(self._time_popover.inflate(-2 * pad, -2 * pad))

    def _layout_side_popover(self) -> None:
        """
        Fit the side popover under its chip and place the three square tiles in
        a centred row above the readout strip. The tiles share whatever width
        survives the fitting, so they stay square and even in any window
        """
        base_w = 2 * SIDE_POPOVER_PAD + 3 * SIDE_TILE + 2 * SIDE_TILE_GAP
        base_h = (SIDE_POPOVER_PAD + SIDE_TILE + SIDE_READOUT_GAP
                  + SIDE_READOUT_H + SIDE_POPOVER_PAD)
        self._side_popover, shrink = self._fit_popover(
            self._s(base_w), self._s(base_h), self._side_chip.x, self._side_chip)
        pad = max(int(self._s(SIDE_POPOVER_PAD) * shrink), 3)
        gap = max(int(self._s(SIDE_TILE_GAP) * shrink), 2)
        readout_h = max(int(self._s(SIDE_READOUT_H) * shrink), 1)
        tile = max(int((self._side_popover.width - 2 * pad - 2 * gap) / 3), 1)
        row_w = 3 * tile + 2 * gap
        x = self._side_popover.x + (self._side_popover.width - row_w) // 2
        ty = self._side_popover.y + pad
        self._side_rects = {}
        for _, key in SIDE_OPTIONS:
            self._side_rects[key] = pg.Rect(x, ty, tile, tile)
            x += tile + gap
        self._side_readout = pg.Rect(self._side_popover.x, self._side_popover.bottom - pad
                                     - readout_h, self._side_popover.width, readout_h)

    def _open_time_popover(self) -> None:
        """
        Open the revolver time picker on the chip the player just pressed,
        handing it the current choice first so the drum and turret come up
        already showing it rather than snapping to it
        """
        self._picker.set_selection(self.selected_time_minutes,
                                   self.selected_increment_seconds)
        self._time_open = True
        self._time_anim.open()
        self._layout_time_popover()

    def _open_side_popover(self) -> None:
        """
        Open the side chooser on the chip the player just pressed, with its
        three tiles laid out and the pop-in animation armed
        """
        self._side_open = True
        self._side_anim.open()
        self._layout_side_popover()

    def _close_popovers(self) -> None:
        """
        Shut whichever popover is open and start its fade out. The panel counts
        as closed from this moment, so a click straight afterwards falls
        through to the hero underneath while the animation is still playing
        """
        if self._time_open:
            self._time_anim.close()
        if self._side_open:
            self._side_anim.close()
        self._time_open = False
        self._side_open = False

    def escape(self) -> bool:
        """
        Answer Esc on the Play panel: an open popover closes and nothing else
        happens. With none open the key is refused, which is what lets the menu
        take the next step and raise the quit confirmation

        :returns: True when a popover was closed, False when Esc is not ours
        """
        if self._time_open or self._side_open:
            self._close_popovers()
            return True
        return False

    def update(self, now: int) -> None:
        """
        Step the time picker one frame while its popover is open, which is what
        keeps a spinning drum turning and a swinging turret moving. Nothing
        else on the panel animates outside the drawing pass

        :param now: pygame tick count in milliseconds since pygame init
        """
        if self._time_open:
            self._picker.update(now)

    def active_scrollable(self, pos: tuple[int, int] | None = None) -> TimePicker | None:
        """
        Offer the time picker to the wheel while its popover is open, so
        scrolling spins the drum or ratchets the increment instead of moving
        the menu behind it

        :param pos: cursor position in window pixels, not used here because the
            open popover claims the wheel wherever the cursor is
        :returns: the time picker while its popover is open, otherwise None
        """
        return self._picker if self._time_open else None

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a left click on the panel. An open popover takes everything: a
        click inside it is passed on to its contents, a click anywhere else
        closes it and is spent doing so. With none open the click goes to the
        hero itself

        :param pos: click position in window pixels
        :returns: True when the panel took the click
        """
        if not self.visible:
            return False
        if self._time_open:
            if self._time_popover.collidepoint(pos):
                self._picker.handle_click(pos)
                self.app.input_router.suppress_click_sound()
            else:
                self._close_popovers()
            return True
        if self._side_open:
            if self._side_popover.collidepoint(pos):
                self._handle_side_click(pos)
            else:
                self._close_popovers()
            return True
        return self._handle_hero_click(pos)

    def _handle_hero_click(self, pos: tuple[int, int]) -> bool:
        """
        Act on a click on the panel itself: rejoin a game from the banner, pick
        a mode (a locked one only toasts), open either popover, start the game,
        or open the FEN card -- which online has no meaning for and is not drawn

        :param pos: click position in window pixels
        :returns: True when something under the cursor took the click
        """
        if self.reconnect_available and self._recon_button.collidepoint(pos):
            self.app.coordinator.reconnect()
            return True
        for label, key, locked in MODE_CHIPS:
            if self._mode_rects[key].collidepoint(pos):
                if locked:
                    self.app.toast.show(COMING_SOON, key=COMING_SOON_KEY)
                else:
                    self.selected_mode = key
                return True
        if self._time_chip.collidepoint(pos):
            self._open_time_popover()
            return True
        if self._side_chip.collidepoint(pos):
            self._open_side_popover()
            return True
        if self._cta_rect.collidepoint(pos):
            self.app._on_start_game(self.build_config())
            return True
        if self.selected_mode != ONLINE and self._fen_rect.collidepoint(pos):
            self.app._on_open_fen_modal()
            return True
        return False

    def _handle_side_click(self, pos: tuple[int, int]) -> None:
        """
        Take the side the player picked from the popover's tiles and reflow the
        panel, because the chip behind it now pictures a different pawn. The
        popover deliberately stays open, so a mistaken pick can be corrected
        without reopening it

        :param pos: click position in window pixels
        """
        for key, rect in self._side_rects.items():
            if rect.collidepoint(pos):
                self.selected_side = key
                if self._menu_layout is not None:
                    self._relayout()
                return

    def _hover_hit(self, pos: tuple[int, int]) -> str | None:
        """
        Name whichever control the cursor is over, the single place hover and
        press agree on what is being pointed at. Locked mode chips are skipped,
        since they never light up

        :param pos: cursor position in window pixels
        :returns: a target name -- cta, time, side or mode:<key> -- or None when
            the cursor is over nothing that reacts
        """
        if self._cta_rect.collidepoint(pos):
            return "cta"
        for label, key, locked in MODE_CHIPS:
            if locked:
                continue
            if self._mode_rects[key].collidepoint(pos):
                return f"mode:{key}"
        if self._time_chip.collidepoint(pos):
            return "time"
        if self._side_chip.collidepoint(pos):
            return "side"
        return None

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Remember which control the player is holding down, which is only ever
        about how it looks -- the press paints the control pushed in, and the
        click that follows is what actually does anything

        :param pos: press position in window pixels
        :returns: True when the press landed on a control that reacts
        """
        if not self.visible or self._time_open or self._side_open:
            return False
        target = self._hover_hit(pos)
        if target is None:
            return False
        self._press_target = target
        return True

    def handle_motion(self, pos: tuple[int, int]) -> bool:
        """
        Track which control the cursor is over so the panel can light it up. A
        panel that is hidden or has a popover open drops the hover instead,
        which is what stops a stale highlight showing when it comes back

        :param pos: cursor position in window pixels
        :returns: True while the panel is taking hover at all
        """
        if not self.visible or self._time_open or self._side_open:
            self._hover_target = None
            return False
        self._hover_target = self._hover_hit(pos)
        return True

    def handle_release(self, pos: tuple[int, int]) -> bool:
        """
        Let go of whatever was being held, which just returns the control to
        its unpressed look

        :param pos: release position in window pixels, not needed because the
            release always ends the press wherever it happens
        :returns: True when a press was actually released
        """
        had_press = self._press_target is not None
        self._press_target = None
        return had_press

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Refuse every key: the Play panel is driven entirely by the mouse, and
        Esc is dealt with by the menu before it could arrive here

        :param event: pygame KEYDOWN event offered to the panel
        :returns: False always, so the key falls through untouched
        """
        return False

    def draw(self, window: pg.Surface, menu_layout: MenuLayout) -> None:
        """
        Paint the panel bottom of the stack upwards: the Reconnect banner, the
        title and tagline, the chips, the start button and the FEN link, with
        the popover layers over the top of everything. Online has no FEN start,
        so the link is not drawn in that mode

        :param window: surface to draw on, the window or a scratch surface the
            menu's own transition is compositing
        :param menu_layout: the menu's rects for this frame, unused here
            because layout already stored everything this draw needs
        """
        if not self.visible:
            return
        if self.reconnect_available:
            self._draw_recon(window)
        window.blit(render_text(self._title_font, TITLE, Colors.text), self._title_pos)
        window.blit(self._tagline_surface(), self._tagline_pos)
        self._draw_mode_chips(window)
        self._draw_time_chip(window)
        self._draw_side_chip(window)
        self._draw_cta(window)
        if self.selected_mode != ONLINE:
            self._draw_fen_link(window)
        self._draw_time_popover_layer(window)
        self._draw_side_popover_layer(window)

    def _draw_recon(self, window: pg.Surface) -> None:
        """
        Draw the banner that says a game is still waiting on the server, with
        its amber dot and its Reconnect button. It is the coordinator's probe
        made visible, and pressing the button is what rejoins that game

        :param window: surface to draw on, the window or a scratch surface
        """
        fill = pg.Color(Colors.amber).lerp(pg.Color(Colors.surface_raised), 0.84)
        window.blit(cut_rect_surface(self._recon_rect.size, self._s(CHIP_CUT), fill,
                                     border=Colors.amber, border_width=1,
                                     corners=("tr", "bl")), self._recon_rect.topleft)
        dot_d = max(self._s(4), 3) * 2
        window.blit(circle_surface(dot_d, Colors.amber),
                    (self._recon_rect.x + self._s(16) - dot_d // 2,
                     self._recon_rect.centery - dot_d // 2))
        text = render_text(self._recon_font, "You have a game in progress", Colors.text)
        window.blit(text, (self._recon_rect.x + self._s(30),
                           self._recon_rect.centery - text.get_height() // 2))
        window.blit(cut_rect_surface(self._recon_button.size, self._s(6), Colors.surface,
                                     border=Colors.amber, border_width=1, corners=("tr", "bl")),
                    self._recon_button.topleft)
        label = render_text(self._recon_font, "Reconnect", Colors.amber_hi)
        window.blit(label, (self._recon_button.centerx - label.get_width() // 2,
                            self._recon_button.centery - label.get_height() // 2))

    def _draw_mode_chips(self, window: pg.Surface) -> None:
        """
        Draw the row of mode chips, showing at a glance which mode the next
        game will be. A mode that is not built yet is drawn as a dashed outline
        instead of a solid chip, so it reads as coming rather than broken

        :param window: surface to draw on, the window or a scratch surface
        """
        for label, key, locked in MODE_CHIPS:
            rect = self._mode_rects[key]
            if locked:
                window.blit(dashed_rounded_rect_surface(
                    rect.size, self._s(7), Colors.border, border_width=1,
                    dash=self._s(DASH_LEN), gap=self._s(DASH_GAP), fill=Colors.surface),
                    rect.topleft)
                text = render_text(self._chip_font, label, Colors.text_muted)
                window.blit(text, (rect.centerx - text.get_width() // 2,
                                   rect.centery - text.get_height() // 2))
                continue
            selected = key == self.selected_mode
            target = f"mode:{key}"
            hovered = self._hover_target == target
            pressed = self._press_target == target and hovered
            fill = Colors.surface_raised if selected else (
                Colors.surface_hover if hovered else Colors.surface)
            border = Colors.accent if selected else Colors.border
            color = Colors.text if selected or hovered else Colors.text_dim
            window.blit(cut_rect_surface(rect.size, self._s(CHIP_CUT), fill,
                                         border=border, border_width=1, corners=("tr", "bl")),
                        rect.topleft)
            text = render_text(self._chip_font, label, color)
            offset = self._s(PRESS_OFFSET_PX) if pressed else 0
            window.blit(text, (rect.centerx - text.get_width() // 2,
                               rect.centery - text.get_height() // 2 + offset))

    def _draw_time_chip(self, window: pg.Surface) -> None:
        """
        Draw the chip that shows the chosen time control -- clock icon, the
        reading, and a chevron that points up while the picker is open. It is
        tinted amber throughout, the colour the whole game uses for clocks

        :param window: surface to draw on, the window or a scratch surface
        """
        rect = self._time_chip
        hovered = self._hover_target == "time"
        pressed = self._press_target == "time" and hovered
        fill = Colors.surface_hover if hovered else (
            pg.Color(Colors.amber).lerp(pg.Color(Colors.surface_raised), 0.84))
        window.blit(cut_rect_surface(rect.size, self._s(CHIP_CUT), fill,
                                     border=Colors.amber, border_width=1, corners=("tr",)),
                    rect.topleft)
        pad = self._s(SUMMARY_CHIP_PAD_X)
        gap = self._s(SUMMARY_CHIP_GAP)
        icon = self._s(SUMMARY_CHIP_ICON)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        icon_rect = pg.Rect(rect.x + pad, rect.y + offset, icon, rect.height)
        draw_clock(window, icon_rect, Colors.amber_hi)
        value = self._time_value_surface()
        window.blit(value, (icon_rect.right + gap,
                            rect.centery - value.get_height() // 2 + offset))
        chevron = chevron_surface(self._s(SUMMARY_CHIP_CHEVRON), Colors.amber_hi,
                                  up=self._time_open)
        window.blit(chevron, (rect.right - pad - chevron.get_width(),
                              rect.centery - chevron.get_height() // 2 + offset))

    def _draw_side_chip(self, window: pg.Surface) -> None:
        """
        Draw the chip that shows which side the player will get -- the pawn or
        pawns, the label and a chevron that points up while the chooser is
        open. Its border lights with the accent colour while that popover is up

        :param window: surface to draw on, the window or a scratch surface
        """
        rect = self._side_chip
        hovered = self._hover_target == "side"
        pressed = self._press_target == "side" and hovered
        border = Colors.accent if self._side_open else (
            Colors.border_strong if hovered else Colors.border)
        fill = Colors.surface_hover if hovered else Colors.surface
        window.blit(cut_rect_surface(rect.size, self._s(CHIP_CUT), fill,
                                     border=border, border_width=1, corners=("tr",)),
                    rect.topleft)
        pad = self._s(SUMMARY_CHIP_PAD_X)
        gap = self._s(SUMMARY_CHIP_GAP)
        icon = self._s(SUMMARY_CHIP_ICON)
        icon_w = self._side_icon_width(icon)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        self._draw_summary_side_icon(window, rect.x + pad, rect.centery + offset, icon)
        label = render_text(self._chip_font, self._side_label_text(), Colors.text)
        window.blit(label, (rect.x + pad + icon_w + gap,
                            rect.centery - label.get_height() // 2 + offset))
        chevron = chevron_surface(self._s(SUMMARY_CHIP_CHEVRON), Colors.text_dim,
                                  up=self._side_open)
        window.blit(chevron, (rect.right - pad - chevron.get_width(),
                              rect.centery - chevron.get_height() // 2 + offset))

    def _draw_summary_side_icon(self, window: pg.Surface, x: int, cy: int,
                                size: int) -> None:
        """
        Draw the side chip's artwork: one pawn for a chosen colour, or a white
        and a black pawn overlapping for Random, which is the panel's way of
        saying the server will decide

        :param window: surface to draw on, the window or a scratch surface
        :param x: left edge of the artwork in window pixels
        :param cy: vertical middle of the artwork in window pixels
        :param size: height of a single pawn in pixels
        """
        if self.selected_side == "random":
            step = round(size * (SIDE_ICON_SPREAD - 1.0))
            self._blit_pawn(window, x + size // 2, cy, size, "white")
            self._blit_pawn(window, x + step + size // 2, cy, size, "black")
        else:
            self._blit_pawn(window, x + size // 2, cy, size, self.selected_side)

    def _blit_pawn(self, window: pg.Surface, cx: int, cy: int, size: int,
                   color: str) -> None:
        """
        Draw one pawn centred on a point, quietly drawing nothing at all when
        the artwork is missing so a lost file costs a picture, not a crash

        :param window: surface to draw on, the window or a scratch surface
        :param cx: horizontal middle of the pawn in window pixels
        :param cy: vertical middle of the pawn in window pixels
        :param size: wanted width and height in pixels
        :param color: side to picture, white or black
        """
        scaled = _scaled_side_image(color, size)
        if scaled is not None:
            window.blit(scaled, (cx - size // 2, cy - size // 2))

    def _draw_cta(self, window: pg.Surface) -> None:
        """
        Draw the big accent-coloured button that starts the game, the loudest
        thing on the menu. Hover and press each shift its colour, so it answers
        the cursor before it is even clicked

        :param window: surface to draw on, the window or a scratch surface
        """
        hovered = self._hover_target == "cta"
        pressed = self._press_target == "cta" and hovered
        fill = Colors.accent_press if pressed else (
            Colors.accent_hi if hovered else Colors.accent)
        window.blit(cut_rect_surface(self._cta_rect.size, self._s(CTA_CUT), fill,
                                     corners=("tr", "bl")), self._cta_rect.topleft)
        text = render_text(self._cta_font, self.cta_label(), Colors.on_accent)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        window.blit(text, (self._cta_rect.centerx - text.get_width() // 2,
                           self._cta_rect.centery - text.get_height() // 2 + offset))

    def _draw_fen_link(self, window: pg.Surface) -> None:
        """
        Draw the quiet text link that starts a local game from a pasted
        position. Its hover is read from the mouse as it draws rather than from
        the tracked hover target, since it is a link and not a chip

        :param window: surface to draw on, the window or a scratch surface
        """
        hovered = self._fen_rect.collidepoint(pg.mouse.get_pos())
        color = Colors.text_dim if hovered else Colors.text_muted
        text = render_text(self._link_font, "Start from FEN", color)
        window.blit(text, (self._fen_rect.x, self._fen_rect.centery - text.get_height() // 2))

    def _popover_panel(self, size: tuple[int, int]) -> pg.Surface:
        """
        Build the raised cut-corner panel both popovers sit on, so the time and
        side popovers are one shape and never drift apart

        :param size: width and height of the panel in pixels
        :returns: the panel surface, cached and shared by size
        """
        return cut_rect_surface(size, self._s(CTA_CUT), Colors.surface_raised,
                                border=Colors.border_strong, border_width=1,
                                corners=("tr", "bl"))

    def _draw_time_popover(self, window: pg.Surface) -> None:
        """
        Draw the settled time popover straight onto the target: the panel, then
        the revolver picker inside it

        :param window: surface to draw on, the window or the pop-in scratch
        """
        window.blit(self._popover_panel(self._time_popover.size), self._time_popover.topleft)
        self._picker.draw(window, pg.time.get_ticks())

    def _draw_side_popover(self, window: pg.Surface) -> None:
        """
        Draw the settled side popover straight onto the target: the panel, the
        three tiles and the readout strip along the bottom. Hover and press on
        the tiles are read from the mouse as it draws

        :param window: surface to draw on, the window or the pop-in scratch
        """
        window.blit(self._popover_panel(self._side_popover.size), self._side_popover.topleft)
        mouse = pg.mouse.get_pos()
        pressed = pg.mouse.get_pressed()[0]
        for label, key in SIDE_OPTIONS:
            self._draw_side_tile(window, key, label, mouse, pressed)
        self._draw_side_readout(window)

    def _draw_side_tile(self, window: pg.Surface, key: str, label: str,
                        mouse: tuple[int, int], mouse_down: bool) -> None:
        """
        Draw one of the three side tiles with its artwork and label, lit when
        it is the chosen side and pushed in while it is being held

        :param window: surface to draw on, the window or the pop-in scratch
        :param key: which side this tile picks, white, random or black
        :param label: the caption printed under the artwork
        :param mouse: cursor position in the same space as the tile rects,
            which is popover-local while the pop-in scratch is being drawn
        :param mouse_down: whether the left button is currently held
        """
        rect = self._side_rects[key]
        selected = key == self.selected_side
        hovered = rect.collidepoint(mouse)
        pressed = hovered and mouse_down
        fill = Colors.surface_raised if selected else (
            Colors.surface_hover if hovered else Colors.surface)
        border = Colors.accent if selected else Colors.border
        window.blit(cut_rect_surface(rect.size, self._s(SIDE_TILE_CUT), fill, border=border,
                                     border_width=1, corners=("tr", "bl")), rect.topleft)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        self._draw_side_tile_art(window, rect, key, offset)
        color = Colors.text if selected or hovered else Colors.text_dim
        text = render_text(self._chip_font, label, color)
        window.blit(text, (rect.centerx - text.get_width() // 2,
                           rect.bottom - self._s(SIDE_TILE_LABEL_BOTTOM)
                           - text.get_height() + offset))

    def _draw_side_tile_art(self, window: pg.Surface, rect: pg.Rect, key: str,
                            offset: int) -> None:
        """
        Draw the picture in the middle of a side tile: a pawn for a colour, a
        die for Random. Missing art falls back to a plain outlined square, so a
        tile is never a blank hole

        :param window: surface to draw on, the window or the pop-in scratch
        :param rect: the tile the art is centred in
        :param key: which side this tile picks, white, random or black
        :param offset: pixels to push the art down by while the tile is held
        """
        size = max(int(rect.width * SIDE_TILE_ART_FRAC), 1)
        cx = rect.centerx
        cy = rect.y + int(rect.height * SIDE_TILE_ART_CY_FRAC) + offset
        if key == "random":
            if not blit_emoji(window, "🎲", (cx, cy), size):
                pg.draw.rect(window, Colors.text_dim,
                             pg.Rect(cx - size // 2, cy - size // 2, size, size), 1,
                             border_radius=4)
            return
        scaled = _scaled_side_image(key, size)
        if scaled is not None:
            window.blit(scaled, (cx - size // 2, cy - size // 2))

    def _draw_side_readout(self, window: pg.Surface) -> None:
        """
        Draw the strip along the bottom of the side popover that spells out the
        current choice, the same job the picker's own readout does for the time
        control

        :param window: surface to draw on, the window or the pop-in scratch
        """
        rect = self._side_readout
        pg.draw.line(window, Colors.border_strong, (rect.x + self._s(SIDE_READOUT_INSET),
                     rect.y), (rect.right - self._s(SIDE_READOUT_INSET), rect.y))
        inset = self._s(SIDE_READOUT_INSET)
        label = render_text(self._side_readout_label_font, "SIDE", Colors.text_muted)
        value = render_text(self._side_readout_value_font, self._side_label_text(), Colors.text)
        window.blit(label, (rect.x + inset, rect.centery - label.get_height() // 2))
        window.blit(value, (rect.right - inset - value.get_width(),
                            rect.centery - value.get_height() // 2))

    def _popover_scratch(self, key: str, size: tuple[int, int]) -> pg.Surface:
        """
        Hand back a transparent surface a popover can be drawn into while it
        pops in or out, keeping one per popover so the animation does not
        allocate a surface every frame it runs

        :param key: which popover this surface belongs to, time or side
        :param size: width and height the surface must have, the popover's own
        :returns: a transparent surface of that size, reused whenever the size
            has not changed
        """
        cached = self._popover_scratches.get(key)
        if cached is not None and cached.get_size() == tuple(size):
            return cached
        scratch = pg.Surface(size, pg.SRCALPHA)
        self._popover_scratches[key] = scratch
        return scratch

    def _blit_popover_anim(self, window: pg.Surface, scratch: pg.Surface, rect: pg.Rect,
                           anim: _PopoverAnim, now: int) -> None:
        """
        Put an animating popover on screen: take the finished picture of it,
        squeeze it to this frame's scale and fade it to this frame's alpha.
        Drawing it once and scaling the result is what keeps the pop cheap

        :param window: surface to draw on, normally the window
        :param scratch: the popover already drawn at its laid-out size
        :param rect: where the popover sits, whose top left the scaled picture
            is pinned to
        :param anim: the animation deciding this frame's scale and alpha
        :param now: pygame tick count in milliseconds since pygame init
        """
        scale = anim.scale(now)
        alpha = anim.alpha(now)
        w = max(int(rect.width * scale), 1)
        h = max(int(rect.height * scale), 1)
        scaled = pg.transform.smoothscale(scratch, (w, h))
        scaled.set_alpha(alpha)
        window.blit(scaled, rect.topleft)

    def _draw_time_popover_layer(self, window: pg.Surface) -> None:
        """
        Draw the time popover at whatever stage it is in: nothing while closed,
        straight onto the window once open, and through the pop-in scratch
        while it is opening or closing. This is also where the animation is
        stepped, so it starts from the first frame that shows it

        :param window: surface to draw on, normally the window
        """
        anim = self._time_anim
        if anim.mode == "closed":
            return
        now = pg.time.get_ticks()
        anim.advance(now)
        if anim.mode == "closed":
            return
        if anim.mode == "open":
            self._draw_time_popover(window)
            return
        scratch = self._render_time_popover_scratch(now)
        self._blit_popover_anim(window, scratch, self._time_popover, anim, now)

    def _render_time_popover_scratch(self, now: int) -> pg.Surface:
        """
        Draw the whole time popover into its own surface with its top left at
        the origin, ready to be scaled and faded. The picker is moved into that
        local space to draw and put back before returning, so the geometry the
        player clicks on is unchanged

        :param now: pygame tick count in milliseconds since pygame init
        :returns: the popover drawn at its full laid-out size
        """
        rect = self._time_popover
        scratch = self._popover_scratch("time", rect.size)
        scratch.fill((0, 0, 0, 0))
        dx, dy = -rect.x, -rect.y
        local_rect = rect.move(dx, dy)
        scratch.blit(self._popover_panel(local_rect.size), local_rect.topleft)
        self._picker.set_rect(self._picker.rect.move(dx, dy))
        self._picker.draw(scratch, now)
        self._layout_time_popover()
        return scratch

    def _draw_side_popover_layer(self, window: pg.Surface) -> None:
        """
        Draw the side popover at whatever stage it is in, exactly as the time
        one is drawn: nothing while closed, straight onto the window once open,
        through the pop-in scratch while it moves

        :param window: surface to draw on, normally the window
        """
        anim = self._side_anim
        if anim.mode == "closed":
            return
        now = pg.time.get_ticks()
        anim.advance(now)
        if anim.mode == "closed":
            return
        if anim.mode == "open":
            self._draw_side_popover(window)
            return
        scratch = self._render_side_popover_scratch()
        self._blit_popover_anim(window, scratch, self._side_popover, anim, now)

    def _render_side_popover_scratch(self) -> pg.Surface:
        """
        Draw the whole side popover into its own surface with its top left at
        the origin. The popover, its tiles and the cursor are all shifted into
        that local space for the drawing and the real rects are restored before
        returning, so nothing the player clicks on moves

        :returns: the popover drawn at its full laid-out size
        """
        rect = self._side_popover
        scratch = self._popover_scratch("side", rect.size)
        scratch.fill((0, 0, 0, 0))
        dx, dy = -rect.x, -rect.y
        self._side_popover = rect.move(dx, dy)
        for key, tile in list(self._side_rects.items()):
            self._side_rects[key] = tile.move(dx, dy)
        self._side_readout = self._side_readout.move(dx, dy)
        mouse = pg.mouse.get_pos()
        local_mouse = (mouse[0] + dx, mouse[1] + dy)
        pressed = pg.mouse.get_pressed()[0]
        scratch.blit(self._popover_panel(self._side_popover.size), self._side_popover.topleft)
        for label, key in SIDE_OPTIONS:
            self._draw_side_tile(scratch, key, label, local_mouse, pressed)
        self._draw_side_readout(scratch)
        self._layout_side_popover()
        return scratch
