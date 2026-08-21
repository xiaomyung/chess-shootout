import logging
import os
import queue

from chessshootout.infra.open_external import NO_HANDLER_EXIT_CODES, open_with_default_app


log = logging.getLogger("chess.frontend")

OPEN_PGN_TOAST_KEY = "open_pgn"
NO_MOVES_MESSAGE = "No moves to save"
MISSING_MESSAGE = "PGN file is missing"
OPEN_FAILED_MESSAGE = "Could not open PGN"
NO_HANDLER_MESSAGE = "No app is set to open .pgn files"


class PgnOpener:

    def __init__(self, toast):
        self.toast = toast
        self._failures = queue.Queue()

    def open(self, path, empty_message=NO_MOVES_MESSAGE):
        if path is None:
            self._toast(empty_message)
            return False
        try:
            size = os.path.getsize(path)
        except OSError:
            self._toast(MISSING_MESSAGE)
            return False
        if size == 0:
            self._toast(empty_message)
            return False
        if not open_with_default_app(path, on_failure=self._failures.put):
            self._toast(OPEN_FAILED_MESSAGE)
            return False
        return True

    def update(self):
        reported = False
        while True:
            try:
                code = self._failures.get_nowait()
            except queue.Empty:
                break
            if reported:
                continue
            reported = True
            log.warning("open pgn failed exit=%s", code)
            self._toast(NO_HANDLER_MESSAGE if code in NO_HANDLER_EXIT_CODES
                        else OPEN_FAILED_MESSAGE)

    def _toast(self, message):
        self.toast.dismiss(OPEN_PGN_TOAST_KEY)
        self.toast.show(message, key=OPEN_PGN_TOAST_KEY)
