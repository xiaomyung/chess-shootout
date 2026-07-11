"""Auto-end countdown badges and heartbeat fold in the player strip.

Drives Frontend._strip_state / _compute_auto_end / _update_heartbeat directly:
no server fixture, no real WebSocket. All three auto-end windows
(abort/abandon/reconnect) are 60 s; the 10 % gate hides the badge for the first
6 s; the heartbeat red threshold is 10 s remaining.
"""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.domain.match import BOT, ONLINE, SINGLE_SCREEN
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import Square
from chessshootout.frontend.frontend import Frontend
from chessshootout.online.client import RECONNECT_TOTAL_SECONDS
from chessshootout.server.protocol import FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS


_pygame_init = pygame_display(1000, 800)


def _online_app():
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.coordinator.client = MagicMock()
    app.coordinator.client.room_id = "room-1"
    app.coordinator.client.state = "connected"
    app.coordinator.client.opp_state = "connected"
    app.coordinator.client.get_ping_ms.return_value = None
    app.switch_to("game", mode=ONLINE)
    app.coordinator.subscribe(app.game)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game._chosen_side = "white"
    app.match.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    app.game._first_move_deadline_ms = None
    app.game._opp_disconnected_at_ms = None
    app.game._local_disconnected_at_ms = None
    return app


def _strip(app, color):
    over = app.current_result() is not None
    return app._strip_state(color, app.match.current_turn(), over)


ABORT_WINDOW_MS = FIRST_MOVE_ABORT_SECONDS * 1000


@pytest.mark.parametrize(
    "local_color, first_move_deadline_ms, opp_disconnected_at_ms, "
    "local_disconnected_at_ms, ticks, query_color, expected_label, expected_seconds",
    [
        pytest.param(
            PieceColor.WHITE, ABORT_WINDOW_MS, None, None, 5_000,
            PieceColor.WHITE, None, None, id="abort_under_10pct_hidden",
        ),
        pytest.param(
            PieceColor.WHITE, ABORT_WINDOW_MS, None, None, 7_000,
            PieceColor.WHITE, "Abort in", 53.0, id="abort_at_10pct_shows",
        ),
        pytest.param(
            PieceColor.WHITE, None, 0, None, 5_000,
            PieceColor.BLACK, None, None, id="abandon_below_gate_hidden",
        ),
        pytest.param(
            PieceColor.WHITE, None, 0, None, 12_000,
            PieceColor.BLACK, "Abandon in", GRACE_SECONDS - 12,
            id="abandon_above_gate_shows",
        ),
        pytest.param(
            PieceColor.WHITE, None, None, 0, 12_000,
            PieceColor.WHITE, "Aborting in", RECONNECT_TOTAL_SECONDS - 12,
            id="reconnect_local_strip_shows",
        ),
        pytest.param(
            PieceColor.WHITE, ABORT_WINDOW_MS, None, 0, 12_000,
            PieceColor.WHITE, "Aborting in", None,
            id="reconnect_beats_abort_local_strip",
        ),
        pytest.param(
            PieceColor.BLACK, ABORT_WINDOW_MS, 0, None, 12_000,
            PieceColor.WHITE, "Abandon in", None,
            id="abandon_beats_abort_opp_to_move",
        ),
    ],
)
def test_compute_auto_end_label_and_remaining(
    monkeypatch, local_color, first_move_deadline_ms, opp_disconnected_at_ms,
    local_disconnected_at_ms, ticks, query_color, expected_label, expected_seconds,
):
    """Reconnect > abandon > abort cascade plus the 10 % visibility gate."""
    app = _online_app()
    app.match.local_color = local_color
    app.game._first_move_deadline_ms = first_move_deadline_ms
    app.game._opp_disconnected_at_ms = opp_disconnected_at_ms
    app.game._local_disconnected_at_ms = local_disconnected_at_ms
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
    state = _strip(app, query_color)
    assert state["auto_end_label"] == expected_label
    if expected_seconds is None:
        if expected_label is None:
            assert state["auto_end_seconds"] is None
    else:
        assert state["auto_end_seconds"] == pytest.approx(expected_seconds, abs=0.1)


def test_abort_clears_on_first_move(monkeypatch):
    """Landing the first ply nulls the abort deadline (Frontend._on_move_landed),
    not a side effect of querying the strip/auto-end state."""
    app = _online_app()
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.match.try_move(Square(6, 4), Square(4, 4))
    app._on_move_landed(app.match.move_history[-1])
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None
    assert app.game._first_move_deadline_ms is None


def test_compute_auto_end_alone_does_not_clear_the_deadline(monkeypatch):
    """Querying auto-end state (_strip_state/_compute_auto_end) is read-only now;
    only the real move-landed transition clears _first_move_deadline_ms."""
    app = _online_app()
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.match.try_move(Square(6, 4), Square(4, 4))
    _strip(app, PieceColor.WHITE)
    assert app.game._first_move_deadline_ms == ABORT_WINDOW_MS


def test_remote_move_applied_clears_first_move_deadline(monkeypatch):
    """The remote move-applied path (coordinator) also clears the deadline, so an
    opponent's first move lands the same reset as a local first move."""
    app = _online_app()
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    payload = {"from": "e2", "to": "e4", "san": "e4", "ply": 1, "clock": {}}
    app.coordinator._handle_remote_move_applied(payload)
    assert app.coordinator._resyncing is False
    assert app.game._first_move_deadline_ms is None


@pytest.mark.parametrize("show_mode", ["nothing", "line", "strips"])
def test_first_move_deadline_clears_via_move_landed_in_every_focus_show_mode(
    monkeypatch, show_mode,
):
    """Regression for the focus-mode gap: _update_player_strips (and the old
    _compute_auto_end reset it used to carry) never runs in focus 'nothing'/'line'
    show modes, so the deadline must clear at the real move-landed transition
    regardless of whether strips are drawn, and the heartbeat fraction must stop
    folding in the abort window once it does."""
    app = _online_app()
    app.game._time_control = (300, 0)
    app.match.setup_clock(300, 0)
    app.coordinator.client.drain_inbound.return_value = []
    app.focus_mode = True
    monkeypatch.setattr(app, "_focus_show", lambda: show_mode)
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS

    strips_calls = []
    real_update = app._update_player_strips

    def spy():
        strips_calls.append(True)
        real_update()

    monkeypatch.setattr(app, "_update_player_strips", spy)
    app.draw_frame()
    if show_mode == "strips":
        assert strips_calls
    else:
        assert not strips_calls
    assert app.game._first_move_deadline_ms == ABORT_WINDOW_MS

    app.match.try_move(Square(6, 4), Square(4, 4))
    app._on_move_landed(app.match.move_history[-1])
    assert app.game._first_move_deadline_ms is None
    assert app.coordinator._auto_end_heartbeat_fraction() is None

    app.draw_frame()
    assert app.game._first_move_deadline_ms is None


@pytest.mark.parametrize("mode", [
    pytest.param(SINGLE_SCREEN, id="single_screen"),
    pytest.param(BOT, id="bot"),
])
def test_offline_mode_never_emits_badge(monkeypatch, mode):
    app = _online_app()
    app.mode = mode
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS
    app.game._opp_disconnected_at_ms = 0
    app.game._local_disconnected_at_ms = 0
    app.coordinator.client.opp_state = "reconnecting"
    app.coordinator.client.state = "reconnecting"
    for color in (PieceColor.WHITE, PieceColor.BLACK):
        assert _strip(app, color)["auto_end_label"] is None


def test_result_clears_timestamps():
    app = _online_app()
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS
    app.game._opp_disconnected_at_ms = 0
    app.game._local_disconnected_at_ms = 0
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.game._first_move_deadline_ms is None
    assert app.game._opp_disconnected_at_ms is None
    assert app.game._local_disconnected_at_ms is None


def test_start_online_game_clears_disconnect_timestamps():
    app = _online_app()
    app.game._opp_disconnected_at_ms = 12345
    app.game._local_disconnected_at_ms = 67890
    app.coordinator._start_online_game({
        "your_color": "white", "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 3, "increment_seconds": 0,
        "started_seconds_ago": 0.0,
    })
    assert app.game._opp_disconnected_at_ms is None
    assert app.game._local_disconnected_at_ms is None


def test_begin_match_found_uses_started_seconds_ago(monkeypatch):
    """Deadline is server-stamped: now + (60 - started_seconds_ago) * 1000."""
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1_000)
    app.coordinator._begin_match_found_transition({
        "your_color": "white", "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 3, "increment_seconds": 0,
        "started_seconds_ago": 4.0,
    })
    assert app.game._first_move_deadline_ms == 57_000


@pytest.mark.parametrize("ticks, expected_fraction", [
    pytest.param(55_000, 0.0, id="below_red_threshold_floors_to_zero"),
    pytest.param(30_000, 0.5, id="above_red_threshold_uses_remaining_ratio"),
])
def test_heartbeat_folds_auto_end_fraction(monkeypatch, ticks, expected_fraction):
    """No chess clock active, so the heartbeat takes the abort fraction directly."""
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
    app.game._first_move_deadline_ms = ABORT_WINDOW_MS
    app.coordinator._update_heartbeat()
    args, _ = app.sound_manager.update_heartbeat.call_args
    fraction, _paused = args
    assert fraction == pytest.approx(expected_fraction, abs=0.01)
