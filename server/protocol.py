import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


PROTOCOL_VERSION = 1
MAX_NICKNAME_LEN = 20

UUID4_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
)


def is_uuid4(value):
    return isinstance(value, str) and bool(UUID4_RE.match(value))


def _validate_uuid4(value, name):
    if not is_uuid4(value):
        raise ValueError(f"invalid_{name}")
    return value


class Reason:
    VERSION_MISMATCH = "version_mismatch"
    INVALID_MESSAGE = "invalid_message"
    INVALID_MOVE_FORMAT = "invalid_move_format"
    INVALID_TIME_CONTROL = "invalid_time_control"
    NOT_YOUR_TURN = "not_your_turn"
    SESSION_EXPIRED = "session_expired"
    ALREADY_IN_GAME = "already_in_game"
    NOT_IN_ROOM = "not_in_room"
    ROOM_FULL = "room_full"
    RATE_LIMITED = "rate_limited"

    CHECKMATE = "checkmate"
    RESIGNATION = "resignation"
    DRAW_AGREEMENT = "draw_agreement"
    DRAW_STALEMATE = "draw_stalemate"
    DRAW_REPETITION = "draw_repetition"
    DRAW_FIFTY_MOVE = "draw_fifty_move"
    DRAW_INSUFFICIENT_MATERIAL = "draw_insufficient_material"
    TIMEOUT = "timeout"
    ABORTED = "aborted"
    ABANDONMENT = "abandonment"
    SERVER_SHUTDOWN = "server_shutdown"


def normalize_nickname(raw):
    if raw is None:
        raise ValueError("nickname required")
    if not all(0x20 <= ord(c) <= 0x7e for c in raw):
        raise ValueError("nickname must be printable ASCII")
    collapsed = re.sub(r"\s+", " ", raw.strip())
    if not collapsed:
        raise ValueError("nickname must not be empty")
    if len(collapsed) > MAX_NICKNAME_LEN:
        raise ValueError(f"nickname must be <= {MAX_NICKNAME_LEN} chars")
    return collapsed


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


class MatchmakeRequest(_Base):
    nickname: str
    client_uuid: str
    time_minutes: int
    increment_seconds: int
    side_preference: Literal["white", "black", "random"] = "random"

    @field_validator("nickname")
    @classmethod
    def _normalize(cls, v):
        return normalize_nickname(v)

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


class MoveAppliedMessage(_Base):
    type: Literal["move_applied"] = "move_applied"
    from_sq: str = Field(alias="from")
    to_sq: str = Field(alias="to")
    promotion: Optional[Literal["q", "r", "b", "n"]] = None
    san: str
    clock: ClockSnapshot

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


class ConnectionStatusMessage(_Base):
    type: Literal["connection_status"] = "connection_status"
    opp_state: Literal["connected", "reconnecting", "disconnected"]


class ErrorMessage(_Base):
    type: Literal["error"] = "error"
    reason: str
    msg_type: Optional[str] = None
