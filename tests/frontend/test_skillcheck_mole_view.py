"""Whack-a-mole skill-check view controller: click/Space shots share one recoil
lockout — a locked shot gets NO muzzle/kick/casing, only a dry-click cue, so the
fire rate is felt — hits adjudicate through the engine's hit_at (grace window
included), the third hit commits a local win that plays a climb-out from the home
pit (hitstop freeze -> ease_out_back rise -> deadpan -> fry flash) through
MOLE_VIEW_WIN_HOLD_MS, while deadline/quota exhaustion commits a fast fail: the
pits fade, the victim draws nothing (the board-level restore drop takes over),
and the overlay ends after MOLE_VIEW_FAIL_HOLD_MS. The taunt moved out of the
controller entirely — module-level pick_taunt(seed) is deterministic per check
seed so mover and spectator show the same line on the board layer. A telegraphing
pop that pop_mandatory marks as must-hit pulses a danger rim (Colors.loss lerp)
instead of the plain white one. Online every registered shot relays exactly once
with a keyword (row_f, col_f) target and the client never self-commits —
resolve() carries the server verdict; a win holds the climb (WIN_HOLD) online and
on the passive mirror, a fail holds the shared RESULT_HOLD. Passive mirrors
swallow no input, never touch the OS cursor, stay muted, and replay the mover's
shots via spectate_shot. The OS cursor hides on active construction and is
restored on every terminal path.
"""

import gc
import logging
from unittest.mock import MagicMock, call

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.skillcheck.controller import SKILLCHECK_RESULT_HOLD_MS
from chessshootout.frontend.skillcheck.mole_view import (
    MoleController, pick_taunt, MOLE_VIEW_FAIL_FADE_MS, MOLE_VIEW_FAIL_HOLD_MS,
    MOLE_VIEW_WIN_HOLD_MS, MOLE_VIEW_HITSTOP_KILL_MS, MOLE_VIEW_WIN_CLIMB_MS,
    MOLE_VIEW_WIN_DEADPAN_MS, MOLE_VIEW_TAUNTS, MOLE_VIEW_PIP_OFFSET_FRAC)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.skillcheck.mole import MoleChallenge, MolePop

_pygame_init = pygame_display(640, 640)

_CELL = 80
_HOLES = ((2, 2), (2, 4), (5, 5))
_POPS = (MolePop(0, 500.0, 700.0, 1500.0),
         MolePop(1, 1700.0, 1900.0, 2700.0),
         MolePop(2, 2900.0, 3100.0, 3900.0),
         MolePop(0, 4100.0, 4300.0, 5100.0),
         MolePop(1, 5300.0, 5500.0, 6300.0))


def _geom_for(cell):
    return lambda sq: (sq.col * cell + cell // 2, sq.row * cell + cell // 2)


def _victim(cell):
    surf = pg.Surface((cell, cell), pg.SRCALPHA)
    pg.draw.circle(surf, (120, 160, 210, 255), (cell // 2, cell // 2), cell // 3)
    return surf


def _challenge(pops=_POPS, hole_count=3, hits_required=3, deadline_ms=7000.0):
    return MoleChallenge(pops=pops, hole_count=hole_count, hits_required=hits_required,
                         deadline_ms=deadline_ms)


def _mole(cell=_CELL, challenge=None, **kw):
    challenge = challenge or _challenge()
    kw.setdefault("hole_squares", _HOLES)
    kw.setdefault("geom", _geom_for(cell))
    kw.setdefault("audio", MagicMock())
    kw.setdefault("victim_surface", _victim(cell))
    return MoleController(challenge, pg.Rect(3 * cell, 4 * cell, cell, cell), 0,
                          challenge.deadline_ms, **kw)


def _click(pos):
    return pg.event.Event(pg.MOUSEBUTTONDOWN, {"button": 1, "pos": pos})


def _space():
    return pg.event.Event(pg.KEYDOWN, {"key": pg.K_SPACE, "unicode": " ", "mod": 0})


def _hole_px(index, cell=_CELL):
    row, col = _HOLES[index]
    return (col * cell + cell // 2, row * cell + cell // 2)


def test_click_at_hole_center_registers_a_hit():
    ctrl = _mole()
    ctrl.update(800)
    assert ctrl.handle_event(_click(_hole_px(0))) is True
    assert ctrl._progress == 1
    ctrl._audio.play_whack_hit.assert_called_once()
    assert ctrl.landed is None, "one hit is not the quota — nothing commits yet"


def test_second_click_inside_the_lockout_does_not_register():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(900)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "a shot inside the recoil lockout never registers"
    assert ctrl._audio.play_whack_hit.call_count == 1
    ctrl._audio.play_whiff_ricochet.assert_not_called()


def test_lockout_shot_gets_a_dry_click_and_none_of_the_shot_feedback():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl._audio.play_whack_dry.assert_not_called()
    assert len(ctrl._casings) == 1
    flash_ms = ctrl._flash_ms
    flash_px = ctrl._flash_px
    ctrl.update(900)
    ctrl.handle_event(_click((600, 600)))
    assert len(ctrl._casings) == 1, "a locked shot ejects no casing"
    assert ctrl._flash_ms == flash_ms, "a locked shot fires no muzzle flash"
    assert ctrl._flash_px == flash_px, "and never moves the flash anchor"
    ctrl._audio.play_whack_dry.assert_called_once()


def test_empty_spot_click_is_a_whiff():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((600, 600)))
    assert ctrl._progress == 0
    ctrl._audio.play_whiff_ricochet.assert_called_once()
    ctrl._audio.play_whack_hit.assert_not_called()


def test_space_fires_at_the_mouse_and_shares_the_click_lockout(monkeypatch):
    monkeypatch.setattr(pg.mouse, "get_pos", lambda: _hole_px(0))
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((40, 40)))
    assert ctrl._progress == 0, "the opener is a registered whiff"
    ctrl.update(880)
    ctrl.handle_event(_space())
    assert ctrl._progress == 0, "Space inside the click's lockout does not register"
    ctrl.update(1000)
    ctrl.handle_event(_space())
    assert ctrl._progress == 1, "Space after the lockout fires at the mouse position"


def test_third_hit_commits_the_win_after_the_climb_hold():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    ctrl.update(3200)
    ctrl.handle_event(_click(_hole_px(2)))
    assert ctrl.landed is True
    ctrl._audio.play_whack_kill.assert_called_once()
    assert ctrl.done is False
    ctrl.update(3200 + MOLE_VIEW_WIN_HOLD_MS - 50)
    assert ctrl.done is False, "the climb-out choreography still owns the overlay at 700ms"
    ctrl.update(3200 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_grace_window_click_still_hits():
    ctrl = _mole()
    ctrl.update(1600)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "t_down + 100ms sits inside MOLE_GRACE_MS and still lands"


def _one_pop_challenge():
    return _challenge(pops=(MolePop(0, 500.0, 700.0, 1990.0),), hits_required=1,
                      deadline_ms=2000.0)


def test_deadline_commits_a_fast_fail_with_no_controller_taunt():
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(1999)
    assert ctrl.landed is None
    ctrl.update(2000)
    assert ctrl.landed is False
    ctrl.update(2000 + MOLE_VIEW_FAIL_HOLD_MS - 1)
    assert ctrl.done is False
    ctrl.update(2000 + MOLE_VIEW_FAIL_HOLD_MS)
    assert ctrl.done is True, "the fail hold is a fast 450ms — no deadpan pause"
    ctrl._audio.play_mole_taunt.assert_not_called()
    for attr in ("_taunt", "_taunt_shown", "_taunt_text"):
        assert not hasattr(ctrl, attr), \
            "the taunt moved to the board layer — the controller keeps no taunt state"


def test_quota_exhaustion_commits_fail_before_the_deadline():
    ctrl = _mole()
    ctrl.update(4019)
    assert ctrl.landed is None, "the third pop is still hittable inside its grace window"
    ctrl.update(4020)
    assert ctrl.landed is False, \
        "three expired pops with two left cannot reach the 3-hit quota — fail early"


def test_online_registered_shot_relays_once_with_a_keyword_target():
    on_shot = MagicMock()
    ctrl = _mole(on_shot=on_shot)
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    on_shot.assert_called_once()
    args, kwargs = on_shot.call_args
    assert args == (800,)
    assert kwargs == {"target": (2.5, 2.5)}
    assert isinstance(kwargs["target"][0], float) and isinstance(kwargs["target"][1], float)
    ctrl.update(900)
    ctrl.handle_event(_click(_hole_px(0)))
    assert on_shot.call_count == 1, "a lockout shot never reaches the wire"
    ctrl.update(1100)
    ctrl.handle_event(_click((600, 600)))
    assert on_shot.call_count == 2, "a registered whiff still relays"


def test_online_never_self_commits_a_terminal():
    ctrl = _mole(on_shot=MagicMock())
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    assert ctrl._progress == 3, "optimistic local hits still fill the displayed progress"
    assert ctrl.landed is None, "the quota online is only the server's to confirm"
    ctrl.update(9000)
    assert ctrl.landed is None and ctrl.done is False, "no self-fail at the deadline online"


def test_online_resolve_fail_holds_the_shared_result_hold():
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(900)
    ctrl.resolve(False)
    assert ctrl.landed is False
    assert ctrl.done is False
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is True


def test_online_resolve_win_holds_through_the_climb():
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(900)
    ctrl.resolve(True)
    assert ctrl.landed is True
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the shredded climb-out plays online too"
    ctrl.update(900 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_spectator_resolve_win_holds_through_the_climb_too():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.resolve(True)
    ctrl.update(900 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is False, "the mirror shows the same climb-out as the mover"
    ctrl.update(900 + MOLE_VIEW_WIN_HOLD_MS)
    assert ctrl.done is True


def test_passive_ignores_input_and_mutes_every_cue():
    audio = MagicMock()
    ctrl = _mole(passive=True, audio=audio)
    assert ctrl.handle_event(_click(_hole_px(0))) is False
    ctrl.update(800)
    ctrl.update(9000)
    assert ctrl.landed is None and ctrl.done is False
    assert audio.method_calls == [], "the passive guard silences the mount and schedule cues"


def test_passive_never_touches_the_cursor(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole(passive=True)
    ctrl.update(500)
    visible.assert_not_called()
    assert ctrl._cursor_hidden is False


def test_spectate_shot_adopts_progress_and_fires_the_hit_juice():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    assert ctrl._progress == 1
    assert ctrl._trauma.value > 0.0, "a relayed hit shakes the minigame layer"
    assert len(ctrl._impacts) == 1, "the impact marker lands at the mover's target"
    assert len(ctrl._casings) == 1
    ctrl.spectate_shot(820.0, 0, True, progress=1, target=(2.5, 2.5))
    assert ctrl._progress == 1, "a replay without a progress increase adopts nothing"


def test_spectate_miss_spawns_dust_without_progress():
    ctrl = _mole(passive=True)
    ctrl.update(700)
    ctrl.spectate_shot(600.0, 0, False, progress=0, target=(7.5, 7.5))
    assert ctrl._progress == 0
    assert len(ctrl._puffs) == 1, "the mover's whiff replays as a dust puff on the mirror"


def test_cursor_hidden_on_construction_and_restored_on_win(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole()
    assert visible.call_args_list[0] == call(False)
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.handle_event(_click(_hole_px(hole)))
    assert visible.call_args_list[-1] == call(True)


def test_cursor_restored_on_fail(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole(challenge=_one_pop_challenge())
    ctrl.update(2000)
    assert ctrl.landed is False
    assert visible.call_args_list[-1] == call(True)


def test_cursor_restored_once_on_resolve_and_survives_the_drop(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole(on_shot=MagicMock())
    ctrl.update(600)
    ctrl.resolve(False)
    ctrl.update(600 + SKILLCHECK_RESULT_HOLD_MS)
    assert ctrl.done is True
    del ctrl
    gc.collect()
    assert visible.call_args_list.count(call(True)) == 1, \
        "the terminal path restores exactly once — dropping the object never double-restores"


def test_close_restores_the_cursor_without_committing(monkeypatch):
    visible = MagicMock()
    monkeypatch.setattr(pg.mouse, "set_visible", visible)
    ctrl = _mole()
    ctrl.update(300)
    ctrl.close()
    assert visible.call_args_list[-1] == call(True)
    assert ctrl.landed is None and ctrl.done is False


@pytest.mark.parametrize("cell", [60, 99, 160])
def test_draw_smoke_across_states_and_sizes(cell):
    surf = pg.Surface((8 * cell, 8 * cell))
    surf.fill((200, 200, 200))
    ctrl = _mole(cell=cell)
    for now in (0, 200, 600):
        ctrl.update(now)
        ctrl.draw(surf)
    row, col = _HOLES[1]
    px = surf.get_at((col * cell + cell // 2, row * cell + cell // 2))
    assert px.r + px.g + px.b < 300, "an open pit paints darker than the light backdrop"
    for now, hole in ((800, 0), (2000, 1), (3200, 2)):
        ctrl.update(now)
        ctrl.draw(surf)
        ctrl.handle_event(_click(_hole_px(hole, cell)))
        ctrl.draw(surf)
    assert ctrl.landed is True
    for dt in (100, MOLE_VIEW_HITSTOP_KILL_MS + 120,
               MOLE_VIEW_HITSTOP_KILL_MS + MOLE_VIEW_WIN_CLIMB_MS
               + MOLE_VIEW_WIN_DEADPAN_MS + 10):
        ctrl.update(3200 + int(dt))
        ctrl.draw(surf)
    failed = _mole(cell=cell, challenge=_one_pop_challenge())
    failed.update(2000)
    failed.draw(surf)
    failed.update(2000 + MOLE_VIEW_FAIL_FADE_MS + 50)
    failed.draw(surf)
    failed.update(2000 + MOLE_VIEW_FAIL_HOLD_MS - 1)
    failed.draw(surf)
    assert failed.landed is False


def _accent_in_band(surf, ctrl):
    accent = pg.Color(Colors.accent)
    n = ctrl.challenge.hits_required
    total = n * ctrl._pip_w + (n - 1) * ctrl._pip_gap
    y0 = ctrl.center[1] + int(ctrl.cell_size * MOLE_VIEW_PIP_OFFSET_FRAC) - 10
    x0 = ctrl.center[0] - total // 2 - 12
    for y in range(max(y0, 0), min(y0 + ctrl._pip_h + 20, surf.get_height())):
        for x in range(max(x0, 0), min(x0 + total + 24, surf.get_width())):
            if surf.get_at((x, y)) == accent:
                return True
    return False


def test_pip_fill_changes_pixels_on_a_hit():
    before = pg.Surface((640, 640))
    before.fill((30, 30, 30))
    after = pg.Surface((640, 640))
    after.fill((30, 30, 30))
    ctrl = _mole()
    ctrl.update(800)
    ctrl.draw(before)
    assert _accent_in_band(before, ctrl) is False, "no pip is filled before the first hit"
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.draw(after)
    assert _accent_in_band(after, ctrl) is True, "the first hit fills a pip with the accent hue"


def test_same_challenge_and_script_reach_the_same_state():
    a, b = _mole(), _mole()
    for ctrl in (a, b):
        ctrl.update(800)
        ctrl.handle_event(_click(_hole_px(0)))
        ctrl.update(2000)
        ctrl.handle_event(_click(_hole_px(1)))
    assert (a._progress, a._last_hit_pop, a.landed) == (b._progress, b._last_hit_pop, b.landed)


def test_pick_taunt_is_deterministic_per_seed_and_varied_across_seeds():
    assert pick_taunt("seed-x") == pick_taunt("seed-x"), \
        "mover and spectator derive the same line from the same check seed"
    texts = {pick_taunt("seed-{}".format(i)) for i in range(30)}
    assert texts <= set(MOLE_VIEW_TAUNTS)
    assert len(texts) >= 3, "fresh per-check seeds actually rotate the taunt pool"


def _telegraph_surface_for(captured_value, pop_index):
    challenge = MoleChallenge.from_seed("danger-seed", captured_value=captured_value)
    holes = tuple((7, col) for col in range(challenge.hole_count))
    ctrl = _mole(challenge=challenge, hole_squares=holes)
    tele = ctrl._telegraph_hole(challenge.pops[pop_index].t_telegraph_ms + 1.0)
    assert tele is not None and tele == (pop_index, challenge.pops[pop_index].hole)
    return ctrl._telegraph_surface(tele[0])


def test_queen_capture_telegraphs_the_danger_rim_where_the_pop_is_mandatory():
    queen = MoleChallenge.from_seed("danger-seed", captured_value=9)
    pawn = MoleChallenge.from_seed("danger-seed", captured_value=1)
    assert queen.hits_required == 5, \
        "the exact-fit budget solve keeps the queen's 5-of-5 quota at the 5s cap"
    assert queen.pop_mandatory(0, 0) is True, \
        "a perfect-run quota makes every pop mandatory from the first telegraph"
    assert pawn.pop_mandatory(0, 0) is False
    assert pawn.pop_mandatory(2, 0) is True
    danger = _telegraph_surface_for(9, 0)
    plain = _telegraph_surface_for(1, 0)
    assert danger is not plain, "a mandatory pop picks the danger-keyed telegraph surface"
    assert pg.image.tostring(danger, "RGBA") != pg.image.tostring(plain, "RGBA"), \
        "the danger rim lerps toward Colors.loss, visibly different from the white pulse"


def test_mount_and_schedule_cues_fire_on_their_edges():
    ctrl = _mole()
    ctrl._audio.play_mole_fall.assert_called_once()
    ctrl.update(600)
    ctrl._audio.play_mole_telegraph.assert_called_once()
    ctrl._audio.play_mole_pop.assert_not_called()
    ctrl.update(750)
    ctrl._audio.play_mole_pop.assert_called_once()
    ctrl.update(1800)
    assert ctrl._audio.play_mole_telegraph.call_count == 2


def test_relayout_reanchors_geometry():
    ctrl = _mole()
    old_rx = ctrl._pit_rx
    ctrl.relayout(pg.Rect(480, 640, 160, 160))
    assert ctrl.center == (560, 720)
    assert ctrl.cell_size == 160
    assert ctrl._pit_rx > old_rx, "pit geometry rescales off the new cell"


def test_out_of_board_shot_clamps_target_within_wire_bounds():
    on_shot = MagicMock()
    ctrl = _mole(on_shot=on_shot)
    ctrl.update(800)
    ctrl.handle_event(_click((752, 200)))
    _, kwargs = on_shot.call_args
    r, c = kwargs["target"]
    assert 0.0 <= r < 8.0 and 0.0 <= c < 8.0, "an off-board shot never exceeds the wire bound"


def test_sentinel_target_clamps_into_wire_bounds():
    on_shot = MagicMock()
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), 0,
                          ch.deadline_ms, hole_squares=_HOLES, audio=MagicMock(),
                          victim_surface=_victim(_CELL), on_shot=on_shot)
    ctrl.update(800)
    ctrl.handle_event(_click((200, 200)))
    _, kwargs = on_shot.call_args
    assert kwargs["target"] == (0.0, 0.0), \
        "the no-mapper sentinel clamps to an in-range guaranteed miss"
    assert ctrl._progress == 0, "the clamped sentinel never registers a hit"


def test_local_edge_shot_adjudicates_on_the_clamped_value(monkeypatch):
    seen = []
    original = MoleChallenge.hit_at

    def spy(self, elapsed_ms, row_f, col_f, holes, last_hit_pop=-1):
        seen.append((row_f, col_f))
        return original(self, elapsed_ms, row_f, col_f, holes, last_hit_pop)

    monkeypatch.setattr(MoleChallenge, "hit_at", spy)
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click((752, 752)))
    assert seen, "the local path adjudicates through the engine"
    for r, c in seen:
        assert r < 8.0 and c < 8.0, "no out-of-range coordinate reaches adjudication"


def test_torn_victim_key_is_per_challenge():
    v = _victim(_CELL)
    other_pops = (MolePop(2, 400.0, 600.0, 1400.0),
                  MolePop(0, 1500.0, 1700.0, 2500.0),
                  MolePop(1, 2600.0, 2800.0, 3600.0))
    a = _mole(victim_surface=v, progress=1)
    b = _mole(challenge=_challenge(pops=other_pops), victim_surface=v, progress=1)
    sa, sb = a._victim_sprite(), b._victim_sprite()
    assert sa is not sb, "distinct challenges never share a cached torn victim"
    assert pg.image.tostring(sa, "RGBA") != pg.image.tostring(sb, "RGBA"), \
        "different pop scripts tear the victim differently"
    assert a._victim_sprite() is sa, "the same check re-uses its cached torn victim"


def test_resume_with_progress_seeds_the_already_hit_pop():
    now = pg.time.get_ticks()
    ch = _challenge()
    ctrl = MoleController(ch, pg.Rect(3 * _CELL, 4 * _CELL, _CELL, _CELL), now - 1000,
                          ch.deadline_ms, hole_squares=_HOLES, geom=_geom_for(_CELL),
                          audio=MagicMock(), victim_surface=_victim(_CELL), progress=1)
    assert ctrl._last_hit_pop == 0, \
        "resuming mid-pop seeds the hit index so the pop can't be locally re-hit"
    ctrl.update(now)
    ctrl.handle_event(_click(_hole_px(0)))
    assert ctrl._progress == 1, "the already-hit pop is deduped on the resumed client"
    ctrl.update(now + 900)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._progress == 2, "a later pop still registers normally"


def test_whack_hit_plays_the_pitch_ladder_index():
    ctrl = _mole()
    ctrl.update(800)
    ctrl.handle_event(_click(_hole_px(0)))
    ctrl.update(2000)
    ctrl.handle_event(_click(_hole_px(1)))
    assert ctrl._audio.play_whack_hit.call_args_list == [call(0), call(1)]


def test_whack_hit_pitch_ladder_muted_when_passive():
    ctrl = _mole(passive=True)
    ctrl.update(900)
    ctrl.spectate_shot(800.0, 0, True, progress=1, target=(2.5, 2.5))
    ctrl._audio.play_whack_hit.assert_not_called()


def test_no_per_frame_logging(caplog):
    surf = pg.Surface((640, 640))
    ctrl = _mole()
    with caplog.at_level(logging.DEBUG):
        for i in range(100):
            ctrl.update(i * 16)
            ctrl.draw(surf)
    assert not caplog.records, "the mole view stays silent on the frame path"
