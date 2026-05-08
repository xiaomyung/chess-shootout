import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.file_picker import FilePicker


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def picker():
    p = FilePicker(pg.display.get_surface())
    p.set_rect(pg.Rect(0, 0, 400, 300))
    return p


def test_picker_hidden_by_default(picker):
    assert picker.is_visible() is False


def test_picker_show_makes_visible(picker, tmp_path):
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    assert picker.is_visible() is True


def test_picker_lists_pgn_files_sorted_by_mtime(picker, tmp_path):
    older = tmp_path / "older.pgn"
    older.write_text("a")
    newer = tmp_path / "newer.pgn"
    newer.write_text("b")
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    names = [n for n, _ in picker.entries]
    assert names == ["newer.pgn", "older.pgn"]


def test_picker_empty_when_no_pgns(picker, tmp_path):
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    assert picker.entries == []


def test_picker_excludes_non_pgn_files(picker, tmp_path):
    (tmp_path / "game.pgn").write_text("x")
    (tmp_path / "notes.txt").write_text("y")
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    names = [n for n, _ in picker.entries]
    assert names == ["game.pgn"]


def test_picker_click_row_invokes_callback(picker, tmp_path):
    f = tmp_path / "game.pgn"
    f.write_text("x")
    picked = []
    picker.show(str(tmp_path), "*.pgn",
                on_select=lambda path: picked.append(path))
    picker.draw()  # populate _row_rects
    row_rect, _ = picker._row_rects[0]
    consumed = picker.handle_click(row_rect.center)
    assert consumed is True
    assert picked == [str(f)]
    assert picker.is_visible() is False


def test_picker_click_cancel_invokes_cancel_callback(picker, tmp_path):
    cancelled = [False]
    picker.show(str(tmp_path), "*.pgn",
                on_select=lambda p: None,
                on_cancel=lambda: cancelled.__setitem__(0, True))
    picker.draw()
    cancel_rect = picker._cancel_rect
    picker.handle_click(cancel_rect.center)
    assert cancelled[0] is True
    assert picker.is_visible() is False


def test_picker_does_not_handle_keys():
    # Esc must close the window — picker should not consume keys.
    p = FilePicker(pg.display.get_surface())
    p.set_rect(pg.Rect(0, 0, 400, 300))
    # Ensure no `handle_key` method exists or that calling it on Esc does nothing.
    assert not hasattr(p, "handle_key")


def test_picker_click_outside_returns_false(picker, tmp_path):
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()
    consumed = picker.handle_click((picker.rect.right + 100, picker.rect.bottom + 100))
    assert consumed is False
    assert picker.is_visible() is True


def _populate(tmp_path, count):
    for i in range(count):
        f = tmp_path / f"game-{i:04d}.pgn"
        f.write_text("x")
        os.utime(f, (1_000 + i, 1_000 + i))


def test_picker_scroll_advances_offset(picker, tmp_path):
    _populate(tmp_path, 50)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()  # populate _max_visible and _list_rect
    pos = picker._list_rect.center
    consumed = picker.handle_scroll(pos, -1)
    assert consumed is True
    assert picker.scroll_offset == 1


def test_picker_scroll_cap_at_max_offset(picker, tmp_path):
    _populate(tmp_path, 50)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()
    max_offset = max(0, len(picker.entries) - picker._max_visible)
    pos = picker._list_rect.center
    for _ in range(200):
        picker.handle_scroll(pos, -1)
    assert picker.scroll_offset == max_offset


def test_picker_scroll_does_not_go_negative(picker, tmp_path):
    _populate(tmp_path, 5)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()
    pos = picker._list_rect.center
    consumed = picker.handle_scroll(pos, 1)
    # Already at top; nothing more to scroll.
    if len(picker.entries) <= picker._max_visible:
        assert consumed is False
    assert picker.scroll_offset == 0


def test_picker_scroll_outside_list_rect_returns_false(picker, tmp_path):
    _populate(tmp_path, 50)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()
    outside = (picker.rect.right + 100, picker.rect.centery)
    consumed = picker.handle_scroll(outside, -1)
    assert consumed is False
    assert picker.scroll_offset == 0


def test_picker_scrolled_view_shows_correct_subset(picker, tmp_path):
    _populate(tmp_path, 50)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()
    pos = picker._list_rect.center
    picker.handle_scroll(pos, -3)
    picker.draw()
    visible_paths = [p for _, p in picker._row_rects]
    expected_first = picker.entries[3][1]
    assert visible_paths[0] == expected_first


def test_picker_scroll_indicator_appears_only_when_overflow(picker, tmp_path):
    # No overflow: indicator never drawn (no exception either).
    _populate(tmp_path, 2)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker.draw()  # smoke
    # Overflow case: just smoke that draw runs.
    _populate(tmp_path, 200)
    picker.show(str(tmp_path), "*.pgn", on_select=lambda p: None)
    picker._last_scroll_activity_ms = pg.time.get_ticks()
    picker.draw()
