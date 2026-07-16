import pytest

from tests.helpers import make_app


@pytest.fixture(autouse=True)
def _reset_rail_section_open():
    """SECTION_OPEN is process-global rail state shared by every game/review
    RightMenu, and A/S/C hotkeys mutate it. Restore the defaults around each
    frontend test so a toggle in one never leaks into another."""
    from chessshootout.frontend.panels.right import SECTION_OPEN
    saved = dict(SECTION_OPEN)
    SECTION_OPEN.update({"actions": True, "signals": True, "chat": True})
    yield
    SECTION_OPEN.clear()
    SECTION_OPEN.update(saved)


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
