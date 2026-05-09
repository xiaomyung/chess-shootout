import pygame as pg

from frontend.visual.colors import Colors


LOW_TIME_FRACTION = 0.10
INCREMENT_FLASH_MS = 300


def clock_pocket_color(fraction):
    base = pg.Color(Colors.light_grey_menu)
    low = pg.Color(Colors.clock_low_time)
    if fraction is None or fraction >= LOW_TIME_FRACTION:
        return base
    if fraction <= 0:
        return low
    progress = (LOW_TIME_FRACTION - fraction) / LOW_TIME_FRACTION
    return base.lerp(low, progress)
