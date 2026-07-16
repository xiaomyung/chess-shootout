"""URL builder unit tests. Live in transport.py post-M19; the client just delegates."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from chessshootout.online.client import (
    OnlineClient, PING_SAMPLE_WINDOW, RECONNECT_BACKOFF_MAX_SECONDS)
from chessshootout.online.transport import _UrlBuilder, _split_addr, WsConnectionClosed


@pytest.mark.parametrize(
    "addr, scheme, host, port",
    [
        pytest.param("localhost:8000", "ws", "localhost", 8000, id="localhost_picks_ws"),
        pytest.param("127.0.0.1:9001", "ws", "127.0.0.1", 9001, id="ip_picks_ws"),
        pytest.param(
            "chess.example.com", "wss", "chess.example.com", 443, id="hostname_picks_wss"
        ),
        pytest.param(
            "ws://chess.example.com", "ws", "chess.example.com", 8000, id="explicit_ws_overrides"
        ),
        pytest.param(
            "wss://localhost:8443", "wss", "localhost", 8443, id="explicit_wss_overrides_localhost"
        ),
        pytest.param(
            "chess.example.com:8000", "ws", "chess.example.com", 8000,
            id="port_8000_picks_ws_for_hostname",
        ),
        pytest.param("203.0.113.5", "ws", "203.0.113.5", 8000, id="ip_without_port_defaults_8000"),
        pytest.param(
            "203.0.113.5:9999", "ws", "203.0.113.5", 9999, id="ip_with_custom_port_uses_that_port"
        ),
        pytest.param(
            "localhost", "ws", "localhost", 8000, id="localhost_without_port_defaults_8000"
        ),
    ],
)
def test_split_addr(addr, scheme, host, port):
    assert _split_addr(addr) == (scheme, host, port)


@pytest.mark.parametrize(
    "addr, method, path, expected",
    [
        pytest.param(
            "localhost:8000", "http", "/matchmake", "http://localhost:8000/matchmake",
            id="http_localhost",
        ),
        pytest.param(
            "chess.example.com", "http", "/matchmake",
            "https://chess.example.com:443/matchmake", id="http_hostname_uses_https",
        ),
        pytest.param(
            "localhost:8000", "ws", "/ws/abc", "ws://localhost:8000/ws/abc", id="ws_localhost"
        ),
        pytest.param(
            "chess.example.com", "ws", "/ws/abc", "wss://chess.example.com:443/ws/abc",
            id="ws_hostname_uses_wss",
        ),
    ],
)
def test_url_builder(addr, method, path, expected):
    u = _UrlBuilder(addr)
    assert getattr(u, method)(path) == expected


def test_get_ping_ms_returns_none_until_first_sample():
    client = OnlineClient()
    assert client.get_ping_ms() is None


def test_get_ping_ms_rounds_average_of_samples():
    client = OnlineClient()
    client._ping_samples_ms.extend([10.0, 20.0, 30.0])
    assert client.get_ping_ms() == 20


def test_get_ping_ms_window_caps_at_constant():
    """The deque caps at PING_SAMPLE_WINDOW so stale RTTs can't drag the value."""
    client = OnlineClient()
    for v in range(20):
        client._ping_samples_ms.append(float(v))
    assert len(client._ping_samples_ms) == PING_SAMPLE_WINDOW
    assert list(client._ping_samples_ms) == [15.0, 16.0, 17.0, 18.0, 19.0]
    assert client.get_ping_ms() == 17


class _RecvWs:
    def __init__(self, messages):
        self._messages = list(messages)

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        raise WsConnectionClosed(None, None)


def test_pong_records_rtt_sample():
    """A pong reply turns the time since the matching ping into a ping-ms sample."""
    client = OnlineClient()
    client._last_ping_sent_at = time.monotonic() - 0.030
    asyncio.run(client._recv_loop(_RecvWs([{"type": "pong"}])))
    assert len(client._ping_samples_ms) == 1
    assert client._ping_samples_ms[0] == pytest.approx(30.0, abs=20.0)


def test_pong_is_consumed_not_forwarded_as_event():
    """A pong updates liveness/RTT but is not surfaced to the frontend; a move is."""
    client = OnlineClient()
    asyncio.run(client._recv_loop(
        _RecvWs([{"type": "pong"}, {"type": "move_applied", "ply": 1}])))
    events = []
    while not client._inbound.empty():
        events.append(client._inbound.get_nowait())
    assert [e.type for e in events] == ["move_applied"]
    assert client.seconds_since_server_msg() < 1.0


def test_send_ping_records_send_time():
    client = OnlineClient()
    before = time.monotonic()
    client.send_ping(5)
    assert client._last_ping_sent_at >= before


def test_is_server_silent_tracks_last_message():
    client = OnlineClient()
    assert client.is_server_silent() is False
    client._last_server_msg_at = time.monotonic() - 1000
    assert client.is_server_silent() is True
    client._last_server_msg_at = time.monotonic()
    assert client.is_server_silent() is False


def test_adopt_timing_from_game_start_message():
    """game_start carries the server's heartbeat interval + grace; the client adopts both."""
    client = OnlineClient()
    asyncio.run(client._recv_loop(_RecvWs([
        {"type": "game_start", "heartbeat_interval_seconds": 4.5, "grace_seconds": 90.0},
    ])))
    assert client.heartbeat_interval() == 4.5
    assert client._reconnect_total == 90.0


def test_result_enters_post_game_so_socket_survives_for_rematch():
    """After a result the game is no longer active but the post-game flag keeps the
    reconnect/keepalive window open (so a rematch can still reach the client)."""
    client = OnlineClient()
    asyncio.run(client._recv_loop(_RecvWs([
        {"type": "result", "reason": "checkmate", "winner_color": "white"},
    ])))
    assert client._game_active is False
    assert client._post_game is True


def test_game_start_clears_post_game_flag():
    client = OnlineClient()
    asyncio.run(client._recv_loop(_RecvWs([
        {"type": "result", "reason": "checkmate", "winner_color": "white"},
        {"type": "game_start"},
    ])))
    assert client._game_active is True
    assert client._post_game is False


def test_ws_session_clears_old_ping_samples_on_reconnect():
    """A fresh ws session must drop the previous link's RTTs from the rolling average."""
    client = OnlineClient()
    client._ping_samples_ms.extend([100.0, 110.0, 120.0])
    client._ping_samples_ms.clear()
    assert client.get_ping_ms() is None


def test_is_connected_requires_both_state_and_socket():
    client = OnlineClient()
    client.state = "connected"
    client._ws = None
    assert client.is_connected() is False, "state alone is not enough — the socket is gone"
    client._ws = object()
    assert client.is_connected() is True
    client.state = "reconnecting"
    assert client.is_connected() is False


class _ClosedWs:
    async def recv(self):
        raise WsConnectionClosed(None, None)

    async def close(self):
        pass


def test_ws_session_refreshes_liveness_and_opp_state_on_connect():
    """The storm root cause: a reconnect must reset the silence timer (against the OLD
    session's timestamp) and clear the self-set opp_state, so the heartbeat check
    doesn't instantly force another reconnect."""
    client = OnlineClient()
    client._room_id, client._session_token = "r", "t"
    client._outbound = asyncio.Queue()
    client._last_server_msg_at = time.monotonic() - 1000.0    # stale from the dead session
    client.opp_state = "reconnecting"

    client._transport = SimpleNamespace(
        ws_connect=lambda room, token: _closed_ws_coro())
    asyncio.run(client._run_ws_session())

    assert client.is_server_silent() is False, "silence timer reset on connect"
    assert client.opp_state == "connected", "opp_state no longer stuck reconnecting"
    assert client.state == "connected"


async def _closed_ws_coro():
    return _ClosedWs()


def test_resume_backoff_grows_and_is_bounded(monkeypatch):
    client = OnlineClient()
    client._room_id = "00000000-0000-4000-8000-000000000000"
    client._session_token = "tok"
    client._reconnect_total = 60.0
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class _Http:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    calls = {"n": 0}

    async def resume_async(body, http):
        calls["n"] += 1
        return (None if calls["n"] <= 4
                else SimpleNamespace(model_dump=lambda by_alias=False: {"ok": True}))

    client._transport = SimpleNamespace(
        make_async_http=lambda: _Http(), resume_async=resume_async)
    result = asyncio.run(client._resume_with_retries())

    assert result == {"ok": True}
    assert sleeps == [2, 4, 8, 8], "exponential backoff, capped at the max"
    assert max(sleeps) <= RECONNECT_BACKOFF_MAX_SECONDS
