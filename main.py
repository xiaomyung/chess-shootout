import argparse
import logging
import os

import pygame as pg

from frontend import env
from frontend.frontend import Frontend


def _parse_args():
    p = argparse.ArgumentParser(description="Pygame chess client")
    p.add_argument("--client-uuid", help="Override CHESS_CLIENT_UUID for this run")
    p.add_argument("--nickname", help="Override CHESS_NICKNAME for this run")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    env.load()
    env.set_overrides(client_uuid=args.client_uuid, nickname=args.nickname)
    pg.init()
    try:
        pg.mixer.init()
    except pg.error:
        pass
    window_width, window_height = 1200, 1000
    app = Frontend(window_width, window_height)
    app.run()
