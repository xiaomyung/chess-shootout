import os
import sys
from pathlib import Path

import platformdirs


APP_NAME = "chess-shootout"
APP_AUTHOR = False
GAMES_SUBDIR = "games"


def is_frozen():
    return getattr(sys, "frozen", False)


def _repo_root():
    return Path(__file__).parent.parent.resolve()


def get_asset_base():
    if is_frozen():
        return Path(sys._MEIPASS)
    return _repo_root()


def resource_path(*parts):
    return get_asset_base().joinpath(*parts)


PROJECT_ROOT = get_asset_base()
SOUNDS_DIR = resource_path("assets", "sounds")
PIECES_PNG_DIR = resource_path("assets", "pieces_png")


def get_app_version():
    try:
        return resource_path("assets", "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _source_root():
    return _repo_root()


def _exe_dir():
    return Path(sys.executable).resolve().parent


def _is_onefile():
    meipass = Path(getattr(sys, "_MEIPASS", "")).resolve()
    return not meipass.is_relative_to(_exe_dir())


def is_portable():
    return is_frozen() and _is_onefile()


def _portable_dir():
    return _exe_dir() / "data"


def _default_config_dir():
    if is_frozen():
        return Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
    return _source_root()


def _default_data_dir():
    if is_frozen():
        return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    return _source_root()


def _default_log_dir():
    if is_frozen():
        return Path(platformdirs.user_log_dir(APP_NAME, APP_AUTHOR))
    return _source_root()


def get_config_dir():
    if is_portable():
        return _portable_dir()
    return _default_config_dir()


def get_data_dir():
    if is_portable():
        return _portable_dir()
    override = os.environ.get("CHESS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _default_data_dir()


def get_default_data_dir():
    if is_portable():
        return _portable_dir()
    return _default_data_dir()


def get_fallback_data_dir():
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def get_log_dir():
    if is_portable():
        return _portable_dir()
    return _default_log_dir()


def get_games_dir():
    return get_data_dir() / GAMES_SUBDIR


def is_writable_dir(directory):
    directory = str(directory) if directory else ""
    if not directory or not os.path.isdir(directory) or not os.access(directory, os.W_OK):
        return False
    probe = os.path.join(directory, ".chess_write_test")
    try:
        with open(probe, "w", encoding="utf-8"):
            pass
        os.remove(probe)
    except OSError:
        return False
    return True
