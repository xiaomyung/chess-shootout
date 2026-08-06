import pygame as pg

from chessshootout.frontend.skillcheck.controller import SkillCheckController, EdgeTrigger
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.effects import EffectManager
from chessshootout.skillcheck.aim import AIM_DEADLINE_MS

AIM_TIME_LIMIT_MS = AIM_DEADLINE_MS
AIM_RESULT_HOLD_MS = 420
AIM_MISS_FLASH_MS = 240
AIM_SHOT_HOLD_MS = 120
AIM_SCRIM_ALPHA = 206
AIM_VIEW_SPAN = 2.6
AIM_PATH_SAMPLES = 96
AIM_SHOW_PATH = False
AIM_CROSS_ARM_FRAC = 0.16
AIM_CROSS_GAP_FRAC = 0.05
AIM_RETICLE_R_FRAC = 0.09
AIM_PATH_DIM = 0.42
AIM_SPOTLIGHT_FRAC = 1.25
AIM_SPOTLIGHT_ALPHA = 70
AIM_CROSS_LW_FRAC = 0.024
AIM_RING_LW_FRAC = 0.02

_VICTIM_KEY = "victim"
_SHOOTER_KEY = "shooter"

_SPOTLIGHT_CACHE = new_cache()


def _spotlight_surface(r):
    def build():
        surf = pg.Surface((2 * r, 2 * r), pg.SRCALPHA)
        rgb = pg.Color(Colors.amber)[:3]
        for i in range(r):
            radius = r - i
            edge = radius / r
            pg.draw.circle(surf, (*rgb, int(AIM_SPOTLIGHT_ALPHA * (1.0 - edge) ** 2)),
                           (r, r), radius)
        return surf
    return memoized_surface(_SPOTLIGHT_CACHE, r, build)


class AimController(SkillCheckController):

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms=AIM_TIME_LIMIT_MS,
                 victim_surface=None, board_rect=None, geom=None, from_sq=None,
                 victim_sq=None, attacker_type=None, shot_sound=None, on_shot=None,
                 miss_count=0, passive=False, audio=None):
        self._init_common(challenge, now_ms, deadline_ms, on_shot=on_shot, passive=passive,
                          audio=audio)
        self.miss_count = miss_count
        self._beep_edge = EdgeTrigger()
        self._last_miss_ms = None
        self._shot_render = None
        self._shot_offset = None
        self._shot_held_until = None
        self._init_victim(victim_surface, cell_rect)
        self.cell_size = 0
        self._from_sq = from_sq if from_sq is not None else _SHOOTER_KEY
        self._victim_sq = victim_sq if victim_sq is not None else _VICTIM_KEY
        self._attacker_type = attacker_type
        self._shot_sound = shot_sound
        self._fx = EffectManager()
        self._geom = geom if geom is not None else (lambda key: self.center)
        self._fx.geom = self._geom
        self._board_rect = None
        self.set_board_rect(board_rect)
        self._apply_geometry(cell_rect)
        self._cue("play_aim_lock")

    def _apply_geometry(self, cell_rect):
        new_cell = max(int(cell_rect.width), 1)
        if self._victim_orig is not None:
            self._victim = self._scaled_victim(new_cell)
        self.center = cell_rect.center
        self.cell_size = new_cell

    def set_board_rect(self, board_rect):
        if board_rect is None:
            self._board_rect = None
            self._fx.board_rect = None
            return
        self._board_rect = pg.Rect(board_rect)
        self._fx.board_rect = pg.Rect(board_rect)

    def relayout(self, cell_rect):
        self._apply_geometry(cell_rect)

    def handle_event(self, event):
        if self._passive:
            return False
        if self._committed_at is not None:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            self._fire()
            return True
        if event.type == pg.KEYDOWN and event.key in (pg.K_SPACE, pg.K_RETURN):
            self._fire()
            return True
        return False

    def _fire(self):
        elapsed = self._now - self.start_ms
        if not self._online and self.challenge.on_target(elapsed, self.miss_count):
            self._landed = True
            self._committed_at = self._now
            self._emit_verdict()
            return
        self._replay_miss(elapsed, self.miss_count)
        if self._online:
            self._on_shot(elapsed)

    def _replay_miss(self, elapsed, miss_count):
        self._shot_render = (elapsed, miss_count)
        self._shot_offset = self.challenge.reticle_offset(elapsed, miss_count)
        self._shot_held_until = self._now + AIM_SHOT_HOLD_MS
        self.miss_count = miss_count + 1
        self._last_miss_ms = self._now
        self._fx.miss(now_ms=self._now, attacker_type=self._attacker_type,
                      from_sq=self._from_sq, victim_sq=self._victim_sq,
                      cell_size=self.cell_size, power="soft",
                      on_fire=self._shot_fired, callout=False)
        self._fx.swear(self._now, self._from_sq, self.cell_size)
        if not self._online:
            self._cue("play_swear")

    def _shot_fired(self, advance_only):
        if self._shot_sound is not None:
            self._shot_sound()

    def resolve(self, won):
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        self._emit_verdict()

    def spectate_shot(self, elapsed, miss_count, won, progress=0, direction=None, target=None):
        if won:
            self._shot_render = (elapsed, miss_count)
            self._shot_offset = self.challenge.reticle_offset(elapsed, miss_count)
            self._shot_held_until = self._now + AIM_SHOT_HOLD_MS
            return
        self._replay_miss(elapsed, miss_count)

    def update(self, now_ms):
        self._now = now_ms
        self._fx.update(now_ms)
        if self._committed_at is None:
            elapsed = now_ms - self.start_ms
            if self._beep_edge.update(self.challenge.on_target(elapsed, self.miss_count)):
                self._cue("play_aim_beep")
        if (not self._online and self._committed_at is None
                and self.challenge.is_expired(now_ms - self.start_ms, self.miss_count)):
            self._landed = False
            self._committed_at = now_ms
            self._emit_verdict()

    @property
    def done(self):
        return self._done_after(AIM_RESULT_HOLD_MS)

    @property
    def landed(self):
        return self._landed

    def _render_state(self):
        if (self._online and self._landed and self._committed_at is not None
                and self._shot_render is not None):
            return self._shot_render
        return self._frozen_elapsed(), self.miss_count

    def victim_scale(self):
        elapsed, miss = self._render_state()
        return self.challenge.piece_scale(elapsed, miss)

    def draw(self, window):
        elapsed, miss = self._render_state()
        self._draw_scrim(window)
        self._draw_spotlight(window)
        self._draw_victim(window, elapsed, miss)
        self._draw_reticle(window, elapsed, miss)
        self._fx.draw_holes(window, self._now)
        self._fx.draw_over(window, self._now)

    def _draw_scrim(self, window):
        if self._passive or self._board_rect is None:
            return
        scrim = pg.Surface(self._board_rect.size, pg.SRCALPHA)
        scrim.fill((*pg.Color(Colors.bg)[:3], AIM_SCRIM_ALPHA))
        window.blit(scrim, self._board_rect.topleft)

    def _draw_spotlight(self, window):
        r = max(int(self.cell_size * AIM_SPOTLIGHT_FRAC), 8)
        glow = _spotlight_surface(r)
        window.blit(glow, glow.get_rect(center=self.center))

    def _draw_victim(self, window, elapsed, miss):
        if self._victim is None:
            return
        scale = self.challenge.piece_scale(elapsed, miss)
        if scale <= 0.0:
            return
        w = max(int(self._victim.get_width() * scale), 1)
        h = max(int(self._victim.get_height() * scale), 1)
        img = pg.transform.smoothscale(self._victim, (w, h))
        window.blit(img, img.get_rect(center=self.center))

    def _reticle_colors(self):
        if self._committed_at is not None and self._landed is not None:
            verdict = pg.Color(Colors.win if self._landed else Colors.loss)
            return verdict, pg.Color(verdict)
        live = pg.Color(self._signal_color(Colors.accent))
        cross_col = pg.Color(Colors.text)
        if self._last_miss_ms is not None:
            flash = max(0.0, 1.0 - (self._now - self._last_miss_ms) / AIM_MISS_FLASH_MS)
            if flash > 0.0:
                loss = pg.Color(Colors.loss)
                live = live.lerp(loss, flash)
                cross_col = cross_col.lerp(loss, flash)
        return live, cross_col

    def _crosshair_offset(self, elapsed, miss):
        if (self._committed_at is None and self._shot_offset is not None
                and self._now < self._shot_held_until):
            return self._shot_offset
        return self.challenge.reticle_offset(elapsed, miss)

    def _draw_reticle(self, window, elapsed, miss):
        live, cross_col = self._reticle_colors()
        path_col = live.lerp(pg.Color(Colors.bg), AIM_PATH_DIM)
        cell = self.cell_size
        span = max(int(cell * AIM_VIEW_SPAN), 8)
        hit_rx, hit_ry = self.challenge.hit_radii(elapsed, miss)
        ox, oy = self._crosshair_offset(elapsed, miss)
        path = (self.challenge.path_offsets(elapsed, miss, AIM_PATH_SAMPLES)
                if AIM_SHOW_PATH else None)
        cross_lw_base = max(1, round(cell * AIM_CROSS_LW_FRAC))
        ring_lw_base = max(1, round(cell * AIM_RING_LW_FRAC))

        def render(surf, k):
            c = surf.get_width() / 2.0
            ring_lw = max(int(ring_lw_base * k), 1)
            if path is not None:
                pts = [(c + px * cell * k, c + py * cell * k) for px, py in path]
                pg.draw.lines(surf, path_col, False, pts, ring_lw)
            if hit_rx > 0.0 and hit_ry > 0.0:
                ring = pg.Rect(0, 0, int(2 * hit_rx * cell * k), int(2 * hit_ry * cell * k))
                ring.center = (int(c), int(c))
                pg.draw.ellipse(surf, live, ring, ring_lw)
            rx, ry = c + ox * cell * k, c + oy * cell * k
            arm = AIM_CROSS_ARM_FRAC * cell * k
            gap = AIM_CROSS_GAP_FRAC * cell * k
            lw = max(int(cross_lw_base * k), 1)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                pg.draw.line(surf, cross_col, (rx + dx * gap, ry + dy * gap),
                             (rx + dx * (gap + arm), ry + dy * (gap + arm)), lw)
            pg.draw.circle(surf, cross_col, (rx, ry), AIM_RETICLE_R_FRAC * cell * k, lw)

        layer = supersample((span, span), render)
        window.blit(layer, layer.get_rect(center=self.center))
