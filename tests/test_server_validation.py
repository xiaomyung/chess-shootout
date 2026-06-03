"""M18a protocol-boundary validation: UUID4 rejection (model + route layers),
the per-uuid /reclaim sliding-window limit, and the expanded /healthz fields.

Two distinct layers are exercised on purpose: the Pydantic models reject
non-UUID4 ids with a ValidationError, and the FastAPI routes map that into an
HTTP 422 — keep both, they verify different seams.
"""
import json

import pydantic
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chessshootout.server.app import (
    PROTOCOL_VERSION, RECLAIM_PER_UUID_LIMIT_PER_MINUTE, UuidRateLimiter,
    WS_CLOSE_INVALID_TOKEN, create_app,
)
from chessshootout.server.protocol import (
    CancelMatchmakeRequest, MatchmakeRequest, Reason, ReclaimRequest,
    ResumeRequest, is_uuid4,
)
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)
ROOM = fake_uuid4(100)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("00000000-0000-4000-8000-000000000000", id="variant_8"),
        pytest.param("12345678-1234-4234-9234-123456789abc", id="variant_9"),
        pytest.param("f47ac10b-58cc-4372-a567-0e02b2c3d479", id="variant_a"),
        pytest.param("abcdef01-2345-4678-bcde-f01234567890", id="variant_b"),
        pytest.param(ALICE, id="fake_uuid4_seed_1"),
        pytest.param(ROOM, id="fake_uuid4_seed_100"),
    ],
)
def test_is_uuid4_accepts_canonical_v4_strings(value):
    assert is_uuid4(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("alice", id="alpha_word"),
        pytest.param("aaaa", id="too_short"),
        pytest.param("not-a-uuid", id="hyphenated_word"),
        pytest.param("00000000-0000-0000-0000-000000000000", id="version_nibble_not_4"),
        pytest.param("00000000-0000-4000-0000-000000000000", id="variant_nibble_not_8_9_a_b"),
        pytest.param(None, id="none"),
        pytest.param(42, id="int"),
        pytest.param(["uuid"], id="list"),
    ],
)
def test_is_uuid4_rejects_short_or_malformed_values(value):
    assert not is_uuid4(value)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda: MatchmakeRequest(nickname="Alice", client_uuid="alice",
                                     time_minutes=5, increment_seconds=0),
            id="matchmake_client_uuid",
        ),
        pytest.param(lambda: ReclaimRequest(client_uuid="alice"), id="reclaim_client_uuid"),
        pytest.param(
            lambda: ResumeRequest(room_id="my-room", session_token="t"),
            id="resume_room_id",
        ),
        pytest.param(
            lambda: CancelMatchmakeRequest(room_id="my-room", session_token="t"),
            id="cancel_matchmake_room_id",
        ),
    ],
)
def test_request_model_rejects_non_uuid4(build):
    with pytest.raises(pydantic.ValidationError):
        build()


def test_resume_request_accepts_valid_uuid4_room_id():
    req = ResumeRequest(room_id=ROOM, session_token="t")
    assert req.room_id == ROOM


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(clock):
    return TestClient(create_app(now_provider=clock, max_rooms=8))


@pytest.mark.parametrize(
    "method, route, payload, expected_status",
    [
        pytest.param(
            "POST", "/matchmake",
            {"version": PROTOCOL_VERSION, "client_uuid": "alice",
             "nickname": "Alice", "time_minutes": 5, "increment_seconds": 0},
            422, id="matchmake_garbage_client_uuid",
        ),
        pytest.param(
            "POST", "/resume",
            {"version": PROTOCOL_VERSION, "room_id": "not-a-uuid", "session_token": "x"},
            422, id="resume_garbage_room_id",
        ),
        pytest.param(
            "POST", "/reclaim",
            {"version": PROTOCOL_VERSION, "client_uuid": "u1"},
            422, id="reclaim_garbage_client_uuid",
        ),
        pytest.param(
            "DELETE", "/matchmake",
            {"version": PROTOCOL_VERSION, "room_id": "blah", "session_token": "t"},
            422, id="cancel_matchmake_garbage_room_id",
        ),
    ],
)
def test_route_rejects_non_uuid4_payload(client, method, route, payload, expected_status):
    r = client.request(method, route, json=payload)
    assert r.status_code == expected_status


def test_ws_closes_with_invalid_token_on_garbage_room_id_path(client):
    """The WS endpoint validates the path param up-front and closes (code 4000)
    before accepting any frame, so the client never gets a successful auth."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/not-a-uuid") as ws:
            ws.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                     "type": "auth", "session_token": "t"}))
            ws.receive_text()
    assert excinfo.value.code == WS_CLOSE_INVALID_TOKEN


def test_reclaim_per_uuid_rate_limited_after_burst(client):
    """The 5th call still resolves (404 NOT_IN_ROOM since the uuid isn't in a
    room); the 6th is short-circuited with 429 rate_limited regardless of room
    state."""
    for _ in range(RECLAIM_PER_UUID_LIMIT_PER_MINUTE):
        r = client.post("/reclaim", json={
            "version": PROTOCOL_VERSION, "client_uuid": ALICE,
        })
        assert r.status_code == 404, r.text
    r = client.post("/reclaim", json={
        "version": PROTOCOL_VERSION, "client_uuid": ALICE,
    })
    assert r.status_code == 429
    assert r.json().get("detail", {}).get("reason") == Reason.RATE_LIMITED


def test_reclaim_limit_is_per_uuid_independent(client):
    """Bursting Alice past the cap leaves Bob's first call unthrottled."""
    for _ in range(RECLAIM_PER_UUID_LIMIT_PER_MINUTE):
        client.post("/reclaim", json={
            "version": PROTOCOL_VERSION, "client_uuid": ALICE,
        })
    r = client.post("/reclaim", json={
        "version": PROTOCOL_VERSION, "client_uuid": BOB,
    })
    assert r.status_code == 404


def test_reclaim_window_slides_releases_capacity(clock):
    """UuidRateLimiter is a sliding 60s window — driven directly with the fake
    clock to verify capacity is released without relying on real time."""
    limiter = UuidRateLimiter(limit_per_minute=5, window_seconds=60.0,
                              now_provider=clock)
    for _ in range(5):
        assert limiter.hit("u")
    assert not limiter.hit("u")
    clock.advance(61)
    assert limiter.hit("u")


def test_uuid_rate_limiter_prunes_stale_buckets(clock):
    """Distinct uuids leave per-key buckets; once their hits age out, pruning
    evicts the empty buckets so a flood of one-off uuids can't grow memory
    unboundedly."""
    limiter = UuidRateLimiter(limit_per_minute=5, window_seconds=60.0,
                              now_provider=clock)
    for i in range(50):
        limiter.hit(f"uuid-{i}")
    assert len(limiter._calls) == 50
    clock.advance(61)
    limiter._prune(clock() - limiter.window)
    assert len(limiter._calls) == 0


def test_healthz_includes_version_field(client):
    body = client.get("/healthz").json()
    assert body["version"] == PROTOCOL_VERSION


def test_healthz_includes_queue_depth_and_uptime(clock, client):
    body = client.get("/healthz").json()
    assert body["queue_depth"] == 0
    assert body["uptime_s"] == pytest.approx(0.0, abs=1e-6)
    clock.advance(7.5)
    body = client.get("/healthz").json()
    assert body["uptime_s"] == pytest.approx(7.5, abs=1e-3)


def test_healthz_queue_depth_reflects_pending_room(client):
    """One unpaired matchmake bumps queue_depth to 1; the peer pairs it into a
    room, draining the queue and incrementing rooms_active."""
    r = client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": ALICE,
        "nickname": "Alice", "time_minutes": 5, "increment_seconds": 0,
    })
    assert r.status_code == 200
    body = client.get("/healthz").json()
    assert body["queue_depth"] == 1
    assert body["rooms_active"] == 0
    client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": BOB,
        "nickname": "Bob", "time_minutes": 5, "increment_seconds": 0,
    })
    body = client.get("/healthz").json()
    assert body["queue_depth"] == 0
    assert body["rooms_active"] == 1
