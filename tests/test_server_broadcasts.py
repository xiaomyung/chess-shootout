"""broadcasts.py + connections.py: the finalize-race guard (a resign and a
mate landing at the same instant must not double-broadcast a contradictory
result) and the broadcast-send-failure -> mark_disconnected seam (a socket
that throws on send must not be left looking "connected" until the next
heartbeat sweep notices, ~HEARTBEAT_TIMEOUT_SECONDS later).
"""
import pytest

from chessshootout.server.app import create_app
from chessshootout.server.broadcasts import finalize_and_broadcast
from chessshootout.server.connections import broadcast
from chessshootout.server.protocol import PROTOCOL_VERSION, Reason, ResultMessage
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


class RecordingWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)

    def of_type(self, t):
        return [m for m in self.sent if m["type"] == t]


class FailingWS:
    async def send_json(self, payload):
        raise RuntimeError("connection reset")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    return create_app(now_provider=clock, max_rooms=8)


async def _pair(rooms):
    await rooms.enqueue(client_uuid=ALICE, nickname="A", session_token="ta",
                        time_minutes=5, increment_seconds=0, side_preference="white")
    await rooms.enqueue(client_uuid=BOB, nickname="B", session_token="tb",
                        time_minutes=5, increment_seconds=0, side_preference="black")
    return list(rooms._active.values())[0]


class _RacingWS(RecordingWS):
    """A socket that, on receiving the winning caller's own result broadcast,
    simulates a second concurrent finalize (e.g. a mate landing) racing in
    with a contradictory reason -- exactly the scenario two truly concurrent
    handler tasks would produce."""

    def __init__(self, rooms, connections, room):
        super().__init__()
        self._rooms = rooms
        self._connections = connections
        self._room = room
        self._fired = False

    async def send_json(self, payload):
        await super().send_json(payload)
        if not self._fired and payload.get("type") == "result":
            self._fired = True
            await finalize_and_broadcast(self._rooms, self._connections, self._room,
                                         Reason.CHECKMATE, winner_color="white")


@pytest.mark.asyncio
async def test_losing_finalize_race_does_not_double_broadcast(app, clock):
    rooms = app.state.rooms
    connections = app.state.connections
    room = await _pair(rooms)
    room.first_move_at = clock()
    racing_white = _RacingWS(rooms, connections, room)
    ws_black = RecordingWS()
    connections.add(room.room_id, room.white.client_uuid, racing_white)
    connections.add(room.room_id, room.black.client_uuid, ws_black)

    await finalize_and_broadcast(rooms, connections, room, Reason.RESIGNATION,
                                 winner_color="black")

    assert room.result == (Reason.RESIGNATION, "black"), "the first finalize wins the state"
    expected = [{
        "version": PROTOCOL_VERSION, "type": "result",
        "reason": Reason.RESIGNATION, "winner_color": "black",
    }]
    assert racing_white.of_type("result") == expected, \
        "the racing (losing) finalize must not re-broadcast its own contradictory reason"
    assert ws_black.of_type("result") == expected, "both sides see one consistent result"


@pytest.mark.asyncio
async def test_broadcast_marks_disconnected_on_send_failure(app, clock):
    rooms = app.state.rooms
    connections = app.state.connections
    room = await _pair(rooms)
    room.first_move_at = clock()
    rooms.mark_connected(room.room_id, "white")
    rooms.mark_connected(room.room_id, "black")
    connections.add(room.room_id, room.white.client_uuid, FailingWS())
    ws_black = RecordingWS()
    connections.add(room.room_id, room.black.client_uuid, ws_black)

    await broadcast(rooms, connections, room,
                    ResultMessage(reason=Reason.RESIGNATION, winner_color="black"))

    assert room.white.connected is False, "a failed send must flip the slot to disconnected"
    assert room.white.disconnected_at is not None
    opp_notice = ws_black.of_type("connection_status")
    assert opp_notice and opp_notice[-1]["opp_state"] == "reconnecting"


@pytest.mark.asyncio
async def test_broadcast_send_failure_to_an_already_disconnected_slot_is_a_noop(app, clock):
    """mark_disconnected is idempotent, so a send failure against a slot that
    was never marked connected (or already disconnected) doesn't stamp a
    fresh disconnected_at over the real one."""
    rooms = app.state.rooms
    connections = app.state.connections
    room = await _pair(rooms)
    room.first_move_at = clock()
    connections.add(room.room_id, room.white.client_uuid, FailingWS())

    await broadcast(rooms, connections, room,
                    ResultMessage(reason=Reason.RESIGNATION, winner_color="black"))

    assert room.white.connected is False
