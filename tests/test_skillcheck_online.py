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


def test_value_diff_promotion_scores_as_a_pawn_capturing_the_promoted_piece():
    facts = TriggerFacts(is_promotion=True)
    pawn = PIECE_VALUES[PieceType.PAWN]
    assert online.value_diff_for(facts, "q") == pawn - PIECE_VALUES[PieceType.QUEEN]
    assert online.value_diff_for(facts, "q") == -8, "queen promotion is as easy as pawn x queen"
    assert online.value_diff_for(facts, "n") == pawn - PIECE_VALUES[PieceType.KNIGHT]
    assert online.value_diff_for(facts, "n") == -2, "knight underpromotion is a bit harder"


def test_promotion_takes_precedence_over_the_landing_capture_for_value():
    facts = TriggerFacts(is_capture=True, capturer_value=1, captured_value=5, is_promotion=True)
    assert online.value_diff_for(facts, "q") == -8, \
        "a capturing promotion scores as the piece it promotes to, not the piece it lands on"


def test_value_diff_quiet_move_is_zero():
    assert online.value_diff_for(TriggerFacts()) == 0


def test_promotion_value_drives_an_easy_slow_needle():
    diff = online.value_diff_for(TriggerFacts(is_promotion=True), "q")
    assert diff < 0
    assert period_for_diff(diff) > period_for_diff(0), \
        "promoting to a queen spins slower (easier) -- the same as a pawn taking a queen"


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


def test_adjudicated_elapsed_uses_the_client_value_when_physically_plausible():
    e = online.adjudicated_elapsed_ms(client_elapsed_ms=380.4, recv_ms=1500.0, start_ms=1000.0)
    assert e == 380 and isinstance(e, int), "honest play is judged at exactly what the client saw"


def test_adjudicated_elapsed_floors_at_zero():
    assert online.adjudicated_elapsed_ms(0.0, recv_ms=1000.0, start_ms=1000.0) == 0


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


# ---- bounded lag-comp: honest play exact, cheating capped to the lag window -

def test_a_too_late_claim_is_clamped_down_to_the_arrival_time():
    # the player cannot have perceived MORE elapsed than the shot physically took to arrive
    assert online.adjudicated_elapsed_ms(9999.0, recv_ms=1500.0, start_ms=1000.0) == 500


def test_a_too_early_claim_is_clamped_up_to_the_lag_bound():
    # raw = 1000, bound 200 -> earliest plausible perceived elapsed is raw - bound = 800
    assert online.adjudicated_elapsed_ms(0.0, recv_ms=2000.0, start_ms=1000.0) == 800


def test_the_manipulable_window_is_exactly_the_lag_bound():
    lo = online.adjudicated_elapsed_ms(-1e9, recv_ms=5000.0, start_ms=0.0)
    hi = online.adjudicated_elapsed_ms(1e9, recv_ms=5000.0, start_ms=0.0)
    assert hi - lo == int(online.SKILLCHECK_LAG_BOUND_MS), \
        "a modded client can shift its effective time by at most the lag bound"


def test_a_forged_early_claim_cannot_buy_a_sub_floor_win():
    effective = online.adjudicated_elapsed_ms(0.0, recv_ms=119.0, start_ms=0.0)
    assert effective == 0
    assert online.shot_wins(WHEEL, _always_arc(), effective) is False, "sub-floor stays a loss"


# ---- aim no longer crashes on a negative effective elapsed ------------------

def test_aim_piece_scale_no_crash_on_negative_elapsed():
    aim = AimChallenge.from_seed("neg", 0)
    assert aim.piece_scale(-1000.0, 0) == aim.piece_scale(0.0, 0)
    assert isinstance(aim.on_target(-5.0, 0), bool)
    assert isinstance(aim.is_expired(-5.0, 0), bool)


# ---- the server-owned skill-check time cap ---------------------------------

@pytest.mark.parametrize("initial_seconds, expected", [
    (300, 5000.0),     # 5+0: 10% = 30s, base 5s wins
    (1800, 5000.0),    # 30+0: 10% = 180s, base 5s wins
    (40, 4000.0),      # 40s game: 10% = 4s binds below the base
    (20, 2000.0),      # 20s game: 10% = 2s
    (0, 5000.0),       # no clock -> the base deadline
])
def test_skillcheck_deadline_ms_caps_at_min_base_tenth_and_ceiling(initial_seconds, expected):
    assert online.skillcheck_deadline_ms(initial_seconds) == expected


def test_skillcheck_deadline_never_exceeds_the_base_and_shrinks_for_fast_tc():
    assert online.skillcheck_deadline_ms(600) == online.SKILLCHECK_DEADLINE_MS
    assert online.skillcheck_deadline_ms(30) < online.SKILLCHECK_DEADLINE_MS
    assert online.skillcheck_deadline_ms(30) == 30 * 0.10 * 1000.0


def test_is_past_deadline_honors_a_capped_deadline():
    assert online.is_past_deadline(3500, deadline_ms=3000.0) is True
    assert online.is_past_deadline(3500) is False


def test_shot_past_the_capped_deadline_never_wins():
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=800.0,
                        start_angle_deg=0.0)
    assert online.shot_wins(SkillCheckKind.WHEEL, ch, 3500, deadline_ms=3000.0) is False
    assert online.shot_wins(SkillCheckKind.WHEEL, ch, 3500) is True
