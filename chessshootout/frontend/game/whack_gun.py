import pygame as pg

from chessshootout.skillcheck.types import SkillCheckKind


class WhackGun:

    def __init__(self, screen):
        self.screen = screen
        self.from_sq = None
        self.attacker_type = None
        self.impact_px = None

    def arm(self, from_sq, capturer):
        self.from_sq = from_sq
        self.attacker_type = capturer.type.value if capturer is not None else None

    def sync(self, live, passive, target):
        if not live or self.from_sq is None:
            self.release()
            return
        board = self.screen.board
        fx = board.effects
        now = pg.time.get_ticks()
        target_px = self._aim_px(passive, target)
        if not fx.has_gun_px():
            fx.hold_gun_px(now_ms=now, attacker_type=self.attacker_type,
                           from_sq=self.from_sq, cell_size=board.cell_size,
                           target_px=target_px)
        fx.aim_gun_px(target_px, now)

    def on_hit_px(self, px, target, kill=False):
        self.impact_px = px
        board = self.screen.board
        board.effects.fire_gun_px(pg.time.get_ticks(), px)
        if kill:
            board.whack_kill_at(px, target, self._attacker_color(),
                                self._victim_piece(target))

    def release(self):
        self.clear()
        self.screen.board.effects.release_gun_px(pg.time.get_ticks())

    def end(self, kind):
        if kind != SkillCheckKind.WHACK:
            self.release()
            return
        self.clear()
        self.screen.board.effects.hand_off_gun_px()

    def clear(self):
        self.from_sq = None
        self.attacker_type = None
        self.impact_px = None

    def _aim_px(self, passive, target):
        if not passive:
            return pg.mouse.get_pos()
        if self.impact_px is not None:
            return self.impact_px
        if target is None:
            return None
        return self.screen.board.cell_rect(target).center

    def _attacker_color(self):
        if self.from_sq is None:
            return None
        attacker = self.screen.match.piece_at(self.from_sq)
        return attacker.color.value if attacker is not None else None

    def _victim_piece(self, target):
        if target is None:
            return None
        return self.screen.match.piece_at(target)
