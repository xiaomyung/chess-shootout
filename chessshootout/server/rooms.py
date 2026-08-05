import asyncio
import random
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import Square
from chessshootout.server.protocol import GRACE_SECONDS, HEARTBEAT_TIMEOUT_SECONDS
from chessshootout.skillcheck import online
from chessshootout.skillcheck.types import SkillCheckKind


REMATCH_IDLE_SECONDS = 300.0
REMATCH_ABSOLUTE_CAP_SECONDS = 900.0
POST_GAME_DISCONNECT_GRACE = GRACE_SECONDS
PAIRING_WAIT_SECONDS = 30
QUEUE_ABANDON_SECONDS = 120.0


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
    country: Optional[str] = None
    hide_opp_marks: bool = False
    connected: bool = False
    disconnected_at: Optional[float] = None
    desync_active: bool = False
    last_seen: float = 0.0
    at_result: bool = False


@dataclass
class PendingSkillCheck:
    color: str
    from_sq: Square
    to_sq: Square
    promotion: Optional[str]
    kind: SkillCheckKind
    seed: str
    value_diff: int
    start_ms: float
    expires_at_ms: float
    deadline_ms: float = online.SKILLCHECK_DEADLINE_MS
    miss_count: int = 0
    captured_value: int = 0
    progress: int = 0
    last_hit_pop: int = -1
    last_input_ms: float = -1.0
    holes: tuple = field(default=(), repr=False, compare=False)
    _challenge: object = field(default=None, repr=False, compare=False)

    @property
    def challenge(self):
        if self._challenge is None:
            self._challenge = online.challenge_from(
                self.kind, self.seed, self.value_diff, self.deadline_ms,
                self.captured_value)
        return self._challenge

    def is_expired(self, now_ms):
        return now_ms > self.expires_at_ms

    def is_dead(self, now_ms):
        if self.is_expired(now_ms):
            return True
        return online.check_expired(self.kind, self.challenge, now_ms - self.start_ms,
                                    self.miss_count, self.progress, self.last_hit_pop)


@dataclass
class SharedAnnotations:
    sharing: bool = False
    highlights: set = field(default_factory=set)
    arrows: list = field(default_factory=list)
    trip_count: int = 0
    share_muted: bool = False
    opp_hidden_notice_sent: bool = False

    def clear_marks(self):
        self.highlights.clear()
        self.arrows.clear()

    def reset(self):
        self.clear_marks()
        self.sharing = False
        self.trip_count = 0
        self.share_muted = False
        self.opp_hidden_notice_sent = False

    def register_trip(self, limit):
        self.trip_count += 1
        muted = self.trip_count >= limit
        if muted:
            self.share_muted = True
            self.clear_marks()
        return muted

    def strip(self, arrows, highlights):
        for arrow in arrows:
            pair = (arrow[0], arrow[1])
            while pair in self.arrows:
                self.arrows.remove(pair)
        for highlight in highlights:
            self.highlights.discard(highlight)


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
    last_rematch_activity_at: Optional[float] = None
    game_start_broadcast: bool = False
    draw_offered_by: Optional[str] = None
    takeback_offered_by: Optional[str] = None
    rematch_offered_by: set[str] = field(default_factory=set)
    result: Optional[tuple[str, str]] = None
    series_scores: dict[str, float] = field(default_factory=dict)
    skillcheck_secret: str = ""
    skillcheck_locks: set = field(default_factory=set)
    skillcheck_log: list = field(default_factory=list)
    pending_skillcheck: Optional[PendingSkillCheck] = None
    plies_ever: int = 0
    annotations_white: SharedAnnotations = field(default_factory=SharedAnnotations)
    annotations_black: SharedAnnotations = field(default_factory=SharedAnnotations)

    def score_for(self, color):
        slot = self.slot(color)
        return self.series_scores.get(slot.nickname, 0.0) if slot else 0.0

    def is_paired(self):
        return self.white is not None and self.black is not None

    def slot(self, color):
        return self.white if color == "white" else self.black

    def annotations_for(self, color):
        return self.annotations_white if color == "white" else self.annotations_black

    def opp_color(self, color):
        return "black" if color == "white" else "white"

    def hides_opponent_marks(self, color):
        slot = self.slot(color)
        return slot is not None and slot.hide_opp_marks

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

    def active_rooms(self):
        return list(self._active.values())

    def get(self, room_id):
        if room_id in self._active:
            return self._active[room_id]
        return self._find_in_queue(room_id)

    async def enqueue(self, *, client_uuid, nickname, session_token,
                      time_minutes, increment_seconds, side_preference,
                      country=None, hide_opp_marks=False):
        async with self._lock:
            if client_uuid in self._uuid_to_room:
                raise AlreadyInGameError()
            if len(self._active) + self.queue_depth >= self._max_rooms:
                raise RuntimeError("server_full")
            tc = (time_minutes, increment_seconds)
            queue = self._queue[tc]
            if queue:
                room = queue.pop(0)
                if not queue:
                    del self._queue[tc]
                first_slot = room.white or room.black
                first_pref = first_slot.side_preference
                second_color, first_color_resolved = self._resolve_colors(
                    first_pref, side_preference,
                )
                room.white = None
                room.black = None
                setattr(room, first_color_resolved, first_slot)
                new_slot = PlayerSlot(
                    client_uuid=client_uuid, nickname=nickname,
                    session_token=session_token, side_preference=side_preference,
                    country=country, hide_opp_marks=hide_opp_marks,
                )
                setattr(room, second_color, new_slot)
                room.backend = Backend()
                room.backend.new_game()
                room.backend.setup_clock(
                    time_minutes * 60, increment_seconds, now_provider=self._now,
                )
                room.skillcheck_secret = secrets.token_hex(16)
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
                country=country, hide_opp_marks=hide_opp_marks,
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
            self._dequeue(room)
            self._uuid_to_room.pop(slot.client_uuid, None)

    def _find_in_queue(self, room_id):
        for queue in self._queue.values():
            for room in queue:
                if room.room_id == room_id:
                    return room
        return None

    def _dequeue(self, room):
        tc = (room.time_minutes, room.increment_seconds)
        queue = self._queue.get(tc)
        if queue is None or room not in queue:
            return False
        queue.remove(room)
        if not queue:
            del self._queue[tc]
        return True

    def stale_queued_rooms(self, ttl_seconds=QUEUE_ABANDON_SECONDS):
        cutoff = self._now() - ttl_seconds
        return [room for queue in self._queue.values() for room in queue
                if room.created_at <= cutoff]

    def drop_queued_room(self, room):
        if not self._dequeue(room):
            return False
        for slot in (room.white, room.black):
            if slot is not None:
                self._uuid_to_room.pop(slot.client_uuid, None)
        return True

    def mark_connected(self, room_id, color):
        room = self.get(room_id)
        if room is None:
            return
        slot = room.slot(color)
        if slot is not None:
            slot.connected = True
            slot.disconnected_at = None
            slot.desync_active = False
            slot.last_seen = self._now()

    def mark_disconnected(self, room_id, color):
        room = self.get(room_id)
        if room is None:
            return
        slot = room.slot(color)
        if slot is not None and slot.connected:
            slot.connected = False
            slot.disconnected_at = self._now()

    def touch_seen(self, room_id, color):
        room = self.get(room_id)
        if room is None:
            return
        slot = room.slot(color)
        if slot is not None:
            slot.last_seen = self._now()

    def heartbeat_timed_out_rooms(self):
        now = self._now()
        for room in list(self._active.values()):
            if room.result is not None or room.first_move_at is None:
                continue
            for color in ("white", "black"):
                slot = room.slot(color)
                if (slot is not None and slot.connected
                        and now - slot.last_seen >= HEARTBEAT_TIMEOUT_SECONDS):
                    yield room, color

    def in_progress_room_for(self, client_uuid):
        room_id = self._uuid_to_room.get(client_uuid)
        if room_id is None:
            return None
        room = self._active.get(room_id)
        if room is None or room.result is not None:
            return None
        if not room.is_paired() or room.first_move_at is None:
            return None
        color = room.color_of(client_uuid)
        if color is None:
            return None
        return room, color

    def release_for_new_game(self, client_uuid):
        room_id = self._uuid_to_room.get(client_uuid)
        if room_id is None:
            return
        if room_id in self._active:
            self._drop_room(room_id)
            return
        queued = self._find_in_queue(room_id)
        if queued is not None:
            self._dequeue(queued)
        self._uuid_to_room.pop(client_uuid, None)

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

    ZERO_PLY_ABORT_REASONS = ("timeout", "abandonment")

    def finalize_result(self, room_id, reason, winner_color=None):
        room = self._active.get(room_id)
        if room is None or room.result is not None:
            return False
        if room.plies_ever == 0 and reason in self.ZERO_PLY_ABORT_REASONS:
            reason, winner_color = "aborted", None
        room.result = (reason, winner_color)
        room.ended_at = self._now()
        for slot in (room.white, room.black):
            if slot is not None and slot.disconnected_at is not None:
                slot.disconnected_at = room.ended_at
        room.last_rematch_activity_at = room.ended_at
        room.pending_skillcheck = None
        room.annotations_white.reset()
        room.annotations_black.reset()
        for slot in (room.white, room.black):
            if slot is not None:
                slot.at_result = True
        self._award_series(room, reason, winner_color)
        return True

    @staticmethod
    def _award_series(room, reason, winner_color):
        if reason in ("aborted", "server_shutdown"):
            return
        scores = room.series_scores
        if winner_color in ("white", "black"):
            slot = room.slot(winner_color)
            if slot is not None:
                scores[slot.nickname] = scores.get(slot.nickname, 0.0) + 1.0
        elif reason.startswith("draw"):
            for slot in (room.white, room.black):
                if slot is not None:
                    scores[slot.nickname] = scores.get(slot.nickname, 0.0) + 0.5

    def finished_timed_out(self, room):
        if room.result is None or room.ended_at is None:
            return False
        now = self._now()
        last = room.last_rematch_activity_at or room.ended_at
        return (now - last >= REMATCH_IDLE_SECONDS
                or now - room.ended_at >= REMATCH_ABSOLUTE_CAP_SECONDS)

    def gc_finished_rooms(self):
        to_drop = [
            room_id for room_id, room in self._active.items()
            if self.finished_timed_out(room)
        ]
        for room_id in to_drop:
            self._drop_room(room_id)

    def mark_rematch_activity(self, room):
        room.last_rematch_activity_at = self._now()

    def finished_room_for(self, client_uuid):
        room_id = self._uuid_to_room.get(client_uuid)
        if room_id is None:
            return None
        room = self._active.get(room_id)
        if room is None or room.result is None:
            return None
        return room

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
            return False
        old_white, old_black = room.white, room.black
        room.white, room.black = old_black, old_white
        room.backend = Backend()
        room.backend.new_game()
        room.backend.setup_clock(
            room.time_minutes * 60, room.increment_seconds, now_provider=self._now,
        )
        room.skillcheck_secret = secrets.token_hex(16)
        room.skillcheck_locks = set()
        room.skillcheck_log = []
        room.pending_skillcheck = None
        room.plies_ever = 0
        room.annotations_white = SharedAnnotations()
        room.annotations_black = SharedAnnotations()
        room.started_at = self._now()
        room.first_move_at = None
        room.ended_at = None
        room.last_rematch_activity_at = None
        room.game_start_broadcast = False
        room.draw_offered_by = None
        room.takeback_offered_by = None
        room.rematch_offered_by = set()
        room.result = None
        for slot in (room.white, room.black):
            if slot is not None:
                slot.at_result = False
        return True

    @staticmethod
    def make_session_token():
        return secrets.token_urlsafe(24)
