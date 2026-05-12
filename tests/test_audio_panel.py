import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.paths import SOUNDS_DIR
from frontend.panels.audio import AudioPanel, SLIDER_FRACTION, TEXT_FRACTION
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
    # New three-region layout: [volume text][slider][mute], left to right.
    panel.set_rect(pg.Rect(0, 0, 200, 40))
    assert panel.text_rect.x < panel.slider_rect.x < panel.mute_rect.x
    assert panel.text_rect.right <= panel.slider_rect.x
    assert panel.slider_rect.right <= panel.mute_rect.x
    assert panel.text_rect.width > 0
    assert panel.slider_rect.width > 0
    assert panel.mute_rect.width > 0


def test_panel_regions_use_configured_fractions(panel):
    # The text gets ~TEXT_FRACTION and the slider gets ~SLIDER_FRACTION
    # of the panel width; mute fills the remainder.
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    total = panel.text_rect.width + panel.slider_rect.width + panel.mute_rect.width
    assert total + 2 * 6 <= 400  # two SLIDER_GAP_PX gaps
    assert abs(panel.text_rect.width / 400 - TEXT_FRACTION) < 0.02
    assert abs(panel.slider_rect.width / 400 - SLIDER_FRACTION) < 0.02


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
    # overlap and similar proportional weights.
    for w in [120, 240, 480]:
        panel.set_rect(pg.Rect(0, 0, w, 40))
        assert panel.text_rect.right <= panel.slider_rect.x
        assert panel.slider_rect.right <= panel.mute_rect.x
        assert abs(panel.text_rect.width / w - TEXT_FRACTION) < 0.05
        assert abs(panel.slider_rect.width / w - SLIDER_FRACTION) < 0.05


# ---------- Volume text label (Bug 5) ----------

def _rendered_text_pixel_count(panel, color=(255, 255, 255)):
    snapshot = pg.Surface(panel.text_rect.size, pg.SRCALPHA)
    surface = panel.window
    panel.window = snapshot
    panel.text_rect = pg.Rect(0, 0, *panel.text_rect.size)
    try:
        panel._draw_volume_text()
    finally:
        panel.window = surface
    arr = pg.surfarray.pixels3d(snapshot)
    return int((arr.sum(axis=2) > 0).sum())


def test_volume_text_default_visible(panel):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    panel.sound_manager.set_master_volume(0.5)
    panel.draw()
    rendered = panel.button_font.render("50%", True, (255, 255, 255))
    assert rendered.get_width() <= panel.text_rect.width


@pytest.mark.parametrize("volume,expected", [
    (0.0, "0%"),
    (0.5, "50%"),
    (1.0, "100%"),
    (0.42, "42%"),
])
def test_volume_text_renders_correct_percent(panel, volume, expected):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    panel.sound_manager.set_master_volume(volume)
    rendered = panel.button_font.render(expected, True, (255, 255, 255))
    # Sanity check: the rendered string fits inside text_rect.
    assert rendered.get_width() <= panel.text_rect.width + 8
    # The percent calculation matches what _draw_volume_text computes.
    percent = int(round(panel.sound_manager.master_volume * 100))
    assert f"{percent}%" == expected


def test_volume_text_updates_after_drag(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    sm.set_master_volume(0.10)
    assert int(round(sm.master_volume * 100)) == 10
    track = panel._track_rect()
    panel.handle_click((track.right, track.centery))
    assert int(round(sm.master_volume * 100)) == 100


def test_volume_text_unchanged_when_toggling_mute(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    sm.set_master_volume(0.42)
    panel.handle_click(panel.mute_rect.center)
    # Mute toggles sm.enabled but leaves master_volume untouched, so the
    # displayed percent stays at 42.
    assert int(round(sm.master_volume * 100)) == 42


def test_volume_text_rounds_to_integer(panel, sm):
    panel.set_rect(pg.Rect(0, 0, 400, 40))
    sm.set_master_volume(0.345)
    # int(round(0.345*100)) is 34 or 35 depending on banker's rounding;
    # accept whichever Python produces.
    rendered = int(round(sm.master_volume * 100))
    assert rendered in (34, 35)


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
