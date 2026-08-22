"""The modal system is now two-tier: Frontend._modal_registry holds the GLOBAL
modals (confirm, wait/match_found/reconnecting, country_picker, directory_browser);
each screen additionally owns its own modals() (menu: fen_input, game/review:
help). Frontend._active_modal_specs() merges global ∪ the
active screen's modals(), global first, and that merged, ordered list drives
the click cascade, KEYDOWN forwarding, Esc-dismiss, _blocking_modal_visible,
_active_scrollable, and the reversed draw order. This file pins two drift bugs
the registry fixed (confirm now outranks help for clicks/keys/Esc, matching its
topmost draw position), a third one dismiss_topmost itself carried (Esc used to
reach past an esc_dismiss=False card to whatever sat underneath it), a sweep
that exercises every registry entry through the same generic surface, and the
screen-ownership behaviors from the split: a menu-owned modal left open doesn't
gate the game screen, and a screen's own modal stops being active
(drawn/dismissable) once its screen is inactive.
"""

import os
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.modal_registry import dismiss_topmost
from chessshootout.frontend.modals.help import HOTKEYS
from tests.helpers import make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)


def _app():
    app = make_app(1000, 800, mock_sound=False)
    app.draw_frame()
    return app


def _start_game(app):
    start_single_screen(app)
    app.draw_frame()
    return app


def _open_help(app):
    if app.screen is not app.game:
        _start_game(app)
    app.help_modal.show(HOTKEYS)


OPENERS = {
    "confirm_modal": lambda app: app.confirm_modal.show(
        "Sure?", on_yes=lambda: None, on_no=lambda: None),
    "help_modal": _open_help,
    "fen_input_modal": lambda app: app.menu.fen_input_modal.show(on_submit=lambda t: True),
    "wait_modal": lambda app: app.coordinator.wait_modal.show(
        "Blitz", "5 + 0", on_cancel=lambda: None),
    "match_found_modal": lambda app: app.coordinator.match_found_modal.show(
        "White", "Black", "white", on_done=lambda: None),
    "reconnecting_modal": lambda app: app.coordinator.reconnecting_modal.show(
        0, on_abandon=lambda: None),
    "country_picker": lambda app: app.country_picker.show("US", lambda c: None),
    "directory_browser": lambda app: app.directory_browser.show(
        os.path.expanduser("~"), on_select=lambda p: None),
}

MODAL_NAMES = list(OPENERS)

GLOBAL_PRIORITY_ORDER = [
    "confirm_modal", "wait_modal", "match_found_modal", "reconnecting_modal",
    "country_picker", "directory_browser",
]

NON_DISMISSABLE = {"match_found_modal", "reconnecting_modal"}

COORDINATOR_MODALS = {"wait_modal", "match_found_modal", "reconnecting_modal"}
MENU_MODALS = {"fen_input_modal"}
GAME_MODALS = {"help_modal"}


def _modal(app, name):
    if name in COORDINATOR_MODALS:
        return getattr(app.coordinator, name)
    if name in MENU_MODALS:
        return getattr(app.menu, name)
    return getattr(app, name)


ADJACENT_GLOBAL_PAIRS = [
    (a, b) for a, b in zip(GLOBAL_PRIORITY_ORDER, GLOBAL_PRIORITY_ORDER[1:])
    if a not in NON_DISMISSABLE and b not in NON_DISMISSABLE
]

BLOCKING_OVER_DISMISSABLE_PAIRS = [
    (top, under)
    for i, top in enumerate(GLOBAL_PRIORITY_ORDER) if top in NON_DISMISSABLE
    for under in GLOBAL_PRIORITY_ORDER[i + 1:] if under not in NON_DISMISSABLE
]

DISMISSABLE_OVER_BLOCKING_PAIRS = [
    (top, under)
    for i, top in enumerate(GLOBAL_PRIORITY_ORDER) if top == "confirm_modal"
    for under in GLOBAL_PRIORITY_ORDER[i + 1:] if under in NON_DISMISSABLE
]

BELOW_EVERY_BLOCKER = sorted({under for _, under in BLOCKING_OVER_DISMISSABLE_PAIRS})


def test_registry_priority_order():
    app = _app()
    names = [
        next(n for n in GLOBAL_PRIORITY_ORDER if _modal(app, n) is spec.modal)
        for spec in app._modal_registry
    ]
    assert names == GLOBAL_PRIORITY_ORDER


def test_menu_screen_modals_follow_global_in_active_specs():
    app = _app()
    assert app.screen is app.menu
    specs = app._active_modal_specs()
    tail = [spec.modal for spec in specs[len(GLOBAL_PRIORITY_ORDER):]]
    assert tail == [app.menu.fen_input_modal]


def test_game_screen_modals_follow_global_in_active_specs():
    app = _start_game(_app())
    specs = app._active_modal_specs()
    tail = [spec.modal for spec in specs[len(GLOBAL_PRIORITY_ORDER):]]
    assert tail == [app.help_modal]


def test_draw_order_is_the_exact_reverse_of_priority():
    app = _app()
    seen = []
    for spec in app._active_modal_specs():
        spec.modal.draw = lambda seen=seen, obj=spec.modal: seen.append(obj)
    app.draw_frame()
    assert seen == [spec.modal for spec in reversed(app._active_modal_specs())]


def test_confirm_blocks_promotion_key_end_to_end():
    """Regression: Q used to reach _handle_promotion_key before the confirm-modal
    guard. A pending promotion behind an open confirm must be left untouched."""
    from chessshootout.backend.pieces import Piece, PieceColor, PieceType
    from chessshootout.backend.utils import Square
    from collections import Counter

    app = _app()
    app.game.skillcheck.enabled = False
    bk = app.game.match.backend
    bk.state = [[None] * 8 for _ in range(8)]
    bk.state[1][0] = Piece(PieceType.PAWN, PieceColor.WHITE)
    bk.state[7][7] = Piece(PieceType.KING, PieceColor.WHITE)
    bk.state[0][7] = Piece(PieceType.KING, PieceColor.BLACK)
    bk.turn = PieceColor.WHITE
    bk.move_history = []
    bk.position_counts = Counter()
    bk.position_counts[bk._position_key()] = 1
    src, dst = Square(1, 0), Square(0, 0)
    app.game.board.handle_click(src)
    app.game.board.handle_click(dst)
    if app.game.board.is_animating():
        for a in list(app.game.board.animations):
            a.start_ms = pg.time.get_ticks() - 10_000
        app.game.board._draw_animations()
    assert app.game.board.pending_promotion_square == dst

    app.confirm_modal.show("Tap out?", on_yes=lambda: None)
    history_before = list(app.game.match.move_history)

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.KEYDOWN, {"key": pg.K_q, "unicode": "q", "mod": 0}))
    app.input_router.check_events()

    assert app.game.board.pending_promotion_square == dst
    assert app.game.match.move_history == history_before
    assert app.game.match.backend.state[dst.row][dst.col].type == PieceType.PAWN


def test_confirm_over_help_receives_the_click_help_stays_open_behind():
    """Regression: help/fen_input used to out-rank confirm in the click cascade
    even though confirm draws on top of them. A click on confirm's own button
    must land, and help (still open behind) must be untouched."""
    app = _start_game(_app())
    app.help_modal.show(HOTKEYS)
    app.game._on_resign()
    assert app.confirm_modal.is_visible() is True
    assert app.help_modal.is_visible() is True

    app.confirm_modal.draw()
    yes_rect = app.confirm_modal.button_rects["yes"]
    app.input_router.mouse_left_clicked(yes_rect.center)

    assert app.game.manual_result is not None
    assert app.confirm_modal.is_visible() is False
    assert app.help_modal.is_visible() is True


def test_esc_dismisses_confirm_before_help_when_both_open():
    app = _start_game(_app())
    app.help_modal.show(HOTKEYS)
    app.game._on_resign()
    assert app.confirm_modal.is_visible() is True
    assert app.help_modal.is_visible() is True

    app.input_router._handle_escape()

    assert app.confirm_modal.is_visible() is False
    assert app.help_modal.is_visible() is True


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_show_makes_it_visible(name):
    app = _app()
    OPENERS[name](app)
    assert _modal(app, name).is_visible() is True


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_click_inside_is_consumed_never_reaches_the_board(name):
    app = _app()
    OPENERS[name](app)
    app.game.board.handle_click = MagicMock()
    spec = next(s for s in app._active_modal_specs() if s.modal is _modal(app, name))
    app.input_router._dispatch_left_click(spec.modal.rect.center)
    app.game.board.handle_click.assert_not_called()


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_active_scrollable_matches_the_spec_flag(name):
    app = _app()
    OPENERS[name](app)
    spec = next(s for s in app._active_modal_specs() if s.modal is _modal(app, name))
    if spec.scrollable:
        assert app.input_router._active_scrollable() is spec.modal
    else:
        assert app.input_router._active_scrollable() is None


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_cancel_all_scroll_stops_an_in_progress_grab(name):
    app = _app()
    OPENERS[name](app)
    spec = next(s for s in app._active_modal_specs() if s.modal is _modal(app, name))
    if not spec.scrollable:
        pytest.skip(f"{name} is not a scrollable registry entry")
    spec.modal.scroll.handle_press(spec.modal.rect.center)
    app.input_router._cancel_all_scroll()
    assert spec.modal.scroll.is_active() is False


@pytest.mark.parametrize("name", MODAL_NAMES)
def test_draw_frame_does_not_raise_with_this_modal_open(name):
    app = _app()
    OPENERS[name](app)
    app.draw_frame()
    if name == "reconnecting_modal":
        assert app.coordinator.reconnecting_modal.is_visible() is False, (
            "_update_online_phase syncs it off outside an actual online "
            "reconnect (variant != online here) — a pre-existing behavior, "
            "not something the registry changed")
    else:
        assert _modal(app, name).is_visible() is True


@pytest.mark.parametrize("top_name, under_name", ADJACENT_GLOBAL_PAIRS)
def test_esc_dismisses_only_the_topmost_of_two_stacked_global_modals(top_name, under_name):
    app = _app()
    OPENERS[under_name](app)
    OPENERS[top_name](app)
    assert _modal(app, top_name).is_visible() is True
    assert _modal(app, under_name).is_visible() is True

    app.input_router._handle_escape()

    assert _modal(app, top_name).is_visible() is False
    assert _modal(app, under_name).is_visible() is True


@pytest.mark.parametrize("name", sorted(NON_DISMISSABLE))
def test_esc_does_not_dismiss_non_dismissable_modals(name):
    """The blocking cards refuse Esc outright but still swallow it: dismiss_topmost
    reports True so the router lets Esc go no further while the card is up."""
    app = _app()
    OPENERS[name](app)
    assert dismiss_topmost(app._active_modal_specs()) is True
    app.input_router._handle_escape()
    assert _modal(app, name).is_visible() is True


@pytest.mark.parametrize("top_name, under_name", BLOCKING_OVER_DISMISSABLE_PAIRS)
def test_esc_dismisses_nothing_when_the_topmost_visible_modal_blocks_it(top_name, under_name):
    """Regression: dismiss_topmost used to step over an esc_dismiss=False spec and
    keep scanning, so Esc reached a dismissable card stacked *underneath* a
    blocking one and cancelled it invisibly. The topmost visible modal decides
    alone: when it refuses Esc, nothing below it closes either, and the press
    is consumed rather than falling through to the screen."""
    app = _app()
    OPENERS[under_name](app)
    OPENERS[top_name](app)
    assert _modal(app, top_name).is_visible() is True
    assert _modal(app, under_name).is_visible() is True

    assert dismiss_topmost(app._active_modal_specs()) is True
    app.input_router._handle_escape()

    assert _modal(app, top_name).is_visible() is True
    assert _modal(app, under_name).is_visible() is True


def test_esc_under_a_blocking_modal_never_reaches_the_screen():
    """A blocking card must swallow Esc entirely: while the reconnecting modal
    covers a live game, Esc may not fall through to GameScreen.escape() and
    open the resign confirmation underneath the overlay."""
    app = _app()
    _start_game(app)
    OPENERS["reconnecting_modal"](app)
    app.input_router._handle_escape()
    assert app.coordinator.reconnecting_modal.is_visible() is True
    assert app.confirm_modal.is_visible() is False


@pytest.mark.parametrize("top_name, under_name", DISMISSABLE_OVER_BLOCKING_PAIRS)
def test_esc_dismisses_a_dismissable_modal_stacked_over_a_blocking_one(top_name, under_name):
    """The mirror of the regression above: a blocking card only shields what is
    below it, never what draws on top of it, so confirm still answers Esc while
    match-found or reconnecting sits behind it and that card stays put."""
    app = _app()
    OPENERS[under_name](app)
    OPENERS[top_name](app)
    assert _modal(app, top_name).is_visible() is True

    app.input_router._handle_escape()

    assert _modal(app, top_name).is_visible() is False
    assert _modal(app, under_name).is_visible() is True


@pytest.mark.parametrize("name", BELOW_EVERY_BLOCKER)
def test_hidden_blocking_modals_never_shield_the_card_below_them(name):
    """A blocking spec only owns Esc while it is actually on screen -- hidden ones
    are skipped entirely by the scan. Both blockers outrank these entries in the
    registry, so stopping at a hidden one would leave every card below
    match-found permanently undismissable."""
    app = _app()
    OPENERS[name](app)
    assert [b for b in sorted(NON_DISMISSABLE) if _modal(app, b).is_visible()] == []
    assert _modal(app, name).is_visible() is True

    app.input_router._handle_escape()

    assert _modal(app, name).is_visible() is False


def test_menu_owned_modal_left_open_does_not_gate_the_game_screen():
    """D: a menu-owned modal (fen_input) left open must not block/gate game-screen
    behavior once the app has switched screens — MenuScreen.exit() hides its own
    modals, and only the active screen's modals() are merged into the blocking
    predicate anyway."""
    app = _app()
    app.menu.fen_input_modal.show(on_submit=lambda t: True)
    assert app.menu.fen_input_modal.is_visible() is True
    _start_game(app)
    assert app.screen is app.game
    assert app.menu.fen_input_modal.is_visible() is False
    assert app._blocking_modal_visible() is False
    before = list(app.game.match.move_history)
    from chessshootout.backend.utils import Square
    app.game.board.handle_click(Square(6, 4))
    app.game.board.handle_click(Square(4, 4))
    assert app.game.match.move_history != before


def test_inactive_screens_modals_are_excluded_from_active_specs():
    """D: screen-owned modals stop drawing/dismissing once their screen isn't
    the active one — the merge only pulls in app.screen.modals(). Leaving the
    menu screen both hides fen_input (exit()) and drops it from the merged
    draw/dismiss list; help_modal only enters that list once the game screen is
    the active one."""
    app = _app()
    app.menu.fen_input_modal.show(on_submit=lambda t: True)
    specs_objs_before = [spec.modal for spec in app._active_modal_specs()]
    assert app.menu.fen_input_modal in specs_objs_before
    assert app.help_modal not in specs_objs_before

    _start_game(app)
    assert app.menu.fen_input_modal.is_visible() is False
    specs_objs_after = [spec.modal for spec in app._active_modal_specs()]
    assert app.menu.fen_input_modal not in specs_objs_after
    assert app.help_modal in specs_objs_after
