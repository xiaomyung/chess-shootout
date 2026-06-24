from chessshootout.backend.fen import export_fen
from chessshootout.backend.utils import coord_from_square
from chessshootout.skillcheck.types import SkillCheckOutcome

from chessshootout.server import logging_setup
from chessshootout.server.connections import broadcast, send
from chessshootout.server.protocol import (
    GameStartMessage, ResultMessage, SkillCheckResultMessage)


log = logging_setup.get_logger("chess.server.app")


async def finalize_and_broadcast(rooms, connections, room, reason, winner_color=None):
    rooms.finalize_result(room.room_id, reason, winner_color=winner_color)
    await broadcast(connections, room,
                    ResultMessage(reason=reason, winner_color=winner_color))


async def resolve_skillcheck_fail(connections, room):
    pending = room.pending_skillcheck
    if pending is None:
        return None
    room.pending_skillcheck = None
    room.skillcheck_locks.add((pending.from_sq, pending.to_sq))
    room.skillcheck_log.append(SkillCheckOutcome(
        len(room.backend.move_history) + 1, pending.kind.value, False,
        room.backend.preview_san(pending.from_sq, pending.to_sq, pending.promotion)))
    await broadcast(connections, room, SkillCheckResultMessage(
        won=False,
        from_sq=coord_from_square(pending.from_sq),
        to_sq=coord_from_square(pending.to_sq),
    ))
    return pending


async def broadcast_game_start(connections, room, now):
    fen = export_fen(room.backend)
    started_seconds_ago = max(now() - (room.started_at or now()), 0.0)
    sent = []
    for color in ("white", "black"):
        ws = connections.get_for_color(room, color)
        if ws is None:
            continue
        await send(ws, GameStartMessage(
            fen=fen,
            white_name=room.white.nickname if room.white else "",
            black_name=room.black.nickname if room.black else "",
            time_minutes=room.time_minutes,
            increment_seconds=room.increment_seconds,
            your_color=color,
            started_seconds_ago=started_seconds_ago,
            white_score=room.score_for("white"),
            black_score=room.score_for("black"),
            white_country=room.white.country if room.white else None,
            black_country=room.black.country if room.black else None,
        ))
        sent.append(color)
    room.game_start_broadcast = True
    log.info("game_start broadcast room=%s sent_to=%s elapsed=%.2f",
             room.room_id, sent, started_seconds_ago)
