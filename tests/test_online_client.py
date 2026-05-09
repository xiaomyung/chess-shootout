"""URL builder unit tests. Live in transport.py post-M19; the client just delegates."""
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
