"""Auto-end countdown badges and heartbeat fold in the player strip.

Drives Frontend._strip_state / _compute_auto_end / _update_heartbeat directly:
no server fixture, no real WebSocket. The idle window (abort/resign) is
server-pushed and client-cleared: the client arms only from an idle_window
push, a resume payload, or match-found's started_seconds_ago, and clears on
every applied move / takeback / result. All auto-end windows are 60 s; the
10 % gate hides the badge for the first 6 s; the heartbeat red threshold is
10 s remaining.
"""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.domain.match import ONLINE
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import Square
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.screens.game import IdleWindow
from chessshootout.online.client import RECONNECT_TOTAL_SECONDS
from chessshootout.server.protocol import (
    FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, IDLE_RESIGN_SECONDS, Reason,
)


_pygame_init = pygame_display(1000, 800)


def _online_app():
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.coordinator.client = MagicMock()
    app.coordinator.client.room_id = "room-1"
    app.coordinator.client.state = "connected"
    app.coordinator.client.opp_state = "connected"
    app.coordinator.client.get_ping_ms.return_value = None
    app.switch_to("game", variant=ONLINE)
    app.coordinator.subscribe(app.game)
    app.game.white_name = "Alice"
    app.game.black_name = "Bob"
    app.game._chosen_side = "white"
    app.game.match.mode = ONLINE
    app.game.match.local_color = PieceColor.WHITE
    app.game._idle_window = None
    app.game._opp_disconnected_at_ms = None
    app.game._local_disconnected_at_ms = None
    return app


def _strip(app, color):
    over = app.game.current_result() is not None
    return app.game._strip_state(color, app.game.match.current_turn(), over)


def _ticks(monkeypatch, start=0):
    state = {"now": start}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: state["now"])
    return state


ABORT_WINDOW_MS = FIRST_MOVE_ABORT_SECONDS * 1000
ABORT_WHITE = IdleWindow(
    Reason.ABORTED, PieceColor.WHITE, ABORT_WINDOW_MS, float(FIRST_MOVE_ABORT_SECONDS))


@pytest.mark.parametrize(
    "local_color, idle_window, opp_disconnected_at_ms, "
    "local_disconnected_at_ms, ticks, query_color, expected_label, expected_seconds",
    [
        pytest.param(
            PieceColor.WHITE, ABORT_WHITE, None, None, 5_000,
            PieceColor.WHITE, None, None, id="abort_under_10pct_hidden",
        ),
        pytest.param(
            PieceColor.WHITE, ABORT_WHITE, None, None, 7_000,
            PieceColor.WHITE, "Abort in", 53.0, id="abort_at_10pct_shows",
        ),
        pytest.param(
            PieceColor.WHITE, None, 0, None, 5_000,
            PieceColor.BLACK, None, None, id="abandon_below_gate_hidden",
        ),
        pytest.param(
            PieceColor.WHITE, None, 0, None, 12_000,
            PieceColor.BLACK, "Abandon in", GRACE_SECONDS - 12,
            id="abandon_above_gate_shows",
        ),
        pytest.param(
            PieceColor.WHITE, None, None, 0, 12_000,
            PieceColor.WHITE, "Aborting in", RECONNECT_TOTAL_SECONDS - 12,
            id="reconnect_local_strip_shows",
        ),
        pytest.param(
            PieceColor.WHITE, ABORT_WHITE, None, 0, 12_000,
            PieceColor.WHITE, "Aborting in", None,
            id="reconnect_beats_abort_local_strip",
        ),
        pytest.param(
            PieceColor.BLACK, ABORT_WHITE, 0, None, 12_000,
            PieceColor.WHITE, "Abandon in", None,
            id="abandon_beats_abort_opp_to_move",
        ),
    ],
)
def test_compute_auto_end_label_and_remaining(
    monkeypatch, local_color, idle_window, opp_disconnected_at_ms,
    local_disconnected_at_ms, ticks, query_color, expected_label, expected_seconds,
):
    """Reconnect > abandon > idle cascade plus the 10 % visibility gate."""
    app = _online_app()
    app.game.match.local_color = local_color
    app.game._idle_window = idle_window
    app.game._opp_disconnected_at_ms = opp_disconnected_at_ms
    app.game._local_disconnected_at_ms = local_disconnected_at_ms
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
    state = _strip(app, query_color)
    assert state["auto_end_label"] == expected_label
    if expected_seconds is None:
        if expected_label is None:
            assert state["auto_end_seconds"] is None
    else:
        assert state["auto_end_seconds"] == pytest.approx(expected_seconds, abs=0.1)


def test_black_first_move_window_shows_the_abort_badge_on_black_strip(monkeypatch):
    """#81: after white's first ply the server re-arms the abort window against
    black. The badge must land on black's strip even though white is the local
    player and it is black's turn everywhere — the window's color, not the turn
    or the ply count, names the side on the hook."""
    app = _online_app()
    ticks = _ticks(monkeypatch)
    app.game.on_idle_window({
        "outcome": "aborted", "color": "black",
        "seconds_remaining": float(FIRST_MOVE_ABORT_SECONDS),
    })
    ticks["now"] = 7_000
    state = _strip(app, PieceColor.BLACK)
    assert state["auto_end_label"] == "Abort in"
    assert state["auto_end_seconds"] == pytest.approx(53.0, abs=0.1)
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None


@pytest.mark.parametrize("local_color", [
    pytest.param(PieceColor.WHITE, id="idler_view"),
    pytest.param(PieceColor.BLACK, id="opponent_view"),
])
def test_idle_resign_window_shows_the_resign_badge_on_the_idler_strip(
    monkeypatch, local_color,
):
    """#82: the resign badge renders on the idler's strip for BOTH viewers —
    the same convention as the abort badge. The server states who is on the
    hook; the client never guesses from local state."""
    app = _online_app()
    app.game.match.local_color = local_color
    ticks = _ticks(monkeypatch)
    app.game.on_idle_window({
        "outcome": "resignation", "color": "white",
        "seconds_remaining": float(IDLE_RESIGN_SECONDS),
    })
    ticks["now"] = 7_000
    state = _strip(app, PieceColor.WHITE)
    assert state["auto_end_label"] == "Resign in"
    assert state["auto_end_seconds"] == pytest.approx(IDLE_RESIGN_SECONDS - 7, abs=0.1)
    assert _strip(app, PieceColor.BLACK)["auto_end_label"] is None


def test_an_idle_window_push_replaces_the_client_deadline(monkeypatch):
    """Every push re-anchors the deadline from the server's remaining seconds,
    so a refresh (the idler proved presence) extends the countdown instead of
    the client ticking down the stale first anchor."""
    app = _online_app()
    ticks = _ticks(monkeypatch)
    app.game.on_idle_window({
        "outcome": "resignation", "color": "white", "seconds_remaining": 60.0,
    })
    assert app.game._idle_window.deadline_ms == 60_000
    ticks["now"] = 30_000
    app.game.on_idle_window({
        "outcome": "resignation", "color": "white", "seconds_remaining": 60.0,
    })
    assert app.game._idle_window.deadline_ms == 90_000


def test_move_applied_clears_the_window_until_the_next_push(monkeypatch):
    """Both move paths clear the window — the local move-landed transition and
    the coordinator's remote move-applied — and nothing re-arms it client-side:
    the next badge can only come from another server push."""
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.game._idle_window = ABORT_WHITE
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    app.game._on_move_landed(app.game.match.move_history[-1])
    assert app.game._idle_window is None
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None

    app.game._idle_window = IdleWindow(
        Reason.ABORTED, PieceColor.BLACK, 90_000, float(FIRST_MOVE_ABORT_SECONDS))
    payload = {"from": "e7", "to": "e5", "san": "e5", "ply": 2, "clock": {}}
    app.coordinator._handle_remote_move_applied(payload)
    assert app.coordinator._resyncing is False
    assert app.game._idle_window is None


def test_compute_auto_end_alone_does_not_clear_the_window(monkeypatch):
    """Querying auto-end state (_strip_state/_compute_auto_end) is read-only;
    only the real move/takeback/result transitions clear _idle_window."""
    app = _online_app()
    app.game._idle_window = ABORT_WHITE
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    _strip(app, PieceColor.WHITE)
    assert app.game._idle_window == ABORT_WHITE


def test_takeback_clears_the_window(monkeypatch):
    """The client must NEVER re-derive a window from len(move_history): a
    takeback pops a ply but the server's plies_ever never decrements, so any
    ply-count derivation diverges exactly here. on_takeback clears the window
    and waits for the next server push (which comes on the next ply or
    refresh) — the accepted gap is a missing badge, never a wrong one."""
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 10_000)
    app.game.match.try_move(Square(6, 4), Square(4, 4))
    app.game._idle_window = IdleWindow(
        Reason.ABORTED, PieceColor.BLACK, 70_000, float(FIRST_MOVE_ABORT_SECONDS))
    app.game.on_takeback({"ply": 0, "clock": {}})
    assert app.game._idle_window is None
    assert not app.game.match.move_history


def test_resume_payload_restores_the_window(monkeypatch):
    """/resume reports the server's remaining time (it never resets it — the
    anti-dodge posture), and the reconnected client adopts it verbatim so the
    badge is honest immediately."""
    app = _online_app()
    _ticks(monkeypatch)
    app.game.on_resume({
        "move_history": [],
        "idle_window": {"outcome": "resignation", "color": "white",
                        "seconds_remaining": 41.5},
    })
    window = app.game._idle_window
    assert window is not None
    assert window.outcome == Reason.RESIGNATION
    assert window.color == PieceColor.WHITE
    assert window.deadline_ms == 41_500
    assert window.total_seconds == float(IDLE_RESIGN_SECONDS)


def test_resume_payload_clears_the_window_when_absent(monkeypatch):
    """A resume with no idle_window means the server has none armed (ply >= 3 or
    disarmed); a stale client window must not survive the reconnect."""
    app = _online_app()
    _ticks(monkeypatch)
    app.game._idle_window = ABORT_WHITE
    app.game.on_resume({"move_history": []})
    assert app.game._idle_window is None


def test_a_garbage_idle_window_payload_is_ignored(monkeypatch):
    """Server payloads are untrusted: an unknown outcome or color never arms a
    window; non-finite seconds clamp to zero (badge hidden, nothing crashes) and
    oversize seconds clamp to the protocol table's total, so a hostile push can
    never paint a longer window than the policy allows. The total is the
    CLIENT'S table on purpose: if a future server ever ships a longer window,
    an old client clamps it short — accepted deliberately, because the error is
    in the conservative direction (badge understates the time) and the protocol
    version pairs client and server anyway, so the mismatch cannot occur in a
    live pairing."""
    app = _online_app()
    _ticks(monkeypatch)
    app.game.on_idle_window({"outcome": "meteor_strike", "color": "white",
                             "seconds_remaining": 30.0})
    assert app.game._idle_window is None
    app.game.on_idle_window({"outcome": "aborted", "color": "green",
                             "seconds_remaining": 30.0})
    assert app.game._idle_window is None
    app.game.on_idle_window({"outcome": "aborted", "color": "white",
                             "seconds_remaining": float("nan")})
    assert app.game._idle_window.deadline_ms == 0
    assert _strip(app, PieceColor.WHITE)["auto_end_label"] is None
    app.game.on_idle_window({"outcome": "aborted", "color": "white",
                             "seconds_remaining": 1e9})
    assert app.game._idle_window.deadline_ms == FIRST_MOVE_ABORT_SECONDS * 1000


@pytest.mark.parametrize("show_mode", ["nothing", "line", "strips"])
def test_idle_window_clears_via_move_landed_in_every_focus_show_mode(
    monkeypatch, show_mode,
):
    """Regression for the focus-mode gap: _update_player_strips (and the old
    _compute_auto_end reset it used to carry) never runs in focus 'nothing'/'line'
    show modes, so the window must clear at the real move-landed transition
    regardless of whether strips are drawn, and the heartbeat fraction must stop
    folding in the idle window once it does."""
    app = _online_app()
    app.game._time_control = (300, 0)
    app.game.match.setup_clock(300, 0)
    app.coordinator.client.drain_inbound.return_value = []
    app.game.focus_mode = True
    monkeypatch.setattr(app.game, "_focus_show", lambda: show_mode)
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.game._idle_window = ABORT_WHITE

    strips_calls = []
    real_update = app.game._update_player_strips

    def spy():
        strips_calls.append(True)
        real_update()

    monkeypatch.setattr(app.game, "_update_player_strips", spy)
    app.draw_frame()
    if show_mode == "strips":
        assert strips_calls
    else:
        assert not strips_calls
    assert app.game._idle_window == ABORT_WHITE

    app.game.match.try_move(Square(6, 4), Square(4, 4))
    app.game._on_move_landed(app.game.match.move_history[-1])
    assert app.game._idle_window is None
    assert app.coordinator._auto_end_heartbeat_fraction() is None

    app.draw_frame()
    assert app.game._idle_window is None


@pytest.mark.parametrize("variant", [
    pytest.param("local", id="single_screen"),
    pytest.param("bot", id="bot"),
])
def test_offline_mode_never_emits_badge(monkeypatch, variant):
    app = _online_app()
    app.game.variant = variant
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 30_000)
    app.game._idle_window = ABORT_WHITE
    app.game._opp_disconnected_at_ms = 0
    app.game._local_disconnected_at_ms = 0
    app.coordinator.client.opp_state = "reconnecting"
    app.coordinator.client.state = "reconnecting"
    for color in (PieceColor.WHITE, PieceColor.BLACK):
        assert _strip(app, color)["auto_end_label"] is None


def test_result_clears_timestamps():
    app = _online_app()
    app.game._idle_window = ABORT_WHITE
    app.game._opp_disconnected_at_ms = 0
    app.game._local_disconnected_at_ms = 0
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.game._idle_window is None
    assert app.game._opp_disconnected_at_ms is None
    assert app.game._local_disconnected_at_ms is None


def test_start_online_game_clears_disconnect_timestamps():
    app = _online_app()
    app.game._opp_disconnected_at_ms = 12345
    app.game._local_disconnected_at_ms = 67890
    app.coordinator._start_online_game({
        "your_color": "white", "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 3, "increment_seconds": 0,
        "started_seconds_ago": 0.0,
    })
    assert app.game._opp_disconnected_at_ms is None
    assert app.game._local_disconnected_at_ms is None


def test_match_found_arms_the_ply0_abort_window_after_game_entry(monkeypatch):
    """Match-found arms the ply-0 abort window through the one ingest path,
    but only once _finish_match_found has entered the game screen: enter
    resets to a clean baseline and on_idle_window drops pushes while the
    screen is not online-bound, so an arm at modal-show time would be wiped.
    The modal hold is charged against the window, so the absolute deadline
    equals matchmake_now + (60 - started_seconds_ago) * 1000 regardless of
    how long the reveal held."""
    app = _online_app()
    ticks = _ticks(monkeypatch, start=1_000)
    app.coordinator._begin_match_found_transition({
        "your_color": "white", "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 3, "increment_seconds": 0,
        "started_seconds_ago": 4.0,
    })
    assert app.game._idle_window is None, "nothing arms while the reveal holds"
    ticks["now"] = 4_000
    app.coordinator._finish_match_found()
    window = app.game._idle_window
    assert window is not None
    assert window.outcome == Reason.ABORTED
    assert window.color == PieceColor.WHITE
    assert window.deadline_ms == 57_000
    assert window.total_seconds == float(FIRST_MOVE_ABORT_SECONDS)


@pytest.mark.parametrize("ticks, expected_fraction", [
    pytest.param(55_000, 0.0, id="below_red_threshold_floors_to_zero"),
    pytest.param(30_000, 0.5, id="above_red_threshold_uses_remaining_ratio"),
])
def test_heartbeat_folds_auto_end_fraction(monkeypatch, ticks, expected_fraction):
    """No chess clock active, so the heartbeat takes the abort fraction directly."""
    app = _online_app()
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
    app.game._idle_window = ABORT_WHITE
    app.coordinator._update_heartbeat()
    args, _ = app.sound_manager.update_heartbeat.call_args
    fraction, _paused = args
    assert fraction == pytest.approx(expected_fraction, abs=0.01)


def test_heartbeat_folds_the_resign_window_total(monkeypatch):
    """The heartbeat divides by the window's own total_seconds — the resign
    window reads its real policy value, not a hardcoded abort constant."""
    app = _online_app()
    ticks = _ticks(monkeypatch)
    app.game.on_idle_window({
        "outcome": "resignation", "color": "white",
        "seconds_remaining": float(IDLE_RESIGN_SECONDS),
    })
    ticks["now"] = 30_000
    app.coordinator._update_heartbeat()
    args, _ = app.sound_manager.update_heartbeat.call_args
    fraction, _paused = args
    assert fraction == pytest.approx(30.0 / IDLE_RESIGN_SECONDS, abs=0.01)
