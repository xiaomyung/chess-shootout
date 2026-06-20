from chessshootout.server import logging_setup
from chessshootout.server.broadcasts import finalize_and_broadcast, resolve_skillcheck_fail
from chessshootout.server.connections import send
from chessshootout.server.protocol import (
    ConnectionStatusMessage, FIRST_MOVE_ABORT_SECONDS, Reason,
)


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
        self.step_drop_orphans_and_post_result()
        self.rooms.gc_finished_rooms()

    async def step_skillcheck_deadline(self):
        now_ms = self._now_ms()
        for room in list(self.rooms._active.values()):
            pending = room.pending_skillcheck
            if room.result is not None or pending is None:
                continue
            if now_ms > pending.expires_at_ms:
                log.info("skillcheck deadline room=%s color=%s kind=%s",
                         room.room_id, pending.color, pending.kind.value)
                await resolve_skillcheck_fail(self.connections, room)

    async def step_heartbeat_timeout(self):
        for room, color in list(self.rooms.heartbeat_timed_out_rooms()):
            log.info("heartbeat timeout room=%s color=%s", room.room_id, color)
            self.rooms.mark_disconnected(room.room_id, color)
            opp_ws = self.connections.get_for_color(room, room.opp_color(color))
            if opp_ws is not None:
                await send(opp_ws, ConnectionStatusMessage(opp_state="reconnecting"))

    async def step_clock_and_first_move_abort(self):
        for room in list(self.rooms._active.values()):
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
            slot = room.slot(gone_color)
            if slot is not None and slot.desync_active:
                log.info("aborted room=%s reason=desync gone=%s", room.room_id, gone_color)
                await finalize_and_broadcast(self.rooms, self.connections, room,
                                             Reason.ABORTED_DISCONNECT)
            else:
                winner = room.opp_color(gone_color)
                log.info("abandonment room=%s loser=%s winner=%s",
                         room.room_id, gone_color, winner)
                await finalize_and_broadcast(self.rooms, self.connections, room,
                                             Reason.ABANDONMENT, winner_color=winner)

    def step_drop_orphans_and_post_result(self):
        now = self._now()
        for room in list(self.rooms._active.values()):
            white_present = (room.white is not None
                             and self.connections.get_for_color(room, "white") is not None)
            black_present = (room.black is not None
                             and self.connections.get_for_color(room, "black") is not None)
            if (room.first_move_at is None
                    and not white_present and not black_present
                    and room.started_at is not None
                    and now - room.started_at >= PREGAME_CONNECT_GRACE_SECONDS):
                log.info("drop room=%s reason=both_disconnected_pre_game", room.room_id)
                self.rooms.drop_room_now(room.room_id)
                continue
            if room.result is not None and not (white_present and black_present):
                log.info("drop room=%s reason=post_result_disconnect", room.room_id)
                self.rooms.drop_room_now(room.room_id)
