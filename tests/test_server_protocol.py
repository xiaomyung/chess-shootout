import pytest
from pydantic import ValidationError

from server.protocol import (
    AuthMessage, ErrorMessage, GameStartMessage, MatchmakeRequest,
    MoveMessage, PROTOCOL_VERSION, normalize_nickname,
)


def test_normalize_nickname_strips_and_collapses():
    assert normalize_nickname("  alice  ") == "alice"
    assert normalize_nickname("a   b   c") == "a b c"


def test_normalize_nickname_rejects_empty():
    with pytest.raises(ValueError):
        normalize_nickname("")
    with pytest.raises(ValueError):
        normalize_nickname("   ")


def test_normalize_nickname_rejects_too_long():
    with pytest.raises(ValueError):
        normalize_nickname("x" * 21)


def test_normalize_nickname_rejects_non_printable():
    with pytest.raises(ValueError):
        normalize_nickname("alice\x00")
    with pytest.raises(ValueError):
        normalize_nickname("alice\n")


def test_normalize_nickname_accepts_printable_ascii():
    assert normalize_nickname("Alice 42!") == "Alice 42!"


def test_matchmake_request_normalizes_nickname():
    req = MatchmakeRequest(
        nickname="  Alice  ", client_uuid="u1",
        time_minutes=5, increment_seconds=0,
    )
    assert req.nickname == "Alice"


def test_matchmake_request_rejects_negative_time():
    with pytest.raises(ValidationError):
        MatchmakeRequest(
            nickname="Alice", client_uuid="u1",
            time_minutes=-1, increment_seconds=0,
        )


def test_matchmake_request_default_side_is_random():
    req = MatchmakeRequest(
        nickname="Alice", client_uuid="u1",
        time_minutes=5, increment_seconds=0,
    )
    assert req.side_preference == "random"


def test_matchmake_request_rejects_bad_side():
    with pytest.raises(ValidationError):
        MatchmakeRequest(
            nickname="Alice", client_uuid="u1",
            time_minutes=5, increment_seconds=0,
            side_preference="middle",
        )


def test_messages_carry_protocol_version():
    msg = AuthMessage(session_token="t")
    assert msg.version == PROTOCOL_VERSION
    msg2 = ErrorMessage(reason="version_mismatch")
    assert msg2.version == PROTOCOL_VERSION


def test_move_message_uses_alias_for_from():
    raw = {"type": "move", "version": 1, "from": "e2", "to": "e4", "promotion": None}
    msg = MoveMessage.model_validate(raw)
    assert msg.from_sq == "e2"
    assert msg.to_sq == "e4"
    assert msg.promotion is None
    dumped = msg.model_dump(by_alias=True)
    assert dumped["from"] == "e2"
    assert dumped["to"] == "e4"


def test_move_message_promotion_validated():
    with pytest.raises(ValidationError):
        MoveMessage.model_validate({"type": "move", "version": 1,
                                    "from": "e7", "to": "e8", "promotion": "x"})


def test_game_start_serializes_with_required_fields():
    msg = GameStartMessage(
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        white_name="Alice", black_name="Bob",
        time_minutes=5, increment_seconds=0,
        your_color="white",
    )
    dumped = msg.model_dump()
    assert dumped["type"] == "game_start"
    assert dumped["your_color"] == "white"
