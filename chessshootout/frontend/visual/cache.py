from collections.abc import Callable
from typing import Any
from weakref import WeakKeyDictionary

import pygame as pg

_REGISTRY = []
_SIZE_REGISTRY = []

_TEXT_CACHE = WeakKeyDictionary()
_REGISTRY.append(_TEXT_CACHE)


def render_text(font: pg.font.Font, text: str, color: str | pg.Color,
                aa: bool = True) -> pg.Surface:
    """
    Draw a line of text once and hand the same surface out every frame after
    that. Nearly every label in the game goes through here, which is what keeps
    a full UI off the font rasteriser each frame. Entries hang off the font
    itself in a weak-keyed map, so the surfaces built for a font size die with
    that font when a resize replaces it

    :param font: the loaded font to render with, also the cache bucket key
    :param text: the exact string to draw; a different string is a new entry
    :param color: ink colour, normally a hex token from Colors
    :param aa: whether to antialias, part of the key so both forms can coexist
    :returns: the shared text surface -- treat it as read-only and copy before
        mutating alpha or blitting into it
    """
    per_font = _TEXT_CACHE.get(font)
    if per_font is None:
        per_font = {}
        _TEXT_CACHE[font] = per_font
    key = (text, str(color), aa)
    surf = per_font.get(key)
    if surf is None:
        surf = font.render(text, aa, color)
        per_font[key] = surf
    return surf


def new_cache() -> dict[Any, Any]:
    """
    Open a cache for drawables whose look does not depend on the window size --
    icons, chips, glyph plates. It is registered process-wide so a full clear
    reaches it, but a window resize deliberately leaves it alone

    :returns: an empty cache dict for the calling module to key as it likes
    """
    cache = {}
    _REGISTRY.append(cache)
    return cache


def new_size_cache() -> dict[Any, Any]:
    """
    Open a cache for drawables built at a particular pixel size -- panels,
    board sprites, rounded and cut rects. These are the entries a resize makes
    worthless, so this cache joins the size-keyed subset that a resize clears

    :returns: an empty cache dict, cleared on every window resize
    """
    cache = {}
    _REGISTRY.append(cache)
    _SIZE_REGISTRY.append(cache)
    return cache


def memoized_surface(cache: dict[Any, Any], key: Any, build: Callable[[], Any]) -> Any:
    """
    Build a drawable once for a given key and reuse it forever after, the
    house pattern for every hand-drawn surface in the UI. Callers pass a
    closure that does the expensive drawing, so nothing is built until the
    first frame that actually needs it

    :param cache: a cache from new_cache or new_size_cache to store it in
    :param key: hashable identity of the drawable -- every input that changes
        how it looks (size, colour, state) must appear in it
    :param build: makes the value on a miss; usually a surface, sometimes a
        surface bundled with the geometry measured while drawing it
    :returns: the cached value, shared with every other caller of that key
    """
    surf = cache.get(key)
    if surf is None:
        surf = build()
        cache[key] = surf
    return surf


def clear_all() -> None:
    """
    Empty every cache in the process, text included. The shell does this while
    shutting down, just before pygame quits, so no surface outlives the display
    it was built against; the test suite does it between modules to cap growth
    """
    for cache in _REGISTRY:
        cache.clear()


def clear_size_keyed() -> None:
    """
    Empty only the caches whose contents were built for the old window size,
    which is exactly what a resize invalidates. The shell calls this from its
    layout pass, leaving size-independent art such as icons in place
    """
    for cache in _SIZE_REGISTRY:
        cache.clear()
