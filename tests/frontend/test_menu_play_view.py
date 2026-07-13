"""Play hero (PlayView) — the setup card the old StartMenu became. Carries the
behavior pins that outlive the widget swap: mode persistence, the build_config
payload contract, side selection (incl. the online side_preference path), the
FEN link visibility gate, reconnect banner arm/disarm, the locked-chip toast,
the CTA label swap, defaults seeding + the options-close sync, and the
view-owned time/side popovers (click-outside / Esc / re-click close, selection
does NOT auto-close, exit() cancels them)."""

import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.menu.hero import COMING_SOON, PlayView
from chessshootout.infra import env
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)

_MODE_ENV = ("CHESS_DEFAULT_TC", "CHESS_DEFAULT_INCREMENT", "CHESS_LAST_MODE", "CHESS_NICKNAME")


def _clean(monkeypatch):
    for var in _MODE_ENV:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def app():
    application = make_app(1000, 800)
    application.draw_frame()
    return application


@pytest.fixture
def hero(app):
    return app.menu.play_view


def test_defaults(monkeypatch):
    _clean(monkeypatch)
    application = make_app(1000, 800)
    hero = application.menu.play_view
    assert hero.selected_mode == "single_screen"
    assert hero.selected_time_minutes == 10
    assert hero.selected_increment_seconds == 5
    assert hero.selected_side == "random"


def test_last_mode_persists_when_selectable(monkeypatch, app):
    _clean(monkeypatch)
    monkeypatch.setenv("CHESS_LAST_MODE", "online")
    assert PlayView(app).selected_mode == "online"


def test_locked_last_mode_falls_back_to_local(monkeypatch, app):
    _clean(monkeypatch)
    monkeypatch.setenv("CHESS_LAST_MODE", "bot")
    assert PlayView(app).selected_mode == "single_screen"


def test_build_config_payload_contract(hero):
    assert set(hero.build_config()) == {
        "mode", "nickname", "time_minutes", "increment_seconds", "side"}


def test_build_config_nickname_reads_env(monkeypatch, app):
    monkeypatch.setattr(env, "get_nickname", lambda: "Hikaru")
    assert app.menu.play_view.build_config()["nickname"] == "Hikaru"


def test_applies_env_default_time(monkeypatch, app):
    _clean(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "15")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    hero = PlayView(app)
    assert hero.selected_time_minutes == 15
    assert hero.selected_increment_seconds == 10


def test_thirty_minute_default_now_seeds(monkeypatch, app):
    _clean(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "30")
    assert PlayView(app).selected_time_minutes == 30


def test_infinity_default_forces_zero_increment(monkeypatch, app):
    _clean(monkeypatch)
    monkeypatch.setenv("CHESS_DEFAULT_TC", "∞")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    hero = PlayView(app)
    assert hero.selected_time_minutes is None
    assert hero.selected_increment_seconds == 0


def test_apply_default_time_settings_overrides_current(monkeypatch, hero):
    hero.selected_time_minutes = 5
    hero.selected_increment_seconds = 2
    monkeypatch.setenv("CHESS_DEFAULT_TC", "15")
    monkeypatch.setenv("CHESS_DEFAULT_INCREMENT", "10")
    hero.apply_default_time_settings()
    assert hero.selected_time_minutes == 15
    assert hero.selected_increment_seconds == 10


def test_mode_chip_click_selects_unlocked_mode(app, hero):
    app.menu.handle_click(hero._mode_rects["online"].center)
    assert hero.selected_mode == "online"


def test_locked_chip_toasts_coming_soon(app, hero):
    app.menu.handle_click(hero._mode_rects["bot"].center)
    assert hero.selected_mode != "bot"
    assert app.toast.message == COMING_SOON


def test_cta_label_swaps_for_online(hero):
    hero.selected_mode = "single_screen"
    assert hero.cta_label() == "START MATCH"
    hero.selected_mode = "online"
    assert hero.cta_label() == "FIND MATCH"


def test_cta_starts_the_selected_mode(app, hero):
    started = []
    app._on_start_game = lambda config: started.append(config)
    hero.selected_mode = "single_screen"
    app.menu.handle_click(hero._cta_rect.center)
    assert started and started[0]["mode"] == "single_screen"


def test_side_popover_selection_updates_config(app, hero):
    app.menu.handle_click(hero._side_chip.center)
    assert hero._side_open is True
    app.menu.handle_click(hero._side_rects["black"].center)
    assert hero.selected_side == "black"
    assert hero.build_config()["side"] == "black"


def test_side_selection_available_in_online_mode(app, hero):
    hero.selected_mode = "online"
    app.menu.handle_click(hero._side_chip.center)
    app.menu.handle_click(hero._side_rects["white"].center)
    assert hero.build_config()["side"] == "white"


def test_fen_link_opens_modal_in_local_mode(app, hero):
    hero.selected_mode = "single_screen"
    app.menu.handle_click(hero._fen_rect.center)
    assert app.menu.fen_input_modal.is_visible() is True


def test_fen_link_inert_in_online_mode(app, hero):
    hero.selected_mode = "online"
    assert app.menu.handle_click(hero._fen_rect.center) is False
    assert app.menu.fen_input_modal.is_visible() is False


def test_reconnect_banner_arms_and_button_fires(app, hero):
    fired = []
    app.coordinator.reconnect = lambda: fired.append(True)
    app.menu.set_reconnect_available(True)
    assert hero.reconnect_available is True
    assert hero._recon_button.width > 0
    app.menu.handle_click(hero._recon_button.center)
    assert fired == [True]


def test_reconnect_banner_disarms(app, hero):
    app.menu.set_reconnect_available(True)
    assert hero._recon_button.width > 0
    app.menu.set_reconnect_available(False)
    assert hero.reconnect_available is False
    assert hero._recon_button.width == 0


def test_time_chip_toggles_the_popover(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_open is True
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_open is False


def test_click_outside_closes_the_popover(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_popover.collidepoint(hero._title_pos) is False
    app.menu.handle_click(hero._title_pos)
    assert hero._time_open is False


def test_escape_closes_the_popover_first(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    assert hero.escape() is True
    assert hero._time_open is False


def test_selecting_a_chamber_does_not_auto_close(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    hero._picker.handle_click(hero._picker.chamber_center(5))
    assert hero._time_open is True


def test_exit_cancels_open_popover(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_open is True
    hero.exit()
    assert hero._time_open is False
    assert hero.is_visible() is False


def test_clicking_the_side_chip_closes_an_open_time_popover(app, hero):
    """Clicking anywhere outside the open popover (including the other chip)
    closes it — switching to the side popover is then a fresh click."""
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_open is True
    app.menu.handle_click(hero._side_chip.center)
    assert hero._time_open is False
    assert hero._side_open is False
    app.menu.handle_click(hero._side_chip.center)
    assert hero._side_open is True


def test_summary_chips_are_content_sized_and_left_aligned(hero):
    """v2.9.0: no more half-width wells — chips hug their own content and sit
    side by side, not stretched across the hero card."""
    gap = hero._s(12)
    assert hero._side_chip.x == hero._time_chip.right + gap
    assert hero._time_chip.right + hero._side_chip.width < hero._panel.right


def test_side_chip_width_tracks_the_selected_label(app, hero):
    """RANDOM renders two pawn icons plus a longer word than WHITE/BLACK, so
    its chip must be wider — width is recomputed on every selection change."""
    app.menu.handle_click(hero._side_chip.center)
    random_width = hero._side_chip.width
    app.menu.handle_click(hero._side_rects["white"].center)
    assert hero._side_chip.width < random_width


def test_time_popover_stays_within_the_hero_card_when_it_fits(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_popover.width <= hero._panel.width
    assert hero._time_popover.left >= hero._panel.left
    assert hero._time_popover.right <= hero._panel.right
