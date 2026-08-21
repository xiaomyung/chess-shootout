"""Reconnect → server is the source of truth for the resumed game.

Two reconnect paths land here:

1. Mid-game ws-drop. The OnlineClient already holds a `_time_control` and
   the GameScreen's variant is already "online", so `_handle_game_resumed`
   is enough on its own — replay SANs + apply the server's clock snapshot.
2. App-restart resume. The user clicks the start-menu Reconnect button on
   a fresh process. `_on_reconnect_active_game` now drives the full setup
   synchronously: `_start_online_game(resume)` followed by
   `_handle_game_resumed(resume)`. The async loop only opens the WS — it
   no longer queues a duplicate `game_start` / `game_resumed` pair, which
   used to race with the 500 ms match-found transition and reset the
   board + clock back to the starting position with full time.
"""

import logging
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import Square
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.online_coordinator import RECONNECT_PROBE_MAX_ATTEMPTS
from chessshootout.frontend.screens.game import RESUME_FEN_FAILED_LABEL
from chessshootout.server.protocol import Reason


_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def app():
    fe = Frontend(1000, 800)
    fe.sound_manager = MagicMock()
    yield fe
    pg.display.set_mode((1000, 800))


def _resume_payload(
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


def test_handle_game_resumed_applies_server_clock_snapshot(app):
    """Mid-game drop: replay SANs, build the clock from the existing
    _time_control, then overwrite remainders + side-to-move from the snapshot."""
    app.game.variant = "online"
    app.game._time_control = (300, 2)
    app.game.match.local_color = PieceColor.WHITE
    payload = _resume_payload(
        move_history=("e4", "e5"),
        white_remaining=240.0, black_remaining=180.0, running_for="white",
    )

    app.coordinator._handle_game_resumed(payload)

    assert app.game.match.clock is not None
    assert app.game.match.clock.increment_seconds == 2.0
    assert app.game.match.clock.white_remaining == 240.0
    assert app.game.match.clock.black_remaining == 180.0
    assert app.game.match.clock.running_for == PieceColor.WHITE
    assert [e.san for e in app.game.match.move_history] == ["e4", "e5"]
    assert app.game.match.current_turn() == PieceColor.WHITE


def test_handle_game_resumed_does_not_reset_clock_to_initial(app):
    """A fresh clock starts at initial_seconds (300); applying the snapshot must
    land on the server value, never the fresh-start value."""
    app.game.variant = "online"
    app.game._time_control = (300, 0)
    app.game.match.local_color = PieceColor.WHITE
    payload = _resume_payload(
        white_remaining=42.0, black_remaining=17.0, running_for="black",
    )

    app.coordinator._handle_game_resumed(payload)

    assert app.game.match.clock.white_remaining == pytest.approx(42.0)
    assert app.game.match.clock.black_remaining == pytest.approx(17.0)
    assert app.game.match.clock.running_for == PieceColor.BLACK
    assert app.game.match.clock.white_remaining != 300.0
    assert app.game.match.move_history == []


def test_on_reconnect_active_game_sets_up_online_state_and_clock(app, monkeypatch):
    """App-restart Reconnect drives the full main-thread setup synchronously;
    reconnect_to_existing is stubbed so no thread/WS opens."""
    monkeypatch.setattr(
        "chessshootout.online.client.OnlineClient.reconnect_to_existing",
        lambda self, *a, **kw: None,
    )
    fresh = _resume_payload(
        your_color="black",
        move_history=("d4", "d5", "c4"),
        white_remaining=200.0, black_remaining=210.0, running_for="black",
        time_minutes=5, increment_seconds=2,
    )
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda *a, **kw: fresh)
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000",
        "room_id": "room-x",
        "session_token": "tok",
        "resume": _resume_payload(
            white_remaining=999.0, black_remaining=999.0, running_for="white",
        ),
    }

    app.coordinator._on_reconnect_active_game()

    assert app.screen is app.game
    assert app.game.variant == "online"
    assert app.game._time_control == (300, 2)
    assert app.game.match.local_color == PieceColor.BLACK
    assert [e.san for e in app.game.match.move_history] == ["d4", "d5", "c4"]
    assert app.game.match.clock is not None
    assert app.game.match.clock.white_remaining == pytest.approx(200.0)
    assert app.game.match.clock.black_remaining == pytest.approx(210.0)
    assert app.game.match.clock.running_for == PieceColor.BLACK
    assert app.coordinator._pending_reconnect is None


def test_on_reconnect_active_game_refetches_resume_to_avoid_drift(app, monkeypatch):
    """Drift repro: the cached payload was taken at launch but the click lands
    arbitrarily later, so /resume is re-fetched at click-time."""
    monkeypatch.setattr(
        "chessshootout.online.client.OnlineClient.reconnect_to_existing",
        lambda self, *a, **kw: None,
    )
    calls = []

    def _fetch(addr, room_id, session_token):
        calls.append((addr, room_id, session_token))
        return _resume_payload(
            white_remaining=42.0, black_remaining=42.0, running_for="white",
        )

    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume", _fetch)
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000",
        "room_id": "room-y",
        "session_token": "tok",
        "resume": _resume_payload(),
    }
    app.coordinator._on_reconnect_active_game()
    assert calls == [("localhost:8000", "room-y", "tok")]
    assert app.game.match.clock.white_remaining == pytest.approx(42.0)


def test_on_reconnect_active_game_failed_refetch_restores_pending(app, monkeypatch):
    """A failed /resume must not fall back to the stale snapshot: stay out of
    the game, restore the pending entry, and surface a Retry/Cancel modal."""
    monkeypatch.setattr(
        "chessshootout.online.client.OnlineClient.reconnect_to_existing",
        lambda self, *a, **kw: None,
    )
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda *a, **kw: None)
    pending = {
        "addr": "localhost:8000",
        "room_id": "room-z",
        "session_token": "tok",
        "resume": _resume_payload(),
    }
    app.coordinator._pending_reconnect = dict(pending)
    app.coordinator._on_reconnect_active_game()
    assert app.screen is app.menu
    assert app.coordinator._pending_reconnect == pending
    assert app.menu.play_view.reconnect_available
    assert app.confirm_modal.is_visible()


def test_on_reconnect_active_game_no_pending_is_noop(app):
    """Clicking Reconnect after the pending entry was cleared must not crash or
    flip screen."""
    app.coordinator._pending_reconnect = None
    prior_screen = app.screen
    app.coordinator._on_reconnect_active_game()
    assert app.screen is prior_screen
    assert app.coordinator._pending_reconnect is None


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda p: p.update({"move_history": [{"note": "no san here"}]}),
                 id="move_entry_without_a_san"),
    pytest.param(lambda p: p.update({"move_history": "e4e5"}),
                 id="move_history_is_not_a_list"),
    pytest.param(lambda p: p.update({"clock": "nope"}),
                 id="clock_is_not_a_mapping"),
])
def test_reconnect_adoption_survives_a_hostile_resume_payload(
        app, monkeypatch, tmp_path, caplog, mutate):
    """Every inbound ws event runs inside the drain's try/except, but Reconnect
    adopts a /resume payload straight from a modal callback — outside it. A
    payload the replay chokes on took the whole app down from a button click.
    Adoption now runs through the same guard: logged, toasted, and the session is
    dropped back to the menu. (A malformed FEN is no longer one of these cases —
    on_resume degrades instead of raising; see the FEN-fallback tests below.)"""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("chessshootout.online.client.OnlineClient.reconnect_to_existing",
                        lambda self, *a, **kw: None)
    hostile = _resume_payload()
    mutate(hostile)
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda *a, **kw: hostile)
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000", "room_id": "room-h", "session_token": "tok",
    }

    with caplog.at_level(logging.ERROR, logger="chess.frontend"):
        app.coordinator._on_reconnect_active_game()

    assert app.screen is app.menu
    assert app.coordinator.client is None
    assert app.toast.is_visible()
    assert any("reconnect adoption failed" in r.getMessage() for r in caplog.records)


def test_resume_keeps_adopting_when_the_fen_fallback_is_refused(app, caplog):
    """The FEN is a rescue path for a move list that would not replay, and it
    arrives from the server like everything else in the snapshot. A FEN the engine
    refuses must not throw the rest of the adoption away with it — the clock, the
    result and the idle window all land after it, and the replayed prefix stays on
    the board for the resync heartbeat to converge."""
    app.toast = MagicMock()
    app.game.variant = Variant.ONLINE
    app.game._time_control = (300, 2)
    app.game.match.local_color = PieceColor.WHITE
    app.game._chosen_side = "white"
    payload = _resume_payload(move_history=("e4", "zzz"),
                              white_remaining=61.0, black_remaining=42.0,
                              running_for="white")
    payload["fen"] = "not a fen"
    payload["idle_window"] = {"outcome": Reason.RESIGNATION, "color": "white",
                              "seconds_remaining": 20.0}

    with caplog.at_level(logging.WARNING, logger="chess.frontend"):
        app.game.on_resume(payload)

    assert [e.san for e in app.game.match.move_history] == ["e4"]
    assert app.game.match.clock.white_remaining == pytest.approx(61.0)
    assert app.game.match.clock.black_remaining == pytest.approx(42.0)
    assert app.game._idle_window is not None
    app.toast.show.assert_any_call(RESUME_FEN_FAILED_LABEL, key="resume_fen_failed")
    assert any("FEN fallback refused" in r.getMessage() for r in caplog.records)


def test_resume_fen_fallback_refreshes_the_check_highlight(app):
    """The board memoises which kings are in check against (ply count, last move).
    A resume that falls back to the FEN empties the move history, so a board that
    has already drawn its opening position matches its own stale (0, None) entry —
    and a resumed position with a king under fire drew no warning at all."""
    app.game.variant = Variant.ONLINE
    app.game._time_control = None
    app.game.match.local_color = PieceColor.WHITE
    assert app.game.board._in_check_king_squares() == []

    payload = _resume_payload(move_history=("zzz",))
    payload["fen"] = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    app.game.on_resume(payload)

    assert app.game.board._in_check_king_squares() == [Square(7, 4)]


def test_on_resume_never_replays_more_than_the_ply_cap(app, monkeypatch):
    """The replay loop is driven by a server-supplied list and only breaks on an
    illegal SAN. A hostile server that sends legal moves forever would spin
    apply_san until the app dies, so the replay is capped far above any real game
    (the longest legal game is a few hundred plies)."""
    from chessshootout.frontend.screens.game import RESUME_MAX_PLIES

    class _Applied:
        legal = True

    replayed = []
    monkeypatch.setattr(app.game.match, "apply_san",
                        lambda san: replayed.append(san) or _Applied())
    app.game.variant = "online"
    app.game._time_control = (300, 0)

    app.game.on_resume(_resume_payload(move_history=["e4"] * (RESUME_MAX_PLIES * 4)))

    assert len(replayed) == RESUME_MAX_PLIES


def test_reconnect_adoption_clips_an_oversize_opponent_name(app, monkeypatch):
    """Names are server-supplied and get font-rendered in full before the strip
    clips them, so a megabyte-long name is a multi-gigabyte surface."""
    from chessshootout.infra.env import _NICKNAME_MAX_LEN

    monkeypatch.setattr("chessshootout.online.client.OnlineClient.reconnect_to_existing",
                        lambda self, *a, **kw: None)
    payload = _resume_payload()
    payload["black_name"] = "b" * 500_000
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda *a, **kw: payload)
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000", "room_id": "room-n", "session_token": "tok",
    }

    app.coordinator._on_reconnect_active_game()

    assert app.game.black_name == "b" * _NICKNAME_MAX_LEN
    assert app.game.white_name == "alice"
    assert set(app.game.result_flow.series_scores) == {"alice", "b" * _NICKNAME_MAX_LEN}
    app.draw_frame()


def test_async_main_resume_does_not_queue_legacy_events():
    """The async loop only opens the WS on reconnect; it must not queue a
    duplicate game_start/game_resumed pair (the original reset-to-initial race)."""
    import asyncio
    from chessshootout.online.client import OnlineClient

    client = OnlineClient()
    client._addr = "localhost:8000"
    client._room_id = "room-x"
    client._session_token = "tok"

    async def fake_session():
        return None

    client._run_session_with_reconnects = fake_session

    asyncio.run(client._async_main_resume(_resume_payload()))

    queued_types = []
    while not client._inbound.empty():
        queued_types.append(client._inbound.get_nowait().type)

    assert "game_start" not in queued_types
    assert "game_resumed" not in queued_types


def test_probe_worker_increments_attempts_on_no_room(app, monkeypatch):
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.probe_active_game",
                        lambda addr, uuid: None)
    app.coordinator._reconnect_probe_attempts = 0
    gen = app.coordinator._reconnect_probe_gen
    app.coordinator._reconnect_probe_worker("addr", "uuid", gen)
    assert app.coordinator._reconnect_probe_attempts == 1
    assert app.coordinator._pending_reconnect is None


def test_probe_worker_sets_pending_and_keeps_attempts_on_room_found(app, monkeypatch):
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.probe_active_game",
                        lambda addr, uuid: {"room_id": "r", "session_token": "t"})
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda addr, room, token: {"fen": ""})
    app.coordinator._reconnect_probe_attempts = 0
    gen = app.coordinator._reconnect_probe_gen
    app.coordinator._reconnect_probe_worker("addr", "uuid", gen)
    assert app.coordinator._pending_reconnect is not None
    assert app.coordinator._reconnect_probe_attempts == 0


def test_spawn_stops_after_max_attempts(app, monkeypatch):
    started = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: started.append(1) or MagicMock())
    app.coordinator._reconnect_probe_gen += 1
    app.coordinator._reconnect_probe_inflight = False
    app.coordinator._pending_reconnect = None
    app.coordinator._reconnect_probe_attempts = RECONNECT_PROBE_MAX_ATTEMPTS
    app.coordinator._spawn_reconnect_probe()
    assert started == []


def test_spawn_stops_when_room_already_pending(app, monkeypatch):
    started = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: started.append(1) or MagicMock())
    app.coordinator._reconnect_probe_gen += 1
    app.coordinator._reconnect_probe_inflight = False
    app.coordinator._reconnect_probe_attempts = 0
    app.coordinator._pending_reconnect = {"room_id": "r"}
    app.coordinator._spawn_reconnect_probe()
    assert started == []


def test_back_to_menu_resets_probe_attempts(app):
    app.coordinator._reconnect_probe_gen += 1
    app.coordinator._reconnect_probe_attempts = RECONNECT_PROBE_MAX_ATTEMPTS
    app._on_back_to_menu()
    assert app.coordinator._reconnect_probe_attempts == 0


def test_spawn_reconnect_probe_logs_a_debug_attempt_not_an_info_line(app, monkeypatch, caplog):
    """The /reclaim probe fires every 5s while idle on the menu — it must stay
    at DEBUG, never INFO, or it becomes the same per-probe noise the httpx
    silencing is fixing on the transport side."""
    monkeypatch.setattr("threading.Thread", lambda *a, **k: MagicMock())
    app.coordinator._reconnect_probe_gen += 1
    app.coordinator._reconnect_probe_inflight = False
    app.coordinator._pending_reconnect = None
    app.coordinator._reconnect_probe_attempts = 0
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.coordinator._spawn_reconnect_probe()
    debug_lines = [r for r in caplog.records if "reclaim probe attempt" in r.getMessage()]
    assert len(debug_lines) == 1
    assert debug_lines[0].levelno == logging.DEBUG
    assert not any(r.levelno == logging.INFO and "reclaim probe" in r.getMessage()
                   for r in caplog.records)


def test_probe_worker_logs_nothing_on_a_routine_miss(app, monkeypatch, caplog):
    """No reclaimable game found (the common case, e.g. no server or a fresh
    client) must not log anything — this is the exact noise pattern the real
    user session showed (~8 repeated /reclaim probes with nothing to say)."""
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.probe_active_game",
                        lambda addr, uuid: None)
    gen = app.coordinator._reconnect_probe_gen
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.coordinator._reconnect_probe_worker("addr", "uuid", gen)
    assert caplog.records == []


def test_probe_worker_logs_info_only_on_the_reclaim_available_transition(app, monkeypatch, caplog):
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.probe_active_game",
                        lambda addr, uuid: {"room_id": "r-1", "session_token": "t"})
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda addr, room, token: {"fen": ""})
    gen = app.coordinator._reconnect_probe_gen
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.coordinator._reconnect_probe_worker("addr", "uuid", gen)
    info_lines = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_lines) == 1
    assert info_lines[0].getMessage() == "reclaim available room=r-1"


def test_probe_worker_does_not_relog_reclaim_available_while_still_pending(
        app, monkeypatch, caplog):
    """A steady state where a reclaimable game is already known must not
    re-announce it every 5s poll — only the None -> available transition
    is a state change worth an INFO line."""
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.probe_active_game",
                        lambda addr, uuid: {"room_id": "r-1", "session_token": "t"})
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda addr, room, token: {"fen": ""})
    gen = app.coordinator._reconnect_probe_gen
    app.coordinator._reconnect_probe_worker("addr", "uuid", gen)
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.coordinator._reconnect_probe_worker("addr", "uuid", gen)
    assert not any(r.levelno == logging.INFO for r in caplog.records)
