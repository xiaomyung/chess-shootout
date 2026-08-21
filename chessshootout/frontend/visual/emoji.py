from pathlib import Path

import pygame as pg

from chessshootout.infra.countries import flag_emoji
from chessshootout.paths import resource_path
from chessshootout.frontend.visual.cache import new_cache, memoized_surface

_BASE = {}
_SCALED_CACHE = new_cache()

_REGIONAL_A = 0x1F1E6
_REGIONAL_Z = 0x1F1FF


def emoji_png_path(char: str) -> Path:
    """
    Point at the picture for an emoji. The game never draws emoji as text,
    because the glyphs a machine has differ wildly -- every emoji and flag it
    shows is a PNG pre-rendered into assets at packaging time, and this is what
    turns a character into its file name. A regional-indicator pair, which is
    how a flag is spelled, resolves to the country picture for its ISO code

    :param char: the emoji character, or the two-character flag pair
    :returns: path to its PNG; the file is not checked for existence here
    """
    cps = [ord(c) for c in char]
    if len(cps) == 2 and all(_REGIONAL_A <= cp <= _REGIONAL_Z for cp in cps):
        iso = "".join(chr(cp - _REGIONAL_A + ord("A")) for cp in cps).lower()
        return resource_path("assets", "emoji_png", "countries", iso + ".png")
    key = "-".join(f"{cp:x}" for cp in cps)
    return resource_path("assets", "emoji_png", "emoji", key + ".png")


def _base_surface(char: str) -> pg.Surface | None:
    """
    Read one emoji picture off disk at its native size, keeping it for the rest
    of the run. A character with no picture, or one that fails to load, is
    remembered as missing too, so a stray emoji cannot re-hit the disk frame
    after frame

    :param char: the emoji character to load, empty meaning nothing to draw
    :returns: the unscaled picture, or None when there is none to show
    """
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


def emoji_surface(char: str, size: int) -> pg.Surface | None:
    """
    Get an emoji sized to sit beside text -- the crossed swords on the
    match-found card, the surrender flag on the board, the icons on banners.
    Each size is scaled once and then shared, so asking every frame is cheap

    :param char: the emoji character to draw
    :param size: wanted height in pixels; the width follows the aspect ratio
    :returns: the shared scaled picture, or None when the emoji has no art
    """
    base = _base_surface(char)
    if base is None:
        return None
    size = max(int(size), 1)
    w, h = base.get_size()
    if h <= 0:
        return None

    def build() -> pg.Surface:
        """
        Scale the native picture down to the wanted height the first time it
        is asked for

        :returns: the picture at the requested height
        """
        scale = size / h
        return pg.transform.smoothscale(base, (max(int(w * scale), 1), size))
    return memoized_surface(_SCALED_CACHE, (char, size), build)


def blit_emoji(window: pg.Surface, char: str, center: tuple[int, int], size: int) -> bool:
    """
    Draw an emoji centred on a point and say whether it actually appeared.
    Callers use the answer to fall back to plain text or a drawn shape when
    the art is missing, so a lost PNG never leaves a blank hole

    :param window: surface to draw onto
    :param char: the emoji character to draw
    :param center: where its middle goes, in window pixels
    :param size: wanted height in pixels
    :returns: True when it was drawn, False when there was no art for it
    """
    surf = emoji_surface(char, size)
    if surf is None:
        return False
    window.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))
    return True


def flag_surface(code: str | None, size: int) -> pg.Surface | None:
    """
    Turn a player's country into the little flag drawn next to their nickname.
    This is the one place a country becomes a picture -- the player strips, the
    match-found card, the profile view, the rail and the country picker all
    come through here, so they cannot disagree about what a code looks like

    :param code: two-letter country code; unknown or blank means no flag
    :param size: wanted flag height in pixels
    :returns: the shared flag picture, or None when there is no country or art
    """
    char = flag_emoji(code)
    if not char:
        return None
    return emoji_surface(char, size)
