import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg

from chessshootout.frontend.window_chrome import WindowChrome, WINDOW_FLAGS


def main():
    pg.init()
    pg.display.set_mode((900, 500), WINDOW_FLAGS)
    chrome = WindowChrome(pg.display.get_surface())
    if chrome._sdl is None:
        raise SystemExit("FAIL: SDL2 library did not load via ctypes")
    if not chrome._win_ptr:
        raise SystemExit("FAIL: SDL_Window pointer not resolved from window id")
    if not hasattr(chrome._sdl, "SDL_SetWindowHitTest"):
        raise SystemExit("FAIL: SDL_SetWindowHitTest symbol missing")
    chrome.draw()
    pg.quit()
    print("chrome selfcheck OK on", os.environ.get("RUNNER_OS", "local"))


if __name__ == "__main__":
    main()
