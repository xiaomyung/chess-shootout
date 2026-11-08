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
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import Square
from chessshootout.frontend.screens.game import IdleWindow
from chessshootout.server.protocol import Reason
from chessshootout.frontend.window_chrome import WINDOW_FLAGS
from tests.helpers import key_event, make_app


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


# --- enter/exit idempotence -------------------------------------------------

@pytest.mark.parametrize("name", ["menu", "game", "review"])
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


def test_game_reenter_starts_from_a_clean_idle_window_baseline():
    """Enter always starts from a clean baseline (screen contract): an idle
    window surviving from a previous online game would paint a phantom
    Abort/Resign badge on the idler's strip and fold the heartbeat in the next
    game. _reset_to_new_game owns the clear, so every entry path gets it."""
    app = make_app()
    app.switch_to("game")
    app.game._idle_window = IdleWindow(Reason.ABORTED, PieceColor.WHITE, 60_000, 60.0)
    app.switch_to("menu")
    app.switch_to("game")
    assert app.game._idle_window is None


# --- nav matrix --------------------------------------------------------------

def _menu_game_menu(app, tmp_path, monkeypatch):
    app.switch_to("game")
    assert app.screen.name == "game"
    app.switch_to("menu")
    return "menu"


def _menu_history_review_menu(app, tmp_path, monkeypatch):
    app.menu.goto_history()
    assert app.menu._active_view == "history"
    pgn = _write_pgn(tmp_path)
    app.switch_to("review", pgn_path=str(pgn), return_to="menu")
    assert app.screen.name == "review"
    app.switch_to("menu")
    assert app.screen.name == "menu"
    assert app.menu._active_view == "history"
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
    pytest.param(_menu_history_review_menu, id="menu_history_review_menu"),
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

@pytest.mark.parametrize("name", ["menu", "game", "review"])
def test_handle_key_and_click_on_an_exited_inactive_screen_is_harmless(name, tmp_path):
    app = make_app()
    payload = _entry_payload(name, tmp_path)
    app.switch_to(name, **payload)
    screen = app.screens[name]

    other = "game" if name != "game" else "menu"
    app.switch_to(other)  # runs screen.exit(); screen is now inactive

    screen.handle_click((10, 10))
    screen.handle_key(key_event(pg.K_a, "a"))

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
    assert app.help_modal not in [spec.modal for spec in app._active_modal_specs()]


def test_help_modal_shown_on_review_is_not_drawn_after_switch_to_history(tmp_path):
    app = make_app()
    pgn = _write_pgn(tmp_path)
    app.switch_to("review", pgn_path=str(pgn), return_to="menu")
    app.help_modal.show([("Esc", "Back")])
    assert app.help_modal.is_visible() is True

    app.switch_to("menu")
    drawn = []
    app.help_modal.draw = lambda: drawn.append(1)
    app.draw_frame()

    assert drawn == []
    assert app.help_modal.is_visible() is False


# --- resize mid-anything ------------------------------------------------------

@pytest.mark.parametrize("name", ["menu", "game", "review"])
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
    app.switch_to("review", pgn_path=str(pgn), return_to="menu")
    app.review.handle_key(key_event(pg.K_RIGHT))
    assert app.review.board.is_animating()

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 900, "h": 700}))
    app.input_router.check_events()

    app.draw_frame()
    assert app.review.board.rect.width > 0


# --- minimize / restore mid-anything (Deck #96) ---------------------------------

ICONIC_SIZE = (160, 31)


class _SdlWindow:
    """Monkeypatched SDL view of the window. The dummy driver always reports an
    active window, so minimize has to be faked through get_active."""

    def __init__(self, monkeypatch, app):
        self.active = True
        self.size = app.window.get_size()
        monkeypatch.setattr(pg.display, "get_active", lambda: self.active)
        monkeypatch.setattr(pg.display, "get_window_size", lambda: self.size)
        monkeypatch.setattr(app.pacer, "wait", lambda: None)
        monkeypatch.setattr(app._idle_pacer, "wait", lambda: None)


def _minimize(app, sdl):
    restore_size = app.window.get_size()
    sdl.active = False
    sdl.size = ICONIC_SIZE
    app.window = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)
    app.chrome.window = app.window
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": ICONIC_SIZE[0], "h": ICONIC_SIZE[1]}))
    app._run_frame()
    app._run_frame()
    return restore_size


def _restore(app, sdl, size):
    sdl.active = True
    sdl.size = size
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": size[0], "h": size[1]}))
    app._run_frame()


def _assert_layout_sane(app):
    for screen in (app.game, app.review):
        for rect in (screen.board.rect, screen.right_menu.outer_rect,
                     screen.right_menu.moves_rect):
            assert rect.width > 0 and rect.height > 0, rect


@pytest.mark.parametrize("name", ["menu", "game", "review"])
def test_minimize_restore_while_screen_active_never_breaks_layout(
        name, tmp_path, monkeypatch):
    app = make_app()
    app.switch_to(name, **_entry_payload(name, tmp_path))
    sdl = _SdlWindow(monkeypatch, app)

    size = _minimize(app, sdl)
    _assert_layout_sane(app)
    app.draw_frame()

    _restore(app, sdl, size)
    assert app.window.get_size() == size
    assert (app.window_width, app.window_height) == size
    assert app._last_layout_size == size
    _assert_layout_sane(app)
    app.draw_frame()


def test_minimize_mid_focus_transition_aborts_it_and_restores_cleanly(monkeypatch):
    app = make_app()
    app.switch_to("game")
    app.game._toggle_focus(True)
    assert app.game.focus_transition is not None
    sdl = _SdlWindow(monkeypatch, app)

    size = _minimize(app, sdl)
    assert app.game.focus_transition is None
    _restore(app, sdl, size)

    assert app.game.focus_transition is None
    _assert_layout_sane(app)
    app.draw_frame()


def test_minimize_mid_board_drag_then_restore_does_not_crash(monkeypatch):
    app = make_app()
    app.switch_to("game")
    _start_board_drag(app.game.board, Square(6, 4))
    sdl = _SdlWindow(monkeypatch, app)

    size = _minimize(app, sdl)
    _restore(app, sdl, size)

    _assert_layout_sane(app)
    app.draw_frame()


def test_minimize_mid_review_animation_then_restore_does_not_crash(tmp_path, monkeypatch):
    app = make_app()
    app.switch_to("review", pgn_path=str(_write_pgn(tmp_path)), return_to="menu")
    app.review.handle_key(key_event(pg.K_RIGHT))
    assert app.review.board.is_animating()
    sdl = _SdlWindow(monkeypatch, app)

    size = _minimize(app, sdl)
    _restore(app, sdl, size)

    _assert_layout_sane(app)
    app.draw_frame()


def test_help_card_measured_while_minimized_is_remeasured_on_restore(monkeypatch):
    """The help card reads the live surface size, so the minimize relayout pins
    it to the iconic surface's corner; only the restore relayout puts it back,
    which is why the restore edge must relayout even at an unchanged size."""
    app = make_app()
    app.switch_to("game")
    sdl = _SdlWindow(monkeypatch, app)
    app.help_modal.show([])
    reference = app.help_modal.rect.copy()

    size = _minimize(app, sdl)
    assert app.help_modal.rect.topleft == (8, 8)
    _restore(app, sdl, size)

    assert app.help_modal.rect == reference
    app.draw_frame()


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
    app.switch_to("review", pgn_path=str(pgn), return_to="menu")
    app.help_modal.show([("Esc", "Back")])

    app.switch_to("menu")
    app.switch_to("review", pgn_path=str(pgn), return_to="menu")

    assert app.help_modal.is_visible() is False
    assert app._blocking_modal_visible() is False


def test_fen_input_left_open_on_the_menu_does_not_re_arm_on_the_next_menu():
    app = make_app()
    app.menu.fen_input_modal.show(on_submit=lambda text: True)

    app.switch_to("game")
    app.switch_to("menu")

    assert app.menu.fen_input_modal.is_visible() is False
    assert app._blocking_modal_visible() is False


@pytest.mark.parametrize("name", ["menu", "game", "review"])
def test_exit_hides_every_modal_the_screen_owns(name, tmp_path):
    """Whatever a screen returns from modals(), exit() hides it. Lives in the base
    Screen, so a fifth screen gets the guarantee without opting in."""
    app = make_app()
    app.switch_to(name, **_entry_payload(name, tmp_path))
    screen = app.screens[name]
    hidden = []
    for spec in screen.modals():
        spec.modal.hide = lambda obj=spec.modal: hidden.append(obj)

    screen.exit()

    assert hidden == [spec.modal for spec in screen.modals()]


# --- menu sub-view lifecycle (menu is now a shell hosting swappable views) ----

MENU_VIEWS = ["play", "battlepass", "armory", "social", "history", "profile", "options"]


@pytest.mark.parametrize("view", MENU_VIEWS)
def test_menu_subview_enter_exit_reenter_is_idempotent(view):
    app = make_app()
    app.menu.goto_view(view)
    assert app.menu._active_view == view

    app.menu.views[view].exit()
    app.menu.views[view].exit()  # double-exit must not raise

    app.menu.views[view].enter()
    app.draw_frame()  # still functional


def test_menu_subview_switching_matrix_draws_cleanly():
    app = make_app()
    for name in ("play", "history", "battlepass", "armory", "social", "profile",
                 "options", "history", "play"):
        app.menu.goto_view(name)
        assert app.menu._active_view == name
        app.draw_frame()


def test_menu_exit_hides_the_active_history_view():
    app = make_app()
    app.menu.goto_history()
    assert app.history_view.is_visible() is True

    app.switch_to("game")  # runs menu.exit()

    assert app.history_view.is_visible() is False


def test_menu_remembers_its_active_view_across_exit_and_reenter():
    app = make_app()
    app.menu.goto_history()

    app.switch_to("game")
    app.switch_to("menu")

    assert app.menu._active_view == "history"


@pytest.mark.parametrize("view", MENU_VIEWS)
def test_videoresize_while_a_menu_subview_is_active_recomputes_without_crash(view):
    app = make_app()
    app.menu.goto_view(view)
    w, h = app.window_width, app.window_height

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": w + 80, "h": h + 40}))
    app.input_router.check_events()

    assert (app.window_width, app.window_height) == (w + 80, h + 40)
    app.draw_frame()


@pytest.mark.parametrize("view", MENU_VIEWS)
def test_minimize_restore_while_a_menu_subview_is_active_draws_cleanly(view, monkeypatch):
    app = make_app()
    app.menu.goto_view(view)
    sdl = _SdlWindow(monkeypatch, app)

    size = _minimize(app, sdl)
    app.draw_frame()
    _restore(app, sdl, size)

    assert app._last_layout_size == size
    app.draw_frame()
