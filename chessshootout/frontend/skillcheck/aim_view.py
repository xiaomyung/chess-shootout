from collections.abc import Callable
from typing import cast

import pygame as pg

from chessshootout.backend.utils import Square
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.skillcheck.controller import SkillCheckController, EdgeTrigger
from chessshootout.frontend.visual.cache import new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import supersample
from chessshootout.frontend.visual.effects import EffectManager
from chessshootout.skillcheck.aim import AimChallenge, AIM_DEADLINE_MS

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


def _spotlight_surface(r: int) -> pg.Surface:
    """
    The warm glow that picks the victim out of the darkened board, so the eye
    goes straight to the piece being shot at. It is a stack of ever smaller
    discs whose alpha falls off towards the rim, built once per radius because
    that many circles is far too much to draw every frame

    :param r: glow radius in pixels, which is also half its square size
    :returns: the shared glow for that radius
    """
    def build() -> pg.Surface:
        """
        Draw the glow for this radius, called only on a cache miss

        :returns: the freshly drawn glow
        """
        surf = pg.Surface((2 * r, 2 * r), pg.SRCALPHA)
        rgb = pg.Color(Colors.amber)[:3]
        for i in range(r):
            radius = r - i
            edge = radius / r
            pg.draw.circle(surf, (*rgb, int(AIM_SPOTLIGHT_ALPHA * (1.0 - edge) ** 2)),
                           (r, r), radius)
        return surf
    return cast(pg.Surface, memoized_surface(_SPOTLIGHT_CACHE, r, build))


class AimController(SkillCheckController):
    """
    The Steady-Aim mini-game: the board dims, a crosshair sweeps a rotating
    figure-8 over the victim, and the player shoots when it crosses the piece.
    It is the multi-shot kind -- a miss costs no move, it makes the sway
    faster and the victim smaller, and the victim shrinking away to nothing is
    what runs the check out
    """

    challenge: AimChallenge

    def __init__(self, challenge: AimChallenge, cell_rect: pg.Rect, now_ms: int,
                 deadline_ms: float = AIM_TIME_LIMIT_MS,
                 victim_surface: pg.Surface | None = None, board_rect: pg.Rect | None = None,
                 geom: Callable[[Square | str], tuple[float, float]] | None = None,
                 from_sq: Square | None = None, victim_sq: Square | None = None,
                 attacker_type: str | None = None,
                 shot_sound: Callable[[], None] | None = None,
                 on_shot: Callable[[float], None] | None = None, miss_count: int = 0,
                 passive: bool = False, audio: SoundManager | None = None) -> None:
        """
        Open a steady-aim check over one square. Every miss is staged as a real
        gun-fight on the board, so the check needs to know who is shooting,
        where from and what it sounds like as well as the figure-8 itself. A
        check adopted after a reconnect starts from the miss count the server
        kept, since that is what the sway and the shrink have escalated to

        :param challenge: the figure-8 and hit box to draw and judge against
        :param cell_rect: rect of the square the victim stands on
        :param now_ms: pygame ticks in milliseconds the check counts from
        :param deadline_ms: how long the check may run, in milliseconds
        :param victim_surface: sprite of the piece being shot at, which this
            check draws while the board suppresses that square
        :param board_rect: board rect in window pixels to dim, None to skip the
            scrim
        :param geom: resolves a square, or this view's off-board sentinel
            keys, to a centre in window pixels, so the miss choreography can
            be staged on the real board
        :param from_sq: square the attacker fires from
        :param victim_sq: square the victim stands on, which for an en-passant
            capture is not the square being moved to
        :param attacker_type: piece type value of the shooter, which picks its
            gun; None falls back to the revolver
        :param shot_sound: plays the shooter's gunshot when the gun goes off
        :param on_shot: reports one shot to the server, None in a local game
        :param miss_count: shots already missed, for a check resumed mid-flight
        :param passive: True for the read-only mirror of the opponent's check
        :param audio: sound manager for the lock, beep and verdict cues
        """
        self._init_common(challenge, now_ms, deadline_ms, on_shot=on_shot, passive=passive,
                          audio=audio)
        self.miss_count = miss_count
        self._beep_edge = EdgeTrigger()
        self._last_miss_ms: int | None = None
        self._shot_render: tuple[float, int] | None = None
        self._shot_offset: tuple[float, float] | None = None
        self._shot_held_until: int | None = None
        self._init_victim(victim_surface, cell_rect)
        self.cell_size = 0
        self._from_sq = from_sq if from_sq is not None else _SHOOTER_KEY
        self._victim_sq = victim_sq if victim_sq is not None else _VICTIM_KEY
        self._attacker_type = attacker_type
        self._shot_sound = shot_sound
        self._fx = EffectManager()
        self._geom = geom if geom is not None else (lambda key: self.center)
        self._fx.geom = self._geom
        self._board_rect: pg.Rect | None = None
        self.set_board_rect(board_rect)
        self._apply_geometry(cell_rect)
        self._cue("play_aim_lock")

    def _apply_geometry(self, cell_rect: pg.Rect) -> None:
        """
        Re-anchor the check on its square and take the board's cell size as the
        unit everything is measured in. Aim geometry is one proportional model
        like the wheel's: the challenge works in cell fractions and the view
        multiplies them by this cell size, so the crosshair, hit ring and
        strokes keep their approved look at any window size and nothing
        look-bearing is a fixed pixel count

        :param cell_rect: the square's rect in window pixels; its centre
            anchors the check and its width is the cell size
        """
        new_cell = max(int(cell_rect.width), 1)
        if self._victim_orig is not None:
            self._victim = self._scaled_victim(new_cell)
        self.center = cell_rect.center
        self.cell_size = new_cell

    def set_board_rect(self, board_rect: pg.Rect | None) -> None:
        """
        Tell the check which area to darken and to keep its gun-fight inside.
        The scrim over the board is what makes a steady-aim check read as the
        rest of the game stepping back for the duel

        :param board_rect: the board's rect in window pixels, None to draw no
            scrim at all
        """
        if board_rect is None:
            self._board_rect = None
            self._fx.board_rect = None
            return
        self._board_rect = pg.Rect(board_rect)
        self._fx.board_rect = pg.Rect(board_rect)

    def _fire(self) -> None:
        """
        Take one shot. Offline a shot with the crosshair over the victim wins
        the capture outright; anything else is played out as a miss, which
        escalates the check rather than ending it. Online every shot is staged
        as a miss and sent to the server -- only the server may upgrade it to
        a win, so an on-target tap is never painted as one here
        """
        elapsed = self._now - self.start_ms
        if not self._online and self.challenge.on_target(elapsed, self.miss_count):
            self._landed = True
            self._committed_at = self._now
            self._emit_verdict()
            return
        self._replay_miss(elapsed, self.miss_count)
        if self._online:
            cast(Callable[..., None], self._on_shot)(elapsed)

    def _replay_miss(self, elapsed: float, miss_count: int) -> None:
        """
        Play out one missed shot: freeze the crosshair where it was fired for a
        beat, stage the attacker's dry-fire on the board with a stray bullet
        and a swear word, and escalate the check. It is deliberately the same
        gun-fight the board runs for a fluffed capture, minus the big taunt,
        which the overlay saves for the final verdict

        :param elapsed: milliseconds into the check the shot was fired at
        :param miss_count: misses before this one, which is the escalation the
            frozen crosshair is drawn at
        """
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

    def _shot_fired(self, advance_only: bool) -> None:
        """
        Sound the shooter's gun at the frame the choreography actually pulls
        the trigger, a few frames after the click, so the bang lands with the
        muzzle flash rather than with the input

        :param advance_only: the effects layer's flag for a capture that only
            walks the piece over; a miss always passes it False
        """
        if self._shot_sound is not None:
            self._shot_sound()

    def spectate_shot(self, elapsed: float, miss_count: int, won: bool, progress: int = 0,
                      direction: str | None = None,
                      target: tuple[float, float] | None = None) -> None:
        """
        Replay a shot the opponent fired in the mirror. A winning shot only
        freezes the crosshair where they hit; a losing one runs the whole miss
        choreography, so the watcher sees the same stray bullets and swearing
        the shooter did

        :param elapsed: milliseconds into the check the shot was fired at
        :param miss_count: misses they had before it, which fixes the lobe the
            frozen crosshair is drawn on
        :param won: True when that shot hit the victim
        :param progress: unused by aim, which counts misses rather than hits
        :param direction: unused by aim, which takes no direction
        :param target: unused by aim, whose crosshair position is derived from
            the elapsed time instead
        """
        if won:
            self._shot_render = (elapsed, miss_count)
            self._shot_offset = self.challenge.reticle_offset(elapsed, miss_count)
            self._shot_held_until = self._now + AIM_SHOT_HOLD_MS
            return
        self._replay_miss(elapsed, miss_count)

    def update(self, now_ms: int) -> None:
        """
        Advance the sweep and the gun-fight by one frame, beeping once each
        time the crosshair crosses onto the victim so the shot can be taken by
        ear as well as by eye. Offline the check fails itself once the victim
        has shrunk away; online the server decides expiry

        :param now_ms: pygame tick count in milliseconds for this frame
        """
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
    def done(self) -> bool:
        """
        Whether the check has held its verdict long enough to be retired. Aim
        holds a little longer than the wheel, since the last shot's
        choreography is still playing when the outcome is decided

        :returns: True once the verdict has been shown
        """
        return self._done_after(AIM_RESULT_HOLD_MS)

    def _render_state(self) -> tuple[float, int]:
        """
        Decide which moment the check should be drawn at. A win the server
        granted is drawn on the shot that earned it, so the crosshair sits over
        the victim rather than wherever the figure-8 had wandered by the time
        the verdict came back

        :returns: (milliseconds into the check, misses) to draw at
        """
        if (self._online and self._landed and self._committed_at is not None
                and self._shot_render is not None):
            return self._shot_render
        return self._frozen_elapsed(), self.miss_count

    def victim_scale(self) -> float:
        """
        Say how far the victim has shrunk, so the board draws the piece at the
        same size this check does. The shrink is this kind's clock made visible
        -- reaching nothing is exactly what running out of time means

        :returns: scale factor for the victim sprite, 1.0 at the start
        """
        elapsed, miss = self._render_state()
        return self.challenge.piece_scale(elapsed, miss)

    def draw(self, window: pg.Surface) -> None:
        """
        Paint the whole duel in the order it reads: the board dimmed, the
        spotlight on the victim, the shrinking piece, the crosshair, then the
        bullet holes and the gun-fight over the top

        :param window: surface to draw on, the app window
        """
        elapsed, miss = self._render_state()
        self._draw_scrim(window)
        self._draw_spotlight(window)
        self._draw_victim(window, elapsed, miss)
        self._draw_reticle(window, elapsed, miss)
        self._fx.draw_holes(window, self._now)
        self._fx.draw_over(window, self._now)

    def _draw_scrim(self, window: pg.Surface) -> None:
        """
        Dim the whole board so only the duel is lit. The mirror skips it -- the
        watcher is not aiming and should keep reading their own position

        :param window: surface to draw on, the app window
        """
        if self._passive or self._board_rect is None:
            return
        scrim = pg.Surface(self._board_rect.size, pg.SRCALPHA)
        scrim.fill((*pg.Color(Colors.bg)[:3], AIM_SCRIM_ALPHA))
        window.blit(scrim, self._board_rect.topleft)

    def _draw_spotlight(self, window: pg.Surface) -> None:
        """
        Light the victim's square through the scrim, which is what tells the
        player where to look the instant the board goes dark

        :param window: surface to draw on, the app window
        """
        r = max(int(self.cell_size * AIM_SPOTLIGHT_FRAC), 8)
        glow = _spotlight_surface(r)
        window.blit(glow, glow.get_rect(center=self.center))

    def _draw_victim(self, window: pg.Surface, elapsed: float, miss: int) -> None:
        """
        Draw the piece being shot at, at whatever is left of it. This check
        owns the victim while it runs -- the board has stopped drawing that
        square -- and once the piece has shrunk to nothing there is nothing
        left to paint

        :param window: surface to draw on, the app window
        :param elapsed: milliseconds into the check this frame shows
        :param miss: misses so far, which shrink the piece faster
        """
        if self._victim is None:
            return
        scale = self.challenge.piece_scale(elapsed, miss)
        if scale <= 0.0:
            return
        w = max(int(self._victim.get_width() * scale), 1)
        h = max(int(self._victim.get_height() * scale), 1)
        img = pg.transform.smoothscale(self._victim, (w, h))
        window.blit(img, img.get_rect(center=self.center))

    def _reticle_colors(self) -> tuple[pg.Color, pg.Color]:
        """
        Pick the crosshair's colours for this frame, which is how the check
        answers back: green or red once it is decided, a red flash that fades
        out after each miss, and the neutral spectate colour in the mirror

        :returns: (hit-ring colour, crosshair colour) for this frame
        """
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

    def _crosshair_offset(self, elapsed: float, miss: int) -> tuple[float, float]:
        """
        Say where to draw the crosshair, holding it still for a moment after
        each shot so the player can see where they actually fired before the
        sweep carries it away

        :param elapsed: milliseconds into the check this frame shows
        :param miss: misses so far, which speed the sweep up
        :returns: (x, y) offset from the victim centre in board-cell widths
        """
        if (self._committed_at is None and self._shot_offset is not None
                and self._now < cast(int, self._shot_held_until)):
            return self._shot_offset
        return self.challenge.reticle_offset(elapsed, miss)

    def _draw_reticle(self, window: pg.Surface, elapsed: float, miss: int) -> None:
        """
        Draw the aiming furniture: the hit ring that shows how much of the
        victim is still catchable and the crosshair on its sweep. Everything is
        sized from the cell -- span, arms, gap, stroke widths -- so the reticle
        keeps its approved proportions at any window size. The figure-8 itself
        is only drawn when the path is switched on, which shipped off

        :param window: surface to draw on, the app window
        :param elapsed: milliseconds into the check this frame shows
        :param miss: misses so far, which shrink the ring and speed the sweep
        """
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

        def render(surf: pg.Surface, k: int) -> None:
            """
            Paint the path, ring and crosshair onto the oversized canvas,
            scaling every cell-fraction offset and width by the enlargement
            factor

            :param surf: the oversized canvas being drawn into
            :param k: how many times oversized that canvas is
            """
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
