from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chessshootout.server.app import PROTOCOL_VERSION, create_app
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


@pytest.fixture
def clock() -> FakeClock:
    """
    Give each server test its own monotonic clock stand-in, so grace periods,
    skill-check deadlines and idle windows are stepped instantly instead of
    waited out

    :returns: a fresh clock sitting at zero seconds
    """
    return FakeClock()


@pytest.fixture
def app(clock: FakeClock) -> FastAPI:
    """
    Build a server application wired to the test clock, with a small room cap so
    the server-full path is reachable without creating a hundred rooms

    :param clock: fake monotonic clock the app reads every timestamp from
    :returns: the application under test
    """
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """
    Drive the app in-process, which exercises the real HTTP endpoints and the
    real websocket route without binding a port or starting a server

    :param app: the application under test
    :returns: a test client bound to that application
    """
    return TestClient(app)


def auth_msg(token: str) -> dict[str, Any]:
    """
    Build the handshake frame a client must send first on a game websocket: the
    protocol version the server insists on, plus the session token naming the
    slot being claimed. No game traffic is accepted before it

    :param token: session token handed out by matchmake, resume or reclaim
    :returns: the auth frame, ready to send as JSON
    """
    return {"version": PROTOCOL_VERSION, "type": "auth", "session_token": token}
