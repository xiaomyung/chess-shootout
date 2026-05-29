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
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("CHESS_DATA_DIR", "/tmp/cd")
    assert paths.get_data_dir() == Path("/tmp/cd")


def test_portable_beats_override_and_default(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    (tmp_path / "portable.txt").write_text("")
    monkeypatch.setenv("CHESS_DATA_DIR", "/tmp/cd")
    assert paths.is_portable() is True
    portable_data = tmp_path / "data"
    assert paths.get_data_dir() == portable_data
    assert paths.get_config_dir() == portable_data
    assert paths.get_log_dir() == portable_data
    assert paths.get_games_dir() == portable_data / "games"


def test_not_portable_without_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    assert paths.is_portable() is False


def test_get_app_dir_appimage(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/home/u/Apps/Chess.AppImage")
    assert paths.get_app_dir() == Path("/home/u/Apps")


def test_get_app_dir_macos_app_bundle(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Apps/Chess.app/Contents/MacOS/Chess", raising=False)
    assert paths.get_app_dir() == Path("/Apps")


def test_get_app_dir_frozen_plain_executable(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/chess/Chess", raising=False)
    assert paths.get_app_dir() == Path("/opt/chess")


def test_get_app_dir_source(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.get_app_dir() == paths._source_root()
