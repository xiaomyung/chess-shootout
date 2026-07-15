import pytest

from tests.helpers import make_app


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
