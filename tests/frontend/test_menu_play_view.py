"""Play hero (PlayView) — the setup card the old StartMenu became. Carries the
behavior pins that outlive the widget swap: mode persistence, the build_config
payload contract, side selection (incl. the online side_preference path), the
FEN link visibility gate, reconnect banner arm/disarm, the locked-chip toast,
the CTA label swap, defaults seeding + the options-close sync, and the
view-owned time/side popovers (click-outside / Esc / re-click close, selection
does NOT auto-close, exit() cancels them)."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.menu import hero as hero_mod
from chessshootout.frontend.menu.hero import (
    COMING_SOON, CTA_BOTTOM, RECON_GAP, SIDE_OPTIONS, PlayView)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.infra import env
from tests.helpers import assert_pixel_color, make_app


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
    assert COMING_SOON == "Hold ya horses, I am cooking that..."
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


def test_summary_chips_are_fixed_width_and_left_packed(hero):
    """cp1: chips are sized to their WIDEST possible content and sit side by
    side, left-packed against the open hero column, so selection never resizes
    them."""
    gap = hero._s(12)
    assert hero._side_chip.x == hero._time_chip.right + gap
    assert hero._time_chip.right + hero._side_chip.width < hero._hero_rect.right


def test_side_chip_width_is_fixed_across_selection(app, hero):
    """cp1 (was: width tracked the label). The side chip is pinned to the widest
    label (RANDOM) so the chips row never jumps when an option is picked."""
    app.menu.handle_click(hero._side_chip.center)
    random_width = hero._side_chip.width
    app.menu.handle_click(hero._side_rects["white"].center)
    assert hero.selected_side == "white"
    assert hero._side_chip.width == random_width


def test_side_popover_and_chips_are_frozen_on_selection(app, hero):
    """cp1: the side popover's rect and the chips row are computed on open and
    frozen — clicking an option must not move or resize either."""
    app.menu.handle_click(hero._side_chip.center)
    popover_before = hero._side_popover.copy()
    time_chip_before = hero._time_chip.copy()
    side_chip_before = hero._side_chip.copy()
    rows_before = {k: r.copy() for k, r in hero._side_rects.items()}

    app.menu.handle_click(hero._side_rects["white"].center)

    assert hero._side_popover == popover_before
    assert hero._time_chip == time_chip_before
    assert hero._side_chip == side_chip_before
    assert {k: r.copy() for k, r in hero._side_rects.items()} == rows_before
    assert hero._side_open is True


def test_side_popover_lays_out_three_square_tiles_in_a_row(app, hero):
    """r4: WHITE / RANDOM / BLACK are three square tiles side by side, with a
    readout strip spanning the panel width below them."""
    app.menu.handle_click(hero._side_chip.center)
    tiles = [hero._side_rects[key] for _, key in SIDE_OPTIONS]
    assert {t.y for t in tiles} == {tiles[0].y}, "tiles share one row"
    assert [t.x for t in tiles] == sorted(t.x for t in tiles), "tiles run left to right"
    for t in tiles:
        assert abs(t.width - t.height) <= 1, "tiles are square"
    assert hero._side_readout.width == hero._side_popover.width
    assert hero._side_readout.top >= tiles[0].bottom, "readout sits below the tiles"
    assert hero._side_readout.bottom <= hero._side_popover.bottom


def test_side_readout_renders_label_then_selected_value(app, hero, monkeypatch):
    """r4: the bottom strip mirrors CHAMBERED — a dim 'SIDE' label then the
    selected value, big and bright, on the right."""
    app.menu.handle_click(hero._side_chip.center)
    app.menu.handle_click(hero._side_rects["black"].center)
    calls = []
    real = hero_mod.render_text
    monkeypatch.setattr(hero_mod, "render_text",
                        lambda f, t, c: calls.append((t, str(c))) or real(f, t, c))
    hero._draw_side_readout(app.window)
    assert [t for t, _ in calls] == ["SIDE", "BLACK"]
    assert calls[0][1] == str(Colors.text_muted), "SIDE is the dim label"
    assert calls[1][1] == str(Colors.text), "the selected value is bright"


def test_side_tile_click_selects_and_does_not_auto_close(app, hero):
    app.menu.handle_click(hero._side_chip.center)
    app.menu.handle_click(hero._side_rects["white"].center)
    assert hero.selected_side == "white"
    assert hero._side_open is True, "picking a side keeps the popover open"


def test_time_popover_stays_within_the_hero_column_when_it_fits():
    """P4 narrows the hero column with the right rail's cards, so the 1000x800
    module window (used by every other test here) no longer has room for the
    popover's fixed pixel width to sit inside the column -- it legitimately
    falls back to window-relative clamping there. Use a wide enough window to
    exercise the in-column-fit branch this test actually pins."""
    app = make_app(1600, 1000)
    app.draw_frame()
    hero = app.menu.play_view
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_popover.width <= hero._hero_rect.width
    assert hero._time_popover.left >= hero._hero_rect.left
    assert hero._time_popover.right <= hero._hero_rect.right


def test_time_popover_shrinks_to_fit_the_narrow_hero_column(app, hero):
    """cp2: at the narrower 1000x800 module window the popover's base pixel width
    exceeds the hero column, so it shrinks its own internal scale to fit inside
    the column instead of overflowing the rail. Its left edge anchors to the hero
    column left edge (aligned with the chips row above it)."""
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_popover.width <= hero._hero_rect.width
    assert hero._time_popover.left == hero._hero_rect.left
    assert hero._time_popover.right <= hero._hero_rect.right


def test_time_popover_stays_left_of_the_left_rail_and_selects_at_reduced_scale():
    """cp2: in a cramped 1000x700 window the popover must never extend left of the
    hero column (covering the left rail), must fit inside the column, and the
    shrunk picker must still be functional -- a chamber click changes the value."""
    app = make_app(1000, 700)
    app.draw_frame()
    hero = app.menu.play_view
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_popover.left >= hero._hero_rect.x
    assert hero._time_popover.left == hero._hero_rect.left
    assert hero._time_popover.width <= hero._hero_rect.width
    assert hero._time_popover.right <= hero._hero_rect.right
    hero._picker.handle_click(hero._picker.chamber_center(5))
    hero._picker.update(1000)
    assert hero._picker.selected_minutes == 30


def test_hero_lays_out_open_with_no_card(app, hero):
    """The restructured hero draws nothing across the open middle — content sits
    directly on the backdrop, so a mid-column point below the chips and above the
    CTA is untouched by the view's draw pass (there is no panel behind it)."""
    hero_rect = hero._hero_rect
    sentinel = (7, 137, 213)
    window = app.window
    window.fill(sentinel)
    hero.draw(window, app.menu._menu_layout)
    mid_y = (hero._side_chip.bottom + hero._cta_rect.top) // 2
    assert window.get_at((hero_rect.centerx, mid_y))[:3] == sentinel


def test_title_sits_at_the_hero_column_top_left(hero):
    assert hero._title_pos[0] == hero._hero_rect.x
    assert hero._title_pos[1] < hero._time_chip.y
    assert hero._tagline_pos[0] == hero._hero_rect.x
    assert hero._tagline_pos[1] > hero._title_pos[1]


def test_cta_is_full_width_and_pinned_to_the_hero_bottom(hero):
    """The CTA is the dominant anchor: full hero-column width, hugging the bottom
    of the column below the vast open middle."""
    assert hero._cta_rect.x == hero._hero_rect.x
    assert hero._cta_rect.width == hero._hero_rect.width
    assert hero._cta_rect.bottom <= hero._hero_rect.bottom
    assert hero._hero_rect.bottom - hero._cta_rect.bottom <= hero._s(CTA_BOTTOM) + 1
    assert hero._cta_rect.top > hero._side_chip.bottom


def test_fen_link_sits_above_the_bottom_pinned_cta(hero):
    """With the CTA pinned to the bottom, the FEN link has no room below it, so it
    rides just above the CTA (left-aligned at the hero column left edge)."""
    hero.selected_mode = "single_screen"
    assert hero._fen_above is True
    assert hero._fen_rect.bottom <= hero._cta_rect.top


def test_fen_link_is_left_aligned_at_the_hero_column_left(app, hero):
    """cp2: the FEN link moved from right- to left-aligned, sitting at the hero
    column's left edge."""
    hero.selected_mode = "single_screen"
    window = app.window
    window.fill((0, 0, 0))
    hero.draw(window, app.menu._menu_layout)
    fen = hero._fen_rect

    def painted(band):
        band = band.clip(window.get_rect())
        return any(window.get_at((x, y))[:3] != (0, 0, 0)
                   for x in range(band.x, band.right)
                   for y in range(band.y, band.bottom))

    left_band = pg.Rect(fen.x, fen.y, 70, fen.height)
    right_band = pg.Rect(fen.right - 70, fen.y, 70, fen.height)
    assert painted(left_band), "the FEN link text sits at the hero column's left edge"
    assert not painted(right_band), "and no longer hugs the right edge"


def test_hover_flag_toggles_on_synthetic_motion(hero):
    assert hero._hover_target is None
    assert hero.handle_motion(hero._cta_rect.center) is True
    assert hero._hover_target == "cta"
    hero.handle_motion((0, 0))
    assert hero._hover_target is None


def test_hover_flag_tracks_an_unlocked_mode_chip(hero):
    hero.handle_motion(hero._mode_rects["online"].center)
    assert hero._hover_target == "mode:online"


def test_locked_chip_ignores_hover(hero):
    hero.handle_motion(hero._mode_rects["bot"].center)
    assert hero._hover_target is None


def test_hover_and_press_are_inert_while_a_popover_is_open(app, hero):
    app.menu.handle_click(hero._time_chip.center)
    assert hero._time_open is True
    assert hero.handle_motion(hero._cta_rect.center) is False
    assert hero._hover_target is None
    assert hero.handle_press(hero._cta_rect.center) is False
    assert hero._press_target is None


def test_press_flag_set_on_press_and_cleared_on_release(hero):
    assert hero.handle_press(hero._cta_rect.center) is True
    assert hero._press_target == "cta"
    assert hero.handle_release(hero._cta_rect.center) is True
    assert hero._press_target is None


def test_press_off_target_returns_false_and_sets_nothing(hero):
    assert hero.handle_press((0, 0)) is False
    assert hero._press_target is None


def test_menu_screen_routes_motion_press_release_to_the_active_view(app, hero):
    app.menu.handle_motion(hero._cta_rect.center)
    assert hero._hover_target == "cta"
    app.menu.handle_press(hero._cta_rect.center)
    assert hero._press_target == "cta"
    app.menu.handle_release(hero._cta_rect.center)
    assert hero._press_target is None


def test_cta_press_fill_swaps_to_the_press_color(app, hero):
    hero.handle_motion(hero._cta_rect.center)
    hero.handle_press(hero._cta_rect.center)
    window = app.window
    window.fill((0, 0, 0))
    hero.draw(window, app.menu._menu_layout)
    assert_pixel_color(window, hero._cta_rect.x + 30, hero._cta_rect.centery,
                       Colors.accent_press, tol=10)


def test_reconnect_banner_shifts_the_title_block_down(app, hero):
    """The armed banner takes the title's slot at the top of the column, pushing
    the title (and everything below it) down by the banner height plus a gap."""
    base_title_y = hero._title_pos[1]
    app.menu.set_reconnect_available(True)
    assert hero._recon_rect.top < hero._title_pos[1]
    assert hero._title_pos[1] == pytest.approx(
        base_title_y + hero._recon_rect.height + hero._s(RECON_GAP), abs=1)
