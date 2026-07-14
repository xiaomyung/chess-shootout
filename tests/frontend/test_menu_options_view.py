"""OptionsView + the layout-agnostic settings rows (v2.9.0: Options folded from a
global modal into a menu sub-view). The row widgets (toggle/segmented/slider/
swatch/path/text) route clicks to their getter/setter exactly as before; the
view itself hosts them in an OptionsBody ScrollHost inside the menu's
subview_rect and replaces the old modal close-gate with an on-exit gate that
fires on view exit AND app quit, never veto-blocking navigation."""

import os

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.infra import env
from chessshootout.frontend.menu.options_rows import (
    OptionsBody, PathRow, TextRow, ToggleRow, SegmentedRow, SliderRow, SwatchRow, _Fonts,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font, get_mono_font
from tests.helpers import assert_pixel_color, make_app


_pygame_init = pygame_display(1200, 900)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path_factory, monkeypatch):
    """Pin persisted env writes to a temp .env (never the real user config)."""
    envfile = tmp_path_factory.mktemp("envcfg") / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", envfile)
    monkeypatch.delenv("CHESS_DATA_DIR", raising=False)
    yield
    os.environ.pop("CHESS_DATA_DIR", None)


def _fonts():
    return _Fonts(get_font(14, bold=True), get_font(11), get_font(10, bold=True),
                  get_mono_font(12), get_font(13, bold=True))


def _draw_row(row, rect=pg.Rect(40, 40, 420, 56)):
    win = pg.display.get_surface()
    win.fill((0, 0, 0))
    row.draw(win, rect, _fonts())
    return row


def _draw_then_click_confirm(app, key):
    app.draw_frame()
    app.confirm_modal.handle_click(app.confirm_modal.button_rects[key].center)


@pytest.fixture
def app():
    application = make_app(1200, 900)
    application.draw_frame()
    return application


@pytest.fixture
def view(app):
    return app.menu.views["options"]


# --- row widgets (layout-agnostic, no app needed) --------------------------

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


def test_slider_row_fires_on_release_when_drag_ends(monkeypatch):
    """Volume persists on drag release (not every frame): on_release fires exactly
    when _dragging goes True -> False."""
    released = []
    row = SliderRow("Volume", "", lambda: 0.5, lambda v: None,
                    on_release=lambda: released.append(1))
    _draw_row(row)
    row.handle_click((row._track.centerx, row._track.centery))
    assert row._dragging is True
    monkeypatch.setattr(pg.mouse, "get_pressed", lambda *a, **k: (False, False, False))
    _draw_row(row)
    assert row._dragging is False
    assert released == [1]


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


def test_text_row_reports_typed_value():
    row = TextRow("Server", "where online connects", pg.display.get_surface(),
                  lambda: "localhost:8000", placeholder="host or host:port")
    _draw_row(row)
    assert row.current_text() == "localhost:8000"
    row.input.focused = True
    row.input.text = "chess.example.com:9000"
    assert row.current_text() == "chess.example.com:9000"


# --- OptionsBody scrolling (standalone, no view/app needed) ----------------

def test_body_scroll_clamps():
    body = OptionsBody()
    rows = [ToggleRow(f"opt {i}", "desc", lambda: False, lambda v: None) for i in range(12)]
    body.set_sections([("Many", rows)])
    surf = pg.display.get_surface()
    rect = pg.Rect(100, 60, 460, 240)
    body.draw(surf, rect, _fonts())
    body.handle_scroll((rect.centerx, rect.centery), -5)
    assert body.scroll_offset > 0
    body.handle_scroll((rect.centerx, rect.centery), 999)
    assert body.scroll_offset == 0


# --- OptionsView hosting ----------------------------------------------------

def test_enter_builds_six_sections_dropping_profile(app, view):
    app.menu.goto_view("options")
    labels = [label for label, _ in view.body.sections]
    assert labels == ["Audio", "Appearance", "Focus mode", "Game", "Online", "Performance"]
    assert "Profile" not in labels


def test_background_panel_paints_surface_raised(app):
    app.menu.goto_view("options")
    view = app.menu.views["options"]
    app.window.fill((0, 0, 0))
    view.draw(app.window, app.menu._menu_layout)
    assert_pixel_color(app.window, view._body_rect.x + 3, view._body_rect.centery,
                       Colors.surface_raised, tol=8)


def test_sections_paint_nonblank_pixels(app):
    app.menu.goto_view("options")
    view = app.menu.views["options"]
    app.window.fill((0, 0, 0))
    view.draw(app.window, app.menu._menu_layout)
    painted = app.window.subsurface(view._body_rect)
    assert pg.image.tobytes(painted, "RGB") != bytes(
        painted.get_width() * painted.get_height() * 3)


def test_esc_from_options_returns_to_play(app):
    app.menu.goto_view("options")
    result = app.menu.escape()
    assert result is True
    assert app.menu._active_view == "play"


def test_click_routes_to_options_body_not_play_view(app, monkeypatch):
    """With options active, clicks route to it and never reach play_view."""
    app.menu.goto_view("options")
    app.draw_frame()
    received = []
    monkeypatch.setattr(app.menu.play_view, "handle_click", lambda pos: received.append(pos))
    app.input_router.mouse_left_clicked((10, 10))
    assert received == []
    assert app.menu._active_view == "options"


def test_mute_toggle_row_wired_to_sound_manager(app):
    from unittest.mock import MagicMock
    app.sound_manager = MagicMock(enabled=True)
    app.menu.goto_view("options")
    rows = dict(app.menu.views["options"].body.sections)["Audio"]
    mute_row = next(r for r in rows if r.title == "Mute all sound")
    assert mute_row.getter() is False
    mute_row.setter(True)
    app.sound_manager.set_enabled.assert_called_once_with(False)


def test_handle_key_routes_to_the_focused_pathrow(app):
    app.menu.goto_view("options")
    app.draw_frame()
    row = app.settings._data_folder_row
    row.input.text = ""
    row.input.focused = True
    ev = pg.event.Event(pg.KEYDOWN, key=pg.K_q, mod=0, unicode="q")
    assert app.menu.views["options"].handle_key(ev) is True
    assert row.current_text() == "q"


def test_directory_browser_esc_closes_browser_not_the_options_view(app):
    """The directory browser opens from inside Options and is a GLOBAL modal
    layered above the view (per the modal-registry ordering): Esc peels it
    first and leaves the options view underneath still active."""
    app.menu.goto_view("options")
    app.directory_browser.show(str(paths.get_data_dir()), lambda p: None)
    assert app.directory_browser.is_visible() is True

    app.input_router._handle_escape()
    assert app.directory_browser.is_visible() is False
    assert app.menu._active_view == "options"

    app.input_router._handle_escape()
    assert app.menu._active_view == "play"


def test_no_options_modal_survives_on_the_frontend(app):
    assert not hasattr(app, "options_modal")


# --- on-exit gate: server address, defaults sync, deferred writes ----------

def test_exit_commits_pending_server_address(app):
    app.menu.goto_view("options")
    app.settings._server_addr_row.input.text = "chess.example.com:9000"
    app.menu.goto_view("play")
    assert env.get_server_addr() == "chess.example.com:9000"


def test_exit_syncs_default_time_to_the_play_picker(monkeypatch):
    app = make_app()
    app.menu.play_view.selected_time_minutes = 5
    app.menu.play_view.selected_increment_seconds = 2
    monkeypatch.setenv("CHESS_DEFAULT_TC", "15")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    app.menu.goto_view("options")
    app.menu.goto_view("play")
    assert app.menu.play_view.selected_time_minutes == 15
    assert app.menu.play_view.selected_increment_seconds == 10


def test_exit_force_flushes_a_pending_deferred_env_write(app):
    fired = []
    app.settings._defer_env_write("master_volume", lambda: fired.append(1))
    app.menu.goto_view("options")
    app.menu.goto_view("play")
    assert fired == [1]


def test_on_app_exit_commits_pending_options_even_without_navigating_away(app):
    """The gate must also fire at app quit (MenuScreen.on_app_exit), covering
    the case where the user quits while Options is still the active view and
    never triggers its own exit() through goto_view."""
    app.menu.goto_view("options")
    app.settings._server_addr_row.input.text = "quit-addr.example.com:9000"
    app.menu.on_app_exit()
    assert env.get_server_addr() == "quit-addr.example.com:9000"


def test_invalid_data_folder_on_exit_toasts_and_does_not_veto_navigation(app):
    app.menu.goto_view("options")
    app.settings._data_folder_row.input.text = "/definitely/not/writable/anywhere"
    app.menu.goto_view("play")
    assert app.toast.message == "That folder isn't writable"
    assert app.menu._active_view == "play"


# --- CROSSCHECK 7: games-folder move flow survives the exit gate -----------

def test_valid_changed_folder_with_games_on_exit_prompts_move_confirm(tmp_path, monkeypatch):
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = make_app()
    app.menu.goto_view("options")
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    app.settings._data_folder_row.input.text = str(new_dir)

    app.menu.goto_view("play")

    assert app.confirm_modal.is_visible() is True
    _draw_then_click_confirm(app, "yes")
    assert (new_dir / "games" / "g.pgn").read_text(encoding="utf-8") == "x"
    assert not (cur / "games").exists()
    assert str(paths.get_data_dir()) == str(new_dir)


def test_changed_folder_dont_move_still_commits_the_new_dir(tmp_path, monkeypatch):
    cur = tmp_path / "cur"
    (cur / "games").mkdir(parents=True)
    (cur / "games" / "g.pgn").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CHESS_DATA_DIR", str(cur))
    app = make_app()
    app.menu.goto_view("options")
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    app.settings._data_folder_row.input.text = str(new_dir)

    app.menu.goto_view("play")
    _draw_then_click_confirm(app, "no")

    assert (cur / "games" / "g.pgn").exists()
    assert not (new_dir / "games" / "g.pgn").exists()
    assert str(paths.get_data_dir()) == str(new_dir)
