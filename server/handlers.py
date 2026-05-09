import json

from pydantic import ValidationError

from backend.fen import export_fen
from backend.pieces import PieceColor
from backend.utils import (
    PROMO_TYPE_BY_LETTER, square_from_coord,
)
from server import logging_setup
from server.connections import broadcast, send
from server.broadcasts import broadcast_game_start
from server.protocol import (
    ClockSnapshot, DrawOfferedMessage, DrawResponseMessage, ErrorMessage,
    MoveAppliedMessage, MoveMessage, Reason, RematchRequestMessage,
    RematchResponseMessage, ResultMessage, TakebackAppliedMessage,
    TakebackOfferedMessage, TakebackResponseMessage,
)
from server.sweep import _RESULT_REASON_BY_GAME_RESULT


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
    rooms = app.state.rooms
    connections = app.state.connections
    if room.backend is None:
        return "no_backend"
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
    result = room.backend.try_move(from_sq, to_sq)
    if not result.legal:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "illegal"
    if result.promotion_required:
        promo_letter = msg.promotion or "q"
        promo_type = PROMO_TYPE_BY_LETTER[promo_letter]
        room.backend.promote(to_sq, promo_type)
    if room.first_move_at is None:
        room.first_move_at = app.state.now()
    room.draw_offered_by = None
    room.takeback_offered_by = None
    san = room.backend.move_history[-1].san
    log.info("move applied room=%s mover=%s san=%s", room.room_id, color, san)
    applied = MoveAppliedMessage(
        from_sq=msg.from_sq, to_sq=msg.to_sq, promotion=msg.promotion,
        san=san, clock=_clock_snapshot(room.backend.clock),
    )
    await broadcast(connections, room, applied)
    game_result = room.backend.game_result()
    if game_result in _RESULT_REASON_BY_GAME_RESULT:
        reason, winner = _RESULT_REASON_BY_GAME_RESULT[game_result]
        rooms.finalize_result(room.room_id, reason, winner_color=winner)
        await broadcast(connections, room,
                          ResultMessage(reason=reason, winner_color=winner))
        return f"applied+result:{reason}"
    return "applied"


async def handle_resign(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None:
        return "already_over"
    winner = room.opp_color(color)
    log.info("resign room=%s loser=%s winner=%s", room.room_id, color, winner)
    rooms.finalize_result(room.room_id, Reason.RESIGNATION, winner_color=winner)
    await broadcast(connections, room,
                      ResultMessage(reason=Reason.RESIGNATION, winner_color=winner))
    return "resigned"


async def handle_draw_offer(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return "noop"
    expected = _color_to_move(room.backend)
    if color != expected:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.NOT_YOUR_TURN, msg_type="draw_offer"))
        return "not_your_turn"
    if room.draw_offered_by is not None and room.draw_offered_by != color:
        log.info("draw mutual room=%s", room.room_id)
        rooms.finalize_result(room.room_id, Reason.DRAW_AGREEMENT)
        room.draw_offered_by = None
        await broadcast(connections, room,
                          ResultMessage(reason=Reason.DRAW_AGREEMENT))
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
        rooms.finalize_result(room.room_id, Reason.DRAW_AGREEMENT)
        room.draw_offered_by = None
        await broadcast(connections, room,
                          ResultMessage(reason=Reason.DRAW_AGREEMENT))
        return "accepted"
    log.info("draw declined room=%s by=%s", room.room_id, color)
    room.draw_offered_by = None
    return "declined"


async def handle_rematch_request(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return "noop"
    if color in room.rematch_offered_by:
        return "duplicate"
    room.rematch_offered_by.add(color)
    if len(room.rematch_offered_by) == 2:
        log.info("rematch mutual — restart room=%s", room.room_id)
        rooms.reset_for_rematch(room.room_id)
        await broadcast_game_start(connections, room)
        return "started"
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
    if msg.accept:
        log.info("rematch accepted room=%s by=%s", room.room_id, color)
        rooms.reset_for_rematch(room.room_id)
        await broadcast_game_start(connections, room)
        return "accepted"
    log.info("rematch declined room=%s by=%s", room.room_id, color)
    room.rematch_offered_by.clear()
    return "declined"


async def handle_takeback_request(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return "noop"
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
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.takeback_offered_by is None:
        return "noop"
    try:
        msg = TakebackResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if room.takeback_offered_by == color:
        return "self"
    if msg.accept:
        log.info("takeback accepted room=%s by=%s", room.room_id, color)
        room.backend.undo()
        room.takeback_offered_by = None
        await broadcast(connections, room, TakebackAppliedMessage(
            fen=export_fen(room.backend),
            clock=_clock_snapshot(room.backend.clock),
        ))
        return "accepted"
    log.info("takeback declined room=%s by=%s", room.room_id, color)
    room.takeback_offered_by = None
    return "declined"


HANDLERS = {
    "move": handle_move,
    "resign": handle_resign,
    "draw_offer": handle_draw_offer,
    "draw_response": handle_draw_response,
    "rematch_request": handle_rematch_request,
    "rematch_response": handle_rematch_response,
    "takeback_request": handle_takeback_request,
    "takeback_response": handle_takeback_response,
}
