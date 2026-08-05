"""The overlay -> board handover must not drop a frame.

Frontend.draw_frame runs screen.draw() BEFORE skillcheck_overlay.update(): the
board paints its pieces first, and only afterwards does the overlay notice its
controller is done, cancel itself and let _on_skillcheck_done clear
board.aim_suppressed_square. So on the handover frame the board had already
skipped the suppressed victim square and the overlay -- just cancelled -- drew
nothing either. One completely blank frame on the victim square.

Every other kind hides this: _on_skillcheck_done restores the piece with
restore_piece(drop=True), whose fade-in animation keeps the square hidden and
starts from alpha 0 anyway. A failed WHACK is the one restore that passes
drop=False, because its own choreography already walked the victim home and set
it down on the rest position the board draws at -- so there the missing frame is
naked, and it reads in play as the piece blinking once right after it lands.

The fix keeps the retiring controller for exactly one more draw (_farewell), so
the handover frame still shows the overlay's final standing frame. draw() always
follows update() inside draw_frame, so that farewell lands on the same frame the
board went blank and nowhere else.
"""

from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from tests.frontend.focus_helpers import FakeTicks, install_clock
from tests.helpers import BLACK, K, P, Q, WHITE, make_app, make_backend, piece, sq, \
    start_single_screen
from chessshootout.backend.pieces import PieceColor, PieceType
from chessshootout.frontend.skillcheck.mole_view import (
    MOLE_VIEW_FAIL_HOLD_MS, MOLE_VIEW_JUMP_HOP_MS, MOLE_VIEW_JUMP_RISE_MS,
    MOLE_VIEW_LAND_SQUASH_MS)
from chessshootout.frontend.skillcheck.overlay import SkillCheckOverlay
from chessshootout.skillcheck.coordinator import move_roll_key
from chessshootout.skillcheck.rng import ply_roll
from chessshootout.skillcheck.triggers import select_skillcheck
from chessshootout.skillcheck.types import SkillCheckKind


_pygame_init = pygame_display(1100, 800)

_FRAME_MS = 16
_SETTLED_MS = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS + MOLE_VIEW_LAND_SQUASH_MS


def _abs_diff(a, b):
    forward = a.copy()
    forward.blit(b, (0, 0), special_flags=pg.BLEND_RGB_SUB)
    back = b.copy()
    back.blit(a, (0, 0), special_flags=pg.BLEND_RGB_SUB)
    forward.blit(back, (0, 0), special_flags=pg.BLEND_RGB_ADD)
    return forward


def _changed_px(a, b, tol=24):
    """Pixels differing between two same-size surfaces, pygame-only (no numpy)."""
    diff = _abs_diff(a, b)
    width, height = diff.get_size()
    same = pg.mask.from_threshold(diff, (0, 0, 0), (tol, tol, tol, 255)).count()
    return width * height - same


def _silhouette(victim_img):
    """Black/white stencil of the victim's own opaque pixels.

    The board blits the piece image at the cell's topleft, and the overlay's
    standing frame lands on the identical rect, so this stencil addresses the
    same pixels in both. Masking to it keeps neighbouring choreography that
    legitimately overlaps the cell -- the held gun poking up from the capturer's
    square, the taunt tag -- out of the measurement.
    """
    return pg.mask.from_surface(victim_img).to_surface(
        setcolor=(255, 255, 255), unsetcolor=(0, 0, 0))


def _piece_only(crop, stencil):
    masked = crop.copy()
    masked.blit(stencil, (0, 0), special_flags=pg.BLEND_RGB_MULT)
    return masked


def _whack_seed(backend, frm, to):
    for i in range(8000):
        seed = "blink-{}".format(i)
        roll = ply_roll(seed, move_roll_key(0, frm, to))
        if select_skillcheck(backend, frm, to, roll) == SkillCheckKind.WHACK:
            return seed
    raise AssertionError("no WHACK seed found")


def _open_failing_whack(monkeypatch):
    """Real local whack check on d5, run out to its fail commit.

    Returns (app, clock, victim_cell_rect, settled_cell) where settled_cell is
    what the BOARD paints for the untouched victim -- the reference every later
    frame is measured against.
    """
    clock = FakeTicks()
    install_clock(monkeypatch, clock)
    app = make_app(1100, 800)
    start_single_screen(app)
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    }, turn=WHITE)
    frm, to = sq(4, 3), sq(3, 3)
    cell_rect = app.game.board.cell_rect(to)
    app.draw_frame()
    settled = app.window.subsurface(cell_rect).copy()

    app.game.skillcheck.reset(enabled=True, seed=_whack_seed(app.game.match.backend, frm, to))
    assert app.game.skillcheck_session.skillcheck_gate(frm, to) is True
    controller = app.game.skillcheck_overlay._controller
    assert app.game.board.aim_suppressed_square == to

    for _ in range(200):
        if controller._committed_at is not None:
            break
        clock.advance(200)
        app.draw_frame()
    assert controller._committed_at is not None, "the check must reach its own fail commit"
    assert controller.landed is False
    return app, clock, cell_rect, settled


def _run_to_handover(app, clock, cell_rect, stencil):
    """Frames from the fail commit up to and including the handover frame.

    Stops there on purpose: the handover frame is the one that used to be blank,
    and _on_skillcheck_done -- which fires on it, after the board has drawn --
    is what arms the taunt tag, so every later frame has unrelated art moving
    over the square.
    """
    commit_ms = clock.t
    frames = []
    for _ in range(int(MOLE_VIEW_FAIL_HOLD_MS // _FRAME_MS) + 8):
        clock.advance(_FRAME_MS)
        app.draw_frame()
        active = app.game.skillcheck_overlay.is_active()
        frames.append((clock.t - commit_ms, active,
                       _piece_only(app.window.subsurface(cell_rect), stencil)))
        if not active:
            return frames
    raise AssertionError("the fail hold never expired")


def test_failed_whack_never_blanks_the_victim_square_at_the_overlay_handover(monkeypatch):
    app, clock, cell_rect, settled = _open_failing_whack(monkeypatch)
    victim_img = app.game.board.piece_images_scaled[(PieceType.PAWN, PieceColor.BLACK)]
    stencil = _silhouette(victim_img)
    piece_px = pg.mask.from_surface(victim_img).count()
    assert piece_px > 0
    settled = _piece_only(settled, stencil)

    frames = _run_to_handover(app, clock, cell_rect, stencil)
    blanks = [(rel, _changed_px(crop, settled)) for rel, _, crop in frames
              if rel >= _SETTLED_MS and _changed_px(crop, settled) > piece_px // 3]

    assert frames[-1][1] is False, "the fail hold must expire inside the window"
    assert not blanks, (
        "victim square lost its piece on frame(s) {} (rel-ms, differing px vs the settled "
        "render; piece is {} px) -- the overlay handed back to the board without painting "
        "its own last frame".format(blanks, piece_px))


def test_the_piece_is_pixel_stable_across_the_frame_the_overlay_retires(monkeypatch):
    # Tighter than the blank check: the standing frame the overlay draws sits on
    # exactly the rest position the board blits at, so the handover must not move
    # or redraw a single piece pixel either.
    app, clock, cell_rect, _ = _open_failing_whack(monkeypatch)
    stencil = _silhouette(app.game.board.piece_images_scaled[(PieceType.PAWN, PieceColor.BLACK)])
    frames = _run_to_handover(app, clock, cell_rect, stencil)

    assert len(frames) > 1, "the overlay must still be live before the hold expires"
    before, after = frames[-2], frames[-1]
    assert before[1] is True and after[1] is False
    assert _changed_px(before[2], after[2]) == 0, (
        "victim square changed between the overlay's last frame (rel {}) and the "
        "handover frame (rel {})".format(before[0], after[0]))


def test_overlay_gives_the_retiring_controller_one_last_draw_then_drops_it():
    window = pg.Surface((10, 10))
    controller = MagicMock(done=False, landed=False)
    done = MagicMock()
    overlay = SkillCheckOverlay()
    overlay.start(controller, ("ctx",), done)

    overlay.update(10)
    overlay.draw(window)
    assert controller.draw.call_count == 1

    controller.done = True
    overlay.update(20)
    assert overlay.is_active() is False, "update still retires the controller on the spot"
    done.assert_called_once_with(("ctx",), False)

    overlay.draw(window)
    assert controller.draw.call_count == 2, \
        "the frame the board was still suppressing must show the overlay's final frame"
    overlay.draw(window)
    assert controller.draw.call_count == 2, "and exactly one farewell frame, never two"


def test_cancel_drops_the_farewell_frame_so_teardown_paints_nothing():
    window = pg.Surface((10, 10))
    controller = MagicMock(done=True, landed=False)
    overlay = SkillCheckOverlay()
    overlay.start(controller, ("ctx",), MagicMock())
    overlay.update(10)
    overlay.cancel()
    overlay.draw(window)
    assert controller.draw.call_count == 0, \
        "an explicit teardown must not leak one more frame of a dead check"
