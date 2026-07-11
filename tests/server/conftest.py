import pytest
from fastapi.testclient import TestClient

from chessshootout.server.app import PROTOCOL_VERSION, create_app
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def client(app):
    return TestClient(app)


def auth_msg(token):
    return {"version": PROTOCOL_VERSION, "type": "auth", "session_token": token}
