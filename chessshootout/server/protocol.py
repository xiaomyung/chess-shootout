import os
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _env_float(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name, default):
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


PROTOCOL_VERSION = 3
MAX_NICKNAME_LEN = 20
GIVE_TIME_SECONDS = 15
GIVE_TIME_TICK_MS = 100
GIVE_TIME_MAX_HOLD_MS = 600_000
FIRST_MOVE_ABORT_SECONDS = 60
GRACE_SECONDS = _env_float("GRACE_SECONDS", 60.0)
HEARTBEAT_INTERVAL_SECONDS = _env_float("HEARTBEAT_INTERVAL_SECONDS", 2.0)
HEARTBEAT_MISS_LIMIT = _env_int("HEARTBEAT_MISS_LIMIT", 3)
HEARTBEAT_TIMEOUT_SECONDS = HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MISS_LIMIT
MAX_SHARED_HIGHLIGHTS = 64
MAX_SHARED_ARROWS = 128
CHAT_COOLDOWN_SECONDS = 3.0
CHAT_PRESET_COUNT = 4
ANNOTATIONS_PER_SECOND = 10

UUID4_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
)
COORD_RE = re.compile(r"^[a-h][1-8]$")


def is_uuid4(value):
    return isinstance(value, str) and bool(UUID4_RE.match(value))


def _validate_uuid4(value, name):
    if not is_uuid4(value):
        raise ValueError(f"invalid_{name}")
    return value


def _validate_coord(value, name):
    if not (isinstance(value, str) and bool(COORD_RE.match(value))):
        raise ValueError(f"invalid_{name}")
    return value


class Reason:
    VERSION_MISMATCH = "version_mismatch"
    INVALID_MESSAGE = "invalid_message"
    INVALID_MOVE_FORMAT = "invalid_move_format"
    INVALID_TIME_CONTROL = "invalid_time_control"
    NOT_YOUR_TURN = "not_your_turn"
    SKILLCHECK_PENDING = "skillcheck_pending"
    MOVE_LOCKED = "move_locked"
    SESSION_EXPIRED = "session_expired"
    ALREADY_IN_GAME = "already_in_game"
    NOT_IN_ROOM = "not_in_room"
    ROOM_FULL = "room_full"
    RATE_LIMITED = "rate_limited"
    GAME_ALREADY_OVER = "game_already_over"
    REMATCH_UNAVAILABLE = "rematch_unavailable"
    REMATCH_ALREADY_PENDING = "rematch_already_pending"
    NO_TAKEBACK_AVAILABLE = "no_takeback_available"

    CHECKMATE = "checkmate"
    RESIGNATION = "resignation"
    DRAW_AGREEMENT = "draw_agreement"
    DRAW_STALEMATE = "draw_stalemate"
    DRAW_REPETITION = "draw_repetition"
    DRAW_FIFTY_MOVE = "draw_fifty_move"
    DRAW_INSUFFICIENT_MATERIAL = "draw_insufficient_material"
    TIMEOUT = "timeout"
    ABORTED = "aborted"
    ABORTED_DISCONNECT = "aborted_disconnect"
    ABANDONMENT = "abandonment"
    SERVER_SHUTDOWN = "server_shutdown"


def normalize_nickname(raw):
    if raw is None:
        raise ValueError("nickname required")
    if not (raw.isascii() and raw.isprintable()):
        raise ValueError("nickname must be printable ASCII")
    collapsed = re.sub(r"\s+", " ", raw.strip())
    if not collapsed:
        raise ValueError("nickname must not be empty")
    if len(collapsed) > MAX_NICKNAME_LEN:
        raise ValueError(f"nickname must be <= {MAX_NICKNAME_LEN} chars")
    return collapsed


def normalize_country(raw):
    if raw is None:
        return None
    value = str(raw).strip().upper()
    if len(value) == 2 and value.isascii() and value.isalpha():
        return value
    return None


class _Base(BaseModel):
    version: int = PROTOCOL_VERSION


class ClockSnapshot(BaseModel):
    white_remaining: float
    black_remaining: float
    running_for: Optional[Literal["white", "black"]]


class HistoryEntryWire(BaseModel):
    from_sq: str
    to_sq: str
    promotion: Optional[Literal["q", "r", "b", "n"]] = None
    san: str


class LockWire(BaseModel):
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class ArrowWire(BaseModel):
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")

    model_config = {"populate_by_name": True}

    @field_validator("from_sq", "to_sq")
    @classmethod
    def _coord(cls, v):
        return _validate_coord(v, "coord")


class AnnotationSetWire(BaseModel):
    sharing: bool = False
    highlights: list[str] = Field(default_factory=list, max_length=MAX_SHARED_HIGHLIGHTS)
    arrows: list[ArrowWire] = Field(default_factory=list, max_length=MAX_SHARED_ARROWS)

    @field_validator("highlights")
    @classmethod
    def _coords(cls, v):
        for sq in v:
            _validate_coord(sq, "coord")
        return v


class _SkillCheckGeometryBase(BaseModel):
    kind: Literal["wheel", "aim"]
    seed: str
    value_diff: int
    deadline_ms: float
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")
    promotion: Optional[Literal["q", "r", "b", "n"]] = None

    model_config = {"populate_by_name": True}


class PendingSkillCheckWire(_SkillCheckGeometryBase):
    elapsed_ms: float
    miss_count: int = 0
    color: Literal["white", "black"]


class SkillCheckOutcomeWire(BaseModel):
    ply: int
    kind: Literal["wheel", "aim"]
    won: bool
    san: str = ""


class MatchmakeRequest(_Base):
    nickname: str
    client_uuid: str
    time_minutes: int
    increment_seconds: int
    side_preference: Literal["white", "black", "random"] = "random"
    country: Optional[str] = None

    @field_validator("nickname")
    @classmethod
    def _normalize(cls, v):
        return normalize_nickname(v)

    @field_validator("country", mode="before")
    @classmethod
    def _country(cls, v):
        return normalize_country(v)

    @field_validator("client_uuid")
    @classmethod
    def _uuid4(cls, v):
        return _validate_uuid4(v, "client_uuid")

    @field_validator("time_minutes", "increment_seconds")
    @classmethod
    def _non_negative(cls, v):
        if v < 0:
            raise ValueError("must be non-negative")
        return v


class MatchmakeResponse(_Base):
    room_id: str
    session_token: str


class CancelMatchmakeRequest(_Base):
    room_id: str
    session_token: str

    @field_validator("room_id")
    @classmethod
    def _uuid4(cls, v):
        return _validate_uuid4(v, "room_id")


class ResumeRequest(_Base):
    room_id: str
    session_token: str

    @field_validator("room_id")
    @classmethod
    def _uuid4(cls, v):
        return _validate_uuid4(v, "room_id")


class ResumeResponse(_Base):
    fen: str
    move_history: list[HistoryEntryWire]
    clock: ClockSnapshot
    your_color: Literal["white", "black"]
    white_name: str
    black_name: str
    time_minutes: int
    increment_seconds: int
    white_score: float = 0.0
    black_score: float = 0.0
    white_country: Optional[str] = None
    black_country: Optional[str] = None
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    grace_seconds: float = GRACE_SECONDS
    pending_skillcheck: Optional[PendingSkillCheckWire] = None
    skillcheck_locks: list[LockWire] = Field(default_factory=list)
    skillcheck_log: list[SkillCheckOutcomeWire] = Field(default_factory=list)
    white_annotations: AnnotationSetWire = Field(default_factory=AnnotationSetWire)
    black_annotations: AnnotationSetWire = Field(default_factory=AnnotationSetWire)
    result_reason: Optional[str] = None
    result_winner: Optional[Literal["white", "black"]] = None


class ReclaimRequest(_Base):
    client_uuid: str

    @field_validator("client_uuid")
    @classmethod
    def _uuid4(cls, v):
        return _validate_uuid4(v, "client_uuid")


class ReclaimResponse(_Base):
    room_id: str
    session_token: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: int = PROTOCOL_VERSION
    app_version: str = ""
    rooms_active: int
    queue_depth: int = 0
    uptime_s: float = 0.0


class AuthMessage(_Base):
    type: Literal["auth"] = "auth"
    session_token: str


class MoveMessage(_Base):
    type: Literal["move"] = "move"
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")
    promotion: Optional[Literal["q", "r", "b", "n"]] = None

    model_config = {"populate_by_name": True}


class DrawResponseMessage(_Base):
    type: Literal["draw_response"] = "draw_response"
    accept: bool


class RematchRequestMessage(_Base):
    type: Literal["rematch_request"] = "rematch_request"


class RematchResponseMessage(_Base):
    type: Literal["rematch_response"] = "rematch_response"
    accept: bool


RematchUpdateEvent = Literal[
    "declined", "cancelled", "window_expired",
    "opponent_left", "opponent_reconnecting", "opponent_returned",
]


class RematchUpdateMessage(_Base):
    type: Literal["rematch_update"] = "rematch_update"
    event: RematchUpdateEvent


class TakebackResponseMessage(_Base):
    type: Literal["takeback_response"] = "takeback_response"
    accept: bool


class GameStartMessage(_Base):
    type: Literal["game_start"] = "game_start"
    fen: str
    white_name: str
    black_name: str
    time_minutes: int
    increment_seconds: int
    your_color: Literal["white", "black"]
    started_seconds_ago: float = 0.0
    white_score: float = 0.0
    black_score: float = 0.0
    white_country: Optional[str] = None
    black_country: Optional[str] = None
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    grace_seconds: float = GRACE_SECONDS
    rematch: bool = False


class MoveAppliedMessage(_Base):
    type: Literal["move_applied"] = "move_applied"
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")
    promotion: Optional[Literal["q", "r", "b", "n"]] = None
    san: str
    clock: ClockSnapshot
    ply: int
    skill_check_kind: Optional[Literal["wheel", "aim"]] = None
    skill_check_won: Optional[bool] = None

    model_config = {"populate_by_name": True}


class ResultMessage(_Base):
    type: Literal["result"] = "result"
    reason: str
    winner_color: Optional[Literal["white", "black"]] = None


class DrawOfferedMessage(_Base):
    type: Literal["draw_offered"] = "draw_offered"


class TakebackOfferedMessage(_Base):
    type: Literal["takeback_offered"] = "takeback_offered"


class TakebackAppliedMessage(_Base):
    type: Literal["takeback_applied"] = "takeback_applied"
    fen: str
    clock: ClockSnapshot
    ply: int


class GiveTimeMessage(_Base):
    type: Literal["give_time"] = "give_time"
    hold_ms: int = Field(default=0, ge=0, le=GIVE_TIME_MAX_HOLD_MS)


class TimeGrantedMessage(_Base):
    type: Literal["time_granted"] = "time_granted"
    granted_by: Literal["white", "black"]
    seconds_added: float
    clock: ClockSnapshot


class AnnotationsStateMessage(_Base):
    type: Literal["annotations_state"] = "annotations_state"
    sharing: bool
    highlights: list[str] = Field(default_factory=list, max_length=MAX_SHARED_HIGHLIGHTS)
    arrows: list[ArrowWire] = Field(default_factory=list, max_length=MAX_SHARED_ARROWS)

    @field_validator("highlights")
    @classmethod
    def _coords(cls, v):
        for sq in v:
            _validate_coord(sq, "coord")
        return v


class AnnotationDeltaMessage(_Base):
    type: Literal["annotation_delta"] = "annotation_delta"
    action: Literal["add", "remove"]
    kind: Literal["highlight", "arrow"]
    square: Optional[str] = None
    from_sq: Optional[str] = Field(default=None, alias="from")
    to_sq: Optional[str] = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}

    @field_validator("square", "from_sq", "to_sq")
    @classmethod
    def _coord(cls, v):
        if v is None:
            return v
        return _validate_coord(v, "coord")


class QuickChatMessage(_Base):
    type: Literal["quick_chat"] = "quick_chat"
    preset: int = Field(ge=0, le=CHAT_PRESET_COUNT - 1)


class QuickChatReceivedMessage(_Base):
    type: Literal["quick_chat_received"] = "quick_chat_received"
    preset: int = Field(ge=0, le=CHAT_PRESET_COUNT - 1)
    sender: Literal["white", "black"]


class ConnectionStatusMessage(_Base):
    type: Literal["connection_status"] = "connection_status"
    opp_state: Literal["connected", "reconnecting", "resyncing"]


class PingMessage(_Base):
    type: Literal["ping"] = "ping"
    ply: int = 0


class PongMessage(_Base):
    type: Literal["pong"] = "pong"


class ResyncDirectiveMessage(_Base):
    type: Literal["resync_directive"] = "resync_directive"


class SkillCheckRequiredMessage(_SkillCheckGeometryBase, _Base):
    type: Literal["skill_check_required"] = "skill_check_required"
    miss_count: int = 0


class SkillCheckShotMessage(_Base):
    type: Literal["skill_check_shot"] = "skill_check_shot"
    client_elapsed_ms: float = 0.0

    model_config = {"extra": "ignore"}


class SkillCheckResultMessage(_Base):
    type: Literal["skill_check_result"] = "skill_check_result"
    won: bool
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class SkillCheckSpectateMessage(_SkillCheckGeometryBase, _Base):
    type: Literal["skill_check_spectate"] = "skill_check_spectate"


class SkillCheckSpectateShotMessage(_Base):
    type: Literal["skill_check_spectate_shot"] = "skill_check_spectate_shot"
    elapsed_ms: float
    miss_count: int
    won: bool


class ErrorMessage(_Base):
    type: Literal["error"] = "error"
    reason: str
    msg_type: Optional[str] = None
