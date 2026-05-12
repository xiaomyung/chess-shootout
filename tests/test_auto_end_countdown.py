"""Auto-end countdown badges in the player strip."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.match import BOT, ONLINE, SINGLE_SCREEN
from backend.pieces import PieceColor
from frontend.frontend import FIRST_MOVE_ABORT_SECONDS, Frontend
from frontend.online.client import RECONNECT_TOTAL_SECONDS
from server.protocol import GRACE_SECONDS


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _online_app():
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.online_client = MagicMock()
    app.online_client.state = "connected"
    app.online_client.opp_state = "connected"
    app.online_client.get_ping_ms.return_value = None
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._chosen_side = "white"
    app.match.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    app._first_move_deadline_ms = None
    app._opp_disconnected_at_ms = None
    app._local_disconnected_at_ms = None
    return app


def _strip(app, color):
    over = app.current_result() is not None
    return app._strip_state(color, app.match.current_turn(), over)


# ---------- 10% gate ----------

def test_abort_under_10_percent_elapsed_is_hidden(monkeypatch):
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 0)
    app._first_move_deadline_ms = 60_000  # 60 s window starting now.
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 5_000)
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None


def test_abort_at_10_percent_elapsed_shows(monkeypatch):
    app = _online_app()
    app._first_move_deadline_ms = 60_000
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 7_000)
    state = _strip(app, PieceColor.WHITE)
    assert state["auto_end_label"] == "abort"
    assert state["auto_end_seconds"] == pytest.approx(53.0, abs=0.1)


def test_abort_clears_on_first_move(monkeypatch):
    from backend.utils import Square
    app = _online_app()
    app._first_move_deadline_ms = 60_000
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.match.try_move(Square(6, 4), Square(4, 4))
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None
    assert app._first_move_deadline_ms is None


def test_abandon_below_gate_hidden(monkeypatch):
    app = _online_app()
    app.online_client.opp_state = "reconnecting"
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 5_000)
    app._opp_disconnected_at_ms = 0
    state = _strip(app, PieceColor.BLACK)
    assert state["auto_end_label"] is None


def test_abandon_above_gate_shows(monkeypatch):
    app = _online_app()
    app.online_client.opp_state = "reconnecting"
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 12_000)
    app._opp_disconnected_at_ms = 0
    state = _strip(app, PieceColor.BLACK)
    assert state["auto_end_label"] == "abandon"
    assert state["auto_end_seconds"] == pytest.approx(GRACE_SECONDS - 12, abs=0.1)


def test_reconnect_local_strip_shows(monkeypatch):
    app = _online_app()
    app.online_client.state = "reconnecting"
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 12_000)
    app._local_disconnected_at_ms = 0
    state = _strip(app, PieceColor.WHITE)
    assert state["auto_end_label"] == "reconnect"
    assert state["auto_end_seconds"] == pytest.approx(RECONNECT_TOTAL_SECONDS - 12, abs=0.1)


# ---------- Priority cascade ----------

def test_priority_reconnect_beats_abort_on_local_strip(monkeypatch):
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 12_000)
    app._first_move_deadline_ms = 60_000
    app._local_disconnected_at_ms = 0
    state = _strip(app, PieceColor.WHITE)
    assert state["auto_end_label"] == "reconnect"


def test_priority_abandon_beats_abort_when_opp_is_side_to_move(monkeypatch):
    app = _online_app()
    # Put local on black so white (side-to-move at start) is the opp.
    app.match.local_color = PieceColor.BLACK
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 12_000)
    app._first_move_deadline_ms = 60_000
    app._opp_disconnected_at_ms = 0
    state = _strip(app, PieceColor.WHITE)
    assert state["auto_end_label"] == "abandon"


# ---------- Mode immunity ----------

def test_local_mode_never_emits_badge(monkeypatch):
    app = _online_app()
    app.mode = SINGLE_SCREEN
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app._first_move_deadline_ms = 60_000
    app._opp_disconnected_at_ms = 0
    app._local_disconnected_at_ms = 0
    app.online_client.opp_state = "reconnecting"
    app.online_client.state = "reconnecting"
    for color in (PieceColor.WHITE, PieceColor.BLACK):
        assert _strip(app, color)["auto_end_label"] is None


def test_bot_mode_never_emits_badge(monkeypatch):
    app = _online_app()
    app.mode = BOT
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app._first_move_deadline_ms = 60_000
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None


# ---------- Game-end / rematch cleanup ----------

def test_result_clears_timestamps(monkeypatch):
    app = _online_app()
    app._first_move_deadline_ms = 60_000
    app._opp_disconnected_at_ms = 0
    app._local_disconnected_at_ms = 0
    app._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app._first_move_deadline_ms is None
    assert app._opp_disconnected_at_ms is None
    assert app._local_disconnected_at_ms is None


def test_start_online_game_clears_disconnect_timestamps():
    app = _online_app()
    app._opp_disconnected_at_ms = 12345
    app._local_disconnected_at_ms = 67890
    app._start_online_game({
        "your_color": "white", "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 3, "increment_seconds": 0,
        "started_seconds_ago": 0.0,
    })
    assert app._opp_disconnected_at_ms is None
    assert app._local_disconnected_at_ms is None


def test_begin_match_found_uses_started_seconds_ago(monkeypatch):
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1_000)
    app._begin_match_found_transition({
        "your_color": "white", "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 3, "increment_seconds": 0,
        "started_seconds_ago": 4.0,
    })
    # Deadline = now + (60 - 4) * 1000 = 1000 + 56000 = 57000.
    assert app._first_move_deadline_ms == 57_000


# ---------- Heartbeat fold ----------

def test_heartbeat_below_red_threshold_fires_zero_fraction(monkeypatch):
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 55_000)
    app._first_move_deadline_ms = 60_000  # remaining = 5 s, below 10 s
    # No chess clock setup → fraction starts as None.
    app._update_heartbeat()
    args, _ = app.sound_manager.update_heartbeat.call_args
    fraction, paused = args
    assert fraction == 0.0


def test_heartbeat_above_red_threshold_uses_min_fraction(monkeypatch):
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app._first_move_deadline_ms = 60_000  # remaining = 30 s → 30/60 = 0.5
    app._update_heartbeat()
    args, _ = app.sound_manager.update_heartbeat.call_args
    fraction, _ = args
    # No chess clock active → take auto-end fraction directly.
    assert fraction == pytest.approx(0.5, abs=0.01)
