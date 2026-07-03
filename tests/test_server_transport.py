"""M19: ServerTransport + ServerWebSocket are the single client-side surface
for HTTP and WS interactions with the server.

Strategy:
- HTTP tests use httpx.MockTransport routed through ServerTransport's
  _http_client constructor arg, so we hit a hand-rolled fake handler
  rather than spinning up uvicorn for each case. That keeps coverage
  fast and lets us assert the wire-level method/path/body shape.
- WS tests use the real in-process server (the `server` fixture in
  tests/conftest.py, shared with test_online_flow.py) and verify each
  ServerWebSocket send_* method round-trips through the real protocol path.
- Schema-version-mismatch is hit via a fake server response.
"""
import asyncio
import json
import ssl

import httpx
import pytest

from chessshootout.online.transport import (
    FatalResumeError, SchemaVersionMismatch, ServerTransport, ServerWebSocket,
    TransportError, TransportHTTPError,
)
from chessshootout.server.protocol import (
    HealthResponse, MatchmakeRequest, MatchmakeResponse, PROTOCOL_VERSION,
    Reason, ResumeRequest,
)
from tests.helpers import fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


def _make_handler(*, status_code=200, body=None, capture=None):
    def handler(request):
        if capture is not None:
            capture.append({
                "method": request.method,
                "url": str(request.url),
                "json": json.loads(request.content) if request.content else None,
            })
        return httpx.Response(status_code=status_code, json=body)
    return handler


@pytest.fixture
def captured():
    return []


@pytest.fixture
def fake_http(captured):
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body={"status": "ok"}, capture=captured,
    ))
    with httpx.Client(transport=transport) as client:
        yield client


def test_healthz_hits_get_path(captured):
    body = {"status": "ok", "version": PROTOCOL_VERSION,
            "rooms_active": 7, "queue_depth": 2, "uptime_s": 99.9}
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body=body, capture=captured,
    ))
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        resp = st.healthz()
    assert isinstance(resp, HealthResponse)
    assert resp.rooms_active == 7
    assert resp.queue_depth == 2
    assert captured[0]["method"] == "GET"
    assert captured[0]["url"].endswith("/healthz")


def test_reclaim_blocking_returns_typed_response(captured):
    body = {"version": PROTOCOL_VERSION, "room_id": fake_uuid4(50),
            "session_token": "tok-99"}
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body=body, capture=captured,
    ))
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        resp = st.reclaim_blocking(ALICE)
    assert resp is not None
    assert resp.session_token == "tok-99"
    assert captured[0]["method"] == "POST"
    assert captured[0]["url"].endswith("/reclaim")
    assert captured[0]["json"]["client_uuid"] == ALICE


def test_reclaim_blocking_returns_none_on_404(captured):
    transport = httpx.MockTransport(_make_handler(
        status_code=404, body={"reason": "not_in_room"}, capture=captured,
    ))
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        assert st.reclaim_blocking(ALICE) is None


def test_resume_blocking_returns_typed_response(captured):
    body = {
        "version": PROTOCOL_VERSION,
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "move_history": [],
        "clock": {"white_remaining": 60.0, "black_remaining": 60.0,
                    "running_for": "white"},
        "your_color": "white",
        "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 5, "increment_seconds": 0,
        "skillcheck_locks": [{"from": "e4", "to": "d5"}],
        "pending_skillcheck": {
            "kind": "aim", "seed": "s", "value_diff": 3, "deadline_ms": 5000.0,
            "elapsed_ms": 100.0, "miss_count": 0, "from": "e4", "to": "d5",
            "promotion": None, "color": "white",
        },
    }
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body=body, capture=captured,
    ))
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        resp = st.resume_blocking(fake_uuid4(50), "tok-99")
    assert resp is not None
    assert resp.your_color == "white"
    assert resp.skillcheck_locks[0].from_sq == "e4"
    assert resp.pending_skillcheck.from_sq == "e4" and resp.pending_skillcheck.color == "white"
    assert captured[0]["method"] == "POST"
    assert captured[0]["url"].endswith("/resume")


@pytest.mark.parametrize(
    "status_code, body, expected_exc, expected_status",
    [
        pytest.param(500, {"reason": "boom"}, TransportHTTPError, 500,
                     id="unknown_5xx_raises_http_error"),
        pytest.param(400, {"reason": Reason.VERSION_MISMATCH},
                     SchemaVersionMismatch, None,
                     id="version_mismatch_reason_raises_schema_mismatch"),
    ],
)
def test_sync_http_error_status_maps_to_exception(
    captured, status_code, body, expected_exc, expected_status,
):
    """Sync _parse_response: VERSION_MISMATCH reason short-circuits to
    SchemaVersionMismatch; any other >=400 surfaces TransportHTTPError."""
    transport = httpx.MockTransport(_make_handler(
        status_code=status_code, body=body, capture=captured,
    ))
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        with pytest.raises(expected_exc) as info:
            st.healthz()
    if expected_status is not None:
        assert info.value.status_code == expected_status


def test_network_failure_surfaces_transport_error():
    def boom(request):
        raise httpx.ConnectError("nope")
    transport = httpx.MockTransport(boom)
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        with pytest.raises(TransportError):
            st.healthz()


@pytest.mark.asyncio
async def test_matchmake_async_returns_typed_response(captured):
    body = {"version": PROTOCOL_VERSION, "room_id": fake_uuid4(50),
            "session_token": "tok-99"}
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body=body, capture=captured,
    ))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        req = MatchmakeRequest(nickname="Alice", client_uuid=ALICE,
                                  time_minutes=5, increment_seconds=0)
        resp = await st.matchmake_async(req, http)
    assert isinstance(resp, MatchmakeResponse)
    assert captured[0]["method"] == "POST"
    assert captured[0]["url"].endswith("/matchmake")


@pytest.mark.asyncio
async def test_matchmake_async_sends_country(captured):
    body = {"version": PROTOCOL_VERSION, "room_id": fake_uuid4(51),
            "session_token": "tok-1"}
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body=body, capture=captured,
    ))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        req = MatchmakeRequest(nickname="Alice", client_uuid=ALICE,
                                  time_minutes=5, increment_seconds=0, country="US")
        await st.matchmake_async(req, http)
    assert captured[0]["json"]["country"] == "US"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, body, expected_exc, expected_status",
    [
        pytest.param(503, {"detail": {"reason": "room_full"}},
                     TransportHTTPError, 503,
                     id="503_maps_to_typed_http_error"),
        pytest.param(400, {"reason": Reason.VERSION_MISMATCH},
                     SchemaVersionMismatch, None,
                     id="version_mismatch_reason_raises_schema_mismatch"),
    ],
)
async def test_matchmake_async_http_error_status_maps_to_exception(
    status_code, body, expected_exc, expected_status,
):
    """matchmake_async mirrors the sync mapping: VERSION_MISMATCH ->
    SchemaVersionMismatch, any other >=400 -> TransportHTTPError."""
    transport = httpx.MockTransport(_make_handler(
        status_code=status_code, body=body,
    ))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        req = MatchmakeRequest(nickname="Alice", client_uuid=ALICE,
                                  time_minutes=5, increment_seconds=0)
        with pytest.raises(expected_exc) as info:
            await st.matchmake_async(req, http)
    if expected_status is not None:
        assert info.value.status_code == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(410, id="410_game_over_is_fatal"),
        pytest.param(404, id="404_room_gone_is_fatal"),
    ],
)
async def test_resume_async_fatal_status_raises_fatal_resume_error(status_code):
    """FATAL set (410 game-over, 404 room-gone): raise FatalResumeError so the
    OnlineClient retry loop bails immediately instead of spinning the full
    reconnect window — distinct from the RETRY set below."""
    transport = httpx.MockTransport(_make_handler(
        status_code=status_code, body={"detail": {"reason": "checkmate"}},
    ))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        body = ResumeRequest(room_id=fake_uuid4(50), session_token="t")
        with pytest.raises(FatalResumeError):
            await st.resume_async(body, http)


@pytest.mark.asyncio
async def test_resume_async_5xx_returns_none_for_retry():
    """RETRY set (5xx hiccup): return None so the caller keeps retrying within
    the reconnect window — must NOT be flattened with the FATAL set."""
    transport = httpx.MockTransport(_make_handler(status_code=503, body={}))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        body = ResumeRequest(room_id=fake_uuid4(50), session_token="t")
        assert await st.resume_async(body, http) is None


@pytest.mark.asyncio
async def test_healthz_async_returns_typed_response():
    body = {"status": "ok", "version": PROTOCOL_VERSION,
            "rooms_active": 1, "queue_depth": 0, "uptime_s": 1.5}
    transport = httpx.MockTransport(_make_handler(status_code=200, body=body))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        resp = await st.healthz_async(http)
    assert resp is not None
    assert resp.rooms_active == 1


@pytest.mark.asyncio
async def test_healthz_async_returns_none_when_unreachable():
    def boom(request):
        raise httpx.ConnectError("nope")
    transport = httpx.MockTransport(boom)
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        assert await st.healthz_async(http) is None


async def _recv_skip_beacons(ws):
    """Next message that isn't a heartbeat pong, which can interleave with the
    message under test once a client starts pinging."""
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
        if msg["type"] != "pong":
            return msg


@pytest.mark.asyncio
async def test_server_websocket_send_move_round_trip(server):
    addr = f"localhost:{server}"
    st = ServerTransport(addr)

    async with httpx.AsyncClient(timeout=10.0) as http:
        a = await st.matchmake_async(
            MatchmakeRequest(nickname="Alice", client_uuid=ALICE,
                                time_minutes=5, increment_seconds=0,
                                side_preference="white"),
            http,
        )
        b = await st.matchmake_async(
            MatchmakeRequest(nickname="Bob", client_uuid=BOB,
                                time_minutes=5, increment_seconds=0,
                                side_preference="black"),
            http,
        )

    ws_a = await st.ws_connect(a.room_id, a.session_token)
    ws_b = await st.ws_connect(b.room_id, b.session_token)
    try:
        msg_a = await _recv_skip_beacons(ws_a)
        msg_b = await _recv_skip_beacons(ws_b)
        assert msg_a["type"] == "game_start"
        assert msg_b["type"] == "game_start"
        await ws_a.send_move("e2", "e4")
        applied_a = await _recv_skip_beacons(ws_a)
        applied_b = await _recv_skip_beacons(ws_b)
        assert applied_a["type"] == "move_applied"
        assert applied_a["san"] == "e4"
        assert applied_b["from"] == "e2"
        await ws_a.send_resign()
        result_a = await _recv_skip_beacons(ws_a)
        assert result_a["type"] == "result"
        assert result_a["reason"] == Reason.RESIGNATION
    finally:
        await ws_a.close()
        await ws_b.close()


@pytest.mark.asyncio
async def test_country_round_trips_through_game_start(server):
    addr = f"localhost:{server}"
    st = ServerTransport(addr)
    c1, c2 = fake_uuid4(60), fake_uuid4(61)

    async with httpx.AsyncClient(timeout=10.0) as http:
        a = await st.matchmake_async(
            MatchmakeRequest(nickname="Alice", client_uuid=c1,
                                time_minutes=5, increment_seconds=0,
                                side_preference="white", country="US"),
            http,
        )
        b = await st.matchmake_async(
            MatchmakeRequest(nickname="Bob", client_uuid=c2,
                                time_minutes=5, increment_seconds=0,
                                side_preference="black", country="RO"),
            http,
        )

    ws_a = await st.ws_connect(a.room_id, a.session_token)
    ws_b = await st.ws_connect(b.room_id, b.session_token)
    try:
        msg_a = await _recv_skip_beacons(ws_a)
        msg_b = await _recv_skip_beacons(ws_b)
        assert (msg_a["white_country"], msg_a["black_country"]) == ("US", "RO")
        assert (msg_b["white_country"], msg_b["black_country"]) == ("US", "RO")
        await ws_a.send_resign()
    finally:
        await ws_a.close()
        await ws_b.close()


@pytest.mark.asyncio
async def test_ws_connect_uses_tls_context_for_wss(monkeypatch):
    """A frozen build has no system trust store, so wss must get an explicit
    certifi-backed SSL context (regression for the v1.0.0 cert-verify bug)."""
    captured = {}

    class _FakeWs:
        async def send(self, _payload):
            pass

    async def _fake_connect(url, **kwargs):
        captured["ssl"] = kwargs.get("ssl")
        return _FakeWs()

    monkeypatch.setattr("chessshootout.online.transport.websockets.connect", _fake_connect)
    st = ServerTransport("chess.example.com")
    await st.ws_connect("room1", "tok")
    assert isinstance(captured["ssl"], ssl.SSLContext)


@pytest.mark.asyncio
async def test_ws_connect_plaintext_for_ws(monkeypatch):
    captured = {}

    class _FakeWs:
        async def send(self, _payload):
            pass

    async def _fake_connect(url, **kwargs):
        captured["ssl"] = kwargs.get("ssl")
        return _FakeWs()

    monkeypatch.setattr("chessshootout.online.transport.websockets.connect", _fake_connect)
    st = ServerTransport("localhost:8000")
    await st.ws_connect("room1", "tok")
    assert captured["ssl"] is None


class _RecordingWS:

    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        return ""

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_server_websocket_send_methods_emit_typed_payloads():
    ws = ServerWebSocket(_RecordingWS())
    inner = ws._ws

    await ws.send_move("e2", "e4", promotion=None)
    move = json.loads(inner.sent[-1])
    assert move["type"] == "move"
    assert move["from"] == "e2"
    assert move["to"] == "e4"
    assert move["promotion"] is None

    await ws.send_resign()
    assert json.loads(inner.sent[-1])["type"] == "resign"

    await ws.send_draw_offer()
    assert json.loads(inner.sent[-1])["type"] == "draw_offer"

    await ws.send_draw_response(True)
    payload = json.loads(inner.sent[-1])
    assert payload["type"] == "draw_response" and payload["accept"] is True

    await ws.send_rematch_request()
    assert json.loads(inner.sent[-1])["type"] == "rematch_request"

    await ws.send_rematch_response(False)
    payload = json.loads(inner.sent[-1])
    assert payload["type"] == "rematch_response" and payload["accept"] is False

    await ws.send_left_result()
    assert json.loads(inner.sent[-1])["type"] == "left_result"

    await ws.send_takeback_request()
    assert json.loads(inner.sent[-1])["type"] == "takeback_request"

    await ws.send_takeback_response(True)
    payload = json.loads(inner.sent[-1])
    assert payload["type"] == "takeback_response" and payload["accept"] is True

    await ws.send_give_time()
    assert json.loads(inner.sent[-1])["type"] == "give_time"

    await ws.send_ping(3)
    sent = json.loads(inner.sent[-1])
    assert sent["type"] == "ping"
    assert sent["ply"] == 3


def test_only_transport_module_imports_httpx_or_websockets():
    import os
    import re
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad_pattern = re.compile(r"^\s*(import\s+httpx|import\s+websockets|"
                                r"from\s+httpx|from\s+websockets)",
                                re.MULTILINE)
    offenders = []
    for pkg in ("frontend", "online"):
        for root, _, files in os.walk(os.path.join(root_dir, "chessshootout", pkg)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                if path.endswith(os.path.join("online", "transport.py")):
                    continue
                with open(path, encoding="utf-8") as f:
                    if bad_pattern.search(f.read()):
                        offenders.append(path)
    assert offenders == [], (
        f"only online/transport.py may import httpx/websockets: {offenders}"
    )
