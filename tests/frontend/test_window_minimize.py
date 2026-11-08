"""Minimize awareness in the shell's frame loop (Deck #96).

A minimized window keeps running the whole frame -- coordinator, screen,
animations -- but presents nothing and idles on a slow pacer. Coming back
always reconciles the surface with the real window and lays everything out
once more, and fullscreen never has its surface remade. A minimized flag that
never clears cannot freeze the window: input, or a window event only a
visible window gets, brings presenting back.

Under the dummy driver pg.display.get_active() is always True, so every test
here drives it through a monkeypatched module attribute, exactly the way
Frontend._window_minimized reads it.
"""

import logging

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.frontend.focus_helpers import FakeTicks, install_clock
from tests.helpers import make_app, start_single_screen
from chessshootout.backend.utils import Square
from chessshootout.frontend.frontend import MINIMIZED_TARGET_FPS
from chessshootout.frontend.window_chrome import (
    MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, WINDOW_FLAGS,
)


_pygame_init = pygame_display(1000, 800)

ICONIC_SIZE = (160, 31)


class _Window:
    """Switchable stand-in for SDL's view of the window: whether it is active
    and how big the system says it is."""

    def __init__(self, monkeypatch, size):
        self.active = True
        self.size = size
        monkeypatch.setattr(pg.display, "get_active", lambda: self.active)
        monkeypatch.setattr(pg.display, "get_window_size", lambda: self.size)


class _Presents:
    """Records every flip / partial update instead of touching the display."""

    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setattr(pg.display, "flip", lambda: self.calls.append("flip"))
        monkeypatch.setattr(pg.display, "update",
                            lambda rects=None: self.calls.append("update"))

    def take(self):
        calls, self.calls = self.calls, []
        return calls


@pytest.fixture
def window(monkeypatch):
    return _Window(monkeypatch, (1000, 800))


@pytest.fixture
def presents(monkeypatch):
    return _Presents(monkeypatch)


def _quiet_pacers(app, monkeypatch):
    waits = {"pacer": 0, "idle": 0}

    def _count(name):
        def _wait():
            waits[name] += 1
        return _wait

    monkeypatch.setattr(app.pacer, "wait", _count("pacer"))
    monkeypatch.setattr(app._idle_pacer, "wait", _count("idle"))
    return waits


def _iconify_surface(app):
    # pygame's own resize watch swaps the display surface to the iconic size
    # before any app code runs; set_mode is the closest the dummy driver gets.
    app.window = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)
    app.chrome.window = app.window


def _minimize(app, window):
    window.active = False
    window.size = ICONIC_SIZE
    _iconify_surface(app)
    pg.event.clear()
    pg.event.post(pg.event.Event(
        pg.VIDEORESIZE, {"w": ICONIC_SIZE[0], "h": ICONIC_SIZE[1], "size": ICONIC_SIZE}))
    app._run_frame()


def _booted(monkeypatch):
    app = make_app()
    pg.event.clear()
    waits = _quiet_pacers(app, monkeypatch)
    return app, waits


# --- the minimized frame ------------------------------------------------------

def test_idle_pacer_runs_at_the_minimized_rate():
    app = make_app()
    assert MINIMIZED_TARGET_FPS == 20
    assert app._idle_pacer.period == pytest.approx(1.0 / MINIMIZED_TARGET_FPS)
    assert app.pacer.period == pytest.approx(1.0 / app.target_fps)


def test_window_minimized_reads_the_live_sdl_flag(window):
    app = make_app()
    assert app._window_minimized() is False
    window.active = False
    assert app._window_minimized() is True


def test_minimized_frame_keeps_logic_running_but_skips_present(
        monkeypatch, window, presents):
    app, waits = _booted(monkeypatch)
    app._run_frame()
    presents.take()
    window.active = False
    order = []
    real_coord_update = app.coordinator.update
    real_screen_update = app.screen.update
    real_draw_frame = app.draw_frame
    monkeypatch.setattr(app.coordinator, "update",
                        lambda now: order.append("coordinator") or real_coord_update(now))
    monkeypatch.setattr(app.screen, "update",
                        lambda now: order.append("screen") or real_screen_update(now))
    monkeypatch.setattr(app, "draw_frame",
                        lambda: order.append("draw_frame") or real_draw_frame())
    monkeypatch.setattr(app.chrome, "draw", lambda stats: order.append("chrome"))
    frames_before = len(app._frame_times)
    waits["pacer"] = waits["idle"] = 0

    app._run_frame()

    assert order == ["draw_frame", "coordinator", "screen"]
    assert presents.take() == []
    assert waits == {"pacer": 0, "idle": 1}
    assert len(app._frame_times) == frames_before
    assert app._last_frame_start is None


def test_many_minimized_frames_never_present_and_never_feed_the_fps_readout(
        monkeypatch, window, presents):
    app, waits = _booted(monkeypatch)
    window.active = False
    app._run_frame()
    presents.take()
    for _ in range(25):
        app._run_frame()
    assert presents.take() == []
    assert waits["pacer"] == 0
    assert waits["idle"] == 26
    assert len(app._frame_times) == 0


def test_the_minimizing_frame_itself_still_presents_when_it_carried_events(
        monkeypatch, window, presents):
    """The iconic VIDEORESIZE is input like any other: that frame is presented
    (harmless, the layout is clamped) and the idle path starts on the next."""
    app, waits = _booted(monkeypatch)
    _minimize(app, window)
    assert presents.take() == ["flip"]
    assert waits == {"pacer": 1, "idle": 0}
    app._run_frame()
    assert presents.take() == []
    assert waits == {"pacer": 1, "idle": 1}


def test_minimized_frames_still_retire_board_animations(monkeypatch, window, presents):
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app = start_single_screen(make_app())
    _quiet_pacers(app, monkeypatch)
    pg.event.clear()
    app._run_frame()
    board = app.game.board
    landed = []
    board.start_animation(Square(6, 4), Square(4, 4),
                          app.game.match.piece_at(Square(6, 4)),
                          on_complete=lambda: landed.append(clock()))
    assert board.is_animating()
    window.active = False
    app._run_frame()
    assert app._minimized is True

    clock.advance(300)
    app._run_frame()

    assert not board.is_animating()
    assert landed == [clock()]
    assert board.last_animation_completed_at_ms == clock()
    assert presents.take() == ["flip"]


def test_minimized_frames_still_step_the_online_coordinator(monkeypatch, window, presents):
    """The heartbeat and watchdogs live in coordinator.update, so a minimized
    online game must keep calling it with the advancing clock."""
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app, _ = _booted(monkeypatch)
    window.active = False
    seen = []
    monkeypatch.setattr(app.coordinator, "update", seen.append)
    for _ in range(3):
        clock.advance(50)
        app._run_frame()
    assert seen == [clock() - 100, clock() - 50, clock()]


# --- the restore edge ---------------------------------------------------------

def test_restore_reconciles_surface_and_layout_to_the_real_window(
        monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    app._run_frame()
    assert app.window.get_size() == ICONIC_SIZE
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    presents.take()

    window.active = True
    window.size = (1100, 850)
    app._run_frame()

    assert app.window.get_size() == (1100, 850)
    assert (app.window_width, app.window_height) == (1100, 850)
    assert app._last_layout_size == (1100, 850)
    assert app._minimized is False
    assert presents.take() == ["flip"]


def test_restore_always_relays_out_once_even_at_the_same_size(
        monkeypatch, window, presents):
    """Cards that measure the live surface (help, the play popover) were laid
    out against the shrunken one, so an unchanged size is no excuse to skip."""
    app, _ = _booted(monkeypatch)
    size = app.window.get_size()
    window.active = False
    app._run_frame()
    app._run_frame()
    finishes = []
    resizes = []
    real_finish = app._finish_resize
    monkeypatch.setattr(app, "_finish_resize",
                        lambda w, h: finishes.append((w, h)) or real_finish(w, h))
    monkeypatch.setattr(app.screen, "on_resize", lambda: resizes.append(1))
    recreated = []
    monkeypatch.setattr(app, "_recreate_window_surface",
                        lambda w, h: recreated.append((w, h)))
    presents.take()

    window.active = True
    app._run_frame()

    assert finishes == [size]
    assert resizes == [1]
    assert recreated == []
    assert presents.take() == ["flip"]

    app._run_frame()
    assert finishes == [size]


def test_restore_reconcile_runs_before_the_frame_is_drawn(monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    window.active = True
    window.size = (1200, 900)
    seen = []
    real_draw = app.draw_frame
    monkeypatch.setattr(app, "draw_frame",
                        lambda: seen.append(app._last_layout_size) or real_draw())
    app._run_frame()
    assert seen == [(1200, 900)]


def test_restore_to_a_sub_minimum_window_clamps_the_surface(monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    window.active = True
    window.size = (400, 200)
    app._run_frame()
    assert app.window.get_size() == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_restore_prefers_the_os_client_size_over_sdl(monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    monkeypatch.setattr(app.chrome, "client_size", lambda: (1300, 950))
    window.active = True
    window.size = (1, 1)
    app._run_frame()
    assert app.window.get_size() == (1300, 950)


def test_fullscreen_restore_never_calls_set_mode(monkeypatch, window, presents):
    """set_mode with the borderless flags would silently drop fullscreen while
    the chrome still believes in it; restore must only relayout."""
    app, _ = _booted(monkeypatch)
    monkeypatch.setattr(app.chrome, "is_fullscreen", lambda: True)
    window.active = False
    app._run_frame()
    set_modes = []
    real_set_mode = pg.display.set_mode
    monkeypatch.setattr(pg.display, "set_mode",
                        lambda *a, **k: set_modes.append(a) or real_set_mode(*a, **k))
    finishes = []
    real_finish = app._finish_resize
    monkeypatch.setattr(app, "_finish_resize",
                        lambda w, h: finishes.append((w, h)) or real_finish(w, h))
    window.size = (1920, 1080)
    presents.take()

    window.active = True
    app._run_frame()

    assert set_modes == []
    assert finishes == [app.window.get_size()]
    assert presents.take() == ["flip"]


def test_fullscreen_restore_from_an_iconic_surface_lays_out_at_the_minimum(
        monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    monkeypatch.setattr(app.chrome, "is_fullscreen", lambda: True)
    window.active = False
    _iconify_surface(app)
    app._run_frame()
    window.active = True
    app._run_frame()
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_frame_stats_resume_cleanly_after_a_restore(monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    window.active = False
    for _ in range(5):
        app._run_frame()
    window.active = True
    app._run_frame()
    assert len(app._frame_times) == 0
    assert app._last_frame_start is not None
    app._run_frame()
    assert len(app._frame_times) == 1


# --- fail-safes against a flag that never clears -------------------------------

@pytest.mark.parametrize("wake_type", [
    pg.WINDOWEXPOSED, pg.WINDOWRESTORED, pg.WINDOWSHOWN, pg.WINDOWFOCUSGAINED,
], ids=["exposed", "restored", "shown", "focus_gained"])
def test_latched_minimized_flag_still_presents_after_a_wake_event(
        monkeypatch, window, presents, wake_type):
    app, waits = _booted(monkeypatch)
    window.active = False
    app._run_frame()
    app._run_frame()
    assert app._minimized is True
    presents.take()

    pg.event.post(pg.event.Event(wake_type, {}))
    app._run_frame()
    assert presents.take() == ["flip"]
    assert app._minimized is False

    app._run_frame()
    assert presents.take() == ["flip"]
    assert waits["idle"] == 2


@pytest.mark.parametrize("wake_type", [
    pg.WINDOWEXPOSED, pg.WINDOWRESTORED, pg.WINDOWSHOWN, pg.WINDOWFOCUSGAINED,
], ids=["exposed", "restored", "shown", "focus_gained"])
def test_a_wake_from_an_iconic_surface_rebuilds_surface_and_layout(
        monkeypatch, window, presents, wake_type):
    """REGRESSION: the wake fail-safe only switched presenting back on, so a
    window whose flag stayed latched kept the iconic surface and the
    minimum-size layout for the rest of the session. A wake now reconciles
    exactly like a real restore edge."""
    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    app._run_frame()
    assert app.window.get_size() == ICONIC_SIZE
    presents.take()

    window.size = (1100, 850)
    pg.event.post(pg.event.Event(wake_type, {}))
    app._run_frame()

    assert window.active is False, "the system flag is still latched"
    assert app.window.get_size() == (1100, 850)
    assert (app.window_width, app.window_height) == (1100, 850)
    assert app._last_layout_size == (1100, 850)
    assert app._minimized is False
    assert presents.take() == ["flip"]


def test_a_woken_window_keeps_following_resizes_on_windows(monkeypatch, window, presents):
    """After a wake the stuck flag no longer gates the surface: on Windows a
    resize event remakes it and the per-frame edge-drag sync follows the real
    window again, while the flag still reads minimized."""
    from types import SimpleNamespace

    from chessshootout.frontend import frontend as frontend_module

    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    window.size = (1100, 850)
    pg.event.post(pg.event.Event(pg.WINDOWRESTORED, {}))
    app._run_frame()
    assert app.window.get_size() == (1100, 850)

    recreated = []
    monkeypatch.setattr(app, "_recreate_window_surface",
                        lambda w, h: recreated.append((w, h)))
    real_os = frontend_module.os
    monkeypatch.setattr(frontend_module, "os", SimpleNamespace(name="nt", environ={}))
    app._on_videoresize(1200, 900)
    window.size = (1300, 950)
    app._sync_window_surface()
    monkeypatch.setattr(frontend_module, "os", real_os)

    assert window.active is False
    assert recreated == [(1200, 900), (1300, 950)]
    assert (app.window_width, app.window_height) == (1300, 950)


def test_a_new_minimize_after_a_wake_stops_the_surface_following_again(
        monkeypatch, window, presents):
    """The wake only lasts until the next real minimize edge: from then on a
    resize is a minimized one again and never remakes the surface."""
    app, _ = _booted(monkeypatch)
    window.active = False
    app._run_frame()
    pg.event.post(pg.event.Event(pg.WINDOWEXPOSED, {}))
    app._run_frame()
    assert app._effectively_minimized() is False
    window.active = True
    app._run_frame()
    window.active = False
    app._run_frame()
    assert app._effectively_minimized() is True
    recreated = []
    monkeypatch.setattr(app, "_recreate_window_surface",
                        lambda w, h: recreated.append((w, h)))
    app._on_videoresize(*ICONIC_SIZE)
    assert recreated == []


def test_a_restore_whose_wake_event_lands_in_the_same_frame_reconciles_once(
        monkeypatch, window, presents):
    """A real restore delivers WINDOWRESTORED in the very frame get_active()
    flips back. The wake path defers to the per-frame edge check when the flag
    has already cleared, so the window is laid out once, not twice."""
    app, _ = _booted(monkeypatch)
    _minimize(app, window)
    app._run_frame()
    finishes = []
    real_finish = app._finish_resize
    monkeypatch.setattr(app, "_finish_resize",
                        lambda w, h: finishes.append((w, h)) or real_finish(w, h))
    presents.take()

    window.active = True
    window.size = (1100, 850)
    pg.event.post(pg.event.Event(pg.WINDOWRESTORED, {}))
    app._run_frame()

    assert finishes == [(1100, 850)]
    assert app.window.get_size() == (1100, 850)
    assert app._minimized is False
    assert app._woke is False
    assert presents.take() == ["flip"]


def test_a_wake_event_on_a_visible_window_changes_nothing(monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    pg.event.post(pg.event.Event(pg.WINDOWFOCUSGAINED, {}))
    app._run_frame()
    assert app._minimized is False
    assert presents.take() == ["flip"]


def test_input_while_reported_minimized_is_presented(monkeypatch, window, presents):
    app, waits = _booted(monkeypatch)
    window.active = False
    app._run_frame()
    app._run_frame()
    presents.take()
    pg.event.post(pg.event.Event(pg.MOUSEMOTION, {
        "pos": (5, 200), "rel": (1, 1), "buttons": (0, 0, 0)}))
    app._run_frame()
    assert presents.take() == ["flip"]
    assert app._minimized is True
    app._run_frame()
    assert presents.take() == []


def test_a_new_minimize_after_a_wake_suppresses_presenting_again(
        monkeypatch, window, presents):
    app, _ = _booted(monkeypatch)
    window.active = False
    app._run_frame()
    pg.event.post(pg.event.Event(pg.WINDOWEXPOSED, {}))
    app._run_frame()
    window.active = True
    app._run_frame()
    window.active = False
    app._run_frame()
    presents.take()
    app._run_frame()
    assert presents.take() == []


def test_videoresize_while_minimized_never_remakes_the_surface(monkeypatch, window):
    """set_mode cannot grow an iconic window and may clobber its restore size,
    so a minimized resize only relayouts against the clamped size."""
    app, _ = _booted(monkeypatch)
    window.active = False
    _iconify_surface(app)
    recreated = []
    monkeypatch.setattr(app, "_recreate_window_surface",
                        lambda w, h: recreated.append((w, h)))
    pg.event.post(pg.event.Event(
        pg.VIDEORESIZE, {"w": ICONIC_SIZE[0], "h": ICONIC_SIZE[1], "size": ICONIC_SIZE}))

    app.input_router.check_events()

    assert recreated == []
    assert app.window.get_size() == ICONIC_SIZE
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


# --- logging --------------------------------------------------------------------

def test_minimize_and_restore_log_once_per_edge_at_debug(monkeypatch, window, presents, caplog):
    app, _ = _booted(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="chess.frontend"):
        window.active = False
        for _ in range(10):
            app._run_frame()
        window.active = True
        for _ in range(10):
            app._run_frame()
    edges = [r for r in caplog.records
             if r.getMessage().startswith(("window minimized", "window restored"))]
    assert [r.getMessage() for r in edges] == [
        "window minimized", "window restored size=1000x800"]
    assert all(r.levelno == logging.DEBUG for r in edges)


# --- the loop ---------------------------------------------------------------------

def test_run_drives_run_frame_until_the_player_quits(monkeypatch):
    app = make_app()
    frames = []

    def _frame():
        frames.append(1)
        if len(frames) == 3:
            app.running = False

    monkeypatch.setattr(app, "_run_frame", _frame)
    monkeypatch.setattr(pg, "quit", lambda: None)
    exits = []
    monkeypatch.setattr(app.coordinator, "on_app_exit", lambda: exits.append(1))
    app.run()
    assert frames == [1, 1, 1]
    assert exits == [1]
