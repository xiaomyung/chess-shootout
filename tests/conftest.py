import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SERVER_START_TIMEOUT_SECONDS = 15


def pygame_display(w=1000, h=800):
    """Build a module-scoped autouse fixture that inits pygame, sets the
    display to (w, h) for the module, and tears back down at module end.

    Single source for the pg.init()/set_mode/yield/pg.quit() shape that used
    to be copy-pasted per file. Usage in a test module:
    `_pygame_init = pygame_display(900, 500)`.
    """
    @pytest.fixture(scope="module", autouse=True)
    def _fixture():
        import pygame as pg
        pg.init()
        pg.display.set_mode((w, h))
        yield
        pg.quit()

    return _fixture


@pytest.fixture(scope="module", autouse=True)
def _clear_render_caches_per_module():
    """Release cached surfaces after each test module.

    The module-level widget caches in frontend/visual/cache.py (text, icon,
    rounded-rect, per-size result-fade/bullet/promo-option surfaces, ...) are
    process-lifetime globals shared by every test that imports them. Left
    alone across a full worker's ~140 modules they accumulate one entry per
    distinct (font, text, size, ...) key ever rendered in the whole run.
    Clearing at each module boundary bounds that growth to roughly one
    module's worth of surfaces at a time instead of the whole suite's.
    """
    yield
    from chessshootout.frontend.visual import cache
    cache.clear_all()


@pytest.fixture(autouse=True)
def _isolate_env_file(tmp_path_factory, monkeypatch):
    """Keep every test off the real .env files.

    Env writers (e.g. a Frontend ensuring a client UUID, or set_last_mode)
    otherwise persist to the module-default _ENV_PATH and leave a stray .env in
    the package dir.
    """
    from chessshootout.infra import env
    monkeypatch.setattr(env, "_ENV_PATH", tmp_path_factory.mktemp("envcfg") / ".env")


@pytest.fixture(autouse=True)
def _isolate_games_dir(tmp_path_factory, monkeypatch):
    """Keep every test off the real games/ folder and the real platformdirs
    user-data folder.

    With incremental autosave, any draw_frame()/_update_result_pending() call
    during a live (or just-finished) game can write a PGN. A test that never
    overrides CHESS_DATA_DIR would otherwise default to the source root (not
    frozen) and litter the real repo's games/ directory. A test's own
    monkeypatch.setenv("CHESS_DATA_DIR", ...) still wins — it runs later, inside
    the test body, after this fixture has already set up. The save pipeline's
    OSError fallback writes to paths.get_fallback_data_dir() (the real
    platformdirs user-data dir, deliberately CHESS_DATA_DIR-immune) — that must
    be isolated too, or a save-failure test litters the developer's real
    ~/.local/share (or platform equivalent).
    """
    from chessshootout import paths
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path_factory.mktemp("gamesdir")))
    monkeypatch.setattr(
        paths, "get_fallback_data_dir", lambda: tmp_path_factory.mktemp("fallbackdir"))


@pytest.fixture(autouse=True)
def _isolate_news(tmp_path_factory, monkeypatch):
    """Keep every test off the real news feed and the real config-dir cache file.

    NewsClient fetches once per app run from a background daemon thread at
    Frontend construction (mirrors the reconnect probe) and reads/writes a
    cache file in the platform config dir. Point both at inert local spots so
    the suite never makes a real HTTPS request or touches a stray
    news_cache.json in the repo root.
    """
    from chessshootout.online import news
    monkeypatch.setenv("CHESS_NEWS_URL", "http://127.0.0.1:1/news.json")
    monkeypatch.setattr(
        news, "_cache_path",
        lambda: tmp_path_factory.mktemp("newscache") / news.CACHE_FILENAME)


@pytest.fixture(autouse=True)
def _isolate_hide_opp_marks():
    """env.set_hide_opp_marks writes os.environ directly (not via monkeypatch),
    so a test that flips it would leak the flag into later tests in the same
    worker. Pop it before and after every test to keep the default (unset)."""
    os.environ.pop("CHESS_HIDE_OPP_MARKS", None)
    yield
    os.environ.pop("CHESS_HIDE_OPP_MARKS", None)


@pytest.fixture(autouse=True)
def _isolate_news_last_seen():
    """env.set_news_last_seen writes os.environ directly (not via monkeypatch),
    so a test that persists a last-seen date would leak it into later tests in
    the same worker and skew their unread-badge counts. Pop it before and after
    every test to keep the default (unset)."""
    os.environ.pop("CHESS_NEWS_LAST_SEEN", None)
    yield
    os.environ.pop("CHESS_NEWS_LAST_SEEN", None)


@pytest.fixture(autouse=True)
def _isolate_profile_hint(monkeypatch):
    """Tests build a fresh Frontend from a blank .env every time, which would
    otherwise trip the once-ever first-run profile hint toast on every single
    test that constructs an app. Mark it as already shown by default; the
    tests for the hint itself override this explicitly.
    """
    monkeypatch.setenv("CHESS_PROFILE_HINT_SHOWN", "1")


@pytest.fixture
def server(server_with_app):
    """Real uvicorn server, port only.

    A thin wrapper over server_with_app (same real-uvicorn startup/teardown)
    for the majority of callers that only need the port and never touch the
    app object directly.
    """
    port, _app = server_with_app
    yield port


@pytest.fixture
def server_with_app():
    """Same real uvicorn server, but also hands the test the app object so a
    skill-check integration test can force a kind (set room.skillcheck_secret)
    and inspect room.skillcheck_log directly. The protocol still flows over real
    HTTP + WebSockets via OnlineClient."""
    import socket
    import threading
    import time

    import uvicorn

    from chessshootout.server.app import create_app

    app = create_app(max_rooms=8)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, log_level="warning", ws_ping_interval=20, ws_ping_timeout=30,
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.time() + SERVER_START_TIMEOUT_SECONDS
    while not srv.started and time.time() < deadline:
        time.sleep(0.02)
    assert srv.started, "test uvicorn server did not start in time"
    try:
        yield port, app
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
        sock.close()
