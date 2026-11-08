"""Window-size clamping: the same MIN_WINDOW_* floor governs both construction
(``Frontend.__init__``) and live ``pg.VIDEORESIZE`` events. Undersized inputs are
raised to the floor; adequate inputs pass through untouched; one dimension can clamp
while the other does not."""

import types

import pygame as pg
import pytest

from tests.conftest import pygame_display
from tests.helpers import make_app, start_single_screen
from chessshootout.infra import env
from chessshootout.frontend.frontend import Frontend, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
from chessshootout.frontend.visual import cache
from chessshootout.frontend.window_chrome import WINDOW_FLAGS


_pygame_init = pygame_display(1000, 800)


@pytest.mark.parametrize(
    "req_w, req_h, exp_w, exp_h",
    [
        pytest.param(
            MIN_WINDOW_WIDTH - 100, 600, MIN_WINDOW_WIDTH, 600,
            id="width_only_clamps",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH - 100, MIN_WINDOW_HEIGHT - 100,
            MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
            id="both_dims_clamp",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
            MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
            id="at_minimum_no_clamp",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH + 200, MIN_WINDOW_HEIGHT + 300,
            MIN_WINDOW_WIDTH + 200, MIN_WINDOW_HEIGHT + 300,
            id="above_minimum_no_clamp",
        ),
    ],
)
def test_construction_clamps_to_minimum(req_w, req_h, exp_w, exp_h):
    app = Frontend(req_w, req_h)
    assert app.window_width == exp_w
    assert app.window_height == exp_h


def test_construction_display_surface_meets_minimum():
    Frontend(600, 300)
    surface = pg.display.get_surface()
    w, h = surface.get_size()
    assert w >= MIN_WINDOW_WIDTH
    assert h >= MIN_WINDOW_HEIGHT


@pytest.mark.parametrize(
    "ev_w, ev_h, exp_w, exp_h",
    [
        pytest.param(600, 300, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT, id="too_small_both_clamp"),
        pytest.param(
            MIN_WINDOW_WIDTH + 50, MIN_WINDOW_HEIGHT + 100,
            MIN_WINDOW_WIDTH + 50, MIN_WINDOW_HEIGHT + 100,
            id="adequate_passes_through",
        ),
        pytest.param(
            MIN_WINDOW_WIDTH + 50, 200,
            MIN_WINDOW_WIDTH + 50, MIN_WINDOW_HEIGHT,
            id="partial_clamp_only_height",
        ),
    ],
)
def test_videoresize_clamps_to_minimum(ev_w, ev_h, exp_w, exp_h):
    """A VIDEORESIZE event is clamped to MIN_WINDOW_WIDTH/HEIGHT; the too-small
    case proves the module constants are the real floor wired into the handler."""
    app = Frontend(MIN_WINDOW_WIDTH + 100, MIN_WINDOW_HEIGHT + 200)
    event = pg.event.Event(pg.VIDEORESIZE, {"w": ev_w, "h": ev_h, "size": (ev_w, ev_h)})
    pg.event.post(event)
    app.input_router.check_events()
    assert app.window_width == exp_w
    assert app.window_height == exp_h


def test_videoresize_goes_through_the_shell_resize_entry_point(monkeypatch):
    """The router owns no resize sequence of its own: a VIDEORESIZE hands the
    clamped size to the same _finish_resize the Windows edge-drag sync uses, so
    the two paths cannot drift on what settling a resize means."""
    app = Frontend(1000, 800)
    calls = []
    real_finish = app._finish_resize
    monkeypatch.setattr(app, "_finish_resize",
                        lambda w, h: calls.append((w, h)) or real_finish(w, h))
    new_w, new_h = MIN_WINDOW_WIDTH + 120, MIN_WINDOW_HEIGHT + 60
    pg.event.post(pg.event.Event(
        pg.VIDEORESIZE, {"w": new_w, "h": new_h, "size": (new_w, new_h)}))

    app.input_router.check_events()

    assert calls == [(new_w, new_h)]
    assert (app.window_width, app.window_height) == (new_w, new_h)


def test_videoresize_still_tells_the_active_screen_before_laying_out(monkeypatch):
    """A screen animating snapshots of the old surface has to hear about the new
    one before anything is measured against it, so on_resize stays ahead of the
    layout pass however the resize arrived."""
    app = Frontend(1000, 800)
    order = []
    monkeypatch.setattr(app.screen, "on_resize", lambda: order.append("on_resize"))
    monkeypatch.setattr(app, "_compute_layout", lambda: order.append("layout"))
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 1100, "h": 850, "size": (1100, 850)}))

    app.input_router.check_events()

    assert order == ["on_resize", "layout"]


def test_sync_reallocates_surface_when_os_window_grew(monkeypatch):
    """The Windows fix: when the OS reports a larger window than the current
    surface (native maximize / edge-drag), _sync_window_surface re-set_modes so
    the surface matches (else content renders small with black/striped margins)."""
    app = Frontend(1000, 800)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: (1400, 900))
    app._sync_window_surface()
    assert app.window.get_size() == (1400, 900)
    assert (app.window_width, app.window_height) == (1400, 900)


def test_sync_is_noop_when_surface_already_matches(monkeypatch):
    app = Frontend(1000, 800)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: app.window.get_size())
    calls = []
    monkeypatch.setattr(app, "_compute_layout", lambda: calls.append(1))
    app._sync_window_surface()
    assert calls == []


def test_sync_clamps_reported_size_to_minimum(monkeypatch):
    app = Frontend(1000, 800)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: (200, 150))
    app._sync_window_surface()
    assert app.window.get_size() == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


@pytest.mark.parametrize(
    "mode, expected",
    [
        pytest.param("fullscreen", ["fullscreen"], id="fullscreen_reuses_f11_toggle"),
        pytest.param("maximized", ["maximize"], id="maximized_calls_maximizer"),
        pytest.param("windowed", [], id="windowed_touches_neither"),
    ],
)
def test_boot_launch_mode_dispatch(monkeypatch, mode, expected):
    """CHESS_LAUNCH_MODE drives the one-shot boot dispatch: fullscreen goes through
    the same chrome.toggle_fullscreen path F11 uses (so state stays consistent),
    maximized asks the maximizer, windowed does nothing."""
    app = Frontend(1000, 800)
    calls = []
    monkeypatch.setattr(app.chrome, "toggle_fullscreen", lambda: calls.append("fullscreen"))
    monkeypatch.setattr(app, "_maximize_window", lambda: calls.append("maximize"))
    monkeypatch.setattr(env, "get_launch_mode", lambda: mode)
    app._apply_launch_mode()
    assert calls == expected


def test_maximize_window_falls_back_to_desktop_size(monkeypatch):
    """Maximize goes through chrome's ctypes SDL channel (a second
    Window.from_display_module wrapper corrupted the SDL window and
    segfaulted on drag-unmaximize). When chrome reports failure, the
    maximizer falls back to re-set_mode at the largest desktop size."""
    app = Frontend(1000, 800)
    monkeypatch.setattr(app.chrome, "maximize", lambda: False)
    monkeypatch.setattr(pg.display, "get_desktop_sizes", lambda: [(2560, 1440)])
    app._maximize_window()
    assert app.window.get_size() == (2560, 1440)
    assert (app.window_width, app.window_height) == (2560, 1440)


def test_maximize_window_uses_chrome_sdl_channel(monkeypatch):
    """Success path: chrome.maximize() is the ONLY maximize mechanism —
    no pygame._sdl2 Window wrapper may be created for it."""
    app = Frontend(1000, 800)
    calls = []
    monkeypatch.setattr(app.chrome, "maximize", lambda: calls.append("max") or True)
    app._maximize_window()
    assert calls == ["max"]
    assert app.window.get_size() == (1000, 800)


class _MaximizingChrome:
    """A chrome whose native maximize succeeds and whose client_size() reports the
    grown OS window (as WindowsSnap does via GetClientRect)."""

    def __init__(self, client_size):
        self.window = None
        self._client_size = client_size

    def maximize(self):
        return True

    def client_size(self):
        return self._client_size

    def reinit_sdl(self):
        pass


def test_maximize_launch_adopts_real_client_size_and_settle_keeps_it(monkeypatch):
    """Maximized launch on Windows: chrome.maximize() succeeds and the OS grows the
    window past the constructor size. The maximizer must adopt that real client size
    into surface + dims + layout, and the subsequent _settle_window pass must NOT
    shrink it back to the stale constructor size (the reported launch-mode bug)."""
    app = Frontend(1000, 800)
    app.chrome = _MaximizingChrome((1400, 900))

    app._maximize_window()
    assert app.window.get_size() == (1400, 900)
    assert (app.window_width, app.window_height) == (1400, 900)
    assert app._last_layout_size == (1400, 900)

    recreated = []
    real_recreate = app._recreate_window_surface

    def spy_recreate(w, h):
        recreated.append((w, h))
        real_recreate(w, h)

    monkeypatch.setattr(app, "_recreate_window_surface", spy_recreate)
    monkeypatch.setattr("chessshootout.frontend.frontend.os", types.SimpleNamespace(name="nt"))
    app._settle_window()
    assert recreated == [(1400, 900)], "settle must re-set_mode at the maximized size, not shrink"
    assert app.window.get_size() == (1400, 900)
    assert (app.window_width, app.window_height) == (1400, 900)


# --- Deck #96: a minimized window must never reach the layout ------------------

ICONIC_SIZE = (160, 31)
SUB_MINIMUM_SIZES = [
    pytest.param((160, 31), id="windows_iconic"),
    pytest.param((1, 1), id="one_pixel"),
]


def _review_pgn(tmp_path):
    path = tmp_path / "resize.pgn"
    path.write_text(
        '[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n'
        '[TimeControl "300+0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n',
        encoding="utf-8",
    )
    return path


def _open(app, name, tmp_path):
    if name == "review":
        app.switch_to("review", pgn_path=str(_review_pgn(tmp_path)), return_to="menu")
    elif name == "game":
        start_single_screen(app)
    return app.screens[name]


def _assert_positive(rect):
    assert rect.width > 0 and rect.height > 0, rect


@pytest.mark.parametrize("size", SUB_MINIMUM_SIZES)
@pytest.mark.parametrize("name", ["menu", "game", "review"])
def test_layout_never_sees_a_size_below_the_minimum(name, size, tmp_path):
    """Regression for the shipped crash: on master the game and review screens
    built a negative RightMenu panel at these sizes and the next draw raised
    'Invalid resolution for Surface'."""
    app = make_app()
    _open(app, name, tmp_path)
    app.window = pg.display.set_mode(size, WINDOW_FLAGS)
    app.chrome.window = app.window

    app._compute_layout()

    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    for screen in (app.game, app.review):
        _assert_positive(screen.right_menu.outer_rect)
        _assert_positive(screen.right_menu.moves_rect)
        _assert_positive(screen.board.rect)
    app.draw_frame()
    app.chrome.draw([])


def test_layout_just_below_the_minimum_is_still_laid_out_at_the_minimum():
    app = make_app()
    app.window = pg.display.set_mode(
        (MIN_WINDOW_WIDTH - 1, MIN_WINDOW_HEIGHT - 1), WINDOW_FLAGS)
    app._compute_layout()
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_a_minimum_size_layout_does_not_clear_the_size_keyed_caches_twice(monkeypatch):
    """Every sub-minimum size maps onto the same layout size, so repeated
    minimizes do not churn the size-keyed caches."""
    app = make_app()
    clears = []
    monkeypatch.setattr(cache, "clear_size_keyed", lambda: clears.append(1))
    for size in [(160, 31), (1, 1), (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT - 1),
                 (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)]:
        app.window = pg.display.set_mode(size, WINDOW_FLAGS)
        app._compute_layout()
    assert clears == [1]


@pytest.mark.parametrize("name", ["game", "review"])
def test_iconic_videoresize_then_draw_does_not_crash(monkeypatch, name, tmp_path):
    """Worst case: minimize detection fails (get_active stays True) and set_mode
    cannot grow the iconic window. The shipped chain end to end."""
    app = make_app()
    screen = _open(app, name, tmp_path)

    def iconic_set_mode(w, h):
        app.window = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)
        app.chrome.window = app.window

    monkeypatch.setattr(app, "_recreate_window_surface", iconic_set_mode)
    app.window = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)
    pg.event.clear()
    pg.event.post(pg.event.Event(
        pg.VIDEORESIZE, {"w": ICONIC_SIZE[0], "h": ICONIC_SIZE[1], "size": ICONIC_SIZE}))

    app.input_router.check_events()
    app.draw_frame()

    _assert_positive(screen.right_menu.outer_rect)
    _assert_positive(screen.right_menu.moves_rect)
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


@pytest.mark.parametrize("ev_w, ev_h", [
    pytest.param(0, 0, id="zero_area"),
    pytest.param(-5, -40, id="negative"),
])
def test_degenerate_videoresize_lays_out_at_the_minimum(ev_w, ev_h):
    app = make_app()
    start_single_screen(app)
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": ev_w, "h": ev_h, "size": (ev_w, ev_h)}))
    app.input_router.check_events()
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    app.draw_frame()


def test_videoresize_router_delegates_to_the_shell(monkeypatch):
    app = make_app()
    calls = []
    monkeypatch.setattr(app, "_on_videoresize", lambda w, h: calls.append((w, h)))
    pg.event.clear()
    pg.event.post(pg.event.Event(pg.VIDEORESIZE, {"w": 1234, "h": 777, "size": (1234, 777)}))
    app.input_router.check_events()
    assert calls == [(1234, 777)]


@pytest.mark.parametrize("os_name, req, recreated", [
    pytest.param("posix", (1100, 850), [], id="posix_adequate_keeps_surface"),
    pytest.param("posix", (300, 200), [(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)],
                 id="posix_clamped_remakes"),
    pytest.param("nt", (1100, 850), [(1100, 850)], id="nt_always_remakes"),
])
def test_on_videoresize_keeps_the_nt_or_clamped_recreate_rule(
        monkeypatch, os_name, req, recreated):
    app = make_app()
    calls = []
    monkeypatch.setattr(app, "_recreate_window_surface", lambda w, h: calls.append((w, h)))
    monkeypatch.setattr("chessshootout.frontend.frontend.os",
                        types.SimpleNamespace(name=os_name, environ={}))
    app._on_videoresize(*req)
    assert calls == recreated


@pytest.mark.parametrize("req", [(0, 0), (160, 31), (-1, 5000)])
def test_finish_resize_never_records_a_size_below_the_minimum(req):
    app = make_app()
    app._finish_resize(*req)
    assert app.window_width >= MIN_WINDOW_WIDTH
    assert app.window_height >= MIN_WINDOW_HEIGHT
    assert app.window_height == max(req[1], MIN_WINDOW_HEIGHT)


@pytest.mark.parametrize("client", [(0, 0), ICONIC_SIZE])
def test_a_launch_that_starts_minimized_settles_at_the_minimum(monkeypatch, client):
    """A 'Run: minimized' shortcut: the very first settle sees the iconic
    window, before any VIDEORESIZE has arrived."""
    import os as real_os

    from chessshootout.frontend import frontend as frontend_module

    app = make_app()
    start_single_screen(app)
    monkeypatch.setattr(app.chrome, "client_size", lambda: client)

    def iconic_set_mode(w, h):
        app.window = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)
        app.chrome.window = app.window

    monkeypatch.setattr(app, "_recreate_window_surface", iconic_set_mode)
    monkeypatch.setattr(frontend_module, "os", types.SimpleNamespace(name="nt", environ={}))
    app._settle_window()
    monkeypatch.setattr(frontend_module, "os", real_os)

    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    _assert_positive(app.game.right_menu.outer_rect)
    app.draw_frame()


def test_maximize_fallback_clamps_a_sub_minimum_desktop(monkeypatch):
    app = make_app()
    monkeypatch.setattr(app.chrome, "maximize", lambda: False)
    monkeypatch.setattr(pg.display, "get_desktop_sizes", lambda: [(640, 480)])
    app._maximize_window()
    assert app.window.get_size() == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_maximize_fallback_records_the_minimum_even_if_the_surface_stays_small(monkeypatch):
    app = make_app()
    monkeypatch.setattr(app.chrome, "maximize", lambda: False)
    monkeypatch.setattr(pg.display, "get_desktop_sizes", lambda: [(2560, 1440)])

    def iconic_set_mode(w, h):
        app.window = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)

    monkeypatch.setattr(app, "_recreate_window_surface", iconic_set_mode)
    app._maximize_window()
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_settle_maximized_with_a_zero_client_size_clamps(monkeypatch):
    app = make_app()
    app.chrome = _MaximizingChrome((0, 0))
    app._settle_maximized()
    assert app.window.get_size() == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_apply_fullscreen_onto_an_iconic_surface_records_the_minimum(monkeypatch):
    app = make_app()
    iconic = pg.display.set_mode(ICONIC_SIZE, WINDOW_FLAGS)
    monkeypatch.setattr(app.chrome, "apply_fullscreen", lambda enable: True)
    monkeypatch.setattr(pg.display, "get_surface", lambda: iconic)
    assert app._apply_fullscreen(True) is True
    assert (app.window_width, app.window_height) == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
    assert app._last_layout_size == (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)


def test_sync_skips_while_minimized(monkeypatch):
    app = make_app()
    before = app.window.get_size()
    monkeypatch.setattr(pg.display, "get_active", lambda: False)
    monkeypatch.setattr(pg.display, "get_window_size", lambda: (200, 150))
    calls = []
    monkeypatch.setattr(app, "_compute_layout", lambda: calls.append(1))
    app._sync_window_surface()
    assert app.window.get_size() == before
    assert calls == []


@pytest.mark.parametrize("client", [(0, 0), (0, 700), (1200, 0)])
def test_sync_skips_a_zero_area_client_size(monkeypatch, client):
    """Real Windows reports a 0x0 client rect for an iconic window; clamping
    that and remaking the surface every frame is what the old sync did."""
    app = make_app()
    before = app.window.get_size()
    monkeypatch.setattr(app.chrome, "client_size", lambda: client)
    recreated = []
    monkeypatch.setattr(app, "_recreate_window_surface", lambda w, h: recreated.append((w, h)))
    app._sync_window_surface()
    assert recreated == []
    assert app.window.get_size() == before
