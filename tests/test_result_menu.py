"""ResultMenu geometry/render invariants: button labels always fit inside their
buttons (the same fit_text_to_rect path draw_button uses), buttons stay inside the
modal at sane sizes, and clicks route to the keyed callback."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame as pg
import pytest

from frontend.modals.result import BUTTONS, ResultMenu
from frontend.visual.widgets import BUTTON_LABEL_PADDING_PX, fit_text_to_rect


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((800, 600))
    yield
    pg.quit()


def _no_op():
    pass


def _make_menu():
    callbacks = {key: _no_op for _, key in BUTTONS}
    return ResultMenu(pg.display.get_surface(), callbacks)


@pytest.mark.parametrize(
    "title_reason",
    [
        pytest.param(("Black wins", "by checkmate"), id="black_wins_checkmate"),
        pytest.param(("White wins", "by resignation"), id="white_wins_resignation"),
        pytest.param(("Draw", "by insufficient material"), id="draw_insufficient_material"),
        pytest.param(("White wins", "on time"), id="white_wins_on_time"),
    ],
)
def test_button_labels_fit_inside_buttons_at_tight_size(title_reason):
    """A tight rect (heavily resized window) would otherwise be too narrow for the
    labels at the height-derived font; fit_text_to_rect must shrink them to fit."""
    menu = _make_menu()
    menu.set_rect(pg.Rect(0, 0, 240, 160))
    menu.set_text(title_reason)
    menu.draw()
    for label, key in BUTTONS:
        rect = menu.button_rects[key]
        rendered = menu.button_font.render(label, True, (255, 255, 255))
        fitted = fit_text_to_rect(rendered, rect)
        assert fitted.get_width() <= rect.width - 2 * BUTTON_LABEL_PADDING_PX
        assert fitted.get_height() <= rect.height - 2 * BUTTON_LABEL_PADDING_PX


def test_buttons_remain_inside_modal_at_normal_size():
    menu = _make_menu()
    menu.set_rect(pg.Rect(50, 50, 500, 320))
    menu.set_text(("Draw", "by insufficient material"))
    menu.draw()
    modal = pg.Rect(50, 50, 500, 320)
    for _, key in BUTTONS:
        br = menu.button_rects[key]
        assert modal.contains(br)


def test_handle_click_fires_callback():
    fired = []
    cbs = {key: (lambda k=key: fired.append(k)) for _, key in BUTTONS}
    menu = ResultMenu(pg.display.get_surface(), cbs)
    menu.set_rect(pg.Rect(0, 0, 400, 200))
    menu.set_text(("White wins", "by resignation"))
    menu.draw()
    new_game_rect = menu.button_rects["new_game"]
    handled = menu.handle_click(new_game_rect.center)
    assert handled is True
    assert fired == ["new_game"]
