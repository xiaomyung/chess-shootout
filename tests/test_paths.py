import sys
from pathlib import Path

import paths


def test_source_mode_defaults(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("CHESS_DATA_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    root = paths._source_root()
    assert paths.get_asset_base() == root
    assert paths.get_config_dir() == root
    assert paths.get_data_dir() == root
    assert paths.get_log_dir() == root
    assert paths.get_games_dir() == root / "games"


def test_resource_path_joins_under_asset_base(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    expected = paths._source_root() / "assets" / "fonts" / "x.ttf"
    assert paths.resource_path("assets", "fonts", "x.ttf") == expected


def test_app_version_reads_bundled_file(monkeypatch, tmp_path):
    version_file = tmp_path / "version.txt"
    version_file.write_text("1.2.3\n")
    monkeypatch.setattr(paths, "resource_path", lambda *parts: version_file)
    assert paths.get_app_version() == "1.2.3"


def test_app_version_blank_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "resource_path", lambda *parts: tmp_path / "absent.txt")
    assert paths.get_app_version() == ""


def test_override_changes_only_data_dir(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("CHESS_DATA_DIR", "/tmp/cd")
    assert paths.get_data_dir() == Path("/tmp/cd")
    assert paths.get_games_dir() == Path("/tmp/cd/games")
    # The override moves only game data; config + logs stay put.
    assert paths.get_config_dir() == paths._source_root()
    assert paths.get_log_dir() == paths._source_root()


def test_override_expands_user(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("CHESS_DATA_DIR", "~/chessdata")
    assert paths.get_data_dir() == Path.home() / "chessdata"


def test_frozen_mode_uses_platformdirs(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/Chess", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI", raising=False)
    monkeypatch.delenv("CHESS_DATA_DIR", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(paths.platformdirs, "user_config_dir", lambda a, b: "/x/config")
    monkeypatch.setattr(paths.platformdirs, "user_data_dir", lambda a, b: "/x/data")
    monkeypatch.setattr(paths.platformdirs, "user_log_dir", lambda a, b: "/x/log")
    assert paths.get_asset_base() == Path("/tmp/_MEI")
    assert paths.get_config_dir() == Path("/x/config")
    assert paths.get_data_dir() == Path("/x/data")
    assert paths.get_log_dir() == Path("/x/log")
    assert paths.get_games_dir() == Path("/x/data/games")


def test_frozen_override_still_wins(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/Chess", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI", raising=False)
    monkeypatch.setenv("CHESS_DATA_DIR", "/tmp/cd")
    assert paths.get_data_dir() == Path("/tmp/cd")


def test_portable_onefile_beats_override_and_default(monkeypatch, tmp_path):
    # The portable build is the PyInstaller onefile exe: its _MEIPASS is a temp
    # dir outside the executable folder, so data lands in ./data/ beside it and
    # wins over any CHESS_DATA_DIR override.
    exe = tmp_path / "ChessShootout-1.0.0-Portable.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI_onefile", raising=False)
    monkeypatch.setenv("CHESS_DATA_DIR", "/tmp/cd")
    assert paths.is_portable() is True
    portable_data = tmp_path / "data"
    assert paths.get_data_dir() == portable_data
    assert paths.get_config_dir() == portable_data
    assert paths.get_log_dir() == portable_data
    assert paths.get_games_dir() == portable_data / "games"


def test_onedir_install_is_not_portable(monkeypatch, tmp_path):
    # The installer / .app / AppImage ship the onedir build: _MEIPASS sits
    # inside the executable folder, so it uses the per-user location.
    appdir = tmp_path / "app"
    (appdir / "_internal").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(appdir / "ChessShootout"), raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(appdir / "_internal"), raising=False)
    assert paths.is_portable() is False


def test_source_is_not_portable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.is_portable() is False
