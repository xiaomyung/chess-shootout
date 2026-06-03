"""AudioPanel + SoundManager: layout grid math, slider interaction, real playback.

Strategy: the panel mirrors the right-menu button grid (text | slider | mute), so
the geometry assertions reproduce widgets.draw_button_row's column formula exactly.
Playback-disabling is verified by spying on the real play path (_play_with_master),
not by "doesn't raise" — disabled must be a true no-op, enabled must fire.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.paths import SOUNDS_DIR
from chessshootout.frontend.panels.audio import (
    AudioPanel, DEFAULT_BUTTON_COLUMNS, DEFAULT_BUTTON_GAP_PX,
)
from chessshootout.frontend.panels.right import RightMenu
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.visual.colors import Colors


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    if not pg.mixer.get_init():
        pg.mixer.init()
    pg.display.set_mode((1500, 800))
    yield
    pg.quit()


@pytest.fixture
def sm():
    return SoundManager(SOUNDS_DIR, enabled=True, master_volume=1.0)


@pytest.fixture
def panel(sm):
    p = AudioPanel(pg.display.get_surface(), sm)
    p.set_rect(pg.Rect(0, 0, 400, 40))
    return p


def test_master_volume_explicit_override(sm):
    assert sm.master_volume == 1.0


def test_master_volume_falls_back_to_env_default(monkeypatch, tmp_path):
    from chessshootout.infra import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CHESS_MASTER_VOLUME", raising=False)
    s = SoundManager(SOUNDS_DIR, enabled=True)
    assert s.master_volume == env_mod._DEFAULT_MASTER_VOLUME


def test_master_volume_reads_env_when_set(monkeypatch, tmp_path):
    from chessshootout.infra import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("CHESS_MASTER_VOLUME", "0.42")
    s = SoundManager(SOUNDS_DIR, enabled=True)
    assert s.master_volume == pytest.approx(0.42, abs=1e-3)


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param(-0.5, 0.0, id="clamps_below_zero"),
        pytest.param(2.0, 1.0, id="clamps_above_one"),
        pytest.param(0.42, 0.42, id="accepts_mid_range"),
    ],
)
def test_set_master_volume_clamps(sm, value, expected):
    sm.set_master_volume(value)
    assert sm.master_volume == pytest.approx(expected)


def test_play_with_master_scales_volume_before_playing():
    s = SoundManager(SOUNDS_DIR, enabled=True)
    s.master_volume = 0.3
    fake_sound = MagicMock()
    s._play_with_master(fake_sound)
    fake_sound.set_volume.assert_called_once_with(0.3)
    fake_sound.play.assert_called_once()


def test_heartbeat_volume_scales_by_master():
    s = SoundManager(SOUNDS_DIR, enabled=True, master_volume=1.0)
    base = s._heartbeat_volume(0.0)
    s.master_volume = 0.5
    half = s._heartbeat_volume(0.0)
    assert half == pytest.approx(base * 0.5)


def test_play_disabled_does_nothing(sm):
    """Disabled is a true no-op; enabling re-arms the real play path."""
    calls = []
    sm._play_with_master = lambda sound: calls.append(sound)
    assert sm._variants["move"]
    sm.enabled = False
    sm.play_move()
    assert calls == []
    sm.enabled = True
    sm.play_move()
    assert len(calls) == 1


def test_panel_set_rect_allocates_text_slider_mute_in_order(panel):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    assert panel.text_rect.x < panel.slider_rect.x < panel.mute_rect.x
    assert panel.text_rect.right <= panel.slider_rect.x
    assert panel.slider_rect.right <= panel.mute_rect.x
    assert panel.text_rect.width > 0
    assert panel.slider_rect.width > 0
    assert panel.mute_rect.width > 0


@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_panel_mirrors_n_button_grid_with_slider_spanning_middle(panel, n):
    """text=col0, mute=col(n-1), slider spans the middle — draw_button_row formula."""
    gap = DEFAULT_BUTTON_GAP_PX
    panel.set_rect(pg.Rect(0, 0, 400, 40), n_columns=n, gap=gap)
    btn_w = (400 - gap * (n - 1)) / n
    assert panel.text_rect.x == 0
    assert abs(panel.text_rect.width - btn_w) <= 1
    expected_mute_x = (n - 1) * (btn_w + gap)
    assert abs(panel.mute_rect.x - expected_mute_x) <= 1
    assert abs(panel.mute_rect.width - btn_w) <= 1
    slider_span = max(n - 2, 1)
    expected_slider_w = slider_span * btn_w + (slider_span - 1) * gap
    assert abs(panel.slider_rect.width - expected_slider_w) <= 1
    assert abs(panel.slider_rect.x - (panel.text_rect.right + gap)) <= 1


def test_panel_default_grid_is_5_columns(panel):
    """No explicit n_columns defaults to the 5-button playing-mode row."""
    assert DEFAULT_BUTTON_COLUMNS == 5
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    gap = DEFAULT_BUTTON_GAP_PX
    btn_w = (400 - gap * 4) / 5
    assert abs(panel.text_rect.width - btn_w) <= 1
    assert abs(panel.mute_rect.width - btn_w) <= 1


def test_panel_grid_aligns_with_actual_buttons_row():
    """Each audio region's x/right matches the right-menu button column it mirrors."""
    from chessshootout.frontend.visual.widgets import draw_button_row
    sm = SoundManager(SOUNDS_DIR, enabled=True)
    p = AudioPanel(pg.display.get_surface(), sm)
    font = pg.font.SysFont("Arial", 14, bold=True)
    rect = pg.Rect(0, 0, 400, 40)
    buttons = [("A", "a"), ("B", "b"), ("C", "c"), ("D", "d"), ("E", "e")]
    btn_rects = draw_button_row(
        pg.display.get_surface(), rect, buttons, font, DEFAULT_BUTTON_GAP_PX,
    )
    p.set_rect(rect, button_font=font, n_columns=len(buttons),
               gap=DEFAULT_BUTTON_GAP_PX)
    assert abs(p.text_rect.x - btn_rects["a"].x) <= 1
    assert abs(p.text_rect.right - btn_rects["a"].right) <= 1
    assert abs(p.mute_rect.x - btn_rects["e"].x) <= 1
    assert abs(p.mute_rect.right - btn_rects["e"].right) <= 1
    assert abs(p.slider_rect.x - btn_rects["b"].x) <= 1
    assert abs(p.slider_rect.right - btn_rects["d"].right) <= 1


def test_panel_grid_uses_external_button_font_when_passed():
    sm = SoundManager(SOUNDS_DIR, enabled=True)
    p = AudioPanel(pg.display.get_surface(), sm)
    custom_font = pg.font.SysFont("Arial", 22, bold=True)
    p.set_rect(pg.Rect(0, 0, 400, 40), button_font=custom_font)
    assert p.button_font is custom_font


def test_panel_click_mute_button_toggles_enabled(panel, sm):
    sm.enabled = True
    panel.handle_click(panel.mute_rect.center)
    assert sm.enabled is False
    panel.handle_click(panel.mute_rect.center)
    assert sm.enabled is True


def test_panel_click_slider_track_sets_value(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click((track.right, track.centery))
    assert sm.master_volume == pytest.approx(1.0)
    panel.handle_click((track.x, track.centery))
    assert sm.master_volume == pytest.approx(0.0)
    panel.handle_click((track.centerx, track.centery))
    assert sm.master_volume == pytest.approx(0.5, abs=0.05)


def test_panel_click_slider_starts_drag(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click((track.centerx, track.centery))
    assert panel._dragging_slider is True


def test_panel_drag_updates_value_continuously(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click((track.x, track.centery))
    assert sm.master_volume == pytest.approx(0.0)
    consumed = panel.handle_drag((track.right, track.centery), True)
    assert consumed is True
    assert sm.master_volume == pytest.approx(1.0)


def test_panel_drag_outside_when_not_started_returns_false(panel):
    consumed = panel.handle_drag((10, 10), True)
    assert consumed is False


def test_panel_drag_with_button_released_clears_state(panel):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click((track.x, track.centery))
    assert panel._dragging_slider is True
    panel.handle_drag((track.right, track.centery), False)
    assert panel._dragging_slider is False


def test_panel_end_drag_clears(panel):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    panel.handle_click(panel.slider_rect.center)
    assert panel._dragging_slider is True
    panel.end_drag()
    assert panel._dragging_slider is False


def test_panel_end_drag_persists_volume_to_env(panel, sm, monkeypatch, tmp_path):
    from chessshootout.infra import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CHESS_MASTER_VOLUME", raising=False)
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click((track.centerx, track.centery))
    assert panel._dragging_slider is True
    panel.end_drag()
    assert env_mod.get_master_volume() == pytest.approx(sm.master_volume, abs=1e-3)


def test_panel_end_drag_does_not_persist_when_not_dragging(panel, monkeypatch, tmp_path):
    from chessshootout.infra import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CHESS_MASTER_VOLUME", raising=False)
    panel.end_drag()
    assert not (tmp_path / ".env").exists()


def test_panel_drag_clamps_at_track_edges(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click(track.center)
    panel.handle_drag((track.x - 500, track.centery), True)
    assert sm.master_volume == pytest.approx(0.0)
    panel.handle_drag((track.right + 500, track.centery), True)
    assert sm.master_volume == pytest.approx(1.0)


def test_panel_click_outside_returns_false(panel):
    consumed = panel.handle_click((10000, 10000))
    assert consumed is False


@pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "muted"])
def test_panel_draw_paints_into_window(sm, enabled):
    """draw() paints the panel region in both mute states (block pixel-diff)."""
    sm.set_enabled(enabled)
    win = pg.display.get_surface()
    p = AudioPanel(win, sm)
    p.set_rect(pg.Rect(0, 0, 400, 40))
    win.fill((0, 0, 0), p.rect)
    before = pg.image.tobytes(win.subsurface(p.rect).copy(), "RGB")
    p.draw()
    after = pg.image.tobytes(win.subsurface(p.rect).copy(), "RGB")
    assert after != before
    assert p.text_rect.width > 0
    assert p.slider_rect.width > 0
    assert p.mute_rect.width > 0


def test_panel_draw_noop_when_rect_collapsed(panel):
    """A zero-width rect short-circuits draw() with no painting."""
    panel.set_rect(pg.Rect(0, 0, 0, 0))
    win = panel.window
    region = pg.Rect(0, 0, 50, 50)
    win.fill((0, 0, 0), region)
    before = pg.image.tobytes(win.subsurface(region).copy(), "RGB")
    panel.draw()
    after = pg.image.tobytes(win.subsurface(region).copy(), "RGB")
    assert after == before


@pytest.mark.parametrize("w", [120, 240, 480], ids=["w120", "w240", "w480"])
def test_panel_resize_keeps_layout_proportions(panel, w):
    """Across widths the three regions stay ordered, non-overlapping, mute hugs right."""
    panel.set_rect(pg.Rect(0, 0, w, 40))
    assert panel.text_rect.right <= panel.slider_rect.x
    assert panel.slider_rect.right <= panel.mute_rect.x
    assert panel.text_rect.x == 0
    assert abs(panel.mute_rect.right - w) <= 1


def test_volume_label_fits_inside_text_rect_at_default_size(panel):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    rendered = panel.button_font.render("Volume", True, Colors.text)
    assert rendered.get_width() <= panel.text_rect.width


def test_volume_label_is_static_across_volume_changes(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    sm.set_master_volume(0.0)
    panel.draw()
    sm.set_master_volume(1.0)
    panel.draw()
    rendered_low = panel.button_font.render("Volume", True, Colors.text)
    rendered_high = panel.button_font.render("Volume", True, Colors.text)
    assert pg.image.tobytes(rendered_low, "RGBA") == pg.image.tobytes(
        rendered_high, "RGBA")


@pytest.mark.parametrize("w", [120, 400], ids=["narrow", "default"])
def test_volume_label_blitted_width_fits_text_rect(panel, w):
    """The label is clip-fit to its column: blitted width never exceeds text_rect."""
    panel.set_rect(pg.Rect(0, 0, w, 40))
    surf = panel.button_font.render("Volume", True, Colors.text)
    if surf.get_width() > panel.text_rect.width > 0:
        surf = surf.subsurface(
            pg.Rect(0, 0, panel.text_rect.width, surf.get_height()))
    assert surf.get_width() <= panel.text_rect.width
    panel.draw()


def test_right_menu_audio_rect_below_buttons_rect():
    backend_mock = MagicMock()
    backend_mock.move_history = []
    rm = RightMenu(pg.display.get_surface(), backend_mock, callbacks={})
    rm.set_rect(pg.Rect(0, 0, 250, 800))
    assert rm.audio_rect.y > rm.buttons_rect.y


def test_right_menu_moves_rect_shrinks_when_audio_added():
    backend_mock = MagicMock()
    backend_mock.move_history = []
    rm = RightMenu(pg.display.get_surface(), backend_mock, callbacks={})
    rm.set_rect(pg.Rect(0, 0, 250, 800))
    assert rm.moves_rect.bottom <= rm.buttons_rect.y


def test_right_menu_three_panels_resize_proportionally():
    """Button block height tracks audio-row height times the number of rows."""
    backend_mock = MagicMock()
    backend_mock.move_history = []
    rm = RightMenu(pg.display.get_surface(), backend_mock, callbacks={})
    rm.set_rect(pg.Rect(0, 0, 250, 600))
    h1 = rm.moves_rect.height
    rm.set_rect(pg.Rect(0, 0, 250, 1200))
    h2 = rm.moves_rect.height
    assert h2 > h1
    n_rows = len(rm.buttons_provider())
    expected = n_rows * rm.audio_rect.height + max(n_rows - 1, 0) * 4
    assert abs(rm.buttons_rect.height - expected) <= n_rows * 2 + 4


def test_right_menu_routes_click_to_audio_panel():
    backend_mock = MagicMock()
    backend_mock.move_history = []
    sm = SoundManager(SOUNDS_DIR, enabled=True)
    panel = AudioPanel(pg.display.get_surface(), sm)
    rm = RightMenu(pg.display.get_surface(), backend_mock, callbacks={},
                   audio_panel=panel)
    rm.set_rect(pg.Rect(0, 0, 250, 800))
    rm.draw_menu()
    initial = sm.enabled
    rm.handle_click(panel.mute_rect.center)
    assert sm.enabled != initial
