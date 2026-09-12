"""Reconnect → server is the source of truth for the resumed game.

Two reconnect paths land here:

1. Mid-game ws-drop. The OnlineClient already holds a `_time_control` and
   the GameScreen's variant is already "online", so `_handle_game_resumed`
   is enough on its own — replay SANs + apply the server's clock snapshot.
2. App-restart resume. The user clicks the start-menu Reconnect button on
   a fresh process. `_on_reconnect_active_game` fetches /resume on a worker
   thread and the next `coordinator.update()` adopts the answer on the main
   thread via `_adopt_reconnect_result`: `_start_online_game(resume)`
   followed by `_handle_game_resumed(resume)`. The async loop only opens
   the WS — it no longer queues a duplicate `game_start` / `game_resumed`
   pair, which used to race with the 500 ms match-found transition and
   reset the board + clock back to the starting position with full time.
"""

import logging
import threading
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceColor
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.online_coordinator import (
    APPLY_FAILED_LABEL, RECONNECT_PROBE_MAX_ATTEMPTS, ReconnectAnswer,
)


_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def app():
    fe = Frontend(1000, 800)
    fe.sound_manager = MagicMock()
    yield fe
    pg.display.set_mode((1000, 800))


def _reconnect_now(app):
    """Press Reconnect, let the worker finish its fetch, and run the frame that
    adopts the answer -- the whole path a real click takes, minus the wait."""
    app.coordinator._on_reconnect_active_game()
    thread = app.coordinator._reconnect_resume_thread
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive(), "the resume fetch never returned"
    app.coordinator.update(pg.time.get_ticks())


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
    """App-restart Reconnect fetches off-thread and adopts on the next frame;
    reconnect_to_existing is stubbed so no WS opens."""
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

    _reconnect_now(app)

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
    _reconnect_now(app)
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
    _reconnect_now(app)
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
    pytest.param(lambda p: p.pop("time_minutes"),
                 id="time_control_missing_before_the_board_is_even_built"),
])
def test_reconnect_adoption_survives_a_hostile_resume_payload(
        app, monkeypatch, tmp_path, caplog, mutate):
    """Every inbound ws event runs inside the drain's try/except, but Reconnect
    adopts a /resume payload from its own worker's answer — outside it. A
    payload the replay chokes on took the whole app down from a button click.
    Adoption now runs through the same guard, at both layers: the snapshot
    replay (`resume adoption`) and the game start around it (`reconnect
    adoption`). Either way: logged, toasted once, and the session is dropped
    back to the menu."""
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
        _reconnect_now(app)

    assert app.screen is app.menu
    assert app.coordinator.client is None
    assert app.toast.is_visible()
    failures = [r for r in caplog.records if "adoption failed" in r.getMessage()]
    assert len(failures) == 1


def test_a_snapshot_that_will_not_replay_abandons_the_game(app, caplog, monkeypatch, tmp_path):
    """There is no FEN rescue any more: a history the engine cannot replay used
    to leave a truncated board whose heartbeat ply was permanently wrong, so
    the server ordered a resync every few seconds forever. Now the replay
    raises, the coordinator's guard catches it, and the game is abandoned
    outright -- session dropped, back on the menu, one toast, no resync gate
    left up and no ply for the heartbeat to misreport."""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.toast = MagicMock()
    app.coordinator.client = MagicMock()
    app.coordinator.client.room_id = "room-1"
    app.coordinator.subscribe(app.game)
    app.screen = app.game
    app.game.variant = Variant.ONLINE
    app.game._time_control = (300, 2)
    app.game.match.local_color = PieceColor.WHITE
    app.game._chosen_side = "white"
    app.coordinator._resyncing = True
    payload = _resume_payload(move_history=("e4", "zzz"))

    with caplog.at_level(logging.ERROR, logger="chess.frontend"):
        app.coordinator._handle_game_resumed(payload)

    assert app.coordinator.client is None
    assert app.screen is app.menu
    assert app.coordinator._resyncing is False
    assert app.coordinator._heartbeat_ply() is None
    app.toast.show.assert_called_once_with(APPLY_FAILED_LABEL, key="online_apply_failed")
    assert [r.getMessage() for r in caplog.records
            if r.levelno >= logging.ERROR] == ["online resume adoption failed"]


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

    _reconnect_now(app)

    assert app.game.black_name == "b" * _NICKNAME_MAX_LEN
    assert app.game.white_name == "alice"
    app.draw_frame()


def test_a_reconnect_fetch_that_hangs_never_holds_the_frame(app, monkeypatch):
    """/resume used to be called on the render thread from the button's
    callback: a server that answered slowly froze the whole window for as
    long as it took. The fetch now runs on a worker, and a frame drawn while
    it is still out returns at once with the player still on the menu."""
    monkeypatch.setattr("chessshootout.online.client.OnlineClient.reconnect_to_existing",
                        lambda self, *a, **kw: None)
    release = threading.Event()
    answer = _resume_payload(move_history=("e4",))
    released = []

    def _slow_fetch(addr, room_id, session_token):
        released.append(release.wait(timeout=5))
        return answer

    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume", _slow_fetch)
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000", "room_id": "room-s", "session_token": "tok",
    }

    app.coordinator._on_reconnect_active_game()
    app.coordinator.update(pg.time.get_ticks())

    assert app.screen is app.menu
    assert app.coordinator.client is None
    assert not app.menu.play_view.reconnect_available, "the offer is taken while the fetch is out"
    assert app.coordinator._reconnect_resume_thread.is_alive()

    release.set()
    app.coordinator._reconnect_resume_thread.join(timeout=5)
    assert released == [True], "the test never released the fetch"
    app.coordinator.update(pg.time.get_ticks())

    assert app.screen is app.game
    assert [e.san for e in app.game.match.move_history] == ["e4"]


def test_a_reconnect_fetch_answering_a_stale_generation_is_dropped(app, monkeypatch):
    """The fetch carries the probe generation it left under. A server change
    while it was out bumps that generation, so the answer it brings back
    belongs to a game on a server the player has already left."""
    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume",
                        lambda *a, **kw: _resume_payload())
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000", "room_id": "room-g", "session_token": "tok",
    }
    monkeypatch.setattr("threading.Thread", lambda *a, **k: MagicMock())

    app.coordinator._on_reconnect_active_game()
    gen = app.coordinator._reconnect_probe_gen
    app.coordinator.on_server_target_changed()
    app.coordinator._reconnect_resume_worker(
        {"addr": "localhost:8000", "room_id": "room-g", "session_token": "tok"}, gen)
    app.coordinator.update(pg.time.get_ticks())

    assert app.coordinator._reconnect_result is None
    assert app.screen is app.menu
    assert app.coordinator.client is None


def test_a_search_started_mid_fetch_retires_the_reconnect_answer(app, monkeypatch):
    """REGRESSION: the /resume answer is adopted a frame or more after the
    worker fetched it. A player who gave up waiting and pressed Play in that
    window had the fresh search's client torn down and replaced by the old
    room's board. Starting a search retires the fetch's generation, so its
    answer is never even filed."""
    monkeypatch.setattr("chessshootout.online.client.OnlineClient.connect",
                        lambda self, *a, **kw: None)
    monkeypatch.setattr("chessshootout.online.client.OnlineClient.reconnect_to_existing",
                        lambda self, *a, **kw: None)
    release = threading.Event()
    released = []

    def _slow_fetch(addr, room_id, session_token):
        released.append(release.wait(timeout=5))
        return _resume_payload(move_history=("e4",))

    monkeypatch.setattr("chessshootout.frontend.online_coordinator.fetch_resume", _slow_fetch)
    app.coordinator._pending_reconnect = {
        "addr": "localhost:8000", "room_id": "room-r", "session_token": "tok",
    }
    app.coordinator._online_config = {
        "nickname": "alice", "time_minutes": 5, "increment_seconds": 0, "side": "random",
    }

    app.coordinator._on_reconnect_active_game()
    app.coordinator._on_server_addr_connect("localhost:8000")
    searching = app.coordinator.client
    release.set()
    app.coordinator._reconnect_resume_thread.join(timeout=5)
    assert released == [True], "the test never released the fetch"

    assert app.coordinator._reconnect_result is None, \
        "a retired fetch never files its answer for the next frame"
    app.coordinator._drain_reconnect_result()
    assert app.coordinator.client is searching
    assert app.screen is app.menu
    assert app.game.match.move_history == []


def test_a_reconnect_answer_is_refused_once_a_session_is_live(app, monkeypatch, caplog):
    """The generation bump is the first gate; this is the second. Whatever put
    a session there -- a search, a second Reconnect press -- adopting on top of
    it would disconnect a live client and rebuild the board from another
    room's snapshot, so a late answer is dropped where it lands."""
    monkeypatch.setattr("chessshootout.online.client.OnlineClient.reconnect_to_existing",
                        lambda self, *a, **kw: None)
    live = MagicMock()
    app.coordinator.client = live
    pending = {"addr": "localhost:8000", "room_id": "room-r", "session_token": "tok"}

    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.coordinator._adopt_reconnect_result(
            ReconnectAnswer(pending, _resume_payload(move_history=("e4",))))

    assert app.coordinator.client is live
    assert app.screen is app.menu
    assert app.game.match.move_history == []
    assert not app.confirm_modal.is_visible()
    assert any("reconnect answer ignored" in r.getMessage() for r in caplog.records)


def test_the_reclaim_probe_stays_quiet_while_a_reconnect_fetch_is_out(app, monkeypatch):
    """The probe bumps the generation every time it spawns. One spawning while
    the reconnect fetch is still out would strand that fetch's answer, so the
    live worker thread is what keeps the probe from starting."""
    started = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: started.append(1) or MagicMock())
    app.coordinator._reconnect_resume_thread = MagicMock(is_alive=lambda: True)
    app.coordinator._reconnect_probe_inflight = False
    app.coordinator._pending_reconnect = None
    app.coordinator._reconnect_probe_attempts = 0
    monkeypatch.setattr("chessshootout.infra.env.get_server_addr", lambda: "localhost:8000")

    app.coordinator._spawn_reconnect_probe()

    assert started == []


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
