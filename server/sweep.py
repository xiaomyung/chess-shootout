from server import logging_setup
from server.connections import broadcast
from server.protocol import FIRST_MOVE_ABORT_SECONDS, Reason, ResultMessage


log = logging_setup.get_logger("chess.server.app")


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

    async def step_all(self):
        await self.step_clock_and_first_move_abort()
        await self.step_grace_expired()
        self.step_drop_orphans_and_post_result()
        self.rooms.gc_finished_rooms()

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
                    self.rooms.finalize_result(room.room_id, reason,
                                                 winner_color=winner)
                    await broadcast(self.connections, room,
                                      ResultMessage(reason=reason, winner_color=winner))
            now = self._now()
            if (room.is_paired() and room.first_move_at is None
                    and room.started_at is not None
                    and now - room.started_at >= FIRST_MOVE_ABORT_SECONDS):
                log.info("aborted room=%s reason=no_first_move", room.room_id)
                self.rooms.finalize_result(room.room_id, Reason.ABORTED)
                await broadcast(self.connections, room,
                                  ResultMessage(reason=Reason.ABORTED))

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
        for room in list(self.rooms._active.values()):
            white_present = (room.white is not None
                             and self.connections.get_for_color(room, "white") is not None)
            black_present = (room.black is not None
                             and self.connections.get_for_color(room, "black") is not None)
            if (room.first_move_at is None
                    and not white_present and not black_present):
                log.info("drop room=%s reason=both_disconnected_pre_game", room.room_id)
                self.rooms.drop_room_now(room.room_id)
                continue
            if room.result is not None and not (white_present and black_present):
                log.info("drop room=%s reason=post_result_disconnect", room.room_id)
                self.rooms.drop_room_now(room.room_id)
