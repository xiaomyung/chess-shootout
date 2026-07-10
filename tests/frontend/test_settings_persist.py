"""Deferred, coalesced settings writes (v2.4.3). Volume sliders update the mixer
live and defer the .env persist to a debounce window, so a drag no longer writes
the file 60x/sec (which on Windows raced os.replace into WinError 5). The pending
write flushes after the delay, coalesces repeat releases by key, and is
force-flushed on shutdown so nothing is lost.
"""
from unittest.mock import MagicMock

import pygame as pg
import pytest


from tests.conftest import pygame_display
_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def app():
    from chessshootout.frontend.frontend import Frontend
    a = Frontend(1000, 800)
    a.sound_manager = MagicMock()
    return a


def test_defer_does_not_commit_before_the_delay(app, monkeypatch):
    fired = []
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000)
    app.settings._defer_env_write("master_volume", lambda: fired.append(1))
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1100)
    app.settings._flush_deferred_env_writes()
    assert fired == []


def test_deferred_write_commits_after_the_delay(app, monkeypatch):
    from chessshootout.frontend.settings import SETTINGS_WRITE_DELAY_MS
    fired = []
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000)
    app.settings._defer_env_write("master_volume", lambda: fired.append(1))
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000 + SETTINGS_WRITE_DELAY_MS)
    app.settings._flush_deferred_env_writes()
    assert fired == [1]


def test_repeat_release_same_key_coalesces_to_one_write(app, monkeypatch):
    from chessshootout.frontend.settings import SETTINGS_WRITE_DELAY_MS
    fired = []
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000)
    app.settings._defer_env_write("master_volume", lambda: fired.append("a"))
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1200)
    app.settings._defer_env_write("master_volume", lambda: fired.append("b"))
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1200 + SETTINGS_WRITE_DELAY_MS)
    app.settings._flush_deferred_env_writes()
    assert fired == ["b"]


def test_force_flush_commits_pending_immediately(app, monkeypatch):
    fired = []
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 1000)
    app.settings._defer_env_write("master_volume", lambda: fired.append(1))
    app.settings._flush_deferred_env_writes(force=True)
    assert fired == [1]
    assert app.settings._deferred_env_writes == {}
