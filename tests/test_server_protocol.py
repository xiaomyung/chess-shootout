import pytest
from pydantic import ValidationError

from chessshootout.server.protocol import (
    AuthMessage, ClockSnapshot, ErrorMessage, GameStartMessage, LockWire,
    MatchmakeRequest, MoveAppliedMessage, MoveMessage, PROTOCOL_VERSION,
    PendingSkillCheckWire, PingMessage, PongMessage, ResumeResponse,
    ResyncDirectiveMessage, SkillCheckRequiredMessage, SkillCheckResultMessage,
    SkillCheckOutcomeWire, SkillCheckShotMessage, SkillCheckSpectateMessage,
    SkillCheckSpectateShotMessage, normalize_country, normalize_nickname,
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
            PingMessage(ply=7),
            {"version": PROTOCOL_VERSION, "type": "ping", "ply": 7},
            id="ping",
        ),
        pytest.param(
            ResyncDirectiveMessage(),
            {"version": PROTOCOL_VERSION, "type": "resync_directive"},
            id="resync_directive",
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
                "heartbeat_interval_seconds": 2.0,
                "grace_seconds": 60.0,
                "rematch": False,
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
        pytest.param(PingMessage(ply=0), id="ping"),
        pytest.param(PongMessage(), id="pong"),
        pytest.param(ResyncDirectiveMessage(), id="resync_directive"),
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
    raw = {"type": "move", "version": PROTOCOL_VERSION, "from": "e2", "to": "e4", "promotion": None}
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
        MoveMessage.model_validate({"type": "move", "version": PROTOCOL_VERSION,
                                    "from": "e7", "to": "e8", "promotion": "x"})


# ---- skill-check protocol (additive; PROTOCOL_VERSION bumped to 2) ----------

def test_protocol_version_bumped_for_skillchecks():
    assert PROTOCOL_VERSION == 2


def test_skill_check_required_round_trips():
    msg = SkillCheckRequiredMessage(
        kind="wheel", seed="abc", value_diff=8, deadline_ms=5000.0,
        from_sq="e4", to_sq="d5")
    dumped = msg.model_dump(by_alias=True)
    assert dumped["from"] == "e4" and dumped["to"] == "d5"
    assert dumped["promotion"] is None and dumped["miss_count"] == 0
    assert SkillCheckRequiredMessage.model_validate(dumped) == msg


def test_skill_check_required_carries_promotion():
    msg = SkillCheckRequiredMessage(
        kind="wheel", seed="s", value_diff=9, deadline_ms=5000.0,
        from_sq="e7", to_sq="e8", promotion="q")
    assert msg.model_dump(by_alias=True)["promotion"] == "q"


def test_skill_check_required_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        SkillCheckRequiredMessage(kind="duel", seed="x", value_diff=0, deadline_ms=5000.0,
                                  from_sq="e4", to_sq="d5")


def test_skill_check_shot_carries_the_client_rendered_elapsed():
    msg = SkillCheckShotMessage.model_validate(
        {"type": "skill_check_shot", "version": PROTOCOL_VERSION, "client_elapsed_ms": 412.0})
    assert msg.client_elapsed_ms == 412.0
    assert SkillCheckShotMessage().client_elapsed_ms == 0.0, "absent -> 0, clamped to a loss"


def test_skill_check_shot_ignores_injected_client_timestamp():
    msg = SkillCheckShotMessage.model_validate(
        {"type": "skill_check_shot", "version": PROTOCOL_VERSION, "client_fire_ms": 123})
    assert not hasattr(msg, "client_fire_ms")
    assert "client_fire_ms" not in msg.model_dump()


def test_skill_check_result_uses_from_to_aliases():
    msg = SkillCheckResultMessage.model_validate(
        {"type": "skill_check_result", "won": False, "from": "e4", "to": "d5"})
    assert (msg.won, msg.from_sq, msg.to_sq) == (False, "e4", "d5")
    assert msg.model_dump(by_alias=True)["from"] == "e4"


def test_skill_check_spectate_carries_the_full_challenge_with_from_to_aliases():
    msg = SkillCheckSpectateMessage(
        kind="aim", seed="abc", value_diff=3, deadline_ms=5000.0,
        **{"from": "d4", "to": "d5"}, promotion=None)
    assert (msg.kind, msg.seed, msg.value_diff) == ("aim", "abc", 3)
    assert (msg.from_sq, msg.to_sq) == ("d4", "d5")
    dumped = msg.model_dump(by_alias=True)
    assert dumped["from"] == "d4" and dumped["to"] == "d5"


def test_skill_check_spectate_shot_round_trips():
    msg = SkillCheckSpectateShotMessage.model_validate(
        {"type": "skill_check_spectate_shot", "elapsed_ms": 742.0,
         "miss_count": 2, "won": False})
    assert (msg.elapsed_ms, msg.miss_count, msg.won) == (742.0, 2, False)
    assert msg.model_dump()["type"] == "skill_check_spectate_shot"


def test_move_applied_skillcheck_fields_default_none_and_round_trip():
    base = dict(from_sq="e2", to_sq="e4", san="e4",
                clock=ClockSnapshot(white_remaining=1.0, black_remaining=1.0, running_for="black"),
                ply=1)
    quiet = MoveAppliedMessage(**base)
    assert quiet.skill_check_kind is None and quiet.skill_check_won is None
    won = MoveAppliedMessage(**base, skill_check_kind="wheel", skill_check_won=True)
    assert MoveAppliedMessage.model_validate(won.model_dump(by_alias=True)) == won


def test_skillcheck_outcome_wire_uses_plain_field_keys_no_alias():
    wire = SkillCheckOutcomeWire(ply=7, kind="wheel", won=False, san="Rxe5")
    dumped = wire.model_dump()
    assert dumped == {"ply": 7, "kind": "wheel", "won": False, "san": "Rxe5"}
    assert wire.model_dump(by_alias=True) == dumped, "no from/to alias, no version key"


def test_skillcheck_outcome_wire_san_defaults_empty_for_wins():
    assert SkillCheckOutcomeWire(ply=1, kind="aim", won=True).san == ""


def test_resume_response_carries_the_skillcheck_log():
    resp = ResumeResponse(
        fen="x", move_history=[],
        clock=ClockSnapshot(white_remaining=1.0, black_remaining=1.0, running_for="white"),
        your_color="white", white_name="A", black_name="B",
        time_minutes=5, increment_seconds=0,
        skillcheck_log=[
            SkillCheckOutcomeWire(ply=1, kind="wheel", won=True),
            SkillCheckOutcomeWire(ply=2, kind="aim", won=False, san="Qxd5")])
    dumped = resp.model_dump()
    assert dumped["skillcheck_log"] == [
        {"ply": 1, "kind": "wheel", "won": True, "san": ""},
        {"ply": 2, "kind": "aim", "won": False, "san": "Qxd5"}]


def test_resume_response_skillcheck_log_defaults_empty():
    resp = ResumeResponse(
        fen="x", move_history=[],
        clock=ClockSnapshot(white_remaining=1.0, black_remaining=1.0, running_for="white"),
        your_color="white", white_name="A", black_name="B",
        time_minutes=5, increment_seconds=0)
    assert resp.skillcheck_log == []


def test_resume_response_pending_and_locks_default_empty():
    resp = ResumeResponse(
        fen="x", move_history=[],
        clock=ClockSnapshot(white_remaining=1.0, black_remaining=1.0, running_for="white"),
        your_color="white", white_name="A", black_name="B",
        time_minutes=5, increment_seconds=0)
    assert resp.pending_skillcheck is None
    assert resp.skillcheck_locks == []


def test_skillcheck_wire_messages_are_byte_identical_after_the_shared_base_refactor():
    """Pins the exact wire shape of the three skill-check messages that share a
    kind/seed/value_diff/deadline_ms/from/to/promotion geometry base, against
    literals captured from the pre-refactor (independently defined) models --
    so factoring out the shared base can never silently change what goes over
    the wire."""
    pending = PendingSkillCheckWire(
        kind="aim", seed="seed123", value_diff=5, deadline_ms=5000.0, elapsed_ms=1200.0,
        miss_count=2, from_sq="e4", to_sq="d5", promotion="q", color="white")
    required = SkillCheckRequiredMessage(
        kind="wheel", seed="seedreq", value_diff=-3, deadline_ms=4000.0, miss_count=1,
        from_sq="a7", to_sq="b8", promotion="n")
    spectate = SkillCheckSpectateMessage(
        kind="aim", seed="seedspec", value_diff=0, deadline_ms=3000.0,
        from_sq="c2", to_sq="c3", promotion=None)

    assert pending.model_dump(by_alias=True) == {
        "kind": "aim", "seed": "seed123", "value_diff": 5, "deadline_ms": 5000.0,
        "elapsed_ms": 1200.0, "miss_count": 2, "from": "e4", "to": "d5",
        "promotion": "q", "color": "white",
    }
    assert required.model_dump(by_alias=True) == {
        "version": PROTOCOL_VERSION, "type": "skill_check_required",
        "kind": "wheel", "seed": "seedreq", "value_diff": -3, "deadline_ms": 4000.0,
        "miss_count": 1, "from": "a7", "to": "b8", "promotion": "n",
    }
    assert spectate.model_dump(by_alias=True) == {
        "version": PROTOCOL_VERSION, "type": "skill_check_spectate",
        "kind": "aim", "seed": "seedspec", "value_diff": 0, "deadline_ms": 3000.0,
        "from": "c2", "to": "c3", "promotion": None,
    }


def test_resume_response_carries_pending_and_locks_when_set():
    pending = PendingSkillCheckWire(
        kind="aim", seed="s", value_diff=3, deadline_ms=5000.0, elapsed_ms=1800.0,
        miss_count=1, from_sq="e4", to_sq="d5", color="white")
    resp = ResumeResponse(
        fen="x", move_history=[],
        clock=ClockSnapshot(white_remaining=1.0, black_remaining=1.0, running_for="white"),
        your_color="white", white_name="A", black_name="B",
        time_minutes=5, increment_seconds=0,
        pending_skillcheck=pending,
        skillcheck_locks=[LockWire(from_sq="e4", to_sq="d5")])
    dumped = resp.model_dump()
    assert dumped["skillcheck_locks"][0] == {"from_sq": "e4", "to_sq": "d5"}, \
        "the client reads /resume via plain model_dump() — field-name keys, not aliases"
    assert dumped["pending_skillcheck"]["from_sq"] == "e4"
    assert dumped["pending_skillcheck"]["to_sq"] == "d5"
    assert dumped["pending_skillcheck"]["color"] == "white"
