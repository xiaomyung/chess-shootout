from weakref import WeakKeyDictionary

_REGISTRY = []
_SIZE_REGISTRY = []

_TEXT_CACHE = WeakKeyDictionary()
_REGISTRY.append(_TEXT_CACHE)


def render_text(font, text, color, aa=True):
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


def new_cache():
    cache = {}
    _REGISTRY.append(cache)
    return cache


def new_size_cache():
    cache = {}
    _REGISTRY.append(cache)
    _SIZE_REGISTRY.append(cache)
    return cache


def memoized_surface(cache, key, build):
    surf = cache.get(key)
    if surf is None:
        surf = build()
        cache[key] = surf
    return surf


def clear_all():
    for cache in _REGISTRY:
        cache.clear()


def clear_size_keyed():
    for cache in _SIZE_REGISTRY:
        cache.clear()
