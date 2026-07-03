"""Redesigned folder browser: lists dirs + files (no ".." row — the Up button
navigates), shows item-count / size meta, drills into folders on click, picks the
current folder via Choose, and creates a folder through the inline input row."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.modals.directory_browser import DirectoryBrowser


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _browser():
    browser = DirectoryBrowser(pg.display.get_surface())
    browser.set_rect(pg.Rect(240, 100, 520, 600))
    return browser


def _names(browser):
    return [e[0] for e in browser.entries]


def test_lists_dirs_and_files_without_parent_row(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "game.pgn").write_text("x", encoding="utf-8")
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    names = _names(browser)
    assert ".." not in names
    assert "sub" in names
    assert "game.pgn" in names
    by_name = {e[0]: e for e in browser.entries}
    assert by_name["sub"][2] is True
    assert by_name["game.pgn"][2] is False


def test_meta_reports_item_count_and_size(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "one").mkdir()
    (sub / "two").mkdir()
    (tmp_path / "game.pgn").write_text("y" * 4096, encoding="utf-8")
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    by_name = {e[0]: e[3] for e in browser.entries}
    assert by_name["sub"] == "2 items"
    assert by_name["game.pgn"] == "4 KB"


def test_hidden_toggle_filters_dotentries(tmp_path):
    (tmp_path / ".secret").mkdir()
    (tmp_path / "visible").mkdir()
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    assert ".secret" not in _names(browser)
    browser.show_hidden = True
    browser._reload()
    assert ".secret" in _names(browser)


def test_enter_dir_and_go_up(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser._enter(str(sub))
    assert browser.current == os.path.abspath(str(sub))
    browser._go_up()
    assert browser.current == os.path.abspath(str(tmp_path))


def test_choose_returns_abspath_and_hides(tmp_path):
    selected = []
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: selected.append(p))
    browser._select_current()
    assert selected == [os.path.normpath(os.path.abspath(str(tmp_path)))]
    assert browser.is_visible() is False


def test_choose_nonwritable_calls_on_error_and_stays_open(tmp_path, monkeypatch):
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
    browser._start_creating()
    browser.new_folder_input.text = "MyGames"
    browser._create_folder()
    assert (tmp_path / "MyGames").is_dir()
    assert browser.creating is False
    assert "MyGames" in _names(browser)


def test_empty_new_folder_name_cancels(tmp_path):
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser._start_creating()
    browser.new_folder_input.text = "   "
    browser._create_folder()
    assert browser.creating is False
    assert list(tmp_path.iterdir()) == []


def test_draw_records_a_row_rect_per_entry(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "game.pgn").write_text("x", encoding="utf-8")
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser.draw()
    assert [path for _, path, _ in browser._row_rects] == [e[1] for e in browser.entries]
    assert all(r.width > 0 and r.height > 0 for r, _, _ in browser._row_rects)
    assert browser._choose_rect.width > 0
    assert browser._cancel_rect.width > 0
    assert browser._up_rect.width > 0
    assert browser._newfolder_rect.width > 0
    assert browser._hidden_rect.width > 0
    assert browser._input_rect.width == 0


def test_draw_creating_lays_out_inline_input_row(tmp_path):
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser._start_creating()
    browser.draw()
    assert browser._input_rect.width > 0


def test_click_dir_row_navigates_click_file_row_does_not(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "game.pgn").write_text("x", encoding="utf-8")
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: None)
    browser.draw()
    rects = {os.path.basename(path): r for r, path, _ in browser._row_rects}
    browser.handle_click(rects["game.pgn"].center)
    assert browser.current == os.path.abspath(str(tmp_path))
    browser.handle_click(rects["sub"].center)
    assert browser.current == os.path.abspath(str(tmp_path / "sub"))


def test_choose_button_click_invokes_on_select(tmp_path):
    selected = []
    browser = _browser()
    browser.show(str(tmp_path), on_select=lambda p: selected.append(p))
    browser.draw()
    browser.handle_click(browser._choose_rect.center)
    assert selected == [os.path.normpath(os.path.abspath(str(tmp_path)))]


def test_up_button_disabled_at_root(tmp_path):
    browser = _browser()
    root = os.path.abspath(os.sep)
    browser.show(root, on_select=lambda p: None)
    assert browser._at_root() is True
