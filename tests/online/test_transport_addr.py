"""A malformed server address must not crash the app.

`env.set_server_addr` persists whatever the user types in Options with no
validation, and `OnlineClient.connect` builds `ServerTransport(addr)`
synchronously on the main thread. A non-numeric port (e.g. "myserver:abc")
used to raise an uncaught ValueError straight through connect() and crash the
process; now `_split_addr` raises a `TransportError`, which the entry points
turn into a graceful `server_unreachable` event instead.
"""

import pytest

from chessshootout.online.transport import ServerTransport, TransportError
from chessshootout.online.client import OnlineClient, probe_active_game


def test_malformed_port_raises_transport_error():
    with pytest.raises(TransportError):
        ServerTransport("myserver:abc")


def test_valid_address_still_parses():
    assert ServerTransport("localhost:8000") is not None
    assert ServerTransport("chess.example.com") is not None


def test_connect_with_bad_address_does_not_crash():
    client = OnlineClient()
    client.connect("myserver:abc", {})
    event = client._inbound.get_nowait()
    assert event.type == "error"
    assert event.payload["reason"] == "server_unreachable"
    assert client.state == "disconnected"
    assert client._thread is None


def test_reconnect_with_bad_address_does_not_crash():
    client = OnlineClient()
    client.reconnect_to_existing("myserver:abc", "room", "tok", {})
    event = client._inbound.get_nowait()
    assert event.type == "error"
    assert event.payload["reason"] == "reconnect_failed"
    assert client.state == "disconnected"


def test_probe_active_game_returns_none_on_bad_address():
    assert probe_active_game("myserver:abc", "uuid-1234") is None
