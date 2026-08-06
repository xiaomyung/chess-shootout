import pygame as pg

from chessshootout.frontend.visual.colors import Colors

SKILLCHECK_RESULT_HOLD_MS = 200


class EdgeTrigger:

    def __init__(self):
        self._prev = False

    def update(self, inside):
        inside = bool(inside)
        rising = inside and not self._prev
        self._prev = inside
        return rising


class SkillCheckController:

    _audio = None
    _passive = False

    def _init_common(self, challenge, now_ms, deadline_ms, *, on_shot, passive, audio):
        self.challenge = challenge
        self.start_ms = now_ms
        self._now = now_ms
        self.deadline_ms = deadline_ms
        self._on_shot = on_shot
        self._passive = passive
        self._online = on_shot is not None or passive
        self._audio = audio
        self._committed_at = None
        self._resolved_at = None
        self._landed = None

    def _init_victim(self, victim_surface, cell_rect):
        self._victim_orig = victim_surface
        self._victim_orig_cell = max(int(cell_rect.width), 1)
        self._victim = victim_surface
        self._victim_cache = {}

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

    def _frozen_elapsed(self):
        frozen = self._committed_at if self._committed_at is not None else self._now
        return frozen - self.start_ms

    def _done_after(self, hold_ms):
        if self._online:
            return (self._resolved_at is not None
                    and self._now - self._resolved_at >= SKILLCHECK_RESULT_HOLD_MS)
        return (self._committed_at is not None
                and self._now - self._committed_at >= hold_ms)

    def _signal_color(self, live):
        return Colors.spectate if self._passive else live

    def _cue(self, method):
        if self._audio is not None and not self._passive:
            getattr(self._audio, method)()

    def _emit_verdict(self):
        self._cue("play_skillcheck_win" if self.landed else "play_skillcheck_miss")

    def handle_event(self, event):
        return False

    def update(self, now_ms):
        pass

    def draw(self, window):
        pass

    def relayout(self, cell_rect):
        pass

    def close(self):
        pass

    def set_board_rect(self, board_rect):
        pass

    def victim_scale(self):
        return 1.0

    @property
    def passive(self):
        return self._passive

    @property
    def done(self):
        return False

    @property
    def landed(self):
        return None
