import logging
import os


def configure(level=None):
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )


def get_logger(name="chess.server"):
    return logging.getLogger(name)
