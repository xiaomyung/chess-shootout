import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.fen import export_fen
from backend.pieces import PieceColor, PieceType
from backend.utils import Square
from server import logging_setup
from server.protocol import (
    ALLOWED_TIME_CONTROLS, AuthMessage, CancelMatchmakeRequest, ClockSnapshot,
    ConnectionStatusMessage, DrawOfferedMessage, DrawOfferMessage, DrawResponseMessage,
    ErrorMessage, GameStartMessage, HealthResponse, HistoryEntryWire, MatchmakeRequest,
    MatchmakeResponse, MatchmakeTimeoutMessage, MoveAppliedMessage, MoveMessage,
    PROTOCOL_VERSION, Reason, RematchRequestMessage, RematchResponseMessage,
    ResignMessage, ResultMessage, ResumeRequest, ResumeResponse, TakebackAppliedMessage,
    TakebackOfferedMessage, TakebackRequestMessage, TakebackResponseMessage,
)
from server.rooms import (
    AlreadyInGameError, FIRST_MOVE_ABORT_SECONDS, GRACE_SECONDS, InvalidTokenError,
    NotInRoomError, PAIRING_WAIT_SECONDS, QUEUE_MAX_SECONDS, REMATCH_KEEP_ALIVE_SECONDS,
    RoomManager,
)


CLOCK_TICK_INTERVAL_SECONDS = 0.1
MAX_INBOUND_MESSAGE_BYTES = 4096

# WebSocket close codes (RFC 6455)
WS_CLOSE_NORMAL = 1000
WS_CLOSE_PAYLOAD_TOO_LARGE = 1009
WS_CLOSE_SERVER_ERROR = 1011
WS_CLOSE_INVALID_TOKEN = 4000
WS_CLOSE_ABANDONMENT = 4001
WS_CLOSE_SERVER_SHUTDOWN = 4002

log = logging_setup.get_logger("chess.server.app")


_RESULT_REASON_BY_GAME_RESULT = {
    "white_wins": (Reason.CHECKMATE, "white"),
    "black_wins": (Reason.CHECKMATE, "black"),
    "white_wins_on_time": (Reason.TIMEOUT, "white"),
    "black_wins_on_time": (Reason.TIMEOUT, "black"),
    "draw_stalemate": (Reason.DRAW_STALEMATE, None),
    "draw_repetition": (Reason.DRAW_REPETITION, None),
    "draw_fifty_move": (Reason.DRAW_FIFTY_MOVE, None),
    "draw_insufficient_material": (Reason.DRAW_INSUFFICIENT_MATERIAL, None),
}


def _square_from_coord(coord):
    if not isinstance(coord, str) or len(coord) != 2:
        raise ValueError(f"bad square coord: {coord!r}")
    file_idx = ord(coord[0]) - ord("a")
    rank = int(coord[1])
    if not (0 <= file_idx < 8) or not (1 <= rank <= 8):
        raise ValueError(f"bad square coord: {coord!r}")
    return Square(8 - rank, file_idx)


def _coord_from_square(sq):
    return f"{chr(ord('a') + sq.col)}{8 - sq.row}"


_PROMO_TYPE_BY_LETTER = {
    "q": PieceType.QUEEN, "r": PieceType.ROOK,
    "b": PieceType.BISHOP, "n": PieceType.KNIGHT,
}


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


class ConnectionRegistry:
    """WS registry keyed by client_uuid (stable across color reshuffles).
    Color lookup is resolved through the room's current slot assignment."""

    def __init__(self):
        self._by_room: dict[str, dict[str, WebSocket]] = defaultdict(dict)

    def add(self, room_id, client_uuid, ws):
        self._by_room[room_id][client_uuid] = ws

    def remove(self, room_id, client_uuid):
        if room_id in self._by_room:
            self._by_room[room_id].pop(client_uuid, None)
            if not self._by_room[room_id]:
                self._by_room.pop(room_id, None)

    def get_for_color(self, room, color):
        slot = room.slot(color)
        if slot is None:
            return None
        return self._by_room.get(room.room_id, {}).get(slot.client_uuid)

    def has_both(self, room):
        if not room.is_paired():
            return False
        present = self._by_room.get(room.room_id, {})
        return (room.white.client_uuid in present
                and room.black.client_uuid in present)

    def all_for_room(self, room):
        for color in ("white", "black"):
            ws = self.get_for_color(room, color)
            if ws is not None:
                yield color, ws

    def all_active(self):
        for room_id, by_uuid in self._by_room.items():
            for ws in by_uuid.values():
                yield room_id, ws


async def _send(ws, message):
    if ws is None:
        return
    try:
        await ws.send_json(message.model_dump(by_alias=True))
    except Exception as exc:
        log.warning("broadcast send failed: %s", exc)


async def _broadcast(connections, room, message):
    for color, ws in list(connections.all_for_room(room)):
        await _send(ws, message)


def create_app(*, now_provider=time.monotonic, max_rooms=100):
    rooms = RoomManager(now_provider=now_provider, max_rooms=max_rooms)
    connections = ConnectionRegistry()
    limiter = Limiter(key_func=get_remote_address)

    @asynccontextmanager
    async def lifespan(app):
        log.info("chess-server v%d listening (max_rooms=%d)", PROTOCOL_VERSION, max_rooms)
        sweep_task = asyncio.create_task(_sweep_loop(app))
        try:
            yield
        finally:
            sweep_task.cancel()
            shutdown_msg = ResultMessage(reason=Reason.SERVER_SHUTDOWN)
            for _, ws in list(connections.all_active()):
                await _send(ws, shutdown_msg)
                try:
                    await ws.close(code=WS_CLOSE_SERVER_SHUTDOWN)
                except Exception:
                    pass

    app = FastAPI(lifespan=lifespan)
    app.state.rooms = rooms
    app.state.connections = connections
    app.state.limiter = limiter
    app.state.now = now_provider

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request, exc):
        return JSONResponse(status_code=429, content={"reason": "rate_limited"})

    @app.exception_handler(ValidationError)
    async def _validation_handler(request, exc):
        return JSONResponse(status_code=422, content={"reason": _first_validation_reason(exc)})

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz():
        return HealthResponse(rooms_active=rooms.rooms_active)

    @app.post("/matchmake", response_model=MatchmakeResponse)
    @limiter.limit("10/minute")
    async def post_matchmake(request: Request, body: MatchmakeRequest):
        log.info("matchmake nickname=%s uuid=%s tc=%s+%s side=%s",
                 body.nickname, body.client_uuid[:8],
                 body.time_minutes, body.increment_seconds, body.side_preference)
        if body.time_minutes < 1 or body.increment_seconds < 0:
            raise HTTPException(status_code=422, detail={"reason": "invalid_time_control"})
        token = RoomManager.make_session_token()
        try:
            room = await rooms.enqueue(
                client_uuid=body.client_uuid, nickname=body.nickname,
                session_token=token, time_minutes=body.time_minutes,
                increment_seconds=body.increment_seconds,
                side_preference=body.side_preference,
            )
        except AlreadyInGameError:
            log.info("matchmake rejected uuid=%s reason=already_in_game", body.client_uuid[:8])
            raise HTTPException(status_code=409, detail={"reason": Reason.ALREADY_IN_GAME})
        except RuntimeError as exc:
            if str(exc) == "server_full":
                log.warning("matchmake rejected reason=server_full")
                raise HTTPException(status_code=503, detail={"reason": Reason.ROOM_FULL})
            raise
        log.info("matchmake ok room=%s paired=%s", room.room_id, room.is_paired())
        return MatchmakeResponse(room_id=room.room_id, session_token=token)

    @app.delete("/matchmake")
    async def delete_matchmake(body: CancelMatchmakeRequest):
        try:
            await rooms.cancel_wait(body.room_id, body.session_token)
        except NotInRoomError:
            raise HTTPException(status_code=404, detail={"reason": Reason.NOT_IN_ROOM})
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail={"reason": Reason.SESSION_EXPIRED})
        except RuntimeError as exc:
            if str(exc) == "game_already_started":
                log.info("cancel ignored room=%s reason=game_already_started", body.room_id)
                return {"status": "already_started"}
            raise
        log.info("cancel ok room=%s", body.room_id)
        return {"status": "ok"}

    @app.post("/resume", response_model=ResumeResponse)
    @limiter.limit("30/minute")
    async def post_resume(request: Request, body: ResumeRequest):
        log.info("resume request room=%s", body.room_id)
        room = rooms.get(body.room_id)
        if room is None:
            log.info("resume rejected room=%s reason=not_in_room", body.room_id)
            raise HTTPException(status_code=404, detail={"reason": Reason.NOT_IN_ROOM})
        color, slot = room.slot_by_token(body.session_token)
        if slot is None:
            log.info("resume rejected room=%s reason=session_expired", body.room_id)
            raise HTTPException(status_code=401, detail={"reason": Reason.SESSION_EXPIRED})
        if room.result is not None:
            log.info("resume rejected room=%s reason=game_already_over", body.room_id)
            raise HTTPException(status_code=410, detail={"reason": room.result[0]})
        opp = room.slot(room.opp_color(color))
        history = []
        for entry in (room.backend.move_history if room.backend else []):
            move = entry.move
            history.append(HistoryEntryWire(
                from_sq=_coord_from_square(move.from_sq),
                to_sq=_coord_from_square(move.to_sq),
                promotion=_promotion_letter(move),
                san=entry.san,
            ))
        return ResumeResponse(
            fen=export_fen(room.backend),
            move_history=history,
            clock=_clock_snapshot(room.backend.clock),
            your_color=color,
            opp_nickname=opp.nickname if opp else "",
            time_minutes=room.time_minutes,
            increment_seconds=room.increment_seconds,
            draw_pending_by=room.draw_offered_by,
            takeback_pending_by=room.takeback_offered_by,
        )

    @app.websocket("/ws/{room_id}")
    async def ws_endpoint(websocket: WebSocket, room_id: str):
        await websocket.accept()
        await _ws_session(app, websocket, room_id)

    return app


async def _sweep_loop(app):
    try:
        while True:
            await asyncio.sleep(CLOCK_TICK_INTERVAL_SECONDS)
            await _sweep(app)
    except asyncio.CancelledError:
        pass


async def _sweep(app):
    rooms = app.state.rooms
    connections = app.state.connections
    for room in list(rooms._active.values()):
        if room.result is not None:
            continue
        backend = room.backend
        if backend is not None and backend.clock is not None and room.first_move_at is not None:
            backend.tick_clock()
            game_result = backend.game_result()
            if game_result in _RESULT_REASON_BY_GAME_RESULT:
                reason, winner = _RESULT_REASON_BY_GAME_RESULT[game_result]
                log.info("game over room=%s reason=%s winner=%s",
                         room.room_id, reason, winner)
                rooms.finalize_result(room.room_id, reason, winner_color=winner)
                await _broadcast(connections, room,
                                 ResultMessage(reason=reason, winner_color=winner))
        now = app.state.now()
        if (room.is_paired() and room.first_move_at is None
                and room.started_at is not None
                and now - room.started_at >= FIRST_MOVE_ABORT_SECONDS):
            log.info("aborted room=%s reason=no_first_move", room.room_id)
            rooms.finalize_result(room.room_id, Reason.ABORTED)
            await _broadcast(connections, room, ResultMessage(reason=Reason.ABORTED))
    for room, abandoned_color in list(rooms.grace_expired_rooms()):
        winner = room.opp_color(abandoned_color)
        log.info("abandonment room=%s loser=%s winner=%s",
                 room.room_id, abandoned_color, winner)
        rooms.finalize_abandonment(room.room_id, abandoned_color)
        await _broadcast(connections, room,
                         ResultMessage(reason=Reason.ABANDONMENT, winner_color=winner))
    # If both players are gone AND no move has been played yet, drop the
    # room immediately so their uuids free up for a fresh game. Once moves
    # have been played, fall back to the standard 60 s grace + GC path so
    # transient WS blips (both reconnecting at once) can still resume.
    for room in list(rooms._active.values()):
        if room.first_move_at is not None:
            continue
        white_present = (room.white is not None
                         and connections.get_for_color(room, "white") is not None)
        black_present = (room.black is not None
                         and connections.get_for_color(room, "black") is not None)
        if not white_present and not black_present:
            log.info("drop room=%s reason=both_disconnected_pre_game", room.room_id)
            rooms.drop_room_now(room.room_id)
    rooms.gc_finished_rooms()


def _first_validation_reason(exc):
    errs = exc.errors() if hasattr(exc, "errors") else []
    if not errs:
        return Reason.INVALID_MESSAGE
    return errs[0].get("msg", Reason.INVALID_MESSAGE)


def _promotion_letter(move):
    if move.promoted_to is None:
        return None
    return {
        PieceType.QUEEN: "q", PieceType.ROOK: "r",
        PieceType.BISHOP: "b", PieceType.KNIGHT: "n",
    }.get(move.promoted_to)


async def _ws_session(app, websocket, room_id):
    rooms = app.state.rooms
    connections = app.state.connections
    auth_color = None
    auth_room = None
    auth_uuid = None
    try:
        first_raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=PAIRING_WAIT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return
    if len(first_raw) > MAX_INBOUND_MESSAGE_BYTES:
        await websocket.close(code=WS_CLOSE_PAYLOAD_TOO_LARGE)
        return
    try:
        first = AuthMessage.model_validate_json(first_raw)
    except (ValidationError, ValueError):
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return
    if first.version != PROTOCOL_VERSION:
        await _send(websocket, ErrorMessage(reason=Reason.VERSION_MISMATCH))
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return
    room = rooms.get(room_id)
    if room is None:
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return
    color, slot = room.slot_by_token(first.session_token)
    if slot is None:
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return
    auth_room = room
    auth_color = color
    auth_uuid = slot.client_uuid
    rooms.mark_connected(room.room_id, color)
    connections.add(room.room_id, auth_uuid, websocket)
    log.info("ws auth ok room=%s uuid=%s tentative_color=%s paired=%s has_both=%s",
             room.room_id, auth_uuid[:8], color, room.is_paired(),
             connections.has_both(room))

    if room.is_paired() and connections.has_both(room):
        if room.started_at is None or room.first_move_at is None:
            room.started_at = app.state.now()
        await _broadcast_game_start(connections, room)
    elif connections.get_for_color(room, room.opp_color(color)) is not None:
        # Opponent reconnected: notify them that we're back.
        await _send(connections.get_for_color(room, room.opp_color(color)),
                    ConnectionStatusMessage(opp_state="connected"))

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception as exc:
                log.warning("ws recv unexpected exc room=%s color=%s exc=%r",
                            room.room_id, color, exc)
                break
            if len(raw) > MAX_INBOUND_MESSAGE_BYTES:
                await websocket.close(code=WS_CLOSE_PAYLOAD_TOO_LARGE)
                return
            current_color = room.color_of(auth_uuid)
            if current_color is None:
                break
            await _dispatch(app, websocket, room, current_color, raw)
            if room.result is not None:
                break
    finally:
        if auth_room is not None and auth_color is not None:
            rooms.mark_disconnected(auth_room.room_id, auth_color)
            if auth_uuid is not None:
                connections.remove(auth_room.room_id, auth_uuid)
            log.info("ws disconnected room=%s color=%s",
                     auth_room.room_id, auth_color)
            opp_ws = connections.get_for_color(auth_room, auth_room.opp_color(auth_color))
            if opp_ws is not None and auth_room.result is None:
                await _send(opp_ws, ConnectionStatusMessage(opp_state="reconnecting"))


async def _broadcast_game_start(connections, room):
    fen = export_fen(room.backend)
    sent = []
    for color in ("white", "black"):
        ws = connections.get_for_color(room, color)
        if ws is None:
            continue
        await _send(ws, GameStartMessage(
            fen=fen,
            white_name=room.white.nickname if room.white else "",
            black_name=room.black.nickname if room.black else "",
            time_minutes=room.time_minutes,
            increment_seconds=room.increment_seconds,
            your_color=color,
        ))
        sent.append(color)
    log.info("game_start broadcast room=%s sent_to=%s", room.room_id, sent)


async def _dispatch(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    msg_type = _peek_type(raw)
    if msg_type == "move":
        await _handle_move(app, room, color, raw)
    elif msg_type == "resign":
        await _handle_resign(app, room, color)
    elif msg_type == "draw_offer":
        await _handle_draw_offer(app, room, color)
    elif msg_type == "draw_response":
        await _handle_draw_response(app, room, color, raw)
    elif msg_type == "rematch_request":
        await _handle_rematch_request(app, room, color)
    elif msg_type == "rematch_response":
        await _handle_rematch_response(app, room, color, raw)
    elif msg_type == "takeback_request":
        await _handle_takeback_request(app, room, color)
    elif msg_type == "takeback_response":
        await _handle_takeback_response(app, room, color, raw)
    else:
        await _send(websocket, ErrorMessage(reason=Reason.INVALID_MESSAGE))


def _peek_type(raw):
    import json
    try:
        return json.loads(raw).get("type")
    except (json.JSONDecodeError, ValueError):
        return None


def _color_to_piece_color(color):
    return PieceColor.WHITE if color == "white" else PieceColor.BLACK


async def _handle_move(app, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    try:
        msg = MoveMessage.model_validate_json(raw)
        from_sq = _square_from_coord(msg.from_sq)
        to_sq = _square_from_coord(msg.to_sq)
    except (ValidationError, ValueError):
        await _send(connections.get_for_color(room, color),
                    ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return
    expected = "white" if room.backend.current_turn() == PieceColor.WHITE else "black"
    if expected != color:
        log.info("move rejected room=%s mover=%s expected=%s reason=not_your_turn",
                 room.room_id, color, expected)
        await _send(connections.get_for_color(room, color),
                    ErrorMessage(reason=Reason.NOT_YOUR_TURN))
        return
    result = room.backend.try_move(from_sq, to_sq)
    if not result.legal:
        await _send(connections.get_for_color(room, color),
                    ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return
    if result.promotion_required:
        promo_letter = msg.promotion or "q"
        promo_type = _PROMO_TYPE_BY_LETTER[promo_letter]
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
    await _broadcast(connections, room, applied)
    game_result = room.backend.game_result()
    if game_result in _RESULT_REASON_BY_GAME_RESULT:
        reason, winner = _RESULT_REASON_BY_GAME_RESULT[game_result]
        rooms.finalize_result(room.room_id, reason, winner_color=winner)
        await _broadcast(connections, room,
                         ResultMessage(reason=reason, winner_color=winner))


async def _handle_resign(app, room, color):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None:
        return
    winner = room.opp_color(color)
    log.info("resign room=%s loser=%s winner=%s", room.room_id, color, winner)
    rooms.finalize_result(room.room_id, Reason.RESIGNATION, winner_color=winner)
    await _broadcast(connections, room,
                     ResultMessage(reason=Reason.RESIGNATION, winner_color=winner))


async def _handle_draw_offer(app, room, color):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None:
        return
    if room.backend is None:
        return
    expected = "white" if room.backend.current_turn() == PieceColor.WHITE else "black"
    if color != expected:
        await _send(connections.get_for_color(room, color),
                    ErrorMessage(reason=Reason.NOT_YOUR_TURN))
        return
    if room.draw_offered_by is not None and room.draw_offered_by != color:
        # Mutual draw offer — auto-agree.
        log.info("draw mutual room=%s", room.room_id)
        rooms.finalize_result(room.room_id, Reason.DRAW_AGREEMENT)
        room.draw_offered_by = None
        await _broadcast(connections, room,
                         ResultMessage(reason=Reason.DRAW_AGREEMENT))
        return
    log.info("draw offered room=%s by=%s", room.room_id, color)
    room.draw_offered_by = color
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    await _send(opp_ws, DrawOfferedMessage())


async def _handle_draw_response(app, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.draw_offered_by is None:
        return
    try:
        msg = DrawResponseMessage.model_validate_json(raw)
    except ValidationError:
        return
    if room.draw_offered_by == color:
        return  # can't respond to your own offer
    if msg.accept:
        log.info("draw accepted room=%s by=%s", room.room_id, color)
        rooms.finalize_result(room.room_id, Reason.DRAW_AGREEMENT)
        room.draw_offered_by = None
        await _broadcast(connections, room,
                         ResultMessage(reason=Reason.DRAW_AGREEMENT))
    else:
        log.info("draw declined room=%s by=%s", room.room_id, color)
        room.draw_offered_by = None


async def _handle_rematch_request(app, room, color):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return  # rematch only after game ended
    if color in room.rematch_offered_by:
        return
    room.rematch_offered_by.add(color)
    if len(room.rematch_offered_by) == 2:
        log.info("rematch mutual — restart room=%s", room.room_id)
        rooms.reset_for_rematch(room.room_id)
        await _broadcast_game_start(connections, room)
        return
    log.info("rematch requested room=%s by=%s", room.room_id, color)
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await _send(opp_ws, RematchRequestMessage())


async def _handle_rematch_response(app, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return
    try:
        msg = RematchResponseMessage.model_validate_json(raw)
    except ValidationError:
        return
    if not room.rematch_offered_by:
        return
    if msg.accept:
        log.info("rematch accepted room=%s by=%s", room.room_id, color)
        rooms.reset_for_rematch(room.room_id)
        await _broadcast_game_start(connections, room)
    else:
        log.info("rematch declined room=%s by=%s", room.room_id, color)
        room.rematch_offered_by.clear()


async def _handle_takeback_request(app, room, color):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return
    expected = "white" if room.backend.current_turn() == PieceColor.WHITE else "black"
    if color == expected:
        await _send(connections.get_for_color(room, color),
                    ErrorMessage(reason=Reason.NOT_YOUR_TURN))
        return
    if not room.backend.move_history:
        return
    last_mover_color = "black" if expected == "white" else "white"
    if last_mover_color != color:
        return
    log.info("takeback requested room=%s by=%s", room.room_id, color)
    room.takeback_offered_by = color
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    await _send(opp_ws, TakebackOfferedMessage())


async def _handle_takeback_response(app, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.takeback_offered_by is None:
        return
    try:
        msg = TakebackResponseMessage.model_validate_json(raw)
    except ValidationError:
        return
    if room.takeback_offered_by == color:
        return
    if msg.accept:
        log.info("takeback accepted room=%s by=%s", room.room_id, color)
        room.backend.undo()
        room.takeback_offered_by = None
        await _broadcast(connections, room, TakebackAppliedMessage(
            fen=export_fen(room.backend),
            clock=_clock_snapshot(room.backend.clock),
        ))
    else:
        log.info("takeback declined room=%s by=%s", room.room_id, color)
        room.takeback_offered_by = None
