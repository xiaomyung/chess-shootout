"""The shared surface cache: memoization behaviour plus the typing guard.

`memoized_surface` is the house pattern behind nearly every hand-drawn
surface in the UI, and it used to be annotated `-> Any`. That erased the
builder's type at ~60 call sites, each of which had to paper over the hole
with `cast(pg.Surface, ...)` -- a cast mypy cannot check, so a builder whose
return type quietly changed would have been silently mis-typed everywhere it
was read. It is now generic in the builder's return type, and the casts are
gone.

The guard below is AST-based and path-walked from chessshootout.__file__
with scanned-file floors, the same shape as the screen-isolation guards in
test_screen_guards.py: a re-introduced cast around a memoized_surface call
is the exact regression that would bring the blind spot back.
"""

import ast
import os
from collections.abc import Callable

import pygame as pg

import chessshootout
from tests.conftest import pygame_display
from chessshootout.frontend.visual.cache import (
    memoized_surface, new_cache, new_size_cache, clear_all, clear_size_keyed,
)


_pygame_init = pygame_display(200, 200)

PACKAGE_ROOT = os.path.dirname(os.path.abspath(chessshootout.__file__))
FRONTEND_ROOT = os.path.join(PACKAGE_ROOT, "frontend")

MIN_SCANNED_FILES = 80
MIN_CALL_SITES = 40


def _iter_py_files(root):
    for dirpath, _, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _called_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _scan_frontend():
    """Every memoized_surface call site in the frontend, and the subset of them
    wrapped in a cast, as "module:line" strings."""
    call_sites, cast_wrapped, files = [], [], 0
    for path in _iter_py_files(FRONTEND_ROOT):
        files += 1
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        rel = os.path.relpath(path, PACKAGE_ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _called_name(node) == "memoized_surface" and node.args:
                call_sites.append(f"{rel}:{node.lineno}")
            if _called_name(node) != "cast" or len(node.args) < 2:
                continue
            inner = node.args[1]
            if isinstance(inner, ast.Call) and _called_name(inner) == "memoized_surface":
                cast_wrapped.append(f"{rel}:{node.lineno}")
    return call_sites, cast_wrapped, files


def test_memoized_surface_is_generic_in_the_builders_return_type():
    """The signature is `def memoized_surface[T](..., build: Callable[[], T]) -> T`:
    what the builder returns is what comes back, checked rather than erased to
    Any. An `-> Any` regression makes every call site unverifiable again."""
    type_params = memoized_surface.__type_params__
    assert len(type_params) == 1, "one type variable, bound to the builder's return"
    tvar = type_params[0]
    annotations = memoized_surface.__annotations__
    assert annotations["return"] is tvar, "the return type is the builder's type, not Any"
    assert annotations["build"] == Callable[[], tvar], \
        "the builder is what pins the type variable"


def test_no_frontend_call_site_casts_a_memoized_surface_result():
    """Every `cast(pg.Surface, memoized_surface(...))` in the frontend was removable
    once the helper became generic. A new one would mean either a needless cast or
    a builder whose real type is being lied about at the call site."""
    call_sites, cast_wrapped, files = _scan_frontend()
    assert files >= MIN_SCANNED_FILES, f"only {files} frontend files walked -- guard blind"
    assert len(call_sites) >= MIN_CALL_SITES, \
        f"only {len(call_sites)} memoized_surface call sites found -- guard blind"
    assert cast_wrapped == [], \
        "memoized_surface returns the builder's type; drop the cast at " \
        + ", ".join(cast_wrapped)


def test_memoized_surface_builds_once_and_shares_the_result():
    """The point of the cache: a second lookup of the same key never runs the
    builder again and hands back the very same object."""
    cache = new_cache()
    built = []

    def build():
        surf = pg.Surface((4, 4), pg.SRCALPHA)
        built.append(surf)
        return surf

    first = memoized_surface(cache, ("k", 4), build)
    second = memoized_surface(cache, ("k", 4), build)
    assert len(built) == 1, "the second lookup is a hit, not a rebuild"
    assert second is first
    assert memoized_surface(cache, ("k", 8), build) is not first, "a new key rebuilds"
    assert len(built) == 2


def test_memoized_surface_round_trips_non_surface_payloads():
    """Some builders return a surface bundled with the geometry measured while
    drawing it, and board.py unpacks that tuple straight from the call. The
    helper must hand the payload back unchanged rather than flattening it."""
    cache = new_cache()
    payload = (pg.Surface((2, 2), pg.SRCALPHA), {"grip": (1, 2)})
    sprite, geom = memoized_surface(cache, "bundle", lambda: payload)
    assert sprite is payload[0]
    assert geom == {"grip": (1, 2)}
    assert memoized_surface(cache, "bundle", lambda: None) is payload, \
        "a hit never consults the builder"


def test_size_caches_clear_on_resize_and_plain_caches_survive():
    """A resize invalidates only what was drawn at the old pixel size; icons and
    other size-independent art must not be thrown away with it."""
    plain, sized = new_cache(), new_size_cache()
    memoized_surface(plain, "icon", lambda: pg.Surface((2, 2)))
    memoized_surface(sized, "panel", lambda: pg.Surface((2, 2)))
    clear_size_keyed()
    assert "icon" in plain, "size-independent art survives a resize"
    assert "panel" not in sized, "size-keyed art is dropped on a resize"
    clear_all()
    assert "icon" not in plain, "a full clear reaches every registered cache"
