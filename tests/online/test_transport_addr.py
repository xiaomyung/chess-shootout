"""A malformed server address must not crash the app.

`env.set_custom_server_addr` persists whatever the user types in Options with no
validation, and `OnlineClient.connect` builds `ServerTransport(addr)`
synchronously on the main thread. A non-numeric port (e.g. "myserver:abc")
used to raise an uncaught ValueError straight through connect() and crash the
process; now `_split_addr` raises a `TransportError`, which the entry points
turn into a graceful `server_unreachable` event instead.

`probe_server_health` is the third such entry point: it is handed the address
straight out of the Options field, so it goes through the same guard.
"""

import pytest

from chessshootout.online.transport import ServerTransport, TransportError
from chessshootout.online.client import OnlineClient, probe_active_game, probe_server_health
from chessshootout.server.protocol import HealthResponse, PROTOCOL_VERSION


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


@pytest.mark.parametrize("blank", ["", None])
def test_probe_server_health_returns_none_for_a_blank_address(blank):
    """An empty address never becomes a request: ServerTransport("") would parse
    into a host-less URL and the probe would report on nothing."""
    assert probe_server_health(blank) is None


@pytest.mark.parametrize("addr", [
    pytest.param("myserver:abc", id="non_numeric_port"),
    pytest.param("éxàmple..com", id="invalid_idna_hostname"),
    pytest.param("a" * 70 + ".com", id="dns_label_over_63_chars"),
])
def test_probe_server_health_returns_none_for_an_unparseable_address(addr):
    """Three distinct escape shapes, one contract. The bad port raises
    TransportError at ServerTransport construction; the accented hostname makes
    httpx raise InvalidURL (which is NOT an HTTPError subclass) when the request
    URL is built; the oversize label reaches getaddrinfo, whose idna codec
    raises a bare UnicodeError before any network I/O. The latter two used to
    escape probe_server_health and kill the daemon worker that called it --
    _sync_request now converts both to TransportError."""
    assert probe_server_health(addr) is None


def test_probe_server_health_returns_none_when_the_server_does_not_answer(monkeypatch):
    monkeypatch.setattr(ServerTransport, "healthz_blocking",
                        lambda self, *, timeout=None: None)
    assert probe_server_health("localhost:8000") is None


def test_probe_server_health_returns_the_health_dict(monkeypatch):
    """The caller renders the protocol version and the app version, so the probe
    hands back the whole dumped model rather than a reachable/unreachable flag."""
    health = HealthResponse(version=PROTOCOL_VERSION, app_version="2.12.1",
                            rooms_active=2, queue_depth=1, uptime_s=9.0)
    seen = []

    def fake_healthz(self, *, timeout=None):
        seen.append((self.addr, timeout))
        return health

    monkeypatch.setattr(ServerTransport, "healthz_blocking", fake_healthz)
    payload = probe_server_health("localhost:8000", timeout=0.5)
    assert payload["version"] == PROTOCOL_VERSION
    assert payload["app_version"] == "2.12.1"
    assert payload["rooms_active"] == 2
    assert seen == [("localhost:8000", 0.5)]


def test_probe_server_health_reports_a_missing_version_as_none(monkeypatch):
    """HealthResponse.version defaults to PROTOCOL_VERSION client-side, so a
    /healthz body that omits "version" validates cleanly and would read as a
    perfect protocol match against a server whose version is unknown. The
    chosen seam is pydantic's model_fields_set: healthz_blocking keeps
    returning the plain model through the shared _blocking_request (its other
    callers only care about reachability, and the field default keeps every
    other payload parse unchanged), and probe_server_health -- the one caller
    that renders the version -- rewrites the dumped dict's version to None
    when the raw payload never carried the key, which the settings probe then
    describes as a protocol mismatch against "v?"."""
    health = HealthResponse.model_validate(
        {"status": "ok", "app_version": "2.12.1", "rooms_active": 1})
    monkeypatch.setattr(ServerTransport, "healthz_blocking",
                        lambda self, *, timeout=None: health)
    payload = probe_server_health("localhost:8000")
    assert payload["version"] is None
    assert payload["app_version"] == "2.12.1"
