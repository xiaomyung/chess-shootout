import os

import pytest

from frontend import env


_ISOLATED_VARS = (
    "CHESS_SERVER_ADDR", "CHESS_NICKNAME", "CHESS_CLIENT_UUID",
    "CHESS_LAST_MODE", "CHESS_MASTER_VOLUME", "CHESS_DATA_DIR",
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
    canonical = "00000000-0000-4000-8000-000000000099"
    env.set_overrides(client_uuid=canonical)
    assert env.get_or_create_client_uuid() == canonical


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


def test_persist_preserves_comments_and_unrelated_keys():
    env._ENV_PATH.write_text(
        "# server addr comment\n"
        "CHESS_SERVER_ADDR=chess.example.com\n"
        "\n"
        "# nickname comment\n"
        "CHESS_NICKNAME=Magnus\n"
        "CHESS_LAST_MODE=online\n"
    )
    env.set_master_volume(0.42)
    contents = env._ENV_PATH.read_text()
    assert "# server addr comment" in contents
    assert "CHESS_SERVER_ADDR=chess.example.com" in contents
    assert "# nickname comment" in contents
    assert "CHESS_NICKNAME=Magnus" in contents
    assert "CHESS_LAST_MODE=online" in contents
    assert "CHESS_MASTER_VOLUME=" in contents


def test_persist_replaces_existing_key_in_place():
    env._ENV_PATH.write_text(
        "CHESS_LAST_MODE=online\n"
        "CHESS_MASTER_VOLUME=0.300\n"
        "CHESS_NICKNAME=Magnus\n"
    )
    env.set_master_volume(0.800)
    lines = env._ENV_PATH.read_text().splitlines()
    # Replaced in place, not appended at the end.
    assert any("CHESS_MASTER_VOLUME=0.800" in line for line in lines)
    # Last key is unchanged (didn't get reordered).
    assert lines[-1] == "CHESS_NICKNAME=Magnus"


def test_persist_drops_malformed_lines():
    # Stray fragment without a `KEY=` prefix (the bug we're hardening against).
    env._ENV_PATH.write_text(
        "CHESS_LAST_MODE=online\n"
        "CHESS_MASTER_VOLUME=0.5\n"
        "0.5\n"
    )
    env.set_master_volume(0.7)
    contents = env._ENV_PATH.read_text()
    # Stray fragment is gone after the first persist.
    assert "0.5\n" not in contents.replace("=0.5\n", "")
    assert contents.count("CHESS_MASTER_VOLUME=") == 1
    assert "CHESS_MASTER_VOLUME=0.700" in contents


def test_persist_writes_unquoted_values():
    env.set_master_volume(0.65)
    contents = env._ENV_PATH.read_text()
    # No spurious quotes around the value.
    assert "CHESS_MASTER_VOLUME=0.650" in contents
    assert "CHESS_MASTER_VOLUME='0.650'" not in contents


def test_persist_appends_new_key_when_absent():
    env._ENV_PATH.write_text("# only a comment\nCHESS_LAST_MODE=online\n")
    env.set_master_volume(0.5)
    contents = env._ENV_PATH.read_text()
    assert "# only a comment" in contents
    assert "CHESS_LAST_MODE=online" in contents
    assert "CHESS_MASTER_VOLUME=0.500" in contents


def test_set_overrides_passes_uuid4_through_unchanged():
    canonical = "00000000-0000-4000-8000-000000000001"
    env.set_overrides(client_uuid=canonical)
    assert env._uuid_override == canonical


def test_set_overrides_coerces_short_alias_to_uuid4():
    # The CLI shortcut `--client-uuid alice` used to produce a 422 against
    # the new server-side UUID4 validator. Coerce short aliases into a
    # deterministic UUID4 so the debug shortcut still works.
    env.set_overrides(client_uuid="alice")
    from server.protocol import is_uuid4
    assert is_uuid4(env._uuid_override)


def test_set_overrides_coercion_is_deterministic_per_alias():
    env.set_overrides(client_uuid="alice")
    a1 = env._uuid_override
    env.set_overrides(client_uuid="alice")
    a2 = env._uuid_override
    assert a1 == a2
    env.set_overrides(client_uuid="bob")
    assert env._uuid_override != a1


def test_get_data_dir_override_empty_when_unset():
    assert env.get_data_dir_override() == ""


def test_set_data_dir_persists_and_reads():
    env.set_data_dir("/tmp/mygames")
    assert env.get_data_dir_override() == "/tmp/mygames"
    assert "CHESS_DATA_DIR=/tmp/mygames" in env._ENV_PATH.read_text()


def test_set_data_dir_none_clears_override():
    env.set_data_dir("/tmp/mygames")
    env.set_data_dir(None)
    assert env.get_data_dir_override() == ""
    contents = env._ENV_PATH.read_text() if env._ENV_PATH.exists() else ""
    assert "CHESS_DATA_DIR" not in contents


def test_set_data_dir_creates_missing_config_parent(tmp_path, monkeypatch):
    nested = tmp_path / "newconfig" / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", nested)
    env.set_data_dir("/tmp/x")
    assert nested.exists()


def test_init_paths_points_env_at_config_dir(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, "get_config_dir", lambda: tmp_path)
    env.init_paths()
    assert env._ENV_PATH == tmp_path / ".env"
