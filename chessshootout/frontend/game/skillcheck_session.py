import logging
from collections.abc import Callable
from typing import Any, NamedTuple, cast

import pygame as pg

from chessshootout.backend.pieces import Piece, PIECE_VALUES, PieceType
from chessshootout.backend.utils import (
    BOARD_SIZE, PROMO_LETTER_BY_TYPE, Square, coord_from_square)
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.game.whack_gun import WhackGun
from chessshootout.frontend.skillcheck.registry import CheckSpec, build_controller
from chessshootout.skillcheck import mole
from chessshootout.skillcheck.online import adjudicated_flipped, skillcheck_deadline_ms
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome, whiffs_by_ply
from chessshootout.skillcheck.wheel import period_for_diff, placement_square


log = logging.getLogger("chess.frontend")

SUPPRESSING_KINDS = frozenset(
    {SkillCheckKind.AIM, SkillCheckKind.WHACK, SkillCheckKind.COMBO})


class CheckContext(NamedTuple):
    """
    The move one skill check is being fought over, carried from the moment the
    check opens to the moment it resolves. Winning lands exactly this move;
    missing locks this from and to pair for the rest of the turn
    """

    from_sq: Square
    to_sq: Square
    promo_type: PieceType | None
    kind: SkillCheckKind


class SkillCheckSession:
    """
    The game screen's skill-check department: it decides whether a capture or
    promotion has to be shot for, opens the overlay for the player or the
    read-only mirror of the opponent's shot, and files what happened into the
    log the PGN comments are written from. Online it never judges anything --
    the server owns the seeds, the geometry and every verdict
    """

    def __init__(self, screen: Any) -> None:
        """
        Set the department up for the life of the game screen, with no check
        open and an empty log. New games clear it through the reset calls
        rather than by building another one

        :param screen: the GameScreen this session belongs to, and its only
            route to the match, the board, the overlay and the coordinator
        """
        self.screen = screen
        self.app = screen.app
        self.whack_gun = WhackGun(screen)
        self.skillcheck_log: list[SkillCheckOutcome] = []
        self._skillcheck_fired_at_ms: int | None = None
        self.clear_online_skillcheck_state()

    def skillcheck_gate(self, from_sq: Square, to_sq: Square,
                        promo_type: PieceType | None = None) -> bool:
        """
        Stand between a move the player is trying to make and the board landing
        it -- the gate the board asks before every drop. A move already fluffed
        this turn, or one made while a check is on screen, is simply refused;
        online the move goes to the server instead of landing; offline a
        capture or promotion may fire a check here and now

        :param from_sq: square the piece is leaving
        :param to_sq: square it is aimed at
        :param promo_type: piece a promoting pawn was told to become, None for
            an ordinary move
        :returns: True when the move is being held back, False to let the board
            play it normally
        """
        screen = self.screen
        if screen.skillcheck.is_locked(from_sq, to_sq) or self.skillcheck_swallows_input():
            return True
        if screen.variant == Variant.ONLINE:
            return self._online_move_gate(from_sq, to_sq, promo_type)
        kind = screen.skillcheck.select(screen.match.backend, from_sq, to_sq)
        if kind == SkillCheckKind.NONE:
            return False
        diff = self._capture_value_diff(from_sq, to_sq, promo_type)
        seed = "{}:{}:{}{}{}{}:{}".format(
            screen.skillcheck.seed, len(screen.match.move_history),
            from_sq.row, from_sq.col, to_sq.row, to_sq.col, kind.value)
        return self.open_skillcheck_overlay(
            kind, seed, diff, self._skillcheck_deadline_ms(),
            from_sq, to_sq, promo_type, self._captured_value(from_sq, to_sq), online=False)

    def _online_move_gate(self, from_sq: Square, to_sq: Square,
                          promo_type: PieceType | None = None) -> bool:
        """
        Hold a capture or promotion back in an online game and send it to the
        server, which alone decides whether a check fires and whether the move
        lands. Quiet moves are let through here and reported by the match's own
        move hook, so only the shooting moves take this path

        :param from_sq: square the piece is leaving
        :param to_sq: square it is aimed at
        :param promo_type: piece a promoting pawn was told to become, None for
            an ordinary move
        :returns: True when the move was sent and must not land locally
        """
        screen = self.screen
        if to_sq not in screen.match.legal_moves_from(from_sq):
            return False
        piece = screen.match.piece_at(from_sq)
        is_capture = screen.board.capture_victim_square(piece, from_sq, to_sq) is not None
        is_promotion = (piece.type == PieceType.PAWN
                        and to_sq.row in (0, BOARD_SIZE - 1))
        if not (is_capture or is_promotion):
            return False
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type is not None else None
        self.app.coordinator.send_move(
            coord_from_square(from_sq), coord_from_square(to_sq), promo_letter)
        self.pending_online_move: tuple[Square, Square, PieceType | None] | None = (
            from_sq, to_sq, promo_type)
        return True

    def open_skillcheck_overlay(self, kind: SkillCheckKind, seed: str, value_diff: int,
                                deadline_ms: float, from_sq: Square, to_sq: Square,
                                promo_type: PieceType | None, captured_value: int = 0, *,
                                online: bool, elapsed_ms: float = 0, miss_count: int = 0,
                                progress: int = 0, passive: bool = False) -> bool:
        """
        Put a skill check on screen and arm everything that goes with it: the
        overlay itself, the pieces the board has to stop drawing and, for
        whack, the gun in the capturer's hand. The elapsed time is honoured, so
        a check adopted after a reconnect carries on where it stood instead of
        starting again

        :param kind: which mini-game runs
        :param seed: the check's seed, which fixes its layout for both players
        :param value_diff: capturer value minus captured value, which sets how
            hard the check is
        :param deadline_ms: how long the whole check may run, in milliseconds
        :param from_sq: square the capturing or promoting piece stands on
        :param to_sq: square the move is aimed at
        :param promo_type: piece a promoting pawn was told to become, or None
        :param captured_value: material value of the piece being taken, which
            sets the whack hit quota
        :param online: True when the server is judging this check
        :param elapsed_ms: how much of the deadline has already gone
        :param miss_count: shots already missed, for a check resumed mid-flight
        :param progress: hits or prompts already answered, likewise
        :param passive: True for the read-only mirror of the opponent's check
        :returns: True when an overlay was opened, False when this kind has no
            controller to open
        """
        screen = self.screen
        target = self._skillcheck_render_square(kind, seed, value_diff, from_sq, to_sq)
        capturer = screen.match.piece_at(from_sq)
        controller = self._build_check_controller(
            kind, seed, value_diff, deadline_ms, from_sq, to_sq, target, capturer,
            captured_value, online=online, elapsed_ms=elapsed_ms, miss_count=miss_count,
            progress=progress, passive=passive)
        if controller is None:
            return False
        log.info("skillcheck fired kind=%s ply=%d online=%s passive=%s",
                 kind.value, len(screen.match.move_history) + 1, online, passive)
        self._arm_check_state(kind, seed, target, from_sq, capturer, elapsed_ms)
        on_done = self._on_online_skillcheck_done if online else self._on_skillcheck_done
        screen.skillcheck_overlay.start(
            controller, CheckContext(from_sq, to_sq, promo_type, kind), on_done)
        return True

    def _build_check_controller(self, kind: SkillCheckKind, seed: str, value_diff: int,
                                deadline_ms: float, from_sq: Square, to_sq: Square,
                                target: Square, capturer: Piece | None,
                                captured_value: int, *, online: bool, elapsed_ms: float,
                                miss_count: int, progress: int, passive: bool) -> Any:
        """
        Assemble the controller that runs one check, gathering everything the
        four kinds might want -- geometry, sprites, sounds and the shot hook --
        into a single spec the registry builds from. The whack pit layout is
        worked out again from the seed rather than taken off the wire, so what
        the player shoots at is what the server judges against

        :param kind: which mini-game runs
        :param seed: the check's seed, which fixes its layout for both players
        :param value_diff: capturer value minus captured value
        :param deadline_ms: how long the whole check may run, in milliseconds
        :param from_sq: square the capturing or promoting piece stands on
        :param to_sq: square the move is aimed at, where the pits are dug round
        :param target: square the check is drawn over, normally the victim
        :param capturer: piece doing the shooting, None when the square is bare
        :param captured_value: material value of the piece being taken
        :param online: True when shots are reported to the server
        :param elapsed_ms: how much of the deadline has already gone
        :param miss_count: shots already missed
        :param progress: hits or prompts already answered
        :param passive: True for the read-only mirror, which sends nothing
        :returns: the controller for this kind, or None when there is no
            builder for it
        """
        screen = self.screen
        hole_squares = None
        if kind == SkillCheckKind.WHACK:
            hole_squares = mole.holes_for(
                seed, captured_value, (to_sq.row, to_sq.col),
                screen.match.state, BOARD_SIZE)
        attacker_surface = (self._piece_surface(capturer)
                            if kind == SkillCheckKind.COMBO else None)
        spec = CheckSpec(
            seed=seed, cell_rect=screen.board.cell_rect(target),
            now_ms=pg.time.get_ticks() - int(elapsed_ms), deadline_ms=deadline_ms,
            period_ms=period_for_diff(value_diff), value_diff=value_diff,
            victim_surface=self._victim_surface(target), board_rect=screen.board.rect,
            geom=lambda sq: screen.board.cell_rect(cast(Square, sq)).center, from_sq=from_sq,
            victim_sq=target, attacker_type=capturer.type.value if capturer else None,
            shot_sound=self._shot_sound_for(capturer),
            on_shot=None if passive else (self._send_skillcheck_shot if online else None),
            miss_count=miss_count, passive=passive, audio=self.app.sound_manager,
            hole_squares=hole_squares, captured_value=captured_value, progress=progress,
            attacker_surface=attacker_surface, on_hit_px=self._on_whack_hit_px,
            mirror_targets=passive and online,
            last_hit_pop=self.online_last_hit_pop if online else -1,
            adjudicated_flipped=self._mover_adjudicated_flipped(online, passive))
        return build_controller(kind, spec)

    def _mover_adjudicated_flipped(self, online: bool, passive: bool) -> bool | None:
        """
        Say which way up the board was for the player actually shooting, which
        the whack hit box needs because a mole is drawn above its hole. In the
        mirror the shooter is the opponent, so the local orientation is flipped
        before asking

        :param online: True when the server is judging, the only case that
            needs this
        :param passive: True in the mirror, where the opponent is shooting
        :returns: True when the shooter sees the board from Black's end, or
            None offline, where nobody else has to agree
        """
        if not online:
            return None
        side = self.screen._chosen_side
        if passive:
            side = "black" if side == "white" else "white"
        return adjudicated_flipped(side)

    def _arm_check_state(self, kind: SkillCheckKind, seed: str, target: Square,
                         from_sq: Square, capturer: Piece | None,
                         elapsed_ms: float) -> None:
        """
        Take ownership of the board while a check runs. This is the one place
        the board's suppressed squares are set -- the victim while an aim,
        whack or combo check is being shot at it, and for combo the capturer as
        well so it is not drawn twice -- and the one place the whack gun is
        armed, after which WhackGun alone drives it

        :param kind: which mini-game is starting
        :param seed: the check's seed, kept for the mole's parting taunt
        :param target: square the check is drawn over, whose piece is hidden
        :param from_sq: square the capturing piece stands on, the gun's pivot
        :param capturer: piece doing the shooting, None when the square is bare
        :param elapsed_ms: how much of the deadline has already gone, backdated
            into the fired-at stamp so the logged duration stays honest
        """
        board = self.screen.board
        self._skillcheck_fired_at_ms = pg.time.get_ticks() - int(elapsed_ms)
        self.skillcheck_target: Square | None = target
        self.active_kind: SkillCheckKind | None = kind
        self.active_seed: str | None = seed
        if kind == SkillCheckKind.WHACK:
            self.whack_gun.arm(from_sq, capturer)
        board.aim_suppressed_square = target if kind in SUPPRESSING_KINDS else None
        board.attacker_suppressed_square = (
            from_sq if kind == SkillCheckKind.COMBO else None)

    def open_spectate_overlay(self, kind: SkillCheckKind, seed: str, value_diff: int,
                              deadline_ms: float, from_sq: Square, to_sq: Square,
                              promo_type: PieceType | None, captured_value: int = 0, *,
                              elapsed_ms: float = 0, miss_count: int = 0,
                              progress: int = 0) -> None:
        """
        Open the read-only mirror of the check the opponent is shooting, so
        both players watch the same shootout instead of one of them staring at
        a frozen board. It takes no input of its own -- every shot in it is one
        the server relayed

        :param kind: which mini-game the opponent is playing
        :param seed: the check's seed, which gives both sides the same layout
        :param value_diff: capturer value minus captured value
        :param deadline_ms: how long the whole check may run, in milliseconds
        :param from_sq: square the opponent's piece stands on
        :param to_sq: square their move is aimed at
        :param promo_type: piece a promoting pawn was told to become, or None
        :param captured_value: material value of the piece being taken
        :param elapsed_ms: how much of the deadline has already gone
        :param miss_count: shots they have already missed
        :param progress: hits or prompts they have already answered
        """
        screen = self.screen
        screen.board.jump_to_review_ply(None)
        self.pending_online_move = None
        self.online_skillcheck: CheckContext | None = CheckContext(
            from_sq, to_sq, promo_type, kind)
        self.online_spectate_kind: SkillCheckKind | None = kind
        self.online_was_spectator = True
        self.online_skillcheck_opened_ms: int | None = pg.time.get_ticks() - int(elapsed_ms)
        self.open_skillcheck_overlay(
            kind, seed, value_diff, deadline_ms, from_sq, to_sq, promo_type, captured_value,
            online=True, passive=True, elapsed_ms=elapsed_ms, miss_count=miss_count,
            progress=progress)

    def skillcheck_swallows_input(self) -> bool:
        """
        Whether the overlay is taking every event right now, which it does
        while this player is shooting. The mirror never swallows anything --
        there is nothing in it for the watcher to aim

        :returns: True while events belong to the overlay instead of the board
        """
        overlay = self.screen.skillcheck_overlay
        return overlay.is_active() and not overlay.is_passive()

    def sync_aim_victim(self) -> None:
        """
        Hand the board the piece a steady-aim check is shrinking, once a frame,
        so the victim is drawn by the check rather than by the board. Anything
        else -- another kind, a closed overlay -- puts the board back to normal
        """
        screen = self.screen
        fx = screen.board.effects
        victim = screen.board.aim_suppressed_square
        if (victim is not None and self.active_kind == SkillCheckKind.AIM
                and screen.skillcheck_overlay.is_active()):
            fx.aim_victim = victim
            fx.aim_victim_scale = screen.skillcheck_overlay.aim_victim_scale()
        else:
            fx.aim_victim = None
            fx.aim_victim_scale = 1.0

    def sync_whack_gun(self) -> None:
        """
        Let the gun follow the cursor while a whack check is live, once a
        frame. It only reports whether a check is running -- the choreography
        itself belongs to WhackGun
        """
        overlay = self.screen.skillcheck_overlay
        live = self.active_kind == SkillCheckKind.WHACK and overlay.is_active()
        self.whack_gun.sync(live, overlay.is_passive(), self.skillcheck_target)

    def clear_whack_impact_px(self) -> None:
        """
        Forget where the last whack hit landed, called when the board is
        resized or flipped and those pixels stop meaning anything
        """
        self.whack_gun.clear_impact_px()

    def _on_whack_hit_px(self, px: tuple[float, float], kill: bool = False) -> None:
        """
        Pass a hit the mole view registered on to the gun, which fires at that
        point and, on the hit that fills the quota, kills the piece there

        :param px: hit point in window pixels
        :param kill: True when this hit completes the quota
        """
        self.whack_gun.on_hit_px(px, self.skillcheck_target, kill=kill)

    def _send_skillcheck_shot(self, client_elapsed_ms: float, direction: str | None = None,
                              target: tuple[float, float] | None = None) -> None:
        """
        Report one shot to the server, the only thing a live check ever sends.
        Nothing but timing and aim travels -- the server holds the geometry and
        decides for itself whether the shot hit

        :param client_elapsed_ms: how far into the check the shot happened, in
            milliseconds measured on this machine
        :param direction: answer to a combo prompt, None for other kinds
        :param target: aim point in board space as (row, column), None when the
            kind does not aim
        """
        target_row, target_col = target if target is not None else (None, None)
        self.app.coordinator.send_skill_check_shot(
            client_elapsed_ms, direction=direction,
            target_row=target_row, target_col=target_col)

    def _clear_active_check_fields(self) -> None:
        """
        Forget everything about the check that was running -- which kind, which
        seed, which square, and all the online bookkeeping around it -- so the
        next one starts from nothing
        """
        self.skillcheck_target = None
        self.active_kind = None
        self.active_seed = None
        self.online_skillcheck = None
        self.online_spectate_kind = None
        self.online_was_spectator = False
        self.online_skillcheck_opened_ms = None
        self.online_verdict_action: Callable[[], None] | None = None
        self.online_last_hit_pop = -1

    def clear_online_skillcheck_state(self) -> None:
        """
        Wipe the whole department back to nothing, used when a new game starts
        and when an online session is dropped. A move still waiting on the
        server is forgotten too, since no answer to it can arrive any more
        """
        self._clear_active_check_fields()
        self.pending_online_move = None
        self.whack_gun.clear()

    def teardown_skillcheck_overlay(self) -> None:
        """
        Abandon a check without resolving it -- the screen is leaving, the game
        has ended, or a resync is about to rebuild everything. The board gets
        its suppressed squares back and the gun is dropped, so no piece is left
        invisible behind an overlay that is gone
        """
        screen = self.screen
        screen.skillcheck_overlay.cancel()
        self.whack_gun.release()
        screen.board.aim_suppressed_square = None
        screen.board.attacker_suppressed_square = None
        self._clear_active_check_fields()

    def _release_active_check(self, kind: SkillCheckKind) -> None:
        """
        Give the board back once a check has been fought to a verdict: the
        suppressed squares are cleared here and nowhere else on this path, and
        the gun is either handed to the capture (a whack win) or dropped

        :param kind: the check that just resolved
        """
        self.whack_gun.end(kind)
        board = self.screen.board
        board.aim_suppressed_square = None
        board.attacker_suppressed_square = None
        self.active_kind = None
        self.active_seed = None

    def _on_online_skillcheck_done(self, context: CheckContext,
                                   landed: bool | None) -> None:
        """
        Close out a server-judged check once the overlay has finished playing
        the verdict. The consequence the server dictated was parked until now,
        so the move lands or locks only after the shot has been seen, and a
        lost whack leaves the mole's taunt on the square

        :param context: the move this check was fought over
        :param landed: the server's verdict, None when the overlay closed
            without one
        """
        kind = context.kind
        target = self.skillcheck_target
        seed = self.active_seed
        was_spectator = self.online_was_spectator
        self.online_was_spectator = False
        action = self.online_verdict_action
        self.online_verdict_action = None
        self._release_active_check(kind)
        self.skillcheck_target = None
        if action is not None:
            action()
        if kind == SkillCheckKind.WHACK and landed is False and target is not None:
            self._show_whack_taunt(target, seed, not was_spectator)

    def _show_whack_taunt(self, square: Square | None, seed: str | None,
                          play_sound: bool) -> None:
        """
        Let the mole jeer over the square it survived on after a lost whack
        check. The jeer is drawn from the seed, so both players read the same
        one, and only the player who missed has to hear it

        :param square: square to tag, None when there is nothing to tag
        :param seed: the lost check's seed, which picks the jeer
        :param play_sound: True for the player who missed, False in the mirror
        """
        if square is None:
            return
        board = self.screen.board
        board.effects.taunt_tag(pg.time.get_ticks(), mole.pick_taunt(cast(str, seed)),
                                square, board.cell_size)
        if play_sound:
            self.app.sound_manager.play_mole_taunt()

    def _skillcheck_render_square(self, kind: SkillCheckKind, seed: str, value_diff: int,
                                  from_sq: Square, to_sq: Square) -> Square:
        """
        Decide which square the check is drawn over. The aiming kinds sit on
        the piece being shot at, which for an en-passant capture is not the
        square being moved to; the wheel may wander off to a seeded square
        instead, which is the same square on both screens

        :param kind: which mini-game is being drawn
        :param seed: the check's seed, which fixes any relocation
        :param value_diff: capturer value minus captured value, which sets how
            often the wheel wanders
        :param from_sq: square the capturing piece stands on
        :param to_sq: square the move is aimed at
        :returns: the square to draw the check over
        """
        screen = self.screen
        if kind in SUPPRESSING_KINDS:
            capturer = screen.match.piece_at(from_sq)
            if capturer is not None:
                victim_sq = screen.board.capture_victim_square(capturer, from_sq, to_sq)
                if victim_sq is not None:
                    return cast(Square, victim_sq)
            return to_sq
        square = placement_square(seed, value_diff,
                                  self._placement_exclusions(from_sq, to_sq), BOARD_SIZE)
        return Square(square[0], square[1]) if square is not None else to_sq

    def _placement_exclusions(self, from_sq: Square, to_sq: Square) -> set[tuple[int, int]]:
        """
        Name the squares a wandering wheel must keep off -- the move's own two
        -- so the dial never hides the piece the player is trying to watch

        :param from_sq: square the capturing piece stands on
        :param to_sq: square the move is aimed at
        :returns: those squares as (row, column) pairs
        """
        return {(from_sq.row, from_sq.col), (to_sq.row, to_sq.col)}

    def _victim_surface(self, square: Square) -> pg.Surface | None:
        """
        Fetch the sprite of the piece being shot at, which the overlay draws
        itself now that the board has stopped drawing it

        :param square: square the check is aimed at
        :returns: the piece's scaled sprite, or None when the square is empty
        """
        return self._piece_surface(self.screen.match.piece_at(square))

    def _piece_surface(self, piece: Piece | None) -> pg.Surface | None:
        """
        Look one piece's sprite up at the board's current size, so an overlay
        draws pieces at exactly the scale the board does

        :param piece: piece to look up, None when there is none
        :returns: the scaled sprite, or None when there is no piece or no
            sprite for it yet
        """
        if piece is None:
            return None
        return cast("pg.Surface | None",
                    self.screen.board.piece_images_scaled.get((piece.type, piece.color)))

    def _shot_sound_for(self, capturer: Piece | None) -> Callable[[], None] | None:
        """
        Give the check the bang its shooter makes, so every shot fired inside
        an overlay sounds like the piece holding the weapon

        :param capturer: piece doing the shooting, None when the square is bare
        :returns: a callable that plays that piece's shot, or None when there
            is nothing to sound
        """
        if capturer is None:
            return None
        piece_type = capturer.type
        return lambda: self.app.sound_manager.play_capture(piece_type)

    def _victim_piece(self, from_sq: Square, to_sq: Square) -> Piece | None:
        """
        Find the piece a move would take, en passant included, where the victim
        does not stand on the square being moved to

        :param from_sq: square the capturing piece stands on
        :param to_sq: square the move is aimed at
        :returns: the piece that would be taken, or None when nothing would
        """
        screen = self.screen
        capturer = screen.match.piece_at(from_sq)
        if capturer is None:
            return None
        victim_sq = screen.board.capture_victim_square(capturer, from_sq, to_sq)
        return screen.match.piece_at(victim_sq) if victim_sq is not None else None

    def _capture_value_diff(self, from_sq: Square, to_sq: Square,
                            promo_type: PieceType | None) -> int:
        """
        Measure how greedy a move is, which is what makes a check harder or
        easier: taking something big with something small is generous and
        forgiving, snapping up a pawn with a queen is not

        :param from_sq: square the capturing or promoting piece stands on
        :param to_sq: square the move is aimed at
        :param promo_type: piece a promoting pawn was told to become, or None
        :returns: capturer value minus captured value, or the equivalent for a
            promotion; zero when nothing is taken
        """
        if promo_type is not None:
            return PIECE_VALUES[PieceType.PAWN] - PIECE_VALUES.get(promo_type, 0)
        victim = self._victim_piece(from_sq, to_sq)
        if victim is None:
            return 0
        capturer = self.screen.match.piece_at(from_sq)
        return PIECE_VALUES.get(capturer.type, 0) - PIECE_VALUES.get(victim.type, 0)

    def _captured_value(self, from_sq: Square, to_sq: Square) -> int:
        """
        Give the material worth of the piece a move would take, which sets how
        many pops a whack check demands -- the bigger the prize, the more
        shooting it costs

        :param from_sq: square the capturing piece stands on
        :param to_sq: square the move is aimed at
        :returns: the victim's value, zero when nothing would be taken
        """
        victim = self._victim_piece(from_sq, to_sq)
        return PIECE_VALUES.get(victim.type, 0) if victim is not None else 0

    def _on_skillcheck_done(self, context: CheckContext, landed: bool | None) -> None:
        """
        Settle an offline check the moment the overlay finishes. Winning lands
        the move that was being fought over; missing costs the player that move
        for the rest of the turn -- it is locked, the piece is put down, the
        shot is played out and a beaten mole gets its jeer

        :param context: the move this check was fought over
        :param landed: True when the player won it
        """
        screen = self.screen
        from_sq, to_sq = context.from_sq, context.to_sq
        promo_type, kind = context.promo_type, context.kind
        seed = self.active_seed
        aim_victim = screen.board.aim_suppressed_square
        self._release_active_check(kind)
        if landed:
            screen.board.apply_gated_move(from_sq, to_sq, promo_type)
            self.record_skillcheck(kind, True, len(screen.match.move_history))
        else:
            promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
            self.record_skillcheck(
                kind, False, len(screen.match.move_history) + 1,
                screen.match.backend.preview_san(from_sq, to_sq, promo_letter))
            screen.skillcheck.lock(from_sq, to_sq)
            log.info("skillcheck move locked from=%s to=%s",
                     coord_from_square(from_sq), coord_from_square(to_sq))
            screen.board.selected_square = None
            if screen.board.premove_color == screen.match.current_turn():
                screen.board.clear_premoves()
            screen.board.trigger_skillcheck_fail(
                from_sq, to_sq, on_fire=self.on_skillcheck_miss_fire)
            if aim_victim is not None and kind != SkillCheckKind.WHACK:
                screen.board.restore_piece(aim_victim)
            if kind == SkillCheckKind.WHACK:
                self._show_whack_taunt(aim_victim, seed, True)

    def on_skillcheck_miss_fire(self, piece_type: PieceType) -> None:
        """
        Fire the weapon sound for a shot that missed, at the frame the board's
        miss choreography pulls the trigger

        :param piece_type: kind of piece that fired, which picks the weapon
        """
        self.app.sound_manager.play_capture(piece_type)

    def record_skillcheck(self, kind: SkillCheckKind | str | None, won: bool, ply: int,
                          san: str = "") -> None:
        """
        File a resolved check in the game's log, which the rail marks fluffed
        moves from and the saved PGN turns into move comments. A move that was
        never played is filed under the ply it would have been, with the
        notation it would have had

        :param kind: which mini-game ran, as the enum or its wire value; None
            files nothing
        :param won: True when the shooter landed it
        :param ply: half-move the check belongs to, counted from one
        :param san: notation of the move that was locked, empty for a win
        """
        if kind is None:
            return
        kind_value = kind.value if isinstance(kind, SkillCheckKind) else kind
        elapsed_ms = (pg.time.get_ticks() - self._skillcheck_fired_at_ms
                      if self._skillcheck_fired_at_ms is not None else None)
        log.info("skillcheck resolved kind=%s ply=%d won=%s elapsed_ms=%s",
                 kind_value, ply, won, elapsed_ms)
        self.skillcheck_log.append(SkillCheckOutcome(ply, kind_value, won, san))

    def drop_skillcheck_log_from(self, ply: int) -> None:
        """
        Forget the checks belonging to plies that have been taken back, so an
        undone move does not leave its shootout history in the saved game

        :param ply: first ply to drop, counted from one; everything from there
            on goes
        """
        self.skillcheck_log = [e for e in self.skillcheck_log if e.ply < ply]

    def record_online_fail(self, pending: CheckContext | None, from_sq: Square,
                           to_sq: Square) -> None:
        """
        File a check the server says was lost, working out the notation of the
        move that never happened from the position as it still stands. It is
        written down before the overlay is torn down, so the miss survives a
        game that ends the same instant

        :param pending: the check that was open, None when none was
        :param from_sq: square the failed move started from
        :param to_sq: square it was aimed at
        """
        if pending is None:
            return
        promo_type = pending.promo_type
        promo_letter = PROMO_LETTER_BY_TYPE.get(promo_type) if promo_type else None
        self.record_skillcheck(
            pending.kind, False, len(self.screen.match.move_history) + 1,
            self.screen.match.backend.preview_san(from_sq, to_sq, promo_letter))

    def apply_resumed_skillcheck_log(self, wire: list[dict[str, Any]]) -> None:
        """
        Replace the whole shootout log with the server's after a reconnect or a
        resync, since the server has kept the authoritative record while this
        client was away

        :param wire: logged checks from the resume snapshot, each carrying its
            ply, kind, outcome and notation
        """
        self.skillcheck_log = [
            SkillCheckOutcome(e["ply"], e["kind"], e["won"], e.get("san", ""))
            for e in wire]

    def skillcheck_whiffs(self) -> dict[int, list[tuple[str, str]]]:
        """
        Report the misses by ply, which is how the rail's move list marks the
        moves a player shot at and lost

        :returns: ply number to its misses as (label, notation) pairs; plies
            with no miss are absent
        """
        return whiffs_by_ply(self.skillcheck_log)

    def _skillcheck_deadline_ms(self) -> int:
        """
        Give how long a check may run in this game, which is the standard
        deadline or a tenth of the starting clock, whichever is shorter, so a
        bullet game never spends a big slice of itself on mini-games. Online
        the server sends its own figure and this is not consulted

        :returns: the deadline in milliseconds
        """
        time_control = self.screen._time_control
        initial = time_control[0] if time_control and time_control[0] else 0
        return int(skillcheck_deadline_ms(initial))
