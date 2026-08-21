import asyncio
import ipaddress
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from chessshootout.backend.fen import export_fen
from chessshootout.backend.utils import (
    PROMO_LETTER_BY_TYPE, coord_from_square,
)
from chessshootout.server import logging_setup
from chessshootout.server.broadcasts import (
    _idle_window_wire, broadcast_game_start, finalize_and_broadcast,
    resolve_skillcheck_fail)
from chessshootout.server.connections import ConnectionRegistry, send
from chessshootout.server.handlers import _clock_snapshot, dispatch
from chessshootout.server.moderation import library
from chessshootout.server.protocol import (
    ANNOTATIONS_PER_SECOND, AnnotationSetWire, ArrowWire,
    AuthMessage, CHAT_COOLDOWN_SECONDS, CancelMatchmakeRequest,
    ConnectionStatusMessage, ErrorMessage,
    HealthResponse, HistoryEntryWire, LockWire,
    MatchmakeRequest, MatchmakeResponse,
    PROTOCOL_VERSION, PendingSkillCheckWire, Reason, ReclaimRequest, ReclaimResponse,
    RematchRequestMessage, RematchUpdateMessage,
    ResultMessage, ResumeRequest, ResumeResponse, SkillCheckOutcomeWire, is_uuid4,
)
from chessshootout.server.rooms import (
    AlreadyInGameError, InvalidTokenError, NotInRoomError, PAIRING_WAIT_SECONDS,
    RoomManager,
)
from chessshootout.server.sweep import Sweep


CLOCK_TICK_INTERVAL_SECONDS = 0.1
MAX_INBOUND_MESSAGE_BYTES = 4096
DEFAULT_MAX_ROOMS = 100


def _moderation_enabled():
    return os.environ.get("MODERATION_OFF", "").strip().lower() not in (
        "1", "true", "yes", "on")


def app_version():
    try:
        return _pkg_version("chess-shootout")
    except PackageNotFoundError:
        return ""


RECLAIM_PER_UUID_LIMIT_PER_MINUTE = 100
RATE_LIMIT_PRUNE_THRESHOLD = 4096
RECLAIM_WINDOW_SECONDS = 60.0

MATCHMAKE_PER_IP_LIMIT = "60/minute"
RESUME_PER_IP_LIMIT = "60/minute"
RECLAIM_PER_IP_LIMIT = "120/minute"

WS_MESSAGES_PER_SECOND = 30
WS_RATE_WINDOW_SECONDS = 1.0

WS_CLOSE_PAYLOAD_TOO_LARGE = 1009
WS_CLOSE_INVALID_TOKEN = 4000
WS_CLOSE_SERVER_SHUTDOWN = 4002
WS_CLOSE_SUPERSEDED = 4003


DEFAULT_TRUSTED_PROXIES = "127.0.0.1/32"


def _parse_trusted_proxies(raw):
    networks = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return networks


TRUSTED_PROXIES_RAW = os.environ.get("TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES)
TRUSTED_PROXIES = _parse_trusted_proxies(TRUSTED_PROXIES_RAW)


def log_trusted_proxies(raw=None, trusted=None):
    raw = TRUSTED_PROXIES_RAW if raw is None else raw
    trusted = TRUSTED_PROXIES if trusted is None else trusted
    if raw.strip() and not trusted:
        log.warning("trusted proxies unparsable (TRUSTED_PROXIES=%r); "
                    "rate limits key on the socket peer", raw)
        return
    log.info("trusted proxies %s", ",".join(str(net) for net in trusted) or "none")


def _peer_trusted(peer, trusted):
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(ip in net for net in trusted)


def _forwarded_ip(raw):
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


def client_ip_key(request, trusted=None):
    trusted = TRUSTED_PROXIES if trusted is None else trusted
    peer = get_remote_address(request)
    if _peer_trusted(peer, trusted):
        forwarded = _forwarded_ip(request.headers.get("cf-connecting-ip"))
        if forwarded is not None:
            return forwarded
    return peer


log = logging_setup.get_logger("chess.server.app")


class UuidRateLimiter:

    def __init__(self, limit_per_minute, window_seconds, now_provider=time.monotonic):
        self.limit = limit_per_minute
        self.window = window_seconds
        self._now = now_provider
        self._calls: dict[str, deque] = defaultdict(deque)

    def _prune(self, cutoff):
        for key in list(self._calls.keys()):
            d = self._calls[key]
            while d and d[0] < cutoff:
                d.popleft()
            if not d:
                del self._calls[key]

    def hit(self, key):
        now = self._now()
        cutoff = now - self.window
        if len(self._calls) > RATE_LIMIT_PRUNE_THRESHOLD:
            self._prune(cutoff)
        d = self._calls[key]
        while d and d[0] < cutoff:
            d.popleft()
        if len(d) >= self.limit:
            return False
        d.append(now)
        return True


def create_app(*, now_provider=time.monotonic, max_rooms=DEFAULT_MAX_ROOMS):
    rooms = RoomManager(now_provider=now_provider, max_rooms=max_rooms)

    def now_ms():
        return now_provider() * 1000.0

    connections = ConnectionRegistry()
    limiter = Limiter(key_func=client_ip_key)
    reclaim_limiter = UuidRateLimiter(
        RECLAIM_PER_UUID_LIMIT_PER_MINUTE, RECLAIM_WINDOW_SECONDS,
        now_provider=now_provider,
    )
    annotation_limiter = UuidRateLimiter(
        ANNOTATIONS_PER_SECOND, 1.0, now_provider=now_provider,
    )
    chat_limiter = UuidRateLimiter(
        1, CHAT_COOLDOWN_SECONDS, now_provider=now_provider,
    )
    started_at = now_provider()

    @asynccontextmanager
    async def lifespan(app):
        log.info("gameserver v%d release=%s listening (max_rooms=%d)",
                 PROTOCOL_VERSION, app_version() or "dev", max_rooms)
        log_trusted_proxies()
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
    app.state.now_ms = now_ms
    app.state.started_at = started_at
    app.state.reclaim_limiter = reclaim_limiter
    app.state.annotation_limiter = annotation_limiter
    app.state.chat_limiter = chat_limiter
    app.state.moderation_enabled = _moderation_enabled()
    if app.state.moderation_enabled:
        library.preload()
    app.state.sweep = Sweep(rooms, connections, now_provider, now_ms)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request, exc):
        return JSONResponse(
            status_code=429,
            content={"detail": {"reason": Reason.RATE_LIMITED}},
        )

    @app.exception_handler(ValidationError)
    async def _validation_handler(request, exc):
        return JSONResponse(status_code=422, content={"reason": _first_validation_reason(exc)})

    @app.get("/")
    async def root():
        return {
            "service": "gameserver",
            "version": PROTOCOL_VERSION,
            "endpoints": ["/healthz", "/matchmake", "/resume", "/reclaim", "/ws/{room_id}"],
        }

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz():
        return HealthResponse(
            app_version=app_version(),
            rooms_active=rooms.rooms_active,
            queue_depth=rooms.queue_depth,
            uptime_s=now_provider() - app.state.started_at,
        )

    @app.post("/matchmake", response_model=MatchmakeResponse)
    @limiter.limit(MATCHMAKE_PER_IP_LIMIT)
    async def post_matchmake(request: Request, body: MatchmakeRequest):
        log.info("matchmake nickname=%s uuid=%s tc=%s+%s side=%s",
                 body.nickname, body.client_uuid[:8],
                 body.time_minutes, body.increment_seconds, body.side_preference)
        if body.time_minutes < 1 or body.increment_seconds < 0:
            raise HTTPException(status_code=422,
                                  detail={"reason": Reason.INVALID_TIME_CONTROL})
        prior = rooms.in_progress_room_for(body.client_uuid)
        if prior is not None:
            prior_room, prior_color = prior
            log.info("matchmake abandons room=%s color=%s", prior_room.room_id, prior_color)
            await finalize_and_broadcast(rooms, connections, prior_room, Reason.ABANDONMENT,
                                         winner_color=prior_room.opp_color(prior_color))
            rooms.release_for_new_game(body.client_uuid)
        finished = rooms.finished_room_for(body.client_uuid)
        if finished is not None:
            fin_color = finished.color_of(body.client_uuid)
            if fin_color is not None:
                opp_ws = connections.get_for_color(finished, finished.opp_color(fin_color))
                if opp_ws is not None:
                    await send(opp_ws, RematchUpdateMessage(event="opponent_left"))
            log.info("matchmake leaves finished room=%s", finished.room_id)
            rooms.release_for_new_game(body.client_uuid)
        queued = rooms.queued_room_for(body.client_uuid)
        if queued is not None:
            log.info("matchmake releases queue slot room=%s", queued.room_id)
            rooms.release_for_new_game(body.client_uuid)
        token = RoomManager.make_session_token()
        try:
            room = await rooms.enqueue(
                client_uuid=body.client_uuid, nickname=body.nickname,
                session_token=token, time_minutes=body.time_minutes,
                increment_seconds=body.increment_seconds,
                side_preference=body.side_preference,
                country=body.country,
                hide_opp_marks=body.hide_opp_marks,
            )
        except AlreadyInGameError:
            log.info("matchmake rejected uuid=%s reason=already_in_game", body.client_uuid[:8])
            raise HTTPException(status_code=409, detail={"reason": Reason.ALREADY_IN_GAME})
        except RuntimeError as exc:
            if str(exc) == "server_full":
                log.warning("matchmake rejected reason=server_full")
                raise HTTPException(status_code=503, detail={"reason": Reason.ROOM_FULL})
            raise
        if room.is_paired():
            log.info("room paired room=%s white=%s black=%s", room.room_id,
                     room.white.client_uuid[:8], room.black.client_uuid[:8])
        else:
            log.info("room created room=%s uuid=%s", room.room_id, body.client_uuid[:8])
        return MatchmakeResponse(room_id=room.room_id, session_token=token)

    @app.delete("/matchmake")
    @limiter.limit(MATCHMAKE_PER_IP_LIMIT)
    async def delete_matchmake(request: Request, body: CancelMatchmakeRequest):
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
    @limiter.limit(RESUME_PER_IP_LIMIT)
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
        dead = room.pending_skillcheck
        if dead is not None and dead.is_dead(app.state.now_ms()):
            await resolve_skillcheck_fail(rooms, connections, room)
        if room.backend is not None:
            room.backend.tick_clock()
        history = [
            HistoryEntryWire(
                from_sq=coord_from_square(entry.move.from_sq),
                to_sq=coord_from_square(entry.move.to_sq),
                promotion=_promotion_letter(entry.move),
                san=entry.san,
            )
            for entry in (room.backend.move_history if room.backend else [])
        ]
        pending = _pending_skillcheck_wire(room, app.state.now_ms)
        locks = [LockWire(from_sq=coord_from_square(frm), to_sq=coord_from_square(to))
                 for frm, to in room.skillcheck_locks]
        skillcheck_log = [
            SkillCheckOutcomeWire(ply=e.ply, kind=e.kind, won=e.won, san=e.san)
            for e in room.skillcheck_log]
        white_annotations = _annotation_set_wire(room.annotations_white)
        black_annotations = _annotation_set_wire(room.annotations_black)
        if room.hides_opponent_marks(color):
            if color == "white":
                black_annotations = AnnotationSetWire()
            else:
                white_annotations = AnnotationSetWire()
        response = ResumeResponse(
            fen=export_fen(room.backend),
            move_history=history,
            clock=_clock_snapshot(room.backend.clock),
            your_color=color,
            white_name=room.white.nickname if room.white else "",
            black_name=room.black.nickname if room.black else "",
            time_minutes=room.time_minutes,
            increment_seconds=room.increment_seconds,
            white_score=room.score_for("white"),
            black_score=room.score_for("black"),
            white_country=room.white.country if room.white else None,
            black_country=room.black.country if room.black else None,
            pending_skillcheck=pending,
            skillcheck_locks=locks,
            skillcheck_log=skillcheck_log,
            white_annotations=white_annotations,
            black_annotations=black_annotations,
            share_muted=room.annotations_for(color).share_muted,
            hide_opp_marks=slot.hide_opp_marks,
            result_reason=room.result[0] if room.result else None,
            result_winner=room.result[1] if room.result else None,
            idle_window=_idle_window_wire(room, app.state.now()),
        )
        log.info("resume served room=%s color=%s ply=%d", body.room_id, color, len(history))
        if (connections.get_for_color(room, color) is not None
                and slot is not None and not slot.desync_active):
            slot.desync_active = True
            opp_ws = connections.get_for_color(room, room.opp_color(color))
            if opp_ws is not None:
                await send(opp_ws, ConnectionStatusMessage(opp_state="resyncing"))
        return response

    @app.post("/reclaim", response_model=ReclaimResponse)
    @limiter.limit(RECLAIM_PER_IP_LIMIT)
    async def post_reclaim(request: Request, body: ReclaimRequest):
        if not reclaim_limiter.hit(body.client_uuid):
            log.info("reclaim rate-limited uuid=%s", body.client_uuid[:8])
            raise HTTPException(status_code=429, detail={"reason": Reason.RATE_LIMITED})
        log.info("reclaim request uuid=%s", body.client_uuid[:8])
        try:
            room, color, new_token = await rooms.reclaim_session(body.client_uuid)
        except NotInRoomError:
            raise HTTPException(status_code=404, detail={"reason": Reason.NOT_IN_ROOM})
        old_ws = connections.get_for_uuid(room.room_id, body.client_uuid)
        if old_ws is not None:
            try:
                await old_ws.close(code=WS_CLOSE_SUPERSEDED)
            except (RuntimeError, WebSocketDisconnect) as exc:
                log.debug("ws close on reclaim failed: %s", exc)
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


def _first_validation_reason(exc):
    errs = exc.errors() if hasattr(exc, "errors") else []
    if not errs:
        return Reason.INVALID_MESSAGE
    return errs[0].get("msg", Reason.INVALID_MESSAGE)


def _over_inbound_cap(raw):
    return len(raw.encode("utf-8")) > MAX_INBOUND_MESSAGE_BYTES


def _promotion_letter(move):
    if move.promoted_to is None:
        return None
    return PROMO_LETTER_BY_TYPE.get(move.promoted_to)


def _annotation_set_wire(store):
    return AnnotationSetWire(
        sharing=store.sharing,
        highlights=sorted(store.highlights),
        arrows=[ArrowWire(from_sq=frm, to_sq=to) for frm, to in store.arrows],
    )


def _pending_skillcheck_wire(room, now_ms):
    pending = room.pending_skillcheck
    if pending is None or pending.is_dead(now_ms()):
        return None
    elapsed = max(0.0, now_ms() - pending.start_ms)
    return PendingSkillCheckWire(
        kind=pending.kind.value, seed=pending.seed, value_diff=pending.value_diff,
        deadline_ms=pending.deadline_ms, captured_value=pending.captured_value,
        elapsed_ms=elapsed, miss_count=pending.miss_count, progress=pending.progress,
        last_hit_pop=pending.last_hit_pop,
        from_sq=coord_from_square(pending.from_sq),
        to_sq=coord_from_square(pending.to_sq),
        promotion=pending.promotion, color=pending.color,
    )


async def _authenticate_ws(websocket, rooms, room_id):
    try:
        first_raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=PAIRING_WAIT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=WS_CLOSE_INVALID_TOKEN)
        return None
    if _over_inbound_cap(first_raw):
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
    displaced = connections.add(room.room_id, auth_uuid, websocket)
    if displaced is not None:
        try:
            await displaced.close(code=WS_CLOSE_SUPERSEDED)
        except (RuntimeError, WebSocketDisconnect) as exc:
            log.debug("ws close on supersede failed: %s", exc)
    log.info("ws auth ok room=%s uuid=%s tentative_color=%s paired=%s has_both=%s",
             room.room_id, auth_uuid[:8], color, room.is_paired(),
             connections.has_both(room))

    if room.result is not None:
        slot.at_result = True
        reason, winner = room.result
        await send(websocket, ResultMessage(reason=reason, winner_color=winner))
        if room.opp_color(color) in room.rematch_offered_by:
            await send(websocket, RematchRequestMessage())
        opp_ws = connections.get_for_color(room, room.opp_color(color))
        if opp_ws is not None:
            await send(opp_ws, RematchUpdateMessage(event="opponent_returned"))
    elif room.is_paired() and connections.has_both(room) and not room.game_start_broadcast:
        if room.started_at is None:
            room.started_at = app.state.now()
        await broadcast_game_start(connections, room, app.state.now)
    else:
        opp_ws = connections.get_for_color(room, room.opp_color(color))
        if opp_ws is not None:
            await send(opp_ws, ConnectionStatusMessage(opp_state="connected"))
        if room.game_start_broadcast:
            await send(websocket, ConnectionStatusMessage(
                opp_state="connected" if opp_ws is not None else "reconnecting"))

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
            except RuntimeError as exc:
                log.debug("ws recv on superseded/closed socket room=%s color=%s: %s",
                          room.room_id, color, exc)
                break
            except Exception as exc:
                log.warning("ws recv unexpected exc room=%s color=%s exc=%r",
                            room.room_id, color, exc)
                break
            if _over_inbound_cap(raw):
                await websocket.close(code=WS_CLOSE_PAYLOAD_TOO_LARGE)
                return
            current_color = room.color_of(auth_uuid)
            if current_color is None:
                break
            rooms.touch_seen(auth_room.room_id, current_color)
            if not ws_rate_limiter.hit(auth_uuid):
                await send(websocket, ErrorMessage(reason=Reason.RATE_LIMITED))
                continue
            t0 = app.state.now()
            msg_type, outcome = await dispatch(app, websocket, room, current_color, raw)
            log.debug("ws dispatch room=%s uuid=%s type=%s latency_ms=%.1f outcome=%s",
                      room.room_id, auth_uuid[:8], msg_type,
                      (app.state.now() - t0) * 1000.0, outcome)
    finally:
        removed = connections.remove(auth_room.room_id, auth_uuid, websocket)
        cur_color = auth_room.color_of(auth_uuid) or auth_color
        if removed or connections.get_for_color(auth_room, cur_color) is None:
            rooms.mark_disconnected(auth_room.room_id, cur_color)
            log.info("ws disconnected room=%s color=%s",
                     auth_room.room_id, cur_color)
            opp_ws = connections.get_for_color(auth_room, auth_room.opp_color(cur_color))
            if opp_ws is not None:
                msg = (ConnectionStatusMessage(opp_state="reconnecting")
                       if auth_room.result is None
                       else RematchUpdateMessage(event="opponent_reconnecting"))
                await send(opp_ws, msg)
