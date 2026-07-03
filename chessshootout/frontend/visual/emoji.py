import pygame as pg

from chessshootout.paths import resource_path
from chessshootout.frontend.visual.cache import new_cache, memoized_surface

_BASE = {}
_SCALED = new_cache()

_REGIONAL_A = 0x1F1E6
_REGIONAL_Z = 0x1F1FF


def emoji_png_path(char):
    cps = [ord(c) for c in char]
    if len(cps) == 2 and all(_REGIONAL_A <= cp <= _REGIONAL_Z for cp in cps):
        iso = "".join(chr(cp - _REGIONAL_A + ord("A")) for cp in cps).lower()
        return resource_path("assets", "emoji_png", "countries", iso + ".png")
    key = "-".join(f"{cp:x}" for cp in cps)
    return resource_path("assets", "emoji_png", "emoji", key + ".png")


def _base_surface(char):
    if char not in _BASE:
        surf = None
        if char:
            try:
                surf = pg.image.load(str(emoji_png_path(char)))
                try:
                    surf = surf.convert_alpha()
                except pg.error:
                    pass
            except (pg.error, FileNotFoundError, OSError):
                surf = None
        _BASE[char] = surf
    return _BASE[char]


def emoji_surface(char, size):
    base = _base_surface(char)
    if base is None:
        return None
    size = max(int(size), 1)
    w, h = base.get_size()
    if h <= 0:
        return None

    def build():
        scale = size / h
        return pg.transform.smoothscale(base, (max(int(w * scale), 1), size))
    return memoized_surface(_SCALED, (char, size), build)


def blit_emoji(window, char, center, size):
    surf = emoji_surface(char, size)
    if surf is None:
        return False
    window.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))
    return True
