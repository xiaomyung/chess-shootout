import pytest

from tests.helpers import make_app


@pytest.fixture(autouse=True)
def _reset_rail_section_open():
    """SECTION_OPEN is process-global rail state shared by every game/review
    RightMenu, and A/S/C hotkeys mutate it (and persist to env since sections
    remember their state across games). Seed all-open for the suite so layout
    tests see the full rail, and scrub both the cache and the persisted env
    keys afterwards so a toggle in one test never leaks into another."""
    import os
    from chessshootout.frontend.panels.right import SECTION_OPEN
    from chessshootout.infra.env import _RAIL_SECTION_KEYS
    saved = dict(SECTION_OPEN)
    saved_env = {key: os.environ.get(key) for key in _RAIL_SECTION_KEYS.values()}
    SECTION_OPEN.update({"actions": True, "signals": True, "chat": True})
    yield
    SECTION_OPEN.clear()
    SECTION_OPEN.update(saved)
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A drawn 1200x900 Frontend with its games folder isolated to a temp dir.

    Shared by the menu sub-view tests (profile, rail cards) that scan the games
    dir for lifetime/recent stats. A file with its own `app` fixture overrides
    this one; the server suite's `app` stays separately scoped to tests/server/.
    """
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    application = make_app(1200, 900)
    application.draw_frame()
    return application
