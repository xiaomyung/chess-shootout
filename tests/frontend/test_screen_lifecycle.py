"""Systematic lifecycle matrix for the four screens (step 7 of the
screen-architecture refactor): enter/exit idempotence, a nav-path matrix,
post-exit event safety, inactive-screen-modal draw safety, and resize
mid-transition/mid-drag/mid-animation.

Deliberately does NOT duplicate what's already pinned elsewhere:
- test_online_coordinator.py already covers the coordinator-side no-subscriber
  assert and the RESULT-with-no-subscriber save/score fallback.
- test_modal_registry.py already covers menu-modal -> game (fen_input excluded
  once the game screen is active); this file only adds the missing directions
  (game -> menu, review -> history).
- test_review_screen.py::test_self_switch_reload_shows_the_new_pgn already
  covers review's own self-switch (pgn A -> pgn B); not repeated here.
- test_scroll_routing.py::test_resize_cancels_active_gesture already covers
  resize cancelling an in-flight move-list scroll drag.
"""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)

SPARSE_FEN = "8/8/8/4k3/8/4K3/8/8 w - - 0 1"


def _write_pgn(tmp_path, name="lifecycle.pgn"):
    path = tmp_path / name
    path.write_text(
        '[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n'
        '[TimeControl "300+0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n',
        encoding="utf-8",
    )
    return path


def _entry_payload(name, tmp_path):
    if name == "review":
        return {"pgn_path": str(_write_pgn(tmp_path)), "return_to": "menu"}
    return {}


def _key(key, unicode=""):
    return pg.event.Event(pg.KEYDOWN, key=key, mod=0, unicode=unicode)


# --- enter/exit idempotence -------------------------------------------------

@pytest.mark.parametrize("name", ["menu", "game", "history", "review"])
def test_enter_exit_double_exit_reenter_leaves_the_screen_functional(name, tmp_path):
    app = make_app()
    payload = _entry_payload(name, tmp_path)

    app.switch_to(name, **payload)
    screen = app.screens[name]
    assert app.screen is screen

    screen.exit()
    screen.exit()  # double-exit must not raise

    screen.enter(**payload)
    app.screen = screen
    app._compute_layout()
    app.draw_frame()  # must not raise; screen still functional


# --- nav matrix --------------------------------------------------------------

def _menu_game_menu(app, tmp_path, monkeypatch):
    app.switch_to("game")
    assert app.screen.name == "game"
    app.switch_to("menu")
    return "menu"


def _menu_history_review_history_menu(app, tmp_path, monkeypatch):
    app.switch_to("history")
    assert app.screen.name == "history"
    pgn = _write_pgn(tmp_path)
    app.switch_to("review", pgn_path=str(pgn), return_to="history")
    assert app.screen.name == "review"
    app.switch_to("history")
    assert app.screen.name == "history"
    app.switch_to("menu")
    return "menu"


def _menu_game_fen_menu(app, tmp_path, monkeypatch):
    app.switch_to("game", fen=SPARSE_FEN)
    king = app.game.match.piece_at(Square(3, 4))
    assert king is not None
    app.switch_to("menu")
    return "menu"


def _game_game_self_switch_rematch(app, tmp_path, monkeypatch):
    app.switch_to("game", side="white", nickname="alice",
                  time_minutes=5, increment_seconds=0)
    exit_calls = []
    original_exit = app.game.exit

    def spy_exit():
        exit_calls.append(1)
        return original_exit()

    monkeypatch.setattr(app.game, "exit", spy_exit)
    app.switch_to("game", side="black", nickname="bob",
                  time_minutes=3, increment_seconds=0)
    assert exit_calls == [1], "self-switch game -> game must still run a full exit/enter cycle"
    assert app.game._chosen_side == "black"
    assert app.game.black_name == "bob"
    return "game"


def _menu_online_match_found(app, tmp_path, monkeypatch):
    app.coordinator.client = MagicMock()
    app.coordinator.client.room_id = "room-1"
    app.coordinator.client.opp_state = "connected"
    app.coordinator.client.is_connected.return_value = False
    payload = {"your_color": "white", "white_name": "alice", "black_name": "bob",
               "time_minutes": 5, "increment_seconds": 0}
    app.coordinator._start_online_game(payload)
    assert app.game.variant == "online"
    assert app.coordinator._subscriber is app.game
    return "game"


NAV_MATRIX = [
    pytest.param(_menu_game_menu, id="menu_game_menu"),
    pytest.param(_menu_history_review_history_menu, id="menu_history_review_history_menu"),
    pytest.param(_menu_game_fen_menu, id="menu_game_fen_menu"),
    pytest.param(_game_game_self_switch_rematch, id="game_game_self_switch_rematch"),
    pytest.param(_menu_online_match_found, id="menu_online_match_found"),
]


@pytest.mark.parametrize("scenario", NAV_MATRIX)
def test_nav_matrix(scenario, tmp_path, monkeypatch):
    app = make_app()
    expected_final_screen = scenario(app, tmp_path, monkeypatch)
    assert app.screen.name == expected_final_screen
    app.draw_frame()  # every path must land on a screen that draws cleanly


# --- post-exit event safety ---------------------------------------------------

@pytest.mark.parametrize("name", ["menu", "game", "history", "review"])
def test_handle_key_and_click_on_an_exited_inactive_screen_is_harmless(name, tmp_path):
    app = make_app()
    payload = _entry_payload(name, tmp_path)
    app.switch_to(name, **payload)
    screen = app.screens[name]

    other = "history" if name != "history" else "menu"
    app.switch_to(other)  # runs screen.exit(); screen is now inactive

    screen.handle_click((10, 10))
    screen.handle_key(_key(pg.K_a, "a"))

    app.draw_frame()  # must not raise, and the real active screen is unaffected
    assert app.screen.name == other
    assert app.screen is not screen


# --- draw-on-inactive-screen safety (extends test_modal_registry.py) --------

def test_help_modal_shown_on_game_is_not_drawn_after_switch_to_menu():
    app = make_app()
    app.switch_to("game")
    app.help_modal.show([("Esc", "Back")])
    assert app.help_modal.is_visible() is True

    app.switch_to("menu")
    drawn = []
    app.help_modal.draw = lambda: drawn.append(1)
    app.draw_frame()

    assert drawn == []
    assert app.help_modal.is_visible() is False, "exit() hides the screen's own modals"
    assert app.help_modal not in [spec.obj for spec in app._active_modal_specs()]


def test_help_modal_shown_on_review_is_not_drawn_after_switch_to_history(tmp_path):
    app = make_app()
    pgn = _write_pgn(tmp_path)
    app.switch_to("review", pgn_path=str(pgn), return_to="history")
    app.help_modal.show([("Esc", "Back")])
    assert app.help_modal.is_visible() is True

    app.switch_to("history")
    drawn = []
    app.help_modal.draw = lambda: drawn.append(1)
    app.draw_frame()

    assert drawn == []
    assert app.help_modal.is_visible() is False


# --- resize mid-anything ------------------------------------------------------

@pytest.mark.parametrize("name", ["menu", "game", "history", "review"])
def test_videoresize_while_screen_active_recomputes_layout_without_crash(name, tmp_path):
    app = make_app()
    payload = _entry_payload(name, tmp_path)
    app.switch_to(name, **payload)
    w, h = app.window_width, app.window_height

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": w + 100, "h": h + 50}))
    app.input_router.check_events()

    assert (app.window_width, app.window_height) == (w + 100, h + 50)
    app.draw_frame()


def test_videoresize_mid_focus_transition_aborts_it_cleanly():
    app = make_app()
    app.switch_to("game")
    app.game._toggle_focus(True)
    assert app.game.focus_transition is not None

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 900, "h": 700}))
    app.input_router.check_events()

    assert app.game.focus_transition is None
    app.draw_frame()


def _start_board_drag(board, sq):
    board.handle_click(sq)
    board.begin_press((0, 0))
    cell = board.cell_size
    cx = sq.col * cell + board.board_offset_x + cell // 2
    cy = sq.row * cell + board.board_offset_y + cell // 2
    board.drag._press_pos = (cx - 50, cy - 50)
    board.update_drag_motion((cx, cy))


def test_videoresize_mid_board_drag_does_not_crash():
    app = make_app()
    app.switch_to("game")
    _start_board_drag(app.game.board, Square(6, 4))
    assert app.game.board.dragging_from == Square(6, 4)

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 900, "h": 700}))
    app.input_router.check_events()

    app.draw_frame()


def test_videoresize_mid_review_animation_does_not_crash(tmp_path):
    app = make_app()
    pgn = _write_pgn(tmp_path)
    app.switch_to("review", pgn_path=str(pgn), return_to="history")
    app.review.handle_key(_key(pg.K_RIGHT))
    assert app.review.board.is_animating()

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 900, "h": 700}))
    app.input_router.check_events()

    app.draw_frame()
    assert app.review.board.rect.width > 0


# --- a screen's own modals must not outlive it ---------------------------------

def test_help_left_open_on_the_game_screen_does_not_re_arm_on_the_next_game():
    """help_modal is shared between game and review and is per-screen, so it is
    neither drawn nor blocking on the menu — it just sits there .is_visible().
    Re-entering a help-owning screen used to pull that stale modal straight back
    into the blocking predicate and kill all board input on a brand-new game."""
    app = make_app()
    app.switch_to("game")
    app.help_modal.show([("Esc", "Back")])

    app.switch_to("menu")
    app.switch_to("game")

    assert app.help_modal.is_visible() is False
    assert app._blocking_modal_visible() is False


def test_help_left_open_on_review_does_not_re_arm_on_the_next_review(tmp_path):
    app = make_app()
    pgn = _write_pgn(tmp_path)
    app.switch_to("review", pgn_path=str(pgn), return_to="history")
    app.help_modal.show([("Esc", "Back")])

    app.switch_to("history")
    app.switch_to("review", pgn_path=str(pgn), return_to="history")

    assert app.help_modal.is_visible() is False
    assert app._blocking_modal_visible() is False


def test_fen_input_left_open_on_the_menu_does_not_re_arm_on_the_next_menu():
    app = make_app()
    app.menu.fen_input_modal.show(on_submit=lambda text: True)

    app.switch_to("game")
    app.switch_to("menu")

    assert app.menu.fen_input_modal.is_visible() is False
    assert app._blocking_modal_visible() is False


@pytest.mark.parametrize("name", ["menu", "game", "history", "review"])
def test_exit_hides_every_modal_the_screen_owns(name, tmp_path):
    """Whatever a screen returns from modals(), exit() hides it. Lives in the base
    Screen, so a fifth screen gets the guarantee without opting in."""
    app = make_app()
    app.switch_to(name, **_entry_payload(name, tmp_path))
    screen = app.screens[name]
    hidden = []
    for spec in screen.modals():
        spec.obj.hide = lambda obj=spec.obj: hidden.append(obj)

    screen.exit()

    assert hidden == [spec.obj for spec in screen.modals()]
