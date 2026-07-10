from chessshootout.server import logging_setup
from chessshootout.server.broadcasts import finalize_and_broadcast, resolve_skillcheck_fail
from chessshootout.server.connections import send
from chessshootout.server.protocol import (
    ConnectionStatusMessage, FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, Reason,
    RematchUpdateMessage,
)
from chessshootout.server.rooms import (
    REMATCH_ABSOLUTE_CAP_SECONDS, REMATCH_IDLE_SECONDS, POST_GAME_DISCONNECT_GRACE,
)
from chessshootout.skillcheck import online
from chessshootout.skillcheck.types import SkillCheckKind


log = logging_setup.get_logger("chess.server.app")


PREGAME_CONNECT_GRACE_SECONDS = 5.0


RESULT_REASON_BY_GAME_RESULT = {
    "white_wins": (Reason.CHECKMATE, "white"),
    "black_wins": (Reason.CHECKMATE, "black"),
    "white_wins_on_time": (Reason.TIMEOUT, "white"),
    "black_wins_on_time": (Reason.TIMEOUT, "black"),
    "draw_stalemate": (Reason.DRAW_STALEMATE, None),
    "draw_repetition": (Reason.DRAW_REPETITION, None),
    "draw_fifty_move": (Reason.DRAW_FIFTY_MOVE, None),
    "draw_insufficient_material": (Reason.DRAW_INSUFFICIENT_MATERIAL, None),
}


class Sweep:

    def __init__(self, rooms, connections, now_provider, now_ms):
        self.rooms = rooms
        self.connections = connections
        self._now = now_provider
        self._now_ms = now_ms

    async def step_all(self):
        await self.step_skillcheck_deadline()
        await self.step_clock_and_first_move_abort()
        await self.step_heartbeat_timeout()
        await self.step_grace_expired()
        self.step_drop_orphans_pre_game()
        await self.step_post_game()
        self.rooms.gc_finished_rooms()

    async def step_skillcheck_deadline(self):
        now_ms = self._now_ms()
        for room in self.rooms.active_rooms():
            pending = room.pending_skillcheck
            if room.result is not None or pending is None:
                continue
            expired = pending.is_expired(now_ms)
            if not expired and pending.kind == SkillCheckKind.AIM:
                challenge = online.challenge_from(
                    pending.kind, pending.seed, pending.value_diff)
                expired = online.aim_expired(
                    challenge, now_ms - pending.start_ms, pending.miss_count)
            if expired:
                log.info("skillcheck deadline room=%s color=%s kind=%s",
                         room.room_id, pending.color, pending.kind.value)
                await resolve_skillcheck_fail(self.rooms, self.connections, room)

    async def step_heartbeat_timeout(self):
        for room, color in list(self.rooms.heartbeat_timed_out_rooms()):
            log.info("heartbeat timeout room=%s color=%s", room.room_id, color)
            self.rooms.mark_disconnected(room.room_id, color)
            opp_ws = self.connections.get_for_color(room, room.opp_color(color))
            if opp_ws is not None:
                await send(opp_ws, ConnectionStatusMessage(opp_state="reconnecting"))

    async def step_clock_and_first_move_abort(self):
        for room in self.rooms.active_rooms():
            if room.result is not None:
                continue
            backend = room.backend
            if (backend is not None and backend.clock is not None
                    and room.first_move_at is not None):
                backend.tick_clock()
                game_result = backend.game_result()
                if game_result in RESULT_REASON_BY_GAME_RESULT:
                    reason, winner = RESULT_REASON_BY_GAME_RESULT[game_result]
                    log.info("game over room=%s reason=%s winner=%s",
                             room.room_id, reason, winner)
                    await finalize_and_broadcast(self.rooms, self.connections, room,
                                                 reason, winner_color=winner)
            now = self._now()
            if (room.is_paired() and room.first_move_at is None
                    and room.started_at is not None
                    and now - room.started_at >= FIRST_MOVE_ABORT_SECONDS):
                log.info("aborted room=%s reason=no_first_move", room.room_id)
                await finalize_and_broadcast(self.rooms, self.connections, room,
                                             Reason.ABORTED)

    async def step_grace_expired(self):
        for room, gone_color in list(self.rooms.grace_expired_rooms()):
            if room.result is not None:
                continue
            slot = room.slot(gone_color)
            if slot is None or slot.disconnected_at is None:
                continue
            if self._now() - slot.disconnected_at < GRACE_SECONDS:
                continue
            if slot.desync_active:
                log.info("aborted room=%s reason=desync gone=%s", room.room_id, gone_color)
                await finalize_and_broadcast(self.rooms, self.connections, room,
                                             Reason.ABORTED_DISCONNECT)
            else:
                winner = room.opp_color(gone_color)
                log.info("abandonment room=%s loser=%s winner=%s",
                         room.room_id, gone_color, winner)
                await finalize_and_broadcast(self.rooms, self.connections, room,
                                             Reason.ABANDONMENT, winner_color=winner)

    def step_drop_orphans_pre_game(self):
        now = self._now()
        for room in self.rooms.active_rooms():
            if room.result is not None or room.first_move_at is not None:
                continue
            white_present = (room.white is not None
                             and self.connections.get_for_color(room, "white") is not None)
            black_present = (room.black is not None
                             and self.connections.get_for_color(room, "black") is not None)
            if (not white_present and not black_present
                    and room.started_at is not None
                    and now - room.started_at >= PREGAME_CONNECT_GRACE_SECONDS):
                log.info("drop room=%s reason=both_disconnected_pre_game", room.room_id)
                self.rooms.drop_room_now(room.room_id)

    async def _notify_rematch(self, room, color, event):
        ws = self.connections.get_for_color(room, color)
        if ws is not None:
            await send(ws, RematchUpdateMessage(event=event))

    async def _notify_both(self, room, event):
        await self._notify_rematch(room, "white", event)
        await self._notify_rematch(room, "black", event)

    async def step_post_game(self):
        now = self._now()
        for room in self.rooms.active_rooms():
            if room.result is None:
                continue
            white_present = self.connections.get_for_color(room, "white") is not None
            black_present = self.connections.get_for_color(room, "black") is not None
            if not white_present and not black_present:
                log.info("drop room=%s reason=both_disconnected_post_result", room.room_id)
                self.rooms.drop_room_now(room.room_id)
                continue
            present_color = "white" if white_present else "black"
            if room.ended_at is not None and now - room.ended_at >= REMATCH_ABSOLUTE_CAP_SECONDS:
                await self._notify_both(room, "window_expired")
                log.info("drop room=%s reason=rematch_cap", room.room_id)
                self.rooms.drop_room_now(room.room_id)
                continue
            if not (white_present and black_present):
                gone_color = "black" if white_present else "white"
                gone = room.slot(gone_color)
                if (gone is not None and gone.disconnected_at is not None
                        and now - gone.disconnected_at >= POST_GAME_DISCONNECT_GRACE):
                    await self._notify_rematch(room, present_color, "opponent_left")
                    log.info("drop room=%s reason=rematch_grace_expired gone=%s",
                             room.room_id, gone_color)
                    self.rooms.drop_room_now(room.room_id)
                continue
            if not room.white.at_result and not room.black.at_result:
                await self._notify_both(room, "window_expired")
                log.info("drop room=%s reason=both_left_result", room.room_id)
                self.rooms.drop_room_now(room.room_id)
                continue
            last = room.last_rematch_activity_at or room.ended_at
            if last is not None and now - last >= REMATCH_IDLE_SECONDS:
                await self._notify_both(room, "window_expired")
                log.info("drop room=%s reason=rematch_idle", room.room_id)
                self.rooms.drop_room_now(room.room_id)
