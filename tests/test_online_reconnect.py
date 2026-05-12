"""Reconnect → server is the source of truth for the resumed game.

Two reconnect paths land here:

1. Mid-game ws-drop. The OnlineClient already holds a `_time_control` and
   the Frontend is in ONLINE mode, so `_handle_game_resumed` is enough on
   its own — replay SANs + apply the server's clock snapshot.
2. App-restart resume. The user clicks the start-menu Reconnect button on
   a fresh process. `_on_reconnect_active_game` now drives the full setup
   synchronously: `_start_online_game(resume)` followed by
   `_handle_game_resumed(resume)`. The async loop only opens the WS — it
   no longer queues a duplicate `game_start` / `game_resumed` pair, which
   used to race with the 500 ms match-found transition and reset the
   board + clock back to the starting position with full time.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from backend.match import ONLINE
from backend.pieces import PieceColor
from frontend.frontend import Frontend


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


@pytest.fixture
def app():
    fe = Frontend(1000, 800)
    fe.sound_manager = MagicMock()
    yield fe
    pg.display.set_mode((1000, 800))


def resume_payload(
    *,
    your_color="white",
    move_history=(),
    white_remaining=120.0,
    black_remaining=95.5,
    running_for="black",
    time_minutes=5,
    increment_seconds=2,
):
    return {
        "fen": "",
        "move_history": [{"san": san} for san in move_history],
        "clock": {
            "white_remaining": white_remaining,
            "black_remaining": black_remaining,
            "running_for": running_for,
        },
        "your_color": your_color,
        "white_name": "alice",
        "black_name": "bob",
        "time_minutes": time_minutes,
        "increment_seconds": increment_seconds,
    }


# ---- _handle_game_resumed: server is the source of truth ---------------------

def test_handle_game_resumed_applies_server_clock_snapshot(app):
    # Mid-game disconnect path: _time_control is already set from the original
    # _start_online_game; we should replay the moves and overwrite the local
    # clock with the server's authoritative remainders + side-to-move.
    app._time_control = (300, 2)
    app.match.local_color = PieceColor.WHITE
    payload = resume_payload(
        move_history=("e4", "e5"),
        white_remaining=240.0, black_remaining=180.0, running_for="white",
    )

    app._handle_game_resumed(payload)

    assert app.match.clock is not None
    assert app.match.clock.white_remaining == 240.0
    assert app.match.clock.black_remaining == 180.0
    assert app.match.clock.running_for == PieceColor.WHITE
    assert [e.san for e in app.match.move_history] == ["e4", "e5"]


def test_handle_game_resumed_does_not_reset_clock_to_initial(app):
    # The bug we're fixing: a fresh local clock starts at initial_seconds
    # (300 here). After applying the server snapshot we must end at the
    # server's value, never at the fresh-start value.
    app._time_control = (300, 0)
    app.match.local_color = PieceColor.WHITE
    payload = resume_payload(
        white_remaining=42.0, black_remaining=17.0, running_for="black",
    )

    app._handle_game_resumed(payload)

    assert app.match.clock.white_remaining == pytest.approx(42.0)
    assert app.match.clock.black_remaining == pytest.approx(17.0)
    # Specifically NOT the initial-seconds value.
    assert app.match.clock.white_remaining != 300.0


# ---- _on_reconnect_active_game: end-to-end app-restart resume ---------------

def test_on_reconnect_active_game_sets_up_online_state_and_clock(app, monkeypatch):
    # Stub the async client so we don't actually open a thread/WS during the
    # test. The bug repro is purely about main-thread state transitions.
    monkeypatch.setattr(
        "frontend.online.client.OnlineClient.reconnect_to_existing",
        lambda self, *a, **kw: None,
    )
    fresh = resume_payload(
        your_color="black",
        move_history=("d4", "d5", "c4"),
        white_remaining=200.0, black_remaining=210.0, running_for="black",
        time_minutes=5, increment_seconds=2,
    )
    monkeypatch.setattr("frontend.frontend.fetch_resume",
                        lambda *a, **kw: fresh)
    app._pending_reconnect = {
        "addr": "localhost:8000",
        "room_id": "room-x",
        "session_token": "tok",
        # Stale cached payload — exercises the fix that we DON'T trust this
        # snapshot and refetch instead.
        "resume": resume_payload(
            white_remaining=999.0, black_remaining=999.0, running_for="white",
        ),
    }

    app._on_reconnect_active_game()

    assert app.mode == ONLINE
    assert app._time_control == (300, 2)
    assert app.match.local_color == PieceColor.BLACK
    assert [e.san for e in app.match.move_history] == ["d4", "d5", "c4"]
    assert app.match.clock is not None
    # Fresh values, not the stale cached 999s.
    assert app.match.clock.white_remaining == pytest.approx(200.0)
    assert app.match.clock.black_remaining == pytest.approx(210.0)
    assert app.match.clock.running_for == PieceColor.BLACK


def test_on_reconnect_active_game_refetches_resume_to_avoid_drift(app, monkeypatch):
    # Concrete repro of the user-reported "drifts a couple seconds" bug:
    # the cached payload was taken at app launch but the click can land
    # arbitrarily later. We must hit /resume again right at click-time.
    monkeypatch.setattr(
        "frontend.online.client.OnlineClient.reconnect_to_existing",
        lambda self, *a, **kw: None,
    )
    calls = []

    def _fetch(addr, room_id, session_token):
        calls.append((addr, room_id, session_token))
        return resume_payload(
            white_remaining=42.0, black_remaining=42.0, running_for="white",
        )

    monkeypatch.setattr("frontend.frontend.fetch_resume", _fetch)
    app._pending_reconnect = {
        "addr": "localhost:8000",
        "room_id": "room-y",
        "session_token": "tok",
        "resume": resume_payload(),
    }
    app._on_reconnect_active_game()
    assert calls == [("localhost:8000", "room-y", "tok")]
    assert app.match.clock.white_remaining == pytest.approx(42.0)


def test_on_reconnect_active_game_failed_refetch_restores_pending(app, monkeypatch):
    # If the fresh /resume call fails, we must NOT silently fall back to
    # the stale cached snapshot — that's exactly the drift this fixes. The
    # pending entry is restored so the user can retry from the same modal.
    monkeypatch.setattr(
        "frontend.online.client.OnlineClient.reconnect_to_existing",
        lambda self, *a, **kw: None,
    )
    monkeypatch.setattr("frontend.frontend.fetch_resume",
                        lambda *a, **kw: None)
    pending = {
        "addr": "localhost:8000",
        "room_id": "room-z",
        "session_token": "tok",
        "resume": resume_payload(),
    }
    app._pending_reconnect = dict(pending)
    app._on_reconnect_active_game()
    # We did NOT enter the game — mode stays at "menu" (or whatever it was).
    assert app.mode != ONLINE
    # And the entry is restored so the start-menu Reconnect button stays live.
    assert app._pending_reconnect == pending
    # User-visible: a confirm modal is up offering Retry / Cancel.
    assert app.confirm_modal.is_visible()


def test_on_reconnect_active_game_no_pending_is_noop(app, monkeypatch):
    # Defensive guard: clicking Reconnect after the pending entry was cleared
    # should not crash and should not flip mode.
    app._pending_reconnect = None
    prior_mode = app.mode
    app._on_reconnect_active_game()
    assert app.mode == prior_mode


# ---- _async_main_resume no longer queues game_start / game_resumed ----------

def test_async_main_resume_does_not_queue_legacy_events():
    # The synchronous path in _on_reconnect_active_game now owns full
    # state setup. The async loop's only job for the initial reconnect is
    # to open the WS — it must NOT queue duplicate game_start/game_resumed
    # events (those are what raced with the match-found transition and
    # caused the original reset-to-initial bug).
    import asyncio
    from frontend.online.client import OnlineClient

    client = OnlineClient()
    client._addr = "localhost:8000"
    client._room_id = "room-x"
    client._session_token = "tok"

    async def fake_session():
        return None

    client._run_session_with_reconnects = fake_session

    asyncio.run(client._async_main_resume(resume_payload()))

    queued_types = []
    while not client._inbound.empty():
        queued_types.append(client._inbound.get_nowait().type)

    assert "game_start" not in queued_types
    assert "game_resumed" not in queued_types
