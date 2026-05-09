"""URL builder unit tests. Live in transport.py post-M19; the client just delegates."""
import asyncio

import pytest

from frontend.online.client import OnlineClient, PING_SAMPLE_WINDOW
from frontend.online.transport import _UrlBuilder, _split_addr


def test_split_addr_localhost_picks_ws():
    scheme, host, port = _split_addr("localhost:8000")
    assert scheme == "ws" and host == "localhost" and port == 8000


def test_split_addr_ip_picks_ws():
    scheme, host, port = _split_addr("127.0.0.1:9001")
    assert scheme == "ws" and host == "127.0.0.1" and port == 9001


def test_split_addr_hostname_picks_wss():
    scheme, host, port = _split_addr("chess.example.com")
    assert scheme == "wss" and host == "chess.example.com" and port == 443


def test_split_addr_explicit_ws_overrides():
    scheme, host, port = _split_addr("ws://chess.example.com")
    assert scheme == "ws" and host == "chess.example.com"


def test_split_addr_explicit_wss_overrides_localhost():
    scheme, host, port = _split_addr("wss://localhost:8443")
    assert scheme == "wss" and host == "localhost" and port == 8443


def test_split_addr_port_8000_picks_ws_for_hostname():
    scheme, host, port = _split_addr("chess.example.com:8000")
    assert scheme == "ws" and host == "chess.example.com" and port == 8000


def test_url_builder_http_localhost():
    u = _UrlBuilder("localhost:8000")
    assert u.http("/matchmake") == "http://localhost:8000/matchmake"


def test_url_builder_http_hostname_uses_https():
    u = _UrlBuilder("chess.example.com")
    assert u.http("/matchmake") == "https://chess.example.com:443/matchmake"


def test_url_builder_ws_localhost():
    u = _UrlBuilder("localhost:8000")
    assert u.ws("/ws/abc") == "ws://localhost:8000/ws/abc"


def test_url_builder_ws_hostname_uses_wss():
    u = _UrlBuilder("chess.example.com")
    assert u.ws("/ws/abc") == "wss://chess.example.com:443/ws/abc"


# ---------- ping rolling average exposed for the game-info panel ----------

def test_get_ping_ms_returns_none_until_first_sample():
    client = OnlineClient()
    assert client.get_ping_ms() is None


def test_get_ping_ms_rounds_average_of_samples():
    client = OnlineClient()
    client._ping_samples_ms.extend([10.0, 20.0, 30.0])
    assert client.get_ping_ms() == 20


def test_get_ping_ms_window_caps_at_constant():
    # The deque caps at PING_SAMPLE_WINDOW so very old samples don't drag
    # the displayed value when the connection's RTT changes.
    client = OnlineClient()
    for v in range(20):
        client._ping_samples_ms.append(float(v))
    assert len(client._ping_samples_ms) == PING_SAMPLE_WINDOW
    # Last 5 samples are 15..19, mean = 17.0.
    assert client.get_ping_ms() == 17


# ---------- ping loop pushes samples from ws.ping() ----------

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
    # Shrink the inter-ping wait so the test runs in milliseconds.
    monkeypatch.setattr("frontend.online.client.PING_INTERVAL_SECONDS", 0.001)

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
    assert client.get_ping_ms() in (40, 41, 42, 43, 44, 45)  # rolling mean of first 3


def test_ping_loop_swallows_transient_ping_failures(monkeypatch):
    monkeypatch.setattr("frontend.online.client.PING_INTERVAL_SECONDS", 0.001)

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

    # Failure was swallowed; the next successful ping landed.
    assert client._ping_samples_ms[-1] == pytest.approx(25.0)
    assert fake_ws.calls >= 2


def test_ws_session_clears_old_ping_samples_on_reconnect():
    # When a new ws session starts (mid-game reconnect), stale RTTs from the
    # previous link must not skew the rolling average.
    client = OnlineClient()
    client._ping_samples_ms.extend([100.0, 110.0, 120.0])
    # Simulate the cleanup _run_ws_session does at the top of a fresh session.
    client._ping_samples_ms.clear()
    assert client.get_ping_ms() is None
