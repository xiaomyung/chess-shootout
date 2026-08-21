import os
import sys
from pathlib import Path

import platformdirs


APP_NAME = "chess-shootout"
APP_AUTHOR = False
GAMES_SUBDIR = "games"


def is_frozen() -> bool:
    """
    Tell whether the game is running from a packaged build instead of from the
    source tree. It is the first switch in every path decision here, because a
    bundle keeps its assets and its user data in different places

    :returns: True when running inside a packaged bundle
    """
    return getattr(sys, "frozen", False)


def _repo_root() -> Path:
    """
    Locate the checkout root, which doubles as both the asset base and the
    writable directory when the game runs from source

    :returns: absolute path to the directory that contains the package
    """
    return Path(__file__).parent.parent.resolve()


def get_asset_base() -> Path:
    """
    Give the directory the bundled read-only assets sit under: the unpacked
    bundle in a packaged build, the checkout when running from source

    :returns: absolute path that every asset lookup is resolved against
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    return _repo_root()


def resource_path(*parts: str) -> Path:
    """
    Build the path to a bundled asset. Every sound, image, font and data file
    is reached through here, which is what makes a source run and a packaged
    run resolve the same names

    :param parts: path segments below the asset base, outermost first
    :returns: absolute path to the asset; existence is not checked
    """
    return get_asset_base().joinpath(*parts)


SOUNDS_DIR = resource_path("assets", "sounds")
PIECES_PNG_DIR = resource_path("assets", "pieces_png")


def get_app_version() -> str:
    """
    Read the display version stamped into the bundle at build time. A source
    checkout has no such file, and the empty answer is what makes the menu
    footer show a dev build instead of a version number

    :returns: version string, or empty when there is none to read
    """
    try:
        return resource_path("assets", "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _exe_dir() -> Path:
    """
    Locate the folder the running executable sits in, which is where a
    portable build keeps its data alongside the exe

    :returns: absolute path to the executable's own directory
    """
    return Path(sys.executable).resolve().parent


def _is_onefile() -> bool:
    """
    Tell a single-file build apart from a folder build by checking whether the
    unpacked bundle lives outside the executable's own directory

    :returns: True when the bundle was unpacked to a temporary directory
    """
    meipass = Path(getattr(sys, "_MEIPASS", "")).resolve()
    return not meipass.is_relative_to(_exe_dir())


def is_portable() -> bool:
    """
    Tell whether this is the portable Windows build, the one that keeps its
    settings, saved games and logs in a data folder next to the exe and leaves
    nothing on the host machine. Portable means frozen AND win32 AND onefile

    :returns: True when everything must be written beside the executable
    """
    return is_frozen() and sys.platform == "win32" and _is_onefile()


def _portable_dir() -> Path:
    """
    Give the single self-contained folder a portable build writes all of its
    settings, saved games and logs into

    :returns: the data folder beside the executable
    """
    return _exe_dir() / "data"


def _default_config_dir() -> Path:
    """
    Give the ordinary home for settings when the build is not portable: the
    per-user config location for an installed build, the checkout from source

    :returns: directory the settings file lives in
    """
    if is_frozen():
        return Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
    return _repo_root()


def _default_data_dir() -> Path:
    """
    Give the ordinary home for saved games and caches when the build is not
    portable: per-user data for an installed build, the checkout from source

    :returns: directory user data is written under
    """
    if is_frozen():
        return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    return _repo_root()


def _default_log_dir() -> Path:
    """
    Give the ordinary home for crash logs when the build is not portable:
    per-user logs for an installed build, the checkout from source

    :returns: directory the crash-log folder is created under
    """
    if is_frozen():
        return Path(platformdirs.user_log_dir(APP_NAME, APP_AUTHOR))
    return _repo_root()


def get_config_dir() -> Path:
    """
    Give the directory the settings file lives in. The portable folder beside
    the exe wins when there is one, otherwise the per-user or checkout default

    :returns: directory holding the stored settings
    """
    if is_portable():
        return _portable_dir()
    return _default_config_dir()


def get_data_dir() -> Path:
    """
    Give the directory user data is written to, which is what the data-folder
    option in the menu changes. Resolved in a fixed order: the portable folder
    beside the exe, then a CHESS_DATA_DIR override, then the normal default

    :returns: directory saved games and caches are written under
    """
    if is_portable():
        return _portable_dir()
    override = os.environ.get("CHESS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _default_data_dir()


def get_default_data_dir() -> Path:
    """
    Give the data directory the game would use with nothing overridden, which
    is what the options screen offers as the reset target for the data folder

    :returns: default data directory, ignoring any CHESS_DATA_DIR override
    """
    if is_portable():
        return _portable_dir()
    return _default_data_dir()


def get_fallback_data_dir() -> Path:
    """
    Give the per-user data directory that saving falls back to when the chosen
    folder turns out not to be writable, so a finished game is never lost

    :returns: the per-user data directory, whatever the current setting is
    """
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def get_log_dir() -> Path:
    """
    Give the directory crash logs are written under: the portable folder
    beside the exe when there is one, the per-user or checkout location
    otherwise

    :returns: directory the crash-log folder is created in
    """
    if is_portable():
        return _portable_dir()
    return _default_log_dir()


def get_games_dir() -> Path:
    """
    Give the folder saved PGN games live in, used both by the autosave that
    runs during a game and by the history list that reads them back

    :returns: the games subfolder of the current data directory
    """
    return get_data_dir() / GAMES_SUBDIR


def is_writable_dir(directory: str | Path | None) -> bool:
    """
    Check that a folder really accepts writes, by creating and deleting a
    probe file rather than trusting the permission bits. It gates the data
    folder a player types or picks, and the folder a finished game saves to

    :param directory: folder to test; empty or missing answers False
    :returns: True when a file could be created and removed in there
    """
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
