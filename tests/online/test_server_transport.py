"""M19: ServerTransport + ServerWebSocket are the single client-side surface
for HTTP and WS interactions with the server.

Strategy:
- HTTP tests use httpx.MockTransport routed through ServerTransport's
  http_client constructor arg, so we hit a hand-rolled fake handler
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
    FatalResumeError, NEWS_MAX_BYTES, ResponseTooLarge, SchemaVersionMismatch,
    ServerTransport, ServerWebSocket, TransportError, TransportHTTPError, fetch_news,
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


def test_reclaim_blocking_returns_none_on_network_failure():
    """_sync_request wraps a connection failure in TransportError; reclaim_blocking
    catches it and reports it the same way as any other unreachable-server case."""
    def boom(request):
        raise httpx.ConnectError("nope")
    transport = httpx.MockTransport(boom)
    with httpx.Client(transport=transport) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        assert st.reclaim_blocking(ALICE) is None


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
async def test_healthz_async_returns_typed_response(captured):
    body = {"status": "ok", "version": PROTOCOL_VERSION,
            "rooms_active": 1, "queue_depth": 0, "uptime_s": 1.5}
    transport = httpx.MockTransport(_make_handler(
        status_code=200, body=body, capture=captured,
    ))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        resp = await st.healthz_async(http)
    assert isinstance(resp, HealthResponse)
    assert resp.rooms_active == 1
    assert resp.queue_depth == 0
    assert captured[0]["method"] == "GET"
    assert captured[0]["url"].endswith("/healthz")


@pytest.mark.asyncio
async def test_healthz_async_returns_none_when_unreachable():
    def boom(request):
        raise httpx.ConnectError("nope")
    transport = httpx.MockTransport(boom)
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        assert await st.healthz_async(http) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    pytest.param(b"<html>502 Bad Gateway</html>", id="html_error_page"),
    pytest.param(b"", id="empty_body"),
    pytest.param(b'{"status": "ok", "version": NaN}', id="non_standard_constant"),
    pytest.param(b'{"status": "ok"}', id="valid_json_wrong_shape"),
])
async def test_healthz_async_returns_none_on_a_body_it_cannot_parse(content):
    """healthz is what tells room_lost apart from server-down, so a proxy that
    answers 200 with an error page must read as "no health", not as a crash --
    every failure mode (undecodable, non-standard constant, missing fields)
    collapses to the same None the unreachable case returns."""
    def handler(request):
        return httpx.Response(200, content=content,
                              headers={"content-type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        st = ServerTransport("localhost:8000")
        assert await st.healthz_async(http) is None


@pytest.mark.asyncio
async def test_healthz_async_returns_none_on_a_non_200():
    transport = httpx.MockTransport(_make_handler(status_code=503, body={}))
    async with httpx.AsyncClient(transport=transport) as http:
        st = ServerTransport("localhost:8000")
        assert await st.healthz_async(http) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    pytest.param(b"<html>429 Too Many Requests</html>", id="html_error_page"),
    pytest.param(b"", id="empty_body"),
    pytest.param(b'{"reason": Infinity}', id="non_standard_constant"),
    pytest.param(b'["room_full"]', id="json_list_not_an_object"),
    pytest.param(b'"room_full"', id="json_string_not_an_object"),
    pytest.param(b'{"detail": 7}', id="detail_is_neither_dict_nor_str"),
])
async def test_error_reason_falls_back_to_the_status_when_the_body_is_unusable(content):
    """_safe_error_reason parses an attacker-reachable error body. Anything it
    cannot turn into a reason string has to degrade to http_<status>, because the
    reason is what picks the retry modal's copy."""
    def handler(request):
        return httpx.Response(429, content=content,
                              headers={"content-type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        st = ServerTransport("localhost:8000")
        req = MatchmakeRequest(nickname="Alice", client_uuid=ALICE,
                               time_minutes=5, increment_seconds=0)
        with pytest.raises(TransportHTTPError) as info:
            await st.matchmake_async(req, http)
    assert info.value.reason == "http_429"
    assert info.value.status_code == 429


@pytest.mark.asyncio
async def test_error_reason_reads_a_plain_string_detail():
    """FastAPI's own HTTPException(detail="...") shape: the string is the reason."""
    def handler(request):
        return httpx.Response(429, json={"detail": "slow_down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        st = ServerTransport("localhost:8000")
        req = MatchmakeRequest(nickname="Alice", client_uuid=ALICE,
                               time_minutes=5, increment_seconds=0)
        with pytest.raises(TransportHTTPError) as info:
            await st.matchmake_async(req, http)
    assert info.value.reason == "slow_down"


@pytest.mark.parametrize("content", [
    pytest.param(b"<html>502 Bad Gateway</html>", id="html_error_page"),
    pytest.param(b"", id="empty_body"),
    pytest.param(b'{"room_id": "r-1"}', id="valid_json_missing_a_required_field"),
    pytest.param(b'["r-1", "tok"]', id="json_list_not_an_object"),
])
def test_blocking_post_returns_none_on_a_body_it_cannot_parse(content):
    """A 200 that is not the model is indistinguishable from no answer at all --
    reclaim_blocking runs on the startup path, so it must degrade to "no session
    to reclaim" rather than propagate a decode error into the menu."""
    def handler(request):
        return httpx.Response(200, content=content,
                              headers={"content-type": "application/json"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        assert st.reclaim_blocking(ALICE) is None


async def _recv_skip_beacons(ws):
    """Next message that isn't ambient wire noise — heartbeat pongs and the
    idle_window pushes that follow plies 1 and 2 — either of which can
    interleave with the message under test."""
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
        if msg["type"] not in ("pong", "idle_window"):
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

    await ws.send_give_time(300)
    give = json.loads(inner.sent[-1])
    assert give["type"] == "give_time" and give["hold_ms"] == 300

    await ws.send_ping(3)
    sent = json.loads(inner.sent[-1])
    assert sent["type"] == "ping"
    assert sent["ply"] == 3


@pytest.mark.asyncio
async def test_share_and_chat_sends_emit_aliased_coord_payloads():
    """The model _send path serializes by_alias, so arrow/delta coords go on the wire
    as "from"/"to" (the field names ArrowWire/AnnotationDeltaMessage validate against),
    never the Python-side from_sq/to_sq. The _send_raw dict path would skip aliasing and
    the server would reject the payload, so these must stay on _send."""
    ws = ServerWebSocket(_RecordingWS())
    inner = ws._ws

    await ws.send_annotations_state(True, ["e4", "d5"], [("e2", "e4"), ("g1", "f3")])
    state = json.loads(inner.sent[-1])
    assert state["type"] == "annotations_state"
    assert state["sharing"] is True
    assert state["highlights"] == ["e4", "d5"]
    assert state["arrows"] == [{"from": "e2", "to": "e4"}, {"from": "g1", "to": "f3"}]
    assert "from_sq" not in state["arrows"][0]

    await ws.send_annotation_delta("add", "arrow", from_sq="e2", to_sq="e4")
    delta = json.loads(inner.sent[-1])
    assert delta["type"] == "annotation_delta"
    assert delta["action"] == "add" and delta["kind"] == "arrow"
    assert delta["from"] == "e2" and delta["to"] == "e4"
    assert "from_sq" not in delta

    await ws.send_annotation_delta("remove", "highlight", square="c3")
    highlight_delta = json.loads(inner.sent[-1])
    assert highlight_delta["kind"] == "highlight"
    assert highlight_delta["square"] == "c3"
    assert highlight_delta["from"] is None and highlight_delta["to"] is None

    await ws.send_quick_chat(2)
    chat = json.loads(inner.sent[-1])
    assert chat["type"] == "quick_chat" and chat["preset"] == 2


class _ReplayWS:
    """Hands back canned raw frames the way the websockets client would."""

    def __init__(self, frames):
        self._frames = list(frames)

    async def recv(self):
        return self._frames.pop(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    pytest.param('{"type": "move_applied", "ply": Infinity}', id="infinity"),
    pytest.param('{"type": "move_applied", "ply": -Infinity}', id="negative_infinity"),
    pytest.param('{"type": "move_applied", "ply": NaN}', id="nan"),
])
async def test_recv_discards_frames_carrying_non_standard_json_constants(raw):
    """json.loads accepts the non-standard Infinity/NaN literals by default, and a
    hostile server can post them into any numeric field the client later feeds to
    pygame draw calls (which raise on inf). parse_constant rejects them at the door,
    and the frame is discarded exactly like any other malformed input."""
    ws = ServerWebSocket(_ReplayWS([raw, '{"type": "pong"}']))
    assert await ws.recv() is None
    assert await ws.recv() == {"type": "pong"}


@pytest.mark.asyncio
async def test_recv_passes_honest_frames_through_untouched():
    frame = ('{"type": "move_applied", "from": "e2", "to": "e4", "san": "e4", '
             '"ply": 1, "clock": {"white_remaining": 59.5}}')
    ws = ServerWebSocket(_ReplayWS([frame, "{not json"]))
    assert await ws.recv() == {
        "type": "move_applied", "from": "e2", "to": "e4", "san": "e4",
        "ply": 1, "clock": {"white_remaining": 59.5},
    }
    assert await ws.recv() is None


def test_http_response_body_with_a_non_standard_constant_is_rejected():
    """The same door on the HTTP side: a body that decodes to inf never reaches
    model_validate, so no inf can ride in on a /reclaim or /resume field."""
    body = ('{"version": "%s", "room_id": "%s", "session_token": Infinity}'
            % (PROTOCOL_VERSION, fake_uuid4(50)))

    def handler(request):
        return httpx.Response(200, content=body,
                              headers={"content-type": "application/json"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        st = ServerTransport("localhost:8000", http_client=client)
        assert st.reclaim_blocking(ALICE) is None


class _FakeStream:

    def __init__(self, status_code, chunks):
        self.status_code = status_code
        self._chunks = chunks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True
        return False

    def iter_bytes(self):
        yield from self._chunks


def _stub_stream(monkeypatch, stream):
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: stream)
    return stream


def test_fetch_news_aborts_past_the_byte_budget(monkeypatch):
    """The news body is attacker-controlled if CHESS_NEWS_URL (or the host behind
    it) is hostile: buffering it whole would OOM the fetch thread. The stream is
    abandoned the moment the budget is exceeded, so the oversize tail is never read."""
    chunk = b"x" * 64 * 1024
    stream = _stub_stream(monkeypatch, _FakeStream(200, [chunk] * 64))
    with pytest.raises(ResponseTooLarge):
        fetch_news("https://example.com/news.json")
    assert stream.closed is True


def test_fetch_news_accepts_a_body_at_the_budget(monkeypatch):
    payload = b'[{"title": "T", "body": "B", "date": "2026-07-14"}]'
    padding = b" " * (NEWS_MAX_BYTES - len(payload))
    _stub_stream(monkeypatch, _FakeStream(200, [payload, padding]))
    assert fetch_news("https://example.com/news.json") == [
        {"title": "T", "body": "B", "date": "2026-07-14"},
    ]


def test_fetch_news_rejects_non_standard_constants(monkeypatch):
    _stub_stream(monkeypatch, _FakeStream(
        200, [b'[{"title": "T", "body": "B", "date": "2026-07-14", "rank": NaN}]']))
    with pytest.raises(TransportError):
        fetch_news("https://example.com/news.json")


def test_fetch_news_maps_a_non_200_to_a_typed_http_error(monkeypatch):
    _stub_stream(monkeypatch, _FakeStream(404, [b"nope"]))
    with pytest.raises(TransportHTTPError) as info:
        fetch_news("https://example.com/news.json")
    assert info.value.status_code == 404


def test_only_transport_module_imports_httpx_or_websockets():
    import os
    import re

    import chessshootout

    package_root = os.path.dirname(os.path.abspath(chessshootout.__file__))
    bad_pattern = re.compile(r"^\s*(import\s+httpx|import\s+websockets|"
                                r"from\s+httpx|from\s+websockets)",
                                re.MULTILINE)
    offenders = []
    scanned = 0
    for pkg in ("frontend", "online"):
        pkg_dir = os.path.join(package_root, pkg)
        assert os.path.isdir(pkg_dir), f"expected a walkable package dir at {pkg_dir}"
        for root, _, files in os.walk(pkg_dir):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                scanned += 1
                if path.endswith(os.path.join("online", "transport.py")):
                    continue
                with open(path, encoding="utf-8") as f:
                    if bad_pattern.search(f.read()):
                        offenders.append(path)
    assert scanned > 50, f"only scanned {scanned} files, guard root is likely wrong"
    assert offenders == [], (
        f"only online/transport.py may import httpx/websockets: {offenders}"
    )
