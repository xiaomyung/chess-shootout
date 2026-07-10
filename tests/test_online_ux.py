"""M16: Online UX layer.

Animation duration scales with the time control, the wait modal shows
elapsed time during search, a themed match-found VS reveal holds for a few
seconds before the game starts, the reconnecting on-board overlay surfaces
only while the client is reconnecting mid-game, and transient errors show a
toast (not a modal).
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.domain.match import ONLINE
from chessshootout.frontend.frontend import (
    ANIM_MS_DEFAULT, ANIM_MS_MIN, ANIM_MS_MAX,
    Frontend, compute_animation_ms, RECONNECT_MODAL_DEBOUNCE_MS,
)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.modals.reconnecting import ReconnectingModal
from chessshootout.frontend.online.events import (
    MATCH_FOUND_SECONDS, NOT_YOUR_TURN_TOASTS, ONLINE_HARD_FAILURE_LABELS,
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
    m.set_rect(pg.Rect(0, 0, 400, 400))
    cancelled = []
    m.show(pg.time.get_ticks(), on_cancel=lambda: cancelled.append(True))
    assert m.is_visible()
    m.draw()
    m.handle_click(m.button_rects["abandon"].center)
    assert cancelled == [True]


def test_reconnecting_overlay_fills_board_rect_with_scrim():
    """The overlay darkens the whole board rect (scrim) and paints an amber
    spinner ring — both absent before show()."""
    win = pg.display.get_surface()
    m = ReconnectingModal(win)
    rect = pg.Rect(0, 0, 420, 360)
    m.set_rect(rect)
    m.show(pg.time.get_ticks(), on_cancel=lambda: None)

    win.fill((0, 0, 0))
    m.draw()
    scrim_corner = win.get_at((4, 4))[:3]
    assert scrim_corner != (0, 0, 0)

    amber = pg.Color(Colors.amber)[:3]

    def amber_pixels():
        return sum(
            1
            for x in range(0, rect.width, 2)
            for y in range(0, rect.height, 2)
            if max(abs(win.get_at((x, y))[i] - amber[i]) for i in range(3)) < 24
        )

    assert amber_pixels() > 0


def _reconnecting_client():
    ns = SimpleNamespace(
        state="reconnecting",
        is_server_silent=lambda: False,
        heartbeat_interval=lambda: 2.0,
        send_ping=lambda ply: None,
    )
    ns.is_connected = lambda: ns.state == "connected"
    return ns


def test_reconnecting_overlay_appears_after_debounce(frontend, monkeypatch):
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    frontend.mode = ONLINE
    frontend.online_client = _reconnecting_client()
    frontend._update_online_phase()                       # arms the debounce clock
    assert not frontend.reconnecting_modal.is_visible(), "debounced, not shown instantly"
    fake_now[0] += RECONNECT_MODAL_DEBOUNCE_MS + 50
    frontend._update_online_phase()
    assert frontend.reconnecting_modal.is_visible()


def test_brief_blip_never_flashes_the_modal(frontend, monkeypatch):
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    frontend.mode = ONLINE
    client = _reconnecting_client()
    frontend.online_client = client
    frontend._update_online_phase()
    fake_now[0] += RECONNECT_MODAL_DEBOUNCE_MS - 100       # recover before the threshold
    client.state = "connected"
    frontend._update_online_phase()
    assert not frontend.reconnecting_modal.is_visible()


def test_reconnecting_overlay_hides_immediately_on_recovery(frontend, monkeypatch):
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    frontend.mode = ONLINE
    client = _reconnecting_client()
    frontend.online_client = client
    frontend._update_online_phase()
    fake_now[0] += RECONNECT_MODAL_DEBOUNCE_MS + 50
    frontend._update_online_phase()
    assert frontend.reconnecting_modal.is_visible()
    client.state = "connected"
    frontend._update_online_phase()
    assert not frontend.reconnecting_modal.is_visible(), \
        "hidden the moment the socket is back — no input-blocking linger"


def test_reconnecting_overlay_cancel_calls_abandon(frontend, monkeypatch):
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    abandoned = []
    monkeypatch.setattr(frontend, "_abandon_online_game",
                        lambda: abandoned.append(True))
    frontend.mode = ONLINE
    frontend.online_client = _reconnecting_client()
    frontend._update_online_phase()
    fake_now[0] += RECONNECT_MODAL_DEBOUNCE_MS + 50
    frontend._update_online_phase()
    frontend.reconnecting_modal.draw()
    frontend.reconnecting_modal.handle_click(
        frontend.reconnecting_modal.button_rects["abandon"].center,
    )
    assert abandoned == [True]


def test_wait_modal_elapsed_tracks_search_time(frontend, monkeypatch):
    fake_now = [10000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    frontend.wait_modal.show("Rapid", "10 + 5", on_cancel=lambda: None)
    frontend._wait_started_at_ms = fake_now[0]
    fake_now[0] += 7 * 1000
    frontend._update_online_phase()
    assert frontend.wait_modal.elapsed == 7
    fake_now[0] += 60 * 1000
    frontend._update_online_phase()
    assert frontend.wait_modal.elapsed == 67


def test_match_found_reveal_holds_then_starts_game(frontend, monkeypatch):
    fake_now = [50000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    started = []
    monkeypatch.setattr(frontend, "_start_online_game",
                        lambda payload: started.append(payload))
    frontend.wait_modal.show("Rapid", "10 + 5", on_cancel=lambda: None)
    frontend._wait_started_at_ms = fake_now[0]

    payload = {"your_color": "white", "white_name": "A", "black_name": "B",
               "time_minutes": 5, "increment_seconds": 0}
    frontend._begin_match_found_transition(payload)

    assert frontend.match_found_modal.is_visible()
    assert not frontend.wait_modal.is_visible()
    fake_now[0] += MATCH_FOUND_SECONDS * 1000 - 50
    frontend._update_online_phase()
    assert started == []
    assert frontend.match_found_modal.is_visible()

    fake_now[0] += 100
    frontend._update_online_phase()
    assert started == [payload]
    assert not frontend.match_found_modal.is_visible()
    fake_now[0] += 1000
    frontend._update_online_phase()
    assert started == [payload]


def test_match_found_transition_plays_online_game_start_sound(frontend):
    plays = []
    frontend.sound_manager.play_online_game_start = lambda: plays.append(True)
    frontend.wait_modal.show("Rapid", "10 + 5", on_cancel=lambda: None)
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
        pytest.param("already_in_game",
                     ONLINE_TRANSIENT_REASON_LABELS["already_in_game"],
                     id="already_in_game_maps_to_friendly_label"),
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
    content_center_y = top + (win_h - top - 22) / 2
    assert abs(rect.centerx - win_w / 2) <= 1
    assert abs(rect.centery - content_center_y) <= 1
    assert rect.bottom < frontend.start_menu._footer_link_rect.top


def test_menu_mode_centers_flex_modals_on_window(frontend):
    frontend.mode = "menu"
    frontend._compute_layout()
    win_w, _ = frontend.window.get_size()
    assert abs(frontend.fen_input_modal.rect.centerx - win_w / 2) <= 1
    assert abs(frontend.wait_modal.rect.centerx - win_w / 2) <= 1
    assert abs(frontend.match_found_modal.rect.centerx - win_w / 2) <= 1


def _board_centerx(board):
    return board.board_offset_x + board.cell_size * board.SIZE / 2


def test_game_mode_centers_flex_modals_on_board(frontend):
    from chessshootout.domain.match import SINGLE_SCREEN
    frontend.mode = SINGLE_SCREEN
    frontend._compute_layout()
    board_cx = _board_centerx(frontend.board)
    assert abs(frontend.fen_input_modal.rect.centerx - board_cx) <= 4
    assert abs(frontend.wait_modal.rect.centerx - board_cx) <= 4
    assert abs(frontend.match_found_modal.rect.centerx - board_cx) <= 4


def test_mode_change_relays_modal_rects_via_draw_frame(frontend):
    from chessshootout.domain.match import SINGLE_SCREEN
    frontend.mode = "menu"
    frontend._compute_layout()
    win_w, _ = frontend.window.get_size()
    assert abs(frontend.wait_modal.rect.centerx - win_w / 2) <= 1
    frontend.mode = SINGLE_SCREEN
    frontend.draw_frame()
    board_cx = _board_centerx(frontend.board)
    assert abs(frontend.wait_modal.rect.centerx - board_cx) <= 4


def test_rematch_request_shows_banner_and_hides_initiate_button(frontend):
    """An incoming rematch request pushes a persistent Accept/Deny banner and
    flags the result modal to drop its initiate button (the banner is the affordance)."""
    sent = []
    frontend.online_client = SimpleNamespace(
        send_rematch_response=lambda accept: sent.append(accept),
        send_rematch_request=lambda: sent.append("req"),
    )
    frontend._chosen_side = "white"
    frontend.white_name, frontend.black_name = "Me", "Them"
    frontend._handle_rematch_request()
    assert frontend._rematch_offered is True
    assert frontend.result_menu.rematch_offered is True
    assert not frontend.offer_banners.is_empty()


def test_draw_offer_banner_pops(frontend):
    frontend.sound_manager = MagicMock()
    frontend.online_client = SimpleNamespace(send_draw_response=lambda v: None)
    frontend._push_offer_banner("draw_offered")
    frontend.sound_manager.play_toast.assert_called_once()


def test_takeback_offer_banner_pops(frontend):
    frontend.sound_manager = MagicMock()
    frontend.online_client = SimpleNamespace(send_takeback_response=lambda v: None)
    frontend._push_offer_banner("takeback_offered")
    frontend.sound_manager.play_toast.assert_called_once()


def test_offer_accept_and_decline_pop_and_send(frontend):
    frontend.sound_manager = MagicMock()
    sent = []
    frontend.online_client = SimpleNamespace(send_draw_response=sent.append)
    captured = {}
    frontend.offer_banners = MagicMock()
    frontend.offer_banners.push = lambda *a, on_ok, on_no, **k: captured.update(ok=on_ok, no=on_no)
    frontend._push_offer_banner("draw_offered")
    frontend.sound_manager.reset_mock()
    captured["ok"]()
    frontend.sound_manager.play_toast.assert_called_once()
    assert sent == [True]
    frontend.sound_manager.reset_mock()
    captured["no"]()
    frontend.sound_manager.play_toast.assert_called_once()
    assert sent == [True, False]


def test_on_rematch_accepts_when_offered(frontend):
    sent = []
    frontend.online_client = SimpleNamespace(
        send_rematch_response=lambda accept: sent.append(("resp", accept)),
        send_rematch_request=lambda: sent.append(("req",)))
    frontend._rematch_offered = True
    frontend.result_menu.set_rematch_offered(True)
    frontend._on_rematch()
    assert sent == [("resp", True)]
    assert frontend._rematch_offered is False
    assert frontend.result_menu.rematch_offered is False


def test_on_rematch_requests_when_not_offered(frontend):
    sent = []
    frontend.online_client = SimpleNamespace(
        send_rematch_response=lambda accept: sent.append(("resp", accept)),
        send_rematch_request=lambda: sent.append(("req",)))
    frontend._rematch_offered = False
    frontend._on_rematch()
    assert sent == [("req",)]


def _arm_post_game(frontend, **client):
    frontend.online_client = SimpleNamespace(**client)
    frontend.mode = ONLINE
    frontend.manual_result = "draw_agreement"
    frontend._chosen_side = "white"
    frontend.white_name, frontend.black_name = "Me", "Them"
    frontend.start_menu.hide()


def test_decline_rematch_sends_false_and_clears(frontend):
    sent = []
    frontend.online_client = SimpleNamespace(
        send_rematch_response=lambda accept: sent.append(accept))
    frontend._rematch_offered = True
    frontend.result_menu.set_rematch_offered(True)
    frontend._decline_rematch()
    assert sent == [False]
    assert frontend._rematch_offered is False
    assert frontend.result_menu.rematch_offered is False


def test_rematch_update_reconnecting_keeps_client(frontend):
    _arm_post_game(frontend, disconnect=lambda: None)
    frontend._handle_rematch_update({"event": "opponent_reconnecting"})
    assert frontend.toast.is_visible()
    assert frontend.online_client is not None
    assert frontend.mode == ONLINE


def test_rematch_update_declined_bubbles_and_returns_to_menu(frontend):
    """The declined/opponent-left/window-expired paths must re-show the start-menu
    card; the old guard left the player on a blank, unresponsive backdrop."""
    _arm_post_game(frontend, disconnect=lambda: None)
    frontend._rematch_offered = True
    frontend._handle_rematch_update({"event": "declined"})
    assert frontend.toast.is_visible()
    assert frontend.online_client is None
    assert frontend.mode == "menu"
    assert frontend._rematch_offered is False
    assert frontend.start_menu.is_visible()


def test_rematch_update_window_expired_returns_to_menu(frontend):
    _arm_post_game(frontend, disconnect=lambda: None)
    frontend._handle_rematch_update({"event": "window_expired"})
    assert frontend.online_client is None
    assert frontend.mode == "menu"
    assert frontend.start_menu.is_visible()


def test_online_result_redelivery_does_not_double_count(frontend, monkeypatch):
    """A reconnect re-delivers the result; the handler must be idempotent so the
    series score (and PGN auto-save) only fire once per game."""
    monkeypatch.setattr(frontend, "_auto_save_pgn", lambda: None)
    frontend.mode = ONLINE
    frontend._chosen_side = "white"
    frontend.white_name, frontend.black_name = "Me", "Them"
    frontend._series_scores = {}
    frontend.manual_result = None
    payload = {"reason": "resignation", "winner_color": "white"}
    frontend._handle_online_result(payload)
    frontend._handle_online_result(payload)
    assert frontend._series_scores["Me"] == 1.0
    assert frontend.manual_result == "white_wins_by_resignation"


def test_starting_fen_game_drops_lingering_online_client(frontend):
    """A kept-alive post-game online socket must be torn down when a local game
    starts, or its rematch banner / result leaks over the local game."""
    disc = []
    frontend.online_client = SimpleNamespace(disconnect=lambda: disc.append(True))
    frontend.mode = "menu"
    ok = frontend._start_game_from_fen(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert ok is True
    assert disc == [True]
    assert frontend.online_client is None


def test_rematch_update_cancelled_clears_banner_and_keeps_client(frontend):
    _arm_post_game(frontend, disconnect=lambda: None)
    frontend._push_rematch_banner()
    frontend.result_menu.set_rematch_offered(True)
    assert not frontend.offer_banners.is_empty()
    frontend._handle_rematch_update({"event": "cancelled"})
    assert frontend.offer_banners.is_empty()
    assert frontend._rematch_offered is False
    assert frontend.result_menu.rematch_offered is False
    assert frontend.toast.is_visible()
    assert frontend.online_client is not None
    assert frontend.mode == ONLINE


def test_back_to_menu_keeps_client_and_reshows_banner_post_game(frontend):
    sent = []
    _arm_post_game(
        frontend,
        send_left_result=lambda: sent.append("left"),
        disconnect=lambda: sent.append("disc"),
    )
    frontend._rematch_offered = True
    frontend._on_back_to_menu()
    assert sent == ["left"]
    assert frontend.online_client is not None
    assert frontend.mode == "menu"
    assert not frontend.offer_banners.is_empty()


def test_match_found_rematch_uses_rematch_eyebrow(frontend):
    frontend.match_found_modal.show("A", "B", "white", lambda: None,
                                    seconds=3, rematch=True)
    frontend.match_found_modal.window.fill((0, 0, 0))
    frontend.match_found_modal.draw()
    assert frontend.match_found_modal.rematch is True
