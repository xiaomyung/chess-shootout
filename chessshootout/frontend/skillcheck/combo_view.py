import math

import pygame as pg

from chessshootout.backend.utils import Square, BOARD_SIZE
from chessshootout.frontend.skillcheck.controller import (
    SkillCheckController, SKILLCHECK_RESULT_HOLD_MS)
from chessshootout.frontend.skillcheck.juice import (
    Trauma, Hitstop, ease_out_back, sakurai_vibrate, torn_sprite)
from chessshootout.frontend.visual.cache import (
    new_size_cache, memoized_surface, render_text)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    chevron_surface, cosine_pulse, supersample)
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_display_font
from chessshootout.skillcheck.combo import (
    COMBO_WRONG_LOCKOUT_MS, COMBO_MAX_WRONGS, COMBO_MIN_INTER_PRESS_MS)
from chessshootout.skillcheck.online import SKILLCHECK_HUMAN_FLOOR_MS
from chessshootout.skillcheck.rng import seeded_floats
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS

COMBO_TIME_LIMIT_MS = SKILLCHECK_DEADLINE_MS
COMBO_RESULT_HOLD_MS = 420

COMBO_PAD_RADIUS_FRAC = 1.35
COMBO_PAD_RADIUS_MIN_PX = 72
COMBO_HUB_FRAC = 0.22
COMBO_SEP_W_FRAC = 0.04
COMBO_SEP_W_MIN_PX = 2
COMBO_CHEVRON_FRAC = 0.34
COMBO_CHEVRON_DIST_FRAC = 0.60
COMBO_HOVER_ALPHA = 45

COMBO_STRIP_GAP_FRAC = 0.55
COMBO_STRIP_CHEVRON_FRAC = 0.34
COMBO_STRIP_SLOT_GAP_FRAC = 0.28
COMBO_STRIP_CURRENT_SCALE = 1.35

COMBO_PIP_GAP_FRAC = 0.34
COMBO_PIP_SIZE_FRAC = 0.22
COMBO_PIP_ROW_GAP_FRAC = 0.5

COMBO_SCRIM_ALPHA = 206
COMBO_SPOT_START_FRAC = 1.05
COMBO_SPOT_END_FRAC = 1.2
COMBO_SPOT_FEATHER_STEPS = 3
COMBO_SPOT_FEATHER_FRAC = 0.18
COMBO_SPOT_WARN_FRAC = 0.2
COMBO_SPOT_RIM_W_FRAC = 0.03
COMBO_SPOT_RIM_W_MIN_PX = 2
COMBO_SPOT_WARN_PULSE_MS = 280.0
COMBO_SPOT_WARN_FLICKER_MIN = 0.5

COMBO_BPM_BASE = 125.0
COMBO_BPM_RAMP = 55.0
COMBO_DANCE_ALPHA = 70

COMBO_RECEPTOR_FLASH_MS = 100.0
COMBO_RECEPTOR_FLASH_ALPHA = 255
COMBO_ARROW_FLY_MS = 120.0
COMBO_ARROW_FLY_RISE_FRAC = 0.9
COMBO_SPARK_MIN = 5
COMBO_SPARK_MAX = 8
COMBO_SPARK_MS = 260.0
COMBO_SPARK_REACH_FRAC = 0.7
COMBO_SPARK_SIZE_FRAC = 0.05
COMBO_WHITE_FLASH_MS = 80.0
COMBO_WHITE_FLASH_ALPHA = 150

COMBO_JUDGE_BRILLIANT_MS = 350.0
COMBO_JUDGE_CLEAN_MS = 700.0
COMBO_JUDGE_HOLD_MS = 520.0
COMBO_JUDGE_FONT_FRAC = 0.5
COMBO_JUDGE_RISE_FRAC = 0.4
COMBO_BRILLIANT_TEXT = "BRILLIANT!"
COMBO_CLEAN_TEXT = "CLEAN!"
COMBO_FAIL_TEXT = "BLUNDER??"

COMBO_TRAUMA_CORRECT = 0.2
COMBO_TRAUMA_MAX_OFFSET = 6.0

COMBO_WIN_HITSTOP_MS = 200.0
COMBO_WIN_FLASH_MS = 80.0
COMBO_WIN_FLASH_ALPHA = 160
COMBO_TORN_MS = 480.0

COMBO_WRONG_HITSTOP_MS = 70.0
COMBO_WRONG_FLASH_MS = 220.0
COMBO_WRONG_FLASH_ALPHA = 220
COMBO_WIGGLE_MS = 260.0
COMBO_WIGGLE_AMP_FRAC = 0.12
COMBO_PAD_DIM_ALPHA = 130

COMBO_CONFETTI = ("🎉", "✨", "🔥")
COMBO_CONFETTI_COUNT = 14
COMBO_CONFETTI_MS = 900.0
COMBO_CONFETTI_SPREAD_FRAC = 2.2
COMBO_CONFETTI_GRAV_FRAC = 2.6
COMBO_CONFETTI_SIZE_FRAC = 0.34

COMBO_STREAK_FIRE = 3
COMBO_FIRE_EMOJI = "🔥"
COMBO_FIRE_SIZE_FRAC = 1.3
COMBO_FIRE_PULSE_MS = 140.0
COMBO_FIRE_ALPHA_MIN = 120
COMBO_FIRE_ALPHA_MAX = 230
COMBO_FIRE_BOB_FRAC = 0.12

COMBO_BOP_AMP_FRAC = 0.12
COMBO_SHUFFLE_AMP_FRAC = 0.06
COMBO_SHUFFLE_PERIOD = 90.0

COMBO_FLASH_WHITE = "#ffffff"

_RECEPTOR_DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_DIR_ANGLE = {"up": 0, "left": 90, "down": 180, "right": -90}
_DIR_WEDGE_SPAN = {
    "up": (-0.75, -0.25), "right": (-0.25, 0.25), "down": (0.25, 0.75), "left": (0.75, 1.25),
}
_WEDGE_ARC_SEGS = 20
_KEY_DIRECTION = {
    pg.K_UP: "up", pg.K_w: "up", pg.K_DOWN: "down", pg.K_s: "down",
    pg.K_LEFT: "left", pg.K_a: "left", pg.K_RIGHT: "right", pg.K_d: "right",
}

_SPOT_BG = pg.Color(Colors.bg)
_SPOT_FILL_RGBA = (_SPOT_BG.r, _SPOT_BG.g, _SPOT_BG.b, COMBO_SCRIM_ALPHA)
_SPOT_FEATHER_RGBA = tuple(
    (_SPOT_BG.r, _SPOT_BG.g, _SPOT_BG.b,
     int(COMBO_SCRIM_ALPHA * k / (COMBO_SPOT_FEATHER_STEPS + 1)))
    for k in range(COMBO_SPOT_FEATHER_STEPS, 0, -1))
_SPOT_HOLE_RGBA = (0, 0, 0, 0)
_RIM_ACCENT = pg.Color(Colors.accent)
_RIM_LOSS = pg.Color(Colors.loss)

_PAD_STATIC_CACHE = new_size_cache()
_DIR_CHEVRON_CACHE = new_size_cache()
_RECEPTOR_FILL_CACHE = new_size_cache()
_DISC_CACHE = new_size_cache()
_TINT_CACHE = new_size_cache()
_SPARK_CACHE = new_size_cache()
_PIP_CACHE = new_size_cache()
_FLASH_CACHE = new_size_cache()
_CONFETTI_CACHE = new_size_cache()


def _direction_chevron(size, color, direction):
    def build():
        base = chevron_surface(size, color, up=True)
        angle = _DIR_ANGLE[direction]
        return base if angle == 0 else pg.transform.rotate(base, angle)
    return memoized_surface(_DIR_CHEVRON_CACHE, (size, str(color), direction), build)


def _pad_static(radius, hub_r):
    sep_w = max(int(radius * COMBO_SEP_W_FRAC), COMBO_SEP_W_MIN_PX)
    chev = max(int(radius * COMBO_CHEVRON_FRAC), 6)

    def build():
        def render(surf, k):
            c = surf.get_width() / 2.0
            r = radius * k
            w = max(int(sep_w * k), 1)
            half = r * math.cos(math.pi / 4.0)
            pg.draw.circle(surf, pg.Color(Colors.surface_raised), (c, c), r)
            pg.draw.line(surf, pg.Color(Colors.border_strong),
                         (c - half, c - half), (c + half, c + half), w)
            pg.draw.line(surf, pg.Color(Colors.border_strong),
                         (c - half, c + half), (c + half, c - half), w)
            pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), r, w)
            pg.draw.circle(surf, pg.Color(Colors.surface), (c, c), hub_r * k)
            pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), hub_r * k, w)
        base = supersample(2 * radius, render)
        for direction, (dx, dy) in _RECEPTOR_DIRS.items():
            arrow = _direction_chevron(chev, Colors.text_dim, direction)
            cx = radius + dx * radius * COMBO_CHEVRON_DIST_FRAC
            cy = radius + dy * radius * COMBO_CHEVRON_DIST_FRAC
            base.blit(arrow, arrow.get_rect(center=(int(cx), int(cy))))
        return base
    return memoized_surface(_PAD_STATIC_CACHE, (radius, hub_r), build)


def _wedge_overlay(radius, hub_r, direction, color):
    def build():
        span = _DIR_WEDGE_SPAN[direction]
        a0, a1 = span[0] * math.pi, span[1] * math.pi

        def render(surf, k):
            c = surf.get_width() / 2.0
            pts = []
            for i in range(_WEDGE_ARC_SEGS + 1):
                a = a0 + (a1 - a0) * i / _WEDGE_ARC_SEGS
                pts.append((c + radius * k * math.cos(a), c + radius * k * math.sin(a)))
            for i in range(_WEDGE_ARC_SEGS + 1):
                a = a1 + (a0 - a1) * i / _WEDGE_ARC_SEGS
                pts.append((c + hub_r * k * math.cos(a), c + hub_r * k * math.sin(a)))
            pg.draw.polygon(surf, pg.Color(color), pts)
        return supersample(2 * radius, render)
    return memoized_surface(_RECEPTOR_FILL_CACHE, (radius, hub_r, direction, str(color)), build)


def _disc(radius, color):
    def build():
        def render(surf, k):
            c = surf.get_width() / 2.0
            pg.draw.circle(surf, pg.Color(color), (c, c), radius * k)
        return supersample(2 * radius, render)
    return memoized_surface(_DISC_CACHE, (radius, str(color)), build)


def _tint_cell(cell, color):
    def build():
        surf = pg.Surface((cell, cell), pg.SRCALPHA)
        surf.fill(pg.Color(color))
        return surf
    return memoized_surface(_TINT_CACHE, (cell, str(color)), build)


def _spark_surface(size, color):
    def build():
        surf = pg.Surface((size, size), pg.SRCALPHA)
        surf.fill(pg.Color(color))
        return surf
    return memoized_surface(_SPARK_CACHE, (size, str(color)), build)


def _pip_surface(size, struck):
    def build():
        def render(surf, k):
            w = surf.get_width()
            r = w / 2.0
            if struck:
                pg.draw.circle(surf, pg.Color(Colors.loss), (r, r), r)
                lw = max(int(w * 0.12), 2)
                pad = w * 0.28
                pg.draw.line(surf, pg.Color(Colors.on_accent), (pad, pad),
                             (w - pad, w - pad), lw)
                pg.draw.line(surf, pg.Color(Colors.on_accent), (w - pad, pad),
                             (pad, w - pad), lw)
            else:
                lw = max(int(w * 0.1), 2)
                pg.draw.circle(surf, pg.Color(Colors.border_strong), (r, r), r - lw, lw)
        return supersample((size, size), render)
    return memoized_surface(_PIP_CACHE, (size, struck), build)


def _flash_layer(w, h):
    def build():
        surf = pg.Surface((max(int(w), 1), max(int(h), 1)))
        surf.fill((255, 255, 255))
        return surf
    return memoized_surface(_FLASH_CACHE, (int(w), int(h)), build)


def _confetti_sprite(char, size):
    def build():
        base = emoji_surface(char, size)
        return base.copy() if base is not None else None
    return memoized_surface(_CONFETTI_CACHE, (char, size), build)


class ComboController(SkillCheckController):

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms=COMBO_TIME_LIMIT_MS, *,
                 board_rect=None, geom=None, victim_surface=None, attacker_surface=None,
                 from_sq=None, victim_sq=None, on_shot=None, miss_count=0, progress=0,
                 passive=False, audio=None):
        self.challenge = challenge
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self.progress = progress
        self.wrong_count = miss_count
        self._on_shot = on_shot
        self._passive = passive
        self._online = on_shot is not None or passive
        self._audio = audio
        self._from_sq = from_sq
        self._victim_sq = victim_sq
        self._geom = geom
        self._board_rect = pg.Rect(board_rect) if board_rect is not None else None
        self._victim_src = victim_surface
        self._attacker_src = attacker_surface
        self._landed = None
        self._committed_at = None
        self._resolved_at = None
        self._closed = False
        self._lockout_until = now_ms
        self._last_accept_ms = None
        self._torn_key = hash(challenge.prompts)
        self._prompt_started_ms = now_ms
        self._judgement = None
        self._judgement_at = now_ms
        self._brilliant_streak = 0
        self._receptor_flash = {}
        self._wrong_flash = None
        self._wiggle_started = None
        self._flying = []
        self._sparks = None
        self._sparks_at = None
        self._spark_count = 0
        self._white_flash = None
        self._win_flash_until = None
        self._torn_until = None
        self._confetti = None
        self._confetti_at = None
        self._fail_started = None
        self._trauma = Trauma()
        self._hitstop = Hitstop()
        self._scaled = {}
        self._spot_layer = None
        self._apply_geometry(cell_rect)
        self._cue("play_skillcheck_appear")

    def _apply_geometry(self, cell_rect):
        self._cell = max(int(cell_rect.width), 1)
        cx, cy = (self._board_rect.center if self._board_rect is not None
                  else cell_rect.center)
        self._pad_center = (cx, cy)
        self._pad_r = max(int(self._cell * COMBO_PAD_RADIUS_FRAC), COMBO_PAD_RADIUS_MIN_PX)
        self._hub_r = max(int(self._pad_r * COMBO_HUB_FRAC), 1)
        self._bbox = 2 * self._pad_r
        self._pad_top = cy - self._pad_r
        self._pad_bottom = cy + self._pad_r
        self._judge_font = get_display_font(max(int(self._cell * COMBO_JUDGE_FONT_FRAC), 14))
        self._scaled = {}
        self._ensure_spot_layer()
        self._layout_strip()

    def _ensure_spot_layer(self):
        if self._passive or self._board_rect is None:
            self._spot_layer = None
            return
        size = self._board_rect.size
        if self._spot_layer is None or self._spot_layer.get_size() != size:
            self._spot_layer = pg.Surface(size, pg.SRCALPHA)

    def _layout_strip(self):
        n = self.challenge.prompt_count
        self._strip_chev = max(int(self._cell * COMBO_STRIP_CHEVRON_FRAC), 8)
        self._strip_big = max(int(self._strip_chev * COMBO_STRIP_CURRENT_SCALE),
                              self._strip_chev + 2)
        self._fire_size = max(int(self._strip_chev * COMBO_FIRE_SIZE_FRAC), 12)
        gap = max(int(self._cell * COMBO_STRIP_SLOT_GAP_FRAC), 4)
        slot_w = self._strip_big
        total = n * slot_w + max(n - 1, 0) * gap
        start = self._pad_center[0] - total // 2
        self._strip_y = self._pad_top - max(int(self._cell * COMBO_STRIP_GAP_FRAC), 12)
        self._strip_slots = [start + i * (slot_w + gap) + slot_w // 2 for i in range(n)]

    def relayout(self, cell_rect):
        self._apply_geometry(cell_rect)

    def set_board_rect(self, board_rect):
        self._board_rect = pg.Rect(board_rect) if board_rect is not None else None
        self._ensure_spot_layer()

    def handle_event(self, event):
        if self._passive:
            return False
        if self._closed:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            direction = self._receptor_hit(event.pos)
            if direction is not None and self._now >= self._lockout_until:
                self._press(direction)
            return True
        if event.type == pg.KEYDOWN:
            direction = _KEY_DIRECTION.get(event.key)
            if direction is None:
                return False
            if self._now >= self._lockout_until:
                self._press(direction)
            return True
        return False

    def _receptor_hit(self, pos):
        dx = pos[0] - self._pad_center[0]
        dy = pos[1] - self._pad_center[1]
        r = math.hypot(dx, dy)
        if r > self._pad_r or r < self._hub_r:
            return None
        if abs(dx) > abs(dy):
            return "left" if dx < 0 else "right"
        return "up" if dy < 0 else "down"

    def _press(self, direction):
        elapsed = self._now - self.start_ms
        if elapsed < SKILLCHECK_HUMAN_FLOOR_MS:
            return
        if (self._last_accept_ms is not None
                and self._now - self._last_accept_ms < COMBO_MIN_INTER_PRESS_MS):
            return
        self._last_accept_ms = self._now
        if self.challenge.press_correct(self.progress, direction):
            self._register_correct(direction)
        else:
            self._register_wrong(direction)
        if self._online:
            self._on_shot(elapsed, direction=direction)

    def _register_correct(self, direction):
        self._judgement = self._judge(self._now - self._prompt_started_ms)
        self._judgement_at = self._now
        if not self._passive:
            if self._judgement == COMBO_BRILLIANT_TEXT:
                self._brilliant_streak += 1
            else:
                self._brilliant_streak = 0
        self._receptor_flash[direction] = self._now
        self._spawn_flying(direction)
        self._spawn_sparks()
        self._white_flash = (direction, self._now + COMBO_WHITE_FLASH_MS)
        self._trauma.add(COMBO_TRAUMA_CORRECT)
        self.progress += 1
        self._prompt_started_ms = self._now
        if self._audio is not None and not self._passive:
            self._audio.play_combo_hit(self.progress - 1)
        if self.challenge.is_complete(self.progress):
            self._win()

    def _register_wrong(self, direction):
        self.wrong_count += 1
        self._brilliant_streak = 0
        self._lockout_until = self._now + int(COMBO_WRONG_LOCKOUT_MS)
        self._wrong_flash = (direction, self._now)
        self._wiggle_started = self._now
        self._hitstop.trigger(self._now, COMBO_WRONG_HITSTOP_MS)
        self._cue("play_combo_wrong")
        if self.challenge.wrongs_exhausted(self.wrong_count):
            self._fail()

    def _register_spectate_wrong(self, direction):
        self._wrong_flash = (direction, self._now)
        self._wiggle_started = self._now
        self._cue("play_combo_wrong")
        if self.challenge.wrongs_exhausted(self.wrong_count):
            self._closed = True

    def _win(self):
        self._hitstop.trigger(self._now, COMBO_WIN_HITSTOP_MS)
        self._win_flash_until = self._now + COMBO_WIN_FLASH_MS
        self._torn_until = self._now + COMBO_TORN_MS
        self._spawn_confetti()
        self._closed = True
        self._cue("play_combo_complete")
        if not self._online:
            self._landed = True
            self._committed_at = self._now

    def _fail(self):
        self._judgement = COMBO_FAIL_TEXT
        self._judgement_at = self._now
        self._fail_started = self._now
        self._closed = True
        self._cue("play_combo_fail")
        if not self._online:
            self._landed = False
            self._committed_at = self._now

    def _judge(self, latency):
        if latency < COMBO_JUDGE_BRILLIANT_MS:
            return COMBO_BRILLIANT_TEXT
        if latency < COMBO_JUDGE_CLEAN_MS:
            return COMBO_CLEAN_TEXT
        return None

    def _fire_active(self):
        return self._brilliant_streak >= COMBO_STREAK_FIRE

    def resolve(self, won):
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        self._closed = True

    def spectate_shot(self, elapsed, miss_count, won, progress=0, direction=None, target=None):
        if progress > self.progress:
            while self.progress < progress:
                step = direction if direction is not None else self.challenge.expected(
                    self.progress)
                self._register_correct(step if step is not None else "up")
        else:
            self.wrong_count = miss_count + 1
            step = direction if direction is not None else self.challenge.expected(self.progress)
            self._register_spectate_wrong(step if step is not None else "up")

    def update(self, now_ms):
        self._now = now_ms
        self._trauma.update(now_ms)
        if (not self._online and not self._closed
                and now_ms - self.start_ms >= self.deadline_ms):
            self._fail()

    @property
    def done(self):
        if self._online:
            return (self._resolved_at is not None
                    and self._now - self._resolved_at >= SKILLCHECK_RESULT_HOLD_MS)
        return (self._committed_at is not None
                and self._now - self._committed_at >= COMBO_RESULT_HOLD_MS)

    @property
    def landed(self):
        return self._landed

    def _spawn_flying(self, direction):
        if self.progress < len(self._strip_slots):
            sx = self._strip_slots[self.progress]
        else:
            sx = self._pad_center[0]
        self._flying.append((direction, sx, self._strip_y, self._now))

    def _spawn_sparks(self):
        self._sparks = seeded_floats(
            "combospark:{}:{}".format(self.challenge.prompts, self.progress),
            COMBO_SPARK_MAX)
        self._sparks_at = self._now
        self._spark_count = COMBO_SPARK_MIN + int(
            self._sparks[0] * (COMBO_SPARK_MAX - COMBO_SPARK_MIN + 1))

    def _spawn_confetti(self):
        self._confetti = seeded_floats(
            "comboconfetti:{}".format(self.challenge.prompts), COMBO_CONFETTI_COUNT * 3)
        self._confetti_at = self._now

    def _shake(self):
        return self._trauma.offset(self._now, COMBO_TRAUMA_MAX_OFFSET)

    def _actor_center(self, sq):
        if self._geom is not None and sq is not None:
            return self._geom(sq)
        return self._pad_center

    def _scaled_sprite(self, src):
        if src is None:
            return None
        cached = self._scaled.get(id(src))
        if cached is not None:
            return cached
        if src.get_width() == self._cell and src.get_height() == self._cell:
            surf = src
        else:
            surf = pg.transform.smoothscale(src, (self._cell, self._cell))
        self._scaled[id(src)] = surf
        return surf

    def draw(self, window):
        self._draw_dance_floor(window)
        self._draw_actors(window)
        self._draw_spotlight(window)
        self._draw_strip(window)
        self._draw_pad(window)
        self._draw_pips(window)
        self._draw_flying(window)
        self._draw_sparks(window)
        self._draw_white_flash(window)
        self._draw_confetti(window)
        self._draw_torn_victim(window)
        self._draw_win_flash(window)
        self._draw_judgement(window)

    def _timer_frac(self):
        timer_now = self._committed_at if self._committed_at is not None else self._now
        frac = (timer_now - self.start_ms) / max(self.deadline_ms, 1)
        return min(max(frac, 0.0), 1.0)

    def _spot_radius(self):
        start_r = COMBO_SPOT_START_FRAC * 0.5 * math.hypot(
            self._board_rect.width, self._board_rect.height)
        end_r = COMBO_SPOT_END_FRAC * self._pad_r
        return start_r + (end_r - start_r) * self._timer_frac()

    def _rim_color(self):
        frac = self._timer_frac()
        warn_start = 1.0 - COMBO_SPOT_WARN_FRAC
        if frac < warn_start:
            return _RIM_ACCENT
        warn_t = (frac - warn_start) / COMBO_SPOT_WARN_FRAC
        flicker = cosine_pulse(self._now, COMBO_SPOT_WARN_PULSE_MS)
        mix = warn_t * (COMBO_SPOT_WARN_FLICKER_MIN
                        + (1.0 - COMBO_SPOT_WARN_FLICKER_MIN) * flicker)
        return _RIM_ACCENT.lerp(_RIM_LOSS, min(max(mix, 0.0), 1.0))

    def _draw_spotlight(self, window):
        if self._spot_layer is None or self._board_rect is None:
            return
        radius = self._spot_radius()
        layer = self._spot_layer
        layer.fill(_SPOT_FILL_RGBA)
        center = (self._pad_center[0] - self._board_rect.x,
                  self._pad_center[1] - self._board_rect.y)
        band = radius * COMBO_SPOT_FEATHER_FRAC
        for i, rgba in enumerate(_SPOT_FEATHER_RGBA):
            step = COMBO_SPOT_FEATHER_STEPS - i
            pg.draw.circle(layer, rgba, center, int(radius + band * step))
        pg.draw.circle(layer, _SPOT_HOLE_RGBA, center, max(int(radius), 1))
        rim_w = max(int(self._cell * COMBO_SPOT_RIM_W_FRAC), COMBO_SPOT_RIM_W_MIN_PX)
        pg.draw.circle(layer, self._rim_color(), center, max(int(radius), 1), rim_w)
        window.blit(layer, self._board_rect.topleft)

    def _beat(self):
        remaining = max(self.challenge.prompt_count - self.progress, 0)
        total = max(self.challenge.prompt_count, 1)
        bpm = COMBO_BPM_BASE + COMBO_BPM_RAMP * (1.0 - remaining / total)
        return cosine_pulse(self._now, 60000.0 / bpm)

    def _draw_dance_floor(self, window):
        if self._geom is None or self._victim_sq is None:
            return
        alpha = int(COMBO_DANCE_ALPHA * self._beat())
        if alpha <= 0:
            return
        lit_r = None if self._spot_layer is None else self._spot_radius()
        tint = _tint_cell(self._cell, Colors.accent)
        tint.set_alpha(alpha)
        px, py = self._pad_center
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                cx, cy = self._geom(Square(row, col))
                if lit_r is not None and math.hypot(cx - px, cy - py) > lit_r:
                    continue
                window.blit(tint, (cx - self._cell // 2, cy - self._cell // 2))

    def _draw_actors(self, window):
        if self._geom is None:
            return
        beat = 1.0 if self._hitstop.frozen(self._now) else self._beat()
        attacker = self._scaled_sprite(self._attacker_src)
        if attacker is not None and self._from_sq is not None:
            cx, cy = self._geom(self._from_sq)
            bob = int(self._cell * COMBO_BOP_AMP_FRAC * beat)
            window.blit(attacker, attacker.get_rect(center=(cx, cy - bob)))
        victim = self._scaled_sprite(self._victim_src)
        showing_torn = self._torn_until is not None and self._now < self._torn_until
        if victim is not None and self._victim_sq is not None and not showing_torn:
            cx, cy = self._geom(self._victim_sq)
            shuffle = int(self._cell * COMBO_SHUFFLE_AMP_FRAC
                          * math.sin(self._now / COMBO_SHUFFLE_PERIOD))
            window.blit(victim, victim.get_rect(center=(cx + shuffle, cy)))

    def _draw_strip(self, window):
        ox, oy = self._shake()
        deflate = self._deflate_scale()
        fire = self._fire_active()
        for i, sx in enumerate(self._strip_slots):
            direction = self.challenge.expected(i)
            wiggle = 0
            if i == self.progress and self._wiggle_started is not None:
                wiggle = int(sakurai_vibrate(self._now, self._wiggle_started, COMBO_WIGGLE_MS,
                                             self._cell * COMBO_WIGGLE_AMP_FRAC))
            if fire and i >= self.progress:
                self._draw_fire(window, sx + ox + wiggle, self._strip_y + oy)
            if i < self.progress:
                chev = _direction_chevron(self._strip_chev, Colors.win, direction)
            elif i == self.progress:
                size = max(int(self._strip_big * deflate), 4)
                chev = _direction_chevron(size, Colors.accent, direction)
            else:
                chev = _direction_chevron(self._strip_chev, Colors.text_dim, direction)
            window.blit(chev, chev.get_rect(center=(sx + ox + wiggle, self._strip_y + oy)))

    def _draw_fire(self, window, cx, cy):
        sprite = _confetti_sprite(COMBO_FIRE_EMOJI, self._fire_size)
        if sprite is None:
            return
        pulse = cosine_pulse(self._now, COMBO_FIRE_PULSE_MS)
        sprite.set_alpha(int(COMBO_FIRE_ALPHA_MIN
                             + (COMBO_FIRE_ALPHA_MAX - COMBO_FIRE_ALPHA_MIN) * pulse))
        bob = int(self._fire_size * COMBO_FIRE_BOB_FRAC * pulse)
        window.blit(sprite, sprite.get_rect(center=(cx, cy - bob)))

    def _deflate_scale(self):
        if self._fail_started is None:
            return 1.0
        t = self._now - self._fail_started
        if t >= COMBO_TORN_MS:
            return 0.35
        return max(0.35, 1.0 - 0.65 * (t / COMBO_TORN_MS))

    def _draw_pad(self, window):
        ox, oy = self._shake()
        left = self._pad_center[0] - self._pad_r + ox
        top = self._pad_center[1] - self._pad_r + oy
        static = _pad_static(self._pad_r, self._hub_r)
        window.blit(static, (left, top))
        self._draw_hover(window, left, top)
        if self._now < self._lockout_until:
            dim = _disc(self._pad_r, Colors.bg)
            dim.set_alpha(COMBO_PAD_DIM_ALPHA)
            window.blit(dim, (left, top))
        self._draw_receptor_flashes(window, left, top)

    def _draw_hover(self, window, left, top):
        if self._passive or self._closed or self._now < self._lockout_until:
            return
        direction = self._receptor_hit(pg.mouse.get_pos())
        if direction is None:
            return
        fill = _wedge_overlay(self._pad_r, self._hub_r, direction, Colors.accent)
        fill.set_alpha(COMBO_HOVER_ALPHA)
        window.blit(fill, (left, top))

    def _draw_receptor_flashes(self, window, left, top):
        for direction, start in self._receptor_flash.items():
            t = self._now - start
            if t < 0 or t >= COMBO_RECEPTOR_FLASH_MS:
                continue
            fill = _wedge_overlay(self._pad_r, self._hub_r, direction, Colors.accent_hi)
            fill.set_alpha(int(COMBO_RECEPTOR_FLASH_ALPHA * (1.0 - t / COMBO_RECEPTOR_FLASH_MS)))
            window.blit(fill, (left, top))
        if self._wrong_flash is not None:
            direction, start = self._wrong_flash
            t = self._now - start
            if 0 <= t < COMBO_WRONG_FLASH_MS:
                fill = _wedge_overlay(self._pad_r, self._hub_r, direction, Colors.loss)
                fill.set_alpha(int(COMBO_WRONG_FLASH_ALPHA * (1.0 - t / COMBO_WRONG_FLASH_MS)))
                window.blit(fill, (left, top))

    def _draw_pips(self, window):
        ox, oy = self._shake()
        size = max(int(self._cell * COMBO_PIP_SIZE_FRAC), 8)
        gap = max(int(self._cell * COMBO_PIP_GAP_FRAC), 4)
        total = COMBO_MAX_WRONGS * size + (COMBO_MAX_WRONGS - 1) * gap
        start = self._pad_center[0] - total // 2
        y = self._pad_bottom + max(int(self._cell * COMBO_PIP_ROW_GAP_FRAC), 10)
        for i in range(COMBO_MAX_WRONGS):
            x = start + i * (size + gap) + size // 2
            pip = _pip_surface(size, i < self.wrong_count)
            window.blit(pip, pip.get_rect(center=(x + ox, y + oy)))

    def _draw_flying(self, window):
        ox, oy = self._shake()
        for direction, sx, sy, start in self._flying:
            t = self._now - start
            if t < 0 or t >= COMBO_ARROW_FLY_MS:
                continue
            progress = ease_out_back(min(t / COMBO_ARROW_FLY_MS, 1.0))
            rise = int(self._cell * COMBO_ARROW_FLY_RISE_FRAC * progress)
            chev = _direction_chevron(self._strip_big, Colors.accent_hi, direction)
            chev.set_alpha(int(255 * (1.0 - t / COMBO_ARROW_FLY_MS)))
            window.blit(chev, chev.get_rect(center=(sx + ox, sy - rise + oy)))

    def _draw_sparks(self, window):
        if self._sparks is None or self._sparks_at is None:
            return
        t = self._now - self._sparks_at
        if t < 0 or t >= COMBO_SPARK_MS:
            return
        ox, oy = self._shake()
        cx, cy = self._pad_center
        progress = t / COMBO_SPARK_MS
        reach = self._cell * COMBO_SPARK_REACH_FRAC * progress
        size = max(int(self._cell * COMBO_SPARK_SIZE_FRAC), 3)
        spark = _spark_surface(size, Colors.amber_hi)
        spark.set_alpha(int(255 * (1.0 - progress)))
        for i in range(self._spark_count):
            ang = self._sparks[i] * 2.0 * math.pi
            x = cx + math.cos(ang) * reach + ox
            y = cy + math.sin(ang) * reach + oy
            window.blit(spark, (x - size / 2.0, y - size / 2.0))

    def _draw_white_flash(self, window):
        if self._white_flash is None:
            return
        direction, until = self._white_flash
        remaining = until - self._now
        if remaining <= 0:
            return
        ox, oy = self._shake()
        fill = _wedge_overlay(self._pad_r, self._hub_r, direction, COMBO_FLASH_WHITE)
        fill.set_alpha(int(COMBO_WHITE_FLASH_ALPHA * (remaining / COMBO_WHITE_FLASH_MS)))
        window.blit(fill, (self._pad_center[0] - self._pad_r + ox,
                           self._pad_center[1] - self._pad_r + oy))

    def _draw_win_flash(self, window):
        if self._win_flash_until is None:
            return
        remaining = self._win_flash_until - self._now
        if remaining <= 0:
            return
        if self._board_rect is not None:
            layer = _flash_layer(self._board_rect.width, self._board_rect.height)
            pos = self._board_rect.topleft
        else:
            layer = _flash_layer(self._bbox, self._bbox)
            pos = (self._pad_center[0] - self._pad_r, self._pad_center[1] - self._pad_r)
        layer.set_alpha(int(COMBO_WIN_FLASH_ALPHA * (remaining / COMBO_WIN_FLASH_MS)))
        window.blit(layer, pos)

    def _draw_confetti(self, window):
        if self._confetti is None or self._confetti_at is None:
            return
        t = self._now - self._confetti_at
        if t < 0 or t >= COMBO_CONFETTI_MS:
            return
        progress = t / COMBO_CONFETTI_MS
        cx, cy = self._pad_center
        size = max(int(self._cell * COMBO_CONFETTI_SIZE_FRAC), 10)
        spread = self._cell * COMBO_CONFETTI_SPREAD_FRAC
        grav = self._cell * COMBO_CONFETTI_GRAV_FRAC
        alpha = int(255 * (1.0 - progress))
        f = self._confetti
        for i in range(COMBO_CONFETTI_COUNT):
            ang = (f[i * 3] - 0.5) * math.pi
            speed = 0.5 + f[i * 3 + 1]
            char = COMBO_CONFETTI[int(f[i * 3 + 2] * len(COMBO_CONFETTI)) % len(COMBO_CONFETTI)]
            surf = _confetti_sprite(char, size)
            if surf is None:
                continue
            x = cx + math.sin(ang) * spread * speed * progress
            y = cy - math.cos(ang) * spread * speed * progress + grav * progress * progress
            surf.set_alpha(alpha)
            window.blit(surf, (x - surf.get_width() / 2.0, y - surf.get_height() / 2.0))

    def _torn_victim(self):
        victim = self._scaled_sprite(self._victim_src)
        if victim is None:
            return None
        return torn_sprite(victim, (self._torn_key, self._cell), 3)

    def _draw_torn_victim(self, window):
        if self._torn_until is None or self._now >= self._torn_until:
            return
        torn = self._torn_victim()
        if torn is None:
            return
        window.blit(torn, torn.get_rect(center=self._actor_center(self._victim_sq)))

    def _draw_judgement(self, window):
        if self._judgement is None:
            return
        t = self._now - self._judgement_at
        if t < 0 or t >= COMBO_JUDGE_HOLD_MS:
            return
        text = render_text(self._judge_font, self._judgement, pg.Color(self._judgement_color()))
        text.set_alpha(int(255 * (1.0 - t / COMBO_JUDGE_HOLD_MS)))
        rise = int(self._cell * COMBO_JUDGE_RISE_FRAC * (t / COMBO_JUDGE_HOLD_MS))
        y = self._strip_y - max(int(self._cell * 0.7), 16) - rise
        window.blit(text, text.get_rect(center=(self._pad_center[0], y)))

    def _judgement_color(self):
        if self._judgement == COMBO_FAIL_TEXT:
            return Colors.loss
        if self._judgement == COMBO_BRILLIANT_TEXT:
            return Colors.accent_hi
        return Colors.win
