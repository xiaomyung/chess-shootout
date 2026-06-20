import pygame as pg

from chessshootout.frontend.skillcheck.controller import SkillCheckController
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.effects import EffectManager

AIM_TIME_LIMIT_MS = 5000
AIM_RESULT_HOLD_MS = 420
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
AIM_SPOTLIGHT_BASE_R = 72

_VICTIM_KEY = "victim"
_SHOOTER_KEY = "shooter"


class AimController(SkillCheckController):

    def __init__(self, challenge, cell_rect, now_ms, deadline_ms=AIM_TIME_LIMIT_MS,
                 victim_surface=None, board_rect=None, geom=None, from_sq=None,
                 victim_sq=None, attacker_type=None, shot_sound=None):
        self.challenge = challenge
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self.miss_count = 0
        self._committed_at = None
        self._landed = None
        self._victim = victim_surface
        self.cell_size = 0
        self._from_sq = from_sq if from_sq is not None else _SHOOTER_KEY
        self._victim_sq = victim_sq if victim_sq is not None else _VICTIM_KEY
        self._attacker_type = attacker_type
        self._shot_sound = shot_sound
        self._fx = EffectManager()
        self._geom = geom if geom is not None else (lambda key: self.center)
        self._fx.geom = self._geom
        self._glow_base = None
        self._board_rect = None
        self.set_board_rect(board_rect)
        self._apply_geometry(cell_rect)

    def _apply_geometry(self, cell_rect):
        new_cell = max(int(cell_rect.width), 1)
        if self._victim is not None and self.cell_size and new_cell != self.cell_size:
            w = max(int(self._victim.get_width() * new_cell / self.cell_size), 1)
            h = max(int(self._victim.get_height() * new_cell / self.cell_size), 1)
            self._victim = pg.transform.smoothscale(self._victim, (w, h))
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
        if self.challenge.on_target(elapsed, self.miss_count):
            self._landed = True
            self._committed_at = self._now
            return
        self.miss_count += 1
        self._fx.miss(now_ms=self._now, attacker_type=self._attacker_type,
                      from_sq=self._from_sq, victim_sq=self._victim_sq,
                      cell_size=self.cell_size, power="soft",
                      on_fire=self._shot_sound, callout=False)
        self._fx.swear(self._now, self._from_sq, self.cell_size)

    def update(self, now_ms):
        self._now = now_ms
        self._fx.update(now_ms)
        if self._committed_at is None and self.challenge.is_expired(
                now_ms - self.start_ms, self.miss_count):
            self._landed = False
            self._committed_at = now_ms

    @property
    def done(self):
        return (self._committed_at is not None
                and self._now - self._committed_at >= AIM_RESULT_HOLD_MS)

    @property
    def landed(self):
        return self._landed

    def _frozen_elapsed(self):
        frozen = self._committed_at if self._committed_at is not None else self._now
        return frozen - self.start_ms

    def draw(self, window):
        elapsed = self._frozen_elapsed()
        self._draw_scrim(window)
        self._draw_spotlight(window)
        self._draw_victim(window, elapsed)
        self._draw_reticle(window, elapsed)
        self._fx.draw_holes(window, self._now)
        self._fx.draw_over(window, self._now)

    def _draw_scrim(self, window):
        if self._board_rect is None:
            return
        scrim = pg.Surface(self._board_rect.size, pg.SRCALPHA)
        scrim.fill((*pg.Color(Colors.bg)[:3], AIM_SCRIM_ALPHA))
        window.blit(scrim, self._board_rect.topleft)

    def _spotlight_base(self):
        if self._glow_base is None:
            r = AIM_SPOTLIGHT_BASE_R
            surf = pg.Surface((2 * r, 2 * r), pg.SRCALPHA)
            rgb = pg.Color(Colors.amber)[:3]
            for i in range(r):
                radius = r - i
                edge = radius / r
                pg.draw.circle(surf, (*rgb, int(AIM_SPOTLIGHT_ALPHA * (1.0 - edge) ** 2)),
                               (r, r), radius)
            self._glow_base = surf
        return self._glow_base

    def _draw_spotlight(self, window):
        r = max(int(self.cell_size * AIM_SPOTLIGHT_FRAC), 8)
        glow = pg.transform.smoothscale(self._spotlight_base(), (2 * r, 2 * r))
        window.blit(glow, glow.get_rect(center=self.center))

    def _draw_victim(self, window, elapsed):
        if self._victim is None:
            return
        scale = self.challenge.piece_scale(elapsed, self.miss_count)
        if scale <= 0.0:
            return
        w = max(int(self._victim.get_width() * scale), 1)
        h = max(int(self._victim.get_height() * scale), 1)
        img = pg.transform.smoothscale(self._victim, (w, h))
        window.blit(img, img.get_rect(center=self.center))

    def _draw_reticle(self, window, elapsed):
        won = self._committed_at is not None and self._landed
        live = pg.Color(Colors.win if won else Colors.accent)
        path_col = live.lerp(pg.Color(Colors.bg), AIM_PATH_DIM)
        cross_col = pg.Color(Colors.win if won else Colors.text)
        cell = self.cell_size
        span = max(int(cell * AIM_VIEW_SPAN), 8)
        hit_rx, hit_ry = self.challenge.hit_radii(elapsed, self.miss_count)
        ox, oy = self.challenge.reticle_offset(elapsed, self.miss_count)
        path = (self.challenge.path_offsets(elapsed, self.miss_count, AIM_PATH_SAMPLES)
                if AIM_SHOW_PATH else None)

        def render(surf, k):
            c = surf.get_width() / 2.0
            if path is not None:
                pts = [(c + px * cell * k, c + py * cell * k) for px, py in path]
                pg.draw.lines(surf, path_col, False, pts, max(int(2 * k), 1))
            if hit_rx > 0.0 and hit_ry > 0.0:
                ring = pg.Rect(0, 0, int(2 * hit_rx * cell * k), int(2 * hit_ry * cell * k))
                ring.center = (int(c), int(c))
                pg.draw.ellipse(surf, live, ring, max(int(2 * k), 1))
            rx, ry = c + ox * cell * k, c + oy * cell * k
            arm = AIM_CROSS_ARM_FRAC * cell * k
            gap = AIM_CROSS_GAP_FRAC * cell * k
            lw = max(int(2.4 * k), 1)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                pg.draw.line(surf, cross_col, (rx + dx * gap, ry + dy * gap),
                             (rx + dx * (gap + arm), ry + dy * (gap + arm)), lw)
            pg.draw.circle(surf, cross_col, (rx, ry), AIM_RETICLE_R_FRAC * cell * k, lw)

        layer = supersample((span, span), render)
        window.blit(layer, layer.get_rect(center=self.center))
