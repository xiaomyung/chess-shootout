import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.fen import export_fen
from backend.utils import (
    PROMO_LETTER_BY_TYPE, coord_from_square,
)
from server import logging_setup
from server.broadcasts import broadcast_game_start
from server.connections import ConnectionRegistry, send
from server.handlers import _clock_snapshot, dispatch
from server.protocol import (
    AuthMessage, CancelMatchmakeRequest,
    ConnectionStatusMessage, ErrorMessage, HealthResponse, HistoryEntryWire, MatchmakeRequest,
    MatchmakeResponse, PROTOCOL_VERSION, Reason, ReclaimRequest, ReclaimResponse,
    ResultMessage, ResumeRequest, ResumeResponse,
    is_uuid4,
)
from server.rooms import (
    AlreadyInGameError, InvalidTokenError, NotInRoomError, PAIRING_WAIT_SECONDS,
    RoomManager,
)
from server.sweep import Sweep


CLOCK_TICK_INTERVAL_SECONDS = 0.1
MAX_INBOUND_MESSAGE_BYTES = 4096

RECLAIM_PER_UUID_LIMIT_PER_MINUTE = 5
RECLAIM_WINDOW_SECONDS = 60.0

WS_MESSAGES_PER_SECOND = 30
WS_RATE_WINDOW_SECONDS = 1.0

WS_CLOSE_PAYLOAD_TOO_LARGE = 1009
WS_CLOSE_INVALID_TOKEN = 4000
WS_CLOSE_SERVER_SHUTDOWN = 4002

log = logging_setup.get_logger("chess.server.app")


class UuidRateLimiter:

    def __init__(self, limit_per_minute, window_seconds, now_provider=time.monotonic):
        self.limit = limit_per_minute
        self.window = window_seconds
        self._now = now_provider
        self._calls: dict[str, deque] = defaultdict(deque)

    def hit(self, key):
        now = self._now()
        cutoff = now - self.window
        d = self._calls[key]
        while d and d[0] < cutoff:
            d.popleft()
        if len(d) >= self.limit:
            return False
        d.append(now)
        return True


def create_app(*, now_provider=time.monotonic, max_rooms=100):
    rooms = RoomManager(now_provider=now_provider, max_rooms=max_rooms)
    connections = ConnectionRegistry()
    limiter = Limiter(key_func=get_remote_address)
    reclaim_limiter = UuidRateLimiter(
        RECLAIM_PER_UUID_LIMIT_PER_MINUTE, RECLAIM_WINDOW_SECONDS,
        now_provider=now_provider,
    )
    started_at = now_provider()

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
                await send(ws, shutdown_msg)
                try:
                    await ws.close(code=WS_CLOSE_SERVER_SHUTDOWN)
                except (RuntimeError, WebSocketDisconnect) as exc:
                    log.debug("ws close on shutdown failed: %s", exc)

    app = FastAPI(lifespan=lifespan)
    app.state.rooms = rooms
    app.state.connections = connections
    app.state.limiter = limiter
    app.state.now = now_provider
    app.state.started_at = started_at
    app.state.reclaim_limiter = reclaim_limiter
    app.state.sweep = Sweep(rooms, connections, now_provider)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request, exc):
        return JSONResponse(status_code=429, content={"reason": "rate_limited"})

    @app.exception_handler(ValidationError)
    async def _validation_handler(request, exc):
        return JSONResponse(status_code=422, content={"reason": _first_validation_reason(exc)})

    @app.get("/")
    async def root():
        return {
            "service": "chess-server",
            "version": PROTOCOL_VERSION,
            "endpoints": ["/healthz", "/matchmake", "/resume", "/reclaim", "/ws/{room_id}"],
        }

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz():
        return HealthResponse(
            rooms_active=rooms.rooms_active,
            queue_depth=rooms.queue_depth,
            uptime_s=now_provider() - app.state.started_at,
        )

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
        history = []
        for entry in (room.backend.move_history if room.backend else []):
            move = entry.move
            history.append(HistoryEntryWire(
                from_sq=coord_from_square(move.from_sq),
                to_sq=coord_from_square(move.to_sq),
                promotion=_promotion_letter(move),
                san=entry.san,
            ))
        return ResumeResponse(
            fen=export_fen(room.backend),
            move_history=history,
            clock=_clock_snapshot(room.backend.clock),
            your_color=color,
            white_name=room.white.nickname if room.white else "",
            black_name=room.black.nickname if room.black else "",
            time_minutes=room.time_minutes,
            increment_seconds=room.increment_seconds,
        )

    @app.post("/reclaim", response_model=ReclaimResponse)
    @limiter.limit("30/minute")
    async def post_reclaim(request: Request, body: ReclaimRequest):
        if not reclaim_limiter.hit(body.client_uuid):
            log.info("reclaim rate-limited uuid=%s", body.client_uuid[:8])
            raise HTTPException(status_code=429, detail={"reason": Reason.RATE_LIMITED})
        log.info("reclaim request uuid=%s", body.client_uuid[:8])
        try:
            room, color, new_token = await rooms.reclaim_session(body.client_uuid)
        except NotInRoomError:
            raise HTTPException(status_code=404, detail={"reason": Reason.NOT_IN_ROOM})
        if room.result is not None:
            log.info("reclaim rejected uuid=%s reason=game_already_over",
                     body.client_uuid[:8])
            raise HTTPException(status_code=410, detail={"reason": room.result[0]})
        log.info("reclaim ok uuid=%s room=%s color=%s",
                 body.client_uuid[:8], room.room_id, color)
        return ReclaimResponse(room_id=room.room_id, session_token=new_token)

    @app.websocket("/ws/{room_id}")
    async def ws_endpoint(websocket: WebSocket, room_id: str):
        if not is_uuid4(room_id):
            await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
            return
        await websocket.accept()
        await _ws_session(app, websocket, room_id)

    return app


async def _sweep_loop(app):
    try:
        while True:
            await asyncio.sleep(CLOCK_TICK_INTERVAL_SECONDS)
            await app.state.sweep.step_all()
    except asyncio.CancelledError:
        pass


async def _sweep(app):
    await app.state.sweep.step_all()


def _first_validation_reason(exc):
    errs = exc.errors() if hasattr(exc, "errors") else []
    if not errs:
        return Reason.INVALID_MESSAGE
    return errs[0].get("msg", Reason.INVALID_MESSAGE)


def _promotion_letter(move):
    if move.promoted_to is None:
        return None
    return PROMO_LETTER_BY_TYPE.get(move.promoted_to)


async def _authenticate_ws(websocket, rooms, room_id):
    try:
        first_raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=PAIRING_WAIT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return None
    if len(first_raw) > MAX_INBOUND_MESSAGE_BYTES:
        await websocket.close(code=WS_CLOSE_PAYLOAD_TOO_LARGE)
        return None
    try:
        auth_msg = AuthMessage.model_validate_json(first_raw)
    except (ValidationError, ValueError):
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return None
    if auth_msg.version != PROTOCOL_VERSION:
        await send(websocket, ErrorMessage(reason=Reason.VERSION_MISMATCH))
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return None
    room = rooms.get(room_id)
    if room is None:
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return None
    color, slot = room.slot_by_token(auth_msg.session_token)
    if slot is None:
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return None
    return room, color, slot


async def _ws_session(app, websocket, room_id):
    rooms = app.state.rooms
    connections = app.state.connections
    auth = await _authenticate_ws(websocket, rooms, room_id)
    if auth is None:
        return
    room, color, slot = auth
    auth_room = room
    auth_color = color
    auth_uuid = slot.client_uuid
    rooms.mark_connected(room.room_id, color)
    connections.add(room.room_id, auth_uuid, websocket)
    log.info("ws auth ok room=%s uuid=%s tentative_color=%s paired=%s has_both=%s",
             room.room_id, auth_uuid[:8], color, room.is_paired(),
             connections.has_both(room))

    if room.is_paired() and connections.has_both(room) and not room.game_start_broadcast:
        if room.started_at is None:
            room.started_at = app.state.now()
        await broadcast_game_start(connections, room)
    else:
        opp_ws = connections.get_for_color(room, room.opp_color(color))
        if opp_ws is not None:
            await send(opp_ws, ConnectionStatusMessage(opp_state="connected"))

    ws_rate_limiter = UuidRateLimiter(
        WS_MESSAGES_PER_SECOND, WS_RATE_WINDOW_SECONDS,
        now_provider=app.state.now,
    )

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
            if not ws_rate_limiter.hit(auth_uuid):
                await send(websocket, ErrorMessage(reason=Reason.RATE_LIMITED))
                continue
            t0 = app.state.now()
            msg_type, outcome = await dispatch(app, websocket, room, current_color, raw)
            log.debug("ws dispatch room=%s uuid=%s type=%s latency_ms=%.1f outcome=%s",
                      room.room_id, auth_uuid[:8], msg_type,
                      (app.state.now() - t0) * 1000.0, outcome)
    finally:
        if auth_room is not None and auth_color is not None:
            rooms.mark_disconnected(auth_room.room_id, auth_color)
            if auth_uuid is not None:
                connections.remove(auth_room.room_id, auth_uuid)
            log.info("ws disconnected room=%s color=%s",
                     auth_room.room_id, auth_color)
            opp_ws = connections.get_for_color(auth_room, auth_room.opp_color(auth_color))
            if opp_ws is not None and auth_room.result is None:
                await send(opp_ws, ConnectionStatusMessage(opp_state="reconnecting"))
