import logging
import logging.handlers
import os


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
LOG_DATEFMT = "%H:%M:%S"
ROTATING_MAX_BYTES = 5 * 1024 * 1024
ROTATING_BACKUP_COUNT = 3


def configure(level=None, log_file=None):
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=level, format=LOG_FORMAT, datefmt=LOG_DATEFMT,
    )
    log_file = log_file or os.environ.get("LOG_FILE")
    if log_file:
        attach_rotating_file_handler(log_file, level=level)


def attach_rotating_file_handler(path, *, level="INFO",
                                   max_bytes=ROTATING_MAX_BYTES,
                                   backup_count=ROTATING_BACKUP_COUNT):
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count,
    )
    handler.setLevel(level if isinstance(level, int) else level.upper())
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    logging.getLogger().addHandler(handler)
    return handler


def get_logger(name="chess.server"):
    return logging.getLogger(name)
