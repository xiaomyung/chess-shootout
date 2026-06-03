from chessshootout.server import logging_setup
from chessshootout.server.broadcasts import finalize_and_broadcast
from chessshootout.server.connections import broadcast
from chessshootout.server.protocol import (
    FIRST_MOVE_ABORT_SECONDS, Reason, ResultMessage, StateSyncMessage,
)


log = logging_setup.get_logger("chess.server.app")


BEACON_INTERVAL_SECONDS = 2.5

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

    def __init__(self, rooms, connections, now_provider):
        self.rooms = rooms
        self.connections = connections
        self._now = now_provider
        self._last_beacon = {}

    async def step_all(self):
        await self.step_clock_and_first_move_abort()
        await self.step_grace_expired()
        await self.step_state_sync_beacon()
        self.step_drop_orphans_and_post_result()
        self.rooms.gc_finished_rooms()

    async def step_state_sync_beacon(self):
        now = self._now()
        active_ids = set()
        for room in list(self.rooms._active.values()):
            if (room.result is not None or room.first_move_at is None
                    or not room.is_paired() or room.backend is None):
                continue
            active_ids.add(room.room_id)
            if now - self._last_beacon.get(room.room_id, 0.0) < BEACON_INTERVAL_SECONDS:
                continue
            self._last_beacon[room.room_id] = now
            await broadcast(self.connections, room,
                            StateSyncMessage(ply=len(room.backend.move_history)))
        for room_id in self._last_beacon.keys() - active_ids:
            del self._last_beacon[room_id]

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
        for room, abandoned_color in list(self.rooms.grace_expired_rooms()):
            winner = room.opp_color(abandoned_color)
            log.info("abandonment room=%s loser=%s winner=%s",
                     room.room_id, abandoned_color, winner)
            self.rooms.finalize_abandonment(room.room_id, abandoned_color)
            await broadcast(self.connections, room,
                              ResultMessage(reason=Reason.ABANDONMENT,
                                              winner_color=winner))

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
