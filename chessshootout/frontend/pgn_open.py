import logging
import os
import queue

from chessshootout.infra.open_external import NO_HANDLER_EXIT_CODES, open_with_default_app
from chessshootout.frontend.visual.toast import Toast


log = logging.getLogger("chess.frontend")

OPEN_PGN_TOAST_KEY = "open_pgn"
NO_MOVES_MESSAGE = "No moves to save"
MISSING_MESSAGE = "PGN file is missing"
OPEN_FAILED_MESSAGE = "Could not open PGN"
NO_HANDLER_MESSAGE = "No app is set to open .pgn files"


class PgnOpener:
    """
    The shell service behind every Open PGN button -- the result card and the
    review screen both go through this one instance. It hands a saved game to
    whatever application the player's system opens .pgn files with, and turns
    the several ways that can quietly do nothing into a message they can read
    """

    def __init__(self, toast: Toast) -> None:
        """
        Build the opener on the app's toast bar, with an empty queue for the
        failures that only surface later, from a watcher thread rather than
        from the call that started the opener

        :param toast: the shell's toast bar, where every message is shown
        """
        self.toast = toast
        self._failures: queue.Queue[int] = queue.Queue()

    def open(self, path: str | None, empty_message: str = NO_MOVES_MESSAGE) -> bool:
        """
        Open a saved game in the player's own PGN application. Each way this
        can fail gets its own message rather than nothing visibly happening:
        no game was ever saved, the file has since gone missing, the file was
        reserved but never written, or no opener would start at all

        :param path: full path of the PGN to open, or None when nothing has
            been saved for this game yet
        :param empty_message: shown when there is no game to open, worded by
            the caller since a live game and a review mean different things
        :returns: True once an opener was started, False when a message was
            shown instead
        """
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

    def update(self) -> None:
        """
        Report openers that started happily and then failed, which is what a
        machine with no application for .pgn looks like. The failure arrives on
        a watcher thread, so this drain -- run once a frame by the shell -- is
        where it crosses onto the drawing thread; a burst of them is reported
        once, since the player only needs telling once
        """
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

    def _toast(self, message: str) -> None:
        """
        Show one message under the shared open-PGN key, taking whatever is
        already under that key away first. That dismissal is deliberate: a
        second failed click would otherwise silently refresh the bubble already
        on screen, with no chirp and no visible change to notice

        :param message: the line to show the player
        """
        self.toast.dismiss(OPEN_PGN_TOAST_KEY)
        self.toast.show(message, key=OPEN_PGN_TOAST_KEY)
