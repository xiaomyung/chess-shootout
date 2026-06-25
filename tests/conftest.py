import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SERVER_START_TIMEOUT_SECONDS = 15


@pytest.fixture(autouse=True)
def _isolate_env_file(tmp_path_factory, monkeypatch):
    """Keep every test off the real .env files.

    Env writers (e.g. a Frontend ensuring a client UUID, or set_last_mode)
    otherwise persist to the module-default _ENV_PATH and leave a stray .env in
    the package dir.
    """
    from chessshootout.infra import env
    monkeypatch.setattr(env, "_ENV_PATH", tmp_path_factory.mktemp("envcfg") / ".env")


@pytest.fixture
def server():
    """Real uvicorn server on a socket pre-bound here and handed over still open.

    The previous pattern (bind to port 0, close the socket, pass the bare port
    number to uvicorn) left a window in which the kernel could reassign that
    port to another concurrently-starting test server before uvicorn re-bound
    it. Under xdist that TOCTOU race occasionally left a server unable to bind,
    so its clients' matchmake calls were refused and the game_start broadcast
    never arrived (both clients saw None). It was worse on Windows, whose
    SO_REUSEADDR semantics let a second bind hijack the port. Handing over the
    already-bound socket removes the window entirely and guarantees the port is
    live before the test body runs.
    """
    import socket
    import threading
    import time

    import uvicorn

    from chessshootout.server.app import create_app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        create_app(max_rooms=8), log_level="warning",
        ws_ping_interval=20, ws_ping_timeout=30,
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(
        target=lambda: srv.run(sockets=[sock]), daemon=True,
    )
    thread.start()
    deadline = time.time() + SERVER_START_TIMEOUT_SECONDS
    while not srv.started and time.time() < deadline:
        time.sleep(0.02)
    assert srv.started, "test uvicorn server did not start in time"
    try:
        yield port
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
        sock.close()


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
