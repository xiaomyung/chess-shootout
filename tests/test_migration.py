import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

import paths
from frontend import env
from frontend.frontend import Frontend


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path_factory, monkeypatch):
    # Keep set_data_dir away from the real repo .env, and start with no override.
    envfile = tmp_path_factory.mktemp("envcfg") / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", envfile)
    monkeypatch.delenv("CHESS_DATA_DIR", raising=False)
    yield
    os.environ.pop("CHESS_DATA_DIR", None)


def _app():
    return Frontend(1000, 800)


def _draw_then_click_confirm(app, key):
    app.draw_frame()  # lays out the confirm modal's button rects
    app.confirm_modal.handle_click(app.confirm_modal.button_rects[key].center)


def test_move_pgns_relocates_and_renames_collisions(tmp_path):
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    dst = tmp_path / "new"
    dst.mkdir()
    (src / "a.pgn").write_text("1")
    (src / "b.pgn").write_text("2")
    (dst / "a.pgn").write_text("existing")
    assert app._move_pgns(str(src), str(dst)) is True
    names = sorted(os.listdir(dst))
    assert "a.pgn" in names      # pre-existing kept
    assert "a-1.pgn" in names    # collision renamed
    assert "b.pgn" in names
    assert not os.path.isdir(src)   # emptied old games dir is removed


def test_move_pgns_keeps_old_dir_when_non_pgn_present(tmp_path):
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.pgn").write_text("1")
    (src / "notes.txt").write_text("keep me")
    assert app._move_pgns(str(src), str(tmp_path / "new")) is True
    assert os.path.isdir(src)              # not removed: a non-pgn file remains
    assert (src / "notes.txt").exists()
    assert not (src / "a.pgn").exists()    # the pgn was still moved


def test_move_pgns_failure_returns_false(tmp_path, monkeypatch):
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.pgn").write_text("1")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("frontend.frontend.shutil.move", boom)
    assert app._move_pgns(str(src), str(tmp_path / "new")) is False


def test_change_with_no_games_commits_immediately(tmp_path, monkeypatch):
    cur = tmp_path / "cur"
    cur.mkdir()
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))  # empty: no games/
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    assert app.confirm_modal.is_visible() is False
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_prompts_then_moves(tmp_path, monkeypatch):
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    assert app.confirm_modal.is_visible() is True
    _draw_then_click_confirm(app, "yes")
    assert (new / "games" / "g.pgn").exists()
    assert not (cur / "games").exists()          # emptied old games dir removed
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_dont_move_leaves_them(tmp_path, monkeypatch):
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    _draw_then_click_confirm(app, "no")
    assert (cur / "games" / "g.pgn").exists()        # original untouched
    assert not (new / "games" / "g.pgn").exists()
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_cancel_aborts(tmp_path, monkeypatch):
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    _draw_then_click_confirm(app, "extra")           # Cancel
    assert (cur / "games" / "g.pgn").exists()         # original untouched
    assert not (new / "games").exists()
    assert str(paths.get_data_dir()) == str(cur)      # data dir NOT changed


def test_reset_clears_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    custom.mkdir()
    monkeypatch.setenv("CHESS_DATA_DIR", str(custom))
    app = _app()
    app._on_reset_data_folder()
    if app.confirm_modal.is_visible():
        _draw_then_click_confirm(app, "no")
    assert env.get_data_dir_override() == ""


def test_menu_hidden_while_overlay_modal_open():
    app = _app()
    assert app._menu_overlay_active() is False     # plain menu shows
    app._on_open_options()
    assert app._menu_overlay_active() is True       # modal open -> menu hidden
    app.options_modal.hide()
    assert app._menu_overlay_active() is False       # modal closed -> menu back


def test_menu_click_routes_to_options_not_start_menu(monkeypatch):
    app = _app()
    assert app.mode == "menu"
    app._on_open_options()
    app.draw_frame()
    received = []
    monkeypatch.setattr(app.start_menu, "handle_click", lambda pos: received.append(pos))
    app.mouse_left_clicked((10, 10))
    assert received == []                       # start_menu shielded by the modal
    assert app.options_modal.is_visible() is True
