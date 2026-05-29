import argparse
import logging
import os

import certifi
import pygame as pg

import paths
from frontend import env, crash_log
from frontend.frontend import Frontend


os.environ.setdefault("SSL_CERT_FILE", certifi.where())


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
    handler = crash_log.install_memory_handler()
    log = logging.getLogger("chess.main")
    log.info("client starting pid=%s", os.getpid())
    env.init_paths()
    env.load()
    env.set_overrides(client_uuid=args.client_uuid, nickname=args.nickname)
    pg.init()
    mixer_ok = True
    try:
        pg.mixer.init()
    except pg.error:
        mixer_ok = False
    log.info("pygame init ok mixer=%s", mixer_ok)
    window_width, window_height = 1200, 1000
    app = None
    try:
        app = Frontend(window_width, window_height)
        log.info("frontend ready window=%dx%d", window_width, window_height)
        app.run()
    except Exception as exc:
        try:
            state = crash_log.gather_state(app) if app is not None else {}
            crash_log.write_crash_log(exc, handler.buffer, state, root=paths.get_log_dir())
        except Exception:
            log.exception("crash log write failed")
        raise
