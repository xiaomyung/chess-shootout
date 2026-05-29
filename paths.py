import os
import sys
from pathlib import Path

import platformdirs


appname = "chess-pygame"
appauthor = False


def is_frozen():
    return getattr(sys, "frozen", False)


def get_asset_base():
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent.resolve()


def resource_path(*parts):
    return get_asset_base().joinpath(*parts)


def _source_root():
    return Path(__file__).parent.resolve()


def get_app_dir():
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(appimage).resolve().parent
    if is_frozen():
        executable = Path(sys.executable).resolve()
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent.parent
        return executable.parent
    return _source_root()


def is_portable():
    return (get_app_dir() / "portable.txt").exists()


def _portable_dir():
    return get_app_dir() / "data"


def _default_config_dir():
    if is_frozen():
        return Path(platformdirs.user_config_dir(appname, appauthor))
    return _source_root()


def _default_data_dir():
    if is_frozen():
        return Path(platformdirs.user_data_dir(appname, appauthor))
    return _source_root()


def _default_log_dir():
    if is_frozen():
        return Path(platformdirs.user_log_dir(appname, appauthor))
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


def get_log_dir():
    if is_portable():
        return _portable_dir()
    return _default_log_dir()


def get_games_dir():
    return get_data_dir() / "games"
