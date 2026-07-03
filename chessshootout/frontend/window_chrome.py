import ctypes
import ctypes.util
import glob
import logging
import os

import pygame as pg

from chessshootout.paths import resource_path
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.fonts import get_font, get_mono_font

log = logging.getLogger("chess.chrome")

WINDOW_FLAGS = pg.NOFRAME | pg.RESIZABLE
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600

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
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int)]


DOUBLE_CLICK_MS = 350
FS_DRAG_EXIT_PX = 8
_SDL_WINDOW_FULLSCREEN_DESKTOP = 0x00001001


_HITTEST_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_SDLPoint), ctypes.c_void_p
)


def _iter_sdl_candidates():
    if os.name == "nt" and hasattr(ctypes, "WinDLL"):
        try:
            handle = ctypes.windll.kernel32.GetModuleHandleW("SDL2.dll")
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
    DOT_HOVER_LIGHTEN = 0.22
    DOT_GLYPH_DARKEN = 0.74
    DOT_GLYPH_INSET = 0.55

    def __init__(self, window, on_fullscreen=None):
        self.window = window
        self._w, self._h = window.get_size()
        self._dot_rects = {}
        self._sdl = None
        self._win_ptr = None
        self._sdl_window = None
        self._cb = None
        self._wordmark = None
        self._wordmark_accent = None
        self._logo_surf = None
        self._cursor = None
        self._on_fullscreen = on_fullscreen
        self._win_state = "normal"
        self._last_title_click_ms = 0
        self._fs_press_pos = None
        self._snap = None
        self._init_sdl()

    def reinit_sdl(self):
        self._sdl = None
        self._win_ptr = None
        self._sdl_window = None
        self._init_sdl()

    def _init_sdl(self):
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

    def _install_win_snap(self):
        if os.name != "nt":
            return
        try:
            hwnd = pg.display.get_wm_info().get("window")
        except Exception:
            hwnd = None
        if not hwnd:
            return
        if self._snap is not None and self._snap._hwnd == hwnd:
            self._snap.apply_styles()
            return
        if self._snap is not None:
            self._snap.shutdown()
            self._snap = None
        try:
            from chessshootout.frontend.win_snap import WindowsSnap
            snap = WindowsSnap(hwnd, lambda: self._win_state == "fullscreen")
            if snap.install():
                self._snap = snap
        except Exception:
            log.warning("window snap unavailable", exc_info=True)

    def shutdown(self):
        if self._snap is not None:
            self._snap.shutdown()
            self._snap = None

    def _resolve_owning_sdl(self, win_id):
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

    def _configure_sdl_functions(self):
        self._sdl.SDL_SetWindowHitTest.restype = ctypes.c_int
        self._sdl.SDL_SetWindowHitTest.argtypes = [
            ctypes.c_void_p, _HITTEST_CB, ctypes.c_void_p
        ]
        self._sdl.SDL_SetWindowMinimumSize.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int
        ]
        self._sdl.SDL_MinimizeWindow.argtypes = [ctypes.c_void_p]
        self._sdl.SDL_RaiseWindow.argtypes = [ctypes.c_void_p]
        self._sdl.SDL_SetWindowFullscreen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._sdl.SDL_SetWindowFullscreen.restype = ctypes.c_int

    def _resize_code(self, x, y):
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

    def _hit_test(self, win, area_ptr, data):
        x = area_ptr.contents.x
        y = area_ptr.contents.y
        if self._win_state != "normal":
            return _HITTEST_NORMAL
        code = self._resize_code(x, y)
        if code is not None:
            return code
        if y < self.HEIGHT:
            for rect in self._dot_rects.values():
                if rect.collidepoint(x, y):
                    return _HITTEST_NORMAL
            return _HITTEST_DRAGGABLE
        return _HITTEST_NORMAL

    def _over_dot(self, pos):
        return any(rect.collidepoint(pos) for rect in self._dot_rects.values())

    def _cursor_for(self, pos):
        code = self._resize_code(pos[0], pos[1])
        if code is not None:
            return _RESIZE_CURSORS[code]
        if pos[1] < self.HEIGHT and self._over_dot(pos):
            return pg.SYSTEM_CURSOR_HAND
        return pg.SYSTEM_CURSOR_ARROW

    def update_cursor(self, pos):
        self._w, self._h = self.window.get_size()
        cursor = self._cursor_for(pos)
        if cursor != self._cursor:
            try:
                pg.mouse.set_cursor(cursor)
                self._cursor = cursor
            except pg.error:
                pass

    def _layout_dots(self, w):
        self._dot_rects = {}
        cy = self.HEIGHT // 2
        x = w - self.DOT_MARGIN_RIGHT
        for key, _ in self.DOT_BUTTONS:
            rect = pg.Rect(0, 0, self.DOT_RADIUS * 2 + self.DOT_HIT_PAD, self.HEIGHT)
            rect.centerx = x - self.DOT_RADIUS
            rect.centery = cy
            self._dot_rects[key] = rect
            x -= self.DOT_RADIUS * 2 + self.DOT_GAP

    def draw(self, fps=None, ping=None, show_fps=False, show_ping=False):
        self._w, self._h = self.window.get_size()
        self._layout_dots(self._w)
        bar = pg.Rect(0, 0, self._w, self.HEIGHT)
        self.window.fill(pg.Color(Colors.titlebar_bg), bar)
        pg.draw.line(self.window, pg.Color(Colors.border),
                     (0, self.HEIGHT - 1), (self._w, self.HEIGHT - 1))
        self._draw_logo()
        self._draw_stats(fps, ping, show_fps, show_ping)
        self._draw_dots()

    def _wordmark_right_edge(self):
        tile_right = self.LOGO_MARGIN_LEFT + self.LOGO_SIZE
        if self._wordmark is None:
            return tile_right
        return (tile_right + self.WORDMARK_GAP
                + self._wordmark.get_width() + self._wordmark_accent.get_width())

    @staticmethod
    def _stat_texts(fps, ping, show_fps, show_ping):
        parts = []
        if show_fps:
            parts.append(f"{int(fps or 0)} FPS")
        if show_ping:
            parts.append(f"PING {ping} ms" if ping is not None else "PING — ms")
        return parts

    def _draw_stats(self, fps, ping, show_fps, show_ping):
        parts = self._stat_texts(fps, ping, show_fps, show_ping)
        if not parts or not self._dot_rects:
            return
        font = get_mono_font(self.STATS_FONT_PX, bold=True)
        surfs = [font.render(text, True, pg.Color(Colors.text_dim)) for text in parts]
        total_w = sum(s.get_width() for s in surfs) + self.STATS_GAP * (len(surfs) - 1)
        right = min(rect.left for rect in self._dot_rects.values()) - self.STATS_PAD
        left = right - total_w
        if left < self._wordmark_right_edge() + self.STATS_PAD:
            return
        cy = self.HEIGHT // 2
        x = left
        for s in surfs:
            self.window.blit(s, (x, cy - s.get_height() // 2))
            x += s.get_width() + self.STATS_GAP

    def _load_logo(self):
        try:
            img = pg.image.load(
                str(resource_path("assets", "icons", "brand_mark.png"))).convert_alpha()
            return pg.transform.smoothscale(img, (self.LOGO_SIZE, self.LOGO_SIZE))
        except (OSError, pg.error):
            return None

    def _draw_logo(self):
        tile = pg.Rect(self.LOGO_MARGIN_LEFT, (self.HEIGHT - self.LOGO_SIZE) // 2,
                       self.LOGO_SIZE, self.LOGO_SIZE)
        if self._logo_surf is None:
            self._logo_surf = self._load_logo()
        if self._logo_surf is not None:
            self.window.blit(self._logo_surf, tile)
        else:
            pg.draw.rect(self.window, pg.Color(Colors.accent), tile, border_radius=5)
        if self._wordmark is None:
            font = get_font(self.WORDMARK_FONT_PX, bold=True)
            self._wordmark = font.render("CHESS ", True, pg.Color(Colors.text))
            self._wordmark_accent = font.render("SHOOTOUT", True, pg.Color(Colors.accent))
        tx = tile.right + self.WORDMARK_GAP
        ty = self.HEIGHT // 2
        wm = self._wordmark
        self.window.blit(wm, (tx, ty - wm.get_height() // 2))
        self.window.blit(self._wordmark_accent,
                         (tx + wm.get_width(), ty - self._wordmark_accent.get_height() // 2))

    def _draw_dots(self):
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

    def _draw_smooth_dot(self, center, color):
        def render(surf, k):
            pg.draw.circle(surf, pg.Color(color),
                           (self.DOT_RADIUS * k, self.DOT_RADIUS * k), self.DOT_RADIUS * k)
        dot = supersample(self.DOT_RADIUS * 2, render)
        self.window.blit(dot, (center[0] - self.DOT_RADIUS, center[1] - self.DOT_RADIUS))

    def _dot_glyph(self, key, base):
        dark = base.lerp(pg.Color(0, 0, 0), self.DOT_GLYPH_DARKEN)

        def render(surf, k):
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

    def handle_click(self, pos):
        if pos[1] >= self.HEIGHT:
            return False
        for key, rect in self._dot_rects.items():
            if rect.collidepoint(pos):
                self._activate(key)
                return True
        if self._win_state != "normal":
            self._fs_press_pos = pos
            return True
        now = pg.time.get_ticks()
        if now - self._last_title_click_ms <= DOUBLE_CLICK_MS:
            self._last_title_click_ms = 0
            self.toggle_fullscreen()
        else:
            self._last_title_click_ms = now
        return True

    def handle_title_motion(self, pos):
        if self._fs_press_pos is None:
            return
        dx = pos[0] - self._fs_press_pos[0]
        dy = pos[1] - self._fs_press_pos[1]
        if dx * dx + dy * dy >= FS_DRAG_EXIT_PX * FS_DRAG_EXIT_PX:
            self._fs_press_pos = None
            self.toggle_fullscreen()

    def clear_title_press(self):
        self._fs_press_pos = None

    def _activate(self, key):
        if key == "close":
            pg.event.post(pg.event.Event(pg.QUIT))
        elif key == "min":
            self._minimize()
        elif key == "max":
            self.toggle_fullscreen()

    def _minimize(self):
        if self._win_ptr is not None:
            try:
                self._sdl.SDL_MinimizeWindow(self._win_ptr)
            except Exception:
                log.warning("minimize failed", exc_info=True)

    def apply_fullscreen(self, enable):
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

    def toggle_fullscreen(self):
        if self._on_fullscreen is None:
            return
        enable = self._win_state != "fullscreen"
        if self._on_fullscreen(enable):
            self._win_state = "fullscreen" if enable else "normal"
