"""Draw/takeback/rematch offer banners: top-of-board pills that replace the old
offer confirm-modal. They stack, dedupe by key, fire on_ok/on_no on a button
click and remove themselves, and — crucially — they do NOT block the board: a
click outside the buttons falls through to the game (verified through the real
click cascade)."""

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.panels.banners import OfferBanners
from chessshootout.frontend.visual.colors import Colors


_pg = pygame_display(1000, 800)


def _banners():
    return OfferBanners(pg.display.get_surface())


def _push(ob, key="draw_offered", ok=None, no=None):
    ob.push(key, "🤝", "bob", "offers a draw", "Accept", "Decline",
            on_ok=ok or (lambda: None), on_no=no or (lambda: None))


def _settle(ob):
    for b in ob._banners:
        b["pushed_at"] -= 5000


BOARD = pg.Rect(60, 60, 600, 600)


def test_push_adds_and_dedupes_by_key():
    ob = _banners()
    _push(ob)
    assert ob.count() == 1
    _push(ob)
    assert ob.count() == 1
    ob.push("takeback_offered", "↩️", "bob", "wants a takeback", "Allow", "Deny",
            on_ok=lambda: None, on_no=lambda: None)
    assert ob.count() == 2


def test_clear_empties():
    ob = _banners()
    _push(ob)
    ob.clear()
    assert ob.is_empty()


def test_accept_fires_on_ok_and_removes():
    ob = _banners()
    fired = []
    _push(ob, ok=lambda: fired.append("ok"))
    ob.draw(BOARD)
    assert ob.handle_click(ob._banners[0]["ok_rect"].center) is True
    assert fired == ["ok"]
    assert ob.is_empty()


def test_decline_fires_on_no_and_removes():
    ob = _banners()
    fired = []
    _push(ob, no=lambda: fired.append("no"))
    ob.draw(BOARD)
    assert ob.handle_click(ob._banners[0]["no_rect"].center) is True
    assert fired == ["no"]
    assert ob.is_empty()


def test_click_outside_buttons_does_not_consume():
    ob = _banners()
    _push(ob)
    ob.draw(BOARD)
    assert ob.handle_click((BOARD.x + 2, BOARD.bottom - 2)) is False
    assert ob.count() == 1


def test_icon_chip_is_painted():
    win = pg.display.get_surface()
    ob = _banners()
    _push(ob)
    win.fill((0, 0, 0))
    _settle(ob)
    ob.draw(BOARD)
    chip = pg.Color(Colors.icon_chip_bg)[:3]
    found = sum(
        1
        for x in range(BOARD.x, BOARD.right, 2)
        for y in range(BOARD.top, BOARD.top + 80, 2)
        if win.get_at((x, y))[:3] == chip
    )
    assert found > 0


def test_accept_button_fill_is_accent():
    win = pg.display.get_surface()
    ob = _banners()
    _push(ob)
    win.fill((0, 0, 0))
    _settle(ob)
    ob.draw(BOARD)
    ok = ob._banners[0]["ok_rect"]
    accent = pg.Color(Colors.accent)[:3]
    found = sum(
        1
        for x in range(ok.x, ok.right)
        for y in range(ok.y, ok.bottom)
        if win.get_at((x, y))[:3] == accent
    )
    assert found > 0


def _start_local(app):
    app._on_start_game({
        "mode": "single_screen", "nickname": "alice",
        "time_minutes": 5, "increment_seconds": 2, "side": "white",
    })


def test_banner_does_not_block_board_clicks():
    app = Frontend(1000, 800)
    _start_local(app)
    app.coordinator.offer_banners.push(
        "draw_offered", "🤝", "bob", "offers a draw", "Accept", "Decline",
        on_ok=lambda: None, on_no=lambda: None)
    app.draw_frame()
    center = app.game.board._cell_rect(6, 4).center
    app.input_router.mouse_left_clicked(center)
    assert app.game.board.selected_square == Square(6, 4)


def test_banner_does_not_gate_menu_overlay():
    app = Frontend(1000, 800)
    app.coordinator.offer_banners.push(
        "draw_offered", "🤝", "bob", "offers a draw", "Accept", "Decline",
        on_ok=lambda: None, on_no=lambda: None)
    assert app._blocking_modal_visible() is False


def test_banner_slides_down_into_view():
    ob = _banners()
    _push(ob)
    ob.draw(BOARD)
    top_at_push = ob._banners[0]["ok_rect"].top
    assert top_at_push < BOARD.top
    _settle(ob)
    ob.draw(BOARD)
    assert ob._banners[0]["ok_rect"].top > top_at_push
    assert ob._banners[0]["ok_rect"].top >= BOARD.top
