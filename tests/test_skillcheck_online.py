"""The pure, server-importable online adjudication layer (chessshootout/skillcheck/
online.py) that both the authoritative server and the client build on: the single
challenge_from() both sides render/adjudicate from, server-secret selection,
value_diff parity, the full-RTT + ms-quantized shot adjudication, the shared human
floor applied to BOTH kinds, the 5s deadline as a hard ceiling, and the rtt-credit
session-min/cap policy. These are the security-critical primitives, so each property
is pinned independently.
"""

import pytest

from chessshootout.backend.pieces import PIECE_VALUES, PieceType
from chessshootout.skillcheck import online
from chessshootout.skillcheck.aim import AimChallenge
from chessshootout.skillcheck.types import SkillCheckKind, TriggerFacts
from chessshootout.skillcheck.wheel import WheelChallenge, period_for_diff
from tests.helpers import BLACK, K, P, Q, WHITE, make_backend, piece, sq

WHEEL = SkillCheckKind.WHEEL
AIM = SkillCheckKind.AIM
NONE = SkillCheckKind.NONE


# ---- challenge_from: the single source both sides build ---------------------

def test_challenge_from_wheel_uses_value_diff_scaled_period():
    ch = online.challenge_from(WHEEL, "s", value_diff=9)
    assert isinstance(ch, WheelChallenge)
    assert ch.period_ms == pytest.approx(period_for_diff(9))


def test_challenge_from_aim_threads_value_diff():
    ch = online.challenge_from(AIM, "s", value_diff=5)
    assert isinstance(ch, AimChallenge)
    assert ch == AimChallenge.from_seed("s", 5)


def test_challenge_from_is_deterministic_for_seed_and_diff():
    a = online.challenge_from(WHEEL, "seed-x", 4)
    b = online.challenge_from(WHEEL, "seed-x", 4)
    assert a == b


def test_challenge_from_none_kind_is_none():
    assert online.challenge_from(NONE, "s", 0) is None


# ---- value_diff parity (server must match the client render) ----------------

def test_value_diff_capture_is_capturer_minus_captured():
    facts = TriggerFacts(is_capture=True, capturer_value=1, captured_value=9)
    assert online.value_diff_for(facts) == -8


def test_value_diff_noncapturing_promotion_uses_chosen_piece():
    facts = TriggerFacts(is_promotion=True)
    assert online.value_diff_for(facts, "q") == PIECE_VALUES[PieceType.QUEEN]
    assert online.value_diff_for(facts, "n") == PIECE_VALUES[PieceType.KNIGHT]


def test_value_diff_capturing_promotion_uses_the_capture_not_the_piece():
    facts = TriggerFacts(is_capture=True, capturer_value=1, captured_value=5, is_promotion=True)
    assert online.value_diff_for(facts, "q") == -4, "a capturing promotion scores as the capture"


def test_value_diff_quiet_move_is_zero():
    assert online.value_diff_for(TriggerFacts()) == 0


def test_promo_value_maps_chars_through_piece_values():
    assert online.promo_value("r") == PIECE_VALUES[PieceType.ROOK]
    assert online.promo_value(None) == 0
    assert online.promo_value("x") == 0


# ---- server-secret selection -----------------------------------------------

def _qxp():
    return make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    })


def test_select_kind_is_deterministic_for_a_secret():
    backend = _qxp()
    a = online.select_kind("secret", 0, backend, sq(4, 3), sq(3, 3), set())
    b = online.select_kind("secret", 0, backend, sq(4, 3), sq(3, 3), set())
    assert a == b and a in (WHEEL, AIM)


def test_select_kind_differs_by_secret():
    backend = _qxp()
    kinds = {online.select_kind("k{}".format(i), 0, backend, sq(4, 3), sq(3, 3), set())
             for i in range(40)}
    assert kinds == {WHEEL, AIM}, "different secrets sweep both capture outcomes"


def test_select_kind_unpredictable_without_the_secret():
    backend = _qxp()
    server = online.select_kind("server-secret", 7, backend, sq(4, 3), sq(3, 3), set())
    guesses = {online.select_kind("guess{}".format(i), 7, backend, sq(4, 3), sq(3, 3), set())
               for i in range(200)}
    assert len(guesses) > 1, "a client guessing the secret cannot pin the kind"
    assert server in (WHEEL, AIM)


def test_select_kind_locked_move_is_none():
    backend = _qxp()
    locks = {(sq(4, 3), sq(3, 3))}
    assert online.select_kind("s", 0, backend, sq(4, 3), sq(3, 3), locks) == NONE


def test_select_kind_two_legal_one_locked_is_forced_none():
    backend = make_backend({
        sq(7, 0): piece(K, WHITE), sq(5, 2): piece(K, BLACK), sq(1, 7): piece(P, BLACK),
    })
    locks = {(sq(7, 0), sq(6, 0))}
    assert online.select_kind("s", 0, backend, sq(7, 0), sq(7, 1), locks) == NONE


# ---- shot adjudication: ms-quantized, full-RTT, floor + deadline ------------

def _always_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def _never_arc():
    return WheelChallenge(arc_start_deg=0.0, arc_width_deg=0.0, period_ms=1000.0,
                          start_angle_deg=0.0)


def test_shot_elapsed_subtracts_full_rtt_and_quantizes_to_int():
    e = online.shot_elapsed_ms(recv_ms=1500.7, start_ms=1000.0, credit_ms=100.0)
    assert e == 400 and isinstance(e, int)


def test_shot_elapsed_clamps_negative_to_zero():
    assert online.shot_elapsed_ms(recv_ms=1000.0, start_ms=1000.0, credit_ms=200.0) == 0


def test_shot_below_human_floor_never_wins_either_kind():
    floor = int(online.SKILLCHECK_HUMAN_FLOOR_MS)
    assert online.shot_wins(WHEEL, _always_arc(), floor - 1) is False
    aim = AimChallenge.from_seed("a", 0)
    assert online.shot_wins(AIM, aim, floor - 1, miss_count=0) is False


def test_shot_at_floor_in_arc_wins():
    floor = int(online.SKILLCHECK_HUMAN_FLOOR_MS)
    assert online.shot_wins(WHEEL, _always_arc(), floor) is True


def test_shot_outside_arc_fails():
    assert online.shot_wins(WHEEL, _never_arc(), 300) is False


def test_shot_past_deadline_never_wins():
    late = int(online.SKILLCHECK_DEADLINE_MS) + 1
    assert online.shot_wins(WHEEL, _always_arc(), late) is False


def test_aim_shot_uses_miss_count_geometry():
    aim = AimChallenge.from_seed("aimseed", 0)
    elapsed = next(e for e in range(120, 5000, 5) if aim.on_target(e, 0))
    assert online.shot_wins(AIM, aim, elapsed, miss_count=0) is True


def test_is_past_deadline_boundary():
    assert online.is_past_deadline(online.SKILLCHECK_DEADLINE_MS) is False
    assert online.is_past_deadline(online.SKILLCHECK_DEADLINE_MS + 0.1) is True


# ---- rtt credit policy: session-min + cap, never inflatable -----------------

def test_rtt_credit_is_session_min_not_latest():
    assert online.rtt_credit_ms(rtt_at_issue_ms=200.0, session_min_ms=20.0) == 20.0


def test_rtt_credit_capped():
    assert online.rtt_credit_ms(5000.0, 5000.0) == online.SKILLCHECK_RTT_CAP_MS


def test_rtt_credit_clamps_negative_inputs_to_zero():
    assert online.rtt_credit_ms(-50.0, -10.0) == 0.0


def test_rtt_inflation_cannot_buy_a_sub_floor_win():
    challenge = _always_arc()
    credit = online.rtt_credit_ms(rtt_at_issue_ms=200.0, session_min_ms=20.0)
    elapsed = online.shot_elapsed_ms(recv_ms=120.0, start_ms=0.0, credit_ms=credit)
    assert elapsed == 100, "a 20ms session-min credit, not 200, so a 120ms arrival stays sub-floor"
    assert online.shot_wins(WHEEL, challenge, elapsed) is False


# ---- aim no longer crashes on a negative effective elapsed ------------------

def test_aim_piece_scale_no_crash_on_negative_elapsed():
    aim = AimChallenge.from_seed("neg", 0)
    assert aim.piece_scale(-1000.0, 0) == aim.piece_scale(0.0, 0)
    assert isinstance(aim.on_target(-5.0, 0), bool)
    assert isinstance(aim.is_expired(-5.0, 0), bool)
