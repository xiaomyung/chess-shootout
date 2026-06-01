import os
import uuid

import pytest

from frontend import env


_ISOLATED_VARS = (
    "CHESS_SERVER_ADDR", "CHESS_NICKNAME", "CHESS_CLIENT_UUID",
    "CHESS_LAST_MODE", "CHESS_MASTER_VOLUME", "CHESS_DATA_DIR",
    "CHESS_REDUCE_MOTION", "CHESS_EFFECT_INTENSITY", "CHESS_DEFAULT_TC",
    "CHESS_DEFAULT_INCREMENT", "CHESS_THEME",
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


@pytest.mark.parametrize(
    "getter, default",
    [
        pytest.param("get_server_addr", "localhost:8000", id="server_addr_defaults_localhost"),
        pytest.param("get_nickname", "", id="nickname_defaults_empty"),
        pytest.param("get_last_mode", "", id="last_mode_defaults_empty"),
        pytest.param("get_data_dir_override", "", id="data_dir_override_defaults_empty"),
    ],
)
def test_getter_returns_default_when_unset(getter, default):
    assert getattr(env, getter)() == default


@pytest.mark.parametrize(
    "var, getter, value",
    [
        pytest.param(
            "CHESS_SERVER_ADDR", "get_server_addr", "chess.example.com",
            id="server_addr_reads_env",
        ),
        pytest.param("CHESS_NICKNAME", "get_nickname", "Magnus", id="nickname_reads_env"),
    ],
)
def test_getter_reads_environment(monkeypatch, var, getter, value):
    monkeypatch.setenv(var, value)
    assert getattr(env, getter)() == value


def test_nickname_override_wins(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "FromEnv")
    env.set_overrides(nickname="FromCLI")
    assert env.get_nickname() == "FromCLI"


def test_get_or_create_client_uuid_generates_when_unset():
    """A fresh launch mints a real uuid4 and caches it for the next call."""
    fresh = env.get_or_create_client_uuid()
    assert uuid.UUID(fresh).version == 4
    assert os.environ["CHESS_CLIENT_UUID"] == fresh
    assert env.get_or_create_client_uuid() == fresh


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


def test_load_reads_env_file_when_present(monkeypatch):
    env._ENV_PATH.write_text("CHESS_SERVER_ADDR=test.example.com\n")
    env.load()
    assert env.get_server_addr() == "test.example.com"


def test_load_no_op_when_env_file_missing():
    assert not env._ENV_PATH.exists()
    env.load()
    assert env.get_server_addr() == "localhost:8000"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(None, id="unset"),
        pytest.param("", id="blank"),
        pytest.param("not-a-float", id="garbage"),
    ],
)
def test_master_volume_falls_back_to_default(monkeypatch, raw):
    """Unset, blank, and unparseable values all return the default volume."""
    if raw is not None:
        monkeypatch.setenv("CHESS_MASTER_VOLUME", raw)
    assert env.get_master_volume() == env._DEFAULT_MASTER_VOLUME


def test_master_volume_persists_round_trip():
    env.set_master_volume(0.42)
    assert env.get_master_volume() == pytest.approx(0.42, abs=1e-3)
    contents = env._ENV_PATH.read_text()
    assert "CHESS_MASTER_VOLUME" in contents


def test_server_addr_persists_round_trip():
    env.set_server_addr("chess.example.com:9000")
    assert env.get_server_addr() == "chess.example.com:9000"
    assert "CHESS_SERVER_ADDR" in env._ENV_PATH.read_text()


def test_server_addr_strips_whitespace():
    env.set_server_addr("  localhost:8000  ")
    assert env.get_server_addr() == "localhost:8000"


@pytest.mark.parametrize("blank", ["", "   "])
def test_server_addr_blank_is_noop_keeps_default(blank):
    env.set_server_addr(blank)
    assert env.get_server_addr() == "localhost:8000"


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
    """An updated key is rewritten where it sat; trailing keys keep their order."""
    env._ENV_PATH.write_text(
        "CHESS_LAST_MODE=online\n"
        "CHESS_MASTER_VOLUME=0.300\n"
        "CHESS_NICKNAME=Magnus\n"
    )
    env.set_master_volume(0.800)
    lines = env._ENV_PATH.read_text().splitlines()
    assert any("CHESS_MASTER_VOLUME=0.800" in line for line in lines)
    assert lines[-1] == "CHESS_NICKNAME=Magnus"


def test_persist_drops_malformed_lines():
    """A stray fragment lacking a `KEY=` prefix is dropped on the first persist."""
    env._ENV_PATH.write_text(
        "CHESS_LAST_MODE=online\n"
        "CHESS_MASTER_VOLUME=0.5\n"
        "0.5\n"
    )
    env.set_master_volume(0.7)
    contents = env._ENV_PATH.read_text()
    assert "0.5\n" not in contents.replace("=0.5\n", "")
    assert contents.count("CHESS_MASTER_VOLUME=") == 1
    assert "CHESS_MASTER_VOLUME=0.700" in contents


def test_persist_writes_unquoted_values():
    env.set_master_volume(0.65)
    contents = env._ENV_PATH.read_text()
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
    """`--client-uuid alice` once 422'd the server validator; coerce to a uuid4."""
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


# ---- settings keys (reduce-motion, intensity, default TC, theme) -----------

def test_reduce_motion_defaults_false_and_round_trips():
    assert env.get_reduce_motion() is False
    env.set_reduce_motion(True)
    assert env.get_reduce_motion() is True
    assert "CHESS_REDUCE_MOTION=1" in env._ENV_PATH.read_text()
    env.set_reduce_motion(False)
    assert env.get_reduce_motion() is False


def test_effect_intensity_defaults_full_and_validates():
    assert env.get_effect_intensity() == "full"
    env.set_effect_intensity("subtle")
    assert env.get_effect_intensity() == "subtle"
    env.set_effect_intensity("bogus")
    assert env.get_effect_intensity() == "full"


def test_default_time_control_round_trips():
    assert env.get_default_time_control() == "10"
    env.set_default_time_control("3")
    assert env.get_default_time_control() == "3"
    assert "CHESS_DEFAULT_TC=3" in env._ENV_PATH.read_text()


def test_default_increment_round_trips():
    assert env.get_default_increment() == "5"
    env.set_default_increment("2")
    assert env.get_default_increment() == "2"
    assert "CHESS_DEFAULT_INCREMENT=2" in env._ENV_PATH.read_text()


def test_default_time_control_rejects_unknown_value():
    env.set_default_time_control("999")
    assert env.get_default_time_control() == "10"


def test_default_increment_rejects_unknown_value():
    env.set_default_increment("7")
    assert env.get_default_increment() == "5"


def test_default_time_minutes_parses_value_and_infinity():
    env.set_default_time_control("15")
    assert env.default_time_minutes() == 15
    env.set_default_time_control("∞")
    assert env.default_time_minutes() is None


def test_default_increment_seconds_parses_value():
    env.set_default_increment("10")
    assert env.default_increment_seconds() == 10


def test_theme_defaults_dark_and_rejects_unknown():
    assert env.get_theme() == "dark"
    env.set_theme("wood")            # not a known theme yet
    assert env.get_theme() == "dark"
    env.set_theme("dark")
    assert env.get_theme() == "dark"
