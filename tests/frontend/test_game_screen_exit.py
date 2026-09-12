"""GameScreen.exit() cancels EVERYTHING screen-local (screen contract), and a
skill-check verdict the server already delivered is never lost on the way out.

Two v2.13.1 gaps: exit() forgot the give-time hold (D10), and a verdict action
parked behind the overlay's flourish was nulled by the teardown without ever
running (E4) -- reachable from exit() and from a verdict whose kind had no
controller to open (D3), which then held the heartbeat off forever.
"""

import logging
from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.game.skillcheck_session import CheckContext
from chessshootout.frontend.online_coordinator import ResyncCause
from chessshootout.skillcheck.types import SkillCheckKind
from tests.helpers import WHITE, capture_board, move_applied, online_app


_pygame_init = pygame_display(1000, 800)


def test_exit_cancels_a_give_time_hold():
    """A hold in progress when the player leaves the screen must not survive
    into the next screen or the next game: exit() drops it like every other
    screen-local thing."""
    app = online_app()
    app.game.give_time.holding = True
    app.game.give_time._give_time_hold_recipient = "black"
    app.game.exit()
    assert app.game.give_time.holding is False
    assert app.game.give_time._give_time_hold_recipient is None


def test_exit_runs_a_parked_verdict_before_tearing_the_overlay_down():
    """The teardown nulls the parked action; running it first is what keeps a
    won capture the server already confirmed from vanishing when the player
    leaves mid-flourish."""
    app = online_app()
    ran = []
    session = app.game.skillcheck_session
    session.online_verdict_action = lambda: ran.append(True)
    session.online_verdict_set_ms = pg.time.get_ticks()
    app.game.exit()
    assert ran == [True]
    assert session.online_verdict_action is None
    assert session.online_verdict_set_ms is None


def test_exit_swallows_a_parked_verdict_that_raises(caplog):
    """exit() must complete whatever the parked action does; a failure is
    logged, not raised into the navigation that is leaving the screen."""
    app = online_app()

    def explode():
        raise RuntimeError("the verdict could not be played out")

    app.game.skillcheck_session.online_verdict_action = explode
    with caplog.at_level(logging.ERROR, logger="chess.frontend"):
        app.game.exit()
    assert app.game.skillcheck_session.online_verdict_action is None
    assert any("parked skill-check verdict failed" in r.getMessage() for r in caplog.records)


def test_a_verdict_with_no_overlay_to_wait_for_lands_the_move_at_once():
    """D3: online_skillcheck is set but no controller ever opened (a kind this
    client could not draw). The won move_applied must not park its apply
    behind an overlay that will never finish -- it applies now, and the
    heartbeat, which is held off while an action is parked, is free again."""
    app = online_app()
    frm, to = capture_board(app)
    session = app.game.skillcheck_session
    session.online_skillcheck = CheckContext(frm, to, None, SkillCheckKind.WHEEL)
    assert not app.game.skillcheck_overlay.is_active()
    app.coordinator._handle_remote_move_applied(move_applied(frm, to, 1, kind="wheel", won=True))
    assert len(app.game.match.move_history) == 1
    assert app.game.match.piece_at(to).color == WHITE
    assert session.online_verdict_action is None
    assert session.online_verdict_set_ms is None
    app.coordinator._last_heartbeat_sent_ms = -100_000
    app.coordinator._send_heartbeat_if_due()
    assert app.coordinator.client.pings == 1, "nothing parked, so the heartbeat runs"


def test_a_verdict_with_no_overlay_whose_action_fails_resyncs(monkeypatch):
    """The immediate run has the same safety net as the overlay path: an apply
    that blows up rebuilds the game from the server instead of leaving a
    half-applied ply behind."""
    app = online_app()
    causes = []
    monkeypatch.setattr(app.coordinator, "_begin_resync", causes.append)

    def explode():
        raise RuntimeError("boom")

    app.game._begin_online_verdict(True, explode)
    assert causes == [ResyncCause.VERDICT_LOST]
    assert app.game.skillcheck_session.online_verdict_action is None


def test_begin_online_verdict_stamps_when_the_action_was_parked():
    """The parked action carries the tick it was parked at, which is what a
    watchdog needs to tell "waiting on the flourish" from "lost"."""
    app = online_app()
    app.game.skillcheck_overlay.start(MagicMock(landed=None), None, lambda *_: None)
    app.game._begin_online_verdict(True, lambda: None)
    assert app.game.skillcheck_session.online_verdict_action is not None
    assert app.game.skillcheck_session.online_verdict_set_ms == pytest.approx(
        pg.time.get_ticks(), abs=50)
    app.game.skillcheck_session.teardown_skillcheck_overlay()
    assert app.game.skillcheck_session.online_verdict_set_ms is None
