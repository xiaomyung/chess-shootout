"""M18a: protocol-boundary validation + per-uuid /reclaim limit + /healthz.

Pydantic now rejects non-UUID4 client_uuid / room_id at the route boundary,
the WS endpoint short-circuits when the path param doesn't look like a
UUID4, /reclaim is throttled to 5/min per uuid in addition to slowapi's
30/min/IP cap, and /healthz returns the new (queue_depth, uptime_s,
version) fields.
"""
import json

import pytest
from fastapi.testclient import TestClient

from server.app import (
    PROTOCOL_VERSION, RECLAIM_PER_UUID_LIMIT_PER_MINUTE, UuidRateLimiter,
    create_app,
)
from server.protocol import (
    CancelMatchmakeRequest, MatchmakeRequest, ReclaimRequest, ResumeRequest,
    is_uuid4,
)
from tests.helpers import FakeClock, fake_uuid4

import pydantic


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)
ROOM = fake_uuid4(100)


# ---- is_uuid4 helper --------------------------------------------------------

def test_is_uuid4_accepts_canonical_v4_strings():
    # Generated UUIDs from python's uuid module satisfy the regex.
    import uuid
    for _ in range(8):
        assert is_uuid4(str(uuid.uuid4()))


def test_is_uuid4_rejects_short_or_malformed_strings():
    bad = ["", "alice", "aaaa", "not-a-uuid",
           "00000000-0000-0000-0000-000000000000",  # version nibble != 4
           "00000000-0000-4000-0000-000000000000",  # variant nibble not in 8/9/a/b
           None, 42, ["uuid"]]
    for b in bad:
        assert not is_uuid4(b), f"unexpectedly accepted {b!r}"


# ---- Pydantic UUID4 validation on each request model ------------------------

def test_matchmake_request_rejects_non_uuid4_client_uuid():
    with pytest.raises(pydantic.ValidationError):
        MatchmakeRequest(nickname="Alice", client_uuid="alice",
                         time_minutes=5, increment_seconds=0)


def test_reclaim_request_rejects_non_uuid4_client_uuid():
    with pytest.raises(pydantic.ValidationError):
        ReclaimRequest(client_uuid="alice")


def test_resume_request_rejects_non_uuid4_room_id():
    with pytest.raises(pydantic.ValidationError):
        ResumeRequest(room_id="my-room", session_token="t")


def test_cancel_matchmake_request_rejects_non_uuid4_room_id():
    with pytest.raises(pydantic.ValidationError):
        CancelMatchmakeRequest(room_id="my-room", session_token="t")


def test_resume_request_accepts_valid_uuid4_room_id():
    req = ResumeRequest(room_id=ROOM, session_token="t")
    assert req.room_id == ROOM


# ---- Route-level rejection (HTTP 422) ---------------------------------------

@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(clock):
    return TestClient(create_app(now_provider=clock, max_rooms=8))


def test_matchmake_returns_422_when_client_uuid_is_garbage(client):
    r = client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": "alice",
        "nickname": "Alice", "time_minutes": 5, "increment_seconds": 0,
    })
    assert r.status_code == 422


def test_resume_returns_422_when_room_id_is_garbage(client):
    r = client.post("/resume", json={
        "version": PROTOCOL_VERSION,
        "room_id": "not-a-uuid", "session_token": "x",
    })
    assert r.status_code == 422


def test_reclaim_returns_422_when_client_uuid_is_garbage(client):
    r = client.post("/reclaim", json={
        "version": PROTOCOL_VERSION, "client_uuid": "u1",
    })
    assert r.status_code == 422


def test_cancel_matchmake_returns_422_when_room_id_is_garbage(client):
    r = client.request("DELETE", "/matchmake", json={
        "version": PROTOCOL_VERSION,
        "room_id": "blah", "session_token": "t",
    })
    assert r.status_code == 422


def test_ws_rejects_garbage_room_id_in_path(client):
    # The WS endpoint validates the path param up-front and closes before
    # accepting any frame. The client must not get a successful auth.
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/not-a-uuid") as ws:
            ws.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                      "type": "auth", "session_token": "t"}))
            ws.receive_text()


# ---- Per-uuid /reclaim rate limit ------------------------------------------

def test_reclaim_per_uuid_rate_limited_after_burst(client):
    # The 5th call still goes through (NOT_IN_ROOM since the uuid isn't in a
    # room), but the 6th is short-circuited with 429 rate_limited regardless
    # of room state.
    for _ in range(RECLAIM_PER_UUID_LIMIT_PER_MINUTE):
        r = client.post("/reclaim", json={
            "version": PROTOCOL_VERSION, "client_uuid": ALICE,
        })
        assert r.status_code == 404, r.text
    r = client.post("/reclaim", json={
        "version": PROTOCOL_VERSION, "client_uuid": ALICE,
    })
    assert r.status_code == 429
    body = r.json()
    # Detail-wrapping mirrors the convention used by the rest of the
    # HTTPException sites in app.py.
    assert body.get("detail", {}).get("reason") == "rate_limited"


def test_reclaim_limit_is_per_uuid_independent(client):
    # Burst on Alice — Bob's first call still goes through.
    for _ in range(RECLAIM_PER_UUID_LIMIT_PER_MINUTE):
        client.post("/reclaim", json={
            "version": PROTOCOL_VERSION, "client_uuid": ALICE,
        })
    r = client.post("/reclaim", json={
        "version": PROTOCOL_VERSION, "client_uuid": BOB,
    })
    # Bob hits NOT_IN_ROOM (404), not rate_limited (429).
    assert r.status_code == 404


def test_reclaim_window_slides_releases_capacity(clock):
    # UuidRateLimiter is a sliding 60s window. Drive it directly with the fake
    # clock to verify the release behaviour without relying on real time.
    limiter = UuidRateLimiter(limit_per_minute=5, window_seconds=60.0,
                                now_provider=clock)
    for _ in range(5):
        assert limiter.hit("u")
    assert not limiter.hit("u")
    clock.advance(61)
    assert limiter.hit("u")


# ---- Expanded /healthz ------------------------------------------------------

def test_healthz_includes_version_field(client):
    body = client.get("/healthz").json()
    assert body["version"] == PROTOCOL_VERSION


def test_healthz_includes_queue_depth_and_uptime(clock, client):
    body = client.get("/healthz").json()
    assert body["queue_depth"] == 0
    # Initial uptime tied to the fake clock — both are zero at TestClient init.
    assert body["uptime_s"] == pytest.approx(0.0, abs=1e-6)
    clock.advance(7.5)
    body = client.get("/healthz").json()
    assert body["uptime_s"] == pytest.approx(7.5, abs=1e-3)


def test_healthz_queue_depth_reflects_pending_room(clock, client):
    # One unpaired matchmake request → queue_depth bumps to 1 until a peer
    # arrives.
    r = client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": ALICE,
        "nickname": "Alice", "time_minutes": 5, "increment_seconds": 0,
    })
    assert r.status_code == 200
    body = client.get("/healthz").json()
    assert body["queue_depth"] == 1
    assert body["rooms_active"] == 0
    # When Bob pairs in, the queue empties and rooms_active goes up.
    client.post("/matchmake", json={
        "version": PROTOCOL_VERSION, "client_uuid": BOB,
        "nickname": "Bob", "time_minutes": 5, "increment_seconds": 0,
    })
    body = client.get("/healthz").json()
    assert body["queue_depth"] == 0
    assert body["rooms_active"] == 1
