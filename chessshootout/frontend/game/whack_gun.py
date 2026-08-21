from typing import Any

import pygame as pg

from chessshootout.backend.pieces import Piece
from chessshootout.backend.utils import Square
from chessshootout.skillcheck.types import SkillCheckKind


class WhackGun:
    """
    The weapon a capturing piece holds while a whack-a-mole check is being
    shot, and the owner of that whole choreography: raised when the check is
    armed, re-aimed every frame, handed to the capture when the player wins and
    dropped on anything else. Nothing outside this class pokes the gun effects
    """

    def __init__(self, screen: Any) -> None:
        """
        Attach the gun to one game screen with nothing drawn yet. A single
        instance lives for the screen's whole life, so every field here is
        state carried between checks rather than per-game setup

        :param screen: the GameScreen this gun belongs to, and its only route
            to the board, the match and the effects layer the weapon lives on
        """
        self.screen = screen
        self.from_sq = None
        self.attacker_type = None
        self.impact_px = None

    def arm(self, from_sq: Square, capturer: Piece | None) -> None:
        """
        Remember who is shooting as a whack check opens, so the right weapon is
        drawn pivoting on the right square. Nothing appears on the board until
        the next frame syncs it

        :param from_sq: square the capturing piece stands on, the gun's pivot
        :param capturer: piece making the capture, which picks the weapon; None
            leaves the gun without a piece and the board with its default
        """
        self.from_sq = from_sq
        self.attacker_type = capturer.type.value if capturer is not None else None

    def sync(self, live: bool, passive: bool, target: Square | None) -> None:
        """
        Keep the drawn gun in step with the check, called once a frame while
        one may be open: it raises the weapon the first time and re-aims it
        after that. A check that has ended, or was never armed, drops the gun
        instead, so a stale weapon is never left on the board

        :param live: whether a whack check is running right now
        :param passive: True in the read-only spectate mirror, where the aim
            follows the opponent's relayed shots instead of this player's mouse
        :param target: square being shot at, used to aim the mirror; None until
            a target is known
        """
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

    def on_hit_px(self, px: tuple[float, float], target: Square | None,
                  kill: bool = False) -> None:
        """
        Fire at the point the mole view reports a hit on: the muzzle flash goes
        off there, and the hit that fills the quota also kills the victim on
        the board at that same point, which is what turns the last pop into the
        capture the player was shooting for

        :param px: hit point in window pixels
        :param target: square the victim stands on, None when there is none
        :param kill: True when this hit completes the quota and takes the piece
        """
        self.impact_px = px
        board = self.screen.board
        board.effects.fire_gun_px(pg.time.get_ticks(), px)
        if kill:
            board.whack_kill_at(px, target, self._attacker_color(),
                                self._victim_piece(target))

    def release(self) -> None:
        """
        Drop the weapon and forget who was holding it, the ordinary ending for
        a missed check, a teardown or a check that never really got going. The
        board plays the gun falling away
        """
        self.clear()
        self.screen.board.effects.release_gun_px(pg.time.get_ticks())

    def end(self, kind: SkillCheckKind) -> None:
        """
        Finish the gun for a check that has just resolved. A whack check hands
        the weapon over to the capture animation, so the same gun fires the
        killing shot; every other kind simply drops it

        :param kind: the check that just ended
        """
        if kind != SkillCheckKind.WHACK:
            self.release()
            return
        self.clear()
        self.screen.board.effects.hand_off_gun_px()

    def clear(self) -> None:
        """
        Forget which piece was shooting and where it last hit, without touching
        what the board is drawing. This is the state half of both the release
        and the hand-off
        """
        self.from_sq = None
        self.attacker_type = None
        self.clear_impact_px()

    def clear_impact_px(self) -> None:
        """
        Forget the last hit point, done whenever the board is resized or
        flipped and those pixels no longer point anywhere real
        """
        self.impact_px = None

    def _aim_px(self, passive: bool, target: Square | None) -> tuple[float, float] | None:
        """
        Work out where the gun should point this frame: the player's own cursor
        while they are shooting, or in the spectate mirror the opponent's last
        relayed hit, falling back to the middle of the target square

        :param passive: True in the read-only spectate mirror
        :param target: square being shot at, None when none is known
        :returns: aim point in window pixels, or None when the mirror has
            nothing to aim at yet
        """
        if not passive:
            return pg.mouse.get_pos()
        if self.impact_px is not None:
            return self.impact_px
        if target is None:
            return None
        return self.screen.board.cell_rect(target).center

    def _attacker_color(self) -> str | None:
        """
        Read the colour of the piece holding the gun, which the board needs so
        a whack kill is credited to the player who shot it

        :returns: the shooter's colour as white or black, or None when no piece
            is armed or the square has since been emptied
        """
        if self.from_sq is None:
            return None
        attacker = self.screen.match.piece_at(self.from_sq)
        return attacker.color.value if attacker is not None else None

    def _victim_piece(self, target: Square | None) -> Piece | None:
        """
        Read the piece being shot at, handed to the board so the kill is
        announced with the right victim

        :param target: square being shot at, None when there is no target
        :returns: the piece standing there, or None when the square is empty or
            unknown
        """
        if target is None:
            return None
        return self.screen.match.piece_at(target)
