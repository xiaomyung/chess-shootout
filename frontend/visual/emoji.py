import pygame as pg

from frontend.visual.fonts import get_emoji_font

_BASE = {}


def _base_surface(char):
    if char not in _BASE:
        font = get_emoji_font()
        surf = None
        if font is not None:
            try:
                surf = font.render(char, True, (255, 255, 255))
            except (pg.error, ValueError):
                surf = None
        _BASE[char] = surf
    return _BASE[char]


def has_emoji():
    return get_emoji_font() is not None


def emoji_surface(char, size):
    base = _base_surface(char)
    if base is None:
        return None
    size = max(int(size), 1)
    w, h = base.get_size()
    if h <= 0:
        return None
    scale = size / h
    return pg.transform.smoothscale(base, (max(int(w * scale), 1), size))


def blit_emoji(window, char, center, size):
    surf = emoji_surface(char, size)
    if surf is None:
        return False
    window.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))
    return True
