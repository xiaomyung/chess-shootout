import logging
import time
from typing import Any


LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

THIRD_PARTY_QUIET_LOGGERS = ("httpx", "httpcore")


class UtcFormatter(logging.Formatter):
    """
    The one log formatter the whole project uses: timestamps in UTC, never the
    host's local time. Client crash logs and server logs are read side by side
    when a match goes wrong, so their clocks have to line up
    """

    converter = staticmethod(time.gmtime)


def make_formatter() -> UtcFormatter:
    """
    Build the shared formatter -- UTC date, time with milliseconds, padded
    level, logger name, message. Every handler the game and the server install
    is given one of these, which is what keeps all log output one shape

    :returns: a formatter carrying the canonical format and date format
    """
    return UtcFormatter(LOG_FORMAT, datefmt=LOG_DATEFMT)


def configure_basic(level: int | str) -> None:
    """
    Set up logging for a process at startup: put the root logger at the wanted
    level and, only if nothing has attached a handler yet, add one stream
    handler using the shared format. Called once by the client and the server

    :param level: root log level, a logging constant or its name such as INFO
    """
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(make_formatter())
        root.addHandler(handler)


def silence_third_party_loggers() -> None:
    """
    Raise the chatty HTTP libraries to WARNING so the client's own log stays
    readable. httpx logs a line for every request, and the reconnect probes
    alone would otherwise bury the game's own state transitions
    """
    for name in THIRD_PARTY_QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def uvicorn_log_config() -> dict[str, Any]:
    """
    Describe logging to uvicorn so the web server's own lines come out in the
    same UTC shape as the game server's. Existing loggers are deliberately left
    enabled, otherwise applying this config would silence the app's own logs

    :returns: a dictConfig mapping ready to hand to uvicorn as log_config
    """
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
