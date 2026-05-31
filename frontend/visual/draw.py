import pygame as pg

SUPERSAMPLE = 4


def supersample(size, render, scale=SUPERSAMPLE):
    if isinstance(size, int):
        size = (size, size)
    big = pg.Surface((size[0] * scale, size[1] * scale), pg.SRCALPHA)
    render(big, scale)
    return pg.transform.smoothscale(big, size)
