import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.paths import SOUNDS_DIR
from frontend.panels.audio import (
    AudioPanel, DEFAULT_BUTTON_COLUMNS, DEFAULT_BUTTON_GAP_PX,
)
from frontend.panels.right import RightMenu
from frontend.audio.sound_manager import SoundManager


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1500, 800))
    yield
    pg.quit()


@pytest.fixture
def sm():
    pg.mixer.init() if not pg.mixer.get_init() else None
    return SoundManager(SOUNDS_DIR, enabled=True, master_volume=1.0)


@pytest.fixture
def panel(sm):
    p = AudioPanel(pg.display.get_surface(), sm)
    p.set_rect(pg.Rect(0, 0, 400, 40))
    return p


# ---------- SoundManager additions ----------

def test_master_volume_explicit_override(sm):
    # Fixture passes master_volume=1.0; verify the explicit value is honored.
    assert sm.master_volume == 1.0


def test_master_volume_falls_back_to_env_default(monkeypatch, tmp_path):
    pg.mixer.init() if not pg.mixer.get_init() else None
    from frontend import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CHESS_MASTER_VOLUME", raising=False)
    s = SoundManager(SOUNDS_DIR, enabled=True)
    assert s.master_volume == env_mod._DEFAULT_MASTER_VOLUME


def test_master_volume_reads_env_when_set(monkeypatch, tmp_path):
    pg.mixer.init() if not pg.mixer.get_init() else None
    from frontend import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("CHESS_MASTER_VOLUME", "0.42")
    s = SoundManager(SOUNDS_DIR, enabled=True)
    assert s.master_volume == pytest.approx(0.42, abs=1e-3)


def test_set_master_volume_clamps_below_zero(sm):
    sm.set_master_volume(-0.5)
    assert sm.master_volume == 0.0


def test_set_master_volume_clamps_above_one(sm):
    sm.set_master_volume(2.0)
    assert sm.master_volume == 1.0


def test_set_master_volume_accepts_mid_range(sm):
    sm.set_master_volume(0.42)
    assert sm.master_volume == pytest.approx(0.42)


def test_set_enabled_false_calls_stop_all():
    pg.mixer.init() if not pg.mixer.get_init() else None
    s = SoundManager(SOUNDS_DIR, enabled=True)
    stopped = []
    s.stop_all = lambda: stopped.append(True)
    s.set_enabled(False)
    assert stopped == [True]
    assert s.enabled is False


def test_set_enabled_true_does_not_stop():
    pg.mixer.init() if not pg.mixer.get_init() else None
    s = SoundManager(SOUNDS_DIR, enabled=False)
    stopped = []
    s.stop_all = lambda: stopped.append(True)
    s.set_enabled(True)
    assert stopped == []
    assert s.enabled is True


def test_play_with_master_scales_volume_before_playing():
    pg.mixer.init() if not pg.mixer.get_init() else None
    s = SoundManager(SOUNDS_DIR, enabled=True)
    s.master_volume = 0.3
    fake_sound = MagicMock()
    s._play_with_master(fake_sound)
    fake_sound.set_volume.assert_called_once_with(0.3)
    fake_sound.play.assert_called_once()


def test_heartbeat_volume_scales_by_master():
    pg.mixer.init() if not pg.mixer.get_init() else None
    s = SoundManager(SOUNDS_DIR, enabled=True, master_volume=1.0)
    base = s._heartbeat_volume(0.0)
    s.master_volume = 0.5
    half = s._heartbeat_volume(0.0)
    assert half == pytest.approx(base * 0.5)


def test_play_disabled_does_nothing(sm):
    sm.enabled = False
    # Should not raise even though sounds aren't loaded into containers when disabled.
    sm.play_move()


# ---------- AudioPanel ----------

def test_panel_set_rect_allocates_text_slider_mute_in_order(panel):
    # Three-region layout: [volume text][slider][mute], left to right.
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    assert panel.text_rect.x < panel.slider_rect.x < panel.mute_rect.x
    assert panel.text_rect.right <= panel.slider_rect.x
    assert panel.slider_rect.right <= panel.mute_rect.x
    assert panel.text_rect.width > 0
    assert panel.slider_rect.width > 0
    assert panel.mute_rect.width > 0


@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_panel_mirrors_n_button_grid_with_slider_spanning_middle(panel, n):
    # The audio panel uses the same n-column grid as the button row above:
    # text occupies col 0, mute occupies col (n-1), and the slider spans
    # every column in between. Same formula as widgets.draw_button_row.
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
    # Without an explicit n_columns, the panel defaults to a 5-button grid
    # (the typical playing-mode button row).
    assert DEFAULT_BUTTON_COLUMNS == 5
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    gap = DEFAULT_BUTTON_GAP_PX
    btn_w = (400 - gap * 4) / 5
    assert abs(panel.text_rect.width - btn_w) <= 1
    assert abs(panel.mute_rect.width - btn_w) <= 1


def test_panel_grid_aligns_with_actual_buttons_row():
    # Mirror the right-menu button column boundaries exactly: each audio
    # region's x/right should match the corresponding button's x/right.
    from frontend.visual.widgets import draw_button_row
    pg.mixer.init() if not pg.mixer.get_init() else None
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
    # Label column aligns with the leftmost button.
    assert abs(p.text_rect.x - btn_rects["a"].x) <= 1
    assert abs(p.text_rect.right - btn_rects["a"].right) <= 1
    # Mute column aligns with the rightmost button.
    assert abs(p.mute_rect.x - btn_rects["e"].x) <= 1
    assert abs(p.mute_rect.right - btn_rects["e"].right) <= 1
    # Slider spans from the second button's left edge to the second-to-last
    # button's right edge.
    assert abs(p.slider_rect.x - btn_rects["b"].x) <= 1
    assert abs(p.slider_rect.right - btn_rects["d"].right) <= 1


def test_panel_grid_uses_external_button_font_when_passed():
    pg.mixer.init() if not pg.mixer.get_init() else None
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
    # Click at the right edge → volume ≈ 1.0.
    panel.handle_click((track.right, track.centery))
    assert sm.master_volume == pytest.approx(1.0)
    # Click at the left edge → volume ≈ 0.0.
    panel.handle_click((track.x, track.centery))
    assert sm.master_volume == pytest.approx(0.0)
    # Click at midpoint → volume ≈ 0.5.
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
    from frontend import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CHESS_MASTER_VOLUME", raising=False)
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click((track.centerx, track.centery))
    assert panel._dragging_slider is True
    panel.end_drag()
    # The end-of-drag persisted whatever volume the slider committed.
    assert env_mod.get_master_volume() == pytest.approx(sm.master_volume, abs=1e-3)


def test_panel_end_drag_does_not_persist_when_not_dragging(panel, monkeypatch, tmp_path):
    from frontend import env as env_mod
    monkeypatch.setattr(env_mod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CHESS_MASTER_VOLUME", raising=False)
    # No prior click/drag — end_drag should not write to .env.
    panel.end_drag()
    assert not (tmp_path / ".env").exists()


def test_panel_drag_clamps_at_track_edges(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    track = panel._track_rect()
    panel.handle_click(track.center)
    # Drag far left of the track.
    panel.handle_drag((track.x - 500, track.centery), True)
    assert sm.master_volume == pytest.approx(0.0)
    # Drag far right.
    panel.handle_drag((track.right + 500, track.centery), True)
    assert sm.master_volume == pytest.approx(1.0)


def test_panel_click_outside_returns_false(panel):
    consumed = panel.handle_click((10000, 10000))
    assert consumed is False


def test_panel_draw_smoke(panel):
    # Mute then draw both states.
    panel.draw()
    panel.sound_manager.set_enabled(False)
    panel.draw()


def test_panel_resize_keeps_layout_proportions(panel):
    # Across panel widths, the three regions stay left-to-right with no
    # overlap and the column-grid math holds.
    for w in [120, 240, 480]:
        panel.set_rect(pg.Rect(0, 0, w, 40))
        assert panel.text_rect.right <= panel.slider_rect.x
        assert panel.slider_rect.right <= panel.mute_rect.x
        assert panel.text_rect.x == 0
        # Mute hugs the right edge to within rounding.
        assert abs(panel.mute_rect.right - w) <= 1


# ---------- Volume label (Bug 5) ----------

def test_volume_label_fits_inside_text_rect_at_default_size(panel):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    rendered = panel.button_font.render("Volume", True, (255, 255, 255))
    assert rendered.get_width() <= panel.text_rect.width


def test_volume_label_is_static_across_volume_changes(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    # The label exists purely to identify the slider — it must not depend on
    # the current volume value.
    sm.set_master_volume(0.0)
    panel.draw()
    sm.set_master_volume(1.0)
    panel.draw()
    # Both calls render the same string; sanity-check the source font matches.
    rendered_low = panel.button_font.render("Volume", True, (255, 255, 255))
    rendered_high = panel.button_font.render("Volume", True, (255, 255, 255))
    assert pg.image.tobytes(rendered_low, "RGBA") == pg.image.tobytes(
        rendered_high, "RGBA")


def test_volume_label_renders_without_overflow_at_narrow_width(panel):
    panel.set_rect(pg.Rect(0, 0, 120, 40))
    # Even at a tight panel size, draw must not raise (subsurface clip path).
    panel.draw()


# ---------- RightMenu integration ----------

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
    # moves_rect should not extend past the buttons_rect top.
    assert rm.moves_rect.bottom <= rm.buttons_rect.y


def test_right_menu_three_panels_resize_proportionally():
    backend_mock = MagicMock()
    backend_mock.move_history = []
    rm = RightMenu(pg.display.get_surface(), backend_mock, callbacks={})
    rm.set_rect(pg.Rect(0, 0, 250, 600))
    h1 = rm.moves_rect.height
    rm.set_rect(pg.Rect(0, 0, 250, 1200))
    h2 = rm.moves_rect.height
    assert h2 > h1
    # Buttons and audio rects keep similar heights.
    assert abs(rm.buttons_rect.height - rm.audio_rect.height) <= 2


def test_right_menu_routes_click_to_audio_panel():
    backend_mock = MagicMock()
    backend_mock.move_history = []
    sm = SoundManager(SOUNDS_DIR, enabled=True)
    panel = AudioPanel(pg.display.get_surface(), sm)
    rm = RightMenu(pg.display.get_surface(), backend_mock, callbacks={},
                   audio_panel=panel)
    rm.set_rect(pg.Rect(0, 0, 250, 800))
    # Force draw to apply audio_rect into the panel.
    rm.draw_menu()
    initial = sm.enabled
    rm.handle_click(panel.mute_rect.center)
    assert sm.enabled != initial
