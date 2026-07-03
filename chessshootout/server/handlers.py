import json
import secrets

from pydantic import ValidationError

from chessshootout.backend.fen import export_fen
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import (
    PROMO_TYPE_BY_LETTER, coord_from_square, square_from_coord,
)
from chessshootout.server import logging_setup
from chessshootout.server.connections import broadcast, send
from chessshootout.server.broadcasts import (
    broadcast_game_start, finalize_and_broadcast, resolve_skillcheck_fail)
from chessshootout.server.protocol import (
    ClockSnapshot, ConnectionStatusMessage, DrawOfferedMessage, DrawResponseMessage,
    ErrorMessage, GIVE_TIME_SECONDS, GIVE_TIME_TICK_MS, GiveTimeMessage,
    MoveAppliedMessage, MoveMessage,
    PingMessage, PongMessage, Reason,
    RematchRequestMessage, RematchResponseMessage, RematchUpdateMessage,
    ResyncDirectiveMessage,
    SkillCheckRequiredMessage, SkillCheckShotMessage, SkillCheckSpectateMessage,
    SkillCheckSpectateShotMessage,
    TakebackAppliedMessage, TakebackOfferedMessage,
    TakebackResponseMessage, TimeGrantedMessage,
)
from chessshootout.server.rooms import PendingSkillCheck
from chessshootout.server.sweep import RESULT_REASON_BY_GAME_RESULT
from chessshootout.skillcheck import online
from chessshootout.skillcheck.triggers import compute_facts
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome


log = logging_setup.get_logger("chess.server.app")


def _color_to_move(backend):
    return "white" if backend.current_turn() == PieceColor.WHITE else "black"


def _clock_snapshot(clock):
    if clock is None:
        return ClockSnapshot(white_remaining=0.0, black_remaining=0.0, running_for=None)
    running = None
    if clock.running_for is not None:
        running = "white" if clock.running_for == PieceColor.WHITE else "black"
    return ClockSnapshot(
        white_remaining=clock.white_remaining,
        black_remaining=clock.black_remaining,
        running_for=running,
    )


def peek_type(raw):
    try:
        return json.loads(raw).get("type")
    except (json.JSONDecodeError, ValueError):
        return None


async def dispatch(app, websocket, room, color, raw):
    msg_type = peek_type(raw)
    handler = HANDLERS.get(msg_type)
    if handler is None:
        await send(websocket, ErrorMessage(reason=Reason.INVALID_MESSAGE))
        return msg_type, "invalid_message"
    return msg_type, await handler(app, websocket, room, color, raw)


async def handle_move(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.backend is None:
        return "no_backend"
    if room.result is not None:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.GAME_ALREADY_OVER, msg_type="move"))
        return "already_over"
    if room.pending_skillcheck is not None:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.SKILLCHECK_PENDING, msg_type="move"))
        return "pending"
    try:
        msg = MoveMessage.model_validate_json(raw)
        from_sq = square_from_coord(msg.from_sq)
        to_sq = square_from_coord(msg.to_sq)
    except (ValidationError, ValueError):
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "invalid_move_format"
    expected = _color_to_move(room.backend)
    if expected != color:
        log.info("move rejected room=%s mover=%s expected=%s reason=not_your_turn",
                 room.room_id, color, expected)
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.NOT_YOUR_TURN, msg_type="move"))
        return "not_your_turn"
    if (from_sq, to_sq) in room.skillcheck_locks:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.MOVE_LOCKED, msg_type="move"))
        return "locked"
    facts = compute_facts(room.backend, from_sq, to_sq, room.skillcheck_locks)
    if facts is None:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "illegal"
    kind = online.select_kind(room.skillcheck_secret, room.plies_ever, room.backend,
                              from_sq, to_sq, room.skillcheck_locks, facts)
    if kind == SkillCheckKind.NONE:
        return await _apply_move(app, room, color, from_sq, to_sq, msg.promotion,
                                 skill_kind=None, skill_won=None)
    value_diff = online.value_diff_for(facts, msg.promotion)
    seed = secrets.token_hex(16)
    start_ms = app.state.now_ms()
    deadline_ms = online.skillcheck_deadline_ms(room.time_minutes * 60)
    room.pending_skillcheck = PendingSkillCheck(
        color=color, from_sq=from_sq, to_sq=to_sq, promotion=msg.promotion,
        kind=kind, seed=seed, value_diff=value_diff,
        start_ms=start_ms, expires_at_ms=start_ms + deadline_ms, deadline_ms=deadline_ms,
    )
    log.info("skillcheck fired room=%s mover=%s kind=%s", room.room_id, color, kind.value)
    await send(connections.get_for_color(room, color), SkillCheckRequiredMessage(
        kind=kind.value, seed=seed, value_diff=value_diff, deadline_ms=deadline_ms,
        from_sq=coord_from_square(from_sq), to_sq=coord_from_square(to_sq),
        promotion=msg.promotion))
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, SkillCheckSpectateMessage(
            kind=kind.value, seed=seed, value_diff=value_diff, deadline_ms=deadline_ms,
            from_sq=coord_from_square(from_sq), to_sq=coord_from_square(to_sq),
            promotion=msg.promotion))
    return f"skillcheck:{kind.value}"


async def _apply_move(app, room, color, from_sq, to_sq, promotion,
                      *, skill_kind, skill_won):
    rooms = app.state.rooms
    connections = app.state.connections
    result = room.backend.try_move(from_sq, to_sq)
    if not result.legal:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "illegal"
    if result.promotion_required:
        room.backend.promote(to_sq, PROMO_TYPE_BY_LETTER[promotion or "q"])
    room.plies_ever += 1
    room.skillcheck_locks.clear()
    if room.first_move_at is None:
        room.first_move_at = app.state.now()
    await clear_resyncing(connections, room, color)
    room.draw_offered_by = None
    room.takeback_offered_by = None
    san = room.backend.move_history[-1].san
    if skill_kind is not None:
        room.skillcheck_log.append(SkillCheckOutcome(
            len(room.backend.move_history), skill_kind, skill_won, san))
    log.info("move applied room=%s mover=%s san=%s", room.room_id, color, san)
    applied = MoveAppliedMessage(
        from_sq=coord_from_square(from_sq), to_sq=coord_from_square(to_sq),
        promotion=promotion, san=san, clock=_clock_snapshot(room.backend.clock),
        ply=len(room.backend.move_history),
        skill_check_kind=skill_kind, skill_check_won=skill_won,
    )
    await broadcast(connections, room, applied)
    game_result = room.backend.game_result()
    if game_result in RESULT_REASON_BY_GAME_RESULT:
        reason, winner = RESULT_REASON_BY_GAME_RESULT[game_result]
        await finalize_and_broadcast(rooms, connections, room, reason, winner_color=winner)
        return f"applied+result:{reason}"
    return "applied"


async def handle_skill_check_shot(app, websocket, room, color, raw):
    connections = app.state.connections
    pending = room.pending_skillcheck
    if room.result is not None or pending is None or color != pending.color:
        return "noop"
    try:
        msg = SkillCheckShotMessage.model_validate_json(raw)
    except ValidationError:
        return "noop"
    recv_ms = app.state.now_ms()
    elapsed = online.adjudicated_elapsed_ms(msg.client_elapsed_ms, recv_ms, pending.start_ms)
    challenge = online.challenge_from(pending.kind, pending.seed, pending.value_diff)
    won = online.shot_wins(pending.kind, challenge, elapsed, pending.miss_count,
                           pending.deadline_ms)
    log.debug("skillcheck shot room=%s kind=%s raw_ms=%.1f client=%.1f effective=%d "
              "miss=%d subfloor=%s", room.room_id, pending.kind.value,
              recv_ms - pending.start_ms, msg.client_elapsed_ms, elapsed,
              pending.miss_count, elapsed < online.SKILLCHECK_HUMAN_FLOOR_MS)
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, SkillCheckSpectateShotMessage(
            elapsed_ms=elapsed, miss_count=pending.miss_count, won=won))
    if room.pending_skillcheck is not pending:
        return "noop"
    if won:
        room.pending_skillcheck = None
        log.info("skillcheck won room=%s mover=%s kind=%s", room.room_id, color,
                 pending.kind.value)
        return await _apply_move(app, room, color, pending.from_sq, pending.to_sq,
                                 pending.promotion, skill_kind=pending.kind.value,
                                 skill_won=True)
    if pending.kind == SkillCheckKind.WHEEL \
            or online.is_past_deadline(elapsed, pending.deadline_ms) \
            or online.aim_expired(challenge, elapsed, pending.miss_count):
        log.info("skillcheck failed room=%s mover=%s kind=%s", room.room_id, color,
                 pending.kind.value)
        await resolve_skillcheck_fail(connections, room)
        return "skillcheck_fail"
    pending.miss_count += 1
    return "skillcheck_miss"


async def handle_resign(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None:
        return "already_over"
    winner = room.opp_color(color)
    log.info("resign room=%s loser=%s winner=%s", room.room_id, color, winner)
    await finalize_and_broadcast(rooms, connections, room, Reason.RESIGNATION,
                                 winner_color=winner)
    return "resigned"


async def handle_draw_offer(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return "noop"
    if room.draw_offered_by is not None and room.draw_offered_by != color:
        log.info("draw mutual room=%s", room.room_id)
        room.draw_offered_by = None
        await finalize_and_broadcast(rooms, connections, room, Reason.DRAW_AGREEMENT)
        return "agreed"
    log.info("draw offered room=%s by=%s", room.room_id, color)
    room.draw_offered_by = color
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    await send(opp_ws, DrawOfferedMessage())
    return "offered"


async def handle_draw_response(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.draw_offered_by is None:
        return "noop"
    try:
        msg = DrawResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if room.draw_offered_by == color:
        return "self"
    if msg.accept:
        log.info("draw accepted room=%s by=%s", room.room_id, color)
        room.draw_offered_by = None
        await finalize_and_broadcast(rooms, connections, room, Reason.DRAW_AGREEMENT)
        return "accepted"
    log.info("draw declined room=%s by=%s", room.room_id, color)
    room.draw_offered_by = None
    return "declined"


async def _restart_rematch(app, room, color):
    rooms = app.state.rooms
    connections = app.state.connections
    if not rooms.reset_for_rematch(room.room_id):
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.REMATCH_UNAVAILABLE,
                                    msg_type="rematch_response"))
        return "unavailable"
    log.info("rematch restart room=%s", room.room_id)
    await broadcast_game_start(connections, room, app.state.now, rematch=True)
    return "restarted"


async def handle_rematch_request(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return "noop"
    slot = room.slot(color)
    if slot is None or not slot.at_result:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.REMATCH_UNAVAILABLE,
                                    msg_type="rematch_request"))
        return "unavailable"
    if color in room.rematch_offered_by:
        return "duplicate"
    room.rematch_offered_by.add(color)
    rooms.mark_rematch_activity(room)
    if len(room.rematch_offered_by) == 2:
        return await _restart_rematch(app, room, color)
    log.info("rematch requested room=%s by=%s", room.room_id, color)
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, RematchRequestMessage())
    return "offered"


async def handle_rematch_response(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return "noop"
    try:
        msg = RematchResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if not room.rematch_offered_by:
        return "noop"
    if color in room.rematch_offered_by:
        return "noop"
    if msg.accept:
        log.info("rematch accepted room=%s by=%s", room.room_id, color)
        rooms.mark_rematch_activity(room)
        return await _restart_rematch(app, room, color)
    log.info("rematch declined room=%s by=%s", room.room_id, color)
    for slot_color in ("white", "black"):
        ws = connections.get_for_color(room, slot_color)
        if ws is not None:
            await send(ws, RematchUpdateMessage(
                event="window_expired" if slot_color == color else "declined"))
    room.rematch_offered_by.clear()
    rooms.drop_room_now(room.room_id)
    return "declined"


async def handle_left_result(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is None:
        return "noop"
    slot = room.slot(color)
    if slot is None:
        return "noop"
    slot.at_result = False
    if color in room.rematch_offered_by:
        room.rematch_offered_by.discard(color)
        opp_ws = connections.get_for_color(room, room.opp_color(color))
        if opp_ws is not None:
            await send(opp_ws, RematchUpdateMessage(event="cancelled"))
    return "left_result"


async def handle_takeback_request(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return "noop"
    if room.pending_skillcheck is not None:
        return "pending"
    expected = _color_to_move(room.backend)
    if color == expected:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.NOT_YOUR_TURN,
                                    msg_type="takeback_request"))
        return "not_your_turn"
    if not room.backend.move_history:
        return "no_moves"
    log.info("takeback requested room=%s by=%s", room.room_id, color)
    room.takeback_offered_by = color
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    await send(opp_ws, TakebackOfferedMessage())
    return "offered"


async def handle_takeback_response(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is not None or room.takeback_offered_by is None:
        return "noop"
    if room.pending_skillcheck is not None:
        return "pending"
    try:
        msg = TakebackResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if room.takeback_offered_by == color:
        return "self"
    if msg.accept:
        log.info("takeback accepted room=%s by=%s", room.room_id, color)
        popped_ply = len(room.backend.move_history)
        room.backend.undo()
        room.skillcheck_log = [e for e in room.skillcheck_log if e.ply < popped_ply]
        room.takeback_offered_by = None
        await broadcast(connections, room, TakebackAppliedMessage(
            fen=export_fen(room.backend),
            clock=_clock_snapshot(room.backend.clock),
            ply=len(room.backend.move_history),
        ))
        return "accepted"
    log.info("takeback declined room=%s by=%s", room.room_id, color)
    room.takeback_offered_by = None
    return "declined"


async def handle_give_time(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is not None or room.backend is None or room.backend.clock is None:
        return "noop"
    try:
        hold_ms = GiveTimeMessage.model_validate_json(raw).hold_ms
    except ValidationError:
        return "invalid"
    ticks = max(1, hold_ms // GIVE_TIME_TICK_MS)
    opp_color_str = room.opp_color(color)
    opp_piece_color = (
        PieceColor.WHITE if opp_color_str == "white" else PieceColor.BLACK
    )
    added = room.backend.clock.add_time(opp_piece_color, GIVE_TIME_SECONDS * ticks)
    log.info("give_time room=%s by=%s hold_ms=%d ticks=%d added=%.2f",
             room.room_id, color, hold_ms, ticks, added)
    await broadcast(connections, room, TimeGrantedMessage(
        granted_by=color, seconds_added=added,
        clock=_clock_snapshot(room.backend.clock),
    ))
    return "granted" if added > 0 else "capped"


async def _notify_opp_state(connections, room, color, state):
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, ConnectionStatusMessage(opp_state=state))


async def set_resyncing(connections, room, color):
    slot = room.slot(color)
    if slot is not None and not slot.desync_active:
        slot.desync_active = True
        await _notify_opp_state(connections, room, color, "resyncing")


async def clear_resyncing(connections, room, color):
    slot = room.slot(color)
    if slot is not None and slot.desync_active:
        slot.desync_active = False
        await _notify_opp_state(connections, room, color, "connected")


async def handle_ping(app, websocket, room, color, raw):
    connections = app.state.connections
    try:
        msg = PingMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid_ping"
    await send(connections.get_for_color(room, color), PongMessage())
    if room.result is not None or room.backend is None:
        return "ping"
    if room.pending_skillcheck is not None:
        return "ping_pending"
    if msg.ply != len(room.backend.move_history):
        await set_resyncing(connections, room, color)
        await send(connections.get_for_color(room, color), ResyncDirectiveMessage())
    else:
        await clear_resyncing(connections, room, color)
    return "ping"


HANDLERS = {
    "move": handle_move,
    "resign": handle_resign,
    "draw_offer": handle_draw_offer,
    "draw_response": handle_draw_response,
    "rematch_request": handle_rematch_request,
    "rematch_response": handle_rematch_response,
    "left_result": handle_left_result,
    "takeback_request": handle_takeback_request,
    "takeback_response": handle_takeback_response,
    "give_time": handle_give_time,
    "ping": handle_ping,
    "skill_check_shot": handle_skill_check_shot,
}
