"""EdgeTrigger: fires True only on a rising (False -> True) transition.

Drives the skill-check tick / beep cues so they sound once per entry into the
sweet spot, never every frame it stays inside.
"""

from chessshootout.frontend.skillcheck.controller import EdgeTrigger


def test_starts_low_and_first_true_is_a_rising_edge():
    edge = EdgeTrigger()
    assert edge.update(True) is True


def test_first_false_is_not_an_edge():
    edge = EdgeTrigger()
    assert edge.update(False) is False


def test_held_true_only_fires_once():
    edge = EdgeTrigger()
    assert edge.update(True) is True
    assert edge.update(True) is False
    assert edge.update(True) is False


def test_re_arms_after_going_low():
    edge = EdgeTrigger()
    assert edge.update(True) is True
    assert edge.update(False) is False
    assert edge.update(True) is True


def test_full_sequence():
    edge = EdgeTrigger()
    seq = [False, True, True, False, False, True, False, True]
    got = [edge.update(v) for v in seq]
    assert got == [False, True, False, False, False, True, False, True]


def test_truthiness_is_normalized():
    edge = EdgeTrigger()
    assert edge.update(1) is True
    assert edge.update(2) is False
    assert edge.update(0) is False
    assert edge.update("x") is True
