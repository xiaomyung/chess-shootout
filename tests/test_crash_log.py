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
import os
import re
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from frontend.crash_log import (
    CRASHLOG_DIR_NAME, gather_state, install_memory_handler, write_crash_log,
)


# ---- write_crash_log: file location & filename shape ------------------------

def test_write_crash_log_creates_dir_under_root(tmp_path):
    path = write_crash_log(ValueError("boom"), [], {}, root=tmp_path)
    assert path.exists()
    assert path.parent == tmp_path / CRASHLOG_DIR_NAME


def test_write_crash_log_creates_dir_when_missing(tmp_path):
    # Even if no `crashlogs/` exists yet, the helper should mkdir -p it.
    target = tmp_path / "fresh"
    path = write_crash_log(ValueError("x"), [], {}, root=target)
    assert (target / CRASHLOG_DIR_NAME).is_dir()
    assert path.exists()


def test_write_crash_log_filename_is_timestamped(tmp_path):
    path = write_crash_log(ValueError("x"), [], {}, root=tmp_path)
    assert re.fullmatch(r"\d{8}-\d{6}\.txt", path.name)


# ---- write_crash_log: content sections --------------------------------------

def test_crash_log_includes_traceback(tmp_path):
    try:
        raise RuntimeError("kaboom")
    except RuntimeError as exc:
        path = write_crash_log(exc, [], {}, root=tmp_path)
    content = path.read_text()
    # Traceback section header + the actual exception text + the raise line.
    assert "== Traceback ==" in content
    assert "RuntimeError" in content
    assert "kaboom" in content


def test_crash_log_includes_state_section(tmp_path):
    state = {"mode": "online", "move_history_len": 12,
             "online_state": "connected"}
    path = write_crash_log(ValueError("x"), [], state, root=tmp_path)
    content = path.read_text()
    assert "== State at crash ==" in content
    assert "mode: online" in content
    assert "move_history_len: 12" in content
    assert "online_state: connected" in content


def test_crash_log_handles_empty_state_dict(tmp_path):
    path = write_crash_log(ValueError("x"), [], {}, root=tmp_path)
    content = path.read_text()
    assert "no state captured" in content


def test_crash_log_includes_log_buffer(tmp_path):
    buffer = [
        "10:00:01 INFO chess.client connecting",
        "10:00:02 INFO chess.client matchmake ok",
    ]
    path = write_crash_log(ValueError("x"), buffer, {}, root=tmp_path)
    content = path.read_text()
    assert "== Logs ==" in content
    assert "matchmake ok" in content
    assert "connecting" in content


def test_crash_log_handles_empty_log_buffer(tmp_path):
    path = write_crash_log(ValueError("x"), [], {}, root=tmp_path)
    content = path.read_text()
    assert "no log records captured" in content


def test_crash_log_section_order_is_traceback_state_logs(tmp_path):
    buffer = ["10:00:01 INFO chess.client logged"]
    state = {"mode": "menu"}
    try:
        raise ValueError("ordered")
    except ValueError as exc:
        path = write_crash_log(exc, buffer, state, root=tmp_path)
    content = path.read_text()
    i_tb = content.index("== Traceback ==")
    i_state = content.index("== State at crash ==")
    i_logs = content.index("== Logs ==")
    assert i_tb < i_state < i_logs


# ---- install_memory_handler -------------------------------------------------

@pytest.fixture
def isolated_root_logger():
    # Snapshot existing root handlers so we can restore them — this test
    # mutates the global logger and we don't want to leak the change to
    # neighbouring test files.
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
    # Match the format used elsewhere in the app: time + level + name + msg.
    handler = install_memory_handler()
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.test_format")
    log.setLevel(logging.DEBUG)
    log.warning("formatted")
    line = next(L for L in handler.buffer if "formatted" in L)
    assert "WARNING" in line
    assert "chess.test_format" in line


def test_install_memory_handler_buffer_unbounded(isolated_root_logger):
    # The user explicitly wants the buffer unbounded — assert that lots of
    # records all stay in the buffer (no LRU eviction).
    handler = install_memory_handler()
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.test_volume")
    log.setLevel(logging.DEBUG)
    for i in range(500):
        log.info("burst-%d", i)
    burst_lines = [L for L in handler.buffer if "burst-" in L]
    assert len(burst_lines) == 500


# ---- gather_state ----------------------------------------------------------

def test_gather_state_extracts_all_known_fields():
    fe = SimpleNamespace(
        mode="online",
        match=SimpleNamespace(move_history=[1, 2, 3]),
        online_client=SimpleNamespace(state="connected"),
        window=SimpleNamespace(get_size=lambda: (1200, 800)),
    )
    state = gather_state(fe)
    assert state["mode"] == "online"
    assert state["move_history_len"] == 3
    assert state["online_state"] == "connected"
    assert state["window_size"] == (1200, 800)


def test_gather_state_handles_missing_match_and_client():
    # Crashes that happen during early init may have no match / no client —
    # gather_state must not raise.
    fe = SimpleNamespace(mode="menu", match=None, online_client=None,
                         window=SimpleNamespace(get_size=lambda: (900, 600)))
    state = gather_state(fe)
    assert state["mode"] == "menu"
    assert state["move_history_len"] is None
    assert state["online_state"] is None


def test_gather_state_tolerates_completely_blank_object():
    # `app` could be None very early — but gather_state is only called when
    # app is non-None. Still, an empty namespace shouldn't blow up.
    state = gather_state(SimpleNamespace())
    assert state == {
        "mode": None,
        "move_history_len": None,
        "online_state": None,
        "window_size": None,
    }


# ---- end-to-end (handler → buffer → write_crash_log) ------------------------

def test_end_to_end_handler_drains_into_crash_log(tmp_path, isolated_root_logger):
    # The whole flow main.py uses: install handler, capture some logs, then
    # call write_crash_log with the handler's buffer when something blows up.
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
    content = path.read_text()
    assert "step-1-ok" in content
    assert "step-2-suspicious" in content
    assert "step-3-broken" in content
    assert "mode: menu" in content
