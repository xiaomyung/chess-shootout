import logging
import time


LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class UtcFormatter(logging.Formatter):
    converter = staticmethod(time.gmtime)


def make_formatter():
    return UtcFormatter(LOG_FORMAT, datefmt=LOG_DATEFMT)


def configure_basic(level):
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(make_formatter())
        root.addHandler(handler)


def uvicorn_log_config():
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "chess": {
                "()": "chessshootout.infra.log_format.UtcFormatter",
                "fmt": LOG_FORMAT,
                "datefmt": LOG_DATEFMT,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "chess",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "class": "logging.StreamHandler",
                "formatter": "chess",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }
