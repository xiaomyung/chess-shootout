from collections.abc import Callable
from typing import Any, cast

import pygame as pg

from chessshootout.paths import resource_path

DISPLAY = "display"
SANS = "sans"
MONO = "mono"

_FONT_FILES = {
    (DISPLAY, False): "Anton-Regular.ttf",
    (DISPLAY, True): "Anton-Regular.ttf",
    (SANS, False): "SpaceGrotesk-Regular.ttf",
    (SANS, True): "SpaceGrotesk-Bold.ttf",
    (MONO, False): "SpaceMono-Regular.ttf",
    (MONO, True): "SpaceMono-Bold.ttf",
}

_SYS_FALLBACK = {DISPLAY: "Arial", SANS: "Arial", MONO: "monospace"}

_FONT_PATHS = {
    key: str(resource_path("assets", "fonts", name)) for key, name in _FONT_FILES.items()
}


def get_font(size: int, bold: bool = False, mono: bool = False,
             family: str | None = None) -> pg.font.Font:
    """
    Load one of the game's three bundled typefaces at a pixel size. Every piece
    of text in the game comes from here rather than a system font, so a
    packaged build looks the same as a source run. A missing font file falls
    back to a system face instead of failing to draw. This returns a FRESH Font
    object on every call by design -- Font objects must never be cached across
    a pygame quit and reinit, which segfaults, and that is why nothing in this
    module is memoised; cache the rendered text surface instead

    :param size: height in pixels, forced to at least 1
    :param bold: use the bold cut where the family has one
    :param mono: pick the monospace family; ignored when family is given
    :param family: DISPLAY, SANS or MONO to choose explicitly, None to let the
        mono flag decide between MONO and SANS
    :returns: a newly loaded font, or a system fallback if the file is missing
    """
    size = max(int(size), 1)
    if family is None:
        family = MONO if mono else SANS
    key = (family, bool(bold))
    try:
        return pg.font.Font(_FONT_PATHS[key], size)
    except (OSError, pg.error):
        return pg.font.SysFont(_SYS_FALLBACK[family], size, bold=bold)


def get_display_font(size: int, bold: bool = False) -> pg.font.Font:
    """
    The condensed poster face used for headings and big numbers -- the result
    outcome, modal titles, the time-picker readout. It ships in one weight, so
    asking for bold gives the same cut back

    :param size: height in pixels
    :param bold: accepted for symmetry with the other loaders
    :returns: a newly loaded display font
    """
    return get_font(size, bold=bold, family=DISPLAY)


def get_mono_font(size: int, bold: bool = False) -> pg.font.Font:
    """
    The monospace face used wherever characters must line up or read as
    machine text -- move lists, clocks, board coordinates, rail labels

    :param size: height in pixels
    :param bold: use the bold cut
    :returns: a newly loaded monospace font
    """
    return get_font(size, bold=bold, family=MONO)


def fonts_for_width(
        cache: dict[str, Any], width: float,
        build: Callable[[float], tuple[pg.font.Font, ...]]) -> tuple[pg.font.Font, ...]:
    """
    Give a widget the set of fonts it needs for its current size, rebuilding
    them only when that size actually changes. Modals size their type off the
    panel they end up with, and this keeps them from loading a whole font set
    on every frame while still obeying the rule that fonts are never shared
    globally

    :param cache: the caller's own two-key dict, holding the last width and the
        fonts built for it; each widget keeps its own
    :param width: the size the fonts are derived from, either a panel width in
        pixels or a scale factor -- whatever the widget's build takes
    :param build: makes the font set for a width, called only on a change
    :returns: the font set for this width, owned by the calling widget
    """
    if cache.get("width") != width:
        cache["width"] = width
        cache["fonts"] = build(width)
    return cast(tuple[pg.font.Font, ...], cache["fonts"])
