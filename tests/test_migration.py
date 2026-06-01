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
    """Pin set_data_dir to a temp .env (never the real repo) and start unset."""
    envfile = tmp_path_factory.mktemp("envcfg") / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", envfile)
    monkeypatch.delenv("CHESS_DATA_DIR", raising=False)
    yield
    os.environ.pop("CHESS_DATA_DIR", None)


def _app():
    return Frontend(1000, 800)


def _draw_then_click_confirm(app, key):
    """Lay out the confirm modal's button rects, then click the named button."""
    app.draw_frame()
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
    assert "a.pgn" in names
    assert "a-1.pgn" in names
    assert "b.pgn" in names
    assert (dst / "a.pgn").read_text() == "existing"
    assert (dst / "a-1.pgn").read_text() == "1"
    assert (dst / "b.pgn").read_text() == "2"
    assert not os.path.isdir(src)


def test_move_pgns_keeps_old_dir_when_non_pgn_present(tmp_path):
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.pgn").write_text("1")
    (src / "notes.txt").write_text("keep me")
    assert app._move_pgns(str(src), str(tmp_path / "new")) is True
    assert os.path.isdir(src)
    assert (src / "notes.txt").exists()
    assert (src / "notes.txt").read_text() == "keep me"
    assert not (src / "a.pgn").exists()
    assert (tmp_path / "new" / "a.pgn").read_text() == "1"


def test_move_pgns_failure_returns_false(tmp_path, monkeypatch):
    """An OSError during the move aborts: returns False and leaves the source pgn."""
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.pgn").write_text("1")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("frontend.frontend.shutil.move", boom)
    assert app._move_pgns(str(src), str(tmp_path / "new")) is False
    assert (src / "a.pgn").exists()
    assert os.path.isdir(src)


def test_change_with_no_games_commits_immediately(tmp_path, monkeypatch):
    """No games/ in the old dir: commit straight through with no confirm prompt."""
    cur = tmp_path / "cur"
    cur.mkdir()
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    assert app.confirm_modal.is_visible() is False
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_prompts_then_moves(tmp_path, monkeypatch):
    """Games present: prompt, then 'Move' relocates them and commits the new dir."""
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
    assert (new / "games" / "g.pgn").read_text() == "x"
    assert not (cur / "games").exists()
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_dont_move_leaves_them(tmp_path, monkeypatch):
    """'Don't move' still commits the new dir but leaves the old games in place."""
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    _draw_then_click_confirm(app, "no")
    assert (cur / "games" / "g.pgn").exists()
    assert not (new / "games" / "g.pgn").exists()
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_cancel_aborts(tmp_path, monkeypatch):
    """'Cancel' (the extra button) aborts: nothing moves and the data dir is unchanged."""
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app._apply_data_folder_change(str(new))
    _draw_then_click_confirm(app, "extra")
    assert (cur / "games" / "g.pgn").exists()
    assert not (new / "games").exists()
    assert str(paths.get_data_dir()) == str(cur)


def test_reset_clears_override(tmp_path, monkeypatch):
    """Reset to default clears the persisted CHESS_DATA_DIR override entirely."""
    custom = tmp_path / "custom"
    custom.mkdir()
    monkeypatch.setenv("CHESS_DATA_DIR", str(custom))
    app = _app()
    app._on_reset_data_folder()
    if app.confirm_modal.is_visible():
        _draw_then_click_confirm(app, "no")
    assert env.get_data_dir_override() == ""


def test_menu_hidden_while_overlay_modal_open():
    """An open overlay modal hides the menu; closing it brings the menu back."""
    app = _app()
    assert app._menu_overlay_active() is False
    app._on_open_options()
    assert app._menu_overlay_active() is True
    app.options_modal.hide()
    assert app._menu_overlay_active() is False


def test_options_close_applies_default_time_to_menu(monkeypatch):
    """Closing Settings re-applies the persisted default time/increment to the
    start-menu selection, overriding whatever was picked there before."""
    app = _app()
    app.start_menu.selected_time_minutes = 5
    app.start_menu.selected_increment_seconds = 2
    monkeypatch.setenv("CHESS_DEFAULT_TC", "15")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    assert app._on_close_settings() is True
    assert app.start_menu.selected_time_minutes == 15
    assert app.start_menu.selected_increment_seconds == 10


def test_menu_click_routes_to_options_not_start_menu(monkeypatch):
    """With the options modal open, clicks route to it and never reach start_menu."""
    app = _app()
    assert app.mode == "menu"
    app._on_open_options()
    app.draw_frame()
    received = []
    monkeypatch.setattr(app.start_menu, "handle_click", lambda pos: received.append(pos))
    app.mouse_left_clicked((10, 10))
    assert received == []
    assert app.options_modal.is_visible() is True
