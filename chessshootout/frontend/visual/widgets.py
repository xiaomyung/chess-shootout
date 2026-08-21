import hashlib
from weakref import WeakKeyDictionary

import pygame as pg

from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.cache import (
    render_text, new_cache, memoized_surface,
)
from chessshootout.frontend.visual.draw import (
    supersample, rounded_rect_surface, blit_centered, cut_rect_surface,
)


SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18
BUTTON_LABEL_PADDING_PX = 6
BUTTON_RADIUS = 8
BUTTON_CUT = 6
PILL_PAD_Y = 6
KO_WINK_MS = 520

AVATAR_CUT_FRAC = 0.22


def build_shell(w: int, h: int, winking: bool = False) -> pg.Surface:
    """
    Draw the little shotgun-shell icon this game marks knockouts with. It sits
    beside every KO count -- in the player strips, in the menu battle and in
    the saved-game rows -- and the winking version is the brighter red flash
    shown right after a fresh capture

    :param w: shell width in pixels, floored at 1
    :param h: shell height in pixels, floored at 1
    :param winking: True for the brighter post-capture flash coloring
    :returns: a freshly drawn shell surface, not cached here
    """
    def render(surf: pg.Surface, k: int) -> None:
        """
        Paint the shell onto the oversized supersampling canvas: a red body
        fading down into a brass base, then rounded off by an alpha mask

        :param surf: oversized canvas, k times the requested size
        :param k: supersampling factor, scales the corner radius
        """
        width, height = surf.get_size()
        split = int(height * 0.78)
        top = pg.Color(Colors.shell_red_hi if winking else Colors.shell_red)
        red = pg.Color(Colors.shell_red)
        brass = pg.Color(Colors.shell_brass)
        for y in range(height):
            if y < split:
                col = top.lerp(red, y / max(split - 1, 1))
            else:
                col = brass
            surf.fill(col, pg.Rect(0, y, width, 1))
        mask = pg.Surface((width, height), pg.SRCALPHA)
        pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_radius=max(int(2 * k), 1))
        surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    return supersample((max(w, 1), max(h, 1)), render)


_KO_BADGE_CACHE = new_cache()


def build_ko_badge(count: int, font: pg.font.Font, height: int,
                   winking: bool = False) -> pg.Surface:
    """
    Build the badge that reports how many pieces a player has shot down: a
    shell icon next to an amber count. The player strips and the menu battle
    redraw it every frame, so the finished surface is cached per count, size
    and wink state

    :param count: knockouts to show, the number printed before KO
    :param font: font the count is rendered in, already sized by the caller
    :param height: reference height in pixels the shell is proportioned from
    :param winking: True for the brighter amber shown just after a capture
    :returns: the cached badge surface for these arguments
    """
    def build() -> pg.Surface:
        """
        Compose the badge the first time this combination is asked for

        :returns: shell icon and count text laid out on one surface
        """
        shell_w = max(int(height * 0.16), 4)
        shell_h = max(int(height * 0.42), 7)
        gap = max(int(height * 0.12), 3)
        text = font.render(f"{count} KO", True,
                           pg.Color(Colors.amber_hi if winking else Colors.amber))
        th = text.get_height()
        h = max(shell_h, th)
        surf = pg.Surface((shell_w + gap + text.get_width(), h), pg.SRCALPHA)
        surf.blit(build_shell(shell_w, shell_h, winking), (0, (h - shell_h) // 2))
        surf.blit(text, (shell_w + gap, (h - th) // 2))
        return surf
    return memoized_surface(_KO_BADGE_CACHE, (count, height, winking), build)


def build_flat_avatar(size: int, fill: pg.Color | str) -> pg.Surface:
    """
    Make the flat square tile that stands in for a player's face everywhere
    the app shows one -- profile card, match-found cards, player strips. The
    clipped top-right and bottom-left corners are the house shape

    :param size: side length in pixels, floored at 1
    :param fill: tile color, normally the player's seeded avatar color
    :returns: the tile surface, cached by size, cut and color
    """
    size = max(int(size), 1)
    cut = max(int(size * AVATAR_CUT_FRAC), 2)
    return cut_rect_surface((size, size), cut, fill, corners=("tr", "bl"))


def draw_avatar(window: pg.Surface, rect: pg.Rect, name: str, font: pg.font.Font,
                fill: pg.Color | str, letter_color: pg.Color | str) -> None:
    """
    Paint a player's avatar straight onto the window: the colored tile with
    the first letter of their name centered on it. A player who has not set a
    name gets a question mark, so the tile is never blank

    :param window: surface drawn to, normally the app window
    :param rect: where the avatar goes; its width sets the tile size
    :param name: player name, only the first letter is shown
    :param font: font for that letter, already sized by the caller
    :param fill: tile color from the player's palette
    :param letter_color: color of the letter drawn over the tile
    """
    window.blit(build_flat_avatar(rect.width, fill), rect.topleft)
    glyph = font.render(name[:1].upper() if name else "?", True, letter_color)
    window.blit(glyph, (rect.centerx - glyph.get_width() / 2,
                        rect.centery - glyph.get_height() / 2))


def draw_pill(window: pg.Surface, text: str, x: int, cy: int, font: pg.font.Font,
              text_color: str = Colors.amber_hi,
              bg: str = Colors.mode_pill_bg, border: str = Colors.mode_pill_border) -> int:
    """
    Draw one small rounded label pill and report where it ends. That is how
    the right panel builds its game-info line: the mode pill first, then the
    time control placed right after it

    :param window: surface drawn to, normally the app window
    :param text: label shown inside the pill
    :param x: left edge in window pixels
    :param cy: vertical center in window pixels
    :param font: font for the label
    :param text_color: label color
    :param bg: pill fill color
    :param border: pill outline color
    :returns: x of the pill's right edge, where the next element starts
    """
    surf = render_text(font, text, text_color)
    pad_x = max(int(surf.get_height() * 0.6), 5)
    w = surf.get_width() + 2 * pad_x
    h = surf.get_height() + PILL_PAD_Y
    chip = rounded_rect_surface((w, h), h // 2, bg,
                                border=border, border_width=1)
    window.blit(chip, (x, round(cy - h / 2)))
    blit_centered(window, surf, (x + w / 2, cy))
    return x + w


def draw_series_chip(window: pg.Surface, center: tuple[int, int], name_a: str, name_b: str,
                     score: str, name_font: pg.font.Font, score_font: pg.font.Font,
                     pad_x: int = 12, pad_y: int = 6, gap: int = 10) -> pg.Rect:
    """
    Draw the running score between two online players -- name, score, name on
    one rounded chip. The result screen shows it after every game of a rematch
    series, which is the only place a series score exists

    :param window: surface drawn to, normally the app window
    :param center: chip center in window pixels
    :param name_a: name shown left of the score
    :param name_b: name shown right of the score
    :param score: already formatted score text, drawn between the names
    :param name_font: font for both names
    :param score_font: font for the score, usually larger than the names
    :param pad_x: horizontal padding inside the chip, in pixels
    :param pad_y: vertical padding inside the chip, in pixels
    :param gap: pixel gap between each name and the score
    :returns: the chip's rect, so the caller can stack content beneath it
    """
    a = render_text(name_font, name_a, Colors.text_dim)
    b = render_text(name_font, name_b, Colors.text_dim)
    sc = render_text(score_font, score, Colors.amber_hi)
    h = max(a.get_height(), b.get_height(), sc.get_height()) + 2 * pad_y
    w = a.get_width() + sc.get_width() + b.get_width() + 2 * gap + 2 * pad_x
    chip = rounded_rect_surface((w, h), h // 2, Colors.surface,
                                border=Colors.border, border_width=1)
    x0 = round(center[0] - w / 2)
    y0 = round(center[1] - h / 2)
    window.blit(chip, (x0, y0))
    cy = center[1]
    x = x0 + pad_x
    blit_centered(window, a, (x + a.get_width() / 2, cy))
    x += a.get_width() + gap
    blit_centered(window, sc, (x + sc.get_width() / 2, cy))
    x += sc.get_width() + gap
    blit_centered(window, b, (x + b.get_width() / 2, cy))
    return pg.Rect(x0, y0, w, h)


def wrap_words(text: str, font: pg.font.Font, max_w: int,
               max_lines: int | None = None) -> list[str]:
    """
    Break a run of text into lines that fit a given width -- the greedy word
    wrap behind confirm-dialog subtitles, news bodies and the battle speech
    bubbles. Words are never split, so one very long word can still overflow

    :param text: text to wrap; text without words comes back as a single line
    :param font: font the widths are measured with
    :param max_w: width to fit into, in pixels
    :param max_lines: give up after this many lines, or None for no limit
    :returns: the wrapped lines, in reading order
    """
    words = text.split()
    if not words:
        return [text]
    lines = []
    cur = words[0]
    for word in words[1:]:
        trial = f"{cur} {word}"
        if font.size(trial)[0] <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if max_lines is not None and len(lines) >= max_lines:
                return lines
    lines.append(cur)
    return lines


_FIT_TEXT_CACHE: WeakKeyDictionary[
    pg.Surface, dict[tuple[int, int], pg.Surface]] = WeakKeyDictionary()


def fit_text_to_rect(text_surface: pg.Surface, rect: pg.Rect,
                     padding: int = BUTTON_LABEL_PADDING_PX) -> pg.Surface:
    """
    Shrink an already rendered label until it fits inside a rect, which is how
    button and modal text survives a small window. Text that already fits is
    handed back untouched, and scaled copies are cached against the source
    surface weakly, so a per-frame render is never pinned in memory

    :param text_surface: rendered text, never modified
    :param rect: box the text has to fit inside
    :param padding: pixels kept clear on each side of that box
    :returns: the original surface, or a scaled-down copy that fits
    """
    max_w = max(rect.width - 2 * padding, 1)
    max_h = max(rect.height - 2 * padding, 1)
    tw, th = text_surface.get_size()
    if tw <= max_w and th <= max_h:
        return text_surface
    key = (max_w, max_h)
    by_size = _FIT_TEXT_CACHE.get(text_surface)
    if by_size is not None:
        fitted = by_size.get(key)
        if fitted is not None:
            return fitted
    else:
        by_size = {}
        _FIT_TEXT_CACHE[text_surface] = by_size
    scale = min(max_w / tw, max_h / th)
    new_size = (max(int(tw * scale), 1), max(int(th * scale), 1))
    fitted = pg.transform.smoothscale(text_surface, new_size)
    by_size[key] = fitted
    return fitted


def _hover_state(rect: pg.Rect) -> tuple[bool, bool]:
    """
    Read the live mouse against one widget box, the shared basis of every
    button's hover and pressed look

    :param rect: the widget's box in window pixels
    :returns: whether the cursor is over it, and whether the left button is
        held down while over it
    """
    hovered = rect.collidepoint(pg.mouse.get_pos())
    pressed = hovered and pg.mouse.get_pressed()[0]
    return hovered, pressed


def _button_bg(rect: pg.Rect, force_pressed: bool = False,
               disabled: bool = False) -> tuple[str, str]:
    """
    Pick the colors of an ordinary (non-primary) button for the state it is
    in, so pressed, hovered, selected and disabled buttons look identical
    wherever in the app they are drawn

    :param rect: the button's box, tested against the cursor
    :param force_pressed: draw the pressed look with no live press, which is
        how a selected button is shown
    :param disabled: draw the inactive look and ignore the mouse entirely
    :returns: fill color and text color, both as color strings
    """
    if disabled:
        return Colors.surface, Colors.text_muted
    hovered, pressed = _hover_state(rect)
    if force_pressed or pressed:
        return Colors.surface_active, Colors.text
    if hovered:
        return Colors.surface_hover, Colors.text
    return Colors.surface_raised, Colors.text_dim


def draw_button(window: pg.Surface, rect: pg.Rect, label: str, font: pg.font.Font,
                force_pressed: bool = False, disabled: bool = False,
                selected: bool = False, primary: bool = False, cut: bool = False) -> None:
    """
    Draw one labelled button, the single button look every modal and picker in
    the app shares. It only paints: the caller owns the rect and does its own
    hit testing, so nothing here reacts to a click

    :param window: surface drawn to, normally the app window
    :param rect: the button's box in window pixels
    :param label: button text, scaled down when it does not fit
    :param font: font for the label
    :param force_pressed: show the pressed look with no live press
    :param disabled: show the inactive look; wins over primary
    :param selected: accent the border and use the pressed fill
    :param primary: draw the accent-filled call to action instead
    :param cut: use the cut-corner house shape rather than rounded corners
    """
    if primary and not disabled:
        hovered, pressed = _hover_state(rect)
        bg = Colors.accent_press if pressed else (Colors.accent_hi if hovered else Colors.accent)
        text_color = Colors.on_accent
        border = bg
    else:
        bg, text_color = _button_bg(rect, force_pressed or selected, disabled)
        border = Colors.accent if (selected and not disabled) else Colors.border
    if cut:
        shape = cut_rect_surface(rect.size, BUTTON_CUT, bg, border=border,
                                 border_width=1, corners=("tr", "bl"))
    else:
        shape = rounded_rect_surface(rect.size, BUTTON_RADIUS, bg, border=border,
                                     border_width=1)
    window.blit(shape, rect.topleft)
    text = fit_text_to_rect(render_text(font, label, text_color), rect)
    window.blit(
        text,
        (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
    )


def draw_button_row(window: pg.Surface, rect: pg.Rect, buttons: list[tuple[str, str]],
                    font: pg.font.Font, gap: int, disabled_keys: set[str] | None = None,
                    primary_keys: set[str] | None = None,
                    cut: bool = False) -> dict[str, pg.Rect]:
    """
    Spread a row of equal-width buttons across a rect and report where each
    one landed. Every modal footer is drawn this way and then routes its
    clicks by key, so the returned rects are the modal's hit map

    :param window: surface drawn to, normally the app window
    :param rect: the strip the buttons are spread across
    :param buttons: label and key pairs, drawn left to right
    :param font: font for the labels
    :param gap: pixel gap between neighboring buttons
    :param disabled_keys: keys drawn inactive, None when every button is live
    :param primary_keys: keys drawn as the accent call to action
    :param cut: use the cut-corner house shape rather than rounded corners
    :returns: rect per button key, empty when the row was too narrow to draw
    """
    n = len(buttons)
    if n == 0 or rect.width <= gap * (n - 1):
        return {}
    btn_w = (rect.width - gap * (n - 1)) / n
    button_rects = {}
    disabled_keys = disabled_keys or set()
    primary_keys = primary_keys or set()
    for i, (label, key) in enumerate(buttons):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, rect.height)
        draw_button(window, br, label, font, disabled=key in disabled_keys,
                    primary=key in primary_keys, cut=cut)
        button_rects[key] = br
    return button_rects


_TOGGLE_CACHE = new_cache()


def draw_toggle(window: pg.Surface, rect: pg.Rect, fraction: float) -> None:
    """
    Draw the on/off switch the Options rows use. The knob position and the
    track color both follow fraction, which lets a row animate the flip
    instead of snapping, and frames are cached in hundredth steps so the
    animation redraws almost nothing

    :param window: surface drawn to, normally the app window
    :param rect: the switch's box in window pixels
    :param fraction: 0.0 fully off through 1.0 fully on, clamped
    """
    fraction = max(0.0, min(1.0, fraction))
    quant = round(fraction, 2)
    key = (rect.width, rect.height, quant)

    def build() -> pg.Surface:
        """
        Render one frame of the switch the first time this size and knob
        position are asked for

        :returns: the switch surface for that size and position
        """
        track = pg.Color(Colors.surface_active).lerp(pg.Color(Colors.accent), quant)

        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the track and the knob onto the oversized supersampling
            canvas

            :param surf: oversized canvas, k times the requested size
            :param k: supersampling factor, unused here because the geometry
                is read off the canvas itself
            """
            w, h = surf.get_size()
            pg.draw.rect(surf, track, surf.get_rect(), border_radius=h // 2)
            pad = max(int(h * 0.16), 2)
            knob_d = h - 2 * pad
            knob_x = pad + (w - 2 * pad - knob_d) * quant
            pg.draw.circle(surf, pg.Color(Colors.text),
                           (int(knob_x + knob_d / 2), h // 2), int(knob_d / 2))
        return supersample(rect.size, render, scale=6)
    window.blit(memoized_surface(_TOGGLE_CACHE, key, build), rect.topleft)


def scroll_thumb_rect(track_rect: pg.Rect, total: float, visible: float,
                      offset_fraction: float) -> pg.Rect | None:
    """
    Work out where the scrollbar thumb sits for a given scroll position. It is
    the one piece of geometry shared by drawing the thumb and hit-testing it,
    so a grab always lands exactly on what the player can see

    :param track_rect: viewport the thumb runs along, right-aligned inside it
    :param total: full content height in pixels
    :param visible: height of the window onto that content, in pixels
    :param offset_fraction: scroll position, 0.0 at the top, 1.0 at the end
    :returns: the thumb rect, or None when the content needs no scrolling
    """
    if total <= visible or track_rect.height <= 0:
        return None
    thumb_h = max(SCROLL_THUMB_MIN_HEIGHT, int(track_rect.height * visible / total))
    thumb_h = min(thumb_h, track_rect.height)
    thumb_y = track_rect.y + int((track_rect.height - thumb_h) * offset_fraction)
    thumb_x = track_rect.right - SCROLL_THUMB_RIGHT_OFFSET - SCROLL_THUMB_WIDTH
    return pg.Rect(thumb_x, thumb_y, SCROLL_THUMB_WIDTH, thumb_h)


def draw_scroll_thumb(window: pg.Surface, track_rect: pg.Rect, total: float, visible: float,
                      offset_fraction: float, last_activity_ms: int) -> None:
    """
    Draw the scrollbar thumb, but only for a couple of seconds after the last
    scroll -- an idle list shows no scrollbar at all. Every scrollable panel in
    the app reaches the screen through here

    :param window: surface drawn to, normally the app window
    :param track_rect: viewport the thumb runs along
    :param total: full content height in pixels
    :param visible: height of the window onto that content, in pixels
    :param offset_fraction: scroll position, 0.0 at the top, 1.0 at the end
    :param last_activity_ms: pygame tick count in milliseconds of the last
        scroll; anything older than the fade window draws nothing
    """
    if pg.time.get_ticks() - last_activity_ms > SCROLL_FADE_MS:
        return
    thumb = scroll_thumb_rect(track_rect, total, visible, offset_fraction)
    if thumb is None:
        return
    pg.draw.rect(window, Colors.surface_hover, thumb,
                 border_radius=SCROLL_THUMB_WIDTH // 2)


AVATAR_COLOR_POOL = (
    Colors.avatar_orange, Colors.avatar_amber, Colors.avatar_teal, Colors.avatar_green,
    Colors.avatar_blue, Colors.avatar_violet, Colors.avatar_rose, Colors.avatar_cyan,
)


def avatar_palette(seed: str) -> tuple[pg.Color, pg.Color]:
    """
    Pick an avatar's colors from the player's name, so one player keeps the
    same tile color on every screen and on the other player's client too. A
    player with no name yet falls back to the first color in the pool

    :param seed: player name the color is hashed from, may be empty
    :returns: tile fill color and the color of the letter drawn on it
    """
    if not seed:
        fill = AVATAR_COLOR_POOL[0]
    else:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        fill = AVATAR_COLOR_POOL[int(digest, 16) % len(AVATAR_COLOR_POOL)]
    return (pg.Color(fill), pg.Color(Colors.on_accent))


class AvatarBadge:
    """
    An avatar tile that keeps the surface it last drew, for panels that paint
    the same player on every frame. The cache is keyed by tile size and color,
    so a resize or a new palette rebuilds it without being told
    """

    def __init__(self) -> None:
        """
        Start with nothing cached; the first draw builds the tile
        """
        self._cache: tuple[tuple[int, str], pg.Surface] | None = None

    def reset(self) -> None:
        """
        Throw the cached tile away, which a panel does when it is laid out
        again so the next draw rebuilds at the new size
        """
        self._cache = None

    def draw(self, window: pg.Surface, rect: pg.Rect, name: str, font: pg.font.Font,
             palette: tuple[pg.Color, pg.Color]) -> None:
        """
        Paint the avatar, reusing the cached tile whenever size and color are
        unchanged, and stamp the first letter of the name over it

        :param window: surface drawn to, normally the app window
        :param rect: where the avatar goes; its width sets the tile size
        :param name: player name, only the first letter is shown
        :param font: font for that letter
        :param palette: tile fill and letter color, from avatar_palette
        """
        fill, letter_color = palette
        key = (rect.width, str(fill))
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, build_flat_avatar(rect.width, fill))
        window.blit(self._cache[1], rect.topleft)
        glyph = font.render(name[:1].upper() if name else "?", True, letter_color)
        window.blit(glyph, (rect.centerx - glyph.get_width() / 2,
                            rect.centery - glyph.get_height() / 2))


class StripAvatar:
    """
    The player-strip avatar: an AvatarBadge that also derives its palette from
    the player's name and re-seeds itself when that name changes, so the
    strips never have to track palettes of their own
    """

    def __init__(self) -> None:
        """
        Start with no cached tile and no palette; both appear on first draw
        """
        self._badge = AvatarBadge()
        self._palette: tuple[pg.Color, pg.Color] | None = None
        self._seed: str | None = None

    def reset(self) -> None:
        """
        Throw the cached tile away after a relayout. The palette survives,
        because it depends on the name rather than on the size
        """
        self._badge.reset()

    def draw(self, window: pg.Surface, rect: pg.Rect, name: str,
             font: pg.font.Font) -> None:
        """
        Paint the strip avatar for whoever is named right now, re-seeding the
        palette whenever the name has changed since the last frame

        :param window: surface drawn to, normally the app window
        :param rect: where the avatar goes; its width sets the tile size
        :param name: player name, seeds the palette and gives the letter
        :param font: font for that letter
        """
        if self._palette is None or self._seed != name:
            self._seed = name
            self._palette = avatar_palette(name)
        self._badge.draw(window, rect, name, font, self._palette)


def strip_frame_metrics(h: int) -> tuple[int, int, int, int]:
    """
    Give a player strip its shared spacing for a height, so the in-game strip
    and the review strip stay proportioned identically at every window size

    :param h: strip height in pixels
    :returns: inner padding, corner radius, avatar size and the gap that
        follows the avatar, all in pixels
    """
    pad = max(int(h * 0.16), 4)
    radius = max(int(h * 0.17), 5)
    av_size = max(h - 2 * pad, 1)
    gap = max(int(h * 0.18), 6)
    return pad, radius, av_size, gap


def draw_captured_row(window: pg.Surface,
                      icons: dict[tuple[PieceType, PieceColor], pg.Surface],
                      captured: list[PieceType], captured_color: PieceColor | None,
                      x: int, cy: int, right: int, ih: int) -> int:
    """
    Draw the little pieces one player has taken, overlapping like a fanned
    hand, and report where the row ends so the material-advantage pill can be
    placed right after it. Icons stop at the right bound instead of spilling
    out of the strip

    :param window: surface drawn to, normally the app window
    :param icons: piece images keyed by type and color, pre-scaled by the strip
    :param captured: piece types to draw, in the order the strip shows them
    :param captured_color: color of the captured pieces, None while a strip
        has no side assigned yet, in which case nothing is drawn
    :param x: left edge of the row in window pixels
    :param cy: vertical center of the row in window pixels
    :param right: right bound; drawing stops before an icon would cross it
    :param ih: inner strip height in pixels, which sets the icon size
    :returns: x of the right edge of the last icon drawn, or x if none fit
    """
    if captured_color is None:
        return x
    cursor = x
    last_right = x
    size = max(int(ih * 0.5), 6)
    for piece_type in captured:
        icon = icons.get((piece_type, captured_color))
        if icon is None:
            continue
        if icon.get_height() != size:
            icon = pg.transform.smoothscale(icon, (size, size))
        if cursor + icon.get_width() > right:
            break
        window.blit(icon, (cursor, cy - icon.get_height() / 2))
        last_right = cursor + icon.get_width()
        cursor += icon.get_width() - icon.get_width() // 3
    return last_right
