import ctypes
import ctypes.util
import glob
import logging
import os
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

import pygame as pg

from chessshootout.paths import resource_path
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.fonts import get_font, get_mono_font

if TYPE_CHECKING:
    from chessshootout.frontend.win_snap import WindowsSnap as _WindowsSnap

_DOT_CACHE = new_cache()
_DOT_GLYPH_CACHE = new_cache()

log = logging.getLogger("chess.chrome")

WINDOW_FLAGS = pg.NOFRAME | pg.RESIZABLE
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600
WINDOW_TITLE = "Chess Shootout"

_HITTEST_NORMAL = 0
_HITTEST_DRAGGABLE = 1
_HITTEST_RESIZE_TOPLEFT = 2
_HITTEST_RESIZE_TOP = 3
_HITTEST_RESIZE_TOPRIGHT = 4
_HITTEST_RESIZE_RIGHT = 5
_HITTEST_RESIZE_BOTTOMRIGHT = 6
_HITTEST_RESIZE_BOTTOM = 7
_HITTEST_RESIZE_BOTTOMLEFT = 8
_HITTEST_RESIZE_LEFT = 9

_RESIZE_CURSORS = {
    _HITTEST_RESIZE_TOPLEFT: pg.SYSTEM_CURSOR_SIZENWSE,
    _HITTEST_RESIZE_BOTTOMRIGHT: pg.SYSTEM_CURSOR_SIZENWSE,
    _HITTEST_RESIZE_TOPRIGHT: pg.SYSTEM_CURSOR_SIZENESW,
    _HITTEST_RESIZE_BOTTOMLEFT: pg.SYSTEM_CURSOR_SIZENESW,
    _HITTEST_RESIZE_TOP: pg.SYSTEM_CURSOR_SIZENS,
    _HITTEST_RESIZE_BOTTOM: pg.SYSTEM_CURSOR_SIZENS,
    _HITTEST_RESIZE_LEFT: pg.SYSTEM_CURSOR_SIZEWE,
    _HITTEST_RESIZE_RIGHT: pg.SYSTEM_CURSOR_SIZEWE,
}


class _SDLPoint(ctypes.Structure):
    """
    The point SDL hands to the hit-test callback, in window pixels. It mirrors
    SDL_Point field for field so ctypes can read it straight out of the pointer
    the callback is given
    """

    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int)]


_FS_DRAG_EXIT_PX = 8
_SDL_WINDOW_FULLSCREEN_DESKTOP = 0x00001001


_HITTEST_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_SDLPoint), ctypes.c_void_p
)


def _iter_sdl_candidates() -> Iterator[ctypes.CDLL]:
    """
    Offer up every copy of the SDL2 library that can be found and loaded. More
    than one can be present at a time -- the one shipped inside pygame, one
    beside it, one installed on the system -- and only the copy that actually
    owns the game window can be asked to make the borderless frame draggable,
    so they are handed over in turn for the caller to try

    :returns: each SDL2 library that loaded, the likeliest candidates first
    """
    if os.name == "nt" and hasattr(ctypes, "WinDLL"):
        try:
            handle = ctypes.windll.kernel32.GetModuleHandleW(  # type: ignore[attr-defined]
                "SDL2.dll")
            if handle:
                yield ctypes.WinDLL("SDL2.dll", handle=handle)
        except (OSError, AttributeError):
            pass
    pgdir = os.path.dirname(pg.__file__)
    roots = (pgdir, os.path.join(pgdir, ".."), os.path.join(pgdir, "..", "pygame.libs"),
             os.path.join(pgdir, ".dylibs"))
    patterns = ("libSDL2-2*.so*", "libSDL2.so*", "SDL2.dll", "libSDL2*.dylib")
    for root in roots:
        for pattern in patterns:
            for path in sorted(glob.glob(os.path.join(root, pattern))):
                try:
                    yield ctypes.CDLL(path)
                except OSError:
                    continue
    for name in (ctypes.util.find_library("SDL2"), "libSDL2-2.0.so.0", "SDL2"):
        if not name:
            continue
        try:
            yield ctypes.CDLL(name)
        except OSError:
            continue


class WindowChrome:
    """
    The game's own title bar, drawn by the game instead of by the operating
    system: the brand mark and wordmark, the optional performance readouts, and
    the three coloured dots that close, maximise and minimise. It also teaches
    the frameless window how to behave like a window -- dragging by the bar,
    resizing from any edge, fullscreen, and Windows snap through the helper it
    installs -- and it owns the window title the whole app is known by
    """

    DOT_BUTTONS = (("close", Colors.loss), ("max", Colors.win), ("min", Colors.amber))
    HEIGHT = 36
    RESIZE_BORDER = 6
    DOT_RADIUS = 6
    DOT_GAP = 16
    DOT_MARGIN_RIGHT = 16
    LOGO_SIZE = 20
    DOT_HIT_PAD = 8
    LOGO_MARGIN_LEFT = 12
    WORDMARK_GAP = 9
    WORDMARK_FONT_PX = 13
    STATS_FONT_PX = 11
    STATS_GAP = 14
    STATS_PAD = 16
    STATS_SEP_HEIGHT_FRAC = 0.6
    DOT_HOVER_LIGHTEN = 0.22
    DOT_GLYPH_DARKEN = 0.74
    DOT_GLYPH_INSET = 0.55

    def __init__(self, window: pg.Surface,
                 on_fullscreen: Callable[[bool], bool] | None = None) -> None:
        """
        Take the window's frame over: remember the surface to draw the bar on,
        then go and find the SDL library that owns the window, which is what
        makes the bar draggable and the edges resizable. Everything the bar
        draws is built on first use rather than here

        :param window: the surface the whole app draws on
        :param on_fullscreen: asked to switch fullscreen on or off and answers
            whether it worked; None leaves the maximise dot inert
        """
        self.window = window
        self._w, self._h = window.get_size()
        self._dot_rects: dict[str, pg.Rect] = {}
        self._sdl: Any = None
        self._win_ptr: int | None = None
        self._sdl_window: Any = None
        self._cb: Any = None
        self._wordmark: pg.Surface | None = None
        self._stats_font: pg.font.Font | None = None
        self._wordmark_accent: pg.Surface | None = None
        self._logo_surf: pg.Surface | None = None
        self._cursor: int | None = None
        self._on_fullscreen = on_fullscreen
        self._win_state = "normal"
        self._fs_press_pos: tuple[int, int] | None = None
        self._snap: "_WindowsSnap | None" = None
        self._snap_hwnd: int | None = None
        self._init_sdl()

    def reinit_sdl(self) -> None:
        """
        Hook the window handling back up after the drawing surface has been
        replaced, which every resize and every fullscreen change does. Without
        this the bar would go on drawing but the window would quietly stop
        being draggable and resizable. Nothing the bar has rendered is thrown
        away: replacing the surface is a set_mode, not a pygame teardown, so
        the brand mark, the wordmark halves and the readout font all stay
        valid -- and on Windows this runs once per frame of an edge drag, where
        dropping them would reload a PNG off disk and rebuild a font every
        single frame
        """
        self._sdl = None
        self._win_ptr = None
        self._init_sdl()

    def _init_sdl(self) -> None:
        """
        Find the SDL library that owns the window, register the hit test that
        tells it which parts of our hand-drawn bar are draggable or resizable,
        and set the smallest size the interface may be squeezed to. Every step
        is optional: where a platform will not have it the bar still draws and
        the window merely loses those tricks. pygame's window wrapper is only
        read for the window's id, but it is kept all the same and never
        cleared: SDL stores a borrowed pointer back to it, which pygame reads
        again whenever it turns a window event into a pygame one, so letting it
        be collected leaves a dangling pointer that takes the process down on
        the next resize
        """
        try:
            from pygame._sdl2 import video as sdl2video
            self._sdl_window = sdl2video.Window.from_display_module()
            self._resolve_owning_sdl(self._sdl_window.id)
            if self._sdl is None or not self._win_ptr:
                log.error("window chrome disabled: no SDL2 instance owns the window")
                self._sdl = None
                self._win_ptr = None
                return
            self._cb = _HITTEST_CB(self._hit_test)
            rc = self._sdl.SDL_SetWindowHitTest(self._win_ptr, self._cb, None)
            if rc != 0:
                log.warning("SDL_SetWindowHitTest unsupported on this driver (rc=%s)", rc)
            self._sdl.SDL_SetWindowMinimumSize(
                self._win_ptr, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
            )
        except Exception:
            log.warning("window chrome SDL hit-test unavailable", exc_info=True)
            self._sdl = None
            self._win_ptr = None
        self._install_win_snap()

    def _install_win_snap(self) -> None:
        """
        Install the Windows-only helper that gives the frameless window Aero
        Snap and a maximise that respects the taskbar. It does nothing at all
        on other platforms, where the window manager handles both itself, and
        re-installing for the same window only refreshes its styles
        """
        if os.name != "nt":
            return
        try:
            hwnd = pg.display.get_wm_info().get("window")
        except Exception:
            hwnd = None
        if not hwnd:
            return
        if self._snap is not None and self._snap_hwnd == hwnd:
            self._snap.apply_styles()
            return
        if self._snap is not None:
            self._snap.shutdown()
            self._snap = None
            self._snap_hwnd = None
        try:
            from chessshootout.frontend.win_snap import WindowsSnap
            snap = WindowsSnap(hwnd, lambda: self._win_state == "fullscreen")
            if snap.install():
                self._snap = snap
                self._snap_hwnd = hwnd
        except Exception:
            log.warning("window snap unavailable", exc_info=True)

    def shutdown(self) -> None:
        """
        Let go of the Windows helper as the game closes, handing the window its
        own message handling back before the process ends
        """
        if self._snap is not None:
            self._snap.shutdown()
            self._snap = None
            self._snap_hwnd = None

    def is_fullscreen(self) -> bool:
        """
        Whether the game is currently filling the screen, which the shell asks
        before chasing window sizes that only matter in a window

        :returns: True while fullscreen
        """
        return self._win_state == "fullscreen"

    def client_size(self) -> tuple[int, int] | None:
        """
        The size the window really is according to Windows, which can differ
        from the size the game asked for while an edge is being dragged. There
        is nothing to ask anywhere else, so it answers with nothing

        :returns: width and height in pixels, or None when it cannot be known
        """
        if self._snap is None:
            return None
        return self._snap.client_size()

    def _is_maximized(self) -> bool:
        """
        Whether Windows has the window maximised, which the hit test needs so
        the edges of a maximised window are not offered as resize handles

        :returns: True while maximised, and always False off Windows
        """
        return self._snap is not None and self._snap.maximized

    def _resolve_owning_sdl(self, win_id: int) -> None:
        """
        Work out which of the loaded SDL2 libraries owns this window by asking
        each in turn to look the window up by its id -- only the right one
        hands a pointer back. The winner is kept, along with that window
        pointer, since every later SDL call needs both

        :param win_id: SDL's own id for the game window
        """
        for sdl in _iter_sdl_candidates():
            try:
                sdl.SDL_GetWindowFromID.restype = ctypes.c_void_p
                sdl.SDL_GetWindowFromID.argtypes = [ctypes.c_uint32]
                win_ptr = sdl.SDL_GetWindowFromID(win_id)
            except (OSError, AttributeError):
                continue
            if win_ptr:
                self._sdl = sdl
                self._win_ptr = win_ptr
                self._configure_sdl_functions()
                return

    def _configure_sdl_functions(self) -> None:
        """
        Declare the argument and result types of every SDL call this module
        makes, which ctypes needs before any of them can be trusted with
        pointers on a 64-bit build
        """
        self._sdl.SDL_SetWindowHitTest.restype = ctypes.c_int
        self._sdl.SDL_SetWindowHitTest.argtypes = [
            ctypes.c_void_p, _HITTEST_CB, ctypes.c_void_p
        ]
        self._sdl.SDL_SetWindowMinimumSize.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int
        ]
        self._sdl.SDL_MinimizeWindow.argtypes = [ctypes.c_void_p]
        self._sdl.SDL_MaximizeWindow.argtypes = [ctypes.c_void_p]
        self._sdl.SDL_RaiseWindow.argtypes = [ctypes.c_void_p]
        self._sdl.SDL_SetWindowFullscreen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._sdl.SDL_SetWindowFullscreen.restype = ctypes.c_int

    def _resize_code(self, x: int, y: int) -> int | None:
        """
        Decide which resize handle a point falls in, if any: the four edges and
        four corners of the window, each a band a few pixels wide. Corners are
        tested first, so dragging one resizes in both directions at once

        :param x: position across the window, in pixels from its left edge
        :param y: position down the window, in pixels from its top edge
        :returns: the SDL hit-test code for that handle, or None away from
            every edge
        """
        w, h = self._w, self._h
        b = self.RESIZE_BORDER
        left, right = x < b, x >= w - b
        top, bottom = y < b, y >= h - b
        if top and left:
            return _HITTEST_RESIZE_TOPLEFT
        if top and right:
            return _HITTEST_RESIZE_TOPRIGHT
        if bottom and left:
            return _HITTEST_RESIZE_BOTTOMLEFT
        if bottom and right:
            return _HITTEST_RESIZE_BOTTOMRIGHT
        if top:
            return _HITTEST_RESIZE_TOP
        if bottom:
            return _HITTEST_RESIZE_BOTTOM
        if left:
            return _HITTEST_RESIZE_LEFT
        if right:
            return _HITTEST_RESIZE_RIGHT
        return None

    def _hit_test(self, win: int | None, area_ptr: Any, data: int | None) -> int:
        """
        Tell SDL what the mouse is over, which is the whole reason a window
        with no system frame still behaves like one: the edges resize, the bar
        drags the window about, and the three dots stay ordinary buttons so a
        click reaches them instead of starting a drag. SDL calls this itself,
        on its own thread of control, for presses anywhere in the window

        :param win: SDL's handle for the window, which this does not need
        :param area_ptr: pointer to the point being asked about, in window
            pixels
        :param data: the user pointer registered with the callback, unused
        :returns: the SDL hit-test code describing that point
        """
        x = area_ptr.contents.x
        y = area_ptr.contents.y
        if self._win_state != "normal":
            return _HITTEST_NORMAL
        if not self._is_maximized():
            code = self._resize_code(x, y)
            if code is not None:
                return code
        if y < self.HEIGHT:
            for rect in self._dot_rects.values():
                if rect.collidepoint(x, y):
                    return _HITTEST_NORMAL
            return _HITTEST_DRAGGABLE
        return _HITTEST_NORMAL

    def _over_dot(self, pos: tuple[int, int]) -> bool:
        """
        Whether a point lands on one of the three window dots, each of which
        carries a hit area larger than the dot itself so it stays easy to hit

        :param pos: mouse position in window pixels
        :returns: True when a dot is under it
        """
        return any(rect.collidepoint(pos) for rect in self._dot_rects.values())

    def _cursor_for(self, pos: tuple[int, int]) -> int:
        """
        Pick the mouse pointer for wherever the mouse is: the matching resize
        arrow over an edge or corner, a hand over the window dots, and the
        ordinary arrow everywhere else

        :param pos: mouse position in window pixels
        :returns: the pygame system-cursor id to show
        """
        code = self._resize_code(pos[0], pos[1])
        if code is not None:
            return _RESIZE_CURSORS[code]
        if pos[1] < self.HEIGHT and self._over_dot(pos):
            return pg.SYSTEM_CURSOR_HAND
        return pg.SYSTEM_CURSOR_ARROW

    def update_cursor(self, pos: tuple[int, int]) -> None:
        """
        Keep the mouse pointer matching what it is hovering over, called by the
        router on every mouse move. The cursor is only actually set when it
        changes, since setting it over and over is wasted work

        :param pos: mouse position in window pixels
        """
        self._w, self._h = self.window.get_size()
        cursor = self._cursor_for(pos)
        if cursor != self._cursor:
            try:
                pg.mouse.set_cursor(cursor)
                self._cursor = cursor
            except pg.error:
                pass

    def _layout_dots(self, w: int) -> None:
        """
        Place the close, maximise and minimise dots along the right end of the
        bar, in that order right to left. Redone on every draw, so the dots
        follow the window as it is resized

        :param w: current window width in pixels
        """
        self._dot_rects = {}
        cy = self.HEIGHT // 2
        x = w - self.DOT_MARGIN_RIGHT
        for key, _ in self.DOT_BUTTONS:
            rect = pg.Rect(0, 0, self.DOT_RADIUS * 2 + self.DOT_HIT_PAD, self.HEIGHT)
            rect.centerx = x - self.DOT_RADIUS
            rect.centery = cy
            self._dot_rects[key] = rect
            x -= self.DOT_RADIUS * 2 + self.DOT_GAP

    def draw(self, stats: list[str] | None = None) -> None:
        """
        Draw the title bar over the top of the finished frame, which happens
        every frame on every screen: the bar and its seam, the brand mark and
        wordmark, any performance readouts, and the three window dots

        :param stats: readouts to show along the bar, each already formatted,
            or None when they are all switched off
        """
        self._w, self._h = self.window.get_size()
        self._layout_dots(self._w)
        bar = pg.Rect(0, 0, self._w, self.HEIGHT)
        self.window.fill(pg.Color(Colors.titlebar_bg), bar)
        pg.draw.line(self.window, pg.Color(Colors.border),
                     (0, self.HEIGHT - 1), (self._w, self.HEIGHT - 1))
        self._draw_logo()
        self._draw_stats(stats or [])
        self._draw_dots()

    def _wordmark_right_edge(self) -> int:
        """
        Where the brand mark and wordmark stop, which is the line the
        performance readouts are not allowed to cross. Until both halves of the
        wordmark have been rendered -- before the first frame, and again after
        a reinit threw them away -- only the mark itself can be measured

        :returns: x position in window pixels of the right edge of the branding
        """
        tile_right = self.LOGO_MARGIN_LEFT + self.LOGO_SIZE
        if self._wordmark is None or self._wordmark_accent is None:
            return tile_right
        return (tile_right + self.WORDMARK_GAP + self._wordmark.get_width()
                + self._wordmark_accent.get_width())

    def _draw_stats(self, parts: list[str]) -> None:
        """
        Draw the performance readouts between the wordmark and the window dots,
        divided by hairlines. When the window is too narrow to fit them without
        running into the branding they are dropped for that frame rather than
        drawn over it

        :param parts: readouts in order, each already padded to a fixed width
        """
        if not parts or not self._dot_rects:
            return
        if self._stats_font is None:
            self._stats_font = get_mono_font(self.STATS_FONT_PX, bold=True)
        surfs = [self._stats_font.render(text, True, pg.Color(Colors.text_dim))
                 for text in parts]
        total_w = sum(s.get_width() for s in surfs) + self.STATS_GAP * (len(surfs) - 1)
        right = min(rect.left for rect in self._dot_rects.values()) - self.STATS_PAD
        left = right - total_w
        if left < self._wordmark_right_edge() + self.STATS_PAD:
            return
        cy = self.HEIGHT // 2
        sep_half = int(self.HEIGHT * self.STATS_SEP_HEIGHT_FRAC) // 2
        sep_color = pg.Color(Colors.border)
        x = left
        for i, (part, s) in enumerate(zip(parts, surfs)):
            self.window.blit(s, (x, cy - s.get_height() // 2))
            visible_right = x + self._stats_font.size(part.rstrip())[0]
            next_x = x + s.get_width() + self.STATS_GAP
            if i < len(surfs) - 1:
                sep_x = (visible_right + next_x) // 2
                pg.draw.line(self.window, sep_color, (sep_x, cy - sep_half),
                             (sep_x, cy + sep_half))
            x = next_x

    def _load_logo(self) -> pg.Surface | None:
        """
        Read the brand mark off disk and size it for the bar, done once on the
        first frame that draws it. A missing or unreadable file is not fatal --
        the bar falls back to a plain coloured tile

        :returns: the sized brand mark, or None when it could not be loaded
        """
        try:
            img = pg.image.load(
                str(resource_path("assets", "icons", "brand_mark.png"))).convert_alpha()
            return pg.transform.smoothscale(img, (self.LOGO_SIZE, self.LOGO_SIZE))
        except (OSError, pg.error):
            return None

    def _draw_logo(self) -> None:
        """
        Draw the brand mark and the CHESS SHOOTOUT wordmark at the left end of
        the bar, the game's name in front of the player at all times. Both the
        image and the two rendered words are built on the first frame and
        reused from then on; the two wordmark halves are only ever built
        together, so either one missing rebuilds the pair
        """
        tile = pg.Rect(self.LOGO_MARGIN_LEFT, (self.HEIGHT - self.LOGO_SIZE) // 2,
                       self.LOGO_SIZE, self.LOGO_SIZE)
        if self._logo_surf is None:
            self._logo_surf = self._load_logo()
        if self._logo_surf is not None:
            self.window.blit(self._logo_surf, tile)
        else:
            pg.draw.rect(self.window, pg.Color(Colors.accent), tile, border_radius=5)
        if self._wordmark is None or self._wordmark_accent is None:
            font = get_font(self.WORDMARK_FONT_PX, bold=True)
            self._wordmark = font.render("CHESS ", True, pg.Color(Colors.text))
            self._wordmark_accent = font.render("SHOOTOUT", True, pg.Color(Colors.accent))
        tx = tile.right + self.WORDMARK_GAP
        ty = self.HEIGHT // 2
        wm = self._wordmark
        accent = self._wordmark_accent
        self.window.blit(wm, (tx, ty - wm.get_height() // 2))
        self.window.blit(accent,
                         (tx + wm.get_width(), ty - accent.get_height() // 2))

    def _draw_dots(self) -> None:
        """
        Draw the three window dots, lightening whichever one the mouse is over
        and showing its symbol -- a line, a box or a cross -- only while it is
        hovered, so the bar reads as clean the rest of the time
        """
        colors = dict(self.DOT_BUTTONS)
        mouse = pg.mouse.get_pos()
        for key, rect in self._dot_rects.items():
            base = pg.Color(colors[key])
            hovered = rect.collidepoint(mouse)
            col = base.lerp(pg.Color(255, 255, 255), self.DOT_HOVER_LIGHTEN) if hovered else base
            self._draw_smooth_dot((rect.centerx, rect.centery), col)
            if hovered:
                self.window.blit(
                    self._dot_glyph(key, base),
                    (rect.centerx - self.DOT_RADIUS, rect.centery - self.DOT_RADIUS))

    def _draw_smooth_dot(self, center: tuple[int, int], color: pg.Color) -> None:
        """
        Draw one window dot with a smooth edge. The circle is drawn oversized
        and shrunk down once per colour and then kept, since that is the
        expensive part and only a handful of colours ever appear

        :param center: middle of the dot in window pixels
        :param color: the dot's fill, which also keys its cache entry
        """
        def build() -> pg.Surface:
            """
            Draw the dot in this colour, the miss path of the cache around it

            :returns: the finished dot with a smooth edge
            """
            def render(surf: pg.Surface, k: int) -> None:
                """
                Draw the circle onto the oversized canvas, scaling its radius
                by however much larger that canvas is

                :param surf: the oversized canvas to draw on
                :param k: how many times oversized the canvas is
                """
                pg.draw.circle(surf, pg.Color(color),
                               (self.DOT_RADIUS * k, self.DOT_RADIUS * k), self.DOT_RADIUS * k)
            return supersample(self.DOT_RADIUS * 2, render)
        dot = memoized_surface(_DOT_CACHE, str(color), build)
        self.window.blit(dot, (center[0] - self.DOT_RADIUS, center[1] - self.DOT_RADIUS))

    def _dot_glyph(self, key: str, base: pg.Color) -> pg.Surface:
        """
        The symbol shown inside a window dot while the mouse is over it: a line
        for minimise, a box for maximise and a cross for close. Each is drawn
        once and kept, in a darkened shade of that dot's own colour

        :param key: which dot it belongs to -- close, max or min
        :param base: that dot's colour, darkened to draw the symbol in
        :returns: the symbol on a transparent square the size of the dot
        """
        def build() -> pg.Surface:
            """
            Draw this dot's symbol, the miss path of the cache around it

            :returns: the finished symbol with smooth edges
            """
            dark = base.lerp(pg.Color(0, 0, 0), self.DOT_GLYPH_DARKEN)

            def render(surf: pg.Surface, k: int) -> None:
                """
                Draw the symbol onto the oversized canvas, scaling its size and
                its line width by however much larger that canvas is

                :param surf: the oversized canvas to draw on
                :param k: how many times oversized the canvas is
                """
                d = self.DOT_RADIUS * 2 * k
                c = d / 2
                g = self.DOT_RADIUS * k * self.DOT_GLYPH_INSET
                lw = max(int(1.5 * k), 2)
                if key == "min":
                    pg.draw.line(surf, dark, (c - g, c), (c + g, c), lw)
                elif key == "max":
                    box = pg.Rect(0, 0, round(2 * g), round(2 * g))
                    box.center = (round(c), round(c))
                    pg.draw.rect(surf, dark, box, lw)
                else:
                    pg.draw.line(surf, dark, (c - g, c - g), (c + g, c + g), lw)
                    pg.draw.line(surf, dark, (c - g, c + g), (c + g, c - g), lw)
            return supersample(self.DOT_RADIUS * 2, render, scale=8)
        return memoized_surface(_DOT_GLYPH_CACHE, key, build)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """
        Act on a press in the title bar: a dot does what it says, and a press
        anywhere else along the bar while the game is fullscreen arms the drag
        that leaves fullscreen. A press below the bar belongs to the screen
        underneath and is left alone

        :param pos: press position in window pixels
        :returns: True when the bar took the press
        """
        if pos[1] >= self.HEIGHT:
            return False
        for key, rect in self._dot_rects.items():
            if rect.collidepoint(pos):
                self._activate(key)
                return True
        if self._win_state != "normal":
            self._fs_press_pos = pos
        return True

    def handle_title_motion(self, pos: tuple[int, int]) -> None:
        """
        Leave fullscreen when the title bar is dragged, the gesture every other
        window has: press on the bar and pull away. Small movements are ignored
        so a slightly shaky click cannot drop the game out of fullscreen

        :param pos: current mouse position in window pixels
        """
        if self._fs_press_pos is None:
            return
        dx = pos[0] - self._fs_press_pos[0]
        dy = pos[1] - self._fs_press_pos[1]
        if dx * dx + dy * dy >= _FS_DRAG_EXIT_PX * _FS_DRAG_EXIT_PX:
            self._fs_press_pos = None
            self.toggle_fullscreen()

    def clear_title_press(self) -> None:
        """
        Forget a press on the bar that was released without ever becoming a
        drag, so the next press starts the gesture over from nothing
        """
        self._fs_press_pos = None

    def _activate(self, key: str) -> None:
        """
        Do what a window dot says. Close goes through the ordinary quit path
        rather than killing the window, so the game still gets to save and shut
        down properly on the way out

        :param key: which dot was pressed -- close, min or max
        """
        if key == "close":
            pg.event.post(pg.event.Event(pg.QUIT))
        elif key == "min":
            self._minimize()
        elif key == "max":
            self.toggle_fullscreen()

    def _minimize(self) -> None:
        """
        Send the window down to the taskbar. Where SDL could not be reached it
        quietly does nothing, which is the rule the whole bar follows
        """
        if self._win_ptr is not None:
            try:
                self._sdl.SDL_MinimizeWindow(self._win_ptr)
            except Exception:
                log.warning("minimize failed", exc_info=True)

    def maximize(self) -> bool:
        """
        Ask the system to maximise the window, used at launch when the player
        has chosen to start that way. Issuing the request is as far as this
        can go: on Wayland the maximised flag is only set once the compositor
        answers, some frames later, so reading it back here would call a
        perfectly good maximise a failure. The caller is told whether the
        request went out, since it has to fall back to simply growing the
        surface to the desktop when it could not

        :returns: True when SDL took the maximise request
        """
        if self._win_ptr is None:
            return False
        try:
            self._sdl.SDL_MaximizeWindow(self._win_ptr)
        except Exception:
            log.warning("maximize failed", exc_info=True)
            return False
        return True

    def apply_fullscreen(self, enable: bool) -> bool:
        """
        Actually put the window into or take it out of fullscreen, using the
        borderless kind that keeps the desktop's own resolution rather than
        changing modes. Coming back to a window also restores the Windows snap
        styles, which going fullscreen strips off

        :param enable: True to go fullscreen, False to return to a window
        :returns: True when the switch was made
        """
        if self._win_ptr is None:
            return False
        try:
            flag = _SDL_WINDOW_FULLSCREEN_DESKTOP if enable else 0
            self._sdl.SDL_SetWindowFullscreen(self._win_ptr, flag)
            self._sdl.SDL_RaiseWindow(self._win_ptr)
        except Exception:
            log.warning("native fullscreen failed", exc_info=True)
            return False
        if not enable and self._snap is not None:
            self._snap.apply_styles()
        return True

    def toggle_fullscreen(self) -> None:
        """
        Flip between fullscreen and windowed, behind the green dot, the F11 key
        and a drag on the title bar. The shell does the work and reports back,
        so the bar only records the new state once the change really happened
        """
        if self._on_fullscreen is None:
            return
        enable = self._win_state != "fullscreen"
        if self._on_fullscreen(enable):
            self._win_state = "fullscreen" if enable else "normal"
