import pygame as pg

from paths import resource_path


_FONT_FILES = {
    (False, False): "DejaVuSans.ttf",
    (False, True): "DejaVuSans-Bold.ttf",
    (True, False): "DejaVuSansMono.ttf",
    (True, True): "DejaVuSansMono-Bold.ttf",
}


def get_font(size, bold=False, mono=False):
    size = max(int(size), 1)
    name = _FONT_FILES[(bool(mono), bool(bold))]
    try:
        return pg.font.Font(str(resource_path("assets", "fonts", name)), size)
    except (OSError, pg.error):
        return pg.font.SysFont("monospace" if mono else "Arial", size, bold=bold)
