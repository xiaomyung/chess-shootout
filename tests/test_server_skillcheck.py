"""The authoritative server skill-check state machine, driven through the real
handlers with a fake clock and recording websockets. This is the security core:
the move gate (pending/locked guards before any mutation), the one-shot-latch shot
handler (server-owned miss_count, deadline re-check), WIN/FAIL resolution, terminal
hygiene (resign/flag clear pending, takeback blocked, ping no-resync), the
single-resolver sweep deadline, the server-secret selection, and the resume payload.

The geometry seed is server-generated per check, so winning/failing tests READ the
stored pending.seed and solve for an elapsed the pure engine scores — they never
guess the seed (mirrors how the server itself adjudicates).
"""

import pytest

import json

from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.backend.utils import Square, coord_from_square
from chessshootout.server.app import create_app
from chessshootout.server.broadcasts import resolve_skillcheck_fail
from fastapi.testclient import TestClient

from chessshootout.server.handlers import (
    handle_move, handle_ping, handle_skill_check_shot, handle_takeback_request,
    handle_takeback_response,
)
from chessshootout.server.protocol import PROTOCOL_VERSION, Reason
from chessshootout.skillcheck import online
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome
from tests.helpers import FakeClock, fake_uuid4, make_backend, piece, sq

ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)
WHEEL = SkillCheckKind.WHEEL
AIM = SkillCheckKind.AIM


class RecordingWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)

    def types(self):
        return [m["type"] for m in self.sent]

    def of_type(self, t):
        return [m for m in self.sent if m["type"] == t]


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


async def _pair(app):
    rooms = app.state.rooms
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=5, increment_seconds=0, side_preference="black")
    return list(rooms._active.values())[0]


def _qxp_backend():
    return make_backend({
        sq(7, 4): piece(PieceType.KING, PieceColor.WHITE),
        sq(0, 4): piece(PieceType.KING, PieceColor.BLACK),
        sq(4, 3): piece(PieceType.QUEEN, PieceColor.WHITE),
        sq(3, 3): piece(PieceType.PAWN, PieceColor.BLACK),
    })


def _seed_for(backend, frm, to, want_kind, locks=None):
    locks = locks or set()
    for i in range(4000):
        secret = "secret-{}".format(i)
        if online.select_kind(secret, 0, backend, frm, to, locks) == want_kind:
            return secret
    raise AssertionError("no secret for {}".format(want_kind))


async def _capture_room(app, clock, kind):
    room = await _pair(app)
    room.backend = _qxp_backend()
    room.first_move_at = clock()
    room.started_at = clock()
    frm, to = Square(4, 3), Square(3, 3)
    room.skillcheck_secret = _seed_for(room.backend, frm, to, kind)
    ws_w, ws_b = RecordingWS(), RecordingWS()
    app.state.connections.add(room.room_id, room.white.client_uuid, ws_w)
    app.state.connections.add(room.room_id, room.black.client_uuid, ws_b)
    return room, ws_w, ws_b, frm, to


def _move_raw(frm, to, promotion=None):
    payload = {"type": "move", "from": coord_from_square(frm), "to": coord_from_square(to)}
    if promotion is not None:
        payload["promotion"] = promotion
    return json.dumps(payload)


def _win_elapsed(pending):
    ch = online.challenge_from(pending.kind, pending.seed, pending.value_diff)
    for e in range(int(online.SKILLCHECK_HUMAN_FLOOR_MS), int(online.SKILLCHECK_DEADLINE_MS)):
        if online.shot_wins(pending.kind, ch, e, pending.miss_count):
            return e
    raise AssertionError("no winning elapsed for the stored seed")


def _aim_miss_elapsed(pending):
    ch = online.challenge_from(pending.kind, pending.seed, pending.value_diff)
    for e in range(int(online.SKILLCHECK_HUMAN_FLOOR_MS), 2500):
        if (not online.shot_wins(AIM, ch, e, pending.miss_count)
                and not online.aim_expired(ch, e, pending.miss_count)):
            return e
    raise AssertionError("no aim-miss elapsed")


def _wheel_loss_elapsed(pending):
    ch = online.challenge_from(pending.kind, pending.seed, pending.value_diff)
    for e in range(int(online.SKILLCHECK_HUMAN_FLOOR_MS), int(online.SKILLCHECK_DEADLINE_MS)):
        if not online.shot_wins(WHEEL, ch, e, pending.miss_count):
            return e
    raise AssertionError("no losing wheel elapsed for the stored seed")


async def _shoot_at(app, clock, room, color, elapsed_ms):
    start = room.pending_skillcheck.start_ms
    clock.set((start + elapsed_ms) / 1000.0)
    ws = app.state.connections.get_for_color(room, color)
    raw = json.dumps({"type": "skill_check_shot", "client_elapsed_ms": elapsed_ms})
    return await handle_skill_check_shot(app, ws, room, color, raw)


# ---- the move gate ---------------------------------------------------------

@pytest.mark.asyncio
async def test_quiet_move_applies_immediately_no_check(app, clock):
    room = await _pair(app)
    room.first_move_at = clock()
    ws = RecordingWS()
    app.state.connections.add(room.room_id, room.white.client_uuid, ws)
    out = await handle_move(app, ws, room, "white", _move_raw(Square(6, 4), Square(4, 4)))
    assert out == "applied"
    assert room.pending_skillcheck is None
    assert len(room.backend.move_history) == 1


@pytest.mark.asyncio
async def test_capture_fires_check_and_does_not_mutate_the_board(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    out = await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    assert out == "skillcheck:wheel"
    assert room.pending_skillcheck is not None
    assert len(room.backend.move_history) == 0, "selection only probes; the board never mutated"


@pytest.mark.asyncio
async def test_required_to_mover_enriched_spectate_to_opponent(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    assert ws_w.of_type("skill_check_required"), "mover gets the playable challenge"
    assert not ws_w.of_type("skill_check_spectate")
    spec = ws_b.of_type("skill_check_spectate")
    assert spec and spec[0]["kind"] == "aim"
    assert spec[0]["seed"] == room.pending_skillcheck.seed, "the opponent mirrors the real seed"
    assert (spec[0]["from"], spec[0]["to"]) == ("d4", "d5"), "anchored at the move squares"
    req = ws_w.of_type("skill_check_required")[0]
    assert (req["seed"], req["value_diff"]) == (spec[0]["seed"], spec[0]["value_diff"]), \
        "both sides reconstruct the identical challenge"


@pytest.mark.asyncio
async def test_shot_relays_the_winning_position_to_the_opponent(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    elapsed = _win_elapsed(room.pending_skillcheck)
    await _shoot_at(app, clock, room, "white", elapsed)
    relay = ws_b.of_type("skill_check_spectate_shot")
    assert relay and relay[0]["won"] is True
    assert relay[0]["miss_count"] == 0, "the pre-shot count the mover fired at"
    assert relay[0]["elapsed_ms"] == elapsed, "the server-adjudicated position, not raw client time"


@pytest.mark.asyncio
async def test_shot_relays_an_aim_miss_to_the_opponent(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", _aim_miss_elapsed(room.pending_skillcheck))
    assert out == "skillcheck_miss"
    relay = ws_b.of_type("skill_check_spectate_shot")
    assert relay and relay[0]["won"] is False
    assert relay[0]["miss_count"] == 0, "relayed at the pre-increment count"
    assert room.pending_skillcheck.miss_count == 1, "the server escalates after the relay"


@pytest.mark.asyncio
async def test_shot_relays_a_wheel_fail_to_the_opponent(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", _wheel_loss_elapsed(room.pending_skillcheck))
    assert out == "skillcheck_fail"
    relay = ws_b.of_type("skill_check_spectate_shot")
    assert relay and relay[0]["won"] is False


@pytest.mark.asyncio
async def test_shot_relay_is_skipped_when_the_opponent_is_gone(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    app.state.connections.remove(room.room_id, room.black.client_uuid, ws_b)
    out = await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    assert out.startswith("applied"), "the win still resolves with no opponent to relay to"
    assert not ws_b.of_type("skill_check_spectate_shot")


@pytest.mark.asyncio
async def test_move_while_pending_is_rejected_without_mutation(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    before = room.pending_skillcheck
    out = await handle_move(app, ws_w, room, "white", _move_raw(Square(7, 4), Square(6, 4)))
    assert out == "pending"
    assert room.pending_skillcheck is before, "the held check is untouched"
    assert len(room.backend.move_history) == 0
    assert ws_w.of_type("error")[-1]["reason"] == Reason.SKILLCHECK_PENDING


# ---- WIN / FAIL resolution -------------------------------------------------

@pytest.mark.asyncio
async def test_winning_shot_applies_the_move_and_clears_pending(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    assert out == "applied"
    assert room.pending_skillcheck is None
    assert len(room.backend.move_history) == 1
    applied = ws_b.of_type("move_applied")[-1]
    assert applied["skill_check_kind"] == "wheel" and applied["skill_check_won"] is True


@pytest.mark.asyncio
async def test_failing_shot_locks_the_move_clears_pending_broadcasts_result(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", 50)  # below the human floor -> fail
    assert out == "skillcheck_fail"
    assert room.pending_skillcheck is None
    assert (frm, to) in room.skillcheck_locks
    assert len(room.backend.move_history) == 0
    res = ws_w.of_type("skill_check_result")[-1]
    assert res["won"] is False


@pytest.mark.asyncio
async def test_wheel_is_one_shot_a_non_winning_shot_fails(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    ch = online.challenge_from(WHEEL, room.pending_skillcheck.seed,
                               room.pending_skillcheck.value_diff)
    miss = next(e for e in range(120, 800) if not online.shot_wins(WHEEL, ch, e))
    out = await _shoot_at(app, clock, room, "white", miss)
    assert out == "skillcheck_fail", "a wheel never stays pending after its single shot"


@pytest.mark.asyncio
async def test_late_shot_past_deadline_fails_even_if_geometry_would_win(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", int(online.SKILLCHECK_DEADLINE_MS) + 200)
    assert out == "skillcheck_fail"
    assert (frm, to) in room.skillcheck_locks


# ---- AIM multi-shot --------------------------------------------------------

@pytest.mark.asyncio
async def test_aim_miss_keeps_pending_and_increments_server_miss_count(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", _aim_miss_elapsed(room.pending_skillcheck))
    assert out == "skillcheck_miss"
    assert room.pending_skillcheck is not None
    assert room.pending_skillcheck.miss_count == 1
    assert not ws_b.of_type("skill_check_result"), "a miss broadcasts nothing"


@pytest.mark.asyncio
async def test_aim_hit_after_a_miss_applies_the_move(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", _aim_miss_elapsed(room.pending_skillcheck))
    out = await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    assert out == "applied"
    assert len(room.backend.move_history) == 1


# ---- shot guards (opponent / no-pending / latch) ---------------------------

@pytest.mark.asyncio
async def test_shot_with_no_pending_is_a_noop(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    out = await handle_skill_check_shot(app, ws_w, room, "white", '{"type":"skill_check_shot"}')
    assert out == "noop"


@pytest.mark.asyncio
async def test_opponent_shot_is_ignored_not_a_fail(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await handle_skill_check_shot(app, ws_b, room, "black", '{"type":"skill_check_shot"}')
    assert out == "noop"
    assert room.pending_skillcheck is not None, "the opponent cannot grief the mover's check"
    assert not ws_b.of_type("skill_check_result")


@pytest.mark.asyncio
async def test_pending_is_a_one_shot_latch(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    out = await handle_skill_check_shot(app, ws_w, room, "white", '{"type":"skill_check_shot"}')
    assert out == "noop", "a second shot after resolution finds pending cleared"
    assert len(room.backend.move_history) == 1, "the move applied exactly once"


# ---- locks -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_locked_move_is_rejected_outright_not_rerolled(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", 50)  # fail -> lock
    out = await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    assert out == "locked"
    assert room.pending_skillcheck is None, "the locked move never re-fires a check"
    assert ws_w.of_type("error")[-1]["reason"] == Reason.MOVE_LOCKED


@pytest.mark.asyncio
async def test_locks_clear_on_the_next_applied_ply(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", 50)
    assert room.skillcheck_locks
    await handle_move(app, ws_w, room, "white", _move_raw(Square(7, 4), Square(6, 4)))
    assert room.skillcheck_locks == set(), "an applied move clears the per-ply locks"


# ---- terminal hygiene ------------------------------------------------------

@pytest.mark.asyncio
async def test_resign_clears_pending_and_a_later_shot_is_noop(app, clock):
    from chessshootout.server.handlers import handle_resign
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await handle_resign(app, ws_w, room, "white", "{}")
    assert room.pending_skillcheck is None
    out = await handle_skill_check_shot(app, ws_w, room, "white", '{"type":"skill_check_shot"}')
    assert out == "noop"


@pytest.mark.asyncio
async def test_takeback_is_blocked_while_a_check_is_pending(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    room.takeback_offered_by = None
    out = await handle_takeback_request(app, ws_b, room, "black", "{}")
    assert out == "pending", "undo while a move is held would corrupt history"


@pytest.mark.asyncio
async def test_ping_emits_no_resync_while_pending(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await handle_ping(app, ws_w, room, "white", '{"type":"ping","ply":0}')
    assert out == "ping_pending"
    assert not ws_w.of_type("resync_directive"), "a held move legitimately sits at the same ply"
    assert room.white.desync_active is False


# ---- the single-resolver sweep deadline ------------------------------------

@pytest.mark.asyncio
async def test_sweep_auto_fails_a_pending_check_at_the_deadline(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    clock.advance((online.SKILLCHECK_DEADLINE_MS + 100) / 1000.0)
    await app.state.sweep.step_skillcheck_deadline()
    assert room.pending_skillcheck is None
    assert (frm, to) in room.skillcheck_locks
    assert room.result is None, "auto-fail locks the move; it does not end the game"
    assert ws_b.of_type("skill_check_result"), "the spectator is told the check failed"


@pytest.mark.asyncio
async def test_sweep_auto_fails_even_while_the_mover_is_disconnected(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    app.state.rooms.mark_disconnected(room.room_id, "white")
    clock.advance((online.SKILLCHECK_DEADLINE_MS + 100) / 1000.0)
    await app.state.sweep.step_skillcheck_deadline()
    assert room.pending_skillcheck is None, "the deadline runs regardless of presence"


@pytest.mark.asyncio
async def test_sweep_leaves_a_live_pending_check_alone(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    clock.advance(1.0)  # still well within the 5s window
    await app.state.sweep.step_skillcheck_deadline()
    assert room.pending_skillcheck is not None


# ---- clock keeps running on the mover during the check ---------------------

@pytest.mark.asyncio
async def test_movers_clock_keeps_running_during_a_held_check(app, clock):
    room = await _pair(app)
    room.backend = _qxp_backend()
    room.backend.setup_clock(60, 0, now_provider=clock)
    room.first_move_at = clock()
    frm, to = Square(4, 3), Square(3, 3)
    room.skillcheck_secret = _seed_for(room.backend, frm, to, WHEEL)
    ws_w, ws_b = RecordingWS(), RecordingWS()
    app.state.connections.add(room.room_id, room.white.client_uuid, ws_w)
    app.state.connections.add(room.room_id, room.black.client_uuid, ws_b)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    before = room.backend.clock.white_remaining
    clock.advance(2.0)
    room.backend.tick_clock()
    assert room.backend.clock.white_remaining < before, "still white's turn; their clock ticks"


# ---- selection secret never leaks ------------------------------------------

@pytest.mark.asyncio
async def test_selection_secret_never_appears_in_any_client_payload(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    secret = room.skillcheck_secret
    assert secret, "the room has a secret"
    blob = json.dumps(ws_w.sent + ws_b.sent)
    assert secret not in blob, "the selection secret is never sent to either client"


@pytest.mark.asyncio
async def test_secret_is_fresh_per_room_at_pairing(app, clock):
    await _pair(app)
    await app.state.rooms.enqueue(
        client_uuid=fake_uuid4(3), nickname="C", session_token="tc",
        time_minutes=5, increment_seconds=0, side_preference="white")
    await app.state.rooms.enqueue(
        client_uuid=fake_uuid4(4), nickname="D", session_token="td",
        time_minutes=5, increment_seconds=0, side_preference="black")
    rooms = [r for r in app.state.rooms._active.values()]
    secrets_seen = {r.skillcheck_secret for r in rooms}
    assert len(secrets_seen) == len(rooms) >= 2, "each room gets its own secret"
    assert all(s for s in secrets_seen)


# ---- ms timing chokepoint --------------------------------------------------

@pytest.mark.asyncio
async def test_now_ms_is_seconds_times_1000(app, clock):
    clock.set(12.5)
    assert app.state.now_ms() == 12500.0


@pytest.mark.asyncio
async def test_pending_start_ms_is_stamped_in_milliseconds(app, clock):
    clock.set(7.0)
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    assert room.pending_skillcheck.start_ms == 7000.0
    assert room.pending_skillcheck.expires_at_ms == 7000.0 + online.SKILLCHECK_DEADLINE_MS


# ---- resume carries the live pending + locks -------------------------------

def _resume_payload(app, room, color):
    from chessshootout.server.app import _pending_skillcheck_wire
    return _pending_skillcheck_wire(room, app.state.now_ms)


@pytest.mark.asyncio
async def test_resume_wire_carries_live_pending_with_elapsed(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    clock.advance(1.8)
    wire = _resume_payload(app, room, "white")
    assert wire is not None
    assert wire.kind == "aim"
    assert wire.seed == room.pending_skillcheck.seed
    assert wire.elapsed_ms == pytest.approx(1800.0, abs=1.0), "the timer never restarts from zero"


@pytest.mark.asyncio
async def test_resume_wire_is_none_after_the_check_resolves(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", 50)  # fail
    assert _resume_payload(app, room, "white") is None, "a resolved check leaves a free turn"


@pytest.mark.asyncio
async def test_resume_seed_is_identical_across_repeated_resumes(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    a = _resume_payload(app, room, "white")
    b = _resume_payload(app, room, "white")
    assert a.seed == b.seed == room.pending_skillcheck.seed, "resume never re-rolls the seed"


# ---- resolve_skillcheck_fail is itself a latch -----------------------------

@pytest.mark.asyncio
async def test_resolve_fail_is_idempotent(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    first = await resolve_skillcheck_fail(app.state.connections, room)
    second = await resolve_skillcheck_fail(app.state.connections, room)
    assert first is not None and second is None, "a second resolve finds pending already cleared"


# ---- bounded lag-comp: the shot carries the client's rendered elapsed -------

async def _shoot_claiming(app, clock, room, color, *, arrives_at_ms, claims_ms):
    """A shot that physically lands at arrives_at_ms but reports claims_ms as the elapsed."""
    clock.set((room.pending_skillcheck.start_ms + arrives_at_ms) / 1000.0)
    ws = app.state.connections.get_for_color(room, color)
    raw = json.dumps({"type": "skill_check_shot", "client_elapsed_ms": claims_ms})
    return await handle_skill_check_shot(app, ws, room, color, raw)


@pytest.mark.asyncio
async def test_honest_shot_is_judged_at_the_clients_rendered_elapsed(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    win = _win_elapsed(room.pending_skillcheck)
    out = await _shoot_at(app, clock, room, "white", win)
    assert out.startswith("applied"), "the server judges the exact moment the player saw"


@pytest.mark.asyncio
async def test_network_lag_inside_the_bound_does_not_steal_a_clean_hit(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    win = _win_elapsed(room.pending_skillcheck)
    # claims the visual win moment, but the packet lands 80ms later — still inside [raw-bound, raw]
    out = await _shoot_claiming(app, clock, room, "white", arrives_at_ms=win + 80, claims_ms=win)
    assert out.startswith("applied"), "latency inside the bound never steals a clean hit"


@pytest.mark.asyncio
async def test_a_too_early_claim_is_clamped_to_the_lag_bound(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    pending = room.pending_skillcheck
    ch = online.challenge_from(pending.kind, pending.seed, pending.value_diff)
    bounded = int(2000 - online.SKILLCHECK_LAG_BOUND_MS)
    out = await _shoot_claiming(app, clock, room, "white", arrives_at_ms=2000, claims_ms=0.0)
    expected = "applied" if online.shot_wins(WHEEL, ch, bounded, 0) else "skillcheck_fail"
    assert out.split(":")[0] == expected.split(":")[0], \
        "a forged-early claim is judged at raw-bound, never the impossible value it claimed"


# ---- the required message + pending wire carry the move squares -------------

@pytest.mark.asyncio
async def test_required_message_carries_the_move_squares(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    req = ws_w.of_type("skill_check_required")[-1]
    assert req["from"] == coord_from_square(frm)
    assert req["to"] == coord_from_square(to)
    assert req["promotion"] is None


@pytest.mark.asyncio
async def test_pending_wire_carries_squares_color_and_promotion(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    wire = _resume_payload(app, room, "white")
    assert wire.from_sq == coord_from_square(frm)
    assert wire.to_sq == coord_from_square(to)
    assert wire.color == "white"
    assert wire.promotion is None


@pytest.mark.asyncio
async def test_resume_wire_omits_a_pending_past_its_deadline(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    clock.advance((online.SKILLCHECK_DEADLINE_MS + 50) / 1000.0)
    assert room.pending_skillcheck is not None, "the sweep has not run yet"
    assert _resume_payload(app, room, "white") is None, \
        "a reconnect must not re-hand an already-dead check"


@pytest.mark.asyncio
async def test_shot_and_sweep_in_the_same_tick_resolve_exactly_once(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    ws_b.sent.clear()
    out = await _shoot_at(app, clock, room, "white", int(online.SKILLCHECK_DEADLINE_MS) + 10)
    await app.state.sweep.step_skillcheck_deadline()
    assert out == "skillcheck_fail"
    assert len(ws_b.of_type("skill_check_result")) == 1, "exactly one fail broadcast"


# ---- sweep aligns the AIM fail with the piece disappearing ------------------

@pytest.mark.asyncio
async def test_sweep_fails_an_aim_check_when_the_piece_has_shrunk(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    pending = room.pending_skillcheck
    pending.miss_count = 8  # heavy misses -> the victim shrinks to 0 well before 5s
    ch = online.challenge_from(pending.kind, pending.seed, pending.value_diff)
    gone_at = next(e for e in range(200, int(online.SKILLCHECK_DEADLINE_MS))
                   if online.aim_expired(ch, e, pending.miss_count))
    assert gone_at < online.SKILLCHECK_DEADLINE_MS, "the shrink outruns the 5s deadline"
    clock.set((pending.start_ms + gone_at + 1) / 1000.0)
    await app.state.sweep.step_skillcheck_deadline()
    assert room.pending_skillcheck is None, "the fail lands when the piece is gone, not at 5s"
    assert (frm, to) in room.skillcheck_locks


@pytest.mark.asyncio
async def test_sweep_does_not_early_fail_an_aim_check_while_the_piece_remains(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, AIM)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    clock.advance(0.5)  # piece still large, well inside the deadline
    await app.state.sweep.step_skillcheck_deadline()
    assert room.pending_skillcheck is not None, "an on-screen aim check is not swept early"


# ---- the server-authoritative skill-check log -------------------------------

@pytest.mark.asyncio
async def test_won_check_appends_an_outcome_to_the_server_log(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    assert room.skillcheck_log == [SkillCheckOutcome(1, "wheel", True, "Qxd5")]


@pytest.mark.asyncio
async def test_failed_check_appends_a_fail_outcome_with_the_whiffed_san(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", _wheel_loss_elapsed(room.pending_skillcheck))
    assert room.skillcheck_log == [SkillCheckOutcome(1, "wheel", False, "Qxd5")]
    assert len(room.backend.move_history) == 0, "a failed check lands no ply"


@pytest.mark.asyncio
async def test_sweep_resolved_fail_also_records_the_outcome(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await resolve_skillcheck_fail(app.state.connections, room)
    assert room.skillcheck_log == [SkillCheckOutcome(1, "wheel", False, "Qxd5")]


@pytest.mark.asyncio
async def test_a_pending_check_is_absent_from_the_log_until_it_resolves(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    assert room.pending_skillcheck is not None
    assert room.skillcheck_log == [], "an unresolved check is never recorded"
    await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    assert len(room.skillcheck_log) == 1, "recorded exactly once, at resolution"


@pytest.mark.asyncio
async def test_resume_endpoint_carries_the_skillcheck_log(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    resp = TestClient(app).post("/resume", json={
        "version": PROTOCOL_VERSION, "room_id": room.room_id, "session_token": "ta"})
    assert resp.status_code == 200
    assert resp.json()["skillcheck_log"] == [
        {"ply": 1, "kind": "wheel", "won": True, "san": "Qxd5"}]


@pytest.mark.asyncio
async def test_takeback_drops_the_outcomes_for_the_undone_ply(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    await _shoot_at(app, clock, room, "white", _win_elapsed(room.pending_skillcheck))
    assert len(room.skillcheck_log) == 1 and len(room.backend.move_history) == 1
    room.takeback_offered_by = "white"
    raw = json.dumps({"type": "takeback_response", "accept": True})
    await handle_takeback_response(app, ws_b, room, "black", raw)
    assert room.skillcheck_log == [], "the undone ply's outcome is gone"
    assert len(room.backend.move_history) == 0


@pytest.mark.asyncio
async def test_reset_for_rematch_clears_the_skillcheck_log(app, clock):
    room = await _pair(app)
    room.result = ("resignation", "white")
    room.skillcheck_log = [SkillCheckOutcome(1, "wheel", True, "Qxd5")]
    room.skillcheck_locks = {(Square(4, 3), Square(3, 3))}
    app.state.rooms.reset_for_rematch(room.room_id)
    assert room.skillcheck_log == []
    assert room.skillcheck_locks == set()


# ---- the server-owned time cap ---------------------------------------------

@pytest.mark.asyncio
async def test_handle_move_stamps_the_tc_capped_deadline(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    pending = room.pending_skillcheck
    assert pending.deadline_ms == online.SKILLCHECK_DEADLINE_MS, "5+0 -> the 5s base"
    assert pending.expires_at_ms == pending.start_ms + pending.deadline_ms
    req = ws_w.of_type("skill_check_required")[0]
    spec = ws_b.of_type("skill_check_spectate")[0]
    assert req["deadline_ms"] == pending.deadline_ms == spec["deadline_ms"]


@pytest.mark.asyncio
async def test_a_short_time_control_shrinks_the_check_deadline(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    room.time_minutes = 0.5  # 30s game -> 10% = 3s, below the 5s base
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    pending = room.pending_skillcheck
    assert pending.deadline_ms == 3000.0
    assert pending.expires_at_ms == pending.start_ms + 3000.0
    assert ws_w.of_type("skill_check_required")[0]["deadline_ms"] == 3000.0


@pytest.mark.asyncio
async def test_a_shot_past_the_capped_deadline_fails_even_under_the_base(app, clock):
    room, ws_w, ws_b, frm, to = await _capture_room(app, clock, WHEEL)
    room.time_minutes = 0.5  # deadline 3000ms
    await handle_move(app, ws_w, room, "white", _move_raw(frm, to))
    out = await _shoot_at(app, clock, room, "white", 3500)  # past 3000 cap, under 5000 base
    assert out == "skillcheck_fail"
    assert room.pending_skillcheck is None
    assert len(room.backend.move_history) == 0, "the move never lands past the capped deadline"
    assert room.skillcheck_log == [SkillCheckOutcome(1, "wheel", False, "Qxd5")]
