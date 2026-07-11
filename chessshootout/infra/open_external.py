import logging
import os
import shutil
import subprocess
import sys


log = logging.getLogger("chess.infra")


def open_with_default_app(path):
    if sys.platform == "darwin":
        candidates = [["open", path]]
    elif sys.platform.startswith("win"):
        try:
            os.startfile(path)
            return True
        except OSError:
            log.warning("os.startfile failed path=%s", path)
            return False
    else:
        candidates = [
            ["xdg-open", path],
            ["gio", "open", path],
        ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.debug("opened externally via %s path=%s", cmd[0], path)
            return True
        except OSError:
            continue
    log.warning("no external opener available path=%s", path)
    return False
