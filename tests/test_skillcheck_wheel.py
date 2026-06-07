"""The timing Wheel (DBD-style needle + single correct arc, binary land/fail).

Geometry is derived deterministically from a seed (so server and client render
the identical dial), but the server alone adjudicates from its own receive clock
minus a capped half-RTT compensation -- a laggy honest tap is credited fairly, a
lag-switched one cannot widen the window, and an impossibly-early tap is rejected.
Difficulty is exactly the arc fraction of the circle.
"""

import pytest

from chessshootout.skillcheck import wheel
from chessshootout.skillcheck.wheel import WheelChallenge


def land_recv_ms(challenge, start_ms, half_rtt_ms=0.0, target_offset_deg=None):
    if target_offset_deg is None:
        target_offset_deg = challenge.arc_width_deg / 2.0
    target_angle = (challenge.arc_start_deg + target_offset_deg) % 360.0
    sweep = (target_angle - challenge.start_angle_deg) % 360.0
    elapsed = sweep / 360.0 * challenge.period_ms
    while elapsed < wheel.WHEEL_HUMAN_FLOOR_MS:
        elapsed += challenge.period_ms
    return start_ms + elapsed + min(half_rtt_ms, wheel.WHEEL_RTT_CAP_MS)


# ---- seeded geometry -------------------------------------------------------

def test_from_seed_is_deterministic():
    a = WheelChallenge.from_seed("room-1:5")
    b = WheelChallenge.from_seed("room-1:5")
    assert a == b


def test_distinct_seeds_vary_geometry():
    arcs = {WheelChallenge.from_seed(f"s:{i}").arc_start_deg for i in range(20)}
    assert len(arcs) > 10


def test_arc_within_circle():
    for i in range(50):
        ch = WheelChallenge.from_seed(f"s:{i}")
        assert 0.0 <= ch.arc_start_deg < 360.0
        assert ch.arc_width_deg == wheel.WHEEL_ARC_DEGREES


# ---- needle motion ---------------------------------------------------------

def test_needle_starts_at_start_angle():
    ch = WheelChallenge.from_seed("x")
    assert ch.needle_deg(0.0) == pytest.approx(ch.start_angle_deg % 360.0)


def test_needle_wraps_after_one_period():
    ch = WheelChallenge.from_seed("x")
    assert ch.needle_deg(ch.period_ms) == pytest.approx(ch.needle_deg(0.0))


def test_needle_advances_monotonically_within_a_period():
    ch = WheelChallenge.from_seed("x")
    quarter = ch.needle_deg(ch.period_ms * 0.25)
    expected = (ch.start_angle_deg + 90.0) % 360.0
    assert quarter == pytest.approx(expected)


# ---- arc membership (incl. wrap-around) ------------------------------------

def test_in_arc_center_and_edges():
    ch = WheelChallenge(arc_start_deg=100.0, arc_width_deg=60.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert ch.in_arc(130.0) is True
    assert ch.in_arc(100.0) is True
    assert ch.in_arc(159.9) is True
    assert ch.in_arc(160.1) is False
    assert ch.in_arc(99.0) is False


def test_in_arc_handles_wraparound():
    ch = WheelChallenge(arc_start_deg=350.0, arc_width_deg=40.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert ch.in_arc(355.0) is True
    assert ch.in_arc(10.0) is True
    assert ch.in_arc(30.1) is False


# ---- server adjudication ---------------------------------------------------

def test_perfect_tap_lands():
    ch = WheelChallenge.from_seed("room:9")
    recv = land_recv_ms(ch, start_ms=10_000.0)
    assert wheel.adjudicate(ch, recv, start_ms=10_000.0) is True


def test_tap_outside_arc_fails():
    ch = WheelChallenge.from_seed("room:9")
    miss = land_recv_ms(ch, start_ms=10_000.0,
                        target_offset_deg=ch.arc_width_deg + 90.0)
    assert wheel.adjudicate(ch, miss, start_ms=10_000.0) is False


def test_half_rtt_compensation_credits_laggy_tap():
    ch = WheelChallenge.from_seed("room:42")
    half_rtt = 100.0
    recv = land_recv_ms(ch, start_ms=0.0, half_rtt_ms=half_rtt,
                        target_offset_deg=ch.arc_width_deg - 1.0)
    assert wheel.adjudicate(ch, recv, start_ms=0.0, half_rtt_ms=half_rtt) is True
    assert wheel.adjudicate(ch, recv, start_ms=0.0, half_rtt_ms=0.0) is False


def test_rtt_compensation_is_capped():
    assert wheel.effective_elapsed_ms(1000.0, 0.0, 5000.0) == pytest.approx(
        1000.0 - wheel.WHEEL_RTT_CAP_MS)


def test_sub_human_tap_is_rejected():
    ch = WheelChallenge(arc_start_deg=0.0, arc_width_deg=360.0, period_ms=1000.0,
                        start_angle_deg=0.0)
    assert wheel.adjudicate(ch, recv_ms=wheel.WHEEL_HUMAN_FLOOR_MS - 1.0, start_ms=0.0) is False
    assert wheel.adjudicate(ch, recv_ms=wheel.WHEEL_HUMAN_FLOOR_MS + 1.0, start_ms=0.0) is True


# ---- difficulty == arc fraction --------------------------------------------

def test_in_arc_fraction_matches_arc_width():
    ch = WheelChallenge.from_seed("frac")
    steps = 36000
    hits = sum(ch.in_arc(ch.needle_deg(ch.period_ms * i / steps)) for i in range(steps))
    assert hits / steps == pytest.approx(ch.arc_width_deg / 360.0, abs=0.002)
