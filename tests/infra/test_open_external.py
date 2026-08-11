"""open_external: platform branching, the which-gate, frozen-run environment
surgery, and outcome observation.

The reported Open-PGN bug was silent because the module only ever checked that
a *launch* succeeded: on a box where nothing claims `.pgn`, `xdg-open` starts
fine and then exits 3, so the old code returned True and the player saw
nothing. The watcher thread turns that exit code into a reported failure, and
falls through to the remaining candidate first (the old loop broke on the first
successful launch and never tried `gio` afterwards).

The env surgery is the frozen-build half: the PyInstaller bootloader prepends
sys._MEIPASS to LD_LIBRARY_PATH (stashing the caller's value in
LD_LIBRARY_PATH_ORIG) and main.py points SSL_CERT_FILE at the bundled certifi
file. A child xdg-open handler inheriting either loads our libraries or our CA
bundle and dies quietly. Source runs must stay byte-identical, i.e. Popen gets
no env= at all.

The retry chain is deliberately narrow. xdg-open's generic backend can run the
handler in the FOREGROUND and hand back the handler's own exit status, so a
player who opens a PGN, works in the editor and closes it with a non-zero
status would otherwise trigger a second `gio open` of the same file and see the
PGN reopen. Only a child that died too fast to have been used (under
FOREGROUND_HANDLER_MIN_S) or one that returned xdg-open's no-handler family
(NO_HANDLER_EXIT_CODES) falls through to the next opener.

No real process is ever launched here: subprocess.Popen, shutil.which,
threading.Thread and the module's clock are all faked. The fake thread runs the
watcher inline by default so the retry/report chain is deterministic;
`run_watcher=False` gives the inert variant used to pin what the caller sees
BEFORE the exit code is known.
"""

import logging
import os
import subprocess
import sys

from chessshootout.infra import open_external


_STILL_RUNNING = object()

BUNDLE_UNRELATED_KEY = "CHESS_OPENER_UNRELATED"


class _FakeProc:
    """A child whose scripted outcome is an exit code or _STILL_RUNNING.

    Every wait() is recorded: the bounded first one is the watcher's verdict,
    and an unbounded second one is the reap that keeps a resident opener from
    lingering as a zombie once the watcher stops caring about it.
    """

    def __init__(self, outcome):
        self._outcome = outcome
        self.wait_timeout = None
        self.wait_calls = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if timeout is None:
            return 0 if self._outcome is _STILL_RUNNING else self._outcome
        self.wait_timeout = timeout
        if self._outcome is _STILL_RUNNING:
            raise subprocess.TimeoutExpired(cmd="opener", timeout=timeout)
        return self._outcome


class _FakeThread:

    def __init__(self, target, args, daemon, run=True):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self._run = run

    def start(self):
        self.started = True
        if self._run:
            self.target(*self.args)


class _Clock:
    """Scripted stand-in for the module's `time`; the last reading repeats."""

    def __init__(self, readings):
        self._readings = list(readings)

    def monotonic(self):
        return self._readings.pop(0) if len(self._readings) > 1 else self._readings[0]


class _Launcher:
    """Records every Popen the module makes and scripts each child's exit.

    `outcomes` is consumed one entry per launch (an exit code, or
    _STILL_RUNNING to raise TimeoutExpired); anything unscripted exits 0.
    """

    def __init__(self, monkeypatch, tools=("xdg-open", "gio", "open"), outcomes=(),
                 missing_binaries=(), run_watcher=True):
        self.launches = []
        self.threads = []
        self._outcomes = list(outcomes)
        self._missing = set(missing_binaries)
        self._run_watcher = run_watcher
        monkeypatch.setattr(open_external.shutil, "which",
                            lambda name: "/usr/bin/" + name if name in tools else None)
        monkeypatch.setattr(open_external.subprocess, "Popen", self._popen)
        monkeypatch.setattr(open_external.threading, "Thread", self._thread)

    def _popen(self, cmd, **kwargs):
        if cmd[0] in self._missing:
            raise OSError("no such binary")
        proc = _FakeProc(self._outcomes.pop(0) if self._outcomes else 0)
        self.launches.append({"cmd": cmd, "env": kwargs.get("env"),
                              "kwargs": kwargs, "proc": proc})
        return proc

    def _thread(self, target=None, args=(), daemon=False):
        thread = _FakeThread(target, args, daemon, run=self._run_watcher)
        self.threads.append(thread)
        return thread

    @property
    def tools(self):
        return [launch["cmd"][0] for launch in self.launches]


def _platform(monkeypatch, name):
    monkeypatch.setattr(sys, "platform", name)


def _clock(monkeypatch, *readings):
    monkeypatch.setattr(open_external, "time", _Clock(readings))


def _warnings(caplog):
    return [record.getMessage() for record in caplog.records
            if record.name == "chess.infra" and record.levelno == logging.WARNING]


def _source_run(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)


def _frozen_run(monkeypatch, bundle):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)


def _child_env(monkeypatch, bundle):
    """The env dict a frozen run actually hands to the child process."""
    launcher = _Launcher(monkeypatch)
    _platform(monkeypatch, "linux")
    _frozen_run(monkeypatch, bundle)
    assert open_external.open_with_default_app("/games/x.pgn") is True
    return launcher.launches[0]["env"]


def test_darwin_uses_the_open_command(monkeypatch):
    launcher = _Launcher(monkeypatch)
    _platform(monkeypatch, "darwin")
    _source_run(monkeypatch)

    assert open_external.open_with_default_app("/games/x.pgn") is True
    assert [launch["cmd"] for launch in launcher.launches] == [["open", "/games/x.pgn"]]


def test_windows_uses_startfile_and_reports_its_oserror(monkeypatch):
    launcher = _Launcher(monkeypatch)
    _platform(monkeypatch, "win32")
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)

    assert open_external.open_with_default_app("C:\\games\\x.pgn") is True
    assert opened == ["C:\\games\\x.pgn"]

    def boom(_path):
        raise OSError("no association")

    monkeypatch.setattr(os, "startfile", boom, raising=False)
    assert open_external.open_with_default_app("C:\\games\\x.pgn") is False
    assert launcher.launches == [], "the windows branch never shells out"
    assert launcher.threads == [], "and never watches an exit code"


def test_linux_prefers_xdg_open_over_gio(monkeypatch):
    launcher = _Launcher(monkeypatch)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    assert open_external.open_with_default_app("/games/x.pgn") is True
    assert launcher.tools == ["xdg-open"]


def test_a_missing_opener_binary_is_skipped_by_the_which_gate(monkeypatch):
    launcher = _Launcher(monkeypatch, tools=("gio",))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    assert open_external.open_with_default_app("/games/x.pgn") is True
    assert [launch["cmd"] for launch in launcher.launches] == [["gio", "open",
                                                               "/games/x.pgn"]]


def test_no_opener_on_path_at_all_reports_failure(monkeypatch, caplog):
    launcher = _Launcher(monkeypatch, tools=())
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="chess.infra"):
        assert open_external.open_with_default_app("/games/x.pgn") is False

    assert launcher.launches == []
    assert len(_warnings(caplog)) == 1
    assert "no external opener available" in _warnings(caplog)[0]


def test_every_opener_failing_to_spawn_is_not_reported_as_none_being_installed(
        monkeypatch, caplog):
    """Both binaries exist and both Popen calls blow up: that is a different
    failure from an empty PATH, and it still gets exactly one warning."""
    launcher = _Launcher(monkeypatch, missing_binaries=("xdg-open", "gio"))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="chess.infra"):
        assert open_external.open_with_default_app("/games/x.pgn") is False

    assert launcher.launches == []
    assert len(_warnings(caplog)) == 1
    assert "no external opener available" not in _warnings(caplog)[0]
    assert "failed to start" in _warnings(caplog)[0]


def test_a_popen_oserror_falls_through_to_the_next_candidate(monkeypatch):
    launcher = _Launcher(monkeypatch, missing_binaries=("xdg-open",))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    assert open_external.open_with_default_app("/games/x.pgn") is True
    assert launcher.tools == ["gio"]


def test_source_runs_pass_no_explicit_environment_to_the_child(monkeypatch):
    launcher = _Launcher(monkeypatch)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/whatever/lib")

    assert open_external.open_with_default_app("/games/x.pgn") is True
    assert open_external.child_env() is None
    assert launcher.launches[0]["env"] is None, "a source run inherits os.environ as-is"


def test_frozen_runs_restore_the_saved_library_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path / "lib"))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib:/usr/local/lib")

    child = _child_env(monkeypatch, tmp_path)

    assert child["LD_LIBRARY_PATH"] == "/usr/lib:/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in child


def test_frozen_runs_drop_a_library_path_with_no_saved_original(monkeypatch, tmp_path):
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path / "lib"))
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    child = _child_env(monkeypatch, tmp_path)

    assert "LD_LIBRARY_PATH" not in child


def test_frozen_runs_drop_the_pyinstaller_bootloader_variables(monkeypatch, tmp_path):
    for key in open_external._BOOTLOADER_KEYS:
        monkeypatch.setenv(key, "bootloader")

    child = _child_env(monkeypatch, tmp_path)

    assert [key for key in open_external._BOOTLOADER_KEYS if key in child] == []


def test_frozen_runs_drop_an_ssl_cert_file_that_points_inside_the_bundle(
        monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "certifi" / "cacert.pem"))

    child = _child_env(monkeypatch, tmp_path)

    assert "SSL_CERT_FILE" not in child


def test_frozen_runs_keep_a_user_set_ssl_cert_file_outside_the_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")

    child = _child_env(monkeypatch, tmp_path)

    assert child["SSL_CERT_FILE"] == "/etc/ssl/certs/ca-certificates.crt"


def test_frozen_runs_keep_a_cert_path_in_a_sibling_that_merely_shares_the_prefix(
        monkeypatch, tmp_path):
    """An install at /opt/ChessShootout must not swallow /opt/ChessShootout-certs:
    a bare startswith() treats the sibling as "inside the bundle" and deletes a
    setting the user chose."""
    bundle = tmp_path / "ChessShootout"
    sibling = tmp_path / "ChessShootout-certs" / "ca.pem"
    monkeypatch.setenv("SSL_CERT_FILE", str(sibling))

    child = _child_env(monkeypatch, bundle)

    assert child["SSL_CERT_FILE"] == str(sibling)


def test_frozen_runs_drop_a_bundle_scoped_value_that_is_the_bundle_root_itself(
        monkeypatch, tmp_path):
    """The separator anchor must not lose the exact-match case: SSL_CERT_DIR
    pointed at the bundle root is still ours, not the user's."""
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))

    child = _child_env(monkeypatch, tmp_path)

    assert "SSL_CERT_DIR" not in child


def test_frozen_runs_leave_unrelated_variables_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv(BUNDLE_UNRELATED_KEY, "keep-me")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    child = _child_env(monkeypatch, tmp_path)

    assert child[BUNDLE_UNRELATED_KEY] == "keep-me"
    assert child["PATH"] == "/usr/bin:/bin"


def test_no_watcher_thread_is_started_without_a_failure_callback(monkeypatch):
    launcher = _Launcher(monkeypatch, outcomes=(3,))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    assert open_external.open_with_default_app("/games/x.pgn") is True
    assert launcher.threads == [], "the menu's open_url wiring must stay fire-and-forget"


def test_the_watcher_thread_is_a_daemon(monkeypatch):
    launcher = _Launcher(monkeypatch)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    open_external.open_with_default_app("/games/x.pgn", on_failure=lambda _code: None)

    assert len(launcher.threads) == 1
    assert launcher.threads[0].daemon is True
    assert launcher.threads[0].started is True


def test_a_zero_exit_reports_nothing(monkeypatch):
    _Launcher(monkeypatch, outcomes=(0,))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    assert open_external.open_with_default_app("/x.pgn", on_failure=failures.append) is True
    assert failures == []


def test_open_returns_true_before_the_watcher_knows_the_exit_code(monkeypatch):
    """The only test whose fake thread does NOT run its target: with the real
    threading.Thread the caller returns while the child is still running, so
    nothing may depend on the watcher having already finished."""
    launcher = _Launcher(monkeypatch, outcomes=(3,), run_watcher=False)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    assert open_external.open_with_default_app("/x.pgn", on_failure=failures.append) is True
    assert failures == [], "the exit code cannot have been observed yet"
    assert launcher.tools == ["xdg-open"], "and the retry has not happened either"
    assert len(launcher.threads) == 1
    assert launcher.threads[0].daemon is True
    assert launcher.threads[0].started is True


def test_an_opener_still_running_after_the_timeout_counts_as_success(monkeypatch):
    launcher = _Launcher(monkeypatch, outcomes=(_STILL_RUNNING,))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    assert open_external.open_with_default_app("/x.pgn", on_failure=failures.append) is True
    assert failures == [], "a resident opener is a success, not a failure"
    assert launcher.tools == ["xdg-open"], "and no retry either"
    assert launcher.launches[0]["proc"].wait_timeout == open_external.OPEN_WAIT_TIMEOUT_S


def test_a_resident_opener_is_reaped_after_the_timeout(monkeypatch):
    """Walking away from a timed-out child leaves it unreaped until interpreter
    cleanup (ResourceWarning, zombie entry); the watcher thread is a daemon and
    has nothing else to do, so it keeps waiting purely to collect the child."""
    launcher = _Launcher(monkeypatch, outcomes=(_STILL_RUNNING,))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    open_external.open_with_default_app("/x.pgn", on_failure=lambda _code: None)

    assert launcher.launches[0]["proc"].wait_calls == [open_external.OPEN_WAIT_TIMEOUT_S, None]


def test_a_non_zero_exit_retries_the_next_opener_before_reporting(monkeypatch):
    launcher = _Launcher(monkeypatch, outcomes=(3, 0))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    assert open_external.open_with_default_app("/x.pgn", on_failure=failures.append) is True
    assert launcher.tools == ["xdg-open", "gio"]
    assert failures == [], "gio handled it, so nothing is reported to the player"


def test_a_non_zero_exit_with_no_candidates_left_reports_the_exit_code(monkeypatch):
    launcher = _Launcher(monkeypatch, tools=("gio",), outcomes=(3,))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    assert open_external.open_with_default_app("/x.pgn", on_failure=failures.append) is True
    assert launcher.tools == ["gio"]
    assert failures == [3]


def test_an_exhausted_candidate_chain_reports_exactly_once(monkeypatch):
    launcher = _Launcher(monkeypatch, outcomes=(3, 4))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    open_external.open_with_default_app("/x.pgn", on_failure=failures.append)

    assert launcher.tools == ["xdg-open", "gio"]
    assert failures == [4], "one report for the whole chain, from the last opener tried"


def test_a_retry_whose_spawn_fails_adds_no_second_warning(monkeypatch, caplog):
    """The watcher already warned about the exit it saw; the retry blowing up
    inside Popen is the same user-visible failure, and it is emphatically not
    "no external opener available" — both binaries were there."""
    launcher = _Launcher(monkeypatch, outcomes=(3,), missing_binaries=("gio",))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    with caplog.at_level(logging.WARNING, logger="chess.infra"):
        open_external.open_with_default_app("/x.pgn", on_failure=failures.append)

    assert launcher.tools == ["xdg-open"]
    assert failures == [3]
    assert len(_warnings(caplog)) == 1
    assert "exited 3" in _warnings(caplog)[0]


def test_a_slow_generic_failure_is_reported_without_reopening_the_file(monkeypatch):
    """xdg-open's generic backend can run the handler in the foreground and
    return the handler's own status, so a player who opened the PGN and closed
    the editor non-zero must not have it reopened by gio."""
    launcher = _Launcher(monkeypatch, outcomes=(1,))
    _clock(monkeypatch, 0.0, open_external.FOREGROUND_HANDLER_MIN_S + 6.0)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    open_external.open_with_default_app("/x.pgn", on_failure=failures.append)

    assert launcher.tools == ["xdg-open"], "the file must be opened exactly once"
    assert failures == [1]


def test_a_fast_generic_failure_still_falls_through_to_the_next_opener(monkeypatch):
    """Nobody read a PGN in a fifth of a second: that child never showed the
    player anything, so trying gio costs nothing."""
    launcher = _Launcher(monkeypatch, outcomes=(1, 0))
    _clock(monkeypatch, 0.0, 0.2)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    open_external.open_with_default_app("/x.pgn", on_failure=failures.append)

    assert launcher.tools == ["xdg-open", "gio"]
    assert failures == []


def test_a_slow_no_handler_exit_still_falls_through_to_the_next_opener(monkeypatch):
    """The other half of the gate: a no-handler exit code is conclusive however
    long the child sat around."""
    launcher = _Launcher(monkeypatch, outcomes=(open_external.NO_HANDLER_EXIT_CODES[0], 0))
    _clock(monkeypatch, 0.0, open_external.FOREGROUND_HANDLER_MIN_S + 60.0)
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)
    failures = []

    open_external.open_with_default_app("/x.pgn", on_failure=failures.append)

    assert launcher.tools == ["xdg-open", "gio"]
    assert failures == []


def test_a_non_zero_exit_logs_one_warning_naming_the_tool_and_code(monkeypatch, caplog):
    _Launcher(monkeypatch, tools=("xdg-open",), outcomes=(3,))
    _platform(monkeypatch, "linux")
    _source_run(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="chess.infra"):
        open_external.open_with_default_app("/games/x.pgn", on_failure=lambda _code: None)

    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("external opener")]
    assert len(lines) == 1
    assert "xdg-open" in lines[0]
    assert "3" in lines[0]
