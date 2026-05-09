"""M16: Online UX layer.

Animation duration scales with the time control, the wait modal shows
elapsed time during search and "Match found!" for 500 ms before the game
starts, the reconnecting overlay surfaces only while the client is
reconnecting, and transient errors show a toast (not a modal).
"""
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.frontend import (
    ANIM_MS_DEFAULT, ANIM_MS_MIN, ANIM_MS_MAX, MATCH_FOUND_HOLD_MS,
    Frontend, compute_animation_ms,
)
from frontend.modals.reconnecting import ReconnectingModal
from frontend.online.events import (
    ONLINE_HARD_FAILURE_LABELS, ONLINE_HARD_FAILURE_REASONS,
    ONLINE_TRANSIENT_REASON_LABELS,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((600, 400))
    yield
    pg.quit()


@pytest.fixture
def frontend():
    fe = Frontend(900, 600)
    yield fe
    # Re-establish a display so subsequent module-scope tests still find one.
    pg.display.set_mode((600, 400))


# ---- compute_animation_ms ----------------------------------------------------

def test_anim_ms_default_when_no_clock():
    # No clock → use the default; menu / casual play still feels snappy.
    assert compute_animation_ms(None) == ANIM_MS_DEFAULT
    assert compute_animation_ms(0) == ANIM_MS_DEFAULT


def test_anim_ms_clamps_low_for_bullet_time_control():
    # Bullet 1+0 (60s) → 0.5 * 60 = 30, clamped up to ANIM_MS_MIN.
    assert compute_animation_ms(60) == ANIM_MS_MIN


def test_anim_ms_in_range_for_blitz():
    # Blitz 5+0 (300s) → 0.5 * 300 = 150 → in range as-is.
    assert compute_animation_ms(300) == 150
    assert ANIM_MS_MIN <= compute_animation_ms(300) <= ANIM_MS_MAX


def test_anim_ms_clamps_high_for_long_time_control():
    # Rapid 10+0 (600s) → 0.5 * 600 = 300, clamped down to ANIM_MS_MAX.
    assert compute_animation_ms(600) == ANIM_MS_MAX
    # And further: classical (3600s) still capped at the max.
    assert compute_animation_ms(3600) == ANIM_MS_MAX


# ---- _reset_to_new_game wires animation duration to the time control --------

def test_reset_to_new_game_sets_anim_ms_from_time_control(frontend):
    frontend._time_control = (300, 0)
    frontend._reset_to_new_game()
    assert frontend.board.animation_duration_ms == compute_animation_ms(300)


def test_reset_to_new_game_uses_default_when_no_clock(frontend):
    frontend._time_control = None
    frontend._reset_to_new_game()
    assert frontend.board.animation_duration_ms == ANIM_MS_DEFAULT


# ---- ReconnectingModal -------------------------------------------------------

def test_reconnecting_modal_starts_hidden():
    m = ReconnectingModal(pg.display.get_surface())
    assert not m.is_visible()


def test_reconnecting_modal_show_makes_visible_and_caches_callback():
    m = ReconnectingModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    cancelled = []
    m.show(on_cancel=lambda: cancelled.append(True))
    assert m.is_visible()
    m.draw()  # populates button_rects
    m.handle_click(m.button_rects["cancel"].center)
    assert cancelled == [True]


def test_reconnecting_modal_subtitle_renders_without_crash():
    m = ReconnectingModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show(on_cancel=lambda: None)
    m.set_subtitle("Trying to reconnect…")
    m.draw()


# ---- Frontend integration with reconnecting overlay -------------------------

def test_reconnecting_overlay_appears_when_client_state_is_reconnecting(frontend):
    fake_client = SimpleNamespace(state="reconnecting")
    frontend.online_client = fake_client
    frontend._update_online_phase()
    assert frontend.reconnecting_modal.is_visible()


def test_reconnecting_overlay_hides_when_client_recovers(frontend):
    fake_client = SimpleNamespace(state="reconnecting")
    frontend.online_client = fake_client
    frontend._update_online_phase()
    assert frontend.reconnecting_modal.is_visible()
    fake_client.state = "connected"
    frontend._update_online_phase()
    assert not frontend.reconnecting_modal.is_visible()


def test_reconnecting_overlay_cancel_calls_abandon(frontend, monkeypatch):
    abandoned = []
    monkeypatch.setattr(frontend, "_abandon_online_game",
                         lambda: abandoned.append(True))
    fake_client = SimpleNamespace(state="reconnecting")
    frontend.online_client = fake_client
    frontend._update_online_phase()
    frontend.reconnecting_modal.draw()
    frontend.reconnecting_modal.handle_click(
        frontend.reconnecting_modal.button_rects["cancel"].center,
    )
    assert abandoned == [True]


# ---- Wait modal phases (search elapsed counter, then match-found hold) ------

def test_wait_modal_subtitle_shows_elapsed_seconds(frontend, monkeypatch):
    fake_now = [10000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    frontend.wait_modal.show("Searching for opponent…", on_cancel=lambda: None)
    frontend._wait_started_at_ms = fake_now[0]
    fake_now[0] += 7 * 1000
    frontend._update_online_phase()
    assert frontend.wait_modal.subtitle == "00:07"
    fake_now[0] += 60 * 1000
    frontend._update_online_phase()
    assert frontend.wait_modal.subtitle == "01:07"


def test_match_found_payload_held_for_500ms_before_start(frontend, monkeypatch):
    fake_now = [50000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    started = []
    monkeypatch.setattr(frontend, "_start_online_game",
                         lambda payload: started.append(payload))
    frontend.wait_modal.show("Searching…", on_cancel=lambda: None)
    frontend._wait_started_at_ms = fake_now[0]

    payload = {"your_color": "white", "white_name": "A", "black_name": "B",
               "time_minutes": 5, "increment_seconds": 0}
    frontend._begin_match_found_transition(payload)

    # During the hold the modal should display the celebration subtitle
    # and the game should not have started yet.
    assert frontend.wait_modal.subtitle == "Match found!"
    fake_now[0] += MATCH_FOUND_HOLD_MS - 50
    frontend._update_online_phase()
    assert started == []

    # Once the hold elapses, _start_online_game fires exactly once.
    fake_now[0] += 100
    frontend._update_online_phase()
    assert started == [payload]
    # And subsequent ticks don't fire it again.
    fake_now[0] += 1000
    frontend._update_online_phase()
    assert started == [payload]


def test_match_found_transition_plays_online_game_start_sound(frontend):
    plays = []
    frontend.sound_manager.play_online_game_start = lambda: plays.append(True)
    frontend.wait_modal.show("Searching…", on_cancel=lambda: None)
    frontend._wait_started_at_ms = pg.time.get_ticks()
    frontend._begin_match_found_transition({"your_color": "white",
                                             "white_name": "A",
                                             "black_name": "B",
                                             "time_minutes": 5,
                                             "increment_seconds": 0})
    assert plays == [True]


# ---- Toast for transient errors / modal for hard failures -------------------

def test_hard_failure_error_shows_confirm_modal(frontend):
    frontend._handle_online_error({"reason": "server_unreachable"})
    assert frontend.confirm_modal.is_visible()
    # And the toast did NOT eat the event.
    assert frontend.toast.is_visible() is False


def test_hard_failure_modal_uses_friendly_label(frontend):
    # Raw engine codes shouldn't bleed into the UI — show readable text.
    frontend._handle_online_error({"reason": "reconnect_failed"})
    assert frontend.confirm_modal.is_visible()
    assert frontend.confirm_modal.title == ONLINE_HARD_FAILURE_LABELS["reconnect_failed"]
    # Specifically, the engine code itself must not surface in the title.
    assert "reconnect_failed" not in frontend.confirm_modal.title


def test_unknown_hard_failure_falls_back_to_generic_label(frontend):
    frontend._handle_online_error({"reason": "http_503"})
    assert frontend.confirm_modal.is_visible()
    assert frontend.confirm_modal.title == "Server unreachable"


def test_http_prefixed_error_treated_as_hard_failure(frontend):
    frontend._handle_online_error({"reason": "http_503"})
    assert frontend.confirm_modal.is_visible()


def test_transient_error_shows_toast_not_modal(frontend):
    # rate_limited maps to a friendly label, not a modal.
    frontend._handle_online_error({"reason": "rate_limited"})
    assert frontend.toast.is_visible()
    assert frontend.toast.message == ONLINE_TRANSIENT_REASON_LABELS["rate_limited"]
    assert not frontend.confirm_modal.is_visible()


def test_unknown_transient_reason_falls_through_to_raw_label(frontend):
    frontend._handle_online_error({"reason": "weird_thing"})
    assert frontend.toast.is_visible()
    assert frontend.toast.message == "weird_thing"


def test_game_state_errors_produce_neither_modal_nor_toast(frontend):
    frontend._handle_online_error({"reason": "not_your_turn"})
    assert not frontend.confirm_modal.is_visible()
    assert not frontend.toast.is_visible()


def test_hard_failure_set_is_well_formed():
    # Sanity: keep this set in sync if the server adds new hard reasons.
    assert "server_unreachable" in ONLINE_HARD_FAILURE_REASONS
    assert "reconnect_failed" in ONLINE_HARD_FAILURE_REASONS


# ---- Main-menu redesign: board hidden when in menu mode ---------------------

def test_menu_mode_skips_board_draw(frontend, monkeypatch):
    drew = []
    monkeypatch.setattr(frontend.board, "draw_board",
                         lambda: drew.append(True))
    frontend.mode = "menu"
    frontend.draw_frame()
    assert drew == []
    # Switching back to a game causes the board to draw again.
    frontend.mode = "single_screen"
    frontend.draw_frame()
    assert drew == [True]


def test_start_menu_centered_on_window_not_board(frontend):
    # The start menu modal should be centered on the window so it doesn't
    # appear off-center while the board is hidden.
    rect = frontend.start_menu._outer
    win_w, win_h = frontend.window.get_size()
    assert abs(rect.centerx - win_w / 2) <= 1
    assert abs(rect.centery - win_h / 2) <= 1


# ---- Modal flex: window-centered in menu mode, board-centered in-game --------

def test_menu_mode_centers_flex_modals_on_window(frontend):
    # In menu mode (board hidden), the flex modals (server/wait/fen) must
    # share the start menu's center — anything else looks misaligned.
    frontend.mode = "menu"
    frontend._compute_layout()
    win_w, _ = frontend.window.get_size()
    assert abs(frontend.fen_input_modal.rect.centerx - win_w / 2) <= 1
    assert abs(frontend.wait_modal.rect.centerx - win_w / 2) <= 1
    assert abs(frontend.server_modal.rect.centerx - win_w / 2) <= 1


def _board_centerx(board):
    return board.board_offset_x + board.cell_size * board.SIZE / 2


def test_game_mode_centers_flex_modals_on_board(frontend):
    # Once the board is visible, those same modals follow the board so the
    # user's eyes don't have to jump from menu-center to board-center.
    from backend.match import SINGLE_SCREEN
    frontend.mode = SINGLE_SCREEN
    frontend._compute_layout()
    board_cx = _board_centerx(frontend.board)
    # Allow 1 px slack — board_size_px is divided by SIZE (8) and floored,
    # so the integer offset can sit within a pixel of the geometric center.
    assert abs(frontend.fen_input_modal.rect.centerx - board_cx) <= 4
    assert abs(frontend.wait_modal.rect.centerx - board_cx) <= 4
    assert abs(frontend.server_modal.rect.centerx - board_cx) <= 4


def test_mode_change_relays_modal_rects_via_draw_frame(frontend):
    # Switching modes between frames should re-layout flex modals
    # automatically — no explicit caller needs to remember to do it.
    from backend.match import SINGLE_SCREEN
    frontend.mode = "menu"
    frontend._compute_layout()
    win_w, _ = frontend.window.get_size()
    assert abs(frontend.wait_modal.rect.centerx - win_w / 2) <= 1
    frontend.mode = SINGLE_SCREEN
    frontend.draw_frame()
    board_cx = _board_centerx(frontend.board)
    assert abs(frontend.wait_modal.rect.centerx - board_cx) <= 4
