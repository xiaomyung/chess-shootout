"""Per-surface drag-scroll integration: every scrollable surface gains
grab-direction content drag, click-vs-drag reporting (tap -> handle_release
False, drag -> True), and a draggable thumb, all routed through its shared
ScrollView. Options additionally arbitrates control-vs-content on press so a
slider/toggle press never arms a scroll."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.pieces import Piece, PieceType, PieceColor
from chessshootout.backend.utils import Square, Move, HistoryEntry
from chessshootout.frontend.modals.country_picker import CountryPicker
from chessshootout.frontend.modals.directory_browser import DirectoryBrowser
from chessshootout.frontend.modals.help import HelpModal, HOTKEYS
from chessshootout.frontend.menu.options_rows import OptionsBody, ToggleRow, _Fonts
from chessshootout.frontend.panels.right import RightMenu
from chessshootout.frontend.visual.fonts import get_font, get_mono_font


_pygame_init = pygame_display(1000, 800)


def _drag(surface, x, y_from, y_to):
    armed = surface.handle_press((x, y_from))
    surface.handle_motion((x, y_to))
    dragged = surface.handle_release((x, y_to))
    return armed, dragged


def _picker():
    cp = CountryPicker(pg.display.get_surface())
    cp.set_rect(pg.Rect(40, 40, 520, 560))
    cp.show("US", lambda c: None)
    cp.draw()
    return cp


def test_country_drag_scrolls_in_grab_direction():
    cp = _picker()
    lr = cp._list_rect
    armed, dragged = _drag(cp, lr.centerx, lr.y + 150, lr.y + 100)
    assert armed is True
    assert dragged is True
    assert cp._scroll_px == pytest.approx(50.0)


def test_country_tap_is_not_a_drag():
    cp = _picker()
    lr = cp._list_rect
    assert cp.handle_press((lr.centerx, lr.centery)) is True
    assert cp.handle_release((lr.centerx, lr.centery)) is False
    assert cp._scroll_px == 0.0


def test_country_press_outside_list_does_not_arm():
    cp = _picker()
    assert cp.handle_press(cp._cancel_rect.center) is False


def test_country_thumb_drag_jumps_offset():
    cp = _picker()
    thumb = cp.scroll.thumb_rect()
    assert thumb is not None
    travel = cp._list_rect.height - thumb.height
    cp.handle_press(thumb.center)
    cp.scroll.handle_motion((thumb.centerx, thumb.centery + travel))
    assert cp._scroll_px == pytest.approx(cp.scroll._max_px())
    assert cp.handle_release(thumb.center) is True
    assert cp.scroll._flinging is False


def _browser():
    db = DirectoryBrowser(pg.display.get_surface())
    db.set_rect(pg.Rect(240, 100, 520, 600))
    db.show("/tmp", lambda p: None)
    db.entries = [(f"f{i}", f"/tmp/f{i}", False, "1 KB") for i in range(80)]
    db.draw()
    return db


def test_directory_drag_scrolls():
    db = _browser()
    lr = db._list_rect
    armed, dragged = _drag(db, lr.centerx, lr.y + 160, lr.y + 90)
    assert armed is True and dragged is True
    assert db._scroll_px == pytest.approx(70.0)


def test_directory_tap_is_not_a_drag():
    db = _browser()
    lr = db._list_rect
    assert db.handle_press((lr.centerx, lr.centery)) is True
    assert db.handle_release((lr.centerx, lr.centery)) is False


def _help():
    hm = HelpModal(pg.display.get_surface())
    hm.set_rect(pg.Rect(0, 0, 320, 280))
    hm.show(HOTKEYS)
    hm.draw()
    return hm


def test_help_overflows_and_drags():
    hm = _help()
    assert hm.scroll.scrollable() is True
    rr = hm._rows_rect
    armed, dragged = _drag(hm, rr.centerx, rr.y + 80, rr.y + 40)
    assert armed is True and dragged is True
    assert hm._scroll_px == pytest.approx(40.0)


def test_help_draws_a_thumb_when_overflowing():
    hm = _help()
    hm.handle_press((hm._rows_rect.centerx, hm._rows_rect.y + 40))
    hm.draw()
    assert hm.scroll.thumb_rect() is not None


def _options_fonts():
    return _Fonts(get_font(14, bold=True), get_font(11), get_font(10, bold=True),
                  get_mono_font(12), get_font(13, bold=True))


def _options():
    state = {f"k{i}": False for i in range(30)}
    rows = [ToggleRow(f"Option {i}", "desc",
                      (lambda i=i: state[f"k{i}"]),
                      (lambda v, i=i: state.__setitem__(f"k{i}", v)))
            for i in range(30)]
    body = OptionsBody()
    body.set_sections([("Section", rows)])
    body.draw(pg.display.get_surface(), pg.Rect(100, 60, 460, 560), _options_fonts())
    return body, rows


def test_options_empty_space_arms_scroll():
    body, _ = _options()
    assert body.scroll.scrollable() is True
    assert body.handle_press((body.rect.x + 4, body.rect.y + 20)) is True


def test_options_control_press_does_not_arm_scroll():
    body, rows = _options()
    ctl = rows[0]._ctl
    assert ctl.width > 0
    assert body.handle_press(ctl.center) is False


def test_options_drag_scrolls_body():
    body, _ = _options()
    x = body.rect.x + 4
    armed, dragged = _drag(body, x, body.rect.y + 30, body.rect.y + 0)
    assert armed is True and dragged is True
    assert body._scroll_px == pytest.approx(30.0)


class _Board:
    def __init__(self):
        self.review_ply = None
        self.jumped = []

    def jump_to_review_ply(self, ply):
        self.jumped.append(ply)
        self.review_ply = ply


def _entry(san):
    move = Move(Square(6, 0), Square(5, 0), Piece(PieceType.PAWN, PieceColor.WHITE))
    return HistoryEntry(move=move, prev_castling_rights=(), prev_en_passant_target=None,
                        prev_halfmove_clock=0, position_key_added=("k",), san=san)


def _right():
    backend = Backend()
    backend.new_game()
    board = _Board()
    rm = RightMenu(pg.display.get_surface(), backend, {}, board=board)
    rm.set_rect(pg.Rect(0, 0, 320, 600))
    backend.move_history = [_entry(f"a{i % 8 + 1}") for i in range(200)]
    rm.draw_menu()
    return rm, board


def test_right_drag_scrolls_without_jumping_ply():
    rm, board = _right()
    vp = rm._moves_viewport
    before = rm.scroll_offset
    armed, dragged = _drag(rm, vp.centerx, vp.y + 30, vp.bottom - 5)
    assert armed is True and dragged is True
    assert rm.scroll_offset != before
    assert board.jumped == []


def test_right_press_on_board_area_does_not_arm():
    rm, _ = _right()
    assert rm.handle_press((rm._moves_viewport.x - 50, rm._moves_viewport.centery)) is False


def test_right_tap_is_not_a_drag():
    rm, _ = _right()
    vp = rm._moves_viewport
    assert rm.handle_press((vp.centerx, vp.centery)) is True
    assert rm.handle_release((vp.centerx, vp.centery)) is False
