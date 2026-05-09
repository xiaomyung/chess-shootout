import os

import pytest

from frontend import env


_ISOLATED_VARS = (
    "CHESS_SERVER_ADDR", "CHESS_NICKNAME", "CHESS_CLIENT_UUID",
    "CHESS_LAST_MODE", "CHESS_MASTER_VOLUME",
)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Each test gets its own .env file and a clean os.environ + module state.

    set_* helpers in env.py write directly to os.environ as a side-effect of
    persisting to the .env file. Monkeypatch only tracks its own mutations, so
    we delenv on both sides of yield to keep state from leaking between tests.
    """
    fake_env = tmp_path / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", fake_env)
    for var in _ISOLATED_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(env, "_uuid_override", None)
    monkeypatch.setattr(env, "_nickname_override", None)
    yield
    for var in _ISOLATED_VARS:
        os.environ.pop(var, None)


def test_get_server_addr_returns_default_when_unset():
    assert env.get_server_addr() == "localhost:8000"


def test_get_server_addr_reads_environment(monkeypatch):
    monkeypatch.setenv("CHESS_SERVER_ADDR", "chess.example.com")
    assert env.get_server_addr() == "chess.example.com"


def test_get_nickname_returns_empty_when_unset():
    assert env.get_nickname() == ""


def test_get_nickname_reads_environment(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "Magnus")
    assert env.get_nickname() == "Magnus"


def test_nickname_override_wins(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "FromEnv")
    env.set_overrides(nickname="FromCLI")
    assert env.get_nickname() == "FromCLI"


def test_get_or_create_client_uuid_generates_when_unset():
    fresh = env.get_or_create_client_uuid()
    assert len(fresh) == 36  # uuid4 string length


def test_get_or_create_client_uuid_persists_to_env_file():
    first = env.get_or_create_client_uuid()
    contents = env._ENV_PATH.read_text()
    assert "CHESS_CLIENT_UUID" in contents
    assert first in contents


def test_get_or_create_client_uuid_returns_existing(monkeypatch):
    monkeypatch.setenv("CHESS_CLIENT_UUID", "fixed-uuid")
    assert env.get_or_create_client_uuid() == "fixed-uuid"


def test_get_or_create_client_uuid_honors_override():
    env.set_overrides(client_uuid="cli-override")
    assert env.get_or_create_client_uuid() == "cli-override"


def test_set_last_mode_persists_to_env_file():
    env.set_last_mode("online")
    assert env.get_last_mode() == "online"
    contents = env._ENV_PATH.read_text()
    assert "CHESS_LAST_MODE" in contents
    assert "online" in contents


def test_get_last_mode_returns_empty_when_unset():
    assert env.get_last_mode() == ""


def test_load_reads_env_file_when_present(monkeypatch):
    env._ENV_PATH.write_text("CHESS_SERVER_ADDR=test.example.com\n")
    env.load()
    assert env.get_server_addr() == "test.example.com"


def test_load_no_op_when_env_file_missing():
    assert not env._ENV_PATH.exists()
    env.load()  # must not raise
    assert env.get_server_addr() == "localhost:8000"


def test_master_volume_default_when_unset():
    assert env.get_master_volume() == env._DEFAULT_MASTER_VOLUME


def test_master_volume_default_when_blank(monkeypatch):
    monkeypatch.setenv("CHESS_MASTER_VOLUME", "")
    assert env.get_master_volume() == env._DEFAULT_MASTER_VOLUME


def test_master_volume_default_when_garbage(monkeypatch):
    monkeypatch.setenv("CHESS_MASTER_VOLUME", "not-a-float")
    assert env.get_master_volume() == env._DEFAULT_MASTER_VOLUME


def test_master_volume_persists_round_trip():
    env.set_master_volume(0.42)
    assert env.get_master_volume() == pytest.approx(0.42, abs=1e-3)
    contents = env._ENV_PATH.read_text()
    assert "CHESS_MASTER_VOLUME" in contents


@pytest.mark.parametrize(
    "raw_value,expected",
    [(-0.5, 0.0), (1.5, 1.0), (0.0, 0.0), (1.0, 1.0)],
)
def test_master_volume_clamped_to_unit_range(raw_value, expected):
    env.set_master_volume(raw_value)
    assert env.get_master_volume() == pytest.approx(expected, abs=1e-3)
