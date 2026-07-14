import logging
import os
import re
import uuid
from pathlib import Path

import pytest

from chessshootout.infra import env


_ISOLATED_VARS = (
    "CHESS_SERVER_ADDR", "CHESS_NICKNAME", "CHESS_CLIENT_UUID",
    "CHESS_LAST_MODE", "CHESS_MASTER_VOLUME", "CHESS_MENU_VOLUME", "CHESS_DATA_DIR",
    "CHESS_DEFAULT_TC",
    "CHESS_DEFAULT_INCREMENT", "CHESS_THEME", "CHESS_COUNTRY",
    "CHESS_SHOW_FPS", "CHESS_SHOW_PING", "CHESS_FOCUS_SHOW",
    "CHESS_NEWS_URL", "CHESS_PROFILE_HINT_SHOWN", "CHESS_LAUNCH_MODE",
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


@pytest.mark.parametrize("raw, expected", [
    pytest.param("Magnus", "Magnus", id="ascii_unchanged"),
    pytest.param("Щёлк", "", id="all_cyrillic_dropped"),
    pytest.param("Bob Щ", "Bob", id="mixed_keeps_ascii"),
    pytest.param("a  b", "a b", id="whitespace_collapsed"),
    pytest.param("emoji 😀 end", "emoji end", id="emoji_dropped"),
    pytest.param("x" * 30, "x" * 20, id="capped_at_max"),
    pytest.param("x" * 19 + " york", "x" * 19, id="truncation_leaves_no_trailing_space"),
    pytest.param("John #1", "John 1", id="hash_dropped"),
    pytest.param("#leading", "leading", id="leading_hash_dropped"),
    pytest.param("trailing#", "trailing", id="trailing_hash_dropped"),
])
def test_sanitize_nickname(raw, expected):
    assert env.sanitize_nickname(raw) == expected


def test_sanitize_nickname_none_is_empty():
    assert env.sanitize_nickname(None) == ""


def test_nickname_max_len_matches_server():
    """Client cap must equal the server's, or a locally-typed 20-char name could be
    rejected online. Drift guard for the mirrored constant."""
    from chessshootout.server import protocol
    assert env._NICKNAME_MAX_LEN == protocol.MAX_NICKNAME_LEN


@pytest.mark.parametrize("raw", ["Magnus", "Bob Щ", "a  b", "José 123", "x" * 40,
                                 "x" * 19 + " york"])
def test_sanitized_nickname_is_accepted_by_server(raw):
    """Whatever the client keeps must pass the server's normalize_nickname unchanged,
    so a name typed locally never bounces at matchmake."""
    from chessshootout.server import protocol
    clean = env.sanitize_nickname(raw)
    if clean:
        assert protocol.normalize_nickname(clean) == clean


def test_set_nickname_strips_nonascii_before_persist():
    env.set_nickname("Bob Щ")
    assert env.get_nickname() == "Bob"
    assert "CHESS_NICKNAME=Bob" in env._ENV_PATH.read_text(encoding="utf-8")


def test_set_nickname_all_nonascii_is_noop():
    env.set_nickname("Щёлк")
    assert env.get_nickname() == ""
    assert not env._ENV_PATH.exists()


def test_nickname_with_hash_round_trips_through_real_dotenv_loader(monkeypatch):
    """An unquoted value containing ' #' truncates at the '#' under python-dotenv
    (it reads as an inline comment) -- sanitize_nickname strips '#' so nothing
    persisted can ever hit that truncation. Reload through the real loader, not
    just os.environ, to prove the file on disk round-trips correctly."""
    env.set_nickname("John #1")
    persisted = env.get_nickname()
    assert persisted == "John 1"
    monkeypatch.delenv("CHESS_NICKNAME", raising=False)
    env.load()
    assert env.get_nickname() == persisted


def test_get_nickname_sanitizes_legacy_env_value(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "Ana Щ")
    assert env.get_nickname() == "Ana"


def test_set_overrides_sanitizes_nickname():
    env.set_overrides(nickname="Игорь Bob")
    assert env.get_nickname() == "Bob"


def test_normalize_stored_nickname_rewrites_dirty(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "Bob Щ")
    assert env.normalize_stored_nickname() is True
    assert os.environ["CHESS_NICKNAME"] == "Bob"
    assert "CHESS_NICKNAME=Bob" in env._ENV_PATH.read_text(encoding="utf-8")


def test_normalize_stored_nickname_clean_is_noop(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "Bob")
    assert env.normalize_stored_nickname() is False
    assert not env._ENV_PATH.exists()


def test_normalize_stored_nickname_all_nonascii_clears(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "Щёлк")
    assert env.normalize_stored_nickname() is True
    assert os.environ["CHESS_NICKNAME"] == ""


def test_normalize_stored_nickname_idempotent(monkeypatch):
    monkeypatch.setenv("CHESS_NICKNAME", "Ann Щ")
    assert env.normalize_stored_nickname() is True
    assert env.normalize_stored_nickname() is False


def test_get_or_create_client_uuid_generates_when_unset():
    """A fresh launch mints a real uuid4 and caches it for the next call."""
    fresh = env.get_or_create_client_uuid()
    assert uuid.UUID(fresh).version == 4
    assert os.environ["CHESS_CLIENT_UUID"] == fresh
    assert env.get_or_create_client_uuid() == fresh


def test_get_or_create_client_uuid_persists_to_env_file():
    first = env.get_or_create_client_uuid()
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "CHESS_CLIENT_UUID" in contents
    assert first in contents


def test_get_or_create_client_uuid_returns_existing(monkeypatch):
    valid = "00000000-0000-4000-8000-000000000042"
    monkeypatch.setenv("CHESS_CLIENT_UUID", valid)
    assert env.get_or_create_client_uuid() == valid


def test_get_or_create_client_uuid_honors_override():
    canonical = "00000000-0000-4000-8000-000000000099"
    env.set_overrides(client_uuid=canonical)
    assert env.get_or_create_client_uuid() == canonical


def test_get_or_create_client_uuid_coerces_hand_edited_non_uuid4(monkeypatch):
    """A stored CHESS_CLIENT_UUID that isn't a valid uuid4 (hand-edited .env,
    or a leftover debug alias) must be coerced the same way the CLI
    --client-uuid path already is, or the client 422s the server validator."""
    monkeypatch.setenv("CHESS_CLIENT_UUID", "not-a-uuid4")
    from chessshootout.server.protocol import is_uuid4
    coerced = env.get_or_create_client_uuid()
    assert is_uuid4(coerced)
    assert coerced != "not-a-uuid4"
    assert os.environ["CHESS_CLIENT_UUID"] == coerced
    assert coerced in env._ENV_PATH.read_text(encoding="utf-8")


def test_get_or_create_client_uuid_coercion_is_stable_and_persists_once(monkeypatch, caplog):
    monkeypatch.setenv("CHESS_CLIENT_UUID", "not-a-uuid4")
    with caplog.at_level(logging.INFO, logger="chess.env"):
        first = env.get_or_create_client_uuid()
        second = env.get_or_create_client_uuid()
    assert first == second
    persisted_lines = [r.getMessage() for r in caplog.records
                        if "setting persisted key=CHESS_CLIENT_UUID" in r.getMessage()]
    assert len(persisted_lines) == 1


def test_get_or_create_client_uuid_valid_uuid4_is_not_repersisted(monkeypatch, caplog):
    valid = "00000000-0000-4000-8000-000000000042"
    monkeypatch.setenv("CHESS_CLIENT_UUID", valid)
    with caplog.at_level(logging.INFO, logger="chess.env"):
        result = env.get_or_create_client_uuid()
    assert result == valid
    assert not any("setting persisted" in r.getMessage() for r in caplog.records)


def test_set_last_mode_persists_to_env_file():
    env.set_last_mode("online")
    assert env.get_last_mode() == "online"
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "CHESS_LAST_MODE" in contents
    assert "online" in contents


def test_load_reads_env_file_when_present(monkeypatch):
    env._ENV_PATH.write_text("CHESS_SERVER_ADDR=test.example.com\n", encoding="utf-8")
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
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "CHESS_MASTER_VOLUME" in contents


def test_menu_volume_defaults_to_ten_percent(monkeypatch):
    monkeypatch.delenv("CHESS_MENU_VOLUME", raising=False)
    assert env.get_menu_volume() == env._DEFAULT_MENU_VOLUME == pytest.approx(0.10)


@pytest.mark.parametrize("raw", [None, "", "not-a-float"])
def test_menu_volume_falls_back_to_default(monkeypatch, raw):
    if raw is not None:
        monkeypatch.setenv("CHESS_MENU_VOLUME", raw)
    assert env.get_menu_volume() == env._DEFAULT_MENU_VOLUME


def test_menu_volume_persists_round_trip_and_clamps():
    env.set_menu_volume(0.35)
    assert env.get_menu_volume() == pytest.approx(0.35, abs=1e-3)
    assert "CHESS_MENU_VOLUME" in env._ENV_PATH.read_text(encoding="utf-8")
    env.set_menu_volume(1.8)
    assert env.get_menu_volume() == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("getter", ["get_show_fps", "get_show_ping"])
def test_show_stats_default_on_when_unset(getter):
    assert getattr(env, getter)() is True


@pytest.mark.parametrize(
    "getter, setter, key",
    [
        ("get_show_fps", "set_show_fps", "CHESS_SHOW_FPS"),
        ("get_show_ping", "set_show_ping", "CHESS_SHOW_PING"),
    ],
)
def test_show_stats_round_trip(getter, setter, key):
    getattr(env, setter)(False)
    assert getattr(env, getter)() is False
    assert f"{key}=0" in env._ENV_PATH.read_text(encoding="utf-8")
    getattr(env, setter)(True)
    assert getattr(env, getter)() is True
    assert f"{key}=1" in env._ENV_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("getter, key", [
    ("get_show_fps", "CHESS_SHOW_FPS"),
    ("get_show_ping", "CHESS_SHOW_PING"),
])
def test_show_stats_zero_reads_false_not_truthy(monkeypatch, getter, key):
    monkeypatch.setenv(key, "0")
    assert getattr(env, getter)() is False


def test_server_addr_persists_round_trip():
    env.set_server_addr("chess.example.com:9000")
    assert env.get_server_addr() == "chess.example.com:9000"
    assert "CHESS_SERVER_ADDR" in env._ENV_PATH.read_text(encoding="utf-8")


def test_server_addr_strips_whitespace():
    env.set_server_addr("  localhost:8000  ")
    assert env.get_server_addr() == "localhost:8000"


@pytest.mark.parametrize("blank", ["", "   "])
def test_server_addr_blank_is_noop_keeps_default(blank):
    env.set_server_addr(blank)
    assert env.get_server_addr() == "localhost:8000"


def test_server_addr_defaults_to_prod_when_frozen(monkeypatch):
    monkeypatch.setattr("chessshootout.paths.is_frozen", lambda: True)
    assert env.get_server_addr() == env._PROD_SERVER_ADDR == "server.chess-shootout.com"


def test_server_addr_defaults_to_localhost_from_source(monkeypatch):
    monkeypatch.setattr("chessshootout.paths.is_frozen", lambda: False)
    assert env.get_server_addr() == "localhost:8000"


def test_explicit_server_addr_overrides_frozen_default(monkeypatch):
    monkeypatch.setattr("chessshootout.paths.is_frozen", lambda: True)
    monkeypatch.setenv("CHESS_SERVER_ADDR", "192.168.1.5:8000")
    assert env.get_server_addr() == "192.168.1.5:8000"


def test_set_nickname_persists_round_trip():
    env.set_nickname("Magnus")
    assert env.get_nickname() == "Magnus"
    assert os.environ["CHESS_NICKNAME"] == "Magnus"
    assert "CHESS_NICKNAME=Magnus" in env._ENV_PATH.read_text(encoding="utf-8")


def test_set_nickname_strips_whitespace():
    env.set_nickname("  Hikaru  ")
    assert env.get_nickname() == "Hikaru"


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_set_nickname_blank_is_noop(blank):
    env.set_nickname("Fabiano")
    env.set_nickname(blank)
    assert env.get_nickname() == "Fabiano"
    assert "CHESS_NICKNAME=Fabiano" in env._ENV_PATH.read_text(encoding="utf-8")


def test_set_nickname_replaces_existing_value_in_place():
    env.set_nickname("First")
    env.set_nickname("Second")
    assert env.get_nickname() == "Second"
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "CHESS_NICKNAME=Second" in contents
    assert "First" not in contents


def test_news_url_defaults_to_the_shipped_constant():
    assert env.get_news_url() == env._DEFAULT_NEWS_URL
    assert env.get_news_url().startswith("https://")


def test_news_url_reads_env_override(monkeypatch):
    monkeypatch.setenv("CHESS_NEWS_URL", "https://example.com/news.json")
    assert env.get_news_url() == "https://example.com/news.json"


def test_profile_hint_shown_defaults_false():
    assert env.get_profile_hint_shown() is False


def test_profile_hint_shown_persists_round_trip():
    env.set_profile_hint_shown()
    assert env.get_profile_hint_shown() is True
    assert "CHESS_PROFILE_HINT_SHOWN=1" in env._ENV_PATH.read_text(encoding="utf-8")


def test_country_defaults_empty():
    assert env.get_country() == ""


def test_country_persists_round_trip():
    env.set_country("RO")
    assert env.get_country() == "RO"
    assert "CHESS_COUNTRY" in env._ENV_PATH.read_text(encoding="utf-8")


def test_country_normalizes_case_and_whitespace():
    env.set_country("  us ")
    assert env.get_country() == "US"


def test_country_clears_on_blank_and_removes_key():
    env.set_country("FR")
    env.set_country("")
    assert env.get_country() == ""
    assert "CHESS_COUNTRY" not in os.environ
    assert "CHESS_COUNTRY" not in env._ENV_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["usa", "1", "ZZ", "longstring"])
def test_country_rejects_unknown_codes(bad):
    env.set_country(bad)
    assert env.get_country() == ""
    assert "CHESS_COUNTRY" not in os.environ


def test_country_getter_ignores_invalid_stored_value(monkeypatch):
    monkeypatch.setenv("CHESS_COUNTRY", "garbage")
    assert env.get_country() == ""


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
        "CHESS_LAST_MODE=online\n", encoding="utf-8"
    )
    env.set_master_volume(0.42)
    contents = env._ENV_PATH.read_text(encoding="utf-8")
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
        "CHESS_NICKNAME=Magnus\n", encoding="utf-8"
    )
    env.set_master_volume(0.800)
    lines = env._ENV_PATH.read_text(encoding="utf-8").splitlines()
    assert any("CHESS_MASTER_VOLUME=0.800" in line for line in lines)
    assert lines[-1] == "CHESS_NICKNAME=Magnus"


def test_persist_preserves_malformed_lines():
    """A stray fragment lacking a `KEY=` prefix survives a persist -- matching
    _persist_delete, which already preserves lines it doesn't recognize (a
    hand-edited .env may carry comments-without-#, export statements, or other
    content the app doesn't own)."""
    env._ENV_PATH.write_text(
        "CHESS_LAST_MODE=online\n"
        "CHESS_MASTER_VOLUME=0.5\n"
        "0.5\n", encoding="utf-8"
    )
    env.set_master_volume(0.7)
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "0.5\n" in contents
    assert contents.count("CHESS_MASTER_VOLUME=") == 1
    assert "CHESS_MASTER_VOLUME=0.700" in contents


def test_persist_preserves_foreign_line_on_unrelated_write():
    """A line _persist doesn't own (not a comment, not a recognized KEY=VALUE)
    must survive an unrelated settings write -- the write shouldn't silently
    destroy content it doesn't understand."""
    env._ENV_PATH.write_text(
        "CHESS_LAST_MODE=online\n"
        "some hand-typed note that isn't KEY=VALUE\n"
        "export SOMETHING_ELSE\n", encoding="utf-8"
    )
    env.set_master_volume(0.7)
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "some hand-typed note that isn't KEY=VALUE" in contents
    assert "export SOMETHING_ELSE" in contents
    assert "CHESS_MASTER_VOLUME=0.700" in contents


def test_persist_writes_unquoted_values():
    env.set_master_volume(0.65)
    contents = env._ENV_PATH.read_text(encoding="utf-8")
    assert "CHESS_MASTER_VOLUME=0.650" in contents
    assert "CHESS_MASTER_VOLUME='0.650'" not in contents


def test_persist_appends_new_key_when_absent():
    env._ENV_PATH.write_text("# only a comment\nCHESS_LAST_MODE=online\n", encoding="utf-8")
    env.set_master_volume(0.5)
    contents = env._ENV_PATH.read_text(encoding="utf-8")
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
    from chessshootout.server.protocol import is_uuid4
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
    assert os.environ.get("CHESS_DATA_DIR") == "/tmp/mygames"
    assert "CHESS_DATA_DIR=/tmp/mygames" in env._ENV_PATH.read_text(encoding="utf-8")


def test_set_data_dir_none_clears_override():
    env.set_data_dir("/tmp/mygames")
    env.set_data_dir(None)
    assert os.environ.get("CHESS_DATA_DIR") is None
    contents = env._ENV_PATH.read_text(encoding="utf-8") if env._ENV_PATH.exists() else ""
    assert "CHESS_DATA_DIR" not in contents


def test_set_data_dir_creates_missing_config_parent(tmp_path, monkeypatch):
    nested = tmp_path / "newconfig" / ".env"
    monkeypatch.setattr(env, "_ENV_PATH", nested)
    env.set_data_dir("/tmp/x")
    assert nested.exists()


def test_init_paths_points_env_at_config_dir(tmp_path, monkeypatch):
    from chessshootout import paths
    monkeypatch.setattr(paths, "get_config_dir", lambda: tmp_path)
    env.init_paths()
    assert env._ENV_PATH == tmp_path / ".env"


def test_env_default_path_derives_from_config_dir_not_file():
    """Regression (package consolidation): env.py lives at chessshootout/infra/,
    so a Path(__file__)-relative default resolves inside the package and drops a
    stray chessshootout/.env. The default must derive from get_config_dir()."""
    import pathlib
    src = pathlib.Path(env.__file__).read_text(encoding="utf-8")
    assert "get_config_dir()" in src
    assert "Path(__file__)" not in src


def test_default_time_control_round_trips():
    assert env.get_default_time_control() == "10"
    env.set_default_time_control("3")
    assert env.get_default_time_control() == "3"
    assert "CHESS_DEFAULT_TC=3" in env._ENV_PATH.read_text(encoding="utf-8")


def test_default_increment_round_trips():
    assert env.get_default_increment() == "5"
    env.set_default_increment("2")
    assert env.get_default_increment() == "2"
    assert "CHESS_DEFAULT_INCREMENT=2" in env._ENV_PATH.read_text(encoding="utf-8")


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
    env.set_theme("wood")
    assert env.get_theme() == "dark"
    env.set_theme("dark")
    assert env.get_theme() == "dark"


def test_launch_mode_defaults_windowed_and_validates():
    """The window opens where the player left it: windowed (default), maximized,
    or fullscreen. Anything unrecognised falls back to windowed."""
    assert env.get_launch_mode() == "windowed"
    for value in ("windowed", "maximized", "fullscreen"):
        env.set_launch_mode(value)
        assert env.get_launch_mode() == value
    env.set_launch_mode("cinema-mode")
    assert env.get_launch_mode() == "windowed"


def test_launch_mode_reads_a_raw_garbage_env_value_as_default(monkeypatch):
    monkeypatch.setenv("CHESS_LAUNCH_MODE", "borderless-nonsense")
    assert env.get_launch_mode() == "windowed"


def _throw_denied(*_a, **_k):
    raise PermissionError(5, "Access is denied")


def test_atomic_write_retries_then_succeeds(tmp_path, monkeypatch):
    """On Windows os.replace can transiently fail with WinError 5 (Access denied)
    while AV/indexer holds a handle; _atomic_write retries and succeeds."""
    monkeypatch.setattr(env, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(env, "_ATOMIC_WRITE_BACKOFF_S", 0)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(env.os, "replace", flaky_replace)
    env._atomic_write("CHESS_X=1\n")
    assert calls["n"] == 3
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "CHESS_X=1\n"


def test_atomic_write_gives_up_without_raising(tmp_path, monkeypatch):
    """A persistently locked .env must not crash the app: give up, drop the write,
    clean up the temp file."""
    monkeypatch.setattr(env, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(env, "_ATOMIC_WRITE_BACKOFF_S", 0)
    monkeypatch.setattr(env.os, "replace", _throw_denied)
    env._atomic_write("CHESS_X=1\n")
    assert not (tmp_path / ".env").exists()
    assert list(tmp_path.glob(".env.tmp.*")) == []


def test_set_volume_does_not_raise_when_env_locked(tmp_path, monkeypatch):
    """The real crash path: dragging a volume slider on Windows persisted every
    frame and a locked os.replace killed the app. set_master_volume must swallow it."""
    monkeypatch.setattr(env, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(env, "_ATOMIC_WRITE_BACKOFF_S", 0)
    monkeypatch.setattr(env.os, "replace", _throw_denied)
    env.set_master_volume(0.5)
    assert env.get_master_volume() == 0.5


def test_set_nickname_logs_only_the_key_never_the_value(caplog):
    """Persisted-setting breadcrumbs must never leak a nickname into the logs."""
    with caplog.at_level(logging.INFO, logger="chess.env"):
        env.set_nickname("TopSecretHandle")
    lines = [r.getMessage() for r in caplog.records if "setting persisted" in r.getMessage()]
    assert lines == ["setting persisted key=CHESS_NICKNAME"]
    assert "TopSecretHandle" not in " ".join(lines)


def test_get_or_create_client_uuid_logs_only_the_key_never_the_value(caplog):
    with caplog.at_level(logging.INFO, logger="chess.env"):
        fresh = env.get_or_create_client_uuid()
    lines = [r.getMessage() for r in caplog.records if "setting persisted" in r.getMessage()]
    assert lines == ["setting persisted key=CHESS_CLIENT_UUID"]
    assert fresh not in " ".join(lines)


def test_set_theme_logs_the_key_for_a_non_sensitive_setting(caplog):
    with caplog.at_level(logging.INFO, logger="chess.env"):
        env.set_theme("dark")
    lines = [r.getMessage() for r in caplog.records if "setting persisted" in r.getMessage()]
    assert lines == ["setting persisted key=CHESS_THEME"]


def test_set_country_empty_logs_the_deleted_key(caplog):
    env.set_country("us")
    with caplog.at_level(logging.INFO, logger="chess.env"):
        env.set_country("")
    lines = [r.getMessage() for r in caplog.records if "setting persisted" in r.getMessage()]
    assert lines == ["setting persisted key=CHESS_COUNTRY (deleted)"]


_CHESS_KEY_RE = re.compile(r'"(CHESS_[A-Z0-9_]+)"')
_SRC_ROOT = Path(env.__file__).resolve().parent.parent.parent / "chessshootout"
_ENV_EXAMPLE = Path(env.__file__).resolve().parent.parent.parent / ".env.example"


def _client_chess_env_keys():
    keys = set()
    for path in _SRC_ROOT.rglob("*.py"):
        if "server" in path.relative_to(_SRC_ROOT).parts:
            continue
        keys.update(_CHESS_KEY_RE.findall(path.read_text(encoding="utf-8")))
    return keys


def test_every_client_chess_env_key_is_documented_in_env_example():
    """Drift guard: any CHESS_* key read/written anywhere in the client code
    (chessshootout/, excluding the server-only subpackage -- server config
    lives in the deploy gameserver.env, not this client template) must have an
    entry in .env.example, or a player has no way to discover it exists."""
    keys = _client_chess_env_keys()
    assert keys
    example = _ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = {key for key in keys if key not in example}
    assert not missing
