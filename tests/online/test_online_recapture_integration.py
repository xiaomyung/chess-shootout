"""Two real clients, two real game screens, one real server -- the recapture
that used to spray "Resyncing…" toasts, and the abort badge that used to vanish.

test_move_echo_by_ply.py pins the echo rule against a faked server and
test_auto_end_countdown.py pins the badge against a fake clock. Neither could
have caught the live v2.13.1 report, because that bug only showed itself as the
SERVER's verdict on two boards it believed were a ply behind: both clients
dropped `Nxe5 Nxe5` as an echo of itself, both then heartbeated the wrong ply,
and the server answered each of them with a resync directive.

So this file drives the whole loop unfaked: real HTTP + WebSockets, real
skill-checks on both captures, two whole Frontends running real frames
(draw_frame drains the socket, animates, plays the overlay verdict and sends
the heartbeat), and a spy on every _begin_resync either coordinator starts.
Only two things are forced -- the check KIND (a wheel, via the room's
server-side secret) and the shot's claimed elapsed, which rides the lag-comp
clamp exactly as tests/online/test_online_skillcheck_integration.py does.
"""
import time

import pygame as pg

from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import square_from_coord
from chessshootout.online.client import OnlineClient
from chessshootout.skillcheck import online
from chessshootout.skillcheck.types import SkillCheckKind
from tests.conftest import pygame_display
from tests.helpers import fake_uuid4, make_app
from tests.online.online_helpers import wait_for
from tests.online.test_online_skillcheck_integration import (
    _SLEEP_LEAD_MS, _widest_win_window,
)


_pygame_init = pygame_display(1000, 800)

FRAME_SLEEP_SECONDS = 0.005
SETTLE_TIMEOUT_SECONDS = 10.0
ANIMATION_WINDOW_SECONDS = 0.6
# Three heartbeats per side at the 2 s interval, comfortably past the two
# judged mismatches a directive needs -- the window the live bug filled with
# directives.
QUIET_WINDOW_SECONDS = 6.5


class _Seat:
    """One player end to end: a real client on a real socket, a real Frontend
    sitting on the online board it opened, and a record of everything its
    coordinator was handed or decided."""

    def __init__(self, client, payload):
        self.client = client
        self.app = make_app(1000, 800)
        self.app.coordinator.client = client
        self.app.coordinator._start_online_game(payload)
        self.events = []
        self.resyncs = []
        coordinator = self.app.coordinator
        handle, begin = coordinator._handle_online_event, coordinator._begin_resync

        def record(event):
            self.events.append(event.type)
            handle(event)

        def spy(cause):
            self.resyncs.append(cause)
            begin(cause)

        coordinator._handle_online_event = record
        coordinator._begin_resync = spy

    @property
    def game(self):
        return self.app.game

    def plies(self):
        return len(self.game.match.move_history)

    def sans(self):
        return [entry.san for entry in self.game.match.move_history]


def _pair(addr, white_uuid, black_uuid):
    """Match two real clients and hand back each one with its game_start."""
    a, b = OnlineClient(), OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": white_uuid,
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "white"})
    b.connect(addr, {"nickname": "Bob", "client_uuid": black_uuid,
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "black"})
    start_a, start_b = wait_for(a, "game_start"), wait_for(b, "game_start")
    assert start_a is not None and start_b is not None, "the pairing never landed"
    return _Seat(a, start_a.payload), _Seat(b, start_b.payload)


def _seats(server_with_app, monkeypatch, white_uuid, black_uuid):
    """Build both seats against the running server, with the reconnect probe
    pointed at it too so no test ever reaches for the real internet."""
    port, app = server_with_app
    monkeypatch.setenv("CHESS_SERVER_ADDR", f"localhost:{port}")
    white, black = _pair(f"localhost:{port}", white_uuid, black_uuid)
    return white, black, app


def _room(app):
    active = list(app.state.rooms._active.values())
    assert len(active) == 1, "expected exactly one paired room"
    return active[0]


def _pump(seats, seconds):
    """Run real frames on both apps for a wall-clock window."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        for seat in seats:
            seat.app.draw_frame()
        time.sleep(FRAME_SLEEP_SECONDS)


def _pump_until(seats, predicate, timeout=SETTLE_TIMEOUT_SECONDS):
    """Run real frames on both apps until a condition holds, or give up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for seat in seats:
            seat.app.draw_frame()
        if predicate():
            return True
        time.sleep(FRAME_SLEEP_SECONDS)
    return predicate()


def _both_at(seats, ply):
    return lambda: all(seat.plies() == ply for seat in seats)


def _quiet_move(seats, mover, frm, to, ply):
    """Play a non-capturing move the way the board does: ask the gate (which
    lets a quiet move through online), land it locally, then wait for the
    server's confirmation to reach both boards."""
    from_sq, to_sq = square_from_coord(frm), square_from_coord(to)
    assert mover.game.skillcheck_session.skillcheck_gate(from_sq, to_sq) is False
    assert mover.game.match.try_move(from_sq, to_sq).legal
    assert _pump_until(seats, _both_at(seats, ply)), f"{frm}{to} never reached both boards"


def _force_wheel(room, frm, to):
    """Pick a room secret whose roll turns this capture into a wheel.

    Every kind owns a quarter of the capture roll, so 8000 misses would mean
    the room is not at the capture at all rather than bad luck."""
    from_sq, to_sq = square_from_coord(frm), square_from_coord(to)
    for i in range(8000):
        secret = f"force-wheel-{i}"
        if online.select_kind(secret, room.plies_ever, room.backend, from_sq, to_sq,
                              room.skillcheck_locks) == SkillCheckKind.WHEEL:
            room.skillcheck_secret = secret
            return
    raise AssertionError(
        "no wheel secret in 8000 tries: plies_ever={} turn={} locks={}".format(
            room.plies_ever, room.backend.turn, room.skillcheck_locks))


def _winning_elapsed(pending):
    """Aim at the middle of the widest window the armed check can be won in."""
    window = _widest_win_window(pending.kind, pending.challenge, float(pending.deadline_ms))
    assert window is not None, "no winning window for the armed check"
    lo, hi = window
    assert hi - lo >= 2 * _SLEEP_LEAD_MS, \
        "the win window must absorb the sleep lead in both directions"
    return (lo + hi) // 2


def _win_capture(seats, mover, room, frm, to, ply):
    """Play a capture through the real hold gate and beat the check the server
    arms for it, so the ply lands on both boards."""
    _force_wheel(room, frm, to)
    from_sq, to_sq = square_from_coord(frm), square_from_coord(to)
    assert mover.game.skillcheck_session.skillcheck_gate(from_sq, to_sq) is True, \
        "an online capture is held back, never applied locally"
    assert _pump_until(seats, lambda: room.pending_skillcheck is not None), \
        "the server never armed the check"
    pending = room.pending_skillcheck
    assert pending.kind == SkillCheckKind.WHEEL
    elapsed = _winning_elapsed(pending)
    time.sleep((elapsed - _SLEEP_LEAD_MS) / 1000.0)  # land in [E, E+lag_bound] -> scored at E
    mover.client.send_skill_check_shot(elapsed)
    assert _pump_until(seats, _both_at(seats, ply)), \
        f"the won capture {frm}{to} never landed on both boards"


def test_a_recapture_lands_on_both_boards_and_draws_no_directive(
        server_with_app, monkeypatch):
    """1.e4 e5 2.Nf3 Nc6 3.Nxe5 Nxe5 -- the last two plies share a SAN, which
    is what a recapture always looks like. Both must land on both boards, and
    the heartbeats that follow must leave the server with nothing to correct."""
    white, black, app = _seats(server_with_app, monkeypatch, fake_uuid4(41), fake_uuid4(42))
    seats = (white, black)
    _quiet_move(seats, white, "e2", "e4", 1)
    _quiet_move(seats, black, "e7", "e5", 2)
    _quiet_move(seats, white, "g1", "f3", 3)
    _quiet_move(seats, black, "b8", "c6", 4)

    room = _room(app)
    _win_capture(seats, white, room, "f3", "e5", 5)
    _win_capture(seats, black, room, "c6", "e5", 6)

    expected = ["e4", "e5", "Nf3", "Nc6", "Nxe5", "Nxe5"]
    assert white.sans() == expected, "the mover's own recapture is not an echo"
    assert black.sans() == expected
    assert [entry.san for entry in room.backend.move_history] == expected
    assert white.resyncs == [] and black.resyncs == []

    _pump(seats, QUIET_WINDOW_SECONDS)
    assert "resync_directive" not in white.events, "the server had nothing to correct"
    assert "resync_directive" not in black.events
    assert white.resyncs == [] and black.resyncs == []
    assert white.app.coordinator._resyncing is False
    assert black.app.coordinator._resyncing is False
    assert white.plies() == black.plies() == len(room.backend.move_history) == 6

    white.client.disconnect()
    black.client.disconnect()


def test_the_abort_badge_survives_the_first_move_on_the_real_wire(
        server_with_app, monkeypatch):
    """#95 over the wire: the server pushes idle_window right behind the
    move_applied for white's first move, and the animation that finishes a
    couple of hundred milliseconds later must leave that window alone."""
    white, black, _app = _seats(server_with_app, monkeypatch, fake_uuid4(43), fake_uuid4(44))
    seats = (white, black)
    _quiet_move(seats, white, "e2", "e4", 1)
    assert _pump_until(seats, lambda: black.game._idle_window is not None), \
        "the server never pushed the abort window"
    _pump(seats, ANIMATION_WINDOW_SECONDS)

    for seat in seats:
        applied = seat.events.index("move_applied")
        assert "idle_window" in seat.events[applied:], \
            "the forced push follows the move on the wire"
    assert not black.game.board.is_animating(), "the animation had time to finish"
    window = black.game._idle_window
    assert window is not None, "the landing is not what clears the window"
    assert window.color == PieceColor.BLACK
    assert white.game._idle_window is not None

    # The badge is held back for the first tenth of the window, so read the
    # strips from seven seconds in rather than waiting there.
    shown_at = window.deadline_ms - int(window.total_seconds * 1000) + 7_000
    monkeypatch.setattr(pg.time, "get_ticks", lambda: shown_at)
    turn = black.game.match.current_turn()
    assert black.game._strip_state(PieceColor.BLACK, turn, False)["auto_end_label"] == "Abort in"
    assert black.game._strip_state(PieceColor.WHITE, turn, False)["auto_end_label"] is None
    assert white.game._strip_state(PieceColor.BLACK, turn, False)["auto_end_label"] == "Abort in"

    white.client.disconnect()
    black.client.disconnect()
