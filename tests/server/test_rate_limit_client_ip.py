import ipaddress

import pytest
from starlette.requests import Request

from chessshootout.server.app import (
    _parse_trusted_proxies, _peer_trusted, client_ip_key,
)

TRUSTED = [ipaddress.ip_network("172.28.0.0/16")]


def make_request(peer_ip, headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "headers": raw}
    scope["client"] = (peer_ip, 12345) if peer_ip is not None else None
    return Request(scope)


def test_parse_trusted_proxies_parses_cidrs_and_skips_blanks_and_invalid():
    nets = _parse_trusted_proxies("172.28.0.0/16, , 10.0.0.1, not-an-ip, ::1/128")
    assert [str(n) for n in nets] == ["172.28.0.0/16", "10.0.0.1/32", "::1/128"]


def test_parse_trusted_proxies_empty_string_yields_no_networks():
    assert _parse_trusted_proxies("") == []


@pytest.mark.parametrize("peer,expected", [
    ("172.28.0.5", True),
    ("172.29.0.5", False),
    ("8.8.8.8", False),
    ("testclient", False),
])
def test_peer_trusted_matches_only_configured_networks(peer, expected):
    assert _peer_trusted(peer, TRUSTED) is expected


def test_client_ip_key_ignores_spoofed_cf_header_from_untrusted_peer():
    req = make_request("8.8.8.8", {"cf-connecting-ip": "1.2.3.4"})
    assert client_ip_key(req, TRUSTED) == "8.8.8.8"


def test_client_ip_key_honors_cf_header_from_trusted_peer():
    req = make_request("172.28.0.5", {"cf-connecting-ip": "1.2.3.4"})
    assert client_ip_key(req, TRUSTED) == "1.2.3.4"


def test_client_ip_key_falls_back_to_socket_ip_for_trusted_peer_without_cf_header():
    req = make_request("172.28.0.5")
    assert client_ip_key(req, TRUSTED) == "172.28.0.5"


def test_client_ip_key_strips_whitespace_from_cf_header():
    req = make_request("172.28.0.5", {"cf-connecting-ip": "  1.2.3.4  "})
    assert client_ip_key(req, TRUSTED) == "1.2.3.4"


def test_client_ip_key_uses_loopback_when_request_has_no_client():
    req = make_request(None, {"cf-connecting-ip": "1.2.3.4"})
    assert client_ip_key(req, TRUSTED) == "127.0.0.1"


def test_client_ip_key_defaults_to_module_trusted_proxies(monkeypatch):
    import chessshootout.server.app as app_module
    monkeypatch.setattr(
        app_module, "TRUSTED_PROXIES", [ipaddress.ip_network("10.1.0.0/16")],
    )
    trusted_req = make_request("10.1.2.3", {"cf-connecting-ip": "9.9.9.9"})
    untrusted_req = make_request("8.8.8.8", {"cf-connecting-ip": "9.9.9.9"})
    assert client_ip_key(trusted_req) == "9.9.9.9"
    assert client_ip_key(untrusted_req) == "8.8.8.8"


def test_client_ip_key_trusts_cf_header_from_loopback_under_default_config():
    trusted = _parse_trusted_proxies("127.0.0.1/32")
    req = make_request("127.0.0.1", {"cf-connecting-ip": "1.2.3.4"})
    assert client_ip_key(req, trusted) == "1.2.3.4"
