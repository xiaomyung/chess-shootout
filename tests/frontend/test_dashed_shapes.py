from tests.conftest import pygame_display
from chessshootout.frontend.visual.draw import chevron_surface, dashed_rounded_rect_surface
from tests.helpers import rgb


_pygame_init = pygame_display(80, 80)

SIZE = 60
RADIUS = 10
BORDER = "#ffcc00"
FILL = "#223344"


def test_top_edge_alternates_dash_and_gap():
    surf = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER, border_width=2, dash=4, gap=3)
    alphas = [surf.get_at((x, 1))[3] for x in range(RADIUS + 2, SIZE - RADIUS - 2)]
    assert any(a == 0 for a in alphas), "gaps must be fully transparent"
    assert any(a > 0 for a in alphas), "dashes must paint the border color"


def test_fill_paints_the_body_when_given():
    surf = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER, fill=FILL)
    px = surf.get_at((SIZE // 2, SIZE // 2))
    assert px[:3] == rgb(FILL)
    assert px[3] == 255


def test_no_fill_leaves_the_body_transparent():
    surf = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER)
    assert surf.get_at((SIZE // 2, SIZE // 2))[3] == 0


def test_zero_radius_degenerates_to_a_dashed_circle():
    d = 40
    surf = dashed_rounded_rect_surface((d, d), d // 2, BORDER)
    corner_alphas = [surf.get_at((x, y))[3] for x in (1, 2) for y in (1, 2)]
    assert all(a == 0 for a in corner_alphas), "a full-radius square must clip its own corners"


def test_memoization_same_args_same_object():
    a = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER, fill=FILL)
    b = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER, fill=FILL)
    assert a is b


def test_memoization_distinguishes_dash_and_gap():
    a = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER, dash=4, gap=3)
    b = dashed_rounded_rect_surface((SIZE, SIZE), RADIUS, BORDER, dash=3, gap=4)
    assert a is not b


def _ink_span(surf, y):
    w, _ = surf.get_size()
    xs = [x for x in range(w) if surf.get_at((x, y))[3] > 40]
    return (max(xs) - min(xs)) if xs else 0


def test_chevron_down_is_wide_at_the_top_narrow_at_the_bottom():
    surf = chevron_surface(16, BORDER, up=False)
    _, h = surf.get_size()
    assert _ink_span(surf, 4) > _ink_span(surf, h - 5)


def test_chevron_up_is_narrow_at_the_top_wide_at_the_bottom():
    surf = chevron_surface(16, BORDER, up=True)
    _, h = surf.get_size()
    assert _ink_span(surf, 4) < _ink_span(surf, h - 5)


def test_chevron_memoization_distinguishes_direction():
    down = chevron_surface(16, BORDER, up=False)
    up = chevron_surface(16, BORDER, up=True)
    assert down is not up
