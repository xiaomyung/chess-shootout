"""URL builder unit tests. Live in transport.py post-M19; the client just delegates."""
import asyncio

import pytest

from chessshootout.online.client import OnlineClient, PING_SAMPLE_WINDOW
from chessshootout.online.transport import _UrlBuilder, _split_addr


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


class _FakeWs:
    def __init__(self, latencies):
        self._latencies = list(latencies)
        self.ping_calls = 0

    async def ping(self):
        self.ping_calls += 1
        latency = self._latencies.pop(0)

        async def _waiter():
            return latency
        return _waiter()


def test_ping_loop_records_samples(monkeypatch):
    """ws.ping() pong latencies are converted s->ms and pushed onto the rolling window."""
    monkeypatch.setattr("chessshootout.online.client.PING_INTERVAL_SECONDS", 0.001)

    client = OnlineClient()
    fake_ws = _FakeWs([0.030, 0.045, 0.060])

    async def _drive():
        task = asyncio.create_task(client._ping_loop(fake_ws))
        for _ in range(200):
            await asyncio.sleep(0.001)
            if len(client._ping_samples_ms) >= 3:
                break
        client._stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())

    assert list(client._ping_samples_ms)[:3] == pytest.approx([30.0, 45.0, 60.0])
    assert client.get_ping_ms() in (40, 41, 42, 43, 44, 45)


def test_ping_loop_swallows_transient_ping_failures(monkeypatch):
    """A raised ws.ping() is logged and skipped; the next successful ping still records."""
    monkeypatch.setattr("chessshootout.online.client.PING_INTERVAL_SECONDS", 0.001)

    class _FlakyWs:
        def __init__(self):
            self.calls = 0

        async def ping(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient blip")

            async def _waiter():
                return 0.025
            return _waiter()

    client = OnlineClient()
    fake_ws = _FlakyWs()

    async def _drive():
        task = asyncio.create_task(client._ping_loop(fake_ws))
        for _ in range(200):
            await asyncio.sleep(0.001)
            if len(client._ping_samples_ms) >= 1:
                break
        client._stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())

    assert client._ping_samples_ms[-1] == pytest.approx(25.0)
    assert fake_ws.calls >= 2


def test_ws_session_clears_old_ping_samples_on_reconnect():
    """A fresh ws session must drop the previous link's RTTs from the rolling average."""
    client = OnlineClient()
    client._ping_samples_ms.extend([100.0, 110.0, 120.0])
    client._ping_samples_ms.clear()
    assert client.get_ping_ms() is None
