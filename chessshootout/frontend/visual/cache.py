from collections import OrderedDict
from weakref import WeakKeyDictionary

_REGISTRY = []

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


def memoized_surface(cache, key, build):
    surf = cache.get(key)
    if surf is None:
        surf = build()
        cache[key] = surf
    return surf


class LruSurfaceCache:

    def __init__(self, capacity):
        self.capacity = max(int(capacity), 1)
        self._data = OrderedDict()
        _REGISTRY.append(self._data)

    def get_or_build(self, key, build):
        data = self._data
        surf = data.get(key)
        if surf is not None:
            data.move_to_end(key)
            return surf
        surf = build()
        data[key] = surf
        while len(data) > self.capacity:
            data.popitem(last=False)
        return surf

    def clear(self):
        self._data.clear()


def clear_all():
    for cache in _REGISTRY:
        cache.clear()
