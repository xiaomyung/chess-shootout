import math
from collections.abc import Callable, Sequence
from typing import NamedTuple

import pygame as pg

from chessshootout.backend.utils import BOARD_SIZE, Square
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.skillcheck.controller import SkillCheckController
from chessshootout.frontend.skillcheck.juice import (
    Trauma, Hitstop, expire_particles, particle_ages, sakurai_vibrate, torn_sprite,
    flash_sprite, TORN_MAX_TIER)
from chessshootout.frontend.skillcheck.mole_art import (
    MOLE_VIEW_BLOOM_BUCKETS, MOLE_VIEW_CASING_SPIN_BUCKET_DEG, MOLE_VIEW_CROSS_OUT_BUCKETS,
    MOLE_VIEW_PULSE_BUCKETS, PIT_DARK, casing_rotated, cross_glow_surface,
    crosshair_surface, emerge_mask, muzzle_surface, pit_front_surface, pit_mouth,
    pit_surface, pit_telegraph_surface, seam_band_surface, seam_glow_surface,
    win_pop_surface)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    cosine_pulse, rounded_rect_surface, strike_pip_surface)
from chessshootout.frontend.visual.tween import out_cubic
from chessshootout.infra import env
from chessshootout.skillcheck.mole import (
    MOLE_GRACE_MS, MOLE_HITBOX_RX_FRAC, MOLE_HITBOX_RY_FRAC,
    MOLE_INTRO_MS, MOLE_MAX_WHIFFS, MOLE_RECOIL_LOCKOUT_MS, MoleChallenge, MolePop,
    hitbox_lift)
from chessshootout.skillcheck.rng import seeded_floats

MOLE_VIEW_FAIL_HOLD_MS = 1250
MOLE_VIEW_HOLE_STAGGER_MS = 40.0
MOLE_VIEW_HOLE_OPEN_MS = 160.0
MOLE_VIEW_RETREAT_MS = 160.0
MOLE_VIEW_POP_HEIGHT_FRAC = 1.0
MOLE_VIEW_POP_OVERSHOOT = 1.08
MOLE_VIEW_POP_APEX_FRAC = 0.30
MOLE_VIEW_POP_LIFT_CAP = 1.2
MOLE_VIEW_PIT_RX_FRAC = 0.42
MOLE_VIEW_PIT_RY_FRAC = 0.24
MOLE_VIEW_EMERGE_FADE_FRAC = 0.35
MOLE_VIEW_PIT_CLOSE_MS = 160.0
MOLE_VIEW_PULSE_MS = 420
MOLE_VIEW_DANGER_PULSE_MS = 200
MOLE_VIEW_DANGER_SWITCH = 0.5
MOLE_VIEW_SQUASH_BUCKETS = 4
MOLE_VIEW_SQUASH_X = 0.28
MOLE_VIEW_SQUASH_Y = 0.38
MOLE_VIEW_CROSS_ARM_FRAC = 0.19
MOLE_VIEW_CROSS_GAP_FRAC = 0.05
MOLE_VIEW_CROSS_LW_FRAC = 0.024
MOLE_VIEW_CROSS_GLOW_FRAC = 0.16
MOLE_VIEW_CROSS_OUT_MS = 120.0
MOLE_VIEW_KICK_FRAC = 0.12
MOLE_VIEW_KICK_MS = 140.0
MOLE_VIEW_MUZZLE_MS = 90.0
MOLE_VIEW_MUZZLE_FRAC = 0.34
MOLE_VIEW_HIT_FLASH_MS = 90.0
MOLE_VIEW_TRAUMA_PER_HIT = 0.3
MOLE_VIEW_TRAUMA_OFFSET_FRAC = 0.10
MOLE_VIEW_HITSTOP_HIT_MS = 60.0
MOLE_VIEW_HITSTOP_KILL_MS = 200.0
MOLE_VIEW_VIBRATE_AMP_FRAC = 0.05
MOLE_VIEW_WIN_POP_MS = 350.0
MOLE_VIEW_WIN_POP_R_FRAC = 1.1
MOLE_VIEW_WIN_HOLD_MS = 750
MOLE_VIEW_TOSS_MS = 550.0
MOLE_VIEW_TOSS_SPEED_FRAC = 2.6
MOLE_VIEW_TOSS_UP_FRAC = 1.4
MOLE_VIEW_TOSS_GRAVITY_FRAC = 6.0
MOLE_VIEW_TOSS_SPIN_DPS = 540.0
MOLE_VIEW_TOSS_FADE_START = 0.45
MOLE_VIEW_TOSS_FALLBACK_ARC = (0.2, 0.8)
MOLE_VIEW_JUMP_RISE_MS = 180.0
MOLE_VIEW_JUMP_HOP_MS = 320.0
MOLE_VIEW_JUMP_HEIGHT_FRAC = 0.5
MOLE_VIEW_LAND_SQUASH_MS = 90.0
MOLE_VIEW_REGROW_MS = 550.0
MOLE_VIEW_HEAL_BUCKETS = 24
MOLE_VIEW_SEAM_BAND_FRAC = 0.21
MOLE_VIEW_SEAM_GLOW_W_FRAC = 1.25
MOLE_VIEW_SEAM_GLOW_H_FRAC = 0.10
MOLE_VIEW_SPARK_MS = 260.0
MOLE_VIEW_SPARK_SPEED_FRAC = 0.30
MOLE_VIEW_SPARK_RISE_FRAC = 0.12
MOLE_VIEW_SPARK_R_FRAC = 0.035
MOLE_VIEW_SPARK_SPEED_JITTER = (0.6, 0.8)
MOLE_VIEW_SPARK_RISE_JITTER = (0.5, 1.0)
MOLE_VIEW_PIP_W_FRAC = 0.11
MOLE_VIEW_PIP_H_FRAC = 0.20
MOLE_VIEW_PIP_GAP_FRAC = 0.07
MOLE_VIEW_PIP_OFFSET_FRAC = 0.66
MOLE_VIEW_PIP_FADE_DELAY_MS = 300.0
MOLE_VIEW_PIP_FADE_MS = 250.0
MOLE_VIEW_PIP_RADIUS_DIV = 3
MOLE_VIEW_CROSS_STRIKE_SIZE_FRAC = 0.16
MOLE_VIEW_CROSS_STRIKE_GAP_FRAC = 0.07
MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC = 0.66
MOLE_VIEW_CROSS_STRIKE_LW_FRAC = 0.12
MOLE_VIEW_CROSS_STRIKE_PAD_FRAC = 0.28
MOLE_VIEW_CROSS_STRIKE_RING_LW_FRAC = 0.1
MOLE_VIEW_CASING_W_FRAC = 0.10
MOLE_VIEW_CASING_H_FRAC = 0.05
MOLE_VIEW_CASING_VX_FRAC = 1.4
MOLE_VIEW_CASING_UP_FRAC = 1.8
MOLE_VIEW_CASING_GRAVITY_FRAC = 7.0
MOLE_VIEW_CASING_FALL_FRAC = 0.7
MOLE_VIEW_CASING_SPIN_DPS = 520.0
MOLE_VIEW_CASING_UP_JITTER = (0.7, 0.6)
MOLE_VIEW_CASING_REST_MS = 1000.0
MOLE_VIEW_CASING_FADE_MS = 400.0
MOLE_VIEW_CASING_COMMIT_FADE_MS = 300.0
MOLE_VIEW_PUFF_MS = 320.0
MOLE_VIEW_PUFF_COUNT = 5
MOLE_VIEW_PUFF_R_FRAC = 0.09
MOLE_VIEW_PUFF_SPEED_FRAC = 0.9
MOLE_VIEW_PUFF_SPEED_JITTER = (0.5, 0.5)
MOLE_VIEW_DEBRIS_MS = 420.0
MOLE_VIEW_DEBRIS_COUNT = 7
MOLE_VIEW_DEBRIS_R_FRAC = 0.05
MOLE_VIEW_DEBRIS_SPEED_FRAC = 1.6
MOLE_VIEW_DEBRIS_SPEED_JITTER = (0.4, 0.6)
MOLE_VIEW_DEBRIS_GRAVITY_FRAC = 4.0
MOLE_VIEW_IMPACT_MS = 260.0
MOLE_VIEW_IMPACT_R_FRAC = 0.12
MOLE_VIEW_FALLBACK_SPREAD_FRAC = 1.2
MOLE_VIEW_TARGET_MAX = BOARD_SIZE - 0.001
MOLE_VIEW_HITBOX_LW = 1
MOLE_VIEW_HITBOX_ACTIVE_LW = 2


class MoleCasing(NamedTuple):
    """
    One spent shell in flight, from the shot that threw it out to the moment it
    comes to rest. Speeds are pixels per second and the landing time is
    seconds, so the whole arc can be evaluated from these at draw time
    """

    spawn_ms: float
    x0: float
    y0: float
    vx: float
    vy: float
    gravity: float
    t_land: float
    spin: float


class MoleToss(NamedTuple):
    """
    The beaten mole's flight off the board after a won check: where the body
    left from, how fast, and which way it tumbles. Everything else about the
    arc is worked out per frame from these
    """

    x0: float
    y0: float
    vx: float
    vy: float
    spin: float


_IMPACT_COLOR = pg.Color(Colors.spectate)
_HITBOX_COLOR = pg.Color(Colors.spectate)
_HITBOX_ACTIVE_COLOR = pg.Color(Colors.win)
_DUST_COLORS = (pg.Color(Colors.text_dim), pg.Color(Colors.text_muted), pg.Color(Colors.border))
_DEBRIS_COLORS = (pg.Color(Colors.amber_hi), pg.Color(Colors.accent_hi), pg.Color(Colors.amber))

_POP_APEX = MOLE_VIEW_POP_HEIGHT_FRAC * MOLE_VIEW_POP_OVERSHOOT
_CLEAR = (0, 0, 0, 0)


def _blit_alpha(window: pg.Surface, surf: pg.Surface, pos: tuple[int, int],
                alpha: int) -> None:
    """
    Blit a shared sprite at a given opacity and hand it back untouched. Almost
    everything drawn here comes out of a cache, so a fade has to be put on and
    taken off around the blit rather than baked into the surface

    :param window: surface being drawn onto
    :param surf: the shared sprite to blit, left at full opacity afterwards
    :param pos: top-left corner in window pixels
    :param alpha: opacity from 0 to 255; 255 blits it as it is
    """
    if alpha < 255:
        surf.set_alpha(alpha)
    window.blit(surf, pos)
    if alpha < 255:
        surf.set_alpha(255)


def _puff_color(age_frac: float, index: int) -> pg.Color:
    """
    Colour one mote of the dust a wild shot kicks up, cooling through the dim
    greys as the puff ages

    :param age_frac: how far through its life the puff is, 0.0 fresh to 1.0
        gone
    :param index: which mote of the burst it is, ignored here so that dust of
        one age matches
    :returns: the colour to draw that mote in
    """
    return _DUST_COLORS[min(int(age_frac * len(_DUST_COLORS)), len(_DUST_COLORS) - 1)]


def _debris_color(age_frac: float, index: int) -> pg.Color:
    """
    Colour one chunk thrown off a mole that was hit, cycling the hot colours so
    a burst reads as sparks rather than one blob

    :param age_frac: how far through its life the burst is, ignored here since
        a chunk keeps its colour as it flies
    :param index: which chunk of the burst it is, which picks the colour
    :returns: the colour to draw that chunk in
    """
    return _DEBRIS_COLORS[index % len(_DEBRIS_COLORS)]


class MoleController(SkillCheckController):
    """
    Runs the Whack-a-Mole check a capture can fire: moles pop out of seeded
    pits dug around the victim and the player shoots them with the crosshair.
    The quota grows with the prize -- three pops for a pawn, four for a knight,
    bishop or rook, all five for a queen -- and the check is lost on
    MOLE_MAX_WHIFFS wild shots, on the deadline, or as soon as the quota stops
    being reachable. Online it draws and reports only: a shot travels as an
    elapsed time plus a board-space point, and the server judges it
    """

    def __init__(self, challenge: MoleChallenge, cell_rect: pg.Rect, now_ms: int,
                 deadline_ms: float, *,
                 hole_squares: Sequence[tuple[int, int]] | None = None,
                 victim_surface: pg.Surface | None = None,
                 geom: Callable[[Square], tuple[int, int]] | None = None,
                 from_sq: Square | None = None,
                 shot_sound: Callable[[], None] | None = None,
                 on_shot: Callable[..., None] | None = None,
                 miss_count: int = 0, progress: int = 0, passive: bool = False,
                 audio: SoundManager | None = None,
                 on_hit_px: Callable[[tuple[float, float], bool], None] | None = None,
                 mirror_targets: bool = False, last_hit_pop: int = -1,
                 adjudicated_flipped: bool | None = None) -> None:
        """
        Open one whack check over a square: size everything to the board, hide
        the pointer in favour of the crosshair and start the mole dropping into
        its home pit. A check resumed after a reconnect is built with the hits
        and misses it already had, so it carries on rather than starting again

        :param challenge: the pop schedule, built from the check's seed so both
            players and the server share it exactly
        :param cell_rect: the board square the check is anchored on, whose
            width is the scale for everything drawn
        :param now_ms: pygame tick count the check counts from, already
            backdated by however much of the deadline has gone
        :param deadline_ms: how long the whole check may run, in milliseconds
        :param hole_squares: pit squares in pit order, derived again from the
            seed on this machine; the judge derives its own copy and never
            takes geometry from a client
        :param victim_surface: sprite of the piece being shot at, which stands
            in as the mole; None leaves nothing to draw
        :param geom: turns a board square into its centre in window pixels, the
            only bridge between board space and the screen; None falls back to
            a row of pits that can be drawn but never hit
        :param from_sq: square the capturing piece stands on, which aims the
            body's flight and anchors the whiff badges
        :param shot_sound: plays the capturer's own weapon on every shot, None
            for silence
        :param on_shot: reports a shot to the server as an elapsed time and a
            board-space point; None offline, where this controller judges for
            itself
        :param miss_count: wild shots already spent, for a resumed check
        :param progress: moles already hit, likewise
        :param passive: True for the read-only mirror of the opponent's check,
            which takes no input and sends nothing
        :param audio: the app's sound manager, None when there is nothing to
            play through
        :param on_hit_px: hands each hit's window pixels back to the game
            screen, which fires the gun there and takes the piece on the hit
            that fills the quota
        :param mirror_targets: True when the shots arriving are the opponent's
            and have to be re-anchored into this board's orientation
        :param last_hit_pop: pop already hit before this controller was built,
            so a resumed check cannot shoot one mole twice; -1 for none
        :param adjudicated_flipped: which way up the board is for the player
            actually shooting, since a mole is drawn above its hole; None
            offline, where nobody else has to agree
        """
        self._init_common(challenge, now_ms, deadline_ms, on_shot=on_shot, passive=passive,
                          audio=audio)
        self._hole_squares = tuple(hole_squares) if hole_squares is not None else ()
        self._geom = geom
        self._from_sq = from_sq
        self._shot_sound = shot_sound
        self._on_hit_px = on_hit_px
        self._mirror_targets = mirror_targets
        self._adjudicated_flipped = adjudicated_flipped
        self._init_victim(victim_surface, cell_rect)
        self._victim_bbox = None
        self._squash_cache = {}
        self._heal_cache = {}
        self._emerge_scratch = {}
        self._progress = progress
        self._miss_count = miss_count
        self._torn_key = hash(challenge.pops)
        self._last_hit_pop = last_hit_pop
        self._last_hit_anim_ms = (None if last_hit_pop < 0
                                  else float(now_ms) - MOLE_VIEW_RETREAT_MS)
        self._last_hit_height = 0.0
        self._last_hit_px = None
        self._last_hit_hole = None
        self._last_hit_spectate_target = None
        self._reset_effects(cell_rect.center)
        self._win_ms = None
        self._last_shot_ms = None
        self._shot_count = 0
        self._next_telegraph = 0
        self._next_pop = 0
        self._cues_primed = False
        self._anim_ms = float(now_ms)
        first = challenge.pops[0]
        self._intro_ms = max(min(MOLE_INTRO_MS, first.t_telegraph_ms), 1.0)
        self._debug_hitbox = env.get_debug_hitbox()
        self._cursor_hidden = False
        if not passive:
            pg.mouse.set_visible(False)
            self._cursor_hidden = True
        self._apply_geometry(cell_rect)
        self._cue("play_mole_fall")

    def _reset_effects(self, flash_px: tuple[int, int]) -> None:
        """
        Put every effect back to nothing -- shake, freeze, particles, casings,
        the body's flight -- so the check starts on a quiet board

        :param flash_px: where the muzzle flash would sit until the first shot
            moves it, in window pixels
        """
        self._hit_flash_ms = None
        self._vibrate_ms = None
        self._vibrate_dur_ms = 0.0
        self._flash_ms = None
        self._flash_px = flash_px
        self._trauma = Trauma()
        self._hitstop = Hitstop()
        self._toss = None
        self._casings = []
        self._puffs = []
        self._debris = []
        self._impacts = []
        self._seam_sparks = []
        self._last_heal_bucket = 0

    def _apply_geometry(self, cell_rect: pg.Rect) -> None:
        """
        Size the whole check to the board as it stands, at build time and again
        after every resize or flip. Pits, crosshair, badges and the mole sprite
        are all derived from one cell's width, and the caches keyed by pixel
        size are dropped because nothing in them fits any more

        :param cell_rect: the board square the check is anchored on, whose
            width is the scale for everything drawn
        """
        cell = max(int(cell_rect.width), 1)
        self.center = cell_rect.center
        self.cell_size = cell
        if self._victim_orig is not None:
            self._victim = self._scaled_victim(cell)
        if self._victim is not None:
            self._victim_bbox = self._victim.get_bounding_rect()
        self._affine = self._derive_affine()
        self._hole_px = self._hole_centers()
        self._last_hit_px = self._reanchored_hit_px()
        self._pit_rx = max(int(cell * MOLE_VIEW_PIT_RX_FRAC), 6)
        self._pit_ry = max(int(cell * MOLE_VIEW_PIT_RY_FRAC), 4)
        self._mouth_rx, self._mouth_ry = pit_mouth(self._pit_rx, self._pit_ry)
        self._emerge_fade = max(int(self._mouth_ry * MOLE_VIEW_EMERGE_FADE_FRAC), 2)
        self._cross_arm = max(int(cell * MOLE_VIEW_CROSS_ARM_FRAC), 4)
        self._cross_gap = max(int(cell * MOLE_VIEW_CROSS_GAP_FRAC), 2)
        self._cross_lw = max(round(cell * MOLE_VIEW_CROSS_LW_FRAC), 1)
        self._kick_amp = cell * MOLE_VIEW_KICK_FRAC
        self._pip_w = max(int(cell * MOLE_VIEW_PIP_W_FRAC), 4)
        self._pip_h = max(int(cell * MOLE_VIEW_PIP_H_FRAC), 6)
        self._pip_gap = max(int(cell * MOLE_VIEW_PIP_GAP_FRAC), 2)
        self._strike_size = max(int(cell * MOLE_VIEW_CROSS_STRIKE_SIZE_FRAC), 6)
        self._strike_gap = max(int(cell * MOLE_VIEW_CROSS_STRIKE_GAP_FRAC), 2)
        self._squash_cache.clear()
        self._heal_cache.clear()
        self._emerge_scratch.clear()

    def _derive_affine(self) -> tuple[float, float, float, float] | None:
        """
        Measure the board once by asking it for two squares, giving the
        straight-line mapping between board space and window pixels. Every
        crossing between the two goes through it: shots on their way out,
        relayed shots coming in, and the debug hit boxes

        :returns: (x of the first square's centre, its y, pixels per column,
            pixels per row -- negative when the board is drawn from Black's
            side), or None when there is no board to measure
        """
        if self._geom is None:
            return None
        x0, y0 = self._geom(Square(0, 0))
        x1, y1 = self._geom(Square(1, 1))
        dx, dy = x1 - x0, y1 - y0
        if dx == 0 or dy == 0:
            return None
        return (float(x0), float(y0), float(dx), float(dy))

    def _hole_centers(self) -> tuple[tuple[int, int], ...]:
        """
        Put every pit on screen, one per pit square. With no board to ask, they
        are simply spread in a row about the anchor square, which draws but can
        never be shot at

        :returns: centre of each pit in window pixels, in pit order
        """
        if self._geom is not None:
            return tuple(self._geom(Square(row, col)) for row, col in self._hole_squares)
        n = len(self._hole_squares)
        spread = self.cell_size * MOLE_VIEW_FALLBACK_SPREAD_FRAC
        return tuple((int(self.center[0] + (i - (n - 1) / 2.0) * spread), self.center[1])
                     for i in range(n))

    def _board_to_px(self, row_f: float, col_f: float) -> tuple[float, float] | None:
        """
        Turn a point in board space into window pixels, which is how a shot the
        server relayed becomes something this screen can draw

        :param row_f: row in board space, a whole number being a square edge
            and a half its centre
        :param col_f: column in that same board space
        :returns: the point in window pixels, or None with no board mapping
        """
        if self._affine is None:
            return None
        x0, y0, dx, dy = self._affine
        return (x0 + (col_f - 0.5) * dx, y0 + (row_f - 0.5) * dy)

    def _shot_target(self, pos: tuple[int, int]) -> tuple[float, float] | None:
        """
        Turn the pixel the player shot at into the board-space point that gets
        judged. This pair of numbers is all that ever leaves the machine -- the
        judge holds the geometry itself, so no client can describe its own hit
        boxes

        :param pos: where the shot was aimed, in window pixels
        :returns: (row, column) in board space, or None with no board mapping
        """
        if self._affine is None:
            return None
        x0, y0, dx, dy = self._affine
        return ((pos[1] - y0) / dy + 0.5, (pos[0] - x0) / dx + 0.5)

    def _clamp_target(self, target: tuple[float, float]) -> tuple[float, float]:
        """
        Hold a board-space point inside the board, so neither a shot leaving
        for the server nor a relayed one being drawn can sit off the edge of it

        :param target: (row, column) in board space
        :returns: the same point held inside the board's span
        """
        return (min(max(target[0], 0.0), MOLE_VIEW_TARGET_MAX),
                min(max(target[1], 0.0), MOLE_VIEW_TARGET_MAX))

    def _wire_target(self, target: tuple[float, float]) -> tuple[float, float]:
        """
        Restate a shot in the orientation the judge is using. A mole is drawn
        above its hole, so the hit box is lifted off the square, and a player
        who has flipped their own board would otherwise report shots lifted the
        wrong way from where the server looks for them

        :param target: (row, column) in board space as this screen sees it
        :returns: the point to report, unchanged when both sides already agree
            which way is up
        """
        if (self._adjudicated_flipped is None
                or self._adjudicated_flipped == (self._affine[3] < 0)):
            return target
        return self._clamp_target(
            (target[0] + 2.0 * hitbox_lift(self._adjudicated_flipped), target[1]))

    def handle_event(self, event: pg.event.Event) -> bool:
        """
        Take the player's shots while the check is live: a left click or the
        space bar fires at the cursor. The mirror takes nothing at all, and
        once the check is decided or the quota filled events are swallowed
        rather than acted on, so a late click cannot fall through onto the
        board

        :param event: event handed down by the skill-check overlay
        :returns: True when the check consumed it
        """
        if self._passive:
            return False
        if self._committed_at is not None or self._quota_met():
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._fire(event.pos)
            return True
        if event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
            self._fire(pg.mouse.get_pos())
            return True
        return False

    def _quota_met(self) -> bool:
        """
        Whether enough moles have been hit to land the move -- three for a
        pawn, four for a knight, bishop or rook, all five pops for a queen

        :returns: True once the quota is filled
        """
        return self._progress >= self.challenge.hits_required

    def _fire(self, pos: tuple[int, int]) -> None:
        """
        Fire one shot. The recoil lockout can eat it outright; otherwise it
        becomes a board-space point that is drawn, reported to the server
        online and judged here offline. A hit ducks the mole and counts towards
        the quota, a miss spends one of MOLE_MAX_WHIFFS and loses the check
        when the last is gone

        :param pos: where the shot was aimed, in window pixels
        """
        if (self._last_shot_ms is not None
                and self._now - self._last_shot_ms < MOLE_RECOIL_LOCKOUT_MS):
            self._cue("play_whack_dry")
            return
        target = self._shot_target(pos)
        if target is None:
            return
        target = self._clamp_target(target)
        self._flash_ms = self._now
        self._flash_px = pos
        self._last_shot_ms = self._now
        if self._shot_sound is not None:
            self._shot_sound()
        elapsed = self._now - self.start_ms
        wired = self._wire_target(target)
        if self._online:
            self._on_shot(elapsed, target=wired)
        flipped = (self._affine[3] < 0 if self._adjudicated_flipped is None
                   else self._adjudicated_flipped)
        if self.challenge.hit_at(elapsed, wired[0], wired[1], self._hole_squares,
                                 self._last_hit_pop, flipped=flipped):
            self._register_hit(elapsed, pos)
        else:
            self._miss_count += 1
            self._spawn_puffs(pos)
            self._cue("play_whiff_ricochet")
            if not self._online and self.challenge.whiffs_exhausted(self._miss_count):
                self._commit(False)
        self._spawn_casing(pos)

    def _register_hit(self, elapsed: float, shot_px: tuple[int, int]) -> None:
        """
        Land a hit: the mole that was up ducks away, the quota moves on, the
        juice plays and the game screen is told where it happened so the gun
        fires there. Offline the hit that fills the quota also wins the check

        :param elapsed: milliseconds into the check the shot was fired at
        :param shot_px: where the shot landed in window pixels, used only when
            the pit it hit cannot be placed
        """
        idx = self.challenge.pop_up_at(elapsed)
        self._duck_pop(idx, elapsed)
        hole = self.challenge.pops[idx].hole
        if hole < len(self._hole_px):
            self._last_hit_px = self._hole_px[hole]
            self._last_hit_hole = hole
            self._last_hit_spectate_target = None
        self._progress += 1
        kill = self._quota_met()
        self._hit_juice(kill)
        self._emit_hit_px(shot_px, kill)
        if self._audio is not None and not self._passive:
            self._audio.play_whack_hit(self._progress - 1)
        if kill:
            self._cue("play_whack_kill")
            if not self._online:
                self._commit(True)

    def _emit_hit_px(self, shot_px: tuple[float, float] | None, kill: bool) -> None:
        """
        Tell the game screen where a hit landed, so the gun's muzzle flash goes
        off on the board and the hit that fills the quota takes the piece
        standing there

        :param shot_px: fallback point in window pixels for when the pit is not
            known, None when there is not even that
        :param kill: True when this hit fills the quota
        """
        if self._on_hit_px is None:
            return
        px = self._last_hit_px if self._last_hit_px is not None else shot_px
        if px is not None:
            self._on_hit_px(px, kill)

    def _hit_juice(self, kill: bool) -> None:
        """
        Play everything a hit feels like at once: the screen shakes, the frame
        freezes for a beat, the body shivers and flashes white, and debris
        comes off it. The killing hit gets the longer freeze

        :param kill: True when this hit fills the quota
        """
        self._trauma.add(MOLE_VIEW_TRAUMA_PER_HIT)
        dur = MOLE_VIEW_HITSTOP_KILL_MS if kill else MOLE_VIEW_HITSTOP_HIT_MS
        self._hitstop.trigger(self._now, dur)
        self._vibrate_ms = self._now
        self._vibrate_dur_ms = dur
        self._hit_flash_ms = self._now
        self._spawn_debris(self._last_hit_px if self._last_hit_px is not None else self.center)

    def _spawn_casing(self, pos: tuple[float, float]) -> None:
        """
        Throw a spent shell out of the gun. Its whole arc is drawn from the
        shot's number, so the same shot always throws the same casing however
        many times the moment is replayed

        :param pos: where the shot was fired, in window pixels
        """
        self._shot_count += 1
        cell = self.cell_size
        f = seeded_floats(f"molecasing:{self._shot_count}", 3)
        up_base, up_span = MOLE_VIEW_CASING_UP_JITTER
        vx = (f[0] * 2.0 - 1.0) * cell * MOLE_VIEW_CASING_VX_FRAC
        vy = -cell * MOLE_VIEW_CASING_UP_FRAC * (up_base + up_span * f[1])
        g = cell * MOLE_VIEW_CASING_GRAVITY_FRAC
        fall = cell * MOLE_VIEW_CASING_FALL_FRAC
        t_land = (-vy + math.sqrt(vy * vy + 2.0 * g * fall)) / g
        spin = 1.0 if f[2] < 0.5 else -1.0
        self._casings.append(
            MoleCasing(self._now, float(pos[0]), float(pos[1]), vx, vy, g, t_land, spin))

    def _spawn_burst(self, items: list[tuple[float, float, float, tuple[float, ...]]],
                     pos: tuple[float, float], prefix: str, count: int,
                     tag: str = "") -> None:
        """
        Start one particle burst, keeping only when and where it began plus the
        seeded numbers its motes fly by. Every mote is worked out again at draw
        time, so nothing per-particle is ever stored or stepped

        :param items: the burst list to append to
        :param pos: origin of the burst in window pixels
        :param prefix: seed namespace, which keeps one effect's randomness out
            of another's
        :param count: how many motes the burst has
        :param tag: extra seed text so two bursts from one shot differ
        """
        f = seeded_floats(f"{prefix}:{tag}{self._shot_count + 1}", count * 2)
        items.append((self._now, float(pos[0]), float(pos[1]), f))

    def _spawn_puffs(self, pos: tuple[float, float]) -> None:
        """
        Kick up dust where a shot hit nothing, the visible half of a whiff

        :param pos: where the shot landed, in window pixels
        """
        self._spawn_burst(self._puffs, pos, "molepuff", MOLE_VIEW_PUFF_COUNT)

    def _spawn_debris(self, pos: tuple[float, float], tag: str = "") -> None:
        """
        Throw chunks off a mole that has just been hit or beaten

        :param pos: where the hit landed, in window pixels
        :param tag: extra seed text so the burst on the body's flight differs
            from the one on the hit that started it
        """
        self._spawn_burst(self._debris, pos, "moledebris", MOLE_VIEW_DEBRIS_COUNT, tag=tag)

    def _spawn_seam_sparks(self) -> None:
        """
        Spit sparks out of the seam while a beaten mole knits itself back
        together, one pair per step of the healing. Tying them to the steps
        rather than to frames keeps the shower the same on any machine
        """
        if self._jump_elapsed() is None or self._damage_tier() <= 0:
            return
        bucket = self._heal_bucket()
        speed_base, speed_span = MOLE_VIEW_SPARK_SPEED_JITTER
        rise_base, rise_span = MOLE_VIEW_SPARK_RISE_JITTER
        while self._last_heal_bucket < bucket:
            self._last_heal_bucket += 1
            f = seeded_floats(f"moleseam:{self._torn_key}:{self._last_heal_bucket}", 4)
            frac = 1.0 - self._last_heal_bucket / MOLE_VIEW_HEAL_BUCKETS
            for side, speed_f, rise_f in ((-1, f[0], f[1]), (1, f[2], f[3])):
                self._seam_sparks.append(
                    (self._now, side, frac, speed_base + speed_span * speed_f,
                     rise_base + rise_span * rise_f))

    def _spectate_px(self, target: tuple[float, float]) -> tuple[float, float] | None:
        """
        Turn a shot the server relayed into a point on this board. The screen
        has already clamped it inside the board before it gets here; what is
        left is re-anchoring, because the mole sat above its hole on the
        shooter's screen and this board may be the other way up

        :param target: (row, column) in board space as the shooter aimed it
        :returns: the point in window pixels, or None with no board mapping
        """
        px = self._board_to_px(target[0], target[1])
        if px is None or not self._mirror_targets:
            return px
        own = hitbox_lift(self._affine[3] < 0)
        mover = hitbox_lift(bool(self._adjudicated_flipped))
        return (px[0], px[1] + (own - mover) * self._affine[3])

    def _reanchored_hit_px(self) -> tuple[float, float] | None:
        """
        Find where the last hit landed on the board as it is now, from the pit
        it happened in or, in the mirror, from the point the server relayed.
        Without this a resize or a flip would leave the win burst and the gun's
        muzzle sitting on pixels that no longer mean anything

        :returns: the point in window pixels, or None when there is nothing to
            re-anchor
        """
        hole = self._last_hit_hole
        if hole is not None:
            return self._hole_px[hole] if hole < len(self._hole_px) else None
        if self._last_hit_spectate_target is None:
            return None
        return self._spectate_px(self._last_hit_spectate_target)

    def spectate_shot(self, elapsed: float, miss_count: int, won: bool, progress: int = 0,
                      direction: str | None = None,
                      target: tuple[float, float] | None = None) -> None:
        """
        Replay one of the opponent's shots inside the read-only mirror, so both
        players watch the same shootout. Nothing is judged here: the progress
        and misses are taken as the server states them, and the point is used
        only to put the impact ring, the casing and the dust somewhere true

        :param elapsed: milliseconds into the check their shot was fired at
        :param miss_count: wild shots they had spent before this one
        :param won: True when this shot ended the whole check in their favour
        :param progress: moles they have hit in total, which is what moves the
            quota pips
        :param direction: answer to a combo prompt, never sent for whack
        :param target: (row, column) in board space they aimed at, already
            clamped to the board, None when the server sent none
        """
        px = None
        if target is not None:
            px = self._spectate_px(target)
        if px is not None:
            self._impacts.append((self._now, px[0], px[1]))
            self._spawn_casing(px)
        if progress > self._progress:
            self._progress = progress
            if px is not None:
                self._last_hit_px = px
                self._last_hit_spectate_target = target
                self._last_hit_hole = None
            idx = self.challenge.pop_up_at(elapsed)
            if idx is not None:
                self._duck_pop(idx, elapsed)
            kill = self._quota_met()
            self._hit_juice(kill)
            self._emit_hit_px(px, kill)
        elif not won:
            if miss_count + 1 > self._miss_count:
                self._miss_count = miss_count + 1
            if px is not None:
                self._spawn_puffs(px)

    def resolve(self, won: bool) -> None:
        """
        Take the server's verdict, which is the only thing that ends an online
        check. The hold before the overlay may close starts here, and a lost
        check sets the beaten mole healing

        :param won: True when the server says the shooter landed it
        """
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        if won:
            self._win_ms = self._now
        self._emit_verdict()
        self._cue_heal()
        self._restore_cursor()

    def _commit(self, landed: bool) -> None:
        """
        End an offline check with a verdict of our own -- the quota filled, the
        whiffs spent, the deadline gone, or the quota out of reach

        :param landed: True when the player won it
        """
        self._landed = landed
        self._committed_at = self._now
        if landed:
            self._win_ms = self._now
        self._emit_verdict()
        self._cue_heal()
        self._restore_cursor()

    def _cue_heal(self) -> None:
        """
        Play the mole stitching itself back together, but only after a lost
        check that actually tore it
        """
        if self._landed is False and self._damage_tier() > 0:
            self._cue("play_mole_heal")

    def close(self) -> None:
        """
        Give the pointer back when the overlay is torn down without a verdict,
        which happens when the screen is left or the game ends mid-check
        """
        self._restore_cursor()

    def _restore_cursor(self) -> None:
        """
        Show the mouse pointer again, which the check hid while the crosshair
        stood in for it. Safe to call more than once
        """
        if self._cursor_hidden:
            pg.mouse.set_visible(True)
            self._cursor_hidden = False

    def update(self, now_ms: int) -> None:
        """
        Advance the check one frame: age the particles, hold the animation
        clock still through a freeze frame, and play the cues each pop is due.
        Offline this is also where the check is lost, either on the deadline or
        the moment the quota can no longer be reached; online none of that
        happens here, because the server says when it is over

        :param now_ms: pygame tick count in milliseconds for this frame
        """
        dt = now_ms - self._now
        self._now = now_ms
        self._trauma.update(now_ms)
        if dt > 0 and not self._hitstop.frozen(now_ms):
            self._anim_ms += dt
        expire_particles(self._puffs, now_ms, MOLE_VIEW_PUFF_MS)
        expire_particles(self._debris, now_ms, MOLE_VIEW_DEBRIS_MS)
        expire_particles(self._impacts, now_ms, MOLE_VIEW_IMPACT_MS)
        expire_particles(self._seam_sparks, now_ms, MOLE_VIEW_SPARK_MS)
        self._casings = [c for c in self._casings if now_ms - c.spawn_ms
                         < c.t_land * 1000.0 + MOLE_VIEW_CASING_REST_MS
                         + MOLE_VIEW_CASING_FADE_MS]
        self._spawn_seam_sparks()
        if self._toss is None and self._toss_elapsed() is not None:
            self._start_toss()
        if self._committed_at is None:
            elapsed = now_ms - self.start_ms
            self._cue_schedule(elapsed)
            if not self._online and (elapsed >= self.deadline_ms
                                     or self.challenge.quota_unreachable(
                                         elapsed, self._progress, self._last_hit_pop)):
                self._commit(False)

    def _cue_schedule(self, elapsed: float) -> None:
        """
        Play the telegraph and pop sounds as the schedule reaches them. The
        first pass only takes note of what has already gone by, so a check
        adopted mid-flight after a reconnect does not fire every cue it missed
        in one burst

        :param elapsed: milliseconds since the check started
        """
        pops = self.challenge.pops
        live = self._cues_primed
        self._cues_primed = True
        while (self._next_telegraph < len(pops)
               and elapsed >= pops[self._next_telegraph].t_telegraph_ms):
            self._next_telegraph += 1
            if live:
                self._cue("play_mole_telegraph")
        while self._next_pop < len(pops) and elapsed >= pops[self._next_pop].t_up_ms:
            self._next_pop += 1
            if live:
                self._cue("play_mole_pop")

    @property
    def done(self) -> bool:
        """
        Whether the overlay may close. The verdict is held on screen first,
        longer after a loss so the mole's escape has time to play; online that
        hold only starts when the server's verdict arrives

        :returns: True once the overlay can be torn down
        """
        hold = MOLE_VIEW_WIN_HOLD_MS if self._landed else MOLE_VIEW_FAIL_HOLD_MS
        if self._online:
            if self._resolved_at is None:
                return False
            return self._now - self._resolved_at >= hold
        if self._committed_at is None:
            return False
        return self._now - self._committed_at >= hold

    def draw(self, window: pg.Surface) -> None:
        """
        Draw the whole check for this frame, back to front: the pits, the dust,
        the mole, casings, debris, impacts and the win burst, then the player's
        own crosshair and the two rows of badges. The mirror draws no crosshair
        -- there is nothing in it for the watcher to aim

        :param window: surface the check is drawn onto
        """
        elapsed = self._frozen_elapsed()
        off = self._trauma.offset(self._now, self.cell_size * MOLE_VIEW_TRAUMA_OFFSET_FRAC)
        group = (int(off[0]), int(off[1]))
        self._draw_pits(window, elapsed, group)
        self._draw_puffs(window)
        self._draw_victim(window, elapsed, group)
        self._draw_casings(window)
        self._draw_debris(window)
        self._draw_impacts(window)
        self._draw_win_pop(window, group)
        if not self._passive:
            self._draw_muzzle(window)
            self._draw_crosshair(window)
        self._draw_badges(window, group)
        if self._debug_hitbox:
            self._draw_hitboxes(window, elapsed)

    def _telegraph_hole(self, elapsed: float) -> tuple[int, int] | None:
        """
        Find the pit that is lit right now, in the warning window between a
        mole being telegraphed and appearing

        :param elapsed: milliseconds since the check started
        :returns: (pop index, pit index) of the lit pit, or None when nothing
            is warming up
        """
        if self._committed_at is not None:
            return None
        for index, pop in enumerate(self.challenge.pops):
            if pop.t_telegraph_ms <= elapsed < pop.t_up_ms:
                return index, pop.hole
        return None

    def _draw_pits(self, window: pg.Surface, elapsed: float,
                   group: tuple[int, int]) -> None:
        """
        Draw the ground: the home pit and every dug pit, each opening on its
        own beat so the holes arrive as a wave rather than all at once. The one
        being telegraphed is drawn lit instead of resting

        :param window: surface the pits are drawn onto
        :param elapsed: milliseconds since the check started
        :param group: screen-shake offset in pixels, applied to everything
            anchored to the board
        """
        self._draw_home_pit(window, elapsed, group)
        tele = self._telegraph_hole(elapsed)
        pit = pit_surface(self._pit_rx, self._pit_ry, self._signal_color(Colors.accent))
        for i, (hx, hy) in enumerate(self._hole_px):
            open_t = (elapsed - i * MOLE_VIEW_HOLE_STAGGER_MS) / MOLE_VIEW_HOLE_OPEN_MS
            if open_t <= 0.0:
                continue
            scale = min(open_t, 1.0) * self._pit_close_scale(i)
            if scale <= 0.0:
                continue
            cx, cy = hx + group[0], hy + group[1]
            if scale < 1.0:
                self._draw_pit_mouth(window, cx, cy, scale)
                continue
            surf = pit
            if tele is not None and i == tele[1]:
                surf = self._telegraph_surface(tele[0])
            window.blit(surf, (cx - surf.get_width() // 2, cy - surf.get_height() // 2))

    def _draw_pit_mouth(self, window: pg.Surface, cx: int, cy: int, scale: float) -> None:
        """
        Draw a pit that is only part open as a bare dark oval, which is how a
        hole looks while it is still being dug and again while it closes at the
        end of the check

        :param window: surface the pit is drawn onto
        :param cx: centre of the pit across the window, in pixels
        :param cy: centre of the pit down the window, in pixels
        :param scale: how far open it is, 0.0 shut to 1.0 fully dug
        """
        rx = max(int(self._pit_rx * scale), 2)
        ry = max(int(self._pit_ry * scale), 1)
        pg.draw.ellipse(window, PIT_DARK, pg.Rect(cx - rx, cy - ry, 2 * rx, 2 * ry))

    def _draw_home_pit(self, window: pg.Surface, elapsed: float,
                       group: tuple[int, int]) -> None:
        """
        Draw the hole under the piece being captured, which the mole drops into
        as the check opens and hops back out of if it survives

        :param window: surface the pit is drawn onto
        :param elapsed: milliseconds since the check started
        :param group: screen-shake offset in pixels
        """
        scale = min(elapsed / MOLE_VIEW_HOLE_OPEN_MS, 1.0) * self._home_pit_close_scale()
        if scale <= 0.0:
            return
        cx, cy = self.center[0] + group[0], self.center[1] + group[1]
        if scale < 1.0:
            self._draw_pit_mouth(window, cx, cy, scale)
            return
        surf = pit_surface(self._pit_rx, self._pit_ry, self._signal_color(Colors.accent))
        window.blit(surf, (cx - surf.get_width() // 2, cy - surf.get_height() // 2))

    @staticmethod
    def _close_ramp(closing_ms: float) -> float:
        """
        Turn time spent closing into how open a pit still is, the one ramp
        behind every hole shutting at the end of a check

        :param closing_ms: milliseconds since this pit began to close, zero or
            less meaning it has not started
        :returns: how open it is, 1.0 down to 0.0
        """
        if closing_ms <= 0.0:
            return 1.0
        return max(1.0 - closing_ms / MOLE_VIEW_PIT_CLOSE_MS, 0.0)

    def _outro_start(self) -> float | None:
        """
        Say when the ground starts closing up, which is as soon as the check is
        decided -- except after a win, where the freeze frame on the killing
        blow is allowed to finish first

        :returns: the tick count in milliseconds it starts at, or None while
            the check is still being fought
        """
        if self._committed_at is None:
            return None
        if self._landed:
            return self._committed_at + MOLE_VIEW_HITSTOP_KILL_MS
        return self._committed_at

    def _pit_close_scale(self, index: int) -> float:
        """
        How open one dug pit still is, staggered so the holes shut in the same
        wave they opened in

        :param index: which pit, in pit order
        :returns: how open it is, 1.0 down to 0.0
        """
        start = self._outro_start()
        if start is None:
            return 1.0
        return self._close_ramp(self._now - start - index * MOLE_VIEW_HOLE_STAGGER_MS)

    def _home_pit_close_scale(self) -> float:
        """
        How open the mole's home pit still is. A mole that survived hops out of
        it first, so after a loss the hole only shuts once the hop is over

        :returns: how open it is, 1.0 down to 0.0
        """
        jump_t = self._jump_elapsed()
        if jump_t is not None:
            return self._close_ramp(jump_t - MOLE_VIEW_JUMP_RISE_MS - MOLE_VIEW_JUMP_HOP_MS)
        start = self._outro_start()
        if start is None:
            return 1.0
        return self._close_ramp(self._now - start)

    def _telegraph_surface(self, index: int) -> pg.Surface:
        """
        Pick the lit pit for a mole on its way up: an ordinary breathing
        telegraph, or the two-frame alarm when this is a pop the quota cannot
        survive missing

        :param index: which pop in the schedule is being telegraphed
        :returns: the shared telegraph pit to blit
        """
        danger = self.challenge.pop_mandatory(index, self._progress)
        if danger:
            pulse = cosine_pulse(self._anim_ms, MOLE_VIEW_DANGER_PULSE_MS)
            bucket = 1 if pulse >= MOLE_VIEW_DANGER_SWITCH else 0
        else:
            bucket = int(cosine_pulse(self._anim_ms, MOLE_VIEW_PULSE_MS)
                         * (MOLE_VIEW_PULSE_BUCKETS - 1))
        return pit_telegraph_surface(self._pit_rx, self._pit_ry, bucket, danger,
                                     self._signal_color(Colors.accent))

    def _damage_tier(self) -> int:
        """
        Say how badly the mole is chewed up, which climbs with the share of the
        quota already filled. It is how the sprite reports the score without a
        number anywhere near it

        :returns: tier from 0 for untouched up to TORN_MAX_TIER
        """
        required = max(self.challenge.hits_required, 1)
        steps = -(-TORN_MAX_TIER * self._progress // required)
        return max(min(steps, TORN_MAX_TIER), 0)

    def _heal_progress(self) -> float:
        """
        How far a mole that survived has got through its escape -- rising,
        hopping and knitting itself back together are measured as one ramp

        :returns: 0.0 at the verdict up to 1.0 whole again
        """
        jump_t = self._jump_elapsed()
        if jump_t is None:
            return 0.0
        total = MOLE_VIEW_JUMP_RISE_MS + MOLE_VIEW_JUMP_HOP_MS + MOLE_VIEW_REGROW_MS
        return min(max(jump_t / total, 0.0), 1.0)

    def _heal_bucket(self) -> int:
        """
        Quantise the healing into steps, so the seam moves in stages whose
        sprites are each built once and cached instead of once a frame

        :returns: step from 0 to MOLE_VIEW_HEAL_BUCKETS
        """
        return min(int(self._heal_progress() * MOLE_VIEW_HEAL_BUCKETS),
                   MOLE_VIEW_HEAL_BUCKETS)

    def _torn_victim(self, tier: int) -> pg.Surface:
        """
        Get the victim's sprite chewed up to one tier, keyed by the schedule
        and the board size so every check tears its mole its own way

        :param tier: how badly torn, 0 leaving the sprite whole
        :returns: the shared torn sprite
        """
        return torn_sprite(self._victim, (self._torn_key, self.cell_size), tier)

    def _heal_sprite(self, tier: int, bucket: int) -> pg.Surface:
        """
        Get the sprite part-way through healing -- still torn above the seam,
        whole below it -- for one step of the mole's recovery

        :param tier: how badly torn the body was
        :param bucket: step of the heal, counted from 0
        :returns: the sprite for that step, the whole one once healing is done
        """
        if tier <= 0 or bucket >= MOLE_VIEW_HEAL_BUCKETS:
            return self._victim
        if bucket <= 0:
            return self._torn_victim(tier)
        cached = self._heal_cache.get((tier, bucket))
        if cached is None:
            cached = self._build_heal_sprite(tier, bucket)
            self._heal_cache[(tier, bucket)] = cached
        return cached

    def _build_heal_sprite(self, tier: int, bucket: int) -> pg.Surface:
        """
        Build one step of the heal: the torn body down to the seam, the whole
        body below it, and the hot band laid over the join

        :param tier: how badly torn the body was
        :param bucket: step of the heal, which fixes where the seam sits
        :returns: the finished sprite, which the caller caches
        """
        torn = self._torn_victim(tier)
        w, h = torn.get_size()
        frac = 1.0 - bucket / MOLE_VIEW_HEAL_BUCKETS
        seam_y = max(round(self._seam_offset(frac, h)), 0)
        surf = pg.Surface((w, h), pg.SRCALPHA)
        if seam_y > 0:
            surf.blit(torn, (0, 0), area=pg.Rect(0, 0, w, seam_y))
        if seam_y < h:
            surf.blit(self._victim, (0, seam_y), area=pg.Rect(0, seam_y, w, h - seam_y))
        band_h = max(int(h * MOLE_VIEW_SEAM_BAND_FRAC), 3)
        surf.blit(seam_band_surface(w, band_h), (0, seam_y - band_h // 2),
                  special_flags=pg.BLEND_RGB_ADD)
        return surf

    def _victim_sprite(self) -> pg.Surface:
        """
        Pick the mole's look for this frame: healing while a survivor knits
        itself together, otherwise torn to the tier the quota has earned and
        flashed white for a moment after each hit

        :returns: the sprite to blit
        """
        tier = self._damage_tier()
        if self._jump_elapsed() is not None:
            return self._heal_sprite(tier, self._heal_bucket())
        sprite = self._torn_victim(tier)
        if self._flash_active():
            sprite = flash_sprite(sprite, (self._torn_key, self.cell_size, tier))
        return sprite

    def _flash_active(self) -> bool:
        """
        Whether a hit is still flashing the mole white, the brief tell that a
        shot connected

        :returns: True while the flash is showing
        """
        return (self._hit_flash_ms is not None
                and self._now - self._hit_flash_ms < MOLE_VIEW_HIT_FLASH_MS)

    def _squash_variant(self, sprite: pg.Surface, bucket: int) -> pg.Surface:
        """
        Squash a sprite wider and shorter for the bounce, cached per sprite and
        step so the scaling is paid for once rather than every frame

        :param sprite: the sprite to squash
        :param bucket: how hard to squash it, 0 leaving it alone
        :returns: the squashed sprite
        """
        if bucket <= 0:
            return sprite
        key = (id(sprite), bucket)
        cached = self._squash_cache.get(key)
        if cached is None:
            p = bucket / (MOLE_VIEW_SQUASH_BUCKETS - 1)
            w = max(int(sprite.get_width() * (1.0 + MOLE_VIEW_SQUASH_X * p)), 1)
            h = max(int(sprite.get_height() * (1.0 - MOLE_VIEW_SQUASH_Y * p)), 1)
            cached = pg.transform.smoothscale(sprite, (w, h))
            self._squash_cache[key] = cached
        return cached

    def _blit_victim(self, window: pg.Surface, center_px: tuple[int, int],
                     height_frac: float, group: tuple[int, int], squash: int = 0,
                     lift_px: float = 0.0, ground_dy: int | None = None,
                     lip: bool = False) -> pg.Rect | None:
        """
        Draw the mole at one pit, at whatever height it has reached. A body
        only part-way out is clipped and masked to the hole's mouth so it looks
        like it is climbing through the ground; a body fully out can be lifted
        further still for the bounce or the hop

        :param window: surface the mole is drawn onto
        :param center_px: centre of the pit in window pixels
        :param height_frac: how far out the body is, 1.0 being fully out and
            anything above that the overshoot of a bounce
        :param group: screen-shake offset in pixels
        :param squash: bounce squash step, 0 for none
        :param lift_px: extra height above the pit in pixels, used by the hop
        :param ground_dy: where the feet sit relative to the pit centre in
            pixels, None to take it from the height instead
        :param lip: True to draw the near edge of the pit over the body, so it
            stands in the hole rather than on it
        :returns: the rect the body was drawn in, or None when nothing was
        """
        if height_frac <= 0.0:
            return None
        sprite = self._squash_variant(self._victim_sprite(), squash)
        w, h = sprite.get_size()
        vib = 0.0
        if self._vibrate_ms is not None:
            vib = sakurai_vibrate(self._now, self._vibrate_ms, self._vibrate_dur_ms,
                                  self.cell_size * MOLE_VIEW_VIBRATE_AMP_FRAC)
        cx = center_px[0] + group[0] + int(vib)
        ground = self._emergence_dy(height_frac) if ground_dy is None else ground_dy
        base_y = center_px[1] + group[1] + ground
        if height_frac < 1.0:
            clip_h = max(int(h * height_frac), 1)
            rect = pg.Rect(cx - w // 2, base_y - clip_h, w, clip_h)
            window.blit(self._emerging_sprite(sprite, clip_h - ground), rect.topleft)
            return rect
        lift = int((min(height_frac, MOLE_VIEW_POP_LIFT_CAP) - 1.0) * h + lift_px)
        rect = pg.Rect(cx - w // 2, base_y - h - lift, w, h)
        window.blit(sprite, rect)
        if lip:
            front = pit_front_surface(self._pit_rx, self._pit_ry,
                                      self._signal_color(Colors.accent))
            window.blit(front, (center_px[0] + group[0] - front.get_width() // 2,
                                center_px[1] + group[1]))
        return rect

    def _emerging_sprite(self, sprite: pg.Surface, cut: int) -> pg.Surface:
        """
        Cut a climbing body off at the hole's mouth and fade its lower edge
        along that arch. One scratch surface per sprite size is reused for
        this, since it is rebuilt every frame a mole is on its way up

        :param sprite: the body being drawn
        :param cut: how far down the sprite the ground line falls, in pixels
        :returns: the scratch surface holding the masked body, valid only until
            the next call at this size
        """
        w, h = sprite.get_size()
        scratch = self._emerge_scratch.get((w, h))
        if scratch is None:
            scratch = pg.Surface((w, h), pg.SRCALPHA)
            self._emerge_scratch[(w, h)] = scratch
        scratch.fill(_CLEAR)
        scratch.blit(sprite, (0, 0), special_flags=pg.BLEND_RGBA_MAX)
        scratch.fill(_CLEAR, (0, max(cut + self._mouth_ry, 0), w, h))
        scratch.blit(emerge_mask(w, self._mouth_rx, self._mouth_ry, self._emerge_fade),
                     (0, cut - self._emerge_fade), special_flags=pg.BLEND_RGBA_MULT)
        return scratch

    def _emergence_dy(self, height_frac: float) -> int:
        """
        Sink a body that is only part-way out into the pit, so it climbs from
        the middle of the hole instead of standing on its rim

        :param height_frac: how far out the body is, 0.0 to 1.0
        :returns: pixels to drop the feet by
        """
        return int(self._pit_ry * (1.0 - min(height_frac, 1.0)))

    def _rest_ground_dy(self) -> int:
        """
        Where a mole standing on the board rests, as against one standing in
        its hole -- the offset its victory hop has to land on

        :returns: pixels below the pit centre
        """
        h = self._victim.get_height()
        return h - h // 2

    def _jump_elapsed(self) -> float | None:
        """
        How long a surviving mole has been celebrating, which is also what says
        the celebration is on at all

        :returns: milliseconds since the check was lost, or None when it was
            not lost or is not over yet
        """
        if self._landed is not False or self._committed_at is None:
            return None
        return self._now - self._committed_at

    def _toss_elapsed(self) -> float | None:
        """
        How long the beaten mole has been flying, which only starts once the
        freeze frame on the killing blow has finished

        :returns: milliseconds into the flight, or None when the check was not
            won or the freeze is still running
        """
        if not self._landed or self._committed_at is None:
            return None
        toss_t = self._now - self._committed_at - MOLE_VIEW_HITSTOP_KILL_MS
        return toss_t if toss_t >= 0.0 else None

    def _start_toss(self) -> None:
        """
        Throw the beaten mole off the board: it leaves the last pit it was hit
        in, flies away from the piece that shot it, spins a seeded way and
        sheds debris as it goes
        """
        origin = self._last_hit_px if self._last_hit_px is not None else self.center
        cell = self.cell_size
        dx, dy = self._toss_direction(origin)
        speed = cell * MOLE_VIEW_TOSS_SPEED_FRAC
        spin = seeded_floats(f"moletossspin:{self._torn_key}", 1)[0]
        self._toss = MoleToss(float(origin[0]), float(origin[1]), dx * speed,
                              dy * speed - cell * MOLE_VIEW_TOSS_UP_FRAC,
                              1.0 if spin < 0.5 else -1.0)
        self._spawn_debris(origin, "toss")

    def _toss_direction(self, origin: tuple[float, float]) -> tuple[float, float]:
        """
        Point the body's flight away from the piece that shot it, so a mole
        always leaves by the far side of the capture. With no board to measure
        against, a seeded upward arc stands in

        :param origin: where the body was hit, in window pixels
        :returns: unit direction as (x, y) in window pixels
        """
        if self._from_sq is not None and self._geom is not None:
            ax, ay = self._geom(self._from_sq)
            dx, dy = origin[0] - ax, origin[1] - ay
            dist = math.hypot(dx, dy)
            if dist > 0.0:
                return (dx / dist, dy / dist)
        low, high = MOLE_VIEW_TOSS_FALLBACK_ARC
        f = seeded_floats(f"moletossdir:{self._torn_key}", 1)
        ang = -math.pi * (low + (high - low) * f[0])
        return (math.cos(ang), math.sin(ang))

    def _toss_point(self, toss_t: float) -> tuple[float, float]:
        """
        Where the flying body has got to, on a plain gravity arc from where it
        was thrown

        :param toss_t: milliseconds into the flight
        :returns: the body's centre in window pixels
        """
        t = toss_t / 1000.0
        g = self.cell_size * MOLE_VIEW_TOSS_GRAVITY_FRAC
        return (self._toss.x0 + self._toss.vx * t,
                self._toss.y0 + self._toss.vy * t + 0.5 * g * t * t)

    @staticmethod
    def _toss_alpha(progress: float) -> int:
        """
        Fade the flying body out over the back half of its arc, so it leaves
        the board rather than simply stopping at the edge

        :param progress: how far through the flight, 0.0 to 1.0
        :returns: opacity from 255 down to 0
        """
        fade = ((progress - MOLE_VIEW_TOSS_FADE_START)
                / max(1.0 - MOLE_VIEW_TOSS_FADE_START, 0.001))
        return max(int(255 * (1.0 - max(fade, 0.0))), 0)

    def _draw_toss(self, window: pg.Surface, toss_t: float, group: tuple[int, int]) -> None:
        """
        Draw the beaten mole tumbling away after a won check, turning as it
        flies and fading out on the way

        :param window: surface the body is drawn onto
        :param toss_t: milliseconds into the flight
        :param group: screen-shake offset in pixels
        """
        if self._toss is None or toss_t >= MOLE_VIEW_TOSS_MS:
            return
        x, y = self._toss_point(toss_t)
        deg = self._toss.spin * toss_t / 1000.0 * MOLE_VIEW_TOSS_SPIN_DPS
        sprite = pg.transform.rotozoom(self._torn_victim(self._damage_tier()), deg, 1.0)
        sprite.set_alpha(self._toss_alpha(toss_t / MOLE_VIEW_TOSS_MS))
        window.blit(sprite, (int(x) + group[0] - sprite.get_width() // 2,
                             int(y) + group[1] - sprite.get_height() // 2))

    def _draw_jump(self, window: pg.Surface, jump_t: float, group: tuple[int, int]) -> None:
        """
        Draw the surviving mole's victory, body and seam together: it rises,
        hops and lands while the tears it took knit closed behind it

        :param window: surface the mole is drawn onto
        :param jump_t: milliseconds since the check was lost
        :param group: screen-shake offset in pixels
        """
        rect = self._jump_victim_rect(window, jump_t, group)
        self._draw_seam_glow(window, rect)
        self._draw_seam_sparks(window, rect)

    def _jump_victim_rect(self, window: pg.Surface, jump_t: float,
                          group: tuple[int, int]) -> pg.Rect | None:
        """
        Draw the mole at whichever stage of its victory it has reached: rising
        out of the pit, hopping over it, then squashing as it lands

        :param window: surface the mole is drawn onto
        :param jump_t: milliseconds since the check was lost
        :param group: screen-shake offset in pixels
        :returns: the rect the body was drawn in, which the seam effects hang
            off, or None when nothing was drawn
        """
        rest_dy = self._rest_ground_dy()
        if jump_t < MOLE_VIEW_JUMP_RISE_MS:
            return self._blit_victim(window, self.center,
                                     out_cubic(jump_t / MOLE_VIEW_JUMP_RISE_MS),
                                     group, lip=True)
        hop_t = jump_t - MOLE_VIEW_JUMP_RISE_MS
        if hop_t < MOLE_VIEW_JUMP_HOP_MS:
            u = hop_t / MOLE_VIEW_JUMP_HOP_MS
            lift = self.cell_size * MOLE_VIEW_JUMP_HEIGHT_FRAC * math.sin(math.pi * u)
            return self._blit_victim(window, self.center, 1.0, group, lift_px=lift,
                                     ground_dy=int(rest_dy * u))
        land_t = hop_t - MOLE_VIEW_JUMP_HOP_MS
        squash = 0
        if land_t < MOLE_VIEW_LAND_SQUASH_MS:
            p = 1.0 - land_t / MOLE_VIEW_LAND_SQUASH_MS
            squash = min(int(p * MOLE_VIEW_SQUASH_BUCKETS), MOLE_VIEW_SQUASH_BUCKETS - 1)
        return self._blit_victim(window, self.center, 1.0, group, squash=squash,
                                 ground_dy=rest_dy)

    def _healing(self) -> bool:
        """
        Whether the seam should be lit at all, which is only while a mole that
        took damage is part-way through knitting itself back together

        :returns: True while the seam is still closing
        """
        if self._jump_elapsed() is None or self._damage_tier() <= 0:
            return False
        return 0 < self._heal_bucket() < MOLE_VIEW_HEAL_BUCKETS

    def _seam_offset(self, frac: float, fallback_h: int) -> float:
        """
        Say where the seam sits down the body. It is measured across the
        sprite's visible part, so the join tracks the mole itself rather than
        the transparent padding around it

        :param frac: how far down the body, 0.0 at the top to 1.0 at the bottom
        :param fallback_h: sprite height to fall back on when the body cannot
            be measured
        :returns: offset in pixels from the top of the sprite
        """
        bbox = self._victim_bbox
        if bbox is None or bbox.height <= 0:
            return fallback_h * frac
        return bbox.top + bbox.height * frac

    def _seam_y(self, rect: pg.Rect, frac: float) -> float:
        """
        Put the seam at a real y on screen, for a body drawn in this rect

        :param rect: where the body was drawn this frame
        :param frac: how far down the body the seam sits
        :returns: the seam's y in window pixels
        """
        return rect.top + self._seam_offset(frac, self._victim.get_height())

    def _body_edge_x(self, rect: pg.Rect, side: int) -> int:
        """
        Find one side of the mole's body on screen, which is where the seam
        sparks fly out from

        :param rect: where the body was drawn this frame
        :param side: -1 for its left edge, 1 for its right
        :returns: that edge's x in window pixels
        """
        bbox = self._victim_bbox
        return rect.left + (bbox.right if side > 0 else bbox.left)

    def _draw_seam_glow(self, window: pg.Surface, rect: pg.Rect | None) -> None:
        """
        Draw the bright band riding up the seam as it closes, the loud part of
        a mole putting itself back together

        :param window: surface the glow is drawn onto
        :param rect: where the body was drawn this frame, None when it was not
        """
        if rect is None or not self._healing():
            return
        y = self._seam_y(rect, 1.0 - self._heal_bucket() / MOLE_VIEW_HEAL_BUCKETS)
        if y > rect.bottom:
            return
        bbox = self._victim_bbox
        w = max(int(bbox.width * MOLE_VIEW_SEAM_GLOW_W_FRAC), 4)
        h = max(int(self.cell_size * MOLE_VIEW_SEAM_GLOW_H_FRAC), 3)
        glow = seam_glow_surface(w, h)
        window.blit(glow, (rect.left + bbox.centerx - w // 2, int(y) - h // 2),
                    special_flags=pg.BLEND_RGB_ADD)

    def _draw_seam_sparks(self, window: pg.Surface, rect: pg.Rect | None) -> None:
        """
        Draw the sparks thrown off the closing seam, each riding out from the
        edge of the body and rising as it dies

        :param window: surface the sparks are drawn onto
        :param rect: where the body was drawn this frame, None when it was not
        """
        if rect is None:
            return
        cell = self.cell_size
        for i, (age_ms, (side, frac, speed, rise)) in enumerate(
                particle_ages(self._seam_sparks, self._now)):
            tt = age_ms / MOLE_VIEW_SPARK_MS
            if not 0.0 <= tt < 1.0:
                continue
            y = self._seam_y(rect, frac) - cell * MOLE_VIEW_SPARK_RISE_FRAC * rise * tt
            if y > rect.bottom:
                continue
            x = (self._body_edge_x(rect, side)
                 + side * cell * MOLE_VIEW_SPARK_SPEED_FRAC * speed * tt)
            r = max(int(cell * MOLE_VIEW_SPARK_R_FRAC * (1.0 - tt)), 1)
            pg.draw.circle(window, _DEBRIS_COLORS[i % len(_DEBRIS_COLORS)],
                           (int(x), int(y)), r)

    @staticmethod
    def _bounce_height(pop: MolePop, elapsed: float) -> float:
        """
        Say how far one mole is out of its hole at this moment: a quick pop up
        past its full height, then a slower fall back. The window runs a little
        past the mole dropping, matching the grace the judge allows a shot

        :param pop: the scheduled pop being drawn
        :param elapsed: milliseconds since the check started
        :returns: height as a fraction of the body, 0.0 while it is not up
        """
        up_window_ms = pop.t_down_ms - pop.t_up_ms + MOLE_GRACE_MS
        u = (elapsed - pop.t_up_ms) / up_window_ms
        if u <= 0.0 or u >= 1.0:
            return 0.0
        if u < MOLE_VIEW_POP_APEX_FRAC:
            return _POP_APEX * out_cubic(u / MOLE_VIEW_POP_APEX_FRAC)
        fall = (u - MOLE_VIEW_POP_APEX_FRAC) / (1.0 - MOLE_VIEW_POP_APEX_FRAC)
        return _POP_APEX * (1.0 - fall * fall)

    @staticmethod
    def _pop_frame(idx: int, height: float) -> tuple[int, float, int] | None:
        """
        Turn a height into everything the drawing needs for one mole -- which
        pop it is, how far out, and how far the bounce has squashed it

        :param idx: which pop in the schedule
        :param height: how far out of the hole the body is
        :returns: (pop index, height, squash step), or None when the mole is
            not up
        """
        if height <= 0.0:
            return None
        bucket = int((1.0 - height / _POP_APEX) * MOLE_VIEW_SQUASH_BUCKETS)
        return idx, height, min(bucket, MOLE_VIEW_SQUASH_BUCKETS - 1)

    def _duck_pop(self, idx: int, elapsed: float) -> None:
        """
        Send a mole that has just been hit back down from wherever it stood,
        and remember it as the one already taken so no shot can claim it twice

        :param idx: which pop was hit
        :param elapsed: milliseconds into the check the shot landed at
        """
        self._last_hit_pop = idx
        self._last_hit_anim_ms = self._anim_ms
        self._last_hit_height = self._bounce_height(self.challenge.pops[idx], elapsed)

    def _render_pop(self, elapsed: float) -> tuple[int, float, int] | None:
        """
        Work out which mole to draw this frame and how it looks: the most
        recent one to have come up, either riding its bounce or dropping away
        from where it was hit

        :param elapsed: milliseconds since the check started
        :returns: (pop index, height, squash step), or None when there is no
            mole to draw
        """
        idx = None
        for i, pop in enumerate(self.challenge.pops):
            if pop.t_up_ms <= elapsed:
                idx = i
        if idx is None:
            return None
        if idx == self._last_hit_pop and self._last_hit_anim_ms is not None:
            duck = (self._anim_ms - self._last_hit_anim_ms) / MOLE_VIEW_RETREAT_MS
            return self._pop_frame(idx, self._last_hit_height * (1.0 - duck))
        return self._pop_frame(idx, self._bounce_height(self.challenge.pops[idx], elapsed))

    def _draw_victim(self, window: pg.Surface, elapsed: float,
                     group: tuple[int, int]) -> None:
        """
        Draw the mole in whichever life it is living: flying off after a check
        it lost, celebrating one it survived, dropping into its home pit as the
        check opens, or up in a pit taking a bounce

        :param window: surface the mole is drawn onto
        :param elapsed: milliseconds since the check started
        :param group: screen-shake offset in pixels
        """
        if self._victim is None:
            return
        toss_t = self._toss_elapsed()
        if toss_t is not None:
            self._draw_toss(window, toss_t, group)
            return
        jump_t = self._jump_elapsed()
        if jump_t is not None:
            self._draw_jump(window, jump_t, group)
            return
        if elapsed < self._intro_ms:
            self._blit_victim(window, self.center, 1.0 - elapsed / self._intro_ms, group,
                              lip=True)
            return
        rendered = self._render_pop(elapsed)
        if rendered is None:
            return
        idx, height_frac, squash = rendered
        hole = self.challenge.pops[idx].hole
        if hole >= len(self._hole_px):
            return
        self._blit_victim(window, self._hole_px[hole], height_frac, group, squash, lip=True)

    def _draw_burst(self, window: pg.Surface,
                    items: list[tuple[float, float, float, tuple[float, ...]]],
                    life_ms: float, count: int, r_frac: float, speed_frac: float,
                    jitter: tuple[float, float], gravity_frac: float,
                    color_fn: Callable[[float, int], pg.Color]) -> None:
        """
        Draw one family of particle bursts, working every mote out from its
        burst's seeded numbers as it is drawn. Dust and debris are the same
        code with different speeds, gravity and colours

        :param window: surface the motes are drawn onto
        :param items: the live bursts to draw
        :param life_ms: how long one burst lasts, in milliseconds
        :param count: how many motes each burst has
        :param r_frac: mote radius as a share of one board cell
        :param speed_frac: how fast they fly, in cells per second
        :param jitter: (base, span) the seeded speed factor is drawn between
        :param gravity_frac: downward pull in cells per second squared
        :param color_fn: picks a mote's colour from the burst's age and the
            mote's index
        """
        cell = self.cell_size
        g = cell * gravity_frac
        speed_base, speed_span = jitter
        for age_ms, (x, y, floats) in particle_ages(items, self._now):
            tt = age_ms / life_ms
            if not 0.0 <= tt < 1.0:
                continue
            t = age_ms / 1000.0
            r = max(int(cell * r_frac * (1.0 - tt)), 1)
            for j in range(count):
                ang = floats[j * 2] * 2.0 * math.pi
                speed = cell * speed_frac * (speed_base + speed_span * floats[j * 2 + 1])
                px = x + math.cos(ang) * speed * t
                py = y + math.sin(ang) * speed * t + 0.5 * g * t * t
                pg.draw.circle(window, color_fn(tt, j), (int(px), int(py)), r)

    def _draw_puffs(self, window: pg.Surface) -> None:
        """
        Draw the dust still hanging where shots hit nothing, which is what a
        whiff leaves on the board

        :param window: surface the dust is drawn onto
        """
        self._draw_burst(window, self._puffs, MOLE_VIEW_PUFF_MS, MOLE_VIEW_PUFF_COUNT,
                         MOLE_VIEW_PUFF_R_FRAC, MOLE_VIEW_PUFF_SPEED_FRAC,
                         MOLE_VIEW_PUFF_SPEED_JITTER, 0.0, _puff_color)

    def _draw_debris(self, window: pg.Surface) -> None:
        """
        Draw the chunks flying off moles that have been hit, which fall away
        under gravity rather than hanging like dust

        :param window: surface the debris is drawn onto
        """
        self._draw_burst(window, self._debris, MOLE_VIEW_DEBRIS_MS, MOLE_VIEW_DEBRIS_COUNT,
                         MOLE_VIEW_DEBRIS_R_FRAC, MOLE_VIEW_DEBRIS_SPEED_FRAC,
                         MOLE_VIEW_DEBRIS_SPEED_JITTER, MOLE_VIEW_DEBRIS_GRAVITY_FRAC,
                         _debris_color)

    def _commit_fade_alpha(self, delay_ms: float, span_ms: float) -> int:
        """
        Fade a piece of the check's furniture away once the verdict is in, so
        badges and casings clear off the board instead of sitting through the
        outro

        :param delay_ms: how long after the verdict the fade waits, in
            milliseconds
        :param span_ms: how long the fade itself takes, in milliseconds
        :returns: opacity from 0 to 255, staying full while the check is live
        """
        if self._committed_at is None:
            return 255
        fading = self._now - self._committed_at - delay_ms
        if fading <= 0.0:
            return 255
        return max(int(255 * (1.0 - fading / span_ms)), 0)

    def _draw_casings(self, window: pg.Surface) -> None:
        """
        Draw the spent shells: each flies its own arc, tumbles in bucketed
        steps, rests where it falls and then fades, with the verdict clearing
        the whole floor early

        :param window: surface the casings are drawn onto
        """
        cell = self.cell_size
        w = max(int(cell * MOLE_VIEW_CASING_W_FRAC), 3)
        h = max(int(cell * MOLE_VIEW_CASING_H_FRAC), 2)
        buckets = 360 // MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        cap = self._commit_fade_alpha(0.0, MOLE_VIEW_CASING_COMMIT_FADE_MS)
        for spawn_ms, x0, y0, vx, vy, g, t_land, spin in self._casings:
            t_ms = self._now - spawn_ms
            t = min(t_ms / 1000.0, t_land)
            x = x0 + vx * t
            y = y0 + vy * t + 0.5 * g * t * t
            deg = spin * t * MOLE_VIEW_CASING_SPIN_DPS
            bucket = int(deg / MOLE_VIEW_CASING_SPIN_BUCKET_DEG) % buckets
            surf = casing_rotated(w, h, bucket)
            alpha = min(self._casing_alpha(t_ms - t_land * 1000.0), cap)
            if alpha <= 0:
                continue
            _blit_alpha(window, surf, (int(x) - surf.get_width() // 2,
                                       int(y) - surf.get_height() // 2), alpha)

    @staticmethod
    def _casing_alpha(ground_ms: float) -> int:
        """
        Fade a spent shell out after it has lain on the board a while, so a
        long check does not end up carpeted in brass

        :param ground_ms: milliseconds since it landed
        :returns: opacity from 255 down to 0
        """
        fading = ground_ms - MOLE_VIEW_CASING_REST_MS
        if fading <= 0.0:
            return 255
        return max(int(255 * (1.0 - fading / MOLE_VIEW_CASING_FADE_MS)), 0)

    def _draw_impacts(self, window: pg.Surface) -> None:
        """
        Draw the rings spreading where the opponent's shots landed, the
        mirror's stand-in for the muzzle flash it cannot see

        :param window: surface the rings are drawn onto
        """
        lw = max(self._cross_lw, 1)
        for age_ms, (x, y) in particle_ages(self._impacts, self._now):
            tt = age_ms / MOLE_VIEW_IMPACT_MS
            if not 0.0 <= tt < 1.0:
                continue
            r = max(int(self.cell_size * MOLE_VIEW_IMPACT_R_FRAC * tt), 2)
            pg.draw.circle(window, _IMPACT_COLOR, (int(x), int(y)), r, lw)

    def _draw_win_pop(self, window: pg.Surface, group: tuple[int, int]) -> None:
        """
        Draw the burst thrown by the hit that filled the quota, where that last
        mole was standing

        :param window: surface the burst is drawn onto
        :param group: screen-shake offset in pixels
        """
        if self._win_ms is None or self._now - self._win_ms >= MOLE_VIEW_WIN_POP_MS:
            return
        r = max(int(self.cell_size * MOLE_VIEW_WIN_POP_R_FRAC), 8)
        px = self._last_hit_px if self._last_hit_px is not None else self.center
        window.blit(win_pop_surface(r), (int(px[0]) - r + group[0],
                                         int(px[1]) - r + group[1]),
                    special_flags=pg.BLEND_RGB_ADD)

    def _draw_muzzle(self, window: pg.Surface) -> None:
        """
        Draw the muzzle flash under the crosshair for the moment after a shot,
        which is what makes the click feel like a trigger

        :param window: surface the flash is drawn onto
        """
        if self._flash_ms is None or self._now - self._flash_ms >= MOLE_VIEW_MUZZLE_MS:
            return
        r = max(int(self.cell_size * MOLE_VIEW_MUZZLE_FRAC), 4)
        window.blit(muzzle_surface(r), (int(self._flash_px[0]) - r,
                                        int(self._flash_px[1]) - r),
                    special_flags=pg.BLEND_RGB_ADD)

    def _crosshair_fade(self) -> float:
        """
        Fade the crosshair away as soon as the check is decided, since there is
        nothing left to aim at

        :returns: 1.0 while the check is live, falling to 0.0
        """
        if self._committed_at is None:
            return 1.0
        return max(1.0 - (self._now - self._committed_at) / MOLE_VIEW_CROSS_OUT_MS, 0.0)

    def _draw_crosshair(self, window: pg.Surface) -> None:
        """
        Draw the sight the player aims with, standing in for the hidden mouse
        pointer. It kicks upward on each shot and blooms open while the recoil
        lockout refuses another one, which is how the gun says wait

        :param window: surface the sight is drawn onto
        """
        fade = self._crosshair_fade()
        if fade <= 0.0:
            return
        mx, my = pg.mouse.get_pos()
        if self._flash_ms is not None:
            t = self._now - self._flash_ms
            if t < MOLE_VIEW_KICK_MS:
                my -= int(self._kick_amp * (1.0 - t / MOLE_VIEW_KICK_MS))
        bloom = 0.0
        if self._last_shot_ms is not None:
            t = self._now - self._last_shot_ms
            if t < MOLE_RECOIL_LOCKOUT_MS:
                bloom = 1.0 - t / MOLE_RECOIL_LOCKOUT_MS
        if fade >= 1.0:
            glow = cross_glow_surface(
                max(int(self.cell_size * MOLE_VIEW_CROSS_GLOW_FRAC), 6))
            window.blit(glow, (mx - glow.get_width() // 2, my - glow.get_height() // 2),
                        special_flags=pg.BLEND_RGB_ADD)
        surf = crosshair_surface(self._cross_arm, self._cross_gap, self._cross_lw,
                                 round(bloom * MOLE_VIEW_BLOOM_BUCKETS),
                                 round((1.0 - fade) * MOLE_VIEW_CROSS_OUT_BUCKETS))
        _blit_alpha(window, surf,
                    (mx - surf.get_width() // 2, my - surf.get_height() // 2),
                    int(255 * fade))

    def _draw_hitboxes(self, window: pg.Surface, elapsed: float) -> None:
        """
        Outline the ovals a shot has to land inside to count, the development
        overlay behind CHESS_DEBUG_HITBOX. They are built from the same
        board-space fractions the judge tests against, which is what makes them
        worth looking at

        :param window: surface the outlines are drawn onto
        :param elapsed: milliseconds since the check started
        """
        if self._affine is None:
            return
        up = self.challenge.pop_up_at(elapsed)
        live_hole = self.challenge.pops[up].hole if up is not None else None
        rx = abs(self._affine[2]) * MOLE_HITBOX_RX_FRAC
        ry = abs(self._affine[3]) * MOLE_HITBOX_RY_FRAC
        lift = hitbox_lift(self._affine[3] < 0)
        for i, (row, col) in enumerate(self._hole_squares):
            if elapsed - i * MOLE_VIEW_HOLE_STAGGER_MS <= 0.0:
                continue
            px = self._board_to_px(row + 0.5 + lift, col + 0.5)
            rect = pg.Rect(int(px[0] - rx), int(px[1] - ry), int(2 * rx), int(2 * ry))
            hot = i == live_hole
            pg.draw.ellipse(window, _HITBOX_ACTIVE_COLOR if hot else _HITBOX_COLOR, rect,
                            MOLE_VIEW_HITBOX_ACTIVE_LW if hot else MOLE_VIEW_HITBOX_LW)

    def _pip_badge(self, index: int) -> pg.Surface:
        """
        Draw one quota pip, lit once that many moles have been hit. The row
        says how much shooting the prize costs -- three pips for a pawn, four
        for a knight, bishop or rook, five for a queen

        :param index: which pip in the row, counted from the left
        :returns: the shared pip for that state
        """
        if index < min(self._progress, self.challenge.hits_required):
            fill = self._signal_color(Colors.accent)
            border = self._signal_color(Colors.accent_hi)
        else:
            fill, border = Colors.surface, Colors.border_strong
        radius = max(self._pip_h // MOLE_VIEW_PIP_RADIUS_DIV, 2)
        return rounded_rect_surface((self._pip_w, self._pip_h), radius, fill,
                                    border=border, border_width=1)

    def _strike_badge(self, index: int) -> pg.Surface:
        """
        Draw one whiff pip: an empty ring while that wild shot is still spare,
        crossed out once it has been spent. There are MOLE_MAX_WHIFFS of them,
        and the check is lost the moment the last one is used

        :param index: which pip in the row, counted from the left
        :returns: the shared pip for that state
        """
        return strike_pip_surface(
            self._strike_size, index < min(self._miss_count, MOLE_MAX_WHIFFS),
            lw_frac=MOLE_VIEW_CROSS_STRIKE_LW_FRAC,
            pad_frac=MOLE_VIEW_CROSS_STRIKE_PAD_FRAC,
            ring_lw_frac=MOLE_VIEW_CROSS_STRIKE_RING_LW_FRAC)

    def _draw_badge_row(self, window: pg.Surface, group: tuple[int, int],
                        anchor: tuple[int, int], count: int, size: int, gap: int,
                        offset_frac: float, sprite_fn: Callable[[int], pg.Surface],
                        alpha: int) -> None:
        """
        Draw one row of badges centred under a square, shared by the quota pips
        and the whiff pips so both rows sit and fade the same way

        :param window: surface the row is drawn onto
        :param group: screen-shake offset in pixels
        :param anchor: centre of the square the row hangs under, in window
            pixels
        :param count: how many badges the row has
        :param size: badge width in pixels
        :param gap: space between badges in pixels
        :param offset_frac: how far below the anchor the row sits, as a share
            of one board cell
        :param sprite_fn: draws the badge at one index
        :param alpha: opacity from 0 to 255 for the whole row
        """
        total = count * size + (count - 1) * gap
        x = anchor[0] - total // 2 + group[0]
        y = anchor[1] + int(self.cell_size * offset_frac) + group[1]
        for i in range(count):
            _blit_alpha(window, sprite_fn(i), (x + i * (size + gap), y), alpha)

    def _draw_badges(self, window: pg.Surface, group: tuple[int, int]) -> None:
        """
        Draw both scores the player needs at a glance: the quota pips under the
        capture, and the whiffs left beside the piece doing the shooting. Both
        fade away once the check is decided

        :param window: surface the badges are drawn onto
        :param group: screen-shake offset in pixels
        """
        alpha = self._commit_fade_alpha(MOLE_VIEW_PIP_FADE_DELAY_MS, MOLE_VIEW_PIP_FADE_MS)
        if alpha <= 0:
            return
        self._draw_badge_row(window, group, self.center, self.challenge.hits_required,
                             self._pip_w, self._pip_gap, MOLE_VIEW_PIP_OFFSET_FRAC,
                             self._pip_badge, alpha)
        if self._geom is None or self._from_sq is None:
            return
        self._draw_badge_row(window, group, self._geom(self._from_sq), MOLE_MAX_WHIFFS,
                             self._strike_size, self._strike_gap,
                             MOLE_VIEW_CROSS_STRIKE_OFFSET_FRAC, self._strike_badge, alpha)
