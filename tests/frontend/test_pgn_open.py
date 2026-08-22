"""PgnOpener, the shell service behind every "Open PGN" button.

Three silent paths made the user-visible bug ("nothing happens"):

1. a 0-byte file — result_flow reserves the filename with open(candidate, "x")
   before writing, so a failed write leaves a stub that passes os.path.exists,
   sniffs as application/x-zerosize, and makes xdg-open exit 3;
2. an opener that launches fine and then exits non-zero because no app claims
   .pgn — reported asynchronously, so it can only reach the player through the
   failure queue drained on the UI thread;
3. two consecutive failures inside the toast dedupe window — Toast.show
   refreshes a bubble with the same key WITHOUT firing on_new, so the second
   click produced no chirp and no visible retrigger. PgnOpener dismisses the
   key first; Toast itself must stay untouched (the resync toast re-shows every
   frame and depends on the silent refresh).

The four messages are deliberately distinct: nothing was ever written vs. the
file went missing vs. we could not launch anything vs. the system has no app
for .pgn.
"""

import contextlib
import logging
import os

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend import pgn_open
from chessshootout.frontend.pgn_open import (
    MISSING_MESSAGE, NO_HANDLER_MESSAGE, NO_MOVES_MESSAGE, OPEN_FAILED_MESSAGE,
    OPEN_PGN_TOAST_KEY, PgnOpener,
)
from chessshootout.frontend.visual.toast import Toast


_pygame_init = pygame_display(800, 600)


class _Harness:

    def __init__(self, monkeypatch, launched=True):
        self.calls = []
        self.launched = launched
        self.chirps = []
        self.toast = Toast(pg.display.get_surface())
        self.toast.on_new = lambda: self.chirps.append(1)
        self.opener = PgnOpener(self.toast)
        monkeypatch.setattr(pgn_open, "open_with_default_app", self._open)

    def _open(self, path, on_failure=None):
        self.calls.append({"path": path, "on_failure": on_failure})
        return self.launched

    def fail_async(self, code=3):
        self.calls[-1]["on_failure"](code)

    @property
    def paths(self):
        return [call["path"] for call in self.calls]

    @property
    def message(self):
        return self.toast.message


def _pgn(tmp_path, name="game.pgn", text='[Result "1-0"]\n\n1. e4 e5 1-0\n'):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class _Records(logging.Handler):

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def caplog_at_debug():
    """Collect every chess.frontend record emitted inside the block.

    pytest's caplog fixture is deliberately not used here: several of these
    assertions need the collected list to be empty, and caplog attaches to the
    root logger for the whole test, so records from unrelated setup would leak
    into it.
    """
    handler = _Records()
    logger = logging.getLogger("chess.frontend")
    saved_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved_level)


def test_a_none_path_toasts_no_moves_to_save_and_never_launches(monkeypatch):
    harness = _Harness(monkeypatch)

    assert harness.opener.open(None) is False
    assert harness.message == NO_MOVES_MESSAGE
    assert harness.calls == []


def test_a_missing_path_toasts_that_the_file_is_gone_and_never_launches(
        monkeypatch, tmp_path):
    harness = _Harness(monkeypatch)
    path = _pgn(tmp_path)
    os.remove(path)

    assert harness.opener.open(path) is False
    assert harness.message == MISSING_MESSAGE
    assert harness.calls == []


def test_a_zero_byte_pgn_toasts_no_moves_to_save_and_never_launches(monkeypatch, tmp_path):
    """The reserved stub left behind by a failed write: it exists, so the old
    exists()-only guard handed it straight to the OS."""
    harness = _Harness(monkeypatch)
    stub = _pgn(tmp_path, "reserved.pgn", text="")

    assert os.path.exists(stub) is True
    assert harness.opener.open(stub) is False
    assert harness.message == NO_MOVES_MESSAGE
    assert harness.calls == []


def test_a_stat_error_is_treated_as_a_missing_file(monkeypatch, tmp_path):
    """pgn_open.os.path IS the process-wide os.path module, so the fake must
    stay scoped: it raises only for this test's file and delegates everything
    else, or unrelated code sharing the interpreter starts failing stats."""
    harness = _Harness(monkeypatch)
    path = _pgn(tmp_path)
    real_getsize = os.path.getsize

    def boom(target):
        if os.fspath(target) == path:
            raise OSError("permission denied")
        return real_getsize(target)

    monkeypatch.setattr(pgn_open.os.path, "getsize", boom)

    assert harness.opener.open(path) is False
    assert harness.message == MISSING_MESSAGE
    assert harness.calls == []


def test_a_launch_failure_toasts_immediately(monkeypatch, tmp_path):
    harness = _Harness(monkeypatch, launched=False)
    path = _pgn(tmp_path)

    assert harness.opener.open(path) is False
    assert harness.paths == [path]
    assert harness.message == OPEN_FAILED_MESSAGE


def test_an_async_opener_failure_toasts_only_on_the_next_update(monkeypatch, tmp_path):
    harness = _Harness(monkeypatch)
    path = _pgn(tmp_path)

    assert harness.opener.open(path) is True
    assert harness.message is None, "a launch that succeeded says nothing"

    harness.fail_async(3)
    assert harness.message is None, "the watcher thread never touches the toast itself"

    harness.opener.update()
    assert harness.message == NO_HANDLER_MESSAGE


def test_a_generic_async_exit_toasts_could_not_open_not_no_handler(monkeypatch, tmp_path):
    """xdg-open exits 3/4 when no app claims the type; any other code means an
    opener existed and failed, so blaming a missing handler would misdirect the
    player. The message follows NO_HANDLER_EXIT_CODES."""
    harness = _Harness(monkeypatch)
    assert harness.opener.open(_pgn(tmp_path)) is True

    harness.fail_async(1)
    harness.opener.update()
    assert harness.message == OPEN_FAILED_MESSAGE


def test_update_is_silent_and_logs_nothing_when_nothing_failed(monkeypatch, tmp_path):
    harness = _Harness(monkeypatch)
    assert harness.opener.open(_pgn(tmp_path)) is True

    with caplog_at_debug() as records:
        for _ in range(120):
            harness.opener.update()

    assert records == []
    assert harness.toast.is_visible() is False


def test_a_failed_open_logs_exactly_one_warning(monkeypatch, tmp_path):
    harness = _Harness(monkeypatch)
    harness.opener.open(_pgn(tmp_path))
    harness.fail_async(3)

    with caplog_at_debug() as records:
        for _ in range(10):
            harness.opener.update()

    assert [r.getMessage() for r in records] == ["open pgn failed exit=3"]
    assert records[0].levelno == logging.WARNING


def test_a_burst_of_queued_failures_collapses_to_one_toast(monkeypatch, tmp_path):
    """One message for the player, every exit code in the log: the drops used
    to be thrown away silently, so a crash report showed a single failure where
    three different openers had died, and the two later codes -- the ones that
    say which opener it was -- were gone."""
    harness = _Harness(monkeypatch)
    path = _pgn(tmp_path)
    for code in (3, 1, 4):
        harness.opener.open(path)
        harness.fail_async(code)

    with caplog_at_debug() as records:
        harness.opener.update()

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == ["open pgn failed exit=3"], \
        "a multi-click burst must not spam the log with warnings"
    dropped = [r.getMessage() for r in records if r.levelno == logging.DEBUG]
    assert dropped == ["open pgn failed exit=1, not shown again this frame",
                       "open pgn failed exit=4, not shown again this frame"], \
        "the failures that never reached the toast keep their own exit codes"
    assert harness.chirps == [1], "nor chirp three times"
    assert harness.message == NO_HANDLER_MESSAGE

    harness.opener.update()
    assert harness.chirps == [1], "and the queue is drained, not replayed"


def test_the_failure_toast_rechirps_on_a_second_consecutive_failure(monkeypatch, tmp_path):
    """Two failed opens inside the ~3.3 s dedupe window: the second must be
    audible and visible, or "nothing happened" happens twice."""
    harness = _Harness(monkeypatch)
    path = _pgn(tmp_path)

    harness.opener.open(path)
    harness.fail_async(3)
    harness.opener.update()
    harness.opener.open(path)
    harness.fail_async(3)
    harness.opener.update()

    assert harness.chirps == [1, 1]
    assert harness.message == NO_HANDLER_MESSAGE

    harness.toast.show(NO_HANDLER_MESSAGE, key=OPEN_PGN_TOAST_KEY)
    assert harness.chirps == [1, 1], "a bare re-show is the silent refresh being worked around"
