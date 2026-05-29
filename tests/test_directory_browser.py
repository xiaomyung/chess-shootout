import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modals.directory_browser import DirectoryBrowser


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _browser():
    browser = DirectoryBrowser(pg.display.get_surface())
    browser.set_rect(pg.Rect(50, 50, 800, 600))
    return browser


def test_lists_only_directories_with_parent(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("x")
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    names = [n for n, _ in browser.entries]
    assert ".." in names
    assert "sub" in names
    assert "file.txt" not in names


def test_hidden_toggle_filters_dotfolders(tmp_path):
    (tmp_path / ".secret").mkdir()
    (tmp_path / "visible").mkdir()
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    assert ".secret" not in [n for n, _ in browser.entries]
    browser.show_hidden = True
    browser._reload()
    assert ".secret" in [n for n, _ in browser.entries]


def test_enter_and_parent_navigation(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser._enter(str(sub))
    assert browser.current == os.path.abspath(str(sub))
    parent_name, parent_path = browser.entries[0]
    assert parent_name == ".."
    browser._enter(parent_path)
    assert browser.current == os.path.abspath(str(tmp_path))


def test_select_returns_abspath_and_hides(tmp_path):
    selected = []
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: selected.append(p))
    browser._select_current()
    assert selected == [os.path.normpath(os.path.abspath(str(tmp_path)))]
    assert browser.is_visible() is False


def test_select_nonwritable_calls_on_error_and_stays_open(tmp_path, monkeypatch):
    errors = []
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None, on_error=lambda m: errors.append(m))
    monkeypatch.setattr(browser, "_writable", lambda d: False)
    browser._select_current()
    assert errors
    assert browser.is_visible() is True


def test_new_folder_creates_and_reloads(tmp_path):
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser.creating = True
    browser.new_folder_input.text = "MyGames"
    browser._create_folder()
    assert (tmp_path / "MyGames").is_dir()
    assert browser.creating is False
    assert "MyGames" in [n for n, _ in browser.entries]


def test_draw_runs_without_error(tmp_path):
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser.draw()  # not creating
    browser.creating = True
    browser.draw()  # creating: shows the name input + Create/Cancel
