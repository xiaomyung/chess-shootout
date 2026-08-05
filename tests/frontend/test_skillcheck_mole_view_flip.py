"""Whack orientation: the popped piece rises UP THE SCREEN out of its pit, so the
engine hitbox must follow the drawn body on BOTH board orientations. The
controller derives its orientation from the sign of its affine's row step
(negative row step = flipped view, black at the bottom) and passes it to
hit_at, whose CY lift mirrors below the pit row in board space; the server
derives the same flag from the mover's color (an online client defaults to own
color at the bottom). These tests pin the whole chain: a click on the visual
body center adjudicates as a hit through a flipped affine, the debug overlay
draws its ellipses exactly where clicks count (screen-up of the pit in both
orientations), and a body-center shot wins on the controller path AND the
server's engine path with the same seed for both colors. The clamp pins keep
the client's board-edge clamp (BOARD_SIZE - 0.001) strictly inside the server's
validation ceiling (lt 8.0) so every clamped shot stays wire-valid, and show a
bottom-edge pit's mirrored oval reaching the clamp ceiling -- the piece spills
past the top of a flipped board, and the clamped coordinate still lands."""

from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.utils import BOARD_SIZE, Square
from chessshootout.frontend.skillcheck.mole_view import (
    MoleController, MOLE_VIEW_TARGET_MAX)
from chessshootout.server.protocol import SKILLCHECK_TARGET_MAX
from chessshootout.skillcheck import mole, online
from chessshootout.skillcheck.mole import (
    MoleChallenge, MolePop, MOLE_HITBOX_CY_FRAC)
from chessshootout.skillcheck.types import SkillCheckKind

_pygame_init = pygame_display(640, 640)

_CELL = 80
_SEED = "flip-agreement"
_CAPTURED_VALUE = 5
_CAPTURE_SQ = (3, 3)
_OCCUPIED = {(3, 3), (4, 4)}
_BODY_LIFT_PX = int(MOLE_HITBOX_CY_FRAC * _CELL)


def _unflipped_geom(sq):
    return (sq.col * _CELL + _CELL // 2, sq.row * _CELL + _CELL // 2)


def _flipped_geom(sq):
    return ((BOARD_SIZE - 1 - sq.col) * _CELL + _CELL // 2,
            (BOARD_SIZE - 1 - sq.row) * _CELL + _CELL // 2)


def _victim():
    surf = pg.Surface((_CELL, _CELL), pg.SRCALPHA)
    surf.fill((120, 160, 210, 255))
    return surf


def _holes():
    return mole.hole_squares(_SEED, _CAPTURED_VALUE, _CAPTURE_SQ, _OCCUPIED)


def _mole(geom, **kw):
    ch = MoleChallenge.from_seed(_SEED, captured_value=_CAPTURED_VALUE)
    kw.setdefault("hole_squares", _holes())
    kw.setdefault("audio", MagicMock())
    kw.setdefault("victim_surface", _victim())
    return MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), 0,
                          ch.deadline_ms, geom=geom, **kw), ch


def _click(pos):
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": pos})


def _pop0_mid(ch):
    pop = ch.pops[0]
    return (pop.t_up_ms + pop.t_down_ms) / 2.0


def _pop0_pit_px(ch, geom):
    row, col = _holes()[ch.pops[0].hole]
    return geom(Square(row, col))


def _fired(geom, dy_px, **kw):
    controller, ch = _mole(geom, **kw)
    controller.update(_pop0_mid(ch))
    px, py = _pop0_pit_px(ch, geom)
    assert controller.handle_event(_click((px, py + dy_px))) is True
    return controller


def test_flipped_view_scores_the_click_on_the_risen_body_screen_up():
    controller = _fired(_flipped_geom, _BODY_LIFT_PX)
    assert controller._progress == 1, \
        "the body center is 0.30 cells ABOVE the pit on screen, flipped board included"
    below = _fired(_flipped_geom, -_BODY_LIFT_PX)
    assert below._progress == 0, \
        "screen-below the pit is 0.6 cells off the body: the pre-fix hitbox position"


def test_unflipped_view_keeps_the_shipped_screen_up_hitbox():
    controller = _fired(_unflipped_geom, _BODY_LIFT_PX)
    assert controller._progress == 1
    below = _fired(_unflipped_geom, -_BODY_LIFT_PX)
    assert below._progress == 0


def test_debug_hitbox_ellipses_hug_the_risen_body_in_both_orientations(monkeypatch):
    for geom in (_unflipped_geom, _flipped_geom):
        controller, ch = _mole(geom)
        rects = []
        monkeypatch.setattr(pg.draw, "ellipse",
                            lambda surf, color, rect, width=0: rects.append(pg.Rect(rect)))
        controller._draw_hitboxes(pg.display.get_surface(), _pop0_mid(ch))
        monkeypatch.undo()
        holes = _holes()
        assert len(rects) == len(holes)
        for rect, (row, col) in zip(rects, holes):
            px, py = geom(Square(row, col))
            assert abs(rect.centerx - px) <= 2
            assert abs(rect.centery - (py + _BODY_LIFT_PX)) <= 2, \
                "the overlay ellipse sits exactly where clicks count: screen-up of the pit"


def test_body_center_shots_agree_between_controller_and_server_for_both_colors():
    for color, geom in (("white", _unflipped_geom), ("black", _flipped_geom)):
        sent = {}
        controller = _fired(
            geom, _BODY_LIFT_PX,
            on_shot=lambda elapsed, target=None: sent.update(elapsed=elapsed, target=target))
        assert controller._progress == 1, color
        ch = controller.challenge
        assert online.shot_wins(
            SkillCheckKind.WHACK, ch, sent["elapsed"], 0, ch.deadline_ms,
            target=sent["target"], hole_squares=_holes(),
            flipped=color == "black") is True, \
            "the server scores the mover's own-color orientation: {}".format(color)


def test_client_clamp_stays_strictly_inside_the_server_validation_ceiling():
    assert MOLE_VIEW_TARGET_MAX < SKILLCHECK_TARGET_MAX, \
        "every clamped client shot passes the server's lt-8.0 field validation"
    controller, ch = _mole(_flipped_geom)
    assert controller._clamp_target((9.4, -2.0)) == (MOLE_VIEW_TARGET_MAX, 0.0)
    assert controller._clamp_target((-0.5, 11.0)) == (0.0, MOLE_VIEW_TARGET_MAX)


def _spectator(mirror_targets):
    return _mole(_flipped_geom, passive=True, mirror_targets=mirror_targets)


def _body_target(ch):
    row, col = _holes()[ch.pops[0].hole]
    return (row + 0.5 + MOLE_HITBOX_CY_FRAC, col + 0.5)


def _relayed(mirror_targets, elapsed=None, target=None, progress=1, won=False):
    controller, ch = _spectator(mirror_targets)
    at = _pop0_mid(ch) if elapsed is None else elapsed
    controller.update(at)
    controller.spectate_shot(at, 0, won, progress=progress,
                             target=_body_target(ch) if target is None else target)
    return controller, ch


def test_spectator_mirror_puts_the_relayed_impact_screen_up_of_the_pit():
    """Online the two clients render opposite orientations, but the popped piece rises
    SCREEN-up on both. The mover aims at their own screen-up body (rows around
    hole_row + 0.5 - 0.30), so the raw row read through the spectator's opposite affine
    lands 0.6 cells on the wrong side of the pit. The passive controller mirrors the
    display row about the live pit's row centre, putting rings/casings/puffs back on
    the body the spectator is actually drawing."""
    controller, ch = _relayed(True)
    px, py = _pop0_pit_px(ch, _flipped_geom)
    _, ix, iy = controller._impacts[-1]
    assert abs(ix - px) <= 1, "only the row mirrors: the column is orientation-agnostic"
    assert abs(iy - (py + _BODY_LIFT_PX)) <= 1, \
        "the ring sits on the risen body, screen-up of the pit, like the mover's did"
    assert abs(controller._last_hit_px[1] - iy) < 1e-6, \
        "the kill/gun anchor follows the same mirrored point"
    assert abs(controller._casings[-1].y0 - iy) < 1e-6


def test_the_unmirrored_default_maps_the_relayed_row_straight_through():
    controller, ch = _relayed(False)
    px, py = _pop0_pit_px(ch, _flipped_geom)
    _, ix, iy = controller._impacts[-1]
    assert abs(ix - px) <= 1
    assert abs(iy - (py - _BODY_LIFT_PX)) <= 1, \
        "mirror_targets defaults off: same-orientation surfaces keep the raw mapping"


def test_the_mirror_moves_pixels_only_and_never_the_relayed_progress():
    mirrored, _ = _relayed(True)
    raw, _ = _relayed(False)
    assert mirrored._progress == raw._progress == 1, \
        "the spectator never adjudicates: progress is whatever the server relayed"
    assert mirrored._last_hit_pop == raw._last_hit_pop


def test_a_whiff_with_no_live_pop_mirrors_about_the_victim_square_centre():
    """Between pops there is no pit to anchor on and the puff is pure cosmetics, so the
    rule is: fall back to the check's own cell centre (the victim square the overlay is
    built on). Pinned so the fallback can't silently drift into a no-op."""
    controller, ch = _spectator(True)
    assert ch.pop_up_at(0.0) is None, "elapsed 0 is inside the intro, before any pop"
    target = (2.0, 3.5)
    controller.spectate_shot(0.0, 1, False, target=target)
    raw_y = controller._board_to_px(*target)[1]
    _, _, iy = controller._impacts[-1]
    assert abs(iy - (2.0 * controller.center[1] - raw_y)) < 1e-6
    assert abs(controller._puffs[-1][2] - iy) < 1e-6, "the puff spawns on the same point"


def test_edge_pit_ovals_stay_reachable_under_the_clamp_on_both_orientations():
    edge = MoleChallenge(pops=(MolePop(0, 500.0, 700.0, 1500.0),),
                         hole_count=1, hits_required=1, deadline_ms=5000.0)
    assert edge.hit_at(1000.0, MOLE_VIEW_TARGET_MAX, 3.5, [(7, 3)], flipped=True) is True, \
        "a bottom-edge pit's mirrored oval reaches the clamp ceiling: clamped shots land"
    assert edge.hit_at(1000.0, MOLE_VIEW_TARGET_MAX, 3.5, [(7, 3)]) is False, \
        "the same clamped coordinate is 0.8 rows off the unflipped oval"
    assert edge.hit_at(1000.0, 0.0, 3.5, [(0, 3)]) is True, \
        "and symmetrically a top-edge pit's unflipped oval reaches the floor clamp"
    assert edge.hit_at(1000.0, 0.0, 3.5, [(0, 3)], flipped=True) is False
