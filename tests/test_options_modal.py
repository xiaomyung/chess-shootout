"""OptionsModal + the layout-agnostic settings rows: the modal paints the shell
and a Close button, sections render, and each control row (toggle / segmented /
slider / swatch / path) routes clicks to its getter/setter."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.modals.options import (
    CountryRow, OptionsModal, PathRow, TextRow, ToggleRow, SegmentedRow, SliderRow,
    SwatchRow, _Fonts,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font, get_mono_font


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((900, 700))
    yield
    pg.quit()


def _modal():
    modal = OptionsModal(pg.display.get_surface())
    modal.set_rect(pg.Rect(100, 60, 460, 560))
    return modal


def _fonts():
    return _Fonts(get_font(14, bold=True), get_font(11), get_font(10, bold=True),
                  get_mono_font(12), get_font(13, bold=True))


def _draw_row(row, rect=pg.Rect(40, 40, 420, 56)):
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    row.draw(win, rect, _fonts())
    return row


def test_show_paints_shell_and_close():
    modal = _modal()
    modal.show([("Game", [PathRow("Games folder", "where games live",
                                   pg.display.get_surface(), lambda: "/tmp/x",
                                   lambda: None, lambda: None)])])
    assert modal.is_visible() is True
    modal.window.fill((0, 0, 0))
    modal.draw()
    fill = modal.window.get_at((modal.rect.x + 3, modal.rect.centery))[:3]
    assert fill == pg.Color(Colors.surface_raised)[:3]
    assert "close" in modal.button_rects


def test_close_button_hides_and_calls_on_close():
    modal = _modal()
    closed = []
    modal.show([], on_close=lambda: closed.append(True))
    modal.draw()
    modal.handle_click(modal.button_rects["close"].center)
    assert modal.is_visible() is False
    assert closed == [True]


def test_click_outside_is_consumed_and_stays_open():
    modal = _modal()
    modal.show([])
    modal.draw()
    assert modal.handle_click((5, 5)) is True
    assert modal.is_visible() is True


def test_sections_render():
    modal = _modal()
    modal.show([("Audio", [ToggleRow("Mute", "", lambda: False, lambda v: None)]),
                ("Game", [PathRow("Folder", "", pg.display.get_surface(),
                                  lambda: "/x", lambda: None, lambda: None)])])
    modal.window.fill((0, 0, 0))
    modal.draw()
    painted = modal.window.subsurface(modal.rect)
    assert pg.image.tobytes(painted, "RGB") != bytes(painted.get_width()
                                                     * painted.get_height() * 3)


def test_toggle_row_flips_value():
    state = {"on": False}
    row = ToggleRow("Reduce motion", "calm", lambda: state["on"],
                    lambda v: state.update(on=v))
    _draw_row(row)
    assert row.handle_click(row._ctl.center) is True
    assert state["on"] is True


def test_toggle_knob_animates_toward_target():
    """After a flip the knob eases toward the new state across frames rather than
    snapping instantly."""
    state = {"on": False}
    row = ToggleRow("Reduce motion", "calm", lambda: state["on"],
                    lambda v: state.update(on=v))
    _draw_row(row)
    assert row._pos == 0.0
    state["on"] = True
    _draw_row(row)
    assert 0.0 < row._pos < 1.0
    for _ in range(20):
        _draw_row(row)
    assert row._pos == 1.0


def test_segmented_row_selects_option():
    chosen = {"v": "a"}
    row = SegmentedRow("Intensity", "", [("A", "a"), ("B", "b"), ("C", "c")],
                       lambda: chosen["v"], lambda k: chosen.update(v=k))
    _draw_row(row)
    assert row.handle_click(row._rects["c"].center) is True
    assert chosen["v"] == "c"


def test_slider_row_sets_value_from_click():
    val = {"v": 0.0}
    row = SliderRow("Volume", "", lambda: val["v"], lambda v: val.update(v=v))
    _draw_row(row)
    row.handle_click((row._track.right, row._track.centery))
    assert val["v"] > 0.9


def test_swatch_row_selects_unlocked_only():
    chosen = {"v": "dark"}
    swatches = [("dark", "#7a818b", "#2f343b", False), ("wood", "#d8b483", "#8a5a3c", True)]
    row = SwatchRow("Theme", "soon", swatches, lambda: chosen["v"],
                    lambda k: chosen.update(v=k))
    _draw_row(row)
    assert row.handle_click(row._rects["wood"][0].center) is False
    assert chosen["v"] == "dark"
    assert row.handle_click(row._rects["dark"][0].center) is True
    assert chosen["v"] == "dark"


def _path_row(getter=lambda: "/tmp/x", on_change=lambda: None, on_reset=lambda: None):
    return PathRow("Games folder", "where games live", pg.display.get_surface(),
                   getter, on_change, on_reset)


def test_pathrow_buttons_route_callbacks():
    fired = {"change": 0, "reset": 0}
    row = _path_row(on_change=lambda: fired.update(change=fired["change"] + 1),
                    on_reset=lambda: fired.update(reset=fired["reset"] + 1))
    _draw_row(row, pg.Rect(40, 40, 420, 120))
    assert row.handle_click(row._change_rect.center) is True
    assert row.handle_click(row._reset_rect.center) is True
    assert fired == {"change": 1, "reset": 1}


def test_pathrow_field_click_focuses_input():
    row = _path_row()
    _draw_row(row, pg.Rect(40, 40, 420, 120))
    assert row.handle_click(row._field_rect.center) is True
    assert row.input.focused is True


def test_pathrow_current_text_strips_and_reflects_input():
    row = _path_row()
    _draw_row(row, pg.Rect(40, 40, 420, 120))
    row.input.text = "  /home/me/chess  "
    assert row.current_text() == "/home/me/chess"


def test_pathrow_handle_key_types_into_focused_field():
    row = _path_row()
    _draw_row(row, pg.Rect(40, 40, 420, 120))
    row.input.text = ""
    row.input.focused = True
    ev = pg.event.Event(pg.KEYDOWN, key=pg.K_z, mod=0, unicode="z")
    assert row.handle_key(ev) is True
    assert row.current_text() == "z"


def test_modal_handle_key_routes_to_focused_pathrow():
    modal = _modal()
    row = _path_row()
    modal.show([("Game", [row])])
    modal.draw()
    row.input.text = ""
    row.input.focused = True
    ev = pg.event.Event(pg.KEYDOWN, key=pg.K_q, mod=0, unicode="q")
    assert modal.handle_key(ev) is True
    assert row.current_text() == "q"


def test_close_gate_blocks_when_on_close_returns_false():
    modal = _modal()
    modal.show([], on_close=lambda: False)
    modal.draw()
    modal.handle_click(modal.button_rects["close"].center)
    assert modal.is_visible() is True
    modal.on_close = lambda: True
    modal.handle_click(modal.button_rects["close"].center)
    assert modal.is_visible() is False


def test_body_scroll_clamps():
    modal = _modal()
    modal.set_rect(pg.Rect(100, 60, 460, 240))
    rows = [ToggleRow(f"opt {i}", "desc", lambda: False, lambda v: None) for i in range(12)]
    modal.show([("Many", rows)])
    modal.draw()
    modal.handle_scroll((modal.rect.centerx, modal.rect.centery), -5)
    assert modal.body.scroll > 0
    modal.handle_scroll((modal.rect.centerx, modal.rect.centery), 999)
    assert modal.body.scroll == 0


def test_text_row_reports_typed_value():
    row = TextRow("Server", "where online connects", pg.display.get_surface(),
                  lambda: "localhost:8000", placeholder="host or host:port")
    _draw_row(row)
    assert row.current_text() == "localhost:8000"
    row.input.focused = True
    row.input.text = "chess.example.com:9000"
    assert row.current_text() == "chess.example.com:9000"


def test_country_row_opens_picker_on_control_click():
    opened = []
    row = CountryRow("Country", "Your flag", lambda: "US", lambda: opened.append(1))
    _draw_row(row)
    assert row._ctl.width > 0
    assert row.handle_click(row._ctl.center) is True
    assert opened == [1]


def test_country_row_ignores_click_outside_control():
    opened = []
    row = CountryRow("Country", "", lambda: "", lambda: opened.append(1))
    _draw_row(row)
    assert row.handle_click((5, 5)) is False
    assert opened == []
