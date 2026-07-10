"""The modal registry (Frontend._modal_registry) is the single ordered list that
now drives the click cascade, KEYDOWN forwarding, Esc-dismiss, the collapsed
_menu_overlay_active predicate, _active_scrollable, _cancel_all_scroll, and the
reversed modal draw order. This file pins two drift bugs the registry fixed
(confirm now outranks help for clicks/keys/Esc, matching its topmost draw
position) plus a sweep that exercises every registry entry through the same
generic surface.
"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

from chessshootout.frontend.frontend import Frontend


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _app():
    app = Frontend(1000, 800)
    app.draw_frame()
    return app


def _start_game(app):
    app._on_start_game({"mode": "single_screen", "nickname": "alice", "side": "white",
                        "time_minutes": 5, "increment_seconds": 0})
    app.draw_frame()
    return app


OPENERS = {
    "confirm_modal": lambda app: app.confirm_modal.show(
        "Sure?", on_yes=lambda: None, on_no=lambda: None),
    "help_modal": lambda app: app.help_modal.show(),
    "fen_input_modal": lambda app: app.fen_input_modal.show(on_submit=lambda t: True),
    "wait_modal": lambda app: app.wait_modal.show("Blitz", "5 + 0", on_cancel=lambda: None),
    "match_found_modal": lambda app: app.match_found_modal.show(
        "White", "Black", "white", on_done=lambda: None),
    "reconnecting_modal": lambda app: app.reconnecting_modal.show(0, on_cancel=lambda: None),
    "country_picker": lambda app: app.country_picker.show("US", lambda c: None),
    "directory_browser": lambda app: app.directory_browser.show(
        os.path.expanduser("~"), on_select=lambda p: None),
    "options_modal": lambda app: app.options_modal.show([], on_close=lambda: True),
}

MODAL_NAMES = list(OPENERS)

REGISTRY_PRIORITY_ORDER = [
    "confirm_modal", "help_modal", "fen_input_modal", "wait_modal",
    "match_found_modal", "reconnecting_modal", "country_picker",
    "directory_browser", "options_modal",
]

NON_DISMISSABLE = {"match_found_modal", "reconnecting_modal"}

ADJACENT_DISMISSABLE_PAIRS = [
    (a, b) for a, b in zip(REGISTRY_PRIORITY_ORDER, REGISTRY_PRIORITY_ORDER[1:])
    if a not in NON_DISMISSABLE and b not in NON_DISMISSABLE
]


def test_registry_priority_order():
    app = _app()
    names = [
        next(n for n in MODAL_NAMES if getattr(app, n) is spec.obj)
        for spec in app._modal_registry
    ]
    assert names == REGISTRY_PRIORITY_ORDER


def test_draw_order_is_the_exact_reverse_of_priority():
    app = _app()
    seen = []
    for spec in app._modal_registry:
        spec.obj.draw = lambda seen=seen, obj=spec.obj: seen.append(obj)
    app.draw_frame()
    assert seen == [spec.obj for spec in reversed(app._modal_registry)]


# ---- bug (a): promotion keys must not fire behind a blocking modal --------

def test_confirm_blocks_promotion_key_end_to_end():
    """Regression: Q used to reach _handle_promotion_key before the confirm-modal
    guard. A pending promotion behind an open confirm must be left untouched."""
    from chessshootout.backend.pieces import Piece, PieceColor, PieceType
    from chessshootout.backend.utils import Square
    from collections import Counter

    app = _app()
    app.skillcheck.enabled = False
    bk = app.backend
    bk.state = [[None] * 8 for _ in range(8)]
    bk.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    bk.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    bk.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    bk.turn = PieceColor.WHITE
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1
    src, dst = Square(1, 0), Square(0, 0)
    app.board.handle_click(src)
    app.board.handle_click(dst)
    if app.board.is_animating():
        for a in list(app.board.animations):
            a.start_ms = pg.time.get_ticks() - 10_000
        app.board._draw_animations()
    assert app.board.pending_promotion_square == dst

    app.confirm_modal.show("Tap out?", on_yes=lambda: None)
    history_before = list(app.match.move_history)

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_q, "unicode": "q", "mod": 0}))
    app.input_router.check_events()

    assert app.board.pending_promotion_square == dst
    assert app.match.move_history == history_before
    assert app.backend.state[dst.row][dst.col].type == PieceType.PAWN


# ---- bug (b): click priority must match draw priority (confirm on top) ----

def test_confirm_over_help_receives_the_click_help_stays_open_behind():
    """Regression: help/fen_input used to out-rank confirm in the click cascade
    even though confirm draws on top of them. A click on confirm's own button
    must land, and help (still open behind) must be untouched."""
    app = _start_game(_app())
    app.help_modal.show()
    app._on_resign()
    assert app.confirm_modal.is_visible() is True
    assert app.help_modal.is_visible() is True

    app.confirm_modal.draw()
    yes_rect = app.confirm_modal.button_rects["yes"]
    app.input_router.mouse_left_clicked(yes_rect.center)

    assert app.manual_result is not None
    assert app.confirm_modal.is_visible() is False
    assert app.help_modal.is_visible() is True


def test_esc_dismisses_confirm_before_help_when_both_open():
    app = _start_game(_app())
    app.help_modal.show()
    app._on_resign()
    assert app.confirm_modal.is_visible() is True
    assert app.help_modal.is_visible() is True

    app.input_router._handle_escape()

    assert app.confirm_modal.is_visible() is False
    assert app.help_modal.is_visible() is True


# ---- registry-driven equivalence sweep -------------------------------------

@pytest.mark.parametrize("name", MODAL_NAMES)
def test_show_makes_it_visible(name):
    app = _app()
    OPENERS[name](app)
    assert getattr(app, name).is_visible() is True


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_click_inside_is_consumed_never_reaches_the_board(name):
    app = _app()
    OPENERS[name](app)
    app.board.handle_click = MagicMock()
    spec = next(s for s in app._modal_registry if s.obj is getattr(app, name))
    app.input_router._dispatch_left_click(spec.obj.rect.center)
    app.board.handle_click.assert_not_called()


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_active_scrollable_matches_the_spec_flag(name):
    app = _app()
    OPENERS[name](app)
    spec = next(s for s in app._modal_registry if s.obj is getattr(app, name))
    if spec.scrollable:
        assert app.input_router._active_scrollable() is spec.obj
    else:
        assert app.input_router._active_scrollable() is None


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_cancel_all_scroll_stops_an_in_progress_grab(name):
    app = _app()
    OPENERS[name](app)
    spec = next(s for s in app._modal_registry if s.obj is getattr(app, name))
    if not spec.scrollable:
        pytest.skip(f"{name} is not a scrollable registry entry")
    spec.obj.scroll.handle_press(spec.obj.rect.center)
    app.input_router._cancel_all_scroll()
    assert spec.obj.scroll.is_active() is False


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_draw_frame_does_not_raise_with_this_modal_open(name):
    app = _app()
    OPENERS[name](app)
    app.draw_frame()
    if name == "reconnecting_modal":
        assert app.reconnecting_modal.is_visible() is False, (
            "_update_online_phase syncs it off outside an actual online "
            "reconnect (mode != ONLINE here) — a pre-existing behavior, not "
            "something the registry changed")
    else:
        assert getattr(app, name).is_visible() is True


@pytest.mark.parametrize("top_name, under_name", ADJACENT_DISMISSABLE_PAIRS)
def test_esc_dismisses_only_the_topmost_of_two_stacked(top_name, under_name):
    app = _app()
    OPENERS[under_name](app)
    OPENERS[top_name](app)
    assert getattr(app, top_name).is_visible() is True
    assert getattr(app, under_name).is_visible() is True

    app.input_router._handle_escape()

    assert getattr(app, top_name).is_visible() is False
    assert getattr(app, under_name).is_visible() is True


@pytest.mark.parametrize("name", sorted(NON_DISMISSABLE))
def test_esc_does_not_dismiss_non_dismissable_modals(name):
    app = _app()
    OPENERS[name](app)
    app.input_router._handle_escape()
    assert getattr(app, name).is_visible() is True
