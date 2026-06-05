"""Background gradient debanding dither.

The arena background gradient spans only ~20 8-bit levels per channel
(``#1a1f27 -> #0d0f14 -> #090a0e``) across the whole window, so without
dithering each level is a wide visible band ("low-bitrate" posterization).
``dither`` applies a baked, deterministic +/-1 triangular dither that breaks
the band edges; it is the sole fix (raising the radial source resolution does
not help, since 8-bit quantization is independent of pixel count).
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.visual import backdrop
from chessshootout.frontend.visual.colors import Colors


@pytest.fixture(scope="module", autouse=True)
def _pg():
    pg.init()
    pg.display.set_mode((64, 64))
    yield
    pg.quit()


COLORS = (Colors.battle_bg_hi, Colors.battle_bg, Colors.battle_bg_edge)


def _max_run(surf, x):
    prev = None
    best = run = 0
    for y in range(surf.get_height()):
        c = surf.get_at((x, y))[:3]
        run = run + 1 if c == prev else 1
        best = max(best, run)
        prev = c
    return best


def _shallow_vertical_gradient(w, h):
    surf = pg.Surface((w, h))
    for y in range(h):
        v = 9 + (y * 20) // h
        pg.draw.line(surf, (v, v, v + 5), (0, y), (w, y))
    return surf


def test_radial_gradient_size_and_shape():
    surf = backdrop.radial_gradient(64, 0.5, 0.18, 1.2, 0.8, *COLORS)
    assert surf.get_size() == (64, 64)
    center = surf.get_at((32, 11))[:3]
    corner = surf.get_at((63, 63))[:3]
    assert sum(center) > sum(corner)


def test_dither_amplitude_is_within_one_level():
    flat = pg.Surface((256, 256))
    flat.fill((40, 40, 40))
    out = backdrop.dither(flat.copy())
    seen = set()
    for y in range(0, 256, 3):
        for x in range(0, 256, 3):
            seen.add(out.get_at((x, y))[:3])
    for c in seen:
        for ch in c:
            assert 39 <= ch <= 41


def test_dither_is_balanced_around_zero():
    flat = pg.Surface((256, 256))
    flat.fill((40, 40, 40))
    out = backdrop.dither(flat.copy())
    up = down = 0
    for y in range(256):
        for x in range(256):
            r = out.get_at((x, y))[0]
            up += r > 40
            down += r < 40
    assert up > 0 and down > 0
    assert abs(up - down) < 0.1 * (up + down)


def test_dither_is_deterministic():
    flat = pg.Surface((128, 128))
    flat.fill((30, 30, 30))
    a = backdrop.dither(flat.copy())
    b = backdrop.dither(flat.copy())
    assert pg.image.tostring(a, "RGB") == pg.image.tostring(b, "RGB")


def test_dither_breaks_banding_runs():
    grad = _shallow_vertical_gradient(32, 600)
    before = _max_run(grad, 16)
    after = _max_run(backdrop.dither(grad.copy()), 16)
    assert before > 20
    assert after < before // 3


def test_arena_background_size_and_determinism():
    a = backdrop.arena_background((480, 320), (0.5, 0.18))
    b = backdrop.arena_background((480, 320), (0.5, 0.18))
    assert a.get_size() == (480, 320)
    assert pg.image.tostring(a, "RGB") == pg.image.tostring(b, "RGB")


def test_arena_background_has_no_long_bands():
    surf = backdrop.arena_background((480, 600), (0.5, 0.18))
    assert _max_run(surf, 240) < 24
