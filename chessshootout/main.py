import argparse
import logging
import os

import certifi
import pygame as pg

from chessshootout import paths
from chessshootout.infra import env, crash_log
from chessshootout.infra.log_format import configure_basic, silence_third_party_loggers
from chessshootout.frontend.frontend import Frontend


os.environ.setdefault("SSL_CERT_FILE", certifi.where())

log = logging.getLogger("chess.main")


def _parse_args() -> argparse.Namespace:
    """
    Read the two overrides the client accepts on the command line. They shadow
    the stored CHESS_CLIENT_UUID and CHESS_NICKNAME for one run, which is how
    a second copy of the game can play as a different person for testing

    :returns: parsed arguments; client_uuid and nickname are None when unused
    """
    p = argparse.ArgumentParser(description="Pygame chess client")
    p.add_argument("--client-uuid", help="Override CHESS_CLIENT_UUID for this run")
    p.add_argument("--nickname", help="Override CHESS_NICKNAME for this run")
    return p.parse_args()


def main() -> None:
    """
    Start the game and run it to the end: set up logging and crash capture,
    load the stored settings, bring pygame up, then build the app shell and
    drive its frame loop until the player quits. Anything that escapes the
    loop is written to a crash log before it is re-raised
    """
    args = _parse_args()
    configure_basic(os.environ.get("LOG_LEVEL", "INFO").upper())
    silence_third_party_loggers()
    handler = crash_log.install_memory_handler()
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
        app.sound_manager.preload()
        log.info("frontend ready window=%dx%d", window_width, window_height)
        app.run()
    except Exception as exc:
        try:
            state = crash_log.gather_state(app) if app is not None else {}
            crash_log.write_crash_log(exc, handler.buffer, state, root=paths.get_log_dir())
        except Exception:
            log.exception("crash log write failed")
        raise


if __name__ == "__main__":
    main()
