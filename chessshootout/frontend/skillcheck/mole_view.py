import math

import pygame as pg

from chessshootout.backend.utils import Square
from chessshootout.frontend.board.speech_bubble import SpeechBubble
from chessshootout.frontend.skillcheck.controller import (
    SkillCheckController, SKILLCHECK_RESULT_HOLD_MS)
from chessshootout.frontend.skillcheck.juice import (
    Trauma, Hitstop, sakurai_vibrate, ease_out_back, torn_sprite, flash_sprite)
from chessshootout.frontend.visual.cache import new_size_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import cosine_pulse, rounded_rect_surface, supersample
from chessshootout.skillcheck.mole import MOLE_INTRO_MS, MOLE_RECOIL_LOCKOUT_MS
from chessshootout.skillcheck.rng import seeded_floats

MOLE_VIEW_RESULT_HOLD_MS = 500
MOLE_VIEW_FAIL_FADE_MS = 300
MOLE_VIEW_FAIL_DEADPAN_MS = 500
MOLE_VIEW_FAIL_HOLD_MS = 2200
MOLE_VIEW_HOLE_STAGGER_MS = 40.0
MOLE_VIEW_HOLE_OPEN_MS = 160.0
MOLE_VIEW_RISE_MS = 140.0
MOLE_VIEW_RETREAT_MS = 160.0
MOLE_VIEW_POP_HEIGHT_FRAC = 0.9
MOLE_VIEW_POP_LIFT_CAP = 1.2
MOLE_VIEW_PIT_RX_FRAC = 0.42
MOLE_VIEW_PIT_RY_FRAC = 0.24
MOLE_VIEW_PIT_RIM_FRAC = 0.14
MOLE_VIEW_PIT_GLOW_ALPHA = 60
MOLE_VIEW_PULSE_MS = 420
MOLE_VIEW_PULSE_BUCKETS = 6
MOLE_VIEW_TELE_WHITE_MIN = 0.35
MOLE_VIEW_SQUASH_BUCKETS = 4
MOLE_VIEW_SQUASH_X = 0.28
MOLE_VIEW_SQUASH_Y = 0.38
MOLE_VIEW_CROSS_ARM_FRAC = 0.16
MOLE_VIEW_CROSS_GAP_FRAC = 0.05
MOLE_VIEW_CROSS_RING_FRAC = 0.09
MOLE_VIEW_CROSS_LW_FRAC = 0.024
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
MOLE_VIEW_PIP_W_FRAC = 0.11
MOLE_VIEW_PIP_H_FRAC = 0.20
MOLE_VIEW_PIP_GAP_FRAC = 0.07
MOLE_VIEW_PIP_OFFSET_FRAC = 0.66
MOLE_VIEW_CASING_W_FRAC = 0.10
MOLE_VIEW_CASING_H_FRAC = 0.05
MOLE_VIEW_CASING_VX_FRAC = 1.4
MOLE_VIEW_CASING_UP_FRAC = 1.8
MOLE_VIEW_CASING_GRAVITY_FRAC = 7.0
MOLE_VIEW_CASING_FALL_FRAC = 0.7
MOLE_VIEW_CASING_SPIN_DPS = 520.0
MOLE_VIEW_CASING_SPIN_BUCKET_DEG = 20
MOLE_VIEW_PUFF_MS = 320.0
MOLE_VIEW_PUFF_COUNT = 5
MOLE_VIEW_PUFF_R_FRAC = 0.09
MOLE_VIEW_PUFF_SPEED_FRAC = 0.9
MOLE_VIEW_DEBRIS_MS = 420.0
MOLE_VIEW_DEBRIS_COUNT = 7
MOLE_VIEW_DEBRIS_R_FRAC = 0.05
MOLE_VIEW_DEBRIS_SPEED_FRAC = 1.6
MOLE_VIEW_DEBRIS_GRAVITY_FRAC = 4.0
MOLE_VIEW_IMPACT_MS = 260.0
MOLE_VIEW_IMPACT_R_FRAC = 0.12
MOLE_VIEW_TAUNT_ANCHOR_CELL = 99.0
MOLE_VIEW_TAUNTS = ("missed me", "lol", "nice aim", "rip", "too slow")

_PIT_DARK = pg.Color(Colors.well_deep)
_CROSS_COLOR = pg.Color(Colors.text)
_IMPACT_COLOR = pg.Color(Colors.spectate)
_DUST_COLORS = (pg.Color(Colors.text_dim), pg.Color(Colors.text_muted), pg.Color(Colors.border))
_DEBRIS_COLORS = (pg.Color(Colors.amber_hi), pg.Color(Colors.accent_hi), pg.Color(Colors.amber))

_MOLE_STATIC_CACHE = new_size_cache()


def _pit_render(rim_color, glow_alpha):
    def render(surf, k):
        w, h = surf.get_size()
        rim = pg.Color(rim_color)
        glow = pg.Color(rim.r, rim.g, rim.b, glow_alpha)
        pg.draw.ellipse(surf, glow, pg.Rect(0, 0, w, h))
        inset_x, inset_y = int(w * 0.06), int(h * 0.06)
        outer = pg.Rect(inset_x, inset_y, w - 2 * inset_x, h - 2 * inset_y)
        pg.draw.ellipse(surf, rim, outer)
        rim_w = max(int(outer.height * MOLE_VIEW_PIT_RIM_FRAC), 1)
        pg.draw.ellipse(surf, _PIT_DARK, outer.inflate(-2 * rim_w, -2 * rim_w))
    return render


def _pit_surface(rx, ry):
    def build():
        return supersample((2 * rx, 2 * ry),
                           _pit_render(Colors.accent, MOLE_VIEW_PIT_GLOW_ALPHA))
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit", rx, ry), build)


def _pit_telegraph_surface(rx, ry, bucket):
    def build():
        frac = bucket / (MOLE_VIEW_PULSE_BUCKETS - 1)
        blend = MOLE_VIEW_TELE_WHITE_MIN + (1.0 - MOLE_VIEW_TELE_WHITE_MIN) * frac
        rim = pg.Color(Colors.accent).lerp(pg.Color(Colors.text), blend)
        alpha = int(MOLE_VIEW_PIT_GLOW_ALPHA + (255 - MOLE_VIEW_PIT_GLOW_ALPHA) * frac * 0.5)
        return supersample((2 * rx, 2 * ry), _pit_render(rim, alpha))
    return memoized_surface(_MOLE_STATIC_CACHE, ("pit_tele", rx, ry, bucket), build)


def _muzzle_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r))
        hot = pg.Color(Colors.amber_hi)
        for i in range(r, 0, -1):
            edge = i / r
            col = pg.Color(int(hot.r * (1.0 - edge) ** 2), int(hot.g * (1.0 - edge) ** 2),
                           int(hot.b * (1.0 - edge) ** 2))
            pg.draw.circle(surf, col, (r, r), i)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pg.draw.line(surf, hot, (r, r), (r + dx * r, r + dy * r), max(r // 6, 1))
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("muzzle", r), build)


def _win_pop_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r))
        warm = pg.Color(Colors.amber)
        for i in range(r, 0, -1):
            edge = i / r
            gain = (1.0 - edge) ** 2 * 0.85
            pg.draw.circle(surf, (int(warm.r * gain), int(warm.g * gain), int(warm.b * gain)),
                           (r, r), i)
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("winpop", r), build)


def _casing_surface(w, h):
    def build():
        surf = pg.Surface((w, h), pg.SRCALPHA)
        surf.fill(pg.Color(Colors.amber))
        pg.draw.rect(surf, pg.Color(Colors.amber_hi), pg.Rect(0, 0, max(w // 4, 1), h))
        return surf
    return memoized_surface(_MOLE_STATIC_CACHE, ("casing", w, h), build)


def _casing_rotated(w, h, bucket):
    def build():
        base = _casing_surface(w, h)
        deg = bucket * MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        return base if deg == 0 else pg.transform.rotate(base, deg)
    return memoized_surface(_MOLE_STATIC_CACHE, ("casing_rot", w, h, bucket), build)


class MoleController(SkillCheckController):

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms, *, hole_squares=None,
                 px_to_board=None, victim_surface=None, board_rect=None, geom=None,
                 from_sq=None, victim_sq=None, attacker_type=None, shot_sound=None,
                 on_shot=None, miss_count=0, progress=0, passive=False, audio=None):
        self.challenge = challenge
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self._hole_squares = tuple(hole_squares) if hole_squares is not None else ()
        self._px_to_board = px_to_board
        self._geom = geom
        self._shot_sound = shot_sound
        self._on_shot = on_shot
        self._passive = passive
        self._online = on_shot is not None or passive
        self._audio = audio
        self._victim_orig = victim_surface
        self._victim_orig_cell = max(int(cell_rect.width), 1)
        self._victim = victim_surface
        self._victim_cache = {}
        self._squash_cache = {}
        self._owned = {}
        self._board_rect = None if board_rect is None else pg.Rect(board_rect)
        self._progress = progress
        self._last_hit_pop = -1
        self._last_hit_anim_ms = None
        self._last_hit_px = None
        self._hit_flash_ms = None
        self._vibrate_ms = None
        self._vibrate_dur_ms = 0.0
        self._committed_at = None
        self._resolved_at = None
        self._landed = None
        self._win_ms = None
        self._last_shot_ms = None
        self._shot_count = 0
        self._flash_ms = None
        self._flash_px = cell_rect.center
        self._next_telegraph = 0
        self._next_pop = 0
        self._trauma = Trauma()
        self._hitstop = Hitstop()
        self._anim_ms = float(now_ms)
        self._casings = []
        self._puffs = []
        self._debris = []
        self._impacts = []
        self._taunt = SpeechBubble()
        self._taunt_shown = False
        first = challenge.pops[0]
        self._intro_ms = max(min(MOLE_INTRO_MS, first.t_telegraph_ms), 1.0)
        self._taunt_text = self._pick_taunt()
        self._cursor_hidden = False
        if not passive:
            pg.mouse.set_visible(False)
            self._cursor_hidden = True
        self._apply_geometry(cell_rect)
        self._cue("play_mole_fall")

    def _pick_taunt(self):
        key = "taunt:{}:{}:{}:{}".format(
            self.challenge.hole_count, self.challenge.hits_required,
            int(self.challenge.pops[0].t_up_ms), int(self.challenge.deadline_ms))
        roll = seeded_floats(key, 1)[0]
        return MOLE_VIEW_TAUNTS[int(roll * len(MOLE_VIEW_TAUNTS)) % len(MOLE_VIEW_TAUNTS)]

    def _apply_geometry(self, cell_rect):
        cell = max(int(cell_rect.width), 1)
        self.center = cell_rect.center
        self.cell_size = cell
        self._anchor_rect = pg.Rect(cell_rect)
        if self._victim_orig is not None:
            self._victim = self._scaled_victim(cell)
        self._affine = self._derive_affine()
        self._hole_px = self._hole_centers()
        self._pit_rx = max(int(cell * MOLE_VIEW_PIT_RX_FRAC), 6)
        self._pit_ry = max(int(cell * MOLE_VIEW_PIT_RY_FRAC), 4)
        self._cross_arm = max(int(cell * MOLE_VIEW_CROSS_ARM_FRAC), 4)
        self._cross_gap = max(int(cell * MOLE_VIEW_CROSS_GAP_FRAC), 2)
        self._cross_ring = max(int(cell * MOLE_VIEW_CROSS_RING_FRAC), 3)
        self._cross_lw = max(round(cell * MOLE_VIEW_CROSS_LW_FRAC), 1)
        self._kick_amp = cell * MOLE_VIEW_KICK_FRAC
        self._pip_w = max(int(cell * MOLE_VIEW_PIP_W_FRAC), 4)
        self._pip_h = max(int(cell * MOLE_VIEW_PIP_H_FRAC), 6)
        self._pip_gap = max(int(cell * MOLE_VIEW_PIP_GAP_FRAC), 2)
        self._squash_cache.clear()
        self._owned.clear()

    def _scaled_victim(self, new_cell):
        if new_cell == self._victim_orig_cell:
            return self._victim_orig
        cached = self._victim_cache.get(new_cell)
        if cached is not None:
            return cached
        scale = new_cell / self._victim_orig_cell
        w = max(round(self._victim_orig.get_width() * scale), 1)
        h = max(round(self._victim_orig.get_height() * scale), 1)
        surf = pg.transform.smoothscale(self._victim_orig, (w, h))
        self._victim_cache[new_cell] = surf
        return surf

    def _derive_affine(self):
        if self._geom is None:
            return None
        x0, y0 = self._geom(Square(0, 0))
        x1, y1 = self._geom(Square(1, 1))
        dx, dy = x1 - x0, y1 - y0
        if dx == 0 or dy == 0:
            return None
        return (float(x0), float(y0), float(dx), float(dy))

    def _hole_centers(self):
        if self._geom is not None:
            return tuple(self._geom(Square(row, col)) for row, col in self._hole_squares)
        n = len(self._hole_squares)
        spread = self.cell_size * 1.2
        return tuple((int(self.center[0] + (i - (n - 1) / 2.0) * spread), self.center[1])
                     for i in range(n))

    def _board_to_px(self, row_f, col_f):
        if self._affine is None:
            return None
        x0, y0, dx, dy = self._affine
        return (x0 + (col_f - 0.5) * dx, y0 + (row_f - 0.5) * dy)

    def _shot_target(self, pos):
        if self._px_to_board is not None:
            row_f, col_f = self._px_to_board(pos)
            return (float(row_f), float(col_f))
        if self._affine is not None:
            x0, y0, dx, dy = self._affine
            return ((pos[1] - y0) / dy + 0.5, (pos[0] - x0) / dx + 0.5)
        return (-1.0, -1.0)

    def set_board_rect(self, board_rect):
        self._board_rect = None if board_rect is None else pg.Rect(board_rect)

    def relayout(self, cell_rect):
        self._apply_geometry(cell_rect)

    def handle_event(self, event):
        if self._passive:
            return False
        if self._committed_at is not None:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._fire(event.pos)
            return True
        if event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
            self._fire(pg.mouse.get_pos())
            return True
        return False

    def _fire(self, pos):
        self._flash_ms = self._now
        self._flash_px = pos
        if (self._last_shot_ms is not None
                and self._now - self._last_shot_ms < MOLE_RECOIL_LOCKOUT_MS):
            return
        self._last_shot_ms = self._now
        if self._shot_sound is not None:
            self._shot_sound()
        elapsed = self._now - self.start_ms
        target = self._shot_target(pos)
        if self._online:
            self._on_shot(elapsed, target=target)
        if self.challenge.hit_at(elapsed, target[0], target[1], self._hole_squares,
                                 self._last_hit_pop):
            self._register_hit(elapsed)
        else:
            self._spawn_puffs(pos)
            self._cue("play_whiff_ricochet")
        self._spawn_casing(pos)

    def _register_hit(self, elapsed):
        idx = self.challenge.pop_up_at(elapsed)
        self._last_hit_pop = idx
        self._last_hit_anim_ms = self._anim_ms
        hole = self.challenge.pops[idx].hole
        if hole < len(self._hole_px):
            self._last_hit_px = self._hole_px[hole]
        self._progress += 1
        kill = self._progress >= self.challenge.hits_required
        self._hit_juice(kill)
        self._cue("play_whack_hit")
        if kill:
            self._cue("play_whack_kill")
            if not self._online:
                self._commit(True)

    def _hit_juice(self, kill):
        self._trauma.add(MOLE_VIEW_TRAUMA_PER_HIT)
        dur = MOLE_VIEW_HITSTOP_KILL_MS if kill else MOLE_VIEW_HITSTOP_HIT_MS
        self._hitstop.trigger(self._now, dur)
        self._vibrate_ms = self._now
        self._vibrate_dur_ms = dur
        self._hit_flash_ms = self._now
        self._spawn_debris(self._last_hit_px if self._last_hit_px is not None else self.center)

    def _spawn_casing(self, pos):
        self._shot_count += 1
        cell = self.cell_size
        f = seeded_floats("molecasing:{}".format(self._shot_count), 3)
        vx = (f[0] * 2.0 - 1.0) * cell * MOLE_VIEW_CASING_VX_FRAC
        vy = -cell * MOLE_VIEW_CASING_UP_FRAC * (0.7 + 0.6 * f[1])
        g = cell * MOLE_VIEW_CASING_GRAVITY_FRAC
        fall = cell * MOLE_VIEW_CASING_FALL_FRAC
        t_land = (-vy + math.sqrt(vy * vy + 2.0 * g * fall)) / g
        spin = 1.0 if f[2] < 0.5 else -1.0
        self._casings.append((self._now, float(pos[0]), float(pos[1]), vx, vy, g, t_land, spin))

    def _spawn_puffs(self, pos):
        f = seeded_floats("molepuff:{}".format(self._shot_count + 1),
                          MOLE_VIEW_PUFF_COUNT * 2)
        self._puffs.append((self._now, float(pos[0]), float(pos[1]), f))

    def _spawn_debris(self, pos):
        f = seeded_floats("moledebris:{}".format(self._shot_count + 1),
                          MOLE_VIEW_DEBRIS_COUNT * 2)
        self._debris.append((self._now, float(pos[0]), float(pos[1]), f))

    def spectate_shot(self, elapsed_ms, miss_count, won, progress=0, direction=None,
                      target=None):
        px = None
        if target is not None:
            px = self._board_to_px(target[0], target[1])
        if px is not None:
            self._impacts.append((self._now, px[0], px[1]))
            self._spawn_casing(px)
        if progress > self._progress:
            self._progress = progress
            if px is not None:
                self._last_hit_px = px
            self._hit_juice(progress >= self.challenge.hits_required)
        elif px is not None and not won:
            self._spawn_puffs(px)

    def resolve(self, won):
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        if won:
            self._win_ms = self._now
        self._emit_verdict()
        self._restore_cursor()

    def _commit(self, landed):
        self._landed = landed
        self._committed_at = self._now
        if landed:
            self._win_ms = self._now
        self._emit_verdict()
        self._restore_cursor()

    def close(self):
        self._restore_cursor()

    def _restore_cursor(self):
        if self._cursor_hidden:
            pg.mouse.set_visible(True)
            self._cursor_hidden = False

    def update(self, now_ms):
        dt = now_ms - self._now
        self._now = now_ms
        self._trauma.update(now_ms)
        if dt > 0 and not self._hitstop.frozen(now_ms):
            self._anim_ms += dt
        while self._puffs and now_ms - self._puffs[0][0] >= MOLE_VIEW_PUFF_MS:
            self._puffs.pop(0)
        while self._debris and now_ms - self._debris[0][0] >= MOLE_VIEW_DEBRIS_MS:
            self._debris.pop(0)
        while self._impacts and now_ms - self._impacts[0][0] >= MOLE_VIEW_IMPACT_MS:
            self._impacts.pop(0)
        if self._committed_at is None:
            elapsed = now_ms - self.start_ms
            self._cue_schedule(elapsed)
            if not self._online and (elapsed >= self.deadline_ms
                                     or self.challenge.quota_unreachable(
                                         elapsed, self._progress, self._last_hit_pop)):
                self._commit(False)
        if (self._landed is False and self._committed_at is not None
                and not self._taunt_shown
                and now_ms - self._committed_at
                >= MOLE_VIEW_FAIL_FADE_MS + MOLE_VIEW_FAIL_DEADPAN_MS):
            self._taunt_shown = True
            self._cue("play_mole_taunt")
            self._taunt.show(self._taunt_text, now_ms)

    def _cue_schedule(self, elapsed):
        pops = self.challenge.pops
        while (self._next_telegraph < len(pops)
               and elapsed >= pops[self._next_telegraph].t_telegraph_ms):
            self._next_telegraph += 1
            self._cue("play_mole_telegraph")
        while self._next_pop < len(pops) and elapsed >= pops[self._next_pop].t_up_ms:
            self._next_pop += 1
            self._cue("play_mole_pop")

    @property
    def done(self):
        if self._online:
            return (self._resolved_at is not None
                    and self._now - self._resolved_at >= SKILLCHECK_RESULT_HOLD_MS)
        if self._committed_at is None:
            return False
        hold = MOLE_VIEW_FAIL_HOLD_MS if self._landed is False else MOLE_VIEW_RESULT_HOLD_MS
        return self._now - self._committed_at >= hold

    @property
    def landed(self):
        return self._landed

    def _frozen_elapsed(self):
        frozen = self._committed_at if self._committed_at is not None else self._now
        return frozen - self.start_ms

    def draw(self, window):
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
            if self._committed_at is None:
                self._draw_crosshair(window)
        self._draw_pips(window, group)
        self._draw_taunt(window)

    def _telegraph_hole(self, elapsed):
        if self._committed_at is not None:
            return None
        for pop in self.challenge.pops:
            if pop.t_telegraph_ms <= elapsed < pop.t_up_ms:
                return pop.hole
        return None

    def _owned_faded(self, base, fade):
        owned = self._owned.get("pit")
        if owned is None:
            owned = base.copy()
            self._owned["pit"] = owned
        owned.set_alpha(max(int(fade * 255), 0))
        return owned

    def _draw_pits(self, window, elapsed, group):
        fade = 1.0
        if self._landed is False and self._committed_at is not None:
            fade = 1.0 - min(1.0, (self._now - self._committed_at) / MOLE_VIEW_FAIL_FADE_MS)
            if fade <= 0.0:
                return
        tele = self._telegraph_hole(elapsed)
        pit = _pit_surface(self._pit_rx, self._pit_ry)
        if fade < 1.0:
            pit = self._owned_faded(pit, fade)
        for i, (hx, hy) in enumerate(self._hole_px):
            open_t = (elapsed - i * MOLE_VIEW_HOLE_STAGGER_MS) / MOLE_VIEW_HOLE_OPEN_MS
            if open_t <= 0.0:
                continue
            cx, cy = hx + group[0], hy + group[1]
            if open_t < 1.0:
                rx = max(int(self._pit_rx * open_t), 2)
                ry = max(int(self._pit_ry * open_t), 1)
                pg.draw.ellipse(window, _PIT_DARK, pg.Rect(cx - rx, cy - ry, 2 * rx, 2 * ry))
                continue
            surf = pit
            if i == tele and fade >= 1.0:
                bucket = int(cosine_pulse(self._anim_ms, MOLE_VIEW_PULSE_MS)
                             * (MOLE_VIEW_PULSE_BUCKETS - 1))
                surf = _pit_telegraph_surface(self._pit_rx, self._pit_ry, bucket)
            window.blit(surf, (cx - surf.get_width() // 2, cy - surf.get_height() // 2))

    def _victim_sprite(self):
        tier = min(self._progress, 3)
        sprite = torn_sprite(self._victim, (id(self), self.cell_size), tier)
        if (self._hit_flash_ms is not None
                and self._now - self._hit_flash_ms < MOLE_VIEW_HIT_FLASH_MS):
            sprite = flash_sprite(sprite, (id(self), self.cell_size, tier))
        return sprite

    def _squash_variant(self, sprite, bucket):
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

    def _blit_victim(self, window, center_px, height_frac, group, squash=0):
        if height_frac <= 0.0:
            return
        sprite = self._squash_variant(self._victim_sprite(), squash)
        w, h = sprite.get_size()
        vib = 0.0
        if self._vibrate_ms is not None:
            vib = sakurai_vibrate(self._now, self._vibrate_ms, self._vibrate_dur_ms,
                                  self.cell_size * MOLE_VIEW_VIBRATE_AMP_FRAC)
        cx = center_px[0] + group[0] + int(vib)
        base_y = center_px[1] + group[1] + self._pit_ry // 2
        if height_frac >= 1.0:
            lift = int((min(height_frac, MOLE_VIEW_POP_LIFT_CAP) - 1.0) * h)
            window.blit(sprite, (cx - w // 2, base_y - h - lift))
            return
        clip_h = max(int(h * height_frac), 1)
        window.blit(sprite, (cx - w // 2, base_y - clip_h), area=pg.Rect(0, 0, w, clip_h))

    def _render_pop(self, elapsed):
        idx = None
        for i, pop in enumerate(self.challenge.pops):
            if pop.t_up_ms <= elapsed:
                idx = i
        if idx is None:
            return None
        pop = self.challenge.pops[idx]
        if idx == self._last_hit_pop and self._last_hit_anim_ms is not None:
            rt = (self._anim_ms - self._last_hit_anim_ms) / MOLE_VIEW_RETREAT_MS
            if rt >= 1.0:
                return None
            bucket = min(int(rt * MOLE_VIEW_SQUASH_BUCKETS), MOLE_VIEW_SQUASH_BUCKETS - 1)
            return idx, MOLE_VIEW_POP_HEIGHT_FRAC * (1.0 - rt), bucket
        if elapsed < pop.t_down_ms:
            rise = min((elapsed - pop.t_up_ms) / MOLE_VIEW_RISE_MS, 1.0)
            return idx, MOLE_VIEW_POP_HEIGHT_FRAC * ease_out_back(rise), 0
        rt = (elapsed - pop.t_down_ms) / MOLE_VIEW_RETREAT_MS
        if rt >= 1.0:
            return None
        bucket = min(int(rt * MOLE_VIEW_SQUASH_BUCKETS), MOLE_VIEW_SQUASH_BUCKETS - 1)
        return idx, MOLE_VIEW_POP_HEIGHT_FRAC * (1.0 - rt), bucket

    def _draw_victim(self, window, elapsed, group):
        if self._victim is None:
            return
        if self._landed is False and self._committed_at is not None:
            if self._now - self._committed_at >= MOLE_VIEW_FAIL_FADE_MS:
                self._blit_victim(window, self.center, 1.0, group)
            return
        if elapsed < self._intro_ms:
            self._blit_victim(window, self.center, 1.0 - elapsed / self._intro_ms, group)
            return
        rendered = self._render_pop(elapsed)
        if rendered is None:
            return
        idx, height_frac, squash = rendered
        hole = self.challenge.pops[idx].hole
        if hole >= len(self._hole_px):
            return
        self._blit_victim(window, self._hole_px[hole], height_frac, group, squash)

    def _draw_puffs(self, window):
        cell = self.cell_size
        for spawn_ms, x, y, floats in self._puffs:
            tt = (self._now - spawn_ms) / MOLE_VIEW_PUFF_MS
            if not 0.0 <= tt < 1.0:
                continue
            t = (self._now - spawn_ms) / 1000.0
            color = _DUST_COLORS[min(int(tt * len(_DUST_COLORS)), len(_DUST_COLORS) - 1)]
            r = max(int(cell * MOLE_VIEW_PUFF_R_FRAC * (1.0 - tt)), 1)
            for j in range(MOLE_VIEW_PUFF_COUNT):
                ang = floats[j * 2] * 2.0 * math.pi
                speed = cell * MOLE_VIEW_PUFF_SPEED_FRAC * (0.5 + 0.5 * floats[j * 2 + 1])
                pg.draw.circle(window, color,
                               (int(x + math.cos(ang) * speed * t),
                                int(y + math.sin(ang) * speed * t)), r)

    def _draw_debris(self, window):
        cell = self.cell_size
        g = cell * MOLE_VIEW_DEBRIS_GRAVITY_FRAC
        for spawn_ms, x, y, floats in self._debris:
            tt = (self._now - spawn_ms) / MOLE_VIEW_DEBRIS_MS
            if not 0.0 <= tt < 1.0:
                continue
            t = (self._now - spawn_ms) / 1000.0
            r = max(int(cell * MOLE_VIEW_DEBRIS_R_FRAC * (1.0 - tt)), 1)
            for j in range(MOLE_VIEW_DEBRIS_COUNT):
                ang = floats[j * 2] * 2.0 * math.pi
                speed = cell * MOLE_VIEW_DEBRIS_SPEED_FRAC * (0.4 + 0.6 * floats[j * 2 + 1])
                px = x + math.cos(ang) * speed * t
                py = y + math.sin(ang) * speed * t + 0.5 * g * t * t
                pg.draw.circle(window, _DEBRIS_COLORS[j % len(_DEBRIS_COLORS)],
                               (int(px), int(py)), r)

    def _draw_casings(self, window):
        cell = self.cell_size
        w = max(int(cell * MOLE_VIEW_CASING_W_FRAC), 3)
        h = max(int(cell * MOLE_VIEW_CASING_H_FRAC), 2)
        buckets = 360 // MOLE_VIEW_CASING_SPIN_BUCKET_DEG
        for spawn_ms, x0, y0, vx, vy, g, t_land, spin in self._casings:
            t = min((self._now - spawn_ms) / 1000.0, t_land)
            x = x0 + vx * t
            y = y0 + vy * t + 0.5 * g * t * t
            deg = spin * t * MOLE_VIEW_CASING_SPIN_DPS
            bucket = int(deg / MOLE_VIEW_CASING_SPIN_BUCKET_DEG) % buckets
            surf = _casing_rotated(w, h, bucket)
            window.blit(surf, (int(x) - surf.get_width() // 2,
                               int(y) - surf.get_height() // 2))

    def _draw_impacts(self, window):
        lw = max(self._cross_lw, 1)
        for spawn_ms, x, y in self._impacts:
            tt = (self._now - spawn_ms) / MOLE_VIEW_IMPACT_MS
            if not 0.0 <= tt < 1.0:
                continue
            r = max(int(self.cell_size * MOLE_VIEW_IMPACT_R_FRAC * tt), 2)
            pg.draw.circle(window, _IMPACT_COLOR, (int(x), int(y)), r, lw)

    def _draw_win_pop(self, window, group):
        if self._win_ms is None or self._now - self._win_ms >= MOLE_VIEW_WIN_POP_MS:
            return
        r = max(int(self.cell_size * MOLE_VIEW_WIN_POP_R_FRAC), 8)
        px = self._last_hit_px if self._last_hit_px is not None else self.center
        window.blit(_win_pop_surface(r), (int(px[0]) - r + group[0],
                                          int(px[1]) - r + group[1]),
                    special_flags=pg.BLEND_RGB_ADD)

    def _draw_muzzle(self, window):
        if self._flash_ms is None or self._now - self._flash_ms >= MOLE_VIEW_MUZZLE_MS:
            return
        r = max(int(self.cell_size * MOLE_VIEW_MUZZLE_FRAC), 4)
        window.blit(_muzzle_surface(r), (int(self._flash_px[0]) - r,
                                         int(self._flash_px[1]) - r),
                    special_flags=pg.BLEND_RGB_ADD)

    def _draw_crosshair(self, window):
        mx, my = pg.mouse.get_pos()
        if self._flash_ms is not None:
            t = self._now - self._flash_ms
            if t < MOLE_VIEW_KICK_MS:
                my -= int(self._kick_amp * (1.0 - t / MOLE_VIEW_KICK_MS))
        arm, gap, lw = self._cross_arm, self._cross_gap, self._cross_lw
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pg.draw.line(window, _CROSS_COLOR, (mx + dx * gap, my + dy * gap),
                         (mx + dx * (gap + arm), my + dy * (gap + arm)), lw)
        pg.draw.circle(window, _CROSS_COLOR, (mx, my), self._cross_ring, lw)

    def _draw_pips(self, window, group):
        n = self.challenge.hits_required
        filled = min(self._progress, n)
        w, h, gap = self._pip_w, self._pip_h, self._pip_gap
        total = n * w + (n - 1) * gap
        x = self.center[0] - total // 2 + group[0]
        y = self.center[1] + int(self.cell_size * MOLE_VIEW_PIP_OFFSET_FRAC) + group[1]
        radius = max(h // 3, 2)
        for i in range(n):
            if i < filled:
                surf = rounded_rect_surface((w, h), radius, Colors.accent,
                                            border=Colors.accent_hi, border_width=1)
            else:
                surf = rounded_rect_surface((w, h), radius, Colors.surface,
                                            border=Colors.border_strong, border_width=1)
            window.blit(surf, (x + i * (w + gap), y))

    def _draw_taunt(self, window):
        if self._taunt.shown_at is None:
            return
        bounds = self._board_rect if self._board_rect is not None else window.get_rect()
        self._taunt.draw(window, self._anchor_rect, bounds, self._now,
                         scale=self.cell_size / MOLE_VIEW_TAUNT_ANCHOR_CELL)
