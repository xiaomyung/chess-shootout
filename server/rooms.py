import asyncio
import random
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from backend.backend import Backend


GRACE_SECONDS = 60
REMATCH_KEEP_ALIVE_SECONDS = 60
PAIRING_WAIT_SECONDS = 30
FIRST_MOVE_ABORT_SECONDS = 60


class AlreadyInGameError(Exception):
    pass


class NotInRoomError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


@dataclass
class PlayerSlot:
    client_uuid: str
    nickname: str
    session_token: str
    side_preference: str = "random"
    connected: bool = False
    disconnected_at: Optional[float] = None


@dataclass
class Room:
    room_id: str
    time_minutes: int
    increment_seconds: int
    created_at: float
    white: Optional[PlayerSlot] = None
    black: Optional[PlayerSlot] = None
    backend: Optional[Backend] = None
    started_at: Optional[float] = None
    first_move_at: Optional[float] = None
    ended_at: Optional[float] = None
    game_start_broadcast: bool = False
    draw_offered_by: Optional[str] = None
    takeback_offered_by: Optional[str] = None
    rematch_offered_by: set = field(default_factory=set)
    result: Optional[tuple] = None

    def is_paired(self):
        return self.white is not None and self.black is not None

    def slot(self, color):
        return self.white if color == "white" else self.black

    def opp_color(self, color):
        return "black" if color == "white" else "white"

    def color_of(self, client_uuid):
        if self.white and self.white.client_uuid == client_uuid:
            return "white"
        if self.black and self.black.client_uuid == client_uuid:
            return "black"
        return None

    def slot_by_token(self, session_token):
        if self.white and self.white.session_token == session_token:
            return "white", self.white
        if self.black and self.black.session_token == session_token:
            return "black", self.black
        return None, None


class RoomManager:

    def __init__(self, now_provider=time.monotonic, max_rooms=100):
        self._lock = asyncio.Lock()
        self._queue: dict[tuple[int, int], list[Room]] = defaultdict(list)
        self._active: dict[str, Room] = {}
        self._uuid_to_room: dict[str, str] = {}
        self._now = now_provider
        self._max_rooms = max_rooms

    @property
    def rooms_active(self):
        return len(self._active)

    @property
    def queue_depth(self):
        return sum(len(q) for q in self._queue.values())

    def get(self, room_id):
        if room_id in self._active:
            return self._active[room_id]
        return self._find_in_queue(room_id)

    async def enqueue(self, *, client_uuid, nickname, session_token,
                      time_minutes, increment_seconds, side_preference):
        async with self._lock:
            if client_uuid in self._uuid_to_room:
                raise AlreadyInGameError()
            if len(self._active) + sum(len(q) for q in self._queue.values()) >= self._max_rooms:
                raise RuntimeError("server_full")
            tc = (time_minutes, increment_seconds)
            queue = self._queue[tc]
            if queue:
                room = queue.pop(0)
                first_color = "white" if room.white is not None else "black"
                first_slot = room.white if first_color == "white" else room.black
                first_pref = first_slot.side_preference
                second_color, first_color_resolved = self._resolve_colors(first_pref, side_preference)
                room.white = None
                room.black = None
                setattr(room, first_color_resolved, first_slot)
                new_slot = PlayerSlot(
                    client_uuid=client_uuid, nickname=nickname,
                    session_token=session_token, side_preference=side_preference,
                )
                setattr(room, second_color, new_slot)
                room.backend = Backend()
                room.backend.new_game()
                room.backend.setup_clock(time_minutes * 60, increment_seconds, now_provider=self._now)
                room.started_at = self._now()
                self._uuid_to_room[client_uuid] = room.room_id
                self._active[room.room_id] = room
                return room
            room_id = str(uuid4())
            tentative = (side_preference if side_preference != "random"
                         else random.choice(["white", "black"]))
            slot = PlayerSlot(
                client_uuid=client_uuid, nickname=nickname,
                session_token=session_token, side_preference=side_preference,
            )
            room = Room(
                room_id=room_id, time_minutes=time_minutes,
                increment_seconds=increment_seconds, created_at=self._now(),
            )
            setattr(room, tentative, slot)
            self._uuid_to_room[client_uuid] = room_id
            queue.append(room)
            return room

    @staticmethod
    def _resolve_colors(first_pref, second_pref):
        if second_pref != "random":
            second = second_pref
        elif first_pref != "random":
            second = "black" if first_pref == "white" else "white"
        else:
            second = random.choice(["white", "black"])
        first = "black" if second == "white" else "white"
        return second, first

    async def reclaim_session(self, client_uuid):
        async with self._lock:
            room_id = self._uuid_to_room.get(client_uuid)
            if room_id is None or room_id not in self._active:
                raise NotInRoomError()
            room = self._active[room_id]
            for color in ("white", "black"):
                slot = room.slot(color)
                if slot is not None and slot.client_uuid == client_uuid:
                    new_token = self.make_session_token()
                    slot.session_token = new_token
                    return room, color, new_token
            raise NotInRoomError()

    async def cancel_wait(self, room_id, session_token):
        async with self._lock:
            room = self._find_in_queue(room_id)
            if room is None:
                if room_id in self._active:
                    raise RuntimeError("game_already_started")
                raise NotInRoomError()
            slot = room.white or room.black
            if slot is None or slot.session_token != session_token:
                raise InvalidTokenError()
            tc = (room.time_minutes, room.increment_seconds)
            self._queue[tc].remove(room)
            self._uuid_to_room.pop(slot.client_uuid, None)

    def _find_in_queue(self, room_id):
        for queue in self._queue.values():
            for room in queue:
                if room.room_id == room_id:
                    return room
        return None

    def mark_connected(self, room_id, color):
        room = self.get(room_id)
        if room is None:
            return
        slot = room.slot(color)
        if slot is not None:
            slot.connected = True
            slot.disconnected_at = None

    def mark_disconnected(self, room_id, color):
        room = self.get(room_id)
        if room is None:
            return
        slot = room.slot(color)
        if slot is not None:
            slot.connected = False
            slot.disconnected_at = self._now()

    def grace_expired_rooms(self):
        now = self._now()
        for room in list(self._active.values()):
            if room.result is not None:
                continue
            for color in ("white", "black"):
                slot = room.slot(color)
                if (slot is not None and slot.disconnected_at is not None
                        and now - slot.disconnected_at >= GRACE_SECONDS):
                    yield room, color

    def finalize_abandonment(self, room_id, abandoned_color):
        room = self._active.get(room_id)
        if room is None or room.result is not None:
            return
        winner = room.opp_color(abandoned_color)
        room.result = ("abandonment", winner)
        room.ended_at = self._now()

    def finalize_result(self, room_id, reason, winner_color=None):
        room = self._active.get(room_id)
        if room is None or room.result is not None:
            return
        room.result = (reason, winner_color)
        room.ended_at = self._now()

    def gc_finished_rooms(self):
        now = self._now()
        to_drop = []
        for room_id, room in self._active.items():
            if room.ended_at is None:
                continue
            if now - room.ended_at >= REMATCH_KEEP_ALIVE_SECONDS:
                to_drop.append(room_id)
        for room_id in to_drop:
            self._drop_room(room_id)

    def drop_room_now(self, room_id):
        if room_id in self._active:
            self._drop_room(room_id)

    def _drop_room(self, room_id):
        room = self._active.pop(room_id, None)
        if room is None:
            return
        for slot in (room.white, room.black):
            if slot is not None:
                self._uuid_to_room.pop(slot.client_uuid, None)

    def reset_for_rematch(self, room_id):
        room = self._active.get(room_id)
        if room is None or room.result is None:
            return
        old_white, old_black = room.white, room.black
        room.white, room.black = old_black, old_white
        room.backend = Backend()
        room.backend.new_game()
        room.backend.setup_clock(
            room.time_minutes * 60, room.increment_seconds, now_provider=self._now,
        )
        room.started_at = self._now()
        room.first_move_at = None
        room.ended_at = None
        room.game_start_broadcast = False
        room.draw_offered_by = None
        room.takeback_offered_by = None
        room.rematch_offered_by = set()
        room.result = None

    @staticmethod
    def make_session_token():
        return secrets.token_urlsafe(24)
