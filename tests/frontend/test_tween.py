import pytest

from chessshootout.frontend.visual.tween import Tween, out_back, out_cubic, smoothstep


@pytest.mark.parametrize("ease", [smoothstep, out_cubic, out_back])
def test_easing_endpoints(ease):
    assert ease(0.0) == pytest.approx(0.0, abs=1e-9)
    assert ease(1.0) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("ease", [smoothstep, out_cubic])
def test_easing_monotonic(ease):
    xs = [i / 100 for i in range(101)]
    ys = [ease(x) for x in xs]
    assert all(b >= a for a, b in zip(ys, ys[1:]))


def test_out_back_overshoots_past_one():
    assert max(out_back(i / 100) for i in range(101)) > 1.0


@pytest.mark.parametrize("ease", [smoothstep, out_cubic, out_back])
def test_easing_clamps_outside_unit_range(ease):
    assert ease(-1.0) == pytest.approx(ease(0.0))
    assert ease(2.0) == pytest.approx(ease(1.0))


def test_tween_value_at_start_mid_end():
    tw = Tween(0.0, 100.0, 1000, 0, ease=lambda x: x)
    assert tw.value(0) == pytest.approx(0.0)
    assert tw.value(500) == pytest.approx(50.0)
    assert tw.value(1000) == pytest.approx(100.0)
    assert tw.value(5000) == pytest.approx(100.0)


def test_tween_done_at_and_after_duration():
    tw = Tween(0.0, 10.0, 200, 0)
    assert not tw.done(199)
    assert tw.done(200)
    assert tw.done(400)


def test_retarget_continuity_no_visual_jump():
    tw = Tween(0.0, 100.0, 1000, 0, ease=lambda x: x)
    before = tw.value(300)
    tw.retarget(50.0, 300)
    after = tw.value(300)
    assert after == pytest.approx(before)


def test_retarget_reaches_new_target():
    tw = Tween(0.0, 100.0, 1000, 0, ease=lambda x: x)
    tw.retarget(50.0, 300)
    assert tw.value(1300) == pytest.approx(50.0)
    assert tw.done(1300)
