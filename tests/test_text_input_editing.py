"""TextInput full editing: cursor movement, word nav, selection (shift-arrows,
ctrl+A), mid-string insert/delete, backspace/delete with selection + word, and
mouse click / double-click / drag selection."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.visual.text_input import TextInput


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


def _ev(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


@pytest.fixture
def ti():
    inp = TextInput(pg.display.get_surface(), max_chars=40)
    inp.set_rect(pg.Rect(50, 50, 300, 30))
    inp.focused = True
    return inp


def _sel_text(ti):
    sel = ti._sel_range()
    return ti.text[sel[0]:sel[1]] if sel else None


def test_text_setter_puts_cursor_at_end(ti):
    ti.text = "hello"
    assert ti.cursor == 5


def test_left_right_move_cursor(ti):
    ti.text = "abc"
    ti.handle_key(_ev(pg.K_LEFT))
    assert ti.cursor == 2
    ti.handle_key(_ev(pg.K_RIGHT))
    assert ti.cursor == 3


def test_home_end(ti):
    ti.text = "abcdef"
    ti.handle_key(_ev(pg.K_HOME))
    assert ti.cursor == 0
    ti.handle_key(_ev(pg.K_END))
    assert ti.cursor == 6


def test_ctrl_arrow_word_jump(ti):
    ti.text = "hello world foo"
    ti.handle_key(_ev(pg.K_HOME))
    ti.handle_key(_ev(pg.K_RIGHT, mod=pg.KMOD_CTRL))
    assert ti.cursor == 6
    ti.handle_key(_ev(pg.K_RIGHT, mod=pg.KMOD_CTRL))
    assert ti.cursor == 12


def test_insert_mid_string(ti):
    ti.text = "abc"
    ti.handle_key(_ev(pg.K_LEFT))
    ti.handle_key(_ev(pg.K_x, unicode="X"))
    assert ti.text == "abXc" and ti.cursor == 3


def test_backspace_mid_string(ti):
    ti.text = "abcd"
    ti.handle_key(_ev(pg.K_LEFT))
    ti.handle_key(_ev(pg.K_BACKSPACE))
    assert ti.text == "abd" and ti.cursor == 2


def test_delete_key_removes_char_after_cursor(ti):
    ti.text = "abcd"
    ti.handle_key(_ev(pg.K_HOME))
    ti.handle_key(_ev(pg.K_DELETE))
    assert ti.text == "bcd" and ti.cursor == 0


def test_ctrl_backspace_deletes_word(ti):
    ti.text = "hello world"
    ti.handle_key(_ev(pg.K_BACKSPACE, mod=pg.KMOD_CTRL))
    assert ti.text == "hello "


def test_ctrl_delete_deletes_word(ti):
    ti.text = "hello world"
    ti.handle_key(_ev(pg.K_HOME))
    ti.handle_key(_ev(pg.K_DELETE, mod=pg.KMOD_CTRL))
    assert ti.text == "world"


def test_ctrl_a_selects_all(ti):
    ti.text = "select me"
    ti.handle_key(_ev(pg.K_a, mod=pg.KMOD_CTRL))
    assert _sel_text(ti) == "select me"


def test_shift_arrow_extends_selection(ti):
    ti.text = "abcdef"
    ti.handle_key(_ev(pg.K_HOME))
    ti.handle_key(_ev(pg.K_RIGHT, mod=pg.KMOD_SHIFT))
    ti.handle_key(_ev(pg.K_RIGHT, mod=pg.KMOD_SHIFT))
    assert _sel_text(ti) == "ab"


def test_typing_replaces_selection(ti):
    ti.text = "hello"
    ti.handle_key(_ev(pg.K_a, mod=pg.KMOD_CTRL))
    ti.handle_key(_ev(pg.K_z, unicode="Z"))
    assert ti.text == "Z"


def test_backspace_deletes_selection(ti):
    ti.text = "hello world"
    ti.handle_key(_ev(pg.K_a, mod=pg.KMOD_CTRL))
    ti.handle_key(_ev(pg.K_BACKSPACE))
    assert ti.text == ""


def test_arrow_collapses_selection_without_shift(ti):
    ti.text = "abcdef"
    ti.handle_key(_ev(pg.K_a, mod=pg.KMOD_CTRL))
    ti.handle_key(_ev(pg.K_LEFT))
    assert ti._sel_range() is None and ti.cursor == 0


def test_paste_replaces_selection(ti, monkeypatch):
    monkeypatch.setattr("frontend.visual.text_input._paste_from_clipboard",
                        lambda: "XYZ")
    ti.text = "hello"
    ti.handle_key(_ev(pg.K_a, mod=pg.KMOD_CTRL))
    ti.handle_key(_ev(pg.K_v, unicode="v", mod=pg.KMOD_CTRL))
    assert ti.text == "XYZ"


def test_ctrl_c_copies_selection(ti, monkeypatch):
    captured = []
    monkeypatch.setattr("frontend.visual.text_input._copy_to_clipboard",
                        lambda t: captured.append(t))
    ti.text = "copy this"
    ti.handle_key(_ev(pg.K_a, mod=pg.KMOD_CTRL))
    ti.handle_key(_ev(pg.K_c, mod=pg.KMOD_CTRL))
    assert captured == ["copy this"]


def test_click_positions_cursor_at_edges(ti):
    ti.text = "hello world"
    ti.handle_click((ti.rect.x + ti.padding, ti.rect.centery))
    assert ti.cursor == 0
    ti.handle_click((ti.rect.right - 2, ti.rect.centery))
    assert ti.cursor == len(ti.text)


def test_double_click_selects_word(ti):
    ti.text = "hello world"
    x = ti.rect.x + ti.padding + ti.font.size("hello wo")[0]
    ti.handle_click((x, ti.rect.centery))
    ti.handle_click((x, ti.rect.centery))
    assert _sel_text(ti) == "world"


def test_drag_extends_selection(ti, monkeypatch):
    ti.text = "drag me"
    ti.handle_click((ti.rect.x + ti.padding, ti.rect.centery))
    assert ti._dragging is True
    far_x = ti.rect.x + ti.padding + ti.font.size("drag")[0]
    monkeypatch.setattr(pg.mouse, "get_pressed", lambda *a, **k: (1, 0, 0))
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: (far_x, ti.rect.centery))
    ti.window.fill((0, 0, 0))
    ti.draw()
    assert _sel_text(ti) == "drag"
    monkeypatch.setattr(pg.mouse, "get_pressed", lambda *a, **k: (0, 0, 0))
    ti.draw()
    assert ti._dragging is False
