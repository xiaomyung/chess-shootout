import ctypes
import ctypes.util
import glob
import logging
import os

import pygame as pg

from paths import resource_path
from frontend.visual.colors import Colors
from frontend.visual.draw import supersample
from frontend.visual.fonts import get_font

log = logging.getLogger("chess.chrome")

WINDOW_FLAGS = pg.NOFRAME | pg.RESIZABLE
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 500

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

_SDL_WINDOW_MAXIMIZED = 0x00000080


class _SDLPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int)]


_HITTEST_CB = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_SDLPoint), ctypes.c_void_p
)


def _load_sdl():
    pgdir = os.path.dirname(pg.__file__)
    roots = (pgdir, os.path.join(pgdir, ".."), os.path.join(pgdir, "..", "pygame.libs"),
             os.path.join(pgdir, ".dylibs"))
    patterns = ("libSDL2-2*.so*", "libSDL2.so*", "SDL2.dll", "libSDL2*.dylib")
    for root in roots:
        for pattern in patterns:
            for path in sorted(glob.glob(os.path.join(root, pattern))):
                try:
                    return ctypes.CDLL(path)
                except OSError:
                    continue
    name = ctypes.util.find_library("SDL2") or "SDL2"
    return ctypes.CDLL(name)


class WindowChrome:
    HEIGHT = 36
    RESIZE_BORDER = 6
    DOT_RADIUS = 6
    DOT_GAP = 16
    DOT_MARGIN_RIGHT = 16
    LOGO_SIZE = 20

    def __init__(self, window):
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
        self._init_sdl()

    def _init_sdl(self):
        try:
            from pygame._sdl2 import video as sdl2video
            self._sdl = _load_sdl()
            self._sdl.SDL_GetWindowFromID.restype = ctypes.c_void_p
            self._sdl.SDL_GetWindowFromID.argtypes = [ctypes.c_uint32]
            self._sdl.SDL_GetWindowFlags.restype = ctypes.c_uint32
            self._sdl.SDL_GetWindowFlags.argtypes = [ctypes.c_void_p]
            self._sdl.SDL_SetWindowHitTest.restype = ctypes.c_int
            self._sdl.SDL_SetWindowHitTest.argtypes = [
                ctypes.c_void_p, _HITTEST_CB, ctypes.c_void_p
            ]
            self._sdl.SDL_SetWindowMinimumSize.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int
            ]
            self._sdl.SDL_MaximizeWindow.argtypes = [ctypes.c_void_p]
            self._sdl.SDL_RestoreWindow.argtypes = [ctypes.c_void_p]
            self._sdl.SDL_MinimizeWindow.argtypes = [ctypes.c_void_p]
            self._sdl_window = sdl2video.Window.from_display_module()
            self._win_ptr = self._sdl.SDL_GetWindowFromID(self._sdl_window.id)
            self._cb = _HITTEST_CB(self._hit_test)
            rc = self._sdl.SDL_SetWindowHitTest(self._win_ptr, self._cb, None)
            if rc != 0:
                log.warning("SDL_SetWindowHitTest unsupported on this driver (rc=%s)", rc)
            self._sdl.SDL_SetWindowMinimumSize(
                self._win_ptr, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
            )
        except Exception:
            log.warning("window chrome SDL hit-test unavailable", exc_info=True)

    def _hit_test(self, win, area_ptr, data):
        x = area_ptr.contents.x
        y = area_ptr.contents.y
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
        if y < self.HEIGHT:
            for rect in self._dot_rects.values():
                if rect.collidepoint(x, y):
                    return _HITTEST_NORMAL
            return _HITTEST_DRAGGABLE
        return _HITTEST_NORMAL

    def _layout_dots(self, w):
        self._dot_rects = {}
        cy = self.HEIGHT // 2
        order = ("close", "max", "min")
        x = w - self.DOT_MARGIN_RIGHT
        for key in order:
            rect = pg.Rect(0, 0, self.DOT_RADIUS * 2 + 8, self.HEIGHT)
            rect.centerx = x - self.DOT_RADIUS
            rect.centery = cy
            self._dot_rects[key] = rect
            x -= self.DOT_RADIUS * 2 + self.DOT_GAP

    def draw(self):
        self._w, self._h = self.window.get_size()
        self._layout_dots(self._w)
        bar = pg.Rect(0, 0, self._w, self.HEIGHT)
        self.window.fill(pg.Color(Colors.titlebar_bg), bar)
        pg.draw.line(self.window, pg.Color(Colors.button_border),
                     (0, self.HEIGHT - 1), (self._w, self.HEIGHT - 1))
        self._draw_logo()
        self._draw_dots()

    def _load_logo(self):
        try:
            img = pg.image.load(
                str(resource_path("assets", "icons", "brand_mark.png"))).convert_alpha()
            return pg.transform.smoothscale(img, (self.LOGO_SIZE, self.LOGO_SIZE))
        except (OSError, pg.error):
            return None

    def _draw_logo(self):
        tile = pg.Rect(12, (self.HEIGHT - self.LOGO_SIZE) // 2, self.LOGO_SIZE, self.LOGO_SIZE)
        if self._logo_surf is None:
            self._logo_surf = self._load_logo()
        if self._logo_surf is not None:
            self.window.blit(self._logo_surf, tile)
        else:
            pg.draw.rect(self.window, pg.Color(Colors.accent), tile, border_radius=5)
        if self._wordmark is None:
            font = get_font(13, bold=True)
            self._wordmark = font.render("CHESS ", True, pg.Color(Colors.white))
            self._wordmark_accent = font.render("SHOOTOUT", True, pg.Color(Colors.accent))
        tx = tile.right + 9
        ty = self.HEIGHT // 2
        wm = self._wordmark
        self.window.blit(wm, (tx, ty - wm.get_height() // 2))
        self.window.blit(self._wordmark_accent,
                         (tx + wm.get_width(), ty - self._wordmark_accent.get_height() // 2))

    def _draw_dots(self):
        colors = {
            "min": Colors.titlebar_min,
            "max": Colors.titlebar_max,
            "close": Colors.titlebar_close,
        }
        for key, rect in self._dot_rects.items():
            self._draw_smooth_dot((rect.centerx, rect.centery), colors[key])

    def _draw_smooth_dot(self, center, color):
        def render(surf, k):
            pg.draw.circle(surf, pg.Color(color),
                           (self.DOT_RADIUS * k, self.DOT_RADIUS * k), self.DOT_RADIUS * k)
        dot = supersample(self.DOT_RADIUS * 2, render)
        self.window.blit(dot, (center[0] - self.DOT_RADIUS, center[1] - self.DOT_RADIUS))

    def handle_click(self, pos):
        if pos[1] >= self.HEIGHT:
            return False
        for key, rect in self._dot_rects.items():
            if rect.collidepoint(pos):
                self._activate(key)
                return True
        return True

    def _activate(self, key):
        if key == "close":
            pg.event.post(pg.event.Event(pg.QUIT))
        elif key == "min":
            self._minimize()
        elif key == "max":
            self._toggle_maximize()

    def _is_maximized(self):
        if self._win_ptr is None:
            return False
        return bool(self._sdl.SDL_GetWindowFlags(self._win_ptr) & _SDL_WINDOW_MAXIMIZED)

    def _minimize(self):
        if self._win_ptr is not None:
            try:
                self._sdl.SDL_MinimizeWindow(self._win_ptr)
            except Exception:
                log.warning("minimize failed", exc_info=True)

    def _toggle_maximize(self):
        if self._win_ptr is None:
            return
        try:
            if self._is_maximized():
                self._sdl.SDL_RestoreWindow(self._win_ptr)
            else:
                self._sdl.SDL_MaximizeWindow(self._win_ptr)
        except Exception:
            log.warning("maximize toggle failed", exc_info=True)
