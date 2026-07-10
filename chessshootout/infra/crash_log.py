import logging
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

from chessshootout.paths import PROJECT_ROOT
from chessshootout.infra.log_format import make_formatter


CRASHLOG_DIR_NAME = "crashlogs"
CRASHLOG_BUFFER_MAXLEN = 20000


class _ListHandler(logging.Handler):

    def __init__(self, maxlen=CRASHLOG_BUFFER_MAXLEN):
        super().__init__()
        self.buffer = deque(maxlen=maxlen)

    def emit(self, record):
        try:
            self.buffer.append(self.format(record))
        except Exception:
            pass


_active_handler = None


def install_memory_handler(level=logging.DEBUG):
    global _active_handler
    handler = _ListHandler()
    handler.setLevel(level)
    handler.setFormatter(make_formatter())
    logging.getLogger().addHandler(handler)
    _active_handler = handler
    return handler


def get_memory_buffer():
    if _active_handler is None:
        return []
    return list(_active_handler.buffer)


def gather_state(frontend):
    state = {}
    state["mode"] = getattr(frontend, "mode", None)
    match = getattr(frontend, "match", None)
    if match is not None:
        history = getattr(match, "move_history", None)
        state["move_history_len"] = len(history) if history is not None else None
    else:
        state["move_history_len"] = None
    online_client = getattr(frontend, "online_client", None)
    state["online_state"] = (
        getattr(online_client, "state", None) if online_client is not None else None
    )
    window = getattr(frontend, "window", None)
    state["window_size"] = (
        window.get_size() if window is not None and hasattr(window, "get_size") else None
    )
    return state


def write_crash_log(exc, log_buffer, state, *, root=None):
    base = Path(root) if root is not None else PROJECT_ROOT
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
