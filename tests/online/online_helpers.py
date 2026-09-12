"""
Shared infrastructure for the online tests. Two halves: the polls every
end-to-end file needs against real sockets -- step forward until a named event
shows up, gather a fixed window -- and the skill-check fixtures both the faked
and the real-server files build on, from the payloads a server would send to
the search for a seed that forces one check kind
"""
import time
from typing import Any

import pygame as pg
from fastapi import FastAPI

from chessshootout.backend.utils import Square, coord_from_square
from chessshootout.online.client import Event, OnlineClient
from chessshootout.server.protocol import SkillCheckSpectateMessage
from chessshootout.skillcheck import online
from chessshootout.skillcheck.triggers import compute_facts
from chessshootout.skillcheck.types import SkillCheckKind


POLL_INTERVAL_SECONDS = 0.02


def wait_for(client: OnlineClient, type_name: str,
             timeout: float = 15.0) -> Event | None:
    """
    Drain a client's inbound queue until an event of the wanted type arrives.
    Events stepped past on the way are discarded, so this is for presence
    assertions only; use collect_for when the events in between matter

    :param client: connected client whose inbound queue is polled
    :param type_name: the event type to stop on
    :param timeout: seconds to keep polling before giving up
    :returns: the first matching event, or None if the timeout ran out
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ev in client.drain_inbound():
            if ev.type == type_name:
                return ev
        time.sleep(POLL_INTERVAL_SECONDS)
    return None


def collect_for(client: OnlineClient, timeout: float) -> list[Event]:
    """
    Drain a client's inbound queue for a fixed wall-clock window and return
    everything seen. An assertion that nothing arrived is then about elapsed
    time rather than about polling luck

    :param client: connected client whose inbound queue is polled
    :param timeout: seconds to keep draining before returning
    :returns: every event that arrived during the window, oldest first
    """
    deadline = time.time() + timeout
    seen: list[Event] = []
    while time.time() < deadline:
        seen.extend(client.drain_inbound())
        time.sleep(POLL_INTERVAL_SECONDS)
    seen.extend(client.drain_inbound())
    return seen


SLEEP_LEAD_MS = 30


def room_of(app: FastAPI) -> Any:
    """
    Reach into a running server app for the one room its two clients paired
    into, which is how an e2e test reads server-side truth the wire never
    carries -- the skill-check secret, the pending check, plies_ever

    :param app: the FastAPI app the test server is running
    :returns: the single active room
    """
    active = list(app.state.rooms._active.values())
    assert len(active) == 1, "expected exactly one paired room"
    return active[0]


def force_kind(room: Any, frm: Square, to: Square, kind: SkillCheckKind) -> None:
    """
    Hunt for a room secret whose roll turns one capture into the wanted kind,
    so an e2e test can drive a named check without the client ever learning
    the secret. Each kind owns a quarter of the capture roll, so thousands of
    misses mean the room is not at that capture rather than bad luck

    :param room: the paired room whose secret is being replaced
    :param frm: square the capture starts from
    :param to: square it lands on
    :param kind: the check kind the roll has to select
    """
    for i in range(8000):
        secret = f"force-{kind.value}-{i}"
        if online.select_kind(secret, room.plies_ever, room.backend, frm, to,
                              room.skillcheck_locks) == kind:
            room.skillcheck_secret = secret
            return
    raise AssertionError(
        "no {} secret in 8000 tries: facts={} plies_ever={} turn={} locks={}".format(
            kind.value, compute_facts(room.backend, frm, to, room.skillcheck_locks),
            room.plies_ever, room.backend.turn, room.skillcheck_locks))


def widest_win_window(kind: SkillCheckKind, challenge: Any,
                      deadline_ms: float) -> tuple[int, int] | None:
    """
    Walk a check's whole timeline and find the longest unbroken stretch of
    elapsed times that win it, the window an e2e shot is aimed into

    :param kind: which check is being measured
    :param challenge: the geometry rebuilt from the check's seed
    :param deadline_ms: the check's deadline in milliseconds
    :returns: the widest winning window as (first ms, last ms), or None when
        the check cannot be won at all
    """
    best = None
    e = int(online.SKILLCHECK_HUMAN_FLOOR_MS) + 1
    end = int(deadline_ms)
    while e < end:
        if online.shot_wins(kind, challenge, e, 0, deadline_ms):
            start = e
            while e < end and online.shot_wins(kind, challenge, e, 0, deadline_ms):
                e += 1
            if best is None or (e - 1 - start) > (best[1] - best[0]):
                best = (start, e - 1)
        else:
            e += 1
    return best


def winning_elapsed(kind: SkillCheckKind, challenge: Any, deadline_ms: float) -> int:
    """
    Pick the elapsed time an e2e shot should claim to win a check. It aims at
    the MIDDLE of the widest window, never the top: the server scores
    max(claimed, arrival - lag bound), so a shot that leaves late on a loaded
    runner is scored later than it claims, and the midpoint leaves half the
    window as slack in both directions

    :param kind: which check is being beaten
    :param challenge: the geometry rebuilt from the check's seed
    :param deadline_ms: the check's deadline in milliseconds
    :returns: the elapsed time in milliseconds to claim on the shot
    """
    window = widest_win_window(kind, challenge, deadline_ms)
    assert window is not None, "no winning window for the stored seed"
    lo, hi = window
    assert hi - lo >= 2 * SLEEP_LEAD_MS, \
        "the win window must absorb the sleep lead in both directions"
    return (lo + hi) // 2


def required_payload(frm: Square, to: Square, kind: str = "wheel",
                     promotion: str | None = None, value_diff: int = 3,
                     elapsed_ms: float = 0.0, miss_count: int = 0,
                     captured_value: int = 0) -> dict[str, Any]:
    """
    Build the skill_check_required message the server sends the mover when it
    arms a check, the frontend tests' way of opening an overlay without a
    server

    :param frm: square the guarded move starts from
    :param to: square it is aimed at
    :param kind: which check the server armed
    :param promotion: promotion piece letter, or None when not promoting
    :param value_diff: material swing the check's difficulty is sized from
    :param elapsed_ms: how far into the check the client is already
    :param miss_count: shots already missed on this check
    :param captured_value: value of the piece being taken
    :returns: the skill-check payload
    """
    return {
        "kind": kind, "seed": "seed-1", "value_diff": value_diff,
        "deadline_ms": 5000.0, "elapsed_ms": elapsed_ms, "miss_count": miss_count,
        "from": coord_from_square(frm), "to": coord_from_square(to),
        "promotion": promotion, "captured_value": captured_value,
    }


def result_payload(frm: Square, to: Square) -> dict[str, Any]:
    """
    Build the skill_check_result message the server broadcasts when a check
    was lost, which is the only verdict that travels as its own message

    :param frm: square the guarded move starts from
    :param to: square it is aimed at
    :returns: the verdict payload, always a miss
    """
    return {"won": False, "from": coord_from_square(frm), "to": coord_from_square(to)}


def spectate_payload(frm: Square, to: Square, kind: str = "wheel", value_diff: int = 3,
                     promotion: str | None = None,
                     captured_value: int = 0) -> dict[str, Any]:
    """
    Build the skill_check_spectate message the opponent gets, which opens the
    read-only mirror of the check the mover is fighting

    :param frm: square the guarded move starts from
    :param to: square it is aimed at
    :param kind: which check the server armed
    :param value_diff: material swing the check's difficulty is sized from
    :param promotion: promotion piece letter, or None when not promoting
    :param captured_value: value of the piece being taken
    :returns: the spectate payload, as the wire spells it
    """
    return SkillCheckSpectateMessage(
        kind=kind, seed="seed-1", value_diff=value_diff, deadline_ms=5000.0,
        from_sq=coord_from_square(frm), to_sq=coord_from_square(to),
        promotion=promotion, captured_value=captured_value).model_dump(by_alias=True)


def drive_verdict_hold(app: Any) -> None:
    """
    Advance the skill-check overlay past the online result hold so the parked
    apply or lock actually runs. Two seconds covers every kind's verdict
    choreography: the shared 200 ms result hold, the whack win hold and the
    longer whack fail hold

    :param app: the app whose overlay is showing the verdict
    """
    app.game.skillcheck_overlay.update(pg.time.get_ticks() + 2000)
