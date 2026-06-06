"""Grab-and-wiggle physics for dragged pieces: grab-point geometry, the torsional-spring
tilt integrator, the release settle (legal / illegal / promotion glide), reduce-motion
gating, and drag cancellation. The physics tick takes ``now`` explicitly, so these drive
time deterministically instead of relying on the wall clock."""

import math
import os
from collections import Counter

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg
import pytest

import chessshootout.frontend.board.board as board_mod
from chessshootout.frontend.board import Board
from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import Square
from chessshootout.backend.pieces import Piece, PieceType, PieceColor

WHITE, BLACK = PieceColor.WHITE, PieceColor.BLACK
TWO_PI = 2 * math.pi


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((900, 900))
    yield
    pg.quit()


def _make_board():
    landed = []
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend,
               move_landed_callback=lambda entry: landed.append(entry))
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 640, 640))
    return bd, backend, landed


def _seed_position(backend, piece_map, turn=WHITE):
    backend.state = [[None] * 8 for _ in range(8)]
    for sq, piece in piece_map.items():
        backend.state[sq.row][sq.col] = piece
    backend.turn = turn
    backend.move_history = []
    backend.position_counts = Counter()
    backend.position_counts[backend._position_key()] = 1


def _grab(bd, sq, where="top"):
    bd.handle_click(sq)
    geom = bd._sprite_geom[(bd.match.piece_at(sq).type, bd.match.piece_at(sq).color)]
    rect = bd._cell_rect(sq.row, sq.col)
    local = geom["top_center"] if where == "top" else geom["center"]
    bd._press_pos = (rect.x + local[0], rect.y + local[1])
    bd._begin_drag_physics(bd._press_pos, 0)


def _cursor_to(bd, sq):
    rect = bd._cell_rect(sq.row, sq.col)
    bd._drag["cursor"] = (rect.centerx, rect.centery)


def _finish_settle(bd):
    bd.update_drag_physics(bd._drag["settle_start_ms"] + 100000)


def _smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _drag_sweep(bd, dist_px, dur_ms, hold_ms=1200, step=16):
    """Move the cursor dist_px horizontally over dur_ms (smoothstep), then hold.
    Returns the peak absolute tilt reached."""
    cx, cy = 450, 450
    t = 0
    peak = 0.0
    n = max(1, int(dur_ms / step))
    for i in range(n + 1):
        t += step
        bd._drag["cursor"] = (cx + dist_px * _smoothstep(i / n), cy)
        bd.update_drag_physics(t)
        peak = max(peak, abs(bd._drag["theta"]))
    for _ in range(int(hold_ms / step)):
        t += step
        bd._drag["cursor"] = (cx + dist_px, cy)
        bd.update_drag_physics(t)
        peak = max(peak, abs(bd._drag["theta"]))
    return peak


def test_sprite_geom_populated_for_every_piece():
    bd, _, _ = _make_board()
    assert len(bd._sprite_geom) == 12
    for geom in bd._sprite_geom.values():
        assert geom["center"] == geom["bbox"].center
        assert geom["top_center"] == (geom["bbox"].centerx, geom["bbox"].top)


def test_grab_on_opaque_pixel_is_exact():
    bd, bk, _ = _make_board()
    sq = Square(6, 4)
    piece = bk.piece_at(sq)
    geom = bd._sprite_geom[(piece.type, piece.color)]
    rect = bd._cell_rect(sq.row, sq.col)
    press = (rect.x + geom["center"][0], rect.y + geom["center"][1])
    assert bd._grab_local_for(sq, press, piece) == tuple(geom["center"])


@pytest.mark.parametrize("press_offset", [
    pytest.param((1, 1), id="transparent_corner"),
    pytest.param(None, id="no_press_pos"),
])
def test_grab_outside_visible_art_uses_top_center(press_offset):
    bd, bk, _ = _make_board()
    sq = Square(6, 4)
    piece = bk.piece_at(sq)
    geom = bd._sprite_geom[(piece.type, piece.color)]
    rect = bd._cell_rect(sq.row, sq.col)
    press = None if press_offset is None else (rect.x + press_offset[0], rect.y + press_offset[1])
    assert bd._grab_local_for(sq, press, piece) == geom["top_center"]


def test_grab_local_is_flip_invariant():
    bd, bk, _ = _make_board()
    sq = Square(6, 4)
    piece = bk.piece_at(sq)
    geom = bd._sprite_geom[(piece.type, piece.color)]
    rect = bd._cell_rect(sq.row, sq.col)
    upright = bd._grab_local_for(sq, (rect.x + geom["center"][0],
                                      rect.y + geom["center"][1]), piece)
    bd.flipped = True
    frect = bd._cell_rect(sq.row, sq.col)
    flipped = bd._grab_local_for(sq, (frect.x + geom["center"][0],
                                      frect.y + geom["center"][1]), piece)
    assert upright == flipped


def test_begin_drag_on_empty_square_leaves_no_state():
    bd, _, _ = _make_board()
    bd.selected_square = Square(4, 4)
    bd._press_pos = (100, 100)
    bd._begin_drag_physics((100, 100), 0)
    assert bd.dragging_from is None
    assert bd._drag is None


def test_grab_records_com_and_lever_arm():
    bd, bk, _ = _make_board()
    _grab(bd, Square(6, 4), where="top")
    d = bd._drag
    com = bd._sprite_geom[(d["piece"].type, d["piece"].color)]["center"]
    assert d["com_local"] == tuple(com)
    assert d["r_local"] == (com[0] - d["grab_local"][0], com[1] - d["grab_local"][1])


def test_settles_to_upright_when_cursor_holds_still():
    bd, _, _ = _make_board()
    _grab(bd, Square(7, 3), where="top")
    bd._drag["theta"] = 0.6
    cursor = bd._drag["cursor"]
    t = 0
    for _ in range(120):
        t += 16
        bd._drag["cursor"] = cursor
        bd.update_drag_physics(t)
    assert abs(bd._drag["theta"]) < 0.05
    assert abs(bd._drag["omega"]) < 0.3


def test_bounded_and_finite_under_violent_input():
    bd, _, _ = _make_board()
    _grab(bd, Square(7, 3), where="top")
    t = 0
    for i in range(80):
        t += 16
        bd._drag["cursor"] = (450 + (300 if i % 2 else -300), 450 + (200 if i % 3 else -150))
        bd.update_drag_physics(t)
        assert math.isfinite(bd._drag["theta"])
        assert abs(bd._drag["omega"]) <= board_mod.DRAG_OMEGA_MAX + 1e-6


def test_hard_flick_can_exceed_a_full_rotation():
    bd, _, _ = _make_board()
    _grab(bd, Square(7, 3), where="top")
    peak = _drag_sweep(bd, 300, 80)
    assert peak > TWO_PI


def test_gentle_drag_does_not_spin():
    bd, _, _ = _make_board()
    _grab(bd, Square(7, 3), where="top")
    peak = _drag_sweep(bd, 90, 320, hold_ms=0)
    assert peak < TWO_PI


def test_frame_rate_independent_within_tolerance():
    """Gentle, sub-barrier motion converges across frame rates; a hard spinning motion
    is a chaotic barrier-crossing and legitimately sampling-sensitive, so it is not
    asserted here."""
    def run(step):
        bd, _, _ = _make_board()
        _grab(bd, Square(7, 3), where="top")
        t = 0.0
        while t < 500:
            t += step
            x = 450 + 45 * math.sin(2 * math.pi * (t / 500.0))
            bd._drag["cursor"] = (x, 450)
            bd.update_drag_physics(t)
        return bd._drag["theta"]
    assert abs(run(16) - run(8)) < 0.15


def test_reduced_motion_never_tilts(monkeypatch):
    monkeypatch.setattr(board_mod.env, "get_reduce_motion", lambda: True)
    bd, _, _ = _make_board()
    _grab(bd, Square(7, 3), where="top")
    assert bd._drag["reduced"] is True
    t = 0
    for i in range(40):
        t += 16
        bd._drag["cursor"] = (450 + 200 * (i % 2), 450)
        bd.update_drag_physics(t)
        assert bd._drag["theta"] == 0.0


def test_grab_outside_piece_slides_in_without_flicking():
    bd, bk, _ = _make_board()
    sq = Square(6, 4)
    piece = bk.piece_at(sq)
    geom = bd._sprite_geom[(piece.type, piece.color)]
    bd.handle_click(sq)
    rect = bd._cell_rect(sq.row, sq.col)
    bd._press_pos = (rect.x + 1, rect.y + 1)
    bd._begin_drag_physics((200, 200), 0)
    rest = (rect.x + geom["top_center"][0], rect.y + geom["top_center"][1])
    assert bd._drag["anchor"] == rest
    bd.update_drag_physics(16)
    ax, _ = bd._drag["anchor"]
    lo, hi = sorted((200, rest[0]))
    assert lo < ax < hi
    assert abs(ax - 200) > 5
    t = 16
    for _ in range(30):
        t += 16
        bd.update_drag_physics(t)
    assert abs(bd._drag["anchor"][0] - 200) < 2 and abs(bd._drag["anchor"][1] - 200) < 2


def test_legal_drag_starts_settle_then_lands():
    bd, bk, landed = _make_board()
    e2, e4 = Square(6, 4), Square(4, 4)
    _grab(bd, e2, where="center")
    _cursor_to(bd, e4)
    bd.handle_click(e4)
    bd.end_press()
    assert bd._drag is not None and bd._drag["phase"] == "settle"
    assert bd._drag["settle_to_sq"] == e4
    assert bd.is_animating() is True
    _finish_settle(bd)
    assert bd._drag is None and bd.dragging_from is None
    assert bd.is_animating() is False
    assert len(landed) == 1
    assert bk.piece_at(e4) is not None and bk.piece_at(e2) is None


def test_illegal_drag_settles_back_to_origin():
    bd, bk, landed = _make_board()
    e2, e5 = Square(6, 4), Square(3, 4)
    _grab(bd, e2, where="center")
    _cursor_to(bd, e5)
    bd.handle_click(e5)
    bd.end_press()
    assert bd._drag is not None and bd._drag["phase"] == "settle"
    assert bd._drag["settle_to_sq"] == e2
    assert bd._drag["on_settled"] is None
    _finish_settle(bd)
    assert bd._drag is None and bd.dragging_from is None
    assert len(landed) == 0 and bk.piece_at(e2) is not None


def test_promotion_drag_defers_picker_until_landing():
    bd, bk, _ = _make_board()
    _seed_position(bk, {
        Square(1, 4): Piece(PieceType.PAWN, WHITE),
        Square(0, 0): Piece(PieceType.KING, BLACK),
        Square(7, 7): Piece(PieceType.KING, WHITE),
    }, turn=WHITE)
    e7, e8 = Square(1, 4), Square(0, 4)
    _grab(bd, e7, where="center")
    _cursor_to(bd, e8)
    bd.handle_click(e8)
    bd.end_press()
    assert bd._drag["phase"] == "settle" and bd._drag["settle_to_sq"] == e8
    assert bd.pending_promotion_square is None
    _finish_settle(bd)
    assert bd.pending_promotion_square == e8


def test_destination_is_hidden_during_settle():
    bd, _, _ = _make_board()
    e2, e4 = Square(6, 4), Square(4, 4)
    _grab(bd, e2, where="center")
    _cursor_to(bd, e4)
    bd.handle_click(e4)
    bd.end_press()
    visited = []
    original = bd._cell_rect
    bd._cell_rect = lambda r, c: visited.append((r, c)) or original(r, c)
    try:
        bd.draw_pieces()
    finally:
        bd._cell_rect = original
    assert (e4.row, e4.col) not in visited


def test_settle_completes_within_cap_even_with_large_spin():
    bd, _, _ = _make_board()
    e2, e4 = Square(6, 4), Square(4, 4)
    _grab(bd, e2, where="center")
    _cursor_to(bd, e4)
    bd.handle_click(e4)
    bd.end_press()
    bd._drag["omega"] = 40.0
    dur = bd._drag["settle_dur_ms"]
    start = bd._drag["settle_start_ms"]
    bd.update_drag_physics(start + int(dur * board_mod.DRAG_SETTLE_MAX_T) + 1)
    assert bd._drag is None


def test_cancel_drag_physics_fires_pending_landing():
    bd, bk, landed = _make_board()
    e2, e4 = Square(6, 4), Square(4, 4)
    _grab(bd, e2, where="center")
    _cursor_to(bd, e4)
    bd.handle_click(e4)
    bd.end_press()
    assert bd._drag["phase"] == "settle"
    bd.cancel_drag_physics()
    assert bd._drag is None and bd.dragging_from is None
    assert len(landed) == 1


def test_set_rect_cancels_active_drag():
    bd, _, _ = _make_board()
    _grab(bd, Square(6, 4), where="center")
    assert bd._drag is not None
    bd.set_rect(pg.Rect(0, 0, 500, 500))
    assert bd._drag is None and bd.dragging_from is None
