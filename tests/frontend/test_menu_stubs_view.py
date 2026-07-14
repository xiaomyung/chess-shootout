"""StubView (BattlePassView/ArmoryView/SocialView) — the coming-soon placeholder
sub-view. Fonts must be built once in relayout, like every other menu view
(hero.py, rail.py, rail_cards.py, options_view.py, profile_view.py); draw()
only reads the cached attributes."""

from tests.conftest import pygame_display
from chessshootout.frontend.menu import stubs as stubs_mod
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)


def test_draw_does_not_construct_fonts():
    app = make_app(1000, 800)
    view = app.menu.views["battlepass"]

    font_calls = []
    display_font_calls = []
    real_get_font = stubs_mod.get_font
    real_get_display_font = stubs_mod.get_display_font

    def counting_get_font(*args, **kwargs):
        font_calls.append((args, kwargs))
        return real_get_font(*args, **kwargs)

    def counting_get_display_font(*args, **kwargs):
        display_font_calls.append((args, kwargs))
        return real_get_display_font(*args, **kwargs)

    stubs_mod.get_font = counting_get_font
    stubs_mod.get_display_font = counting_get_display_font
    try:
        window = app.window
        view.draw(window, app.menu._menu_layout)
        view.draw(window, app.menu._menu_layout)
    finally:
        stubs_mod.get_font = real_get_font
        stubs_mod.get_display_font = real_get_display_font

    assert font_calls == []
    assert display_font_calls == []


def test_relayout_rebuilds_the_cached_fonts():
    app = make_app(1000, 800)
    view = app.menu.views["armory"]
    view.relayout(app.menu._menu_layout)

    first_title_font = view._title_font
    first_body_font = view._body_font
    first_button_font = view._button_font

    view.relayout(app.menu._menu_layout)

    assert view._title_font is not first_title_font
    assert view._body_font is not first_body_font
    assert view._button_font is not first_button_font
