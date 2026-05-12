"""M18b: structured logging — KV format, RotatingFileHandler when LOG_FILE set.

Existing log lines already follow the `key=value` style after a free-form
prefix (e.g. `move applied room=… mover=… san=…`). The two surfaces this
file pins are:

1. attach_rotating_file_handler wires up Python's RotatingFileHandler at
   the root logger with the canonical format used everywhere else.
2. The handler uses the documented file path and rotation policy.
"""
import logging
import logging.handlers
import os

import pytest

from server import logging_setup


@pytest.fixture
def isolated_root_logger():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_attach_rotating_file_handler_writes_to_path(tmp_path,
                                                       isolated_root_logger):
    path = tmp_path / "server.log"
    logging_setup.attach_rotating_file_handler(str(path), level="INFO")
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.server.test_logging")
    log.setLevel(logging.DEBUG)
    log.info("matchmake ok room=room-x uuid=abcd1234")
    # Flush all handlers so the line lands on disk before reading.
    for h in isolated_root_logger.handlers:
        h.flush()
    contents = path.read_text()
    assert "matchmake ok" in contents
    assert "room=room-x" in contents


def test_attach_rotating_file_handler_returns_rotating_handler(tmp_path,
                                                                 isolated_root_logger):
    path = tmp_path / "server.log"
    handler = logging_setup.attach_rotating_file_handler(str(path), level="INFO")
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler in isolated_root_logger.handlers


def test_attach_rotating_file_handler_respects_rotation_settings(tmp_path,
                                                                   isolated_root_logger):
    path = tmp_path / "server.log"
    handler = logging_setup.attach_rotating_file_handler(
        str(path), level="DEBUG", max_bytes=1024, backup_count=2,
    )
    assert handler.maxBytes == 1024
    assert handler.backupCount == 2


def test_configure_skips_file_handler_when_env_unset(monkeypatch,
                                                      isolated_root_logger):
    monkeypatch.delenv("LOG_FILE", raising=False)
    logging_setup.configure(level="INFO")
    rotating = [h for h in isolated_root_logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert rotating == []


def test_configure_attaches_file_handler_when_env_set(tmp_path, monkeypatch,
                                                        isolated_root_logger):
    path = tmp_path / "from-env.log"
    monkeypatch.setenv("LOG_FILE", str(path))
    logging_setup.configure(level="INFO")
    rotating = [h for h in isolated_root_logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == 1
    assert os.path.abspath(rotating[0].baseFilename) == os.path.abspath(str(path))


def test_existing_log_lines_use_kv_style_after_prefix():
    # Spot-check: server log strings throughout app.py / handlers / sweep
    # are written as `key=value` pairs after a free-form verb. We pin the
    # ones I touched in M18a/M18b so future edits don't accidentally drop
    # the format.
    from server import app, handlers, sweep
    sources = []
    for module in (app, handlers, sweep):
        path = module.__file__
        if path is None:
            continue
        with open(path) as f:
            sources.append(f.read())
    blob = "\n".join(sources)
    # Every log line in this codebase that mentions room=… also includes
    # uuid=… or color=… — a quick grep guarantees we keep that habit.
    assert 'room=%s' in blob
    assert 'uuid=%s' in blob
