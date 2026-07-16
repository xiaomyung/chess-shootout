"""End-to-end skill-checks: two real OnlineClients pair against a real uvicorn
server over real HTTP + WebSockets, play to a capture, and run the wheel through
to a WIN / FAIL / resume. The protocol (skill_check_required, skill_check_spectate,
the shot, skill_check_result, move_applied's kind/won, /resume's skillcheck_log)
flows over the wire unfaked; only the kind is forced (server-secret) and the room's
skillcheck_log is read directly, so the assertions are deterministic.

A win shot exploits the lag-comp clamp: the server adjudicates at the client's
claimed elapsed when the real arrival is within [E, E+200ms], so sleeping E ms then
sending client_elapsed=E makes the server score the geometry at exactly E."""
import time

from chessshootout.backend.utils import Square
from chessshootout.online.client import OnlineClient, fetch_resume
from chessshootout.skillcheck import online
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome
from tests.helpers import fake_uuid4


def _wait_for(client, type_name, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ev in client.drain_inbound():
            if ev.type == type_name:
                return ev
        time.sleep(0.02)
    return None


def _pair(addr, white_uuid, black_uuid):
    a = OnlineClient()
    a.connect(addr, {"nickname": "Alice", "client_uuid": white_uuid,
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "white"})
    b = OnlineClient()
    b.connect(addr, {"nickname": "Bob", "client_uuid": black_uuid,
                     "time_minutes": 5, "increment_seconds": 0,
                     "side_preference": "black"})
    assert _wait_for(a, "game_start") is not None
    assert _wait_for(b, "game_start") is not None
    return a, b


def _room(app):
    active = list(app.state.rooms._active.values())
    assert len(active) == 1, "expected exactly one paired room"
    return active[0]


def _force_wheel(room):
    frm, to = Square(4, 4), Square(3, 3)  # exd5
    for i in range(8000):
        secret = "force-wheel-{}".format(i)
        if online.select_kind(secret, room.plies_ever, room.backend, frm, to,
                              room.skillcheck_locks) == SkillCheckKind.WHEEL:
            room.skillcheck_secret = secret
            return
    raise AssertionError("no wheel secret found")


# How a win is made deterministic under real CI jitter:
#   The client sleeps (E - SLEEP_LEAD_MS) then sends client_elapsed = E. The server
#   adjudicates min(max(E, raw - lag_bound), raw), where raw is the real arrival gap.
#   * if the packet lands at raw in [E, E+lag_bound]  -> scored EXACTLY E (the win moment)
#   * if it lands a touch early, raw in [E - SLEEP_LEAD, E) -> scored at raw
#   So we aim E at the TOP of the widest win window: a late-ish arrival is pinned to
#   E (a win), and an early arrival down to (E - SLEEP_LEAD) still falls inside the
#   window provided the window is at least SLEEP_LEAD wide. SLEEP_LEAD is kept small
#   (30ms) and the wheel's opening arc is ~120ms wide, so both directions are safe.
_SLEEP_LEAD_MS = 30


def _widest_win_window(kind, ch, deadline):
    best = None
    e = int(online.SKILLCHECK_HUMAN_FLOOR_MS) + 1
    end = int(deadline)
    while e < end:
        if online.shot_wins(kind, ch, e, 0, deadline):
            start = e
            while e < end and online.shot_wins(kind, ch, e, 0, deadline):
                e += 1
            if best is None or (e - 1 - start) > (best[1] - best[0]):
                best = (start, e - 1)
        else:
            e += 1
    return best


def _winning_elapsed(req):
    kind = SkillCheckKind(req["kind"])
    ch = online.challenge_from(kind, req["seed"], int(req["value_diff"]))
    deadline = float(req["deadline_ms"])
    window = _widest_win_window(kind, ch, deadline)
    assert window is not None, "no winning window for the stored seed"
    lo, hi = window
    assert hi - lo > _SLEEP_LEAD_MS, "the win window must absorb the sleep lead both ways"
    return hi  # aim the shot at the top of the window


def _force_aim(room):
    frm, to = Square(4, 4), Square(3, 3)  # exd5
    for i in range(8000):
        secret = "force-aim-{}".format(i)
        if online.select_kind(secret, room.plies_ever, room.backend, frm, to,
                              room.skillcheck_locks) == SkillCheckKind.AIM:
            room.skillcheck_secret = secret
            return
    raise AssertionError("no aim secret found")


def _move(mover, a, b, frm, to):
    mover.send_move(frm, to)
    assert _wait_for(a, "move_applied") is not None
    assert _wait_for(b, "move_applied") is not None


def _reach_capture(a, b, app, force=_force_wheel):
    _move(a, a, b, "e2", "e4")            # 1. e4 (white)
    _move(b, a, b, "d7", "d5")            # 1... d5 (black)
    room = _room(app)
    force(room)
    a.send_move("e4", "d5")               # 2. exd5 -> fires the check
    req = _wait_for(a, "skill_check_required")
    spec = _wait_for(b, "skill_check_spectate")
    assert req is not None and spec is not None, "the check did not fire over the wire"
    return room, req.payload, spec.payload


def test_capture_fires_required_to_mover_and_spectate_to_opponent(server_with_app):
    port, app = server_with_app
    a, b = _pair("localhost:{}".format(port), fake_uuid4(21), fake_uuid4(22))
    room, req, spec = _reach_capture(a, b, app)
    assert req["kind"] == "wheel" == spec["kind"]
    assert req["seed"] == spec["seed"] == room.pending_skillcheck.seed
    assert req["deadline_ms"] == spec["deadline_ms"] == 5000.0, "5+0 -> the 5s cap"
    assert (req["from"], req["to"]) == ("e4", "d5")
    a.disconnect()
    b.disconnect()


def test_a_won_check_applies_the_move_and_records_the_win(server_with_app):
    port, app = server_with_app
    a, b = _pair("localhost:{}".format(port), fake_uuid4(23), fake_uuid4(24))
    room, req, spec = _reach_capture(a, b, app)
    elapsed = _winning_elapsed(req)
    time.sleep((elapsed - _SLEEP_LEAD_MS) / 1000.0)  # land in [E, E+lag_bound] -> scored at E
    a.send_skill_check_shot(elapsed)
    a_applied = _wait_for(a, "move_applied")
    b_applied = _wait_for(b, "move_applied")
    assert a_applied.payload["san"] == "exd5"
    assert a_applied.payload["skill_check_kind"] == "wheel"
    assert a_applied.payload["skill_check_won"] is True
    assert b_applied.payload["skill_check_kind"] == "wheel"
    assert room.skillcheck_log == [SkillCheckOutcome(3, "wheel", True, "exd5")]
    a.disconnect()
    b.disconnect()


def test_a_failed_check_locks_the_move_and_records_the_whiff(server_with_app):
    port, app = server_with_app
    a, b = _pair("localhost:{}".format(port), fake_uuid4(25), fake_uuid4(26))
    room, req, spec = _reach_capture(a, b, app)
    a.send_skill_check_shot(0)  # an immediate sub-floor shot fails the one-shot wheel
    a_result = _wait_for(a, "skill_check_result")
    b_result = _wait_for(b, "skill_check_result")
    assert a_result.payload["won"] is False
    assert b_result.payload["won"] is False, "the opponent is told the verdict too"
    assert (Square(4, 4), Square(3, 3)) in room.skillcheck_locks, "the move is greyed"
    assert room.skillcheck_log == [SkillCheckOutcome(3, "wheel", False, "exd5")]
    assert len(room.backend.move_history) == 2, "the capture never landed"
    a.disconnect()
    b.disconnect()


def test_resume_after_a_won_check_carries_the_skillcheck_log(server_with_app):
    port, app = server_with_app
    addr = "localhost:{}".format(port)
    a, b = _pair(addr, fake_uuid4(27), fake_uuid4(28))
    room, req, spec = _reach_capture(a, b, app)
    elapsed = _winning_elapsed(req)
    time.sleep((elapsed - _SLEEP_LEAD_MS) / 1000.0)  # land in [E, E+lag_bound] -> scored at E
    a.send_skill_check_shot(elapsed)
    assert _wait_for(a, "move_applied") is not None
    assert _wait_for(b, "move_applied") is not None
    payload = fetch_resume(addr, a._room_id, a._session_token)
    assert payload["skillcheck_log"] == [
        {"ply": 3, "kind": "wheel", "won": True, "san": "exd5"}]
    a.disconnect()
    b.disconnect()


def test_resume_pending_uses_wire_alias_keys(server_with_app):
    # the /resume dump the client hands the frontend uses the SAME `from`/`to`
    # alias keys as every WS frame (model_dump(by_alias=True)). A field-name dump
    # here fed GameScreen keys it never reads and silently broke pending recovery
    # and shared-arrow restore.
    port, app = server_with_app
    addr = "localhost:{}".format(port)
    a, b = _pair(addr, fake_uuid4(29), fake_uuid4(30))
    room, req, spec = _reach_capture(a, b, app, force=_force_aim)
    assert req["kind"] == "aim", "an aim check is held but deliberately left unresolved"
    payload = fetch_resume(addr, a._room_id, a._session_token)
    pending = payload["pending_skillcheck"]
    assert pending is not None, "the live pending check rides the resume payload"
    assert pending["from"] == "e4", "alias key carries the capture-from square"
    assert pending["to"] == "d5"
    assert "from_sq" not in pending and "to_sq" not in pending, \
        "no field-name key leaks into the resume dump"
    a.disconnect()
    b.disconnect()
