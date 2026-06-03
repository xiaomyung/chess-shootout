import pytest
from pydantic import ValidationError

from chessshootout.server.protocol import (
    AuthMessage, ErrorMessage, GameStartMessage, MatchmakeRequest,
    MoveMessage, PROTOCOL_VERSION, ResyncNoticeMessage, StateSyncMessage,
    normalize_country, normalize_nickname,
)
from tests.helpers import fake_uuid4


U1 = fake_uuid4(1)

GAME_START = GameStartMessage(
    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    white_name="Alice", black_name="Bob",
    time_minutes=5, increment_seconds=0,
    your_color="white",
)


@pytest.mark.parametrize(
    "msg, expected",
    [
        pytest.param(
            StateSyncMessage(ply=7),
            {"version": PROTOCOL_VERSION, "type": "state_sync", "ply": 7},
            id="state_sync",
        ),
        pytest.param(
            ResyncNoticeMessage(),
            {"version": PROTOCOL_VERSION, "type": "resync"},
            id="resync_notice",
        ),
        pytest.param(
            GAME_START,
            {
                "version": PROTOCOL_VERSION,
                "type": "game_start",
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "white_name": "Alice",
                "black_name": "Bob",
                "time_minutes": 5,
                "increment_seconds": 0,
                "your_color": "white",
                "started_seconds_ago": 0.0,
                "white_score": 0.0,
                "black_score": 0.0,
                "white_country": None,
                "black_country": None,
            },
            id="game_start",
        ),
    ],
)
def test_message_round_trip_matches_independent_wire_shape(msg, expected):
    """model_dump matches a hand-written wire dict, and the dict re-parses to an equal model."""
    assert msg.model_dump() == expected
    assert type(msg).model_validate(expected) == msg


@pytest.mark.parametrize(
    "msg",
    [
        pytest.param(AuthMessage(session_token="t"), id="auth"),
        pytest.param(ErrorMessage(reason="version_mismatch"), id="error"),
        pytest.param(StateSyncMessage(ply=0), id="state_sync"),
        pytest.param(ResyncNoticeMessage(), id="resync"),
    ],
)
def test_messages_carry_protocol_version(msg):
    assert msg.version == PROTOCOL_VERSION


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param("  alice  ", "alice", id="strips_surrounding"),
        pytest.param("a   b   c", "a b c", id="collapses_internal_runs"),
        pytest.param("Alice 42!", "Alice 42!", id="keeps_printable_ascii"),
    ],
)
def test_normalize_nickname_accepts(raw, expected):
    assert normalize_nickname(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace_only"),
        pytest.param("x" * 21, id="too_long"),
        pytest.param("alice\x00", id="null_byte"),
        pytest.param("alice\n", id="newline"),
    ],
)
def test_normalize_nickname_rejects(raw):
    with pytest.raises(ValueError):
        normalize_nickname(raw)


@pytest.mark.parametrize(
    "kwargs, attr, expected",
    [
        pytest.param(
            {"nickname": "  Alice  "}, "nickname", "Alice",
            id="normalizes_nickname",
        ),
        pytest.param({}, "side_preference", "random", id="default_side_random"),
    ],
)
def test_matchmake_request_accepts(kwargs, attr, expected):
    base = {
        "nickname": "Alice", "client_uuid": U1,
        "time_minutes": 5, "increment_seconds": 0,
    }
    req = MatchmakeRequest(**{**base, **kwargs})
    assert getattr(req, attr) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"time_minutes": -1}, id="negative_time"),
        pytest.param({"side_preference": "middle"}, id="bad_side"),
    ],
)
def test_matchmake_request_rejects(kwargs):
    base = {
        "nickname": "Alice", "client_uuid": U1,
        "time_minutes": 5, "increment_seconds": 0,
    }
    with pytest.raises(ValidationError):
        MatchmakeRequest(**{**base, **kwargs})


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param("US", "US", id="passthrough"),
        pytest.param("ro", "RO", id="uppercases"),
        pytest.param("  gb  ", "GB", id="strips"),
    ],
)
def test_normalize_country_accepts(raw, expected):
    assert normalize_country(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("USA", id="three_letters"),
        pytest.param("U1", id="digit"),
        pytest.param("longstring", id="too_long"),
        pytest.param(123, id="non_string"),
    ],
)
def test_normalize_country_nulls_invalid(raw):
    assert normalize_country(raw) is None


def test_matchmake_request_country_defaults_none():
    req = MatchmakeRequest(nickname="Alice", client_uuid=U1,
                           time_minutes=5, increment_seconds=0)
    assert req.country is None


def test_matchmake_request_normalizes_country():
    req = MatchmakeRequest(nickname="Alice", client_uuid=U1,
                           time_minutes=5, increment_seconds=0, country="  us ")
    assert req.country == "US"


@pytest.mark.parametrize("bad", ["usa", "1", 999, "no-country!"])
def test_matchmake_request_bad_country_nulls_not_rejects(bad):
    """A malformed country must never deny a match — it nulls out instead of raising."""
    req = MatchmakeRequest(nickname="Alice", client_uuid=U1,
                           time_minutes=5, increment_seconds=0, country=bad)
    assert req.country is None


def test_game_start_backward_compat_without_country():
    """An old payload lacking the country keys still parses, defaulting to None."""
    wire = {
        "version": PROTOCOL_VERSION, "type": "game_start",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "white_name": "Alice", "black_name": "Bob",
        "time_minutes": 5, "increment_seconds": 0, "your_color": "white",
    }
    msg = GameStartMessage.model_validate(wire)
    assert msg.white_country is None and msg.black_country is None


def test_game_start_carries_country():
    msg = GameStartMessage(
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        white_name="Alice", black_name="Bob", time_minutes=5,
        increment_seconds=0, your_color="white",
        white_country="US", black_country="RO",
    )
    assert (msg.white_country, msg.black_country) == ("US", "RO")


def test_move_message_uses_alias_for_from():
    raw = {"type": "move", "version": 1, "from": "e2", "to": "e4", "promotion": None}
    msg = MoveMessage.model_validate(raw)
    assert msg.from_sq == "e2"
    assert msg.to_sq == "e4"
    assert msg.promotion is None
    assert msg.model_dump(by_alias=True) == {
        "version": PROTOCOL_VERSION, "type": "move",
        "from": "e2", "to": "e4", "promotion": None,
    }


def test_move_message_promotion_validated():
    with pytest.raises(ValidationError):
        MoveMessage.model_validate({"type": "move", "version": 1,
                                    "from": "e7", "to": "e8", "promotion": "x"})
