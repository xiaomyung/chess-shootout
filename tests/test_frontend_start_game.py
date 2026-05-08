import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from backend.utils import Square
from backend.pieces import PieceColor
from frontend.frontend import Frontend, OPPONENT_NAME_FOR_MODE


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


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
    return Frontend(1000, 800)


def test_start_game_single_screen_white_side():
    app = make_app()
    app._on_start_game(base_config())
    assert app.white_name == "alice"
    assert app.black_name == "Player 2"
    assert app.mode == "single_screen"
    assert app.start_menu.is_visible() is False
    assert app.backend.clock is not None
    assert app.backend.clock.initial_seconds == 300
    assert app.backend.clock.increment_seconds == 2


def test_start_game_empty_nickname_falls_back_to_player():
    app = make_app()
    app._on_start_game(base_config(nickname=""))
    assert app.white_name == "Player 1"


def test_start_game_whitespace_nickname_falls_back():
    app = make_app()
    app._on_start_game(base_config(nickname="   "))
    assert app.white_name == "Player 1"


def test_start_game_black_side_swaps_names():
    app = make_app()
    app._on_start_game(base_config(nickname="alice", side="black"))
    assert app.white_name == "Player 2"
    assert app.black_name == "alice"


def test_start_game_random_side_resolves_deterministically():
    app = make_app()
    random.seed(0)
    app._on_start_game(base_config(side="random"))
    # _chosen_side is concrete after random resolution.
    assert app._chosen_side in {"white", "black"}


def test_opponent_name_for_each_mode():
    assert OPPONENT_NAME_FOR_MODE["single_screen"] == "Player 2"
    assert OPPONENT_NAME_FOR_MODE["bot"] == "AI Bot"
    assert OPPONENT_NAME_FOR_MODE["online"] == "Opponent"


def test_start_game_bot_mode_is_inert():
    app = make_app()
    app._on_start_game(base_config(mode="bot"))
    assert app.mode == "menu"
    assert app.backend.clock is None
    assert app.start_menu.is_visible() is True


def test_start_game_online_mode_is_inert():
    app = make_app()
    app._on_start_game(base_config(mode="online"))
    assert app.mode == "menu"
    assert app.backend.clock is None


def test_no_clock_means_backend_clock_is_none():
    app = make_app()
    app._on_start_game(base_config(time_minutes=None))
    assert app.backend.clock is None
    # _update_player_strips must not crash with None clock.
    app._update_player_strips()


def test_tick_clock_called_only_outside_menu():
    app = make_app()
    # In menu mode, draw_frame must NOT call tick_clock.
    calls = []
    original_tick = app.backend.tick_clock
    app.backend.tick_clock = lambda: calls.append(1)
    app.draw_frame()
    assert calls == []

    app._on_start_game(base_config())
    # After leaving menu, draw_frame ticks the clock.
    app.draw_frame()
    assert len(calls) >= 1
    app.backend.tick_clock = original_tick


def test_tick_clock_no_op_when_game_over():
    app = make_app()
    app._on_start_game(base_config())
    app.manual_result = "white_wins"
    pre = app.backend.clock.white_remaining
    for _ in range(20):
        app.draw_frame()
    assert app.backend.clock.white_remaining == pre


def test_new_game_preserves_time_control():
    app = make_app()
    app._on_start_game(base_config(time_minutes=10, increment_seconds=5))
    app.manual_result = "white_wins"
    app._on_new_game()
    assert app.backend.clock is not None
    assert app.backend.clock.initial_seconds == 600
    assert app.backend.clock.increment_seconds == 5


def test_undo_with_clock_restores_remaining():
    app = make_app()
    app._on_start_game(base_config())
    pre = app.backend.clock.white_remaining
    app.board.handle_click(Square(6, 4))
    app.board.handle_click(Square(4, 4))
    # Move-made debits + adds increment, so remaining should differ from pre.
    assert app.backend.clock.white_remaining != pre
    app._on_undo()
    assert app.backend.clock.white_remaining == pre


def test_strip_orientation_no_flip_puts_black_on_top():
    app = make_app()
    app._on_start_game(base_config())
    app.board.flipped = False
    app._update_player_strips()
    assert app.player_strip_top.name == app.black_name
    assert app.player_strip_bottom.name == app.white_name


def test_strip_orientation_flipped_puts_white_on_top():
    app = make_app()
    app._on_start_game(base_config())
    app.board.flipped = True
    app._update_player_strips()
    assert app.player_strip_top.name == app.white_name
    assert app.player_strip_bottom.name == app.black_name


def test_active_strip_at_start_is_bottom_when_white_to_move():
    app = make_app()
    app._on_start_game(base_config())
    app.board.flipped = False  # White at bottom.
    app._update_player_strips()
    assert app.player_strip_bottom.active is True
    assert app.player_strip_top.active is False


def test_no_active_at_game_over():
    app = make_app()
    app._on_start_game(base_config())
    app.manual_result = "white_wins"
    app._update_player_strips()
    assert app.player_strip_top.active is False
    assert app.player_strip_bottom.active is False


def test_save_pgn_writes_headers_with_names_and_time_control(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    monkeypatch.setattr("frontend.frontend.PROJECT_ROOT", str(tmp_path))
    app.manual_result = "white_wins"  # by resignation
    app._on_save_pgn()
    files = list((tmp_path / "games").glob("*.pgn"))
    assert len(files) == 1
    content = files[0].read_text()
    assert '[White "alice"]' in content
    assert '[Black "Player 2"]' in content
    assert '[TimeControl "300+2"]' in content


def test_save_pgn_marks_time_forfeit_on_timeout(tmp_path, monkeypatch):
    app = make_app()
    app._on_start_game(base_config())
    app.backend.clock.flagged = PieceColor.WHITE
    app.backend.clock.white_remaining = 0
    monkeypatch.setattr("frontend.frontend.PROJECT_ROOT", str(tmp_path))
    app._on_save_pgn()
    files = list((tmp_path / "games").glob("*.pgn"))
    content = files[0].read_text()
    assert '[Termination "Time forfeit"]' in content
    assert '[Result "0-1"]' in content
