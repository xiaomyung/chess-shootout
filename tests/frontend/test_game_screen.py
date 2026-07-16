"""GameScreen lifecycle: enter()/exit() own the match/board/config state, the
local vs online variant split drives Match.mode + the game-info pill, and
back-to-menu still exits the screen clean while keeping the save backstop."""

import logging
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceType
from chessshootout.backend.utils import Square
from chessshootout.domain import openings
from chessshootout.domain.match import ONLINE, SINGLE_SCREEN
from chessshootout.domain.premoves import Premove
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.panels.right import SECTION_OPEN
from chessshootout.frontend.screens.base import Nav
from chessshootout.frontend.skillcheck.wheel_view import WheelController
from chessshootout.skillcheck.wheel import WheelChallenge
from chessshootout.server.protocol import GIVE_TIME_SECONDS
from tests.helpers import make_app as _make_app_at, start_single_screen


_pygame_init = pygame_display(1000, 800)

SPARSE_FEN = "8/8/8/4k3/8/4K3/8/8 w - - 0 1"


def _make_app():
    return _make_app_at(1000, 800)


def _key(key, mod=0):
    return pg.event.Event(pg.KEYDOWN, {"key": key, "unicode": "", "mod": mod})


def test_enter_applies_start_config_and_resets_match():
    app = _make_app()
    start_single_screen(app, nickname="carol", side="black",
                         time_minutes=3, increment_seconds=2)
    game = app.game
    assert game.match.move_history == []
    assert game.variant == "local"
    assert game.match.mode == SINGLE_SCREEN
    assert game.black_name == "carol"
    assert game.white_name == "Player 2"
    assert game._chosen_side == "black"
    assert game._time_control == (180, 2)


def test_enter_with_fen_applies_position():
    app = _make_app()
    app.request_nav(Nav("game", {"fen": SPARSE_FEN}))
    app._execute_pending_nav()
    game = app.game
    assert game.match.move_history == []
    king = game.match.piece_at(Square(3, 4))
    assert king is not None and king.type == PieceType.KING


def test_online_variant_drives_match_mode_and_pill():
    app = _make_app()
    app.switch_to("game", variant=ONLINE)
    game = app.game
    assert game.variant == "online"
    assert game.match.mode == ONLINE
    assert game._compute_game_info()["mode"] == "Online"
    assert game.result_flow._auto_save_prefix() == "online"


def test_exit_cancels_focus_drag_premoves_annotations_and_skillcheck(caplog):
    app = _make_app()
    start_single_screen(app)
    game = app.game
    game.focus_mode = True
    game.board.dragging_from = Square(6, 4)
    game.board.premoves.append(
        Premove(Square(6, 4), Square(4, 4), game.match.piece_at(Square(6, 4))))
    game.board.toggle_highlight(Square(4, 4))
    controller = WheelController(WheelChallenge.from_seed("x"), pg.Rect(0, 0, 80, 80), 0)
    game.skillcheck_overlay.start(controller, ("f", "t"), lambda c, landed: None)

    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        app.switch_to("menu")

    assert game.focus_mode is False
    assert game.board.dragging_from is None
    assert game.board.premoves == []
    assert game.board.highlighted_squares == set()
    assert game.skillcheck_overlay.is_active() is False
    assert "game exit teardown" in caplog.text


def test_back_to_menu_end_to_end_saves_and_exits_screen_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    start_single_screen(app, time_minutes=None)
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    app.game.manual_result = "white_wins_by_resignation"

    app._on_back_to_menu()

    assert app.screen is app.menu
    files = list((tmp_path / "games").glob("*.pgn"))
    assert len(files) == 1
    assert '[Result "1-0"]' in files[0].read_text(encoding="utf-8")


def test_enter_is_idempotent_baseline_across_two_consecutive_enters():
    app = _make_app()
    start_single_screen(app, nickname="dana", side="white", time_minutes=5)
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    assert len(app.game.match.move_history) == 1

    start_single_screen(app, nickname="erin", side="white", time_minutes=5)
    assert app.game.match.move_history == []
    assert app.game.white_name == "erin"

    start_single_screen(app, nickname="erin", side="white", time_minutes=5)
    assert app.game.match.move_history == []
    assert app.game.white_name == "erin"


def test_enter_logs_variant(caplog):
    app = _make_app()
    with caplog.at_level(logging.INFO, logger="chess.frontend"):
        start_single_screen(app)
    assert "variant=" in caplog.text


@pytest.mark.parametrize("mod", [0, pg.KMOD_CTRL], ids=["plain_z", "ctrl_z"])
def test_z_undoes_a_ply(mod):
    app = _make_app()
    start_single_screen(app, time_minutes=None)
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    assert len(app.game.match.move_history) == 1
    assert app.game.handle_key(_key(pg.K_z, mod=mod)) is True
    assert app.game.match.move_history == []


def test_g_grants_give_time_once_to_recipient_clock():
    app = _make_app()
    start_single_screen(app, side="white", time_minutes=5, increment_seconds=0)
    clock = app.game.match.clock
    clock.white_remaining -= 40
    before = clock.white_remaining
    assert app.game.handle_key(_key(pg.K_g)) is True
    assert clock.white_remaining == pytest.approx(before + GIVE_TIME_SECONDS)


def test_a_key_toggles_actions_section():
    app = _make_app()
    start_single_screen(app)
    assert SECTION_OPEN["actions"] is True
    assert app.game.handle_key(_key(pg.K_a)) is True
    assert SECTION_OPEN["actions"] is False


def test_s_key_toggles_signals_section():
    app = _make_app()
    start_single_screen(app)
    assert SECTION_OPEN["signals"] is True
    assert app.game.handle_key(_key(pg.K_s)) is True
    assert SECTION_OPEN["signals"] is False


def _play_giuoco(game):
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]:
        assert game.match.apply_san(san).legal


def test_live_game_reports_opening_name():
    app = _make_app()
    start_single_screen(app, time_minutes=None)
    _play_giuoco(app.game)
    assert app.game._debut_line() == ("C50", "Italian Game: Giuoco Piano")


def test_debut_provider_truncates_sans_when_browsing_back(monkeypatch):
    app = _make_app()
    start_single_screen(app, time_minutes=None)
    game = app.game
    _play_giuoco(game)
    captured = []
    monkeypatch.setattr(openings, "lookup",
                        lambda sans: captured.append(list(sans)))
    game._debut_memo = None
    game.board.jump_to_review_ply(4)
    game._debut_line()
    assert captured == [["e4", "e5", "Nf3", "Nc6"]], \
        "browsing back feeds the truncated line to the opening lookup"


def test_custom_fen_game_skips_opening_lookup(monkeypatch):
    app = _make_app()
    app.request_nav(Nav("game", {"fen": SPARSE_FEN}))
    app._execute_pending_nav()
    game = app.game
    called = []
    monkeypatch.setattr(openings, "lookup", lambda sans: called.append(sans))
    assert game._custom_start is True
    assert game._debut_line() is None
    assert called == [], "a custom-FEN start never consults the opening book"


def test_new_game_after_fen_restores_opening_detection():
    app = _make_app()
    app.request_nav(Nav("game", {"fen": SPARSE_FEN}))
    app._execute_pending_nav()
    game = app.game
    assert game._custom_start is True
    app._on_new_game()
    assert game._custom_start is False
    assert game.match.apply_san("e4").legal
    assert game._debut_line() is not None


def test_rail_controls_with_owned_sounds_suppress_the_generic_click():
    """Caps, section headers, chips, and vol notches each play their own sound;
    the router's fallback ui_click must stay silent for them (no doubled click),
    while a plain board/move-list click still gets the generic click."""
    app = _make_app_at(1200, 900)
    start_single_screen(app, nickname="a", side="white",
                        time_minutes=5, increment_seconds=0)
    from chessshootout.frontend.panels import right as right_mod
    right_mod.SECTION_OPEN.update({"actions": True, "signals": True, "chat": True})
    rm = app.game.right_menu
    rm.sounds = app.sound_manager
    rm.set_rect(rm._last_outer_rect, rm._last_scale)
    app.draw_frame()

    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(rm.button_rects["flip"].center)
    app.sound_manager.play_cap_press.assert_called_once()
    app.sound_manager.play_ui_click.assert_not_called()

    header = next(b.header for b in rm._section_blocks if b.key == "signals")
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(header.center)
    app.sound_manager.play_section_toggle.assert_called_once()
    app.sound_manager.play_ui_click.assert_not_called()
    rm.toggle_section("signals")
    app.draw_frame()

    chip_rect = next(rect for chip, rect in rm._signal_chips if chip.key == "sound")
    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(chip_rect.center)
    app.sound_manager.play_chip_toggle.assert_called_once()
    app.sound_manager.play_ui_click.assert_not_called()

    app.sound_manager.reset_mock()
    app.input_router.mouse_left_clicked(app.game.board.rect.center)
    app.sound_manager.play_ui_click.assert_called_once()
