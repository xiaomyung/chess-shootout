import os

from chessshootout.infra.open_external import open_with_default_app


def open_pgn_or_toast(toast, path):
    if path is None or not os.path.exists(path):
        toast.show("No saved PGN")
        return
    if not open_with_default_app(path):
        toast.show("Could not open PGN")
