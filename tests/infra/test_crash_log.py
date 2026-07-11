"""M17: Crash log capture.

write_crash_log is a pure helper — pass it a fake exception, log buffer,
and state dict. Verify the file goes where it should, the filename has
the YYYYMMDD-HHMMSS shape, and the contents include traceback + state +
log lines under recognizable section headers. install_memory_handler
attaches a handler whose buffer accumulates formatted log lines until
write_crash_log drains it; gather_state pulls the few Frontend fields
that are useful in a post-mortem.
"""
import logging
import re
from types import SimpleNamespace

import pytest

from chessshootout.infra.crash_log import (
    CRASHLOG_BUFFER_MAXLEN, CRASHLOG_DIR_NAME, _ListHandler, gather_state,
    install_memory_handler, write_crash_log,
)


def test_write_crash_log_creates_dir_under_root(tmp_path):
    path = write_crash_log(ValueError("boom"), [], {}, root=tmp_path)
    assert path.exists()
    assert path.parent == tmp_path / CRASHLOG_DIR_NAME


def test_write_crash_log_creates_dir_when_missing(tmp_path):
    """root that doesn't exist yet must be mkdir -p'd."""
    target = tmp_path / "fresh"
    path = write_crash_log(ValueError("x"), [], {}, root=target)
    assert (target / CRASHLOG_DIR_NAME).is_dir()
    assert path.exists()


def test_write_crash_log_filename_is_timestamped(tmp_path):
    path = write_crash_log(ValueError("x"), [], {}, root=tmp_path)
    assert re.fullmatch(r"\d{8}-\d{6}\.txt", path.name)


@pytest.mark.parametrize(
    "log_buffer, state, expected_substrings",
    [
        pytest.param(
            [], {}, ["== State at crash ==", "(no state captured)"],
            id="empty_state_falls_back_to_placeholder",
        ),
        pytest.param(
            [], {}, ["== Logs ==", "(no log records captured)"],
            id="empty_buffer_falls_back_to_placeholder",
        ),
        pytest.param(
            [],
            {"mode": "online", "move_history_len": 12, "online_state": "connected"},
            ["== State at crash ==", "mode: online",
             "move_history_len: 12", "online_state: connected"],
            id="state_section_lists_each_key_value",
        ),
        pytest.param(
            ["10:00:01 INFO chess.client connecting",
             "10:00:02 INFO chess.client matchmake ok"],
            {},
            ["== Logs ==", "connecting", "matchmake ok"],
            id="log_section_includes_each_buffer_line",
        ),
    ],
)
def test_crash_log_content_includes(tmp_path, log_buffer, state, expected_substrings):
    """Each section header and rendered line lands verbatim in the file."""
    path = write_crash_log(ValueError("x"), log_buffer, state, root=tmp_path)
    content = path.read_text(encoding="utf-8")
    for fragment in expected_substrings:
        assert fragment in content


def test_crash_log_includes_traceback(tmp_path):
    """Needs a real raise so exc.__traceback__ is populated for the formatter."""
    try:
        raise RuntimeError("kaboom")
    except RuntimeError as exc:
        path = write_crash_log(exc, [], {}, root=tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "== Traceback ==" in content
    assert "RuntimeError" in content
    assert "kaboom" in content


def test_crash_log_section_order_is_traceback_state_logs(tmp_path):
    buffer = ["10:00:01 INFO chess.client logged"]
    state = {"mode": "menu"}
    try:
        raise ValueError("ordered")
    except ValueError as exc:
        path = write_crash_log(exc, buffer, state, root=tmp_path)
    content = path.read_text(encoding="utf-8")
    i_tb = content.index("== Traceback ==")
    i_state = content.index("== State at crash ==")
    i_logs = content.index("== Logs ==")
    assert i_tb < i_state < i_logs


@pytest.fixture
def isolated_root_logger():
    """Snapshot/restore root handlers so the global-logger mutation doesn't leak."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_install_memory_handler_captures_log_records(isolated_root_logger):
    handler = install_memory_handler()
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.test_crash_log")
    log.setLevel(logging.DEBUG)
    log.info("hello-from-test")
    assert any("hello-from-test" in line for line in handler.buffer)


def test_install_memory_handler_uses_canonical_format(isolated_root_logger):
    """Format mirrors the app: level + logger name + msg all rendered per line."""
    handler = install_memory_handler()
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.test_format")
    log.setLevel(logging.DEBUG)
    log.warning("formatted")
    line = next(L for L in handler.buffer if "formatted" in L)
    assert "WARNING" in line
    assert "chess.test_format" in line


def test_install_memory_handler_buffer_is_capped_at_the_default_maxlen(isolated_root_logger):
    """The production entry point wires up the module's default cap so a
    long-running session can't grow the buffer forever."""
    handler = install_memory_handler()
    assert handler.buffer.maxlen == CRASHLOG_BUFFER_MAXLEN
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.test_volume")
    log.setLevel(logging.DEBUG)
    for i in range(500):
        log.info("burst-%d", i)
    burst_lines = [L for L in handler.buffer if "burst-" in L]
    assert len(burst_lines) == 500, "well under the cap, nothing evicted yet"


def test_list_handler_evicts_oldest_once_past_maxlen():
    """A small maxlen exercises the eviction boundary cheaply (no need to log
    20000 real records): once full, appending drops the oldest entry."""
    handler = _ListHandler(maxlen=3)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for i in range(5):
        record = logging.LogRecord(
            "chess.test_evict", logging.INFO, __file__, 1, f"line-{i}", None, None)
        handler.emit(record)
    assert len(handler.buffer) == 3
    assert list(handler.buffer) == ["line-2", "line-3", "line-4"]


def test_gather_state_extracts_all_known_fields():
    fe = SimpleNamespace(
        mode="online",
        match=SimpleNamespace(move_history=[1, 2, 3]),
        coordinator=SimpleNamespace(client=SimpleNamespace(state="connected")),
        window=SimpleNamespace(get_size=lambda: (1200, 800)),
    )
    state = gather_state(fe)
    assert state["mode"] == "online"
    assert state["move_history_len"] == 3
    assert state["online_state"] == "connected"
    assert state["window_size"] == (1200, 800)


def test_gather_state_handles_missing_match_and_client():
    """Early-init crashes (no match / no client) must not raise."""
    fe = SimpleNamespace(mode="menu", match=None,
                         coordinator=SimpleNamespace(client=None),
                         window=SimpleNamespace(get_size=lambda: (900, 600)))
    state = gather_state(fe)
    assert state["mode"] == "menu"
    assert state["move_history_len"] is None
    assert state["online_state"] is None
    assert state["window_size"] == (900, 600)


def test_gather_state_tolerates_completely_blank_object():
    """A bare namespace (no attrs) yields all-None rather than blowing up."""
    state = gather_state(SimpleNamespace())
    assert state == {
        "mode": None,
        "move_history_len": None,
        "online_state": None,
        "window_size": None,
    }


def test_end_to_end_handler_drains_into_crash_log(tmp_path, isolated_root_logger):
    """Full main.py flow: install handler, log, then drain its buffer on crash."""
    handler = install_memory_handler()
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.e2e_crash")
    log.setLevel(logging.DEBUG)
    log.info("step-1-ok")
    log.warning("step-2-suspicious")
    try:
        raise RuntimeError("step-3-broken")
    except RuntimeError as exc:
        path = write_crash_log(exc, handler.buffer, {"mode": "menu"},
                               root=tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "step-1-ok" in content
    assert "step-2-suspicious" in content
    assert "step-3-broken" in content
    assert "mode: menu" in content
