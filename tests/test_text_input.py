"""TextInput widget: focus-gated key handling and state-driven render.

The cursor "blink" is not time-based — draw() paints a trailing "|" iff
self.focused, so focus state alone toggles the cursor glyph. Placeholder text
uses the dim border color while real text and the cursor use the bright text color, so
glyph-brightness sampling can distinguish the three render states.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.visual.text_input import TextInput


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


def make_key_event(key, unicode="", mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": unicode, "mod": mod})


def _count_bright_pixels(ti, threshold=120):
    window = ti.window
    window.fill((0, 0, 0))
    ti.draw()
    count = 0
    inner = ti.rect.inflate(-6, -6)
    for x in range(inner.left, inner.right):
        for y in range(inner.top, inner.bottom):
            r, g, b = window.get_at((x, y))[:3]
            if min(r, g, b) > threshold:
                count += 1
    return count


def test_construction_defaults(ti):
    assert ti.text == ""
    assert ti.focused is False
    assert ti.placeholder == "nickname"


def test_mono_flag_uses_monospace_font():
    from chessshootout.frontend.visual.fonts import get_mono_font
    inp = TextInput(pg.display.get_surface(), mono=True)
    inp.set_rect(pg.Rect(0, 0, 200, 32))
    expected = get_mono_font(max(int(32 / inp.font_factor), 10))
    assert inp.font.size("iiii") == expected.size("iiii")
    assert inp.font.size("iiii") == inp.font.size("MMMM")


def test_handle_click_inside_focuses(ti):
    consumed = ti.handle_click((60, 60))
    assert consumed is True
    assert ti.focused is True


def test_ascii_only_strips_nonascii_on_insert():
    inp = TextInput(pg.display.get_surface(), ascii_only=True)
    inp.set_rect(pg.Rect(0, 0, 200, 30))
    inp._insert("héllo Щ!")
    assert inp.text == "hllo !"


def test_ascii_only_rejects_nonascii_typed():
    inp = TextInput(pg.display.get_surface(), ascii_only=True)
    inp.set_rect(pg.Rect(0, 0, 200, 30))
    inp.focused = True
    for ch in "aЩb":
        inp.handle_key(make_key_event(pg.K_UNKNOWN, unicode=ch))
    assert inp.text == "ab"


def test_default_field_still_accepts_nonascii(ti):
    """Non-nickname fields (data-folder path, new-folder name) must keep accepting
    unicode -- only the nickname field opts into ascii_only."""
    ti.focused = True
    for ch in "Jösé":
        ti.handle_key(make_key_event(pg.K_UNKNOWN, unicode=ch))
    assert ti.text == "Jösé"


def test_ascii_only_fires_on_reject_when_chars_dropped():
    calls = []
    inp = TextInput(pg.display.get_surface(), ascii_only=True,
                    on_reject=lambda: calls.append(1))
    inp.set_rect(pg.Rect(0, 0, 200, 30))
    inp._insert("aЩb")
    assert inp.text == "ab"
    assert calls == [1]


def test_ascii_only_no_reject_for_clean_ascii():
    calls = []
    inp = TextInput(pg.display.get_surface(), ascii_only=True,
                    on_reject=lambda: calls.append(1))
    inp.set_rect(pg.Rect(0, 0, 200, 30))
    inp._insert("clean")
    assert inp.text == "clean"
    assert calls == []


def test_no_reject_when_not_ascii_only():
    calls = []
    inp = TextInput(pg.display.get_surface(), on_reject=lambda: calls.append(1))
    inp.set_rect(pg.Rect(0, 0, 200, 30))
    inp._insert("Щ")
    assert inp.text == "Щ"
    assert calls == []


def test_handle_click_outside_unfocuses(ti):
    ti.focused = True
    consumed = ti.handle_click((10, 10))
    assert consumed is False
    assert ti.focused is False


@pytest.mark.parametrize(
    "start_text, key, unicode, expected_text, expected_focused",
    [
        pytest.param("", pg.K_a, "a", "a", True, id="printable_appends"),
        pytest.param("alice", pg.K_BACKSPACE, "", "alic", True, id="backspace_pops_last"),
        pytest.param("", pg.K_BACKSPACE, "", "", True, id="backspace_on_empty_noop"),
        pytest.param("", pg.K_RETURN, "", "", False, id="return_unfocuses"),
        pytest.param("", pg.K_ESCAPE, "", "", False, id="escape_unfocuses"),
    ],
)
def test_handle_key_while_focused(ti, start_text, key, unicode, expected_text, expected_focused):
    """Focused key handling is always consumed; text/focus update per key."""
    ti.focused = True
    ti.text = start_text
    consumed = ti.handle_key(make_key_event(key, unicode=unicode))
    assert consumed is True
    assert ti.text == expected_text
    assert ti.focused is expected_focused


@pytest.mark.parametrize(
    "key, unicode",
    [
        pytest.param(pg.K_a, "a", id="printable_passes_through"),
        pytest.param(pg.K_ESCAPE, "", id="escape_passes_through"),
    ],
)
def test_handle_key_while_unfocused_not_consumed(ti, key, unicode):
    """Unfocused input is never consumed and never mutates text."""
    consumed = ti.handle_key(make_key_event(key, unicode=unicode))
    assert consumed is False
    assert ti.text == ""


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


def test_draw_placeholder_paints_no_white_pixels(ti):
    """Empty + unfocused renders the dim placeholder, no white glyphs."""
    assert _count_bright_pixels(ti) == 0


def test_draw_focus_paints_cursor_on_empty(ti):
    """Focusing an empty field paints the white "|" cursor (the blink glyph)."""
    ti.focused = False
    unfocused = _count_bright_pixels(ti)
    ti.focused = True
    focused = _count_bright_pixels(ti)
    assert unfocused == 0
    assert focused > 0


def test_draw_typed_text_paints_white_glyphs(ti):
    """Typed text renders white glyphs well beyond the lone cursor."""
    ti.focused = True
    ti.text = ""
    cursor_only = _count_bright_pixels(ti)
    ti.text = "alice"
    typed = _count_bright_pixels(ti)
    assert typed > cursor_only * 3


def test_draw_focus_adds_cursor_to_typed_text(ti):
    """Same text, focus on vs off: focused paints the extra trailing cursor."""
    ti.text = "alice"
    ti.focused = False
    without_cursor = _count_bright_pixels(ti)
    ti.focused = True
    with_cursor = _count_bright_pixels(ti)
    assert with_cursor > without_cursor


@pytest.mark.parametrize(
    "start_text, pasted, expected",
    [
        pytest.param("", "pasted text", "pasted text", id="paste_into_empty"),
        pytest.param("hello ", "world", "hello world", id="paste_appends_to_existing"),
    ],
)
def test_ctrl_v_pastes_clipboard(ti, monkeypatch, start_text, pasted, expected):
    monkeypatch.setattr(
        "chessshootout.frontend.visual.text_input._paste_from_clipboard",
        lambda: pasted,
    )
    ti.focused = True
    ti.text = start_text
    handled = ti.handle_key(make_key_event(pg.K_v, unicode="v", mod=pg.KMOD_CTRL))
    assert handled is True
    assert ti.text == expected


def test_ctrl_v_truncates_to_max_chars(monkeypatch):
    inp = TextInput(pg.display.get_surface(), max_chars=5)
    inp.set_rect(pg.Rect(0, 0, 200, 30))
    inp.focused = True
    monkeypatch.setattr(
        "chessshootout.frontend.visual.text_input._paste_from_clipboard",
        lambda: "abcdefghij",
    )
    inp.handle_key(make_key_event(pg.K_v, unicode="v", mod=pg.KMOD_CTRL))
    assert inp.text == "abcde"


def test_v_without_ctrl_just_types_v(ti):
    ti.focused = True
    ti.handle_key(make_key_event(pg.K_v, unicode="v", mod=0))
    assert ti.text == "v"


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param("  rnbqkbnr/pppppppp\n  ", "rnbqkbnr/pppppppp", id="trims_and_drops_newline"),
        pytest.param("a\r\nb", "a b", id="crlf_becomes_space"),
    ],
)
def test_sanitise_strips_newlines_and_trims(raw, expected):
    from chessshootout.frontend.visual.text_input import _sanitise
    assert _sanitise(raw) == expected
