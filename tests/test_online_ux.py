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
from frontend.visual.colors import Colors
from frontend.modals.reconnecting import ReconnectingModal
from frontend.online.events import (
    NOT_YOUR_TURN_TOASTS, ONLINE_HARD_FAILURE_LABELS,
    ONLINE_HARD_FAILURE_REASONS, ONLINE_TRANSIENT_REASON_LABELS,
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
    pg.display.set_mode((600, 400))


@pytest.mark.parametrize(
    "seconds, expected",
    [
        pytest.param(None, ANIM_MS_DEFAULT, id="no_clock_uses_default"),
        pytest.param(0, ANIM_MS_DEFAULT, id="zero_clock_uses_default"),
        pytest.param(60, ANIM_MS_MIN, id="bullet_1plus0_clamps_to_min"),
        pytest.param(300, 150, id="blitz_5plus0_in_range_as_is"),
        pytest.param(600, ANIM_MS_MAX, id="rapid_10plus0_clamps_to_max"),
        pytest.param(3600, ANIM_MS_MAX, id="classical_still_capped_at_max"),
    ],
)
def test_compute_animation_ms(seconds, expected):
    assert compute_animation_ms(seconds) == expected


@pytest.mark.parametrize(
    "time_control, expected",
    [
        pytest.param((300, 0), compute_animation_ms(300), id="time_control_drives_anim_ms"),
        pytest.param(None, ANIM_MS_DEFAULT, id="no_clock_uses_default"),
    ],
)
def test_reset_to_new_game_sets_anim_ms(frontend, time_control, expected):
    frontend._time_control = time_control
    frontend._reset_to_new_game()
    assert frontend.board.animation_duration_ms == expected


def test_reconnecting_modal_starts_hidden():
    m = ReconnectingModal(pg.display.get_surface())
    assert not m.is_visible()


def test_reconnecting_modal_show_makes_visible_and_caches_callback():
    m = ReconnectingModal(pg.display.get_surface())
    m.set_rect(pg.Rect(0, 0, 400, 220))
    cancelled = []
    m.show(on_cancel=lambda: cancelled.append(True))
    assert m.is_visible()
    m.draw()
    m.handle_click(m.button_rects["cancel"].center)
    assert cancelled == [True]


def test_reconnecting_modal_subtitle_renders_visible_pixels():
    """The subtitle text is actually blitted: white glyph pixels land on the
    modal that were absent before set_subtitle (regression guard for a
    silently-dropped subtitle)."""
    win = pg.display.get_surface()
    m = ReconnectingModal(win)
    m.set_rect(pg.Rect(0, 0, 400, 220))
    m.show(on_cancel=lambda: None)
    subtitle = "Trying to reconnect…"

    rendered = m.subtitle_font.render(subtitle, True, (255, 255, 255))
    assert rendered.get_width() > 0 and rendered.get_height() > 0

    text_rgb = pg.Color(Colors.white)[:3]

    def text_pixels():
        return sum(
            1
            for x in range(m.rect.width)
            for y in range(m.rect.height)
            if win.get_at((x, y))[:3] == text_rgb
        )

    win.fill((0, 0, 0))
    m.draw()
    without_subtitle = text_pixels()

    win.fill((0, 0, 0))
    m.set_subtitle(subtitle)
    m.draw()
    with_subtitle = text_pixels()

    assert with_subtitle > without_subtitle


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

    assert frontend.wait_modal.subtitle == "Match found!"
    fake_now[0] += MATCH_FOUND_HOLD_MS - 50
    frontend._update_online_phase()
    assert started == []

    fake_now[0] += 100
    frontend._update_online_phase()
    assert started == [payload]
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


@pytest.mark.parametrize(
    "reason, expected_title",
    [
        pytest.param("server_unreachable",
                     ONLINE_HARD_FAILURE_LABELS["server_unreachable"],
                     id="server_unreachable_friendly_label"),
        pytest.param("reconnect_failed",
                     ONLINE_HARD_FAILURE_LABELS["reconnect_failed"],
                     id="reconnect_failed_friendly_label"),
        pytest.param("http_503", "Server unreachable",
                     id="http_prefixed_falls_back_to_generic"),
    ],
)
def test_hard_failure_shows_confirm_modal_with_friendly_label(
    frontend, reason, expected_title,
):
    """Hard failures surface a confirm modal with readable text (no raw engine
    code in the title) and never eat the event into a toast."""
    frontend._handle_online_error({"reason": reason})
    assert frontend.confirm_modal.is_visible()
    assert frontend.confirm_modal.title == expected_title
    assert reason not in frontend.confirm_modal.title
    assert frontend.toast.is_visible() is False


def test_room_lost_shows_new_search_modal(frontend, monkeypatch):
    restart_calls = []
    monkeypatch.setattr(frontend, "_restart_online_search",
                        lambda: restart_calls.append(True))
    frontend._handle_online_error({"reason": "room_lost"})
    assert frontend.confirm_modal.is_visible()
    assert "Server restarted" in frontend.confirm_modal.title
    assert frontend.confirm_modal.yes_label == "New Search"
    frontend.confirm_modal.draw()
    frontend.confirm_modal.handle_click(
        frontend.confirm_modal.button_rects["yes"].center,
    )
    assert restart_calls == [True]


def test_room_lost_cancel_returns_to_menu(frontend, monkeypatch):
    abandoned = []
    monkeypatch.setattr(frontend, "_abandon_online_game",
                        lambda: abandoned.append(True))
    frontend._handle_online_error({"reason": "room_lost"})
    frontend.confirm_modal.draw()
    frontend.confirm_modal.handle_click(
        frontend.confirm_modal.button_rects["no"].center,
    )
    assert abandoned == [True]


@pytest.mark.parametrize(
    "reason, expected_message",
    [
        pytest.param("rate_limited",
                     ONLINE_TRANSIENT_REASON_LABELS["rate_limited"],
                     id="known_reason_maps_to_friendly_label"),
        pytest.param("weird_thing", "weird_thing",
                     id="unknown_reason_falls_through_to_raw"),
    ],
)
def test_transient_error_shows_toast_not_modal(frontend, reason, expected_message):
    frontend._handle_online_error({"reason": reason})
    assert frontend.toast.is_visible()
    assert frontend.toast.message == expected_message
    assert not frontend.confirm_modal.is_visible()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"reason": "not_your_turn"}, id="bare_not_your_turn"),
        pytest.param({"reason": "not_your_turn", "msg_type": "weird_action"},
                     id="not_your_turn_unknown_msg_type"),
    ],
)
def test_not_your_turn_without_known_msg_type_stays_silent(frontend, payload):
    """A not_your_turn reply with no recognised msg_type is purely defensive
    (the client already gates by turn) — it must show neither modal nor toast."""
    frontend._handle_online_error(payload)
    assert not frontend.confirm_modal.is_visible()
    assert not frontend.toast.is_visible()


@pytest.mark.parametrize(
    "msg_type",
    [
        pytest.param("draw_offer", id="draw_offer_explains_own_turn_only"),
        pytest.param("takeback_request", id="takeback_explains_after_move_only"),
    ],
)
def test_not_your_turn_with_known_msg_type_shows_toast(frontend, msg_type):
    """When the rejected action is tagged with a msg_type the client knows, a
    friendly toast explains why it was rejected — and no modal pops."""
    frontend._handle_online_error({"reason": "not_your_turn", "msg_type": msg_type})
    assert frontend.toast.is_visible()
    assert frontend.toast.message == NOT_YOUR_TURN_TOASTS[msg_type]
    assert not frontend.confirm_modal.is_visible()


def test_hard_failure_set_is_well_formed():
    assert "server_unreachable" in ONLINE_HARD_FAILURE_REASONS
    assert "reconnect_failed" in ONLINE_HARD_FAILURE_REASONS


def test_menu_mode_skips_board_draw(frontend, monkeypatch):
    drew = []
    monkeypatch.setattr(frontend.board, "draw_board",
                        lambda: drew.append(True))
    frontend.mode = "menu"
    frontend.draw_frame()
    assert drew == []
    frontend.mode = "single_screen"
    frontend.draw_frame()
    assert drew == [True]


def test_start_menu_centered_on_window_not_board(frontend):
    rect = frontend.start_menu._outer
    win_w, win_h = frontend.window.get_size()
    top = frontend.chrome.HEIGHT
    content_center_y = top + (win_h - top) / 2
    assert abs(rect.centerx - win_w / 2) <= 1
    assert abs(rect.centery - content_center_y) <= 1


def test_menu_mode_centers_flex_modals_on_window(frontend):
    frontend.mode = "menu"
    frontend._compute_layout()
    win_w, _ = frontend.window.get_size()
    assert abs(frontend.fen_input_modal.rect.centerx - win_w / 2) <= 1
    assert abs(frontend.wait_modal.rect.centerx - win_w / 2) <= 1
    assert abs(frontend.server_modal.rect.centerx - win_w / 2) <= 1


def _board_centerx(board):
    return board.board_offset_x + board.cell_size * board.SIZE / 2


def test_game_mode_centers_flex_modals_on_board(frontend):
    from backend.match import SINGLE_SCREEN
    frontend.mode = SINGLE_SCREEN
    frontend._compute_layout()
    board_cx = _board_centerx(frontend.board)
    assert abs(frontend.fen_input_modal.rect.centerx - board_cx) <= 4
    assert abs(frontend.wait_modal.rect.centerx - board_cx) <= 4
    assert abs(frontend.server_modal.rect.centerx - board_cx) <= 4


def test_mode_change_relays_modal_rects_via_draw_frame(frontend):
    from backend.match import SINGLE_SCREEN
    frontend.mode = "menu"
    frontend._compute_layout()
    win_w, _ = frontend.window.get_size()
    assert abs(frontend.wait_modal.rect.centerx - win_w / 2) <= 1
    frontend.mode = SINGLE_SCREEN
    frontend.draw_frame()
    board_cx = _board_centerx(frontend.board)
    assert abs(frontend.wait_modal.rect.centerx - board_cx) <= 4
