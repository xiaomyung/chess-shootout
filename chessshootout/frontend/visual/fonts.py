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


def get_font(size, bold=False, mono=False, family=None):
    size = max(int(size), 1)
    if family is None:
        family = MONO if mono else SANS
    name = _FONT_FILES[(family, bool(bold))]
    try:
        return pg.font.Font(str(resource_path("assets", "fonts", name)), size)
    except (OSError, pg.error):
        return pg.font.SysFont(_SYS_FALLBACK[family], size, bold=bold)


def get_display_font(size, bold=False):
    return get_font(size, bold=bold, family=DISPLAY)


def get_mono_font(size, bold=False):
    return get_font(size, bold=bold, family=MONO)


def get_emoji_font(size=128):
    try:
        return pg.font.Font(str(resource_path("assets", "fonts", "NotoColorEmoji.ttf")),
                            max(int(size), 1))
    except (OSError, pg.error):
        return None
