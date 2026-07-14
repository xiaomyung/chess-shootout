import os


import pytest

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.infra import env
from chessshootout.frontend.frontend import Frontend


_pygame_init = pygame_display(1000, 800)


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
    (src / "a.pgn").write_text("1", encoding="utf-8")
    (src / "b.pgn").write_text("2", encoding="utf-8")
    (dst / "a.pgn").write_text("existing", encoding="utf-8")
    assert app.settings._move_pgns(str(src), str(dst)) is True
    names = sorted(os.listdir(dst))
    assert "a.pgn" in names
    assert "a-1.pgn" in names
    assert "b.pgn" in names
    assert (dst / "a.pgn").read_text(encoding="utf-8") == "existing"
    assert (dst / "a-1.pgn").read_text(encoding="utf-8") == "1"
    assert (dst / "b.pgn").read_text(encoding="utf-8") == "2"
    assert not os.path.isdir(src)


def test_move_pgns_keeps_old_dir_when_non_pgn_present(tmp_path):
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.pgn").write_text("1", encoding="utf-8")
    (src / "notes.txt").write_text("keep me", encoding="utf-8")
    assert app.settings._move_pgns(str(src), str(tmp_path / "new")) is True
    assert os.path.isdir(src)
    assert (src / "notes.txt").exists()
    assert (src / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert not (src / "a.pgn").exists()
    assert (tmp_path / "new" / "a.pgn").read_text(encoding="utf-8") == "1"


def test_move_pgns_failure_returns_false(tmp_path, monkeypatch):
    """An OSError during the move aborts: returns False and leaves the source pgn."""
    app = _app()
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.pgn").write_text("1", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("chessshootout.frontend.settings.shutil.move", boom)
    assert app.settings._move_pgns(str(src), str(tmp_path / "new")) is False
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
    app.settings._apply_data_folder_change(str(new))
    assert app.confirm_modal.is_visible() is False
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_prompts_then_moves(tmp_path, monkeypatch):
    """Games present: prompt, then 'Move' relocates them and commits the new dir."""
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app.settings._apply_data_folder_change(str(new))
    assert app.confirm_modal.is_visible() is True
    _draw_then_click_confirm(app, "yes")
    assert (new / "games" / "g.pgn").read_text(encoding="utf-8") == "x"
    assert not (cur / "games").exists()
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_dont_move_leaves_them(tmp_path, monkeypatch):
    """'Don't move' still commits the new dir but leaves the old games in place."""
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app.settings._apply_data_folder_change(str(new))
    _draw_then_click_confirm(app, "no")
    assert (cur / "games" / "g.pgn").exists()
    assert not (new / "games" / "g.pgn").exists()
    assert str(paths.get_data_dir()) == str(new)


def test_change_with_games_cancel_aborts(tmp_path, monkeypatch):
    """'Cancel' (the extra button) aborts: nothing moves and the data dir is unchanged."""
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = _app()
    new = tmp_path / "new"
    new.mkdir()
    app.settings._apply_data_folder_change(str(new))
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
    app.settings._on_reset_data_folder()
    if app.confirm_modal.is_visible():
        _draw_then_click_confirm(app, "no")
    assert os.environ.get("CHESS_DATA_DIR") is None


def test_options_close_applies_default_time_to_menu(monkeypatch):
    """Leaving the Options view re-applies the persisted default time/increment
    to the play view's selection, overriding whatever was picked there before."""
    app = _app()
    app.menu.play_view.selected_time_minutes = 5
    app.menu.play_view.selected_increment_seconds = 2
    monkeypatch.setenv("CHESS_DEFAULT_TC", "15")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    app.menu.goto_view("options")
    app.menu.goto_view("play")
    assert app.menu.play_view.selected_time_minutes == 15
    assert app.menu.play_view.selected_increment_seconds == 10
