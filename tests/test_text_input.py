import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.text_input import TextInput


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


@pytest.fixture
def ti():
    inp = TextInput(pg.display.get_surface())
    inp.set_rect(pg.Rect(50, 50, 200, 30))
    return inp


def make_key_event(key, unicode=""):
    # KEYDOWN with unicode is reliably constructible via pg.event.Event.
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": 0})


def test_construction_defaults(ti):
    assert ti.text == ""
    assert ti.focused is False
    assert ti.placeholder == "nickname"


def test_handle_click_inside_focuses(ti):
    consumed = ti.handle_click((60, 60))
    assert consumed is True
    assert ti.focused is True


def test_handle_click_outside_unfocuses(ti):
    ti.focused = True
    consumed = ti.handle_click((10, 10))
    assert consumed is False
    assert ti.focused is False


def test_handle_key_printable_while_focused_appends(ti):
    ti.focused = True
    consumed = ti.handle_key(make_key_event(pg.K_a, unicode="a"))
    assert consumed is True
    assert ti.text == "a"


def test_handle_key_printable_while_unfocused_no_change(ti):
    consumed = ti.handle_key(make_key_event(pg.K_a, unicode="a"))
    assert consumed is False
    assert ti.text == ""


def test_handle_key_backspace_pops_last_char(ti):
    ti.focused = True
    ti.text = "alice"
    consumed = ti.handle_key(make_key_event(pg.K_BACKSPACE))
    assert consumed is True
    assert ti.text == "alic"


def test_handle_key_backspace_on_empty_no_error(ti):
    ti.focused = True
    consumed = ti.handle_key(make_key_event(pg.K_BACKSPACE))
    assert consumed is True
    assert ti.text == ""


def test_handle_key_return_unfocuses(ti):
    ti.focused = True
    consumed = ti.handle_key(make_key_event(pg.K_RETURN))
    assert consumed is True
    assert ti.focused is False


def test_handle_key_escape_while_focused_unfocuses(ti):
    ti.focused = True
    consumed = ti.handle_key(make_key_event(pg.K_ESCAPE))
    assert consumed is True
    assert ti.focused is False


def test_handle_key_escape_while_unfocused_passes_through(ti):
    consumed = ti.handle_key(make_key_event(pg.K_ESCAPE))
    assert consumed is False


def test_max_chars_enforced(ti):
    ti.focused = True
    for _ in range(25):
        ti.handle_key(make_key_event(pg.K_a, unicode="a"))
    assert len(ti.text) == 20


def test_set_rect_rebuilds_font(ti):
    initial_size = ti.font.get_height()
    ti.set_rect(pg.Rect(0, 0, 200, 60))
    bigger_size = ti.font.get_height()
    assert bigger_size > initial_size


def test_draw_smoke_paths(ti):
    # Empty + unfocused: shows placeholder.
    ti.draw()
    # Empty + focused: shows cursor only.
    ti.focused = True
    ti.draw()
    # Typed + focused: shows text + cursor.
    ti.text = "alice"
    ti.draw()
    # Typed + unfocused: shows text.
    ti.focused = False
    ti.draw()
