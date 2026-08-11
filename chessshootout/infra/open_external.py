import logging
import os
import shutil
import subprocess
import sys
import threading
import time

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


def child_env():
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


def open_with_default_app(path, on_failure=None):
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


def _launch(candidates, path, on_failure):
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


def _watch(proc, tool, remaining, path, on_failure):
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


def _is_retriable(code, elapsed):
    return elapsed < FOREGROUND_HANDLER_MIN_S or code in NO_HANDLER_EXIT_CODES


def _reap(proc):
    try:
        proc.wait()
    except OSError:
        pass
