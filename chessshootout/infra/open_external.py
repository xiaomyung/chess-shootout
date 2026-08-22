import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from chessshootout import paths


log = logging.getLogger("chess.infra")


OPEN_WAIT_TIMEOUT_S = 8.0
FOREGROUND_HANDLER_MIN_S = 1.5
NO_HANDLER_EXIT_CODES = (1,) if sys.platform == "darwin" else (3, 4)

_LIBRARY_PATH_KEYS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LIBPATH")
_BOOTLOADER_KEYS = ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE",
                    "_PYI_PARENT_PROCESS_LEVEL")
_BUNDLE_SCOPED_KEYS = ("SSL_CERT_FILE", "SSL_CERT_DIR", "PYTHONPATH", "PYTHONHOME",
                       "GDK_PIXBUF_MODULE_FILE", "GI_TYPELIB_PATH", "QT_PLUGIN_PATH")


def child_env() -> dict[str, str] | None:
    """
    Build the environment a helper program should be started with, undoing the
    surgery a packaged build performs on its own process. A frozen run prepends
    the bundle to the library search paths and points the TLS variables at the
    bundled certificates; a file handler that inherited either would load our
    libraries or our CA bundle and die quietly, so those keys are restored from
    their saved originals or removed outright

    :returns: the cleaned environment to hand a child process, or None from a
        source run, where the process environment is already clean
    """
    if not paths.is_frozen():
        return None
    child = dict(os.environ)
    for key in _LIBRARY_PATH_KEYS:
        original = child.pop(key + "_ORIG", None)
        if original:
            child[key] = original
        else:
            child.pop(key, None)
    for key in _BOOTLOADER_KEYS:
        child.pop(key, None)
    bundle_root = str(paths.get_asset_base())
    bundle_prefix = os.path.join(bundle_root, "")
    for key in _BUNDLE_SCOPED_KEYS:
        value = child.get(key)
        if value and (value == bundle_root or value.startswith(bundle_prefix)):
            del child[key]
    return child


def open_with_default_app(path: str, on_failure: Callable[[int], None] | None = None) -> bool:
    """
    Hand a saved PGN or a link to whatever the player's system opens it with --
    this is the whole of Open PGN and of the menu's outbound links. Starting the
    opener is not proof it worked, so on platforms with a real child process an
    exit watcher keeps observing it and reports a late failure back

    :param path: file path or URL to open, exactly as the system opener wants it
    :param on_failure: called from a watcher thread with the opener's exit code
        when it starts but then fails; None asks for no follow-up at all
    :returns: True once an opener was started, False when none could be
    """
    if sys.platform.startswith("win"):
        try:
            os.startfile(path)
            return True
        except OSError:
            log.warning("os.startfile failed path=%s", path)
            return False
    candidates = ([["open", path]] if sys.platform == "darwin"
                  else [["xdg-open", path], ["gio", "open", path]])
    available = [cmd for cmd in candidates if shutil.which(cmd[0]) is not None]
    if not available:
        log.warning("no external opener available path=%s", path)
        return False
    if _launch(available, path, on_failure):
        return True
    log.warning("every external opener failed to start path=%s", path)
    return False


def _launch(candidates: list[list[str]], path: str,
            on_failure: Callable[[int], None] | None) -> bool:
    """
    Try each opener command in turn until one actually starts, detaching it
    from the game so quitting never kills the player's editor. When a follow-up
    is wanted, a daemon watcher thread is started for that child and is handed
    the openers that were not tried, so it can fall through to them later

    :param candidates: opener commands to try in order, each an argv list
    :param path: file path or URL, already the last argument of every command
    :param on_failure: reported to when the started opener turns out to fail,
        and the trigger for starting the watcher at all
    :returns: True once one command started, False when every one refused to
    """
    env = child_env()
    for index, cmd in enumerate(candidates):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        except OSError:
            continue
        log.debug("opened externally via %s path=%s", cmd[0], path)
        if on_failure is not None:
            threading.Thread(
                target=_watch, daemon=True,
                args=(proc, cmd[0], candidates[index + 1:], path, on_failure),
            ).start()
        return True
    return False


def _watch(proc: subprocess.Popen[bytes], tool: str, remaining: list[list[str]], path: str,
           on_failure: Callable[[int], None]) -> None:
    """
    Watch a started opener from its own daemon thread and turn a bad exit into
    something the player is told about, which is the whole point: on a machine
    where nothing claims .pgn the opener starts happily and then exits, and the
    game used to show nothing at all. A child still alive after the wait is
    treated as a success and reaped in the background

    :param proc: the opener process that was started
    :param tool: its command name, used only for the log line
    :param remaining: openers not tried yet, one of which may be run instead
    :param path: file path or URL being opened, carried into a retry
    :param on_failure: told the exit code once a failure is final
    """
    started = time.monotonic()
    try:
        code = proc.wait(timeout=OPEN_WAIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _reap(proc)
        return
    if code == 0:
        return
    log.warning("external opener %s exited %s path=%s", tool, code, path)
    if (_is_retriable(code, time.monotonic() - started) and remaining
            and _launch(remaining, path, on_failure)):
        return
    on_failure(code)


def _is_retriable(code: int, elapsed: float) -> bool:
    """
    Decide whether a failed opener is worth replacing with the next one. The
    test is deliberately narrow: an opener may run the real handler in the
    foreground and pass its exit status back, so a player who opened a PGN,
    edited it and closed it badly must not have the file reopened behind them.
    Only a child that died too fast to have been used, or one carrying the
    known no-handler codes, earns a retry

    :param code: exit status the opener returned
    :param elapsed: seconds the child was alive, measured from its start
    :returns: True when the next opener in the list should be tried
    """
    return elapsed < FOREGROUND_HANDLER_MIN_S or code in NO_HANDLER_EXIT_CODES


def _reap(proc: subprocess.Popen[bytes]) -> None:
    """
    Block on a still-running opener until it finally exits, so a long-lived
    child leaves no zombie behind. It runs on the watcher thread that already
    gave up on the child, and its exit status is deliberately ignored

    :param proc: the opener process that outlived the watcher's wait
    """
    try:
        proc.wait()
    except OSError:
        pass
