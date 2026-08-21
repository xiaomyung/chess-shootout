import logging
import traceback
from collections import deque
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from chessshootout import paths
from chessshootout.infra.log_format import make_formatter


CRASHLOG_DIR_NAME = "crashlogs"
CRASHLOG_BUFFER_MAXLEN = 20000


class _ListHandler(logging.Handler):
    """
    A log handler that keeps recent lines in memory rather than writing them
    anywhere, so a crash can ship the log tail that led up to it. The store is
    a bounded deque: the oldest line is dropped once it is full, and a long
    session can never grow the buffer without limit
    """

    def __init__(self, maxlen: int = CRASHLOG_BUFFER_MAXLEN) -> None:
        """
        Create the handler with an empty bounded buffer. The bound is what
        makes this safe to leave installed for a whole run

        :param maxlen: how many formatted lines to keep before the oldest ones
            start falling off the front
        """
        super().__init__()
        self.buffer = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Format one log record and append it to the buffer. Any failure while
        formatting is swallowed on purpose -- a broken log call must never take
        down the run it is only meant to be recording

        :param record: the record the logging framework is dispatching
        """
        try:
            self.buffer.append(self.format(record))
        except Exception:
            pass


_active_handler = None


def install_memory_handler(level: int | str = logging.DEBUG) -> _ListHandler:
    """
    Start capturing the log tail at startup by attaching the in-memory handler
    to the root logger, and remember it so background threads can reach the
    same buffer. The entry point keeps the returned handler and drains it into
    the crash file if anything escapes the frame loop

    :param level: lowest level to capture; DEBUG by default, since the wire
        noise is exactly what a crash report needs
    :returns: the installed handler, whose buffer holds the captured lines
    """
    global _active_handler
    handler = _ListHandler()
    handler.setLevel(level)
    handler.setFormatter(make_formatter())
    logging.getLogger().addHandler(handler)
    _active_handler = handler
    return handler


def get_memory_buffer() -> list[str]:
    """
    Read the captured log tail without holding the handler, which is how the
    online client's worker thread gets the lines for a crash it writes itself.
    Snapshots the deque, so the caller is never iterating a live buffer

    :returns: the captured lines oldest first, empty when nothing is installed
    """
    if _active_handler is None:
        return []
    return list(_active_handler.buffer)


def gather_state(frontend: Any) -> dict[str, Any]:
    """
    Snapshot the few facts that make a crash report readable: which screen was
    up and what it reports about itself, the online connection state and the
    window size. Everything is read defensively, because a crash during startup
    can reach here with a half-built app

    :param frontend: the app shell, or anything shaped like it; missing
        attributes are reported as None rather than raising
    :returns: readable key/value summary written into the crash file
    """
    state = {}
    screen = getattr(frontend, "screen", None)
    state["screen"] = getattr(screen, "name", None)
    if screen is not None:
        state.update(screen.debug_state())
    coordinator = getattr(frontend, "coordinator", None)
    online_client = getattr(coordinator, "client", None) if coordinator is not None else None
    state["online_state"] = (
        getattr(online_client, "state", None) if online_client is not None else None
    )
    window = getattr(frontend, "window", None)
    state["window_size"] = (
        window.get_size() if window is not None and hasattr(window, "get_size") else None
    )
    return state


def write_crash_log(exc: BaseException, log_buffer: Sequence[str], state: dict[str, Any],
                    *, root: str | Path | None = None) -> Path:
    """
    Write the one file a player can send after a crash: the traceback, the
    state at the moment it happened and the captured log tail, in that fixed
    order under readable headings. The file is timestamped and lands in a
    crashlogs folder, which is created if it is not there yet

    :param exc: the exception that ended the run, formatted with its traceback
    :param log_buffer: captured log lines oldest first, empty when there
        are none to report
    :param state: snapshot from gather_state, or empty when none was taken
    :param root: directory to create the crashlogs folder in; defaults to the
        build's own log directory
    :returns: path of the crash file that was written
    """
    base = Path(root) if root is not None else paths.get_log_dir()
    crashlogs_dir = base / CRASHLOG_DIR_NAME
    crashlogs_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    path = crashlogs_dir / filename

    parts = []
    parts.append("== Traceback ==")
    parts.append(
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip(),
    )
    parts.append("")
    parts.append("== State at crash ==")
    if state:
        for key, value in state.items():
            parts.append(f"{key}: {value}")
    else:
        parts.append("(no state captured)")
    parts.append("")
    parts.append("== Logs ==")
    if log_buffer:
        parts.extend(log_buffer)
    else:
        parts.append("(no log records captured)")

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path
