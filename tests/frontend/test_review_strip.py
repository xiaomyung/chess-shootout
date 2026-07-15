import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceColor
from chessshootout.frontend.panels.review_strip import ReviewStrip
from chessshootout.frontend.visual.widgets import avatar_palette
from tests.helpers import draw_strip as _draw, strip_avatar_pixels as _avatar_pixels


_pygame_init = pygame_display(700, 300)


@pytest.fixture
def strip():
    s = ReviewStrip(pg.display.get_surface())
    s.set_rect(pg.Rect(0, 60, 480, 52))
    return s


def test_avatar_fill_matches_the_palette_seeded_by_the_pgn_name(strip):
    strip.set_state("Hikaru", PieceColor.WHITE)
    _draw(strip)
    top, bottom = _avatar_pixels(strip)
    expected_fill, _ = avatar_palette("Hikaru")
    assert (top.r, top.g, top.b) == (expected_fill.r, expected_fill.g, expected_fill.b)
    assert top == bottom, "flat avatar has no gradient (top matches bottom)"


def test_avatar_color_differs_for_a_different_pgn_name(strip):
    strip.set_state("Hikaru", PieceColor.WHITE)
    _draw(strip)
    first_top, _ = _avatar_pixels(strip)
    strip.set_state("Magnus", PieceColor.BLACK)
    _draw(strip)
    second_top, _ = _avatar_pixels(strip)
    assert first_top != second_top, "different PGN names seed different avatar colors"


def test_avatar_color_is_stable_across_redraws_for_the_same_name(strip):
    strip.set_state("Hikaru", PieceColor.WHITE)
    _draw(strip)
    first_top, _ = _avatar_pixels(strip)
    strip.set_state("Hikaru", PieceColor.WHITE, advantage=2)
    _draw(strip)
    second_top, _ = _avatar_pixels(strip)
    assert first_top == second_top, "same name keeps the same avatar color across redraws"
