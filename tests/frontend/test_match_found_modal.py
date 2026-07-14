"""The match-found VS reveal: a non-dismissable centered modal that holds for a
short countdown, then fires on_done (which the frontend wires to starting the
game). Verifies the countdown math, the one-shot completion, the win-rail/accent/
amber palette of the reveal, and the shared flat-avatar builder it relies on."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.frontend.modals.match_found import MatchFoundModal
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.widgets import avatar_palette, build_flat_avatar
from tests.helpers import assert_pixel_color


_pg = pygame_display(800, 600)


def _modal():
    m = MatchFoundModal(pg.display.get_surface())
    m.set_rect(pg.Rect(180, 120, 440, 320))
    return m


def _near_count(win, rect, target, tol=26):
    t = pg.Color(target)[:3]
    return sum(
        1
        for x in range(rect.x, rect.right, 2)
        for y in range(rect.y, rect.bottom, 2)
        if max(abs(win.get_at((x, y))[i] - t[i]) for i in range(3)) <= tol
    )


def test_show_makes_visible_and_hide_clears():
    m = _modal()
    assert not m.is_visible()
    m.show("alice", "bob", "white", on_done=lambda: None)
    assert m.is_visible()
    m.hide()
    assert not m.is_visible()


def test_rematch_defaults_false_and_show_carries_flag():
    m = _modal()
    assert m.rematch is False
    m.show("alice", "bob", "white", on_done=lambda: None)
    assert m.rematch is False
    m.show("alice", "bob", "white", on_done=lambda: None, rematch=True)
    assert m.rematch is True


def test_countdown_decrements(monkeypatch):
    now = [1000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: now[0])
    m = _modal()
    m.show("alice", "bob", "white", on_done=lambda: None, seconds=3)
    assert m._remaining() == 3
    now[0] += 1100
    assert m._remaining() == 2
    now[0] += 1000
    assert m._remaining() == 1


def test_update_fires_on_done_once_at_zero(monkeypatch):
    now = [1000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: now[0])
    fired = []
    m = _modal()
    m.show("alice", "bob", "white", on_done=lambda: fired.append(1), seconds=3)
    now[0] += 2900
    m.update()
    assert fired == []
    assert m.is_visible()
    now[0] += 200
    m.update()
    assert fired == [1]
    assert not m.is_visible()
    m.update()
    assert fired == [1]


def test_draw_paints_win_rail_seeded_avatars_and_amber():
    win = pg.display.get_surface()
    m = _modal()
    m.show("Alice", "Bob", "white", on_done=lambda: None, seconds=3)
    win.fill((0, 0, 0))
    m.draw()
    assert _near_count(win, m.rect, Colors.win) > 0
    me_fill, _ = avatar_palette("Alice")
    opp_fill, _ = avatar_palette("Bob")
    assert _near_count(win, m.rect, me_fill) > 0, \
        "the flat me-side avatar paints its name-seeded palette color"
    assert _near_count(win, m.rect, opp_fill) > 0, \
        "the flat opponent-side avatar paints its name-seeded palette color"
    assert _near_count(win, m.rect, Colors.amber_hi) > 0, \
        "the countdown number keeps the amber cue"


def test_show_resolves_each_side_palette_from_its_own_name():
    m = _modal()
    m.show("Alice", "Bob", "white", on_done=lambda: None, seconds=3)
    assert m.me_palette == avatar_palette("Alice")
    assert m.opp_palette == avatar_palette("Bob")


def test_handle_click_is_non_dismissable():
    m = _modal()
    m.show("alice", "bob", "white", on_done=lambda: None)
    assert m.handle_click(m.rect.center) is False
    assert m.is_visible()


def test_flat_avatar_is_a_solid_accent_fill_no_gradient():
    av = build_flat_avatar(52, Colors.accent)
    assert av.get_size() == (52, 52)
    assert_pixel_color(av, 26, 6, Colors.accent, tol=30)
    assert_pixel_color(av, 26, 46, Colors.accent, tol=30), \
        "flat avatar is one solid fill top-to-bottom (no gradient)"


def test_show_maps_country_to_each_side():
    m = _modal()
    m.show("Alice", "Bob", "black", on_done=lambda: None,
           white_country="US", black_country="RO")
    assert m.me_country == "RO"
    assert m.opp_country == "US"


def test_draw_shows_country_flag():
    win = pg.display.get_surface()
    m = _modal()
    m.show("Alice", "Bob", "white", on_done=lambda: None, seconds=3,
           white_country="US", black_country="RO")
    win.fill((0, 0, 0))
    m.draw()
    assert _near_count(win, m.rect, "#b22234", tol=70) > 0
