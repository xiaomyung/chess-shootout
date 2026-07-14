"""Menu rise-in motion (design lock #46): entering the menu screen (app start,
game -> menu return) rises the whole shell -- rail + active view + right rail --
~20px and fades in over ~260ms; a rail sub-view switch runs a lighter ~10px /
~140ms rise on the CONTENT layer only, leaving the left rail planted (its reticle
animates on its own). These pins nail the two behaviours apart at the pixel level,
prove the transition settles back to a byte-for-byte untweened draw, that
goto_view still arms the light transition even though it calls _compute_layout
mid-flight, and that exit()/resize leave nothing dangling.

The transition clock is pg.time.get_ticks(), frozen here through a mutable holder
so the eased progress is deterministic instead of wall-clock flaky.

The tween is armed by enter()/goto_view() but only STARTS on the first draw()
after arming: app startup burns hundreds of ms on asset loading between enter()
and the first presented frame, and an enter-anchored tween would finish before
anything became visible (the original user-reported symptom -- "it just
appears"). Anchoring on first-draw guarantees the rise is actually seen."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.screens.menu import MENU_RISE_MS, VIEW_RISE_MS
from chessshootout.frontend.visual.colors import Colors
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)


def _freeze(monkeypatch):
    holder = {"ms": 100_000}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: holder["ms"])
    return holder


def _draw_menu(app):
    app.window.fill((0, 0, 0))
    app.menu.draw()


def _active_row_probe(app, name):
    box = app.menu.rail._row_rects[name]
    return (box.x + 5, box.y + 5)


def test_enter_arms_a_screen_transition(monkeypatch):
    _freeze(monkeypatch)
    app = make_app()

    app.menu.enter()
    assert app.menu._transition_kind == "screen"
    assert app.menu._transition_tween is None, \
        "armed but not started -- the tween must anchor on the first draw, not on enter()"

    _draw_menu(app)
    assert app.menu._transition_tween is not None


def test_screen_transition_shifts_the_rail_but_a_view_switch_leaves_it_planted(monkeypatch):
    clock = _freeze(monkeypatch)
    app = make_app()
    raised = pg.Color(Colors.surface_raised)[:3]
    play_probe = _active_row_probe(app, "play")

    _draw_menu(app)
    final = app.window.get_at(play_probe)[:3]
    assert final == raised

    app.menu.enter()
    clock["ms"] += 20
    _draw_menu(app)
    assert app.window.get_at(play_probe)[:3] != final, \
        "screen-enter animates the rail with the content, so its pixel has moved/faded"

    clock["ms"] += MENU_RISE_MS
    _draw_menu(app)

    app.menu.goto_view("history")
    history_probe = _active_row_probe(app, "history")
    clock["ms"] += VIEW_RISE_MS // 2
    _draw_menu(app)
    assert app.window.get_at(history_probe)[:3] == raised, \
        "a view switch draws the rail straight to the window -- it never shifts or fades"


def test_transition_settles_to_the_untweened_draw(monkeypatch):
    clock = _freeze(monkeypatch)
    app = make_app()
    probe = _active_row_probe(app, "play")

    _draw_menu(app)
    untweened = app.window.get_at(probe)[:3]

    app.menu.enter()
    assert app.menu._transition_kind == "screen"
    _draw_menu(app)
    assert app.menu._transition_kind == "screen", \
        "the first draw starts the clock -- a long pre-frame gap must not swallow the rise"
    clock["ms"] += MENU_RISE_MS + 1
    _draw_menu(app)

    assert app.menu._transition_kind == "none", "the settling frame self-resets the transition"
    assert app.window.get_at(probe)[:3] == untweened


def test_goto_view_arms_the_light_transition_after_its_layout_pass(monkeypatch):
    _freeze(monkeypatch)
    app = make_app()
    assert app.menu._transition_kind == "none"

    app.menu.goto_view("history")

    assert app.menu._active_view == "history"
    assert app.menu._transition_kind == "view"


def test_exit_clears_the_transition_and_drops_the_scratch(monkeypatch):
    _freeze(monkeypatch)
    app = make_app()
    app.menu.enter()
    _draw_menu(app)
    assert app.menu._scratch is not None

    app.menu.exit()

    assert app.menu._transition_kind == "none"
    assert app.menu._transition_tween is None
    assert app.menu._scratch is None


def test_resize_mid_transition_does_not_crash():
    app = make_app()
    app.menu.enter()
    app.draw_frame()

    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 900, "h": 700}))
    app.input_router.check_events()
    app.draw_frame()

    app.menu.relayout((820, 640))
    app.menu.draw()
