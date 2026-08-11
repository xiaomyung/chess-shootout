"""Frontend start-game wiring: _on_start_game mode gating, name/clock setup, and the
player-strip/auto-save behavior that hangs off a started game. Only single_screen
actually starts a game in-process; bot returns early and online connects directly to
the configured server (address lives in Settings — no modal), so neither builds a
clock or leaves the "menu" mode until the server confirms the game."""

import os
import random

import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.backend.pieces import PieceColor
from chessshootout.infra import countries, env
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.screens.game import OPPONENT_NAME_FOR_MODE
from chessshootout.online.client import OnlineClient
from chessshootout.domain.pgn.load import extract_csmatchid, parse_pgn_headers
from tests.helpers import fake_uuid4
from tests.helpers import make_app as _shared_make_app


class _StubClient:
    def __init__(self, room_id):
        self.room_id = room_id


def _online_payload(**overrides):
    payload = {
        "white_name": "alice", "black_name": "bob", "your_color": "white",
        "time_minutes": 5, "increment_seconds": 2,
    }
    payload.update(overrides)
    return payload


_pygame_init = pygame_display(1000, 800)

_SERVER_TARGET_VARS = ("CHESS_SERVER_MODE", "CHESS_CUSTOM_SERVER_ADDR", "CHESS_SERVER_ADDR")


@pytest.fixture(autouse=True)
def _isolate_server_target_env(monkeypatch):
    """env.set_server_mode/set_custom_server_addr write os.environ directly (not
    via monkeypatch), so the official-mode test would otherwise leak the resolved
    production address into every later test in the worker."""
    for var in _SERVER_TARGET_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    for var in _SERVER_TARGET_VARS:
        os.environ.pop(var, None)


def base_config(**overrides):
    cfg = {
        "mode": "single_screen",
        "nickname": "alice",
        "time_minutes": 5,
        "increment_seconds": 2,
        "side": "white",
    }
    cfg.update(overrides)
    return cfg


def make_app():
    return _shared_make_app(1000, 800, mock_sound=False)


def test_start_game_single_screen_white_side():
    app = make_app()
    app._on_start_game(base_config())
    assert app.game.white_name == "alice"
    assert app.game.black_name == "Player 2"
    assert app.game.variant == "local"
    assert app.menu.play_view_visible() is False
    clock = app.game.match.backend.clock
    assert clock is not None
    assert clock.initial_seconds == 300
    assert clock.increment_seconds == 2


@pytest.mark.parametrize("nickname", [
    pytest.param("", id="empty_string"),
    pytest.param("   ", id="whitespace_only"),
])
def test_start_game_blank_nickname_falls_back_to_player(nickname):
    """Blank/whitespace nicknames are stripped to "Player 1" for the white side."""
    app = make_app()
    app._on_start_game(base_config(nickname=nickname))
    assert app.game.white_name == "Player 1"
    assert app.game.black_name == "Player 2"


def test_start_game_black_side_swaps_names():
    app = make_app()
    app._on_start_game(base_config(nickname="alice", side="black"))
    assert app.game.white_name == "Player 2"
    assert app.game.black_name == "alice"


def test_start_game_gives_your_country_and_random_opponent(monkeypatch):
    monkeypatch.setattr(env, "get_country", lambda: "RO")
    app = make_app()
    app._on_start_game(base_config(side="white"))
    assert app.game.white_country == "RO"
    assert app.game.black_country in countries.CODES
    assert app.game.black_country != ""


def test_start_game_black_side_swaps_country(monkeypatch):
    monkeypatch.setattr(env, "get_country", lambda: "RO")
    app = make_app()
    app._on_start_game(base_config(side="black"))
    assert app.game.black_country == "RO"
    assert app.game.white_country in countries.CODES


def test_start_game_no_country_leaves_your_side_blank(monkeypatch):
    monkeypatch.setattr(env, "get_country", lambda: "")
    app = make_app()
    app._on_start_game(base_config(side="white"))
    assert app.game.white_country == ""
    assert app.game.black_country in countries.CODES


def test_country_flows_to_player_strips(monkeypatch):
    monkeypatch.setattr(env, "get_country", lambda: "RO")
    app = make_app()
    app._on_start_game(base_config(side="white"))
    app.game._update_player_strips()
    assert "RO" in {app.game.player_strip_top.country, app.game.player_strip_bottom.country}


def test_start_game_random_side_resolves_to_concrete_color():
    """A "random" side preference is resolved to a concrete color before game start."""
    app = make_app()
    random.seed(0)
    app._on_start_game(base_config(side="random"))
    assert app.game._chosen_side in {"white", "black"}


def test_opponent_name_for_each_mode():
    assert OPPONENT_NAME_FOR_MODE["single_screen"] == "Player 2"
    assert OPPONENT_NAME_FOR_MODE["bot"] == "Bot"
    assert "online" not in OPPONENT_NAME_FOR_MODE


def test_start_game_bot_mode_returns_early_without_starting():
    """Bot mode hits the early return: no game is set up and the menu stays put."""
    app = make_app()
    assert app.screen is app.menu
    app._on_start_game(base_config(mode="bot"))
    assert app.screen is app.menu
    assert app.game.match.backend.clock is None
    assert app.menu.play_view_visible() is True
    assert app.coordinator.client is None


def test_start_game_online_mode_starts_matchmaking_without_starting_game(monkeypatch):
    """Online mode connects to the configured server directly (no modal) and shows
    the searching wait modal; the game itself isn't set up until game_start."""
    app = make_app()
    connected = []
    monkeypatch.setattr(
        OnlineClient, "connect",
        lambda self, addr, request: connected.append((addr, request)))
    app._on_start_game(base_config(mode="online"))
    assert app.screen is app.menu
    assert app.game.match.backend.clock is None
    assert app.menu.play_view_visible() is False
    assert app.coordinator.client is not None
    assert app.coordinator.wait_modal.is_visible() is True
    assert connected and connected[0][0] == env.get_server_addr()


def test_no_clock_leaves_strips_clockless():
    """With time_minutes=None no clock is built and the strips report no seconds."""
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    assert app.game.match.backend.clock is None
    app.game._update_player_strips()
    assert app.game.player_strip_top.clock_seconds is None
    assert app.game.player_strip_bottom.clock_seconds is None


def test_tick_clock_called_only_outside_menu():
    """draw_frame ticks the clock only once a game has started, never in the menu."""
    app = make_app()
    calls = []
    backend = app.game.match.backend
    original_tick = backend.tick_clock
    backend.tick_clock = lambda: calls.append(1)
    app.draw_frame()
    assert calls == []

    app._on_start_game(base_config())
    app.draw_frame()
    assert len(calls) >= 1
    backend.tick_clock = original_tick


def test_tick_clock_no_op_when_game_over():
    app = make_app()
    app._on_start_game(base_config())
    app.game.manual_result = "white_wins"
    pre = app.game.match.backend.clock.white_remaining
    for _ in range(20):
        app.draw_frame()
    assert app.game.match.backend.clock.white_remaining == pre


def test_new_game_preserves_time_control():
    app = make_app()
    app._on_start_game(base_config(time_minutes=10, increment_seconds=5))
    app.game.manual_result = "white_wins"
    app._on_new_game()
    clock = app.game.match.backend.clock
    assert clock is not None
    assert clock.initial_seconds == 600
    assert clock.increment_seconds == 5


def test_undo_with_clock_restores_remaining():
    """A move debits and increments the clock; undo restores the pre-move remaining."""
    app = make_app()
    app._on_start_game(base_config())
    clock = app.game.match.backend.clock
    pre = clock.white_remaining
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    assert clock.white_remaining != pre
    app.game._on_undo()
    assert clock.white_remaining == pre


@pytest.mark.parametrize("flipped, top_is_white", [
    pytest.param(False, False, id="no_flip_black_on_top"),
    pytest.param(True, True, id="flipped_white_on_top"),
])
def test_strip_orientation_follows_board_flip(flipped, top_is_white):
    """The top strip shows whichever color the flip puts at the top of the board."""
    app = make_app()
    app._on_start_game(base_config())
    app.game.board.flipped = flipped
    app.game._update_player_strips()
    top, bottom = (app.game.white_name, app.game.black_name) if top_is_white \
        else (app.game.black_name, app.game.white_name)
    assert app.game.player_strip_top.name == top
    assert app.game.player_strip_bottom.name == bottom


def test_active_strip_at_start_is_bottom_when_white_to_move():
    """Unflipped, white is at the bottom, so the bottom strip is the active one at move 1."""
    app = make_app()
    app._on_start_game(base_config())
    app.game.board.flipped = False
    app.game._update_player_strips()
    assert app.game.player_strip_bottom.active is True
    assert app.game.player_strip_top.active is False


def test_no_active_at_game_over():
    app = make_app()
    app._on_start_game(base_config())
    app.game.manual_result = "white_wins"
    app.game._update_player_strips()
    assert app.game.player_strip_top.active is False
    assert app.game.player_strip_bottom.active is False


def test_auto_save_writes_headers_with_names_and_time_control(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    app.game.manual_result = "white_wins"
    app.game.result_flow.auto_save_pgn()
    files = list((tmp_path / "games").glob("*.pgn"))
    assert len(files) == 1
    assert files[0].name.startswith("local-")
    content = files[0].read_text(encoding="utf-8")
    assert '[White "alice"]' in content
    assert '[Black "Player 2"]' in content
    assert '[TimeControl "300+2"]' in content


def test_auto_save_marks_time_forfeit_on_timeout(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    app.game.match.backend.clock.flagged = PieceColor.WHITE
    app.game.match.backend.clock.white_remaining = 0
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.result_flow.auto_save_pgn()
    files = list((tmp_path / "games").glob("*.pgn"))
    content = files[0].read_text(encoding="utf-8")
    assert '[Termination "Time forfeit"]' in content
    assert '[Result "0-1"]' in content


def test_auto_save_records_path_and_shows_toast(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.manual_result = "white_wins"
    path = app.game.result_flow.auto_save_pgn()
    assert path is not None
    assert app.game.result_flow._last_saved_pgn_path == path
    assert app.toast.is_visible() is True
    assert "Saved" in app.toast.message


def test_open_pgn_invokes_default_app(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.manual_result = "white_wins"
    app.game.result_flow.auto_save_pgn()
    captured = {}
    monkeypatch.setattr(
        "chessshootout.frontend.pgn_open.open_with_default_app",
        lambda path: captured.setdefault("path", path) or True,
    )
    app.game.result_flow.on_open_pgn()
    assert captured["path"] == app.game.result_flow._last_saved_pgn_path


def test_open_pgn_no_op_when_no_saved_path():
    app = make_app()
    app._on_start_game(base_config())
    app.game.result_flow.on_open_pgn()
    assert app.toast.message == "No saved PGN"


def test_open_pgn_warns_on_open_failure(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.manual_result = "white_wins"
    app.game.result_flow.auto_save_pgn()
    monkeypatch.setattr(
        "chessshootout.frontend.pgn_open.open_with_default_app", lambda _path: False,
    )
    app.game.result_flow.on_open_pgn()
    assert app.toast.message == "Could not open PGN"


def test_local_game_mints_match_session_id():
    app = make_app()
    assert app.game._match_session_id is None
    app._on_start_game(base_config())
    assert extract_csmatchid(
        {"CSMatchId": app.game._match_session_id}) == app.game._match_session_id


def test_new_game_reuses_match_session_id():
    """The in-game New Game button stacks onto the same match session (a local rematch)."""
    app = make_app()
    app._on_start_game(base_config())
    first = app.game._match_session_id
    app.game.manual_result = "white_wins"
    app._on_new_game()
    assert app.game._match_session_id == first


def test_local_new_game_flips_sides_and_names():
    """A local rematch flips the player's side: who played White now plays Black, with
    the name/country labels swapped to match."""
    app = make_app()
    app._on_start_game(base_config(side="white", nickname="alice"))
    assert app.game._chosen_side == "white"
    assert app.game.white_name == "alice"
    app.game.white_country, app.game.black_country = "RO", "US"
    app.game.manual_result = "white_wins"
    app._on_new_game()
    assert app.game._chosen_side == "black"
    assert app.game.white_name == "Player 2"
    assert app.game.black_name == "alice"
    assert (app.game.white_country, app.game.black_country) == ("US", "RO")


def test_back_to_menu_clears_match_session_id():
    app = make_app()
    app._on_start_game(base_config())
    assert app.game._match_session_id is not None
    app._on_back_to_menu()
    assert app.game._match_session_id is None


def test_fresh_local_game_after_menu_return_mints_new_session():
    app = make_app()
    app._on_start_game(base_config())
    first = app.game._match_session_id
    app._on_back_to_menu()
    app._on_start_game(base_config())
    assert app.game._match_session_id != first


def test_fen_start_mints_match_session_id():
    app = make_app()
    ok = app._start_game_from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert ok is True
    assert extract_csmatchid(
        {"CSMatchId": app.game._match_session_id}) == app.game._match_session_id


def test_fen_start_arms_skillchecks_with_a_fresh_local_seed():
    # FEN-only payloads used to skip _apply_start_config, leaving the coordinator
    # at its enabled=False default -- custom-position games silently never rolled
    # a skill-check.
    app = make_app()
    app._start_game_from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert app.game.skillcheck.enabled is True
    first_seed = app.game.skillcheck.seed
    assert first_seed.startswith("local-")
    app._start_game_from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert app.game.skillcheck.enabled is True
    assert app.game.skillcheck.seed != first_seed


def test_online_match_session_uses_room_id():
    app = make_app()
    room = fake_uuid4(2)
    app.coordinator.client = _StubClient(room)
    app.coordinator._start_online_game(_online_payload())
    assert app.game._match_session_id == room


def test_online_rematch_same_room_keeps_match_session_id():
    """A rematch re-enters _start_online_game with the same room; the id is stable."""
    app = make_app()
    room = fake_uuid4(4)
    app.coordinator.client = _StubClient(room)
    app.coordinator._start_online_game(_online_payload())
    app.coordinator._start_online_game(_online_payload())
    assert app.game._match_session_id == room


def test_online_game_start_threads_countries_to_state():
    app = make_app()
    app.coordinator.client = _StubClient(fake_uuid4(6))
    app.coordinator._start_online_game(_online_payload(white_country="US", black_country="RO"))
    assert app.game.white_country == "US"
    assert app.game.black_country == "RO"


def test_online_game_start_without_countries_defaults_blank():
    app = make_app()
    app.coordinator.client = _StubClient(fake_uuid4(7))
    app.coordinator._start_online_game(_online_payload())
    assert app.game.white_country == ""
    assert app.game.black_country == ""


def test_saved_local_pgn_contains_match_session_id(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    app.game.manual_result = "white_wins"
    app.game.result_flow.auto_save_pgn()
    content = list((tmp_path / "games").glob("*.pgn"))[0].read_text(encoding="utf-8")
    assert extract_csmatchid(parse_pgn_headers(content)) == app.game._match_session_id


@pytest.mark.parametrize("variant_value, expected_prefix", [
    pytest.param("local", "local", id="single_screen_local"),
    pytest.param("bot", "bot", id="bot_bot"),
    pytest.param("online", "online", id="online_online"),
])
def test_auto_save_filename_prefix_per_mode(tmp_path, monkeypatch, variant_value, expected_prefix):
    app = make_app()
    app._on_start_game(base_config())
    app.game.match.backend.try_move(Square(6, 4), Square(4, 4))
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app.game.variant = variant_value
    app.game.manual_result = "white_wins"
    app.game.result_flow.auto_save_pgn()
    files = list((tmp_path / "games").glob("*.pgn"))
    assert files
    assert files[0].name.startswith(f"{expected_prefix}-")


@pytest.mark.parametrize("mode_value", ["single_screen", "online"])
def test_start_game_persists_nickname(monkeypatch, mode_value):
    """Starting a game (local or online) persists the entered nickname so the profile
    survives a relaunch."""
    app = make_app()
    saved = []
    monkeypatch.setattr(env, "set_nickname", lambda v: saved.append(v))
    monkeypatch.setattr(OnlineClient, "connect", lambda self, addr, request: None)
    app._on_start_game(base_config(mode=mode_value, nickname="Hikaru"))
    assert saved == ["Hikaru"]


def test_settings_close_persists_the_custom_server_address(monkeypatch):
    """Editing the Options custom-address field and leaving the view persists it
    via env, so the next matchmake + reconnect probe target the last-used
    server."""
    app = make_app()
    saved = []
    monkeypatch.setattr(env, "set_custom_server_addr", lambda v: saved.append(v))
    app.menu.goto_view("options")
    app.settings._custom_server_row.input.text = "chess.example.com:9000"
    app.menu.goto_view("play")
    assert saved == ["chess.example.com:9000"]


def test_online_connect_uses_the_official_address_in_official_mode(monkeypatch):
    """Official mode rewrites the resolved active address at set-time, so
    matchmaking connects to the production host no matter what custom address
    is stored."""
    env.set_custom_server_addr("10.0.0.5:9000")
    env.set_server_mode("official")
    app = make_app()
    connected = []
    monkeypatch.setattr(OnlineClient, "connect",
                        lambda self, addr, request: connected.append(addr))
    app._on_start_game(base_config(mode="online"))
    assert connected == [env.official_server_addr()]


def test_first_run_profile_hint_toasts_once_when_the_flag_is_unset(monkeypatch):
    """v2.9.0: a brand-new install (flag never set) sees a one-time hype toast
    pointing at Profile, and the flag is persisted immediately so it never
    fires again."""
    monkeypatch.delenv("CHESS_PROFILE_HINT_SHOWN", raising=False)
    assert env.get_profile_hint_shown() is False

    app = Frontend(1000, 800)

    messages = [b["message"] for b in app.toast._bubbles]
    assert "Set your name in Profile >" in messages
    assert env.get_profile_hint_shown() is True


def test_first_run_profile_hint_does_not_repeat_once_the_flag_is_persisted(monkeypatch):
    monkeypatch.delenv("CHESS_PROFILE_HINT_SHOWN", raising=False)
    env.set_profile_hint_shown()

    app = Frontend(1000, 800)

    messages = [b["message"] for b in app.toast._bubbles]
    assert "Set your name in Profile >" not in messages
