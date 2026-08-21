from collections.abc import Callable

import pygame as pg

from chessshootout.frontend.visual.cache import render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    cut_rect_surface, infinity_surface, notch_geometry, notch_value_from_click,
    notch_readout_slot_w,
)
from chessshootout.frontend.visual.fonts import get_mono_font
from chessshootout.frontend.visual.scroll_view import ScrollHost, ScrollView
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.widgets import draw_toggle


CARD_CUT = 8
CARD_PAD_X = 16
ROW_PAD_Y = 13
LABEL_DESC_GAP = 3
CONTROL_GAP = 18
SECTION_LABEL_GAP = 9
SECTION_GAP = 18
SCROLLBAR_RESERVE = 14
OPTIONS_WHEEL_STEP = 30

TOGGLE_W = 46
TOGGLE_H = 24
TOGGLE_HIT_PAD_X = 16
TOGGLE_HIT_PAD_Y = 14
TOGGLE_SNAP_EPS = 0.02
TOGGLE_LERP = 0.3

NOTCH_COUNT = 10
NOTCH_CELL_W = 13
NOTCH_CELL_H = 22
NOTCH_GAP = 4
NOTCH_CELL_CUT = 3
NOTCH_READOUT_GAP = 12
NOTCH_HIT_PAD_X = 14
NOTCH_HIT_PAD_Y = 16

SEG_MIN_H = 30
SEG_PAD_X = 14
SEG_GAP = 8
SEG_CUT = 6
CELL_GAP = 6
CELL_CUT = 5
CELL_PAD_X = 10

FIELD_H = 34
BTN_PAD_X = 14
BTN_CUT = 6
BTN_GAP = 8
RESET_PAD_X = 10
FIELD_LEFT_FRAC = 0.40

REVEAL_LERP = 0.24
REVEAL_SNAP_EPS = 0.01

ACTION_STATUS_GAP = 12
ACTION_MIN_LABEL_W = 120

TONE_OK = "ok"
TONE_WARN = "warn"
TONE_IDLE = "idle"

_STATUS_TONES = {TONE_OK: Colors.win, TONE_WARN: Colors.loss, TONE_IDLE: Colors.text_muted}


class Fonts:
    """
    The five faces an options row draws with -- row title, description, section
    heading, value text and button label. They are loaded once by the Options
    sub-view and handed down, so no row loads a font of its own and a resize
    replaces the whole set in one place
    """

    __slots__ = ("title", "desc", "section", "value", "button")

    def __init__(self, title: pg.font.Font, desc: pg.font.Font, section: pg.font.Font,
                 value: pg.font.Font, button: pg.font.Font) -> None:
        """
        Bundle one set of already-loaded faces for the rows to share

        :param title: face for a row's title line
        :param desc: smaller face for the dim line under the title
        :param section: face for the heading above each card
        :param value: monospaced face for values, paths and status lines
        :param button: face for the labels on buttons and chips
        """
        self.title = title
        self.desc = desc
        self.section = section
        self.value = value
        self.button = button


def _blit_clip(window: pg.Surface, surf: pg.Surface, pos: tuple[int, int],
               max_w: int) -> None:
    """
    Draw a piece of text but never let it run past the room it was given, which
    is what stops a long row title from sliding under its own control. Text
    that already fits is drawn untouched

    :param window: surface drawn to, normally the app window
    :param surf: text surface to draw; it is shared and cached, so an over-wide
        one is cropped through a subsurface rather than resized
    :param pos: top-left corner to draw at, in window pixels
    :param max_w: width the text may occupy in pixels; zero or less draws it
        whole
    """
    if surf.get_width() > max_w > 0:
        surf = surf.subsurface(pg.Rect(0, 0, int(max_w), surf.get_height()))
    window.blit(surf, pos)


def _fitting_ellipsis(font: pg.font.Font) -> str:
    """
    Pick the ellipsis a font can really draw, so a trimmed path never ends in
    an empty box. A face missing the single-character form measures it exactly
    like a private-use character nothing defines, and that is the tell this
    checks before falling back to three dots

    :param font: font the elided text will be drawn in
    :returns: the ellipsis to use, one character or three dots
    """
    metrics = font.metrics(chr(0x2026))
    if not metrics or metrics[0] is None or metrics == font.metrics(chr(0xE000)):
        return "..."
    return "…"


def _elide_left(font: pg.font.Font, text: str, max_w: int) -> str:
    """
    Trim text from the left until it fits, which keeps the end on screen -- for
    a folder path or a server verdict that is the part that identifies it. Text
    that already fits comes back untouched

    :param font: font the text will be drawn in
    :param text: text to fit, normally a path or a status line
    :param max_w: width available in pixels
    :returns: the text, or a left-trimmed version led by an ellipsis
    """
    if font.size(text)[0] <= max_w:
        return text
    ell = _fitting_ellipsis(font)
    budget = max(max_w - font.size(ell)[0], 0)
    while text and font.size(text)[0] > budget:
        text = text[1:]
    return ell + text


def _draw_cut_button(window: pg.Surface, rect: pg.Rect, font: pg.font.Font,
                     label: str) -> None:
    """
    Draw the small cut-corner button the rows carry -- Change on the games
    folder and Test on the connection row both come from here, so every button
    inside the settings list wears the same shape

    :param window: surface drawn to, normally the app window
    :param rect: the button's box in window pixels
    :param font: face for the label
    :param label: text drawn centred in the button
    """
    window.blit(cut_rect_surface(rect.size, BTN_CUT, Colors.surface_raised,
                                 border=Colors.border, border_width=1, corners=("tr",)),
                rect.topleft)
    text = render_text(font, label, Colors.text)
    window.blit(text, (rect.centerx - text.get_width() // 2,
                       rect.centery - text.get_height() // 2))


def _seg_glyph(font: pg.font.Font, label: str, color: str) -> pg.Surface:
    """
    Render one option label for a segmented row, swapping in the drawn figure
    of eight wherever the untimed time control is offered, since that mark is a
    curve rather than a character any of the bundled faces carry

    :param font: face for the label
    :param label: option label as the player reads it
    :param color: ink colour as a hex token from Colors
    :returns: the label surface, shared and to be treated as read-only
    """
    if label == "∞":
        return infinity_surface(int(font.get_height() * 0.82), color)
    return render_text(font, label, color)


class _Row:
    """
    The shape every settings row has: a title with an optional dim line under
    it on the left, and a control hard against the right edge. Subclasses bring
    the control -- a switch, notches, chips, a text field, a button -- and
    inherit the measuring, the label drawing and the click plumbing
    """

    def __init__(self, title: str, desc: str = "") -> None:
        """
        Build a row with the text the player reads. Where anything sits is
        settled the first time the row is drawn, not here

        :param title: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        """
        self.title = title
        self.desc = desc

    def tick(self) -> None:
        """
        Advance whatever this row animates, run once a frame before the row is
        measured. Most rows animate nothing, so the base row does nothing
        """
        pass

    def animating(self) -> bool:
        """
        Whether this row's height is still moving, which the card behind it
        reads to keep its background at the settled size instead of reshaping
        every frame

        :returns: True while an animation is running
        """
        return False

    def _control_h(self, fonts: Fonts) -> int:
        """
        How tall this row's control is, which sets the row height together with
        the label. The base row has no control at all

        :param fonts: the faces this row draws with, for a control sized off
            its own text
        :returns: control height in pixels
        """
        return 0

    def _label_h(self, fonts: Fonts) -> int:
        """
        How tall the text block on the left is -- the title alone, or the title
        with the description line under it

        :param fonts: the faces this row draws with
        :returns: label height in pixels
        """
        h = fonts.title.get_height()
        if self.desc:
            h += fonts.desc.get_height() + LABEL_DESC_GAP
        return h

    def height(self, fonts: Fonts) -> int:
        """
        The height this row takes in its card right now, which is what the list
        stacks every row against. Whichever of the label and the control is
        taller decides it

        :param fonts: the faces this row draws with
        :returns: row height in pixels, padding included
        """
        return 2 * ROW_PAD_Y + max(self._label_h(fonts), self._control_h(fonts))

    def full_height(self, fonts: Fonts) -> int:
        """
        The height this row takes once nothing is animating. The card draws its
        background at this size, so an animating row does not mint a fresh card
        surface on every frame

        :param fonts: the faces this row draws with
        :returns: settled row height in pixels
        """
        return self.height(fonts)

    def draw(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> None:
        """
        Paint the row. The control goes first, because where it lands is what
        decides how much room the title has, and the label is then clipped to
        whatever is left of the row

        :param window: surface drawn to, normally the app window
        :param rect: the row's box inside its card, in window pixels
        :param fonts: the faces this row draws with
        """
        control_left = self._draw_control(window, rect, fonts)
        self._draw_label(window, rect, fonts, control_left - CONTROL_GAP)

    def _draw_label(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts,
                    max_right: int) -> None:
        """
        Draw the title and its description, centred against the row and both
        cut off before the control rather than running under it

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :param max_right: window x the text must stop before
        """
        x = rect.x
        avail = max(max_right - x, 1)
        y = rect.centery - self._label_h(fonts) // 2
        _blit_clip(window, render_text(fonts.title, self.title, Colors.text), (x, y), avail)
        if self.desc:
            _blit_clip(window, render_text(fonts.desc, self.desc, Colors.text_muted),
                       (x, y + fonts.title.get_height() + LABEL_DESC_GAP), avail)

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Draw this row's control against the right edge and report where it
        begins, which is the measure the label is clipped against. The base row
        draws nothing and claims no width

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x of the control's left edge
        """
        return rect.right

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Take a click that landed in this row's card. A row claims it only when
        the click really worked its control, which is how the list knows to
        stop offering it to further rows

        :param pos: click position in window pixels
        :returns: True when the row acted on the click
        """
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on this row's control, hit padding included. The
        list asks before starting a scroll drag, so a press meant for a switch
        or a field is never swallowed as a gesture

        :param pos: position in window pixels
        :returns: True when the control owns that spot
        """
        return False

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Take a key press, which only the rows holding a text field ever want

        :param event: pygame KEYDOWN event
        :returns: True when the row consumed the key
        """
        return False

    def cancel_edit(self) -> bool:
        """
        Give up a half-typed value and put the stored one back, which is what
        Esc does inside Options. Declining lets that press fall through to
        leaving the sub-view

        :returns: True when there was an edit to cancel
        """
        return False


class ToggleRow(_Row):
    """
    The on/off row -- mute, auto-queen, hiding the opponent's marks, each of
    the performance readouts. It reads and writes the stored setting straight
    through the getter and setter it was built with, and slides the knob across
    instead of snapping it
    """

    def __init__(self, title: str, desc: str, getter: Callable[[], bool],
                 setter: Callable[[bool], None]) -> None:
        """
        Build a switch wired to one stored setting

        :param title: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        :param getter: reads the setting, True meaning on
        :param setter: writes the flipped value, which bites immediately
        """
        super().__init__(title, desc)
        self.getter = getter
        self.setter = setter
        self._ctl = pg.Rect(0, 0, 0, 0)
        self._pos: float | None = None

    def _control_h(self, fonts: Fonts) -> int:
        """
        The switch is one fixed size, so only the label can make this row any
        taller

        :param fonts: the faces this row draws with, which a fixed-size switch
            never consults
        :returns: switch height in pixels
        """
        return TOGGLE_H

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Place the switch at the right edge and draw it, easing the knob a
        fraction of the way toward the stored state each frame so a flip reads
        as a slide. A knob near enough its target covers the rest in one step
        and stops moving

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x of the switch's left edge
        """
        self._ctl = pg.Rect(rect.right - TOGGLE_W, rect.centery - TOGGLE_H // 2,
                            TOGGLE_W, TOGGLE_H)
        target = 1.0 if self.getter() else 0.0
        if self._pos is None or abs(self._pos - target) < TOGGLE_SNAP_EPS:
            self._pos = target
        else:
            self._pos += (target - self._pos) * TOGGLE_LERP
        draw_toggle(window, self._ctl, self._pos)
        return self._ctl.x

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Flip the setting when the click landed on the switch, storing the
        opposite of whatever the getter reports

        :param pos: click position in window pixels
        :returns: True when the switch took the click
        """
        if self.contains_control(pos):
            self.setter(not self.getter())
            return True
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on the switch, padded well past the drawn track
        so the small control is still easy to hit

        :param pos: position in window pixels
        :returns: True when the switch owns that spot
        """
        return self._ctl.inflate(TOGGLE_HIT_PAD_X, TOGGLE_HIT_PAD_Y).collidepoint(pos)


class NotchRow(_Row):
    """
    The volume row: ten notch cells and a percentage beside them standing in
    for a slider, used by the master and menu levels. Clicking a cell sets that
    level, and clicking the first cell when it already is the level drops to
    zero, so the first notch doubles as a mute
    """

    def __init__(self, title: str, desc: str, getter: Callable[[], float],
                 setter: Callable[[float], None],
                 on_tick: Callable[[], None] | None = None,
                 on_release: Callable[[], None] | None = None) -> None:
        """
        Build a notch strip wired to a level, with optional hooks for the click
        the player hears and for saving where they settled

        :param title: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        :param getter: reads the level in force, 0.0 through 1.0
        :param setter: applies a new level live, before anything is stored
        :param on_tick: plays the click feedback, or None for a silent row
        :param on_release: asks for the settled level to be written, or None
            when this level is not stored at all
        """
        super().__init__(title, desc)
        self.getter = getter
        self.setter = setter
        self.on_tick = on_tick
        self.on_release = on_release
        self._band = pg.Rect(0, 0, 0, 0)

    def _control_h(self, fonts: Fonts) -> int:
        """
        The strip is as tall as its cells, or as tall as the percentage next to
        them when that font is the bigger of the two

        :param fonts: the faces this row draws with
        :returns: control height in pixels
        """
        return max(NOTCH_CELL_H, fonts.value.get_height())

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Draw the percentage and the cells filled up to it, filled ones in the
        accent and the rest as empty wells. The readout keeps a slot as wide as
        a full hundred percent, so the cells never shift as the number changes

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x of the notch strip's left edge
        """
        value = max(0.0, min(1.0, self.getter()))
        readout = render_text(fonts.value, f"{int(round(value * 100))}%", Colors.text_dim)
        slot_w = notch_readout_slot_w(fonts.value)
        window.blit(readout, (rect.right - readout.get_width(),
                              rect.centery - readout.get_height() // 2))
        x0, total_w = notch_geometry(rect.width, NOTCH_COUNT, NOTCH_CELL_W, NOTCH_GAP,
                                     slot_w, NOTCH_READOUT_GAP)
        cx = rect.x + x0
        cy = rect.centery - NOTCH_CELL_H // 2
        filled = int(round(value * NOTCH_COUNT))
        for i in range(NOTCH_COUNT):
            cell = pg.Rect(cx + i * (NOTCH_CELL_W + NOTCH_GAP), cy, NOTCH_CELL_W, NOTCH_CELL_H)
            if i < filled:
                window.blit(cut_rect_surface(cell.size, NOTCH_CELL_CUT, Colors.accent,
                                             corners=("tr",)), cell.topleft)
            else:
                window.blit(cut_rect_surface(cell.size, NOTCH_CELL_CUT, Colors.surface_raised,
                                             border=Colors.border, border_width=1,
                                             corners=("tr",)), cell.topleft)
        self._band = pg.Rect(cx, cy, total_w, NOTCH_CELL_H)
        return cx

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Apply the level the clicked cell stands for, play the tick and ask for
        that level to be saved. A click off the strip changes nothing

        :param pos: click position in window pixels
        :returns: True when the strip took the click
        """
        if not self.contains_control(pos):
            return False
        step = NOTCH_CELL_W + NOTCH_GAP
        target = notch_value_from_click(pos[0], self._band.x, step, NOTCH_COUNT,
                                        self.getter())
        self.setter(target)
        if self.on_tick is not None:
            self.on_tick()
        if self.on_release is not None:
            self.on_release()
        return True

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on the notch strip, padded so the thin cells stay
        comfortable to hit

        :param pos: position in window pixels
        :returns: True when the strip owns that spot
        """
        return self._band.inflate(NOTCH_HIT_PAD_X, NOTCH_HIT_PAD_Y).collidepoint(pos)


class SegmentedRow(_Row):
    """
    The pick-one row: launch mode, what focus mode keeps on screen, the default
    clock and increment, and the server picker. Its options draw either as
    labelled chips or as small square value cells, and the chosen one wears the
    accent
    """

    def __init__(self, title: str, desc: str, options: list[tuple[str, str]],
                 getter: Callable[[], str], setter: Callable[[str], None],
                 mono: bool = False, variant: str = "chips") -> None:
        """
        Build a segmented row over a fixed set of options, wired to the setting
        that holds the choice

        :param title: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        :param options: label and stored value of each option, in display order
        :param getter: reads the value currently chosen
        :param setter: stores the value the player picked
        :param mono: True for the monospaced face, used where the options are
            numbers
        :param variant: chips for labelled buttons, cells for small squares
        """
        super().__init__(title, desc)
        self.options = options
        self.getter = getter
        self.setter = setter
        self.mono = mono
        self.variant = variant
        self._rects: dict[str, pg.Rect] = {}
        self._mono_font: tuple[int, pg.font.Font] | None = None
        self._layout_cache: tuple[tuple[int, int], tuple[list[int], int, int]] | None = None

    def _seg_h(self, fonts: Fonts) -> int:
        """
        How tall one segment is: enough for its label, never below the minimum
        that keeps a chip comfortable to hit

        :param fonts: the faces this row draws with
        :returns: segment height in pixels
        """
        return max(fonts.button.get_height() + 12, SEG_MIN_H)

    def _control_h(self, fonts: Fonts) -> int:
        """
        The control is a single line of segments, so it stands exactly as tall
        as one of them

        :param fonts: the faces this row draws with
        :returns: control height in pixels
        """
        return self._seg_h(fonts)

    def _font(self, fonts: Fonts) -> pg.font.Font:
        """
        The face the option labels are drawn in: the shared button face, or a
        slightly smaller monospaced one for rows whose options are numbers.
        That mono face is kept until its size changes, since loading a font is
        not free

        :param fonts: the faces this row draws with
        :returns: the font to render the option labels with
        """
        if not self.mono:
            return fonts.button
        size = max(int(fonts.button.get_height() * 0.9), 13)
        if self._mono_font is None or self._mono_font[0] != size:
            self._mono_font = (size, get_mono_font(size, bold=True))
        return self._mono_font[1]

    def _layout(self, font: pg.font.Font, h: int) -> tuple[list[int], int, int]:
        """
        Work out how wide the segments are and how they are spaced -- equal
        squares for the cells variant, label-width chips otherwise. The answer
        is kept against the font and height it was measured for, so a settled
        row measures nothing per frame

        :param font: font the option labels are drawn in
        :param h: segment height in pixels, which also squares a value cell
        :returns: the segment widths, the corner cut and the gap between two
            segments, all in pixels
        """
        key = (id(font), h)
        if self._layout_cache is not None and self._layout_cache[0] == key:
            return self._layout_cache[1]
        if self.variant == "cells":
            cell_w = max(h, max(_seg_glyph(font, label, Colors.text_dim).get_width()
                                for label, _ in self.options) + 2 * CELL_PAD_X)
            result = ([cell_w] * len(self.options), CELL_CUT, CELL_GAP)
        else:
            widths = [_seg_glyph(font, label, Colors.text_dim).get_width() + 2 * SEG_PAD_X
                      for label, _ in self.options]
            result = (widths, SEG_CUT, SEG_GAP)
        self._layout_cache = (key, result)
        return result

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Draw the segments as one block against the right edge and remember
        where each landed, which is what a later click is matched against. The
        chosen one is drawn raised, in the accent, so the current setting reads
        at a glance

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x of the leftmost segment
        """
        font = self._font(fonts)
        h = self._seg_h(fonts)
        y = rect.centery - h // 2
        widths, cut, gap = self._layout(font, h)
        x = rect.right - (sum(widths) + gap * (len(widths) - 1))
        left = x
        self._rects = {}
        for (label, key), w in zip(self.options, widths):
            sr = pg.Rect(round(x), y, round(w), h)
            selected = key == self.getter()
            fill = Colors.surface_raised if selected else Colors.surface
            border = Colors.accent if selected else Colors.border
            color = Colors.text if selected else Colors.text_dim
            window.blit(cut_rect_surface(sr.size, cut, fill, border=border,
                                         border_width=1, corners=("tr",)), sr.topleft)
            glyph = _seg_glyph(font, label, color)
            window.blit(glyph, (sr.centerx - glyph.get_width() // 2,
                                sr.centery - glyph.get_height() // 2))
            self._rects[key] = sr
            x += w + gap
        return int(left)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Store the option whose segment was clicked. A click that misses every
        segment leaves the setting alone

        :param pos: click position in window pixels
        :returns: True when a segment took the click
        """
        for key, r in self._rects.items():
            if r.collidepoint(pos):
                self.setter(key)
                return True
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on one of the segments, which is what stops a
        press on a chip from beginning a scroll drag instead

        :param pos: position in window pixels
        :returns: True when a segment owns that spot
        """
        return any(r.collidepoint(pos) for r in self._rects.values())


class PathRow(_Row):
    """
    The games-folder row: where the PGNs are saved, shown in a field the player
    may type into, with a Change button that opens the in-app folder browser
    and a Reset that goes back to the platform's own place. The fixed suffix
    after the path names the sub-folder the games themselves land in
    """

    def __init__(self, label: str, desc: str, window: pg.Surface,
                 value_getter: Callable[[], str], on_change: Callable[[], None],
                 on_reset: Callable[[], None], suffix: str = "") -> None:
        """
        Build the row with the stored folder already in its field. The folder
        is only ever read back through the getter, so one changed elsewhere
        shows up here without the row being rebuilt

        :param label: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        :param window: the app window surface the text field draws onto
        :param value_getter: reads the folder currently stored
        :param on_change: opens the folder browser, the Change button's action
        :param on_reset: restores the default folder, the Reset button's action
        :param suffix: fixed tail drawn after the path, the sub-folder saved
            games land in
        """
        super().__init__(label, desc)
        self.value_getter = value_getter
        self.on_change = on_change
        self.on_reset = on_reset
        self.suffix = suffix
        self.input = TextInput(window, max_chars=512, placeholder="data folder path",
                               mono=True, bg=Colors.bg, radius=6, rest_align="end")
        self.input.padding = 10
        self.input.text = str(value_getter())
        self._change_rect = pg.Rect(0, 0, 0, 0)
        self._reset_rect = pg.Rect(0, 0, 0, 0)
        self._field_rect = pg.Rect(0, 0, 0, 0)
        self._rest_cache: tuple[tuple[int, str, int], pg.Surface] | None = None

    def _control_h(self, fonts: Fonts) -> int:
        """
        The field and its two buttons all stand at one fixed height, so this
        control never depends on the fonts

        :param fonts: the faces this row draws with, which a fixed-height
            control never consults
        :returns: control height in pixels
        """
        return FIELD_H

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Lay out and draw Reset, Change and the path field, placed from the
        right edge inwards. A field nobody is typing in is repainted from the
        stored folder and drawn at rest, tail first, so the end of a long path
        is the part that stays on screen

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x of the field's left edge
        """
        y = rect.centery - FIELD_H // 2
        if not self.input.focused and self.input.text != str(self.value_getter()):
            self.input.text = str(self.value_getter())
        reset_surf = render_text(fonts.button, "Reset", Colors.text_dim)
        reset_w = reset_surf.get_width() + 2 * RESET_PAD_X
        self._reset_rect = pg.Rect(rect.right - reset_w, y, reset_w, FIELD_H)
        change_w = fonts.button.size("Change")[0] + 2 * BTN_PAD_X
        self._change_rect = pg.Rect(self._reset_rect.x - BTN_GAP - change_w, y,
                                    change_w, FIELD_H)
        field_left = rect.x + int(rect.width * FIELD_LEFT_FRAC)
        self._field_rect = pg.Rect(field_left, y,
                                   max(self._change_rect.x - BTN_GAP - field_left, 1), FIELD_H)
        self.input.set_rect(self._field_rect)
        self.input.font = fonts.value
        if self.input.focused:
            self.input.draw(window)
        else:
            self._draw_rest_path(window, fonts)
        _draw_cut_button(window, self._change_rect, fonts.button, "Change")
        window.blit(reset_surf, (self._reset_rect.centerx - reset_surf.get_width() // 2,
                                 self._reset_rect.centery - reset_surf.get_height() // 2))
        return self._field_rect.x

    def _draw_rest_path(self, window: pg.Surface, fonts: Fonts) -> None:
        """
        Draw the folder as it looks at rest: the path, left-trimmed to fit,
        followed by its fixed suffix, both pushed against the right of the
        field and clipped to it. The trimmed surface is kept until the text,
        the width or the font changes, so a settled row renders nothing

        :param window: surface drawn to, normally the app window
        :param fonts: the faces this row draws with
        """
        fr = self._field_rect
        suffix_surf = render_text(fonts.value, self.suffix, Colors.text_dim) \
            if self.suffix else None
        suffix_w = suffix_surf.get_width() if suffix_surf else 0
        avail = max(fr.width - suffix_w, 1)
        key = (id(fonts.value), self.input.text, avail)
        if self._rest_cache is None or self._rest_cache[0] != key:
            path_text = _elide_left(fonts.value, self.input.text, avail)
            self._rest_cache = (key, render_text(fonts.value, path_text, Colors.text_muted))
        path_surf = self._rest_cache[1]
        total = path_surf.get_width() + suffix_w
        prev = window.get_clip()
        window.set_clip(fr.clip(prev))
        x = fr.right - total
        window.blit(path_surf, (x, fr.centery - path_surf.get_height() // 2))
        if suffix_surf:
            window.blit(suffix_surf, (x + path_surf.get_width(),
                                      fr.centery - suffix_surf.get_height() // 2))
        window.set_clip(prev)

    def current_text(self) -> str:
        """
        The folder as it stands in the field this moment, committed or still
        being typed. It is what the options exit gate validates and applies

        :returns: the field's text with surrounding space trimmed
        """
        return self.input.text.strip()

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Route a click to Change, to Reset or into the field. A click anywhere
        else in the row drops focus, which parks whatever was typed rather than
        committing it

        :param pos: click position in window pixels
        :returns: True when the click landed on the field or a button
        """
        if self._change_rect.collidepoint(pos):
            self.input.focused = False
            self.on_change()
            return True
        if self._reset_rect.collidepoint(pos):
            self.input.focused = False
            self.on_reset()
            return True
        if self._field_rect.collidepoint(pos):
            self.input.handle_click(pos)
            return True
        self.input.focused = False
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on the field or on either of the two buttons

        :param pos: position in window pixels
        :returns: True when the control owns that spot
        """
        return (self._change_rect.collidepoint(pos) or self._reset_rect.collidepoint(pos)
                or self._field_rect.collidepoint(pos))

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Feed typing to the folder field, which only takes keys while it holds
        focus

        :param event: pygame KEYDOWN event
        :returns: True when the field consumed the key
        """
        return self.input.handle_key(event)

    def cancel_edit(self) -> bool:
        """
        Drop a half-typed folder on Esc and put the stored one back, so the
        exit gate never sees a fragment and either complains it cannot be
        written to or moves the saved games somewhere unintended

        :returns: True when a focused edit was cancelled
        """
        if not self.input.focused:
            return False
        self.input.focused = False
        self.input.text = str(self.value_getter())
        return True


class TextRow(_Row):
    """
    The plain typing row, used for the address of a server the player runs
    themselves. Enter commits the value through the commit hook; clicking away
    parks the edit instead, with the options exit gate as the backstop that
    saves it
    """

    def __init__(self, label: str, desc: str, window: pg.Surface,
                 value_getter: Callable[[], str], placeholder: str = "",
                 on_commit: Callable[[str], None] | None = None) -> None:
        """
        Build the row with the stored value already in its field

        :param label: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        :param window: the app window surface the text field draws onto
        :param value_getter: reads the value currently stored
        :param placeholder: dim hint shown while the field is empty
        :param on_commit: run with the typed value when Enter lands, or None to
            leave committing to the exit gate
        """
        super().__init__(label, desc)
        self.value_getter = value_getter
        self.on_commit = on_commit
        self.input = TextInput(window, max_chars=128, placeholder=placeholder,
                               mono=True, bg=Colors.bg, radius=6)
        self.input.padding = 11
        self.input.text = str(value_getter())
        self._edited = False
        self._field_rect = pg.Rect(0, 0, 0, 0)

    def _control_h(self, fonts: Fonts) -> int:
        """
        The field stands at one fixed height, so this control never depends on
        the fonts

        :param fonts: the faces this row draws with, which a fixed-height field
            never consults
        :returns: control height in pixels
        """
        return FIELD_H

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Place the field across the right of the row and draw it. A field that
        is neither focused nor holding an unsaved edit is repainted from the
        stored value, which is how a change made elsewhere shows up; a parked
        edit is left standing until it is committed or cancelled

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x of the field's left edge
        """
        y = rect.centery - FIELD_H // 2
        if not self.input.focused and not self._edited \
                and self.input.text != str(self.value_getter()):
            self.input.text = str(self.value_getter())
        field_left = rect.x + int(rect.width * FIELD_LEFT_FRAC)
        self._field_rect = pg.Rect(field_left, y, rect.right - field_left, FIELD_H)
        self.input.set_rect(self._field_rect)
        self.input.font = fonts.value
        self.input.draw(window)
        return self._field_rect.x

    def current_text(self) -> str:
        """
        The value as it stands in the field this moment, committed or still
        being typed. It is what the options exit gate commits

        :returns: the field's text with surrounding space trimmed
        """
        return self.input.text.strip()

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Focus the field when the click landed inside it, and drop focus
        otherwise, which parks the edit without saving it

        :param pos: click position in window pixels
        :returns: True when the click landed in the field
        """
        if self._field_rect.collidepoint(pos):
            self.input.handle_click(pos)
            return True
        self.input.focused = False
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is inside the text field

        :param pos: position in window pixels
        :returns: True when the field owns that spot
        """
        return self._field_rect.collidepoint(pos)

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Feed typing to the field, with Enter as the save: it hands the value to
        the commit hook and clears the unsaved mark, so the next frame may
        follow the stored value again. Any other key that lands marks the row
        as holding an edit, which is what keeps it from being painted over

        :param event: pygame KEYDOWN event
        :returns: True when the field consumed the key
        """
        if not self.input.focused:
            return False
        handled = self.input.handle_key(event)
        if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
            self._edited = False
            if self.on_commit is not None:
                self.on_commit(self.current_text())
        elif handled:
            self._edited = True
        return handled

    def cancel_edit(self) -> bool:
        """
        Drop the typed value on Esc and put the stored one back, so an address
        the player was still working on is never saved by the exit gate

        :returns: True when there was a focused or parked edit to cancel
        """
        if not self.input.focused and not self._edited:
            return False
        self._edited = False
        self.input.focused = False
        self.input.text = str(self.value_getter())
        return True


class RevealRow(_Row):
    """
    A wrapper that slides another row open and shut as a setting elsewhere
    turns it on and off -- the custom server address, which only belongs on
    screen while the player's own server is the chosen one. It animates its own
    height and gates every click and key by whether the row is really showing
    """

    def __init__(self, inner: _Row, visible_getter: Callable[[], bool]) -> None:
        """
        Wrap a row and tie its presence to a getter. The animation starts
        already settled, so opening Options on a row that simply belongs there
        never plays a reveal

        :param inner: the row being revealed, whose title and description this
            one shows as its own
        :param visible_getter: reads whether the inner row belongs on screen
        """
        super().__init__(inner.title, inner.desc)
        self.inner = inner
        self.visible_getter = visible_getter
        self._t = 1.0 if visible_getter() else 0.0
        self._collapse_cancelled = self._t == 0.0
        self._rect = pg.Rect(0, 0, 0, 0)

    def tick(self) -> None:
        """
        Step the reveal one frame toward open or shut. The very first frame of
        a collapse cancels whatever was being typed in the inner row, so a
        field about to disappear can never keep a half-typed value alive long
        enough for the exit gate to save it
        """
        visible = self.visible_getter()
        if visible:
            self._collapse_cancelled = False
        elif not self._collapse_cancelled:
            self._collapse_cancelled = True
            self.inner.cancel_edit()
        target = 1.0 if visible else 0.0
        if abs(self._t - target) < REVEAL_SNAP_EPS:
            self._t = target
        else:
            self._t += (target - self._t) * REVEAL_LERP

    def animating(self) -> bool:
        """
        Whether the reveal is somewhere between shut and open, which keeps the
        card behind it drawing at its settled height

        :returns: True while the slide is still running
        """
        return 0.0 < self._t < 1.0

    def height(self, fonts: Fonts) -> int:
        """
        The height this row takes on this frame, the inner row's scaled by how
        far the reveal has opened. Fully shut it is nothing at all, so the card
        closes up around it

        :param fonts: the faces this row draws with
        :returns: current row height in pixels
        """
        return int(round(self.inner.height(fonts) * self._t))

    def full_height(self, fonts: Fonts) -> int:
        """
        The inner row's settled height, ignoring the reveal, which is the size
        the card draws its background at while the slide runs

        :param fonts: the faces this row draws with
        :returns: settled row height in pixels
        """
        return self.inner.height(fonts)

    def draw(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> None:
        """
        Draw the inner row at its full height but clipped to the sliver the
        reveal currently allows, centred in it, so the row appears to slide out
        from behind the card edge rather than squash flat

        :param window: surface drawn to, normally the app window
        :param rect: the slot this row was given inside the card, in window
            pixels
        :param fonts: the faces this row draws with
        """
        self._rect = pg.Rect(rect)
        full_h = self.inner.height(fonts)
        prev = window.get_clip()
        window.set_clip(rect.clip(prev))
        self.inner.draw(window, pg.Rect(rect.x, rect.centery - full_h // 2,
                                        rect.width, full_h), fonts)
        window.set_clip(prev)

    def _live(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is inside the part of the row actually on screen.
        The inner row keeps the rects it was last drawn at even while
        collapsed, so the drawn slot, never those rects, is what decides

        :param pos: position in window pixels
        :returns: True when the row is showing and covers that spot
        """
        return self._t > 0.0 and self._rect.collidepoint(pos)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Pass a click to the inner row while it is showing. A click elsewhere is
        still delivered to it as a miss, which is what lets an open field blur
        when the player clicks another row, but it is never reported as handled

        :param pos: click position in window pixels
        :returns: True when the inner row acted on a click inside the slot
        """
        if self._live(pos):
            return self.inner.handle_click(pos)
        if self._t > 0.0 and not self.inner.contains_control(pos):
            self.inner.handle_click(pos)
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on the inner row's control, asked only while the
        row is showing -- a collapsed row owns nothing, however recently it was
        drawn

        :param pos: position in window pixels
        :returns: True when the inner control owns that spot
        """
        return self.inner.contains_control(pos) if self._live(pos) else False

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Pass a key press to the inner row only while the setting says it
        belongs on screen. The gate follows the setting rather than the
        animation, so a row that is closing goes deaf the instant the switch
        lands instead of eating keys it would throw away

        :param event: pygame KEYDOWN event
        :returns: True when the inner row consumed the key
        """
        return self.inner.handle_key(event) if self.visible_getter() else False

    def cancel_edit(self) -> bool:
        """
        Let the inner row give up its edit, as long as this row is not already
        fully shut. A collapsed row declines, so the Esc falls through to
        leaving the sub-view

        :returns: True when the inner row cancelled an edit
        """
        return self.inner.cancel_edit() if self._t > 0.0 else False


class ActionRow(_Row):
    """
    The row that does something rather than storing something: the connection
    test in the Online section. Both the button's label and the verdict beside
    it are read from callbacks every frame, so a test in flight and the answer
    it comes back with show up without anything touching the row
    """

    def __init__(self, title: str, desc: str, button_label_getter: Callable[[], str],
                 on_press: Callable[[], None],
                 status_getter: Callable[[], tuple[str, str]]) -> None:
        """
        Build an action row wired to whatever runs the action and reports on it

        :param title: row title, the label on the left
        :param desc: smaller line under the title, empty for none
        :param button_label_getter: reads the button's label, which changes
            while the action is running
        :param on_press: runs the action, the button's whole job
        :param status_getter: reads the tone constant and the message drawn
            beside the button
        """
        super().__init__(title, desc)
        self.button_label_getter = button_label_getter
        self.on_press = on_press
        self.status_getter = status_getter
        self._button_rect = pg.Rect(0, 0, 0, 0)
        self._status_cache: tuple[tuple[int, str, str, int], pg.Surface] | None = None

    def _control_h(self, fonts: Fonts) -> int:
        """
        The button stands at one fixed height, so this control never depends on
        the fonts

        :param fonts: the faces this row draws with, which a fixed-height
            button never consults
        :returns: control height in pixels
        """
        return FIELD_H

    def _draw_control(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> int:
        """
        Draw the button at the right edge and the verdict beside it, tinted by
        the tone it came with. The row title keeps a reserved width whatever
        the verdict says, so a long line -- a protocol mismatch naming both
        versions -- is trimmed instead of crushing the title to a sliver

        :param window: surface drawn to, normally the app window
        :param rect: the row's box in window pixels
        :param fonts: the faces this row draws with
        :returns: window x where the drawn block begins, the button alone when
            there is no verdict to show
        """
        y = rect.centery - FIELD_H // 2
        label = self.button_label_getter()
        btn_w = fonts.button.size(label)[0] + 2 * BTN_PAD_X
        self._button_rect = pg.Rect(rect.right - btn_w, y, btn_w, FIELD_H)
        _draw_cut_button(window, self._button_rect, fonts.button, label)
        tone, text = self.status_getter()
        left = self._button_rect.x
        avail = self._button_rect.x - ACTION_STATUS_GAP \
            - (rect.x + ACTION_MIN_LABEL_W + CONTROL_GAP)
        if text and avail > 0:
            key = (id(fonts.value), tone, text, avail)
            if self._status_cache is None or self._status_cache[0] != key:
                shown = _elide_left(fonts.value, text, avail)
                self._status_cache = (key, render_text(fonts.value, shown,
                                                       _STATUS_TONES[tone]))
            surf = self._status_cache[1]
            left = self._button_rect.x - ACTION_STATUS_GAP - surf.get_width()
            _blit_clip(window, surf, (max(left, rect.x), rect.centery - surf.get_height() // 2),
                       avail)
        return int(left)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Run the action when the click landed on the button

        :param pos: click position in window pixels
        :returns: True when the button took the click
        """
        if self._button_rect.collidepoint(pos):
            self.on_press()
            return True
        return False

    def contains_control(self, pos: tuple[int, int]) -> bool:
        """
        Whether a position is on the button

        :param pos: position in window pixels
        :returns: True when the button owns that spot
        """
        return self._button_rect.collidepoint(pos)


class OptionsBody(ScrollHost):
    """
    The scrolling list of settings the Options sub-view hosts: one cut-corner
    card per section, the rows stacked inside it, and a scrollbar of its own.
    It knows nothing about what any setting means -- the rows arrive ready
    wired from the settings controller -- only how they are stacked, drawn and
    pointed at
    """

    def __init__(self) -> None:
        """
        Build the list empty. Sections arrive on every visit to Options, and
        the scroll view is wired to this object's own offset and to the panel
        it is last drawn in
        """
        self.sections: list[tuple[str, list[_Row]]] = []
        self.rect = pg.Rect(0, 0, 0, 0)
        self._card_rects: list[pg.Rect] = []
        self._scroll_px = 0.0
        self._content_h: float = 0
        self.scroll = ScrollView(
            lambda: self._scroll_px,
            self._store_scroll,
            lambda: (self.rect, self._content_h),
            wheel_step_px=OPTIONS_WHEEL_STEP,
        )

    def is_visible(self) -> bool:
        """
        Whether this list should be taking the mouse wheel. It only exists
        while Options is the showing sub-view, so the answer is always yes

        :returns: True in every case
        """
        return True

    def set_sections(self, sections: list[tuple[str, list[_Row]]]) -> None:
        """
        Replace the whole list with freshly built rows, which the sub-view does
        every time the player opens Options, and go back to the top so a visit
        never begins scrolled where the last one ended

        :param sections: heading and rows of each section, in display order
        """
        self.sections = sections
        self._scroll_px = 0.0
        self.scroll.cancel()

    def draw(self, window: pg.Surface, rect: pg.Rect, fonts: Fonts) -> None:
        """
        Paint the list: each section's heading and then its card of rows, all
        shifted by the scroll offset and clipped to the panel, with the
        scrollbar over the top. Drawing is also what measures the content and
        fixes the rects clicks are tested against

        :param window: surface drawn to, normally the app window
        :param rect: the panel the list lives in, in window pixels
        :param fonts: the faces the rows draw with
        """
        self.scroll.tick()
        self.rect = pg.Rect(rect)
        self._scroll_px = max(0.0, min(self._scroll_px, self._max_scroll()))
        prev = window.get_clip()
        window.set_clip(rect)
        card_w = rect.width - SCROLLBAR_RESERVE
        y = rect.y - self._scroll_px
        self._card_rects = []
        for label, rows in self.sections:
            window.blit(render_text(fonts.section, label.upper(), Colors.text_muted),
                        (rect.x, y))
            y += fonts.section.get_height() + SECTION_LABEL_GAP
            y = self._draw_card(window, rect.x, y, card_w, rows, fonts)
            y += SECTION_GAP
        self._content_h = (y - SECTION_GAP + self._scroll_px) - rect.y
        window.set_clip(prev)
        self.scroll.draw_thumb(window)

    def _draw_card(self, window: pg.Surface, x: int, y: float, card_w: int,
                   rows: list[_Row], fonts: Fonts) -> int:
        """
        Draw one section: the cut-corner card and the rows stacked inside it,
        with a hairline between neighbours. Every row is ticked before any is
        measured, so the card outline and the rows drawn into it agree on the
        same frame, and a row collapsed to nothing draws neither itself nor a
        divider above it

        :param window: surface drawn to, normally the app window
        :param x: left edge of the card in window pixels
        :param y: top of the card in window pixels, fractional while scrolling
        :param card_w: card width in pixels
        :param rows: this section's rows, in display order
        :param fonts: the faces the rows draw with
        :returns: window y just below the card
        """
        for row in rows:
            row.tick()
        heights = [row.height(fonts) for row in rows]
        card = pg.Rect(x, round(y), card_w, sum(heights))
        self._card_rects.append(card)
        bg_h = card.height
        if any(row.animating() for row in rows):
            bg_h = sum(row.full_height(fonts) for row in rows)
        bg = cut_rect_surface((card_w, bg_h), CARD_CUT, Colors.surface, border=Colors.border,
                              border_width=1, corners=("tr",))
        window.blit(bg, card.topleft, pg.Rect(0, 0, card.width, card.height))
        content_x = card.x + CARD_PAD_X
        content_w = card.width - 2 * CARD_PAD_X
        ry = y
        drawn_any = False
        for row, h in zip(rows, heights):
            if h <= 0:
                continue
            if drawn_any:
                pg.draw.line(window, pg.Color(Colors.border), (content_x, round(ry)),
                             (content_x + content_w, round(ry)))
            row.draw(window, pg.Rect(content_x, round(ry), content_w, h), fonts)
            ry += h
            drawn_any = True
        return card.bottom

    def _max_scroll(self) -> float:
        """
        How far this list can travel at all -- the content that sticks out past
        the panel. Zero means everything fits and no gesture may move anything

        :returns: the largest valid offset, in pixels
        """
        return max(0, self._content_h - self.rect.height)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Offer a click to every row until one takes it. A click landing in the
        panel is claimed either way, even when it hit no control at all, so it
        cannot fall through to whatever sits behind the list

        :param pos: click position in window pixels
        :returns: True when the click landed anywhere in the panel
        """
        if not self.rect.collidepoint(pos):
            return False
        for _, rows in self.sections:
            for row in rows:
                if row.handle_click(pos):
                    return True
        return True

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """
        Begin a scroll drag, unless the press was on a row's own control -- a
        switch, a notch strip, a chip or a field has to get the click itself
        rather than have the list swallow the whole gesture

        :param pos: press position in window pixels
        :returns: True when the press started a scroll gesture
        """
        if not self.rect.collidepoint(pos):
            return False
        for _, rows in self.sections:
            for row in rows:
                if row.contains_control(pos):
                    return False
        return super().handle_press(pos)

    def handle_key(self, event: pg.event.Event) -> bool:
        """
        Offer a key press to every row until one takes it, which is how typing
        reaches whichever field currently holds focus

        :param event: pygame KEYDOWN event
        :returns: True when a row consumed the key
        """
        for _, rows in self.sections:
            for row in rows:
                if row.handle_key(event):
                    return True
        return False

    def cancel_focused_edit(self) -> bool:
        """
        Ask each row in turn to give up a half-typed value, the first link in
        the Esc chain: cancelling an edit consumes the press, and only when
        nothing at all is being edited does Esc go on to leave the sub-view

        :returns: True when a row had an edit to cancel
        """
        for _, rows in self.sections:
            for row in rows:
                if row.cancel_edit():
                    return True
        return False
