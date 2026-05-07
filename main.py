import pygame as pg

from frontend.frontend import Frontend


if __name__ == "__main__":
    pg.init()
    window_width, window_height = 1200, 1000
    app = Frontend(window_width, window_height)
    app.run()