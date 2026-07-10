"""Unified log format (v2.4.3): date+time+ms, fixed-width level, UTC everywhere,
and a uvicorn log_config that does NOT silence the app loggers.

The old format was time-only (`%H:%M:%S`) and uvicorn's own lines interleaved
with no timestamp. These pin the single shared format + the UtcFormatter
converter + the uvicorn config's `disable_existing_loggers: False` guarantee.
"""
import logging
import logging.config
import time

import pytest

from chessshootout.infra import log_format


@pytest.fixture
def clean_root():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_formatters = [h.formatter for h in saved_handlers]
    saved_level = root.level
    for h in list(root.handlers):
        root.removeHandler(h)
    yield root
    for h in list(root.handlers):
        root.removeHandler(h)
    for h, fmt in zip(saved_handlers, saved_formatters):
        h.setFormatter(fmt)
        root.addHandler(h)
    root.setLevel(saved_level)


def test_format_carries_date_time_ms_and_padded_level():
    assert "%(asctime)s.%(msecs)03d" in log_format.LOG_FORMAT
    assert "%(levelname)-8s" in log_format.LOG_FORMAT
    assert "%(name)s" in log_format.LOG_FORMAT
    assert log_format.LOG_DATEFMT == "%Y-%m-%d %H:%M:%S"


def test_utc_formatter_converter_is_gmtime():
    assert log_format.UtcFormatter.converter is time.gmtime


def test_make_formatter_renders_utc_ms_padded_level_exactly():
    fmt = log_format.make_formatter()
    record = logging.LogRecord(
        name="chess.server.app", level=logging.INFO, pathname=__file__, lineno=1,
        msg="matchmake ok room=%s", args=("r-1",), exc_info=None,
    )
    record.created = 1_600_000_000.0
    record.msecs = 789.0
    out = fmt.format(record)
    assert out == "2020-09-13 12:26:40.789 INFO     chess.server.app matchmake ok room=r-1"


def test_make_formatter_is_utc_not_local():
    """A DEBUG record at a fixed epoch renders the gmtime wall clock, independent
    of the host timezone (proves converter=gmtime, not localtime)."""
    fmt = log_format.make_formatter()
    record = logging.LogRecord(
        name="x", level=logging.DEBUG, pathname=__file__, lineno=1,
        msg="hi", args=(), exc_info=None,
    )
    record.created = 0.0
    record.msecs = 0.0
    assert fmt.format(record).startswith("1970-01-01 00:00:00.000 DEBUG   ")


def test_configure_basic_adds_utc_stream_handler_when_root_empty(monkeypatch):
    """The real startup case (root has no handlers): add exactly one StreamHandler
    with the UtcFormatter. Uses a fake root because pytest keeps its own capture
    handlers on the real root."""
    fake = logging.Logger("fake_root_empty")
    fake.handlers = []
    monkeypatch.setattr(log_format.logging, "getLogger", lambda *a, **k: fake)
    log_format.configure_basic("DEBUG")
    assert fake.level == logging.DEBUG
    assert len(fake.handlers) == 1
    assert isinstance(fake.handlers[0], logging.StreamHandler)
    assert isinstance(fake.handlers[0].formatter, log_format.UtcFormatter)


def test_configure_basic_is_noop_on_existing_handlers(monkeypatch):
    """Idempotent: if root already has a handler (e.g. pytest capture), a second
    configure only sets the level and does not add/replace handlers."""
    fake = logging.Logger("fake_root_nonempty")
    sentinel = logging.NullHandler()
    fake.handlers = [sentinel]
    monkeypatch.setattr(log_format.logging, "getLogger", lambda *a, **k: fake)
    log_format.configure_basic("WARNING")
    assert fake.handlers == [sentinel]
    assert fake.level == logging.WARNING


def test_uvicorn_log_config_keeps_app_loggers_alive():
    cfg = log_format.uvicorn_log_config()
    assert cfg["disable_existing_loggers"] is False
    assert cfg["formatters"]["chess"]["()"] == "chessshootout.infra.log_format.UtcFormatter"
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert name in cfg["loggers"]


def test_applying_uvicorn_config_does_not_disable_app_logger(clean_root):
    """dictConfig with disable_existing_loggers False must leave a pre-created
    app logger enabled (the silence-the-app-logs footgun)."""
    app_log = logging.getLogger("chess.server.app")
    app_log.setLevel(logging.INFO)
    logging.config.dictConfig(log_format.uvicorn_log_config())
    assert app_log.disabled is False
