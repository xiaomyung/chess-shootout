"""Structured logging surface: RotatingFileHandler wiring + KV log format.

Existing log lines already follow `key=value` after a free-form verb prefix
(e.g. `move applied room=… mover=… san=…`). This file pins that the rotating
handler honours the documented path/rotation policy and that the codebase
keeps emitting `room=…`/`uuid=…` pairs.
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


def test_attach_rotating_file_handler_rotates_and_caps_backups(tmp_path,
                                                                isolated_root_logger):
    """Real rotation: file rolls at max_bytes and never keeps more than
    backup_count backups (no .{backup_count + 1})."""
    path = tmp_path / "server.log"
    max_bytes, backup_count = 200, 2
    handler = logging_setup.attach_rotating_file_handler(
        str(path), level="DEBUG", max_bytes=max_bytes, backup_count=backup_count,
    )
    isolated_root_logger.setLevel(logging.DEBUG)
    log = logging.getLogger("chess.server.rotation")
    log.setLevel(logging.DEBUG)
    for i in range(40):
        log.debug("line %02d room=r-%02d uuid=u-%02d padding=xxxxxxxxxxxxxxxxxxxx",
                  i, i, i)
    handler.flush()

    assert path.exists()
    assert (tmp_path / "server.log.1").exists()
    assert (tmp_path / "server.log.2").exists()
    assert not (tmp_path / "server.log.3").exists()

    rolled = list(tmp_path.iterdir())
    assert len(rolled) == backup_count + 1
    for f in rolled:
        assert f.stat().st_size <= max_bytes


@pytest.mark.parametrize(
    "level, max_bytes, backup_count, expected_level",
    [
        pytest.param("INFO", 1024, 2, logging.INFO, id="info_string_level"),
        pytest.param("DEBUG", 4096, 5, logging.DEBUG, id="debug_string_level"),
        pytest.param(logging.WARNING, 512, 0, logging.WARNING, id="int_level_zero_backups"),
    ],
)
def test_attach_rotating_file_handler_applies_config(tmp_path, isolated_root_logger,
                                                     level, max_bytes, backup_count,
                                                     expected_level):
    path = tmp_path / "server.log"
    handler = logging_setup.attach_rotating_file_handler(
        str(path), level=level, max_bytes=max_bytes, backup_count=backup_count,
    )
    assert handler.maxBytes == max_bytes
    assert handler.backupCount == backup_count
    assert handler.level == expected_level
    assert os.path.abspath(handler.baseFilename) == os.path.abspath(str(path))


@pytest.mark.parametrize(
    "set_env, expected_count",
    [
        pytest.param(False, 0, id="env_unset_skips_file_handler"),
        pytest.param(True, 1, id="env_set_attaches_file_handler"),
    ],
)
def test_configure_file_handler_follows_log_file_env(tmp_path, monkeypatch,
                                                     isolated_root_logger,
                                                     set_env, expected_count):
    path = tmp_path / "from-env.log"
    if set_env:
        monkeypatch.setenv("LOG_FILE", str(path))
    else:
        monkeypatch.delenv("LOG_FILE", raising=False)
    logging_setup.configure(level="INFO")
    rotating = [h for h in isolated_root_logger.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == expected_count
    if expected_count:
        assert os.path.abspath(rotating[0].baseFilename) == os.path.abspath(str(path))


def test_existing_log_lines_use_kv_style_after_prefix():
    """Pin that app/handlers/sweep log lines keep `room=%s` + `uuid=%s` KV pairs."""
    from server import app, handlers, sweep
    sources = []
    for module in (app, handlers, sweep):
        path = module.__file__
        if path is None:
            continue
        with open(path) as f:
            sources.append(f.read())
    blob = "\n".join(sources)
    assert "room=%s" in blob
    assert "uuid=%s" in blob
