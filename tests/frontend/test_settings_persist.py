"""Deferred, coalesced settings writes (v2.4.3). Volume sliders update the mixer
live and defer the .env persist to a debounce window, so a drag no longer writes
the file 60x/sec (which on Windows raced os.replace into WinError 5). The pending
write flushes after the delay, coalesces repeat releases by key, and is
force-flushed on shutdown so nothing is lost.

Also the SettingsController half of the server connection probe (v2.12.1): the
worker's try/finally unlatch, the verdict keyed to the address it probed, the
Official-mode target honoring a launch-time CHESS_SERVER_ADDR override, the
missing-version mismatch copy, and the coordinator notification on a server
target change. The Options-view UI side lives in test_menu_options_view.py.
"""
from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.frontend.settings import (
    SERVER_PROBE_BUTTON_IDLE, SERVER_PROBE_BUTTON_PENDING, SettingsController,
)
from chessshootout.server.protocol import PROTOCOL_VERSION

from tests.conftest import pygame_display
_pygame_init = pygame_display(1000, 800)


@pytest.fixture
def app():
    from chessshootout.frontend.frontend import Frontend
    a = Frontend(1000, 800)
    a.sound_manager = MagicMock()
    return a


@pytest.fixture
def controller():
    frontend = MagicMock()
    frontend.coordinator.is_connected.return_value = False
    return SettingsController(frontend)


class _Row:

    def __init__(self, text):
        self.text = text

    def current_text(self):
        return self.text


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


def test_probe_worker_raise_still_returns_the_button_to_idle(controller, monkeypatch):
    """_server_probe_worker had no try/finally, so any raise on the probe thread
    latched _server_probe_pending and the Test button read "Testing…" forever.
    The finally clears pending for the live generation even when the probe
    blows up."""
    monkeypatch.setattr("chessshootout.frontend.settings.probe_server_health",
                        MagicMock(side_effect=RuntimeError("boom")))
    controller._server_probe_gen = 1
    controller._server_probe_pending = True
    with pytest.raises(RuntimeError):
        controller._server_probe_worker("localhost:8000", 1)
    assert controller._probe_button_label() == SERVER_PROBE_BUTTON_IDLE
    assert controller._probe_status() == ("idle", "")


def test_probe_worker_raise_from_a_stale_generation_leaves_the_new_probe_pending(
        controller, monkeypatch):
    """The unlatch compares generations under the lock: a superseded worker that
    dies must not clear the pending flag the newer probe owns."""
    monkeypatch.setattr("chessshootout.frontend.settings.probe_server_health",
                        MagicMock(side_effect=RuntimeError("boom")))
    controller._server_probe_gen = 2
    controller._server_probe_pending = True
    with pytest.raises(RuntimeError):
        controller._server_probe_worker("localhost:8000", 1)
    assert controller._probe_button_label() == SERVER_PROBE_BUTTON_PENDING


def test_probe_verdict_clears_when_the_typed_address_changes(controller, monkeypatch):
    """The stored verdict is keyed to the address that was probed: retyping the
    custom field invalidates the display straight from _probe_status (no click
    handler involved), and typing the probed address back restores it."""
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_mode",
                        lambda: "custom")
    monkeypatch.setattr(
        "chessshootout.frontend.settings.probe_server_health",
        lambda addr, timeout=None: {"version": PROTOCOL_VERSION, "app_version": ""})
    row = _Row("first:8000")
    controller._custom_server_row = row
    controller._server_probe_gen = 1
    controller._server_probe_pending = True
    controller._server_probe_worker("first:8000", 1)
    kind, _ = controller._probe_status()
    assert kind == "ok"
    row.text = "second:8000"
    assert controller._probe_status() == ("idle", "")
    row.text = "first:8000"
    kind, _ = controller._probe_status()
    assert kind == "ok"


def test_probe_target_in_official_mode_is_the_effective_server_addr(controller, monkeypatch):
    """A launch-time CHESS_SERVER_ADDR override (the documented two-client dev
    workflow) redirects what Official mode actually connects to, so the probe
    must test env.get_server_addr(), not the official constant."""
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_mode",
                        lambda: "official")
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_addr",
                        lambda: "localhost:9001")
    assert controller._probe_target_addr() == "localhost:9001"


def test_missing_server_version_reads_as_a_protocol_mismatch(controller):
    """probe_server_health hands back version=None when the /healthz body never
    carried the key; the describe step must render that as an unknown-server
    mismatch, not fall through to the OK branch."""
    kind, text = controller._describe_health({"version": None, "app_version": ""}, 12)
    assert kind == "warn"
    assert text == "Protocol mismatch: server v? ≠ client v{}".format(PROTOCOL_VERSION)


def test_server_mode_change_notifies_the_coordinator(controller, monkeypatch):
    """A server target change must clear the coordinator's pending reclaim and
    bump its reconnect-probe generation, or the menu keeps offering a Reconnect
    into the previous server."""
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_mode",
                        lambda: "official")
    monkeypatch.setattr("chessshootout.frontend.settings.env.set_server_mode", MagicMock())
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_addr",
                        lambda: "localhost:9001")
    controller._apply_server_mode("custom")
    controller.frontend.coordinator.on_server_target_changed.assert_called_once_with()


def test_blocked_server_mode_change_does_not_notify_the_coordinator(controller, monkeypatch):
    """The blocked path (live online session) changes nothing, so the coordinator
    must not be told the target moved."""
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_mode",
                        lambda: "official")
    controller.frontend.coordinator.is_connected.return_value = True
    controller._apply_server_mode("custom")
    controller.frontend.coordinator.on_server_target_changed.assert_not_called()


def test_custom_addr_commit_notifies_the_coordinator(controller, monkeypatch):
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_custom_server_addr",
                        lambda: "old:8000")
    monkeypatch.setattr("chessshootout.frontend.settings.env.set_custom_server_addr",
                        MagicMock())
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_mode",
                        lambda: "custom")
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_server_addr",
                        lambda: "new:8000")
    controller._commit_custom_server_addr("new:8000")
    controller.frontend.coordinator.on_server_target_changed.assert_called_once_with()


def test_blocked_custom_addr_commit_does_not_notify_the_coordinator(controller, monkeypatch):
    monkeypatch.setattr("chessshootout.frontend.settings.env.get_custom_server_addr",
                        lambda: "old:8000")
    controller.frontend.coordinator.is_connected.return_value = True
    controller._commit_custom_server_addr("new:8000")
    controller.frontend.coordinator.on_server_target_changed.assert_not_called()
