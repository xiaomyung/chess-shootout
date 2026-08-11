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
past the top of a flipped board, and the clamped coordinate still lands.

Manual flips are legal online again, so the controller now carries the server's
ASSUMED orientation (adjudicated_flipped = mover plays black) next to its live
affine. When the two disagree -- a mover who flipped their board -- _wire_target
shifts the outgoing row by twice the assumed lift into the server's frame and
re-clamps it, and the local prediction scores that SAME wired row in the same
assumed orientation the server will use: on an edge pit the shift collapses
under the clamp, so scoring the raw row through the live affine instead let the
server land a shot the client had rendered as a whiff (free progress plus a
desynced mirror). When the orientations agree, or offline where
adjudicated_flipped is None, the raw target and the live-affine orientation go
into the predicate bit-identically to the pre-fix path. The spectator mirror
likewise derives the MOVER's lift from the same field
instead of assuming the opposite of its own board, so it keeps painting relays
on the drawn body after either side flips."""

from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from tests.helpers import click_event as _click
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
_CELL_RECT = pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL)


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
    return MoleController(ch, _CELL_RECT, 0, ch.deadline_ms, geom=geom, **kw), ch


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


def _edge_challenge():
    return MoleChallenge(pops=(MolePop(0, 500.0, 700.0, 1500.0),),
                         hole_count=1, hits_required=1, deadline_ms=5000.0)


def _edge_mole(geom, hole, **kw):
    ch = _edge_challenge()
    kw.setdefault("audio", MagicMock())
    kw.setdefault("victim_surface", _victim())
    return MoleController(ch, _CELL_RECT, 0, ch.deadline_ms, geom=geom,
                          hole_squares=(hole,), **kw), ch


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
            geom, _BODY_LIFT_PX, adjudicated_flipped=color == "black",
            on_shot=lambda elapsed, target=None: sent.update(elapsed=elapsed, target=target))
        assert controller._progress == 1, color
        ch = controller.challenge
        assert online.shot_wins(
            SkillCheckKind.WHACK, ch, sent["elapsed"], 0, ch.deadline_ms,
            target=sent["target"], hole_squares=_holes(),
            flipped=color == "black") is True, \
            "the server scores the mover's own-color orientation: {}".format(color)


def test_a_manually_flipped_mover_wires_the_row_in_the_servers_assumed_orientation():
    """A black player who flipped to white-at-bottom aims at the body their OWN screen
    draws. _wire_target shifts the outgoing row by twice the assumed lift into the
    server's black-at-bottom frame (the column is orientation-free), so the server
    scores the shot the mover saw land -- while the raw affine row would lose by
    0.6 rows against the mirrored oval."""
    sent = {}
    controller = _fired(
        _unflipped_geom, _BODY_LIFT_PX, adjudicated_flipped=True,
        on_shot=lambda elapsed, target=None: sent.update(elapsed=elapsed, target=target))
    assert controller._progress == 1, \
        "local prediction scores the wired row: interior points keep the same verdict"
    ch = controller.challenge
    raw = _body_target(ch)
    assert abs(sent["target"][0] - (raw[0] + 2.0 * mole.hitbox_lift(True))) < 1e-9
    assert abs(sent["target"][1] - raw[1]) < 1e-9, "the column never moves"
    assert online.shot_wins(
        SkillCheckKind.WHACK, ch, sent["elapsed"], 0, ch.deadline_ms,
        target=sent["target"], hole_squares=_holes(), flipped=True) is True, \
        "the wired row wins on the server's engine path"
    assert online.shot_wins(
        SkillCheckKind.WHACK, ch, sent["elapsed"], 0, ch.deadline_ms,
        target=raw, hole_squares=_holes(), flipped=True) is False, \
        "the un-normalised row is what 096ec0e locked the board over"


def test_an_agreeing_orientation_wires_the_raw_target_untouched():
    for flipped, geom in ((False, _unflipped_geom), (True, _flipped_geom)):
        sent = {}
        controller = _fired(
            geom, _BODY_LIFT_PX, adjudicated_flipped=flipped,
            on_shot=lambda elapsed, target=None: sent.update(elapsed=elapsed, target=target))
        assert controller._progress == 1, flipped
        ch = controller.challenge
        px, py = _pop0_pit_px(ch, geom)
        raw = controller._clamp_target(controller._shot_target((px, py + _BODY_LIFT_PX)))
        assert sent["target"] == raw, \
            "own-color-at-bottom keeps the wire byte-identical to the pre-flip one"
        assert online.shot_wins(
            SkillCheckKind.WHACK, ch, sent["elapsed"], 0, ch.deadline_ms,
            target=sent["target"], hole_squares=_holes(), flipped=flipped) is True


def test_an_edge_clamped_shot_scores_locally_exactly_what_the_server_scores():
    """The free-progress desync: with a disagreeing orientation, an off-board click
    past an edge pit clamps to the board rim, and _wire_target's +/-0.6 row shift
    collapses under the second clamp -- the wired row equals the raw one, but the
    server scores it against the ASSUMED orientation's oval while the raw local
    prediction scored the live affine's. The client rendered a whiff, the server
    counted a hit, and the mirror showed one. The prediction therefore evaluates
    the WIRED row with adjudicated_flipped, so the two verdicts always agree; the
    raw live-affine verdict is pinned below as the whiff the pre-fix client
    showed. Both edge rows: a bottom pit under an unflipped live view wired
    flipped, and a top pit under a flipped live view wired unflipped."""
    off_board_y = BOARD_SIZE * _CELL + 30
    for geom, hole, adjudicated in ((_unflipped_geom, (7, 3), True),
                                    (_flipped_geom, (0, 3), False)):
        sent = {}
        controller, ch = _edge_mole(
            geom, hole, adjudicated_flipped=adjudicated,
            on_shot=lambda elapsed, target=None: sent.update(elapsed=elapsed, target=target))
        controller.update(1000.0)
        pos = (geom(Square(*hole))[0], off_board_y)
        assert controller.handle_event(_click(pos)) is True
        server_hit = online.shot_wins(
            SkillCheckKind.WHACK, ch, sent["elapsed"], 0, ch.deadline_ms,
            target=sent["target"], hole_squares=[hole], flipped=adjudicated)
        assert (controller._progress == 1) == server_hit, hole
        assert server_hit is True, "the clamped edge shot lands on the assumed-frame oval"
        raw = controller._clamp_target(controller._shot_target(pos))
        assert ch.hit_at(sent["elapsed"], raw[0], raw[1], [hole],
                         flipped=geom is _flipped_geom) is False, \
            "the raw live-affine verdict is the whiff the pre-fix client rendered"


def test_agreeing_and_offline_paths_keep_the_raw_target_and_live_orientation(monkeypatch):
    """The fix only reroutes the DISAGREEING online case: everywhere else the exact
    pre-fix predicate inputs must reach hit_at -- the raw clamped target (the same
    object _wire_target passes through untouched) with the live affine's
    orientation."""
    scored = []
    real = MoleChallenge.hit_at

    def spy(self, elapsed_ms, row_f, col_f, hole_squares, last_hit_pop=-1, *,
            flipped=False):
        scored.append((row_f, col_f, flipped))
        return real(self, elapsed_ms, row_f, col_f, hole_squares, last_hit_pop,
                    flipped=flipped)

    monkeypatch.setattr(MoleChallenge, "hit_at", spy)
    for adjudicated, geom in ((None, _flipped_geom), (None, _unflipped_geom),
                              (True, _flipped_geom), (False, _unflipped_geom)):
        scored.clear()
        kw = {} if adjudicated is None else {
            "adjudicated_flipped": adjudicated,
            "on_shot": lambda elapsed, target=None: None}
        controller, ch = _mole(geom, **kw)
        controller.update(_pop0_mid(ch))
        px, py = _pop0_pit_px(ch, geom)
        pos = (px, py + _BODY_LIFT_PX)
        assert controller.handle_event(_click(pos)) is True
        raw = controller._clamp_target(controller._shot_target(pos))
        assert scored == [(raw[0], raw[1], geom is _flipped_geom)], adjudicated
        assert controller._progress == 1, adjudicated


def test_the_normalised_row_stays_inside_the_field_bounds():
    """The +/-0.6 wire shift on an edge pit must re-clamp, or the shifted row would
    leave the protocol's [0, 8.0) Field bounds and the server would 422 the shot."""
    down, _ = _mole(_unflipped_geom, adjudicated_flipped=True)
    shifted = down._wire_target((MOLE_VIEW_TARGET_MAX, 3.5))
    assert shifted == (MOLE_VIEW_TARGET_MAX, 3.5), "the ceiling clamp holds after the shift"
    assert shifted[0] < SKILLCHECK_TARGET_MAX
    up, _ = _mole(_flipped_geom, adjudicated_flipped=False)
    assert up._wire_target((0.1, 3.5)) == (0.0, 3.5), "and the floor clamp on the way down"
    agreeing, _ = _mole(_flipped_geom, adjudicated_flipped=True)
    assert agreeing._wire_target((0.1, 3.5)) == (0.1, 3.5)
    offline, _ = _mole(_flipped_geom)
    assert offline._wire_target((0.1, 3.5)) == (0.1, 3.5), \
        "a local/bot controller carries None and passes every target through"


def test_client_clamp_stays_strictly_inside_the_server_validation_ceiling():
    assert MOLE_VIEW_TARGET_MAX < SKILLCHECK_TARGET_MAX, \
        "every clamped client shot passes the server's lt-8.0 field validation"
    controller, ch = _mole(_flipped_geom)
    assert controller._clamp_target((9.4, -2.0)) == (MOLE_VIEW_TARGET_MAX, 0.0)
    assert controller._clamp_target((-0.5, 11.0)) == (0.0, MOLE_VIEW_TARGET_MAX)


def _spectator(mirror_targets, **kw):
    return _mole(_flipped_geom, passive=True, mirror_targets=mirror_targets, **kw)


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
    lands 0.6 cells on the wrong side of the pit. The passive controller shifts every
    relayed y screen-up by the DOUBLED head lift (2 x CY_FRAC x cell, a fixed
    translation), putting rings/casings/puffs back on the body the spectator is
    actually drawing."""
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


def test_a_whiff_with_no_live_pop_keeps_its_true_spot_shifted_by_the_head_lift():
    """The old mirror reflected every relayed y about the ACTIVE pop's hole centre
    (else the capture square), so a whiff far from the anchor rendered at a
    geometrically unrelated point on the other side of it. The mirror is a fixed
    screen-up translation by the doubled head lift now, so a stray shot stays at
    its own true spot, merely lifted like every other relayed shot."""
    controller, ch = _spectator(True)
    assert ch.pop_up_at(0.0) is None, "elapsed 0 is inside the intro, before any pop"
    target = (2.0, 3.5)
    controller.spectate_shot(0.0, 1, False, target=target)
    raw_y = controller._board_to_px(*target)[1]
    _, _, iy = controller._impacts[-1]
    assert abs(iy - (raw_y + 2 * _BODY_LIFT_PX)) < 1e-6
    assert abs(controller._puffs[-1][2] - iy) < 1e-6, "the puff spawns on the same point"


def test_a_stray_miss_near_an_inactive_hole_renders_on_that_hole_not_reflected():
    """The bug the translation fixes: a miss aimed at a NON-active hole's body used to
    reflect about the active pop's anchor and paint rings/puffs at a different hole.
    It must land on the risen-body spot of the hole it was actually shot at."""
    controller, ch = _spectator(True)
    at = _pop0_mid(ch)
    controller.update(at)
    holes = _holes()
    active_hole = ch.pops[0].hole
    other = next(i for i in range(len(holes)) if i != active_hole)
    row, col = holes[other]
    controller.spectate_shot(at, 0, False,
                             target=(row + 0.5 + MOLE_HITBOX_CY_FRAC, col + 0.5))
    px, py = _flipped_geom(Square(row, col))
    _, ix, iy = controller._impacts[-1]
    assert abs(ix - px) <= 1
    assert abs(iy - (py + _BODY_LIFT_PX)) <= 1, \
        "the miss sits screen-up of ITS OWN hole, exactly like a shot on the live pop"


def test_the_mirror_lift_follows_the_mover_not_the_spectators_own_board():
    """After a manual flip both sides can render the SAME way up. The mirror shift is
    (own_lift - mover_lift) * dy: with mover and spectator both flipped it collapses
    to zero and the raw mapping already lands screen-up of the pit, where the
    spectator draws the risen body. The old spectator-derived doubled shift would
    paint the relay 0.6 rows past it. The default-orientation case (mover opposite,
    adjudicated_flipped unset) is the unchanged test above."""
    controller, ch = _spectator(True, adjudicated_flipped=True)
    at = _pop0_mid(ch)
    controller.update(at)
    row, col = _holes()[ch.pops[0].hole]
    controller.spectate_shot(at, 0, False, progress=1,
                             target=(row + 0.5 + mole.hitbox_lift(True), col + 0.5))
    px, py = _pop0_pit_px(ch, _flipped_geom)
    _, ix, iy = controller._impacts[-1]
    assert abs(ix - px) <= 1
    assert abs(iy - (py + _BODY_LIFT_PX)) <= 1, \
        "the relayed impact sits on the body the spectator draws, screen-up of the pit"
    assert abs(controller._last_hit_px[1] - iy) < 1e-6, \
        "the kill/gun anchor follows the same point"


def test_the_movers_kill_anchor_re_maps_when_geometry_changes_mid_check():
    """_last_hit_px is a cached window-space pixel: a mid-check flip (or resize)
    re-derives _affine and _hole_px but used to leave it at the mirrored-away
    point, so the win pop and the toss launched from the wrong side of the board.
    The board-space source IS retained -- the mover keeps the hit hole's index --
    so _apply_geometry re-maps the anchor through the fresh geometry instead of
    clearing it."""
    live = {"geom": _unflipped_geom}
    controller = _fired(lambda sq: live["geom"](sq), _BODY_LIFT_PX)
    row, col = _holes()[controller.challenge.pops[0].hole]
    assert controller._last_hit_px == _unflipped_geom(Square(row, col))
    live["geom"] = _flipped_geom
    controller.relayout(_CELL_RECT)
    assert controller._last_hit_px == _flipped_geom(Square(row, col)), \
        "the anchor re-maps to the hit hole's fresh pixel, not the stale mirror image"


def test_the_spectators_relayed_anchor_re_maps_when_geometry_changes_mid_check():
    """Same staleness on the passive mirror, whose anchor came from a relayed shot:
    the relayed board-space target is retained, so the anchor re-maps through the
    fresh affine AND the fresh mirror shift (which itself depends on the
    spectator's new orientation), landing back on the body being drawn."""
    live = {"geom": _flipped_geom}
    spec, ch = _mole(lambda sq: live["geom"](sq), passive=True, mirror_targets=True)
    at = _pop0_mid(ch)
    spec.update(at)
    spec.spectate_shot(at, 0, False, progress=1, target=_body_target(ch))
    stale = spec._last_hit_px
    live["geom"] = _unflipped_geom
    spec.relayout(_CELL_RECT)
    row, col = _holes()[ch.pops[0].hole]
    px, py = _unflipped_geom(Square(row, col))
    assert spec._last_hit_px != stale
    assert abs(spec._last_hit_px[0] - px) <= 1
    assert abs(spec._last_hit_px[1] - (py + _BODY_LIFT_PX)) <= 1, \
        "the relayed anchor sits on the risen body under the fresh orientation"


def test_edge_pit_ovals_stay_reachable_under_the_clamp_on_both_orientations():
    edge = _edge_challenge()
    assert edge.hit_at(1000.0, MOLE_VIEW_TARGET_MAX, 3.5, [(7, 3)], flipped=True) is True, \
        "a bottom-edge pit's mirrored oval reaches the clamp ceiling: clamped shots land"
    assert edge.hit_at(1000.0, MOLE_VIEW_TARGET_MAX, 3.5, [(7, 3)]) is False, \
        "the same clamped coordinate is 0.8 rows off the unflipped oval"
    assert edge.hit_at(1000.0, 0.0, 3.5, [(0, 3)]) is True, \
        "and symmetrically a top-edge pit's unflipped oval reaches the floor clamp"
    assert edge.hit_at(1000.0, 0.0, 3.5, [(0, 3)], flipped=True) is False
