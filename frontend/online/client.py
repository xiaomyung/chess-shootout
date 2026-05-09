import asyncio
import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass

from frontend.online.transport import (
    FatalResumeError, ServerTransport, TransportError, TransportHTTPError,
    SchemaVersionMismatch, WsConnectionClosed,
)
from server.protocol import (
    CancelMatchmakeRequest, MatchmakeRequest, ResumeRequest,
)


log = logging.getLogger("chess.client")


SERVER_FULL_RETRIES = 3
SERVER_FULL_BACKOFF_SECONDS = 1.5
RECONNECT_TOTAL_SECONDS = 60
RECONNECT_INTERVAL_SECONDS = 2
PING_INTERVAL_SECONDS = 5
PING_SAMPLE_WINDOW = 5


@dataclass
class Event:
    type: str
    payload: dict


def probe_active_game(addr, client_uuid, timeout=2.0):
    if not addr or not client_uuid:
        return None
    transport = ServerTransport(addr)
    response = transport.reclaim_blocking(client_uuid, timeout=timeout)
    if response is None:
        return None
    return response.model_dump()


def fetch_resume(addr, room_id, session_token):
    transport = ServerTransport(addr)
    response = transport.resume_blocking(room_id, session_token)
    if response is None:
        return None
    return response.model_dump()


class OnlineClient:

    ROOM_LOST = object()

    def __init__(self):
        self._inbound = queue.Queue()
        self._loop = None
        self._thread = None
        self._stop = threading.Event()
        self._outbound = None
        self._ws = None
        self._transport = None
        self._addr = None
        self._room_id = None
        self._session_token = None
        self.state = "disconnected"
        self.opp_state = "connected"
        self._in_queue = False
        self._game_active = False
        self._ping_samples_ms = deque(maxlen=PING_SAMPLE_WINDOW)

    def get_ping_ms(self):
        if not self._ping_samples_ms:
            return None
        return int(round(sum(self._ping_samples_ms) / len(self._ping_samples_ms)))

    def connect(self, addr, request):
        self._addr = addr
        self._transport = ServerTransport(addr)
        self._spawn_loop_thread(self._async_main, request)

    def reconnect_to_existing(self, addr, room_id, session_token, resume_payload):
        self._addr = addr
        self._transport = ServerTransport(addr)
        self._room_id = room_id
        self._session_token = session_token
        self._game_active = True
        self._spawn_loop_thread(self._async_main_resume, resume_payload)

    def _spawn_loop_thread(self, coro_factory, *args):
        self._thread = threading.Thread(
            target=self._run_loop, args=(coro_factory, args), daemon=True,
        )
        self._thread.start()

    def cancel_queue(self):
        if self._loop is None or not self._loop.is_running():
            self.state = "disconnected"
            return
        asyncio.run_coroutine_threadsafe(self._cancel_async(), self._loop)

    async def _cancel_async(self):
        if self._in_queue and self._room_id and self._session_token:
            try:
                async with self._transport.make_async_http() as http:
                    body = CancelMatchmakeRequest(
                        room_id=self._room_id,
                        session_token=self._session_token,
                    )
                    await self._transport.cancel_matchmake_async(body, http)
            except Exception:
                pass
        self._in_queue = False
        self._stop.set()
        if self._ws is not None:
            await self._ws.close()

    def disconnect(self):
        if self._loop is None or not self._loop.is_running():
            self.state = "disconnected"
            return
        self._stop.set()
        if self._ws is not None:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def send_move(self, from_sq, to_sq, promotion=None):
        self._enqueue("send_move", from_sq, to_sq, promotion)

    def send_resign(self):
        self._enqueue("send_resign")

    def send_draw_offer(self):
        self._enqueue("send_draw_offer")

    def send_draw_response(self, accept):
        self._enqueue("send_draw_response", accept)

    def send_rematch_request(self):
        self._enqueue("send_rematch_request")

    def send_rematch_response(self, accept):
        self._enqueue("send_rematch_response", accept)

    def send_takeback_request(self):
        self._enqueue("send_takeback_request")

    def send_takeback_response(self, accept):
        self._enqueue("send_takeback_response", accept)

    def _enqueue(self, method, *args):
        if self._loop is None or self._loop.is_closed() or self._outbound is None:
            log.debug("send dropped (loop not running): method=%s", method)
            return
        try:
            self._loop.call_soon_threadsafe(
                self._outbound.put_nowait, (method, args),
            )
            log.debug("ws send method=%s", method)
        except RuntimeError:
            pass

    def drain_inbound(self):
        events = []
        while True:
            try:
                events.append(self._inbound.get_nowait())
            except queue.Empty:
                break
        return events

    def _run_loop(self, coro_factory, args):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._outbound = asyncio.Queue()
        try:
            self._loop.run_until_complete(coro_factory(*args))
        except Exception as exc:
            self._inbound.put(Event("error", {"reason": str(exc)}))
            self._dump_crash_log(exc)
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    def _dump_crash_log(self, exc):
        try:
            from frontend import crash_log
            crash_log.write_crash_log(exc, crash_log.get_memory_buffer(), {
                "online_state": self.state,
                "addr": self._addr,
                "room_id": self._room_id,
                "in_queue": self._in_queue,
                "game_active": self._game_active,
            })
        except Exception:
            log.exception("crash log write failed")

    async def _async_main_resume(self, resume_payload):
        log.info("reconnect-resume addr=%s room=%s", self._addr, self._room_id)
        self.state = "connecting"
        await self._run_session_with_reconnects()

    async def _async_main(self, request):
        log.info("connect addr=%s", self._addr)
        try:
            self.state = "connecting"
            mm = await self._matchmake_with_retries(request)
        except SchemaVersionMismatch as exc:
            log.warning("schema version mismatch reason=%s", exc)
            self._inbound.put(Event("error", {"reason": "version_mismatch"}))
            self.state = "disconnected"
            return
        except Exception as exc:
            log.warning("matchmake failed reason=%s", exc)
            self._inbound.put(Event("error", {"reason": str(exc)}))
            self.state = "disconnected"
            return
        self._room_id = mm["room_id"]
        self._session_token = mm["session_token"]
        self._in_queue = True
        log.info("matchmake ok room=%s", self._room_id)
        self._inbound.put(Event("matchmake_response", mm))
        await self._run_session_with_reconnects()

    async def _run_session_with_reconnects(self):
        try:
            await self._run_ws_session()
            while (not self._stop.is_set() and self._game_active
                   and self._session_token is not None):
                log.info("ws dropped mid-game; attempting reconnect")
                self.state = "reconnecting"
                self.opp_state = "reconnecting"
                resumed = await self._resume_with_retries()
                if resumed is self.ROOM_LOST:
                    log.warning("reconnect: server alive but room gone")
                    self._inbound.put(Event("error", {"reason": "room_lost"}))
                    break
                if not resumed:
                    log.warning("reconnect gave up")
                    self._inbound.put(Event("error", {"reason": "reconnect_failed"}))
                    break
                log.info("reconnect succeeded; resuming game")
                self._inbound.put(Event("game_resumed", resumed))
                try:
                    await self._run_ws_session()
                except Exception as exc:
                    self._inbound.put(Event("error", {"reason": str(exc)}))
                    break
        except Exception as exc:
            log.warning("ws session crash: %s", exc)
            self._inbound.put(Event("error", {"reason": str(exc)}))
        finally:
            log.info("session ended state=disconnected")
            self.state = "disconnected"

    async def _resume_with_retries(self):
        deadline = asyncio.get_running_loop().time() + RECONNECT_TOTAL_SECONDS
        body = ResumeRequest(
            room_id=self._room_id, session_token=self._session_token,
        )
        async with self._transport.make_async_http() as http:
            while asyncio.get_running_loop().time() < deadline and not self._stop.is_set():
                try:
                    response = await self._transport.resume_async(body, http)
                except FatalResumeError:
                    health = await self._transport.healthz_async(http)
                    if health is not None:
                        return self.ROOM_LOST
                    return None
                if response is not None:
                    return response.model_dump()
                await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        return None

    async def _matchmake_with_retries(self, request):
        last_exc = None
        req = MatchmakeRequest(**request)
        async with self._transport.make_async_http() as http:
            for attempt in range(SERVER_FULL_RETRIES + 1):
                try:
                    return (await self._transport.matchmake_async(req, http)).model_dump()
                except TransportHTTPError as exc:
                    if exc.status_code == 503:
                        last_exc = RuntimeError("room_full")
                        await asyncio.sleep(SERVER_FULL_BACKOFF_SECONDS)
                        continue
                    raise RuntimeError(exc.reason or f"http_{exc.status_code}") from exc
                except TransportError as exc:
                    last_exc = exc
                    if attempt < SERVER_FULL_RETRIES:
                        await asyncio.sleep(SERVER_FULL_BACKOFF_SECONDS)
                        continue
                    raise RuntimeError("server_unreachable") from exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("room_full")

    async def _run_ws_session(self):
        ws = await self._transport.ws_connect(self._room_id, self._session_token)
        self._ws = ws
        self.state = "connected"
        self._ping_samples_ms.clear()
        recv_task = asyncio.create_task(self._recv_loop(ws))
        send_task = asyncio.create_task(self._send_loop(ws))
        ping_task = asyncio.create_task(self._ping_loop(ws))
        try:
            await asyncio.wait({recv_task, send_task},
                                 return_when=asyncio.FIRST_COMPLETED)
        finally:
            recv_task.cancel()
            send_task.cancel()
            ping_task.cancel()
            await ws.close()
            self._ws = None

    async def _recv_loop(self, ws):
        try:
            while not self._stop.is_set():
                msg = await ws.recv()
                if msg is None:
                    continue
                msg_type = msg.get("type", "")
                log.debug("ws recv type=%s", msg_type)
                if msg_type == "game_start":
                    self._in_queue = False
                    self._game_active = True
                if msg_type == "result":
                    self._game_active = False
                    log.info("ws result reason=%s winner=%s",
                             msg.get("reason"), msg.get("winner_color"))
                if msg_type == "connection_status":
                    self.opp_state = msg.get("opp_state", "connected")
                self._inbound.put(Event(msg_type, msg))
        except (WsConnectionClosed, asyncio.CancelledError):
            pass

    async def _send_loop(self, ws):
        try:
            while not self._stop.is_set():
                method, args = await self._outbound.get()
                send = getattr(ws, method, None)
                if send is None:
                    log.warning("unknown ws send method=%s", method)
                    continue
                await send(*args)
        except (WsConnectionClosed, asyncio.CancelledError):
            pass

    async def _ping_loop(self, ws):
        try:
            while not self._stop.is_set():
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                try:
                    pong_waiter = await ws.ping()
                    latency_s = await pong_waiter
                except (WsConnectionClosed, asyncio.CancelledError):
                    raise
                except Exception as exc:
                    log.debug("ping failed: %r", exc)
                    continue
                self._ping_samples_ms.append(latency_s * 1000.0)
        except (WsConnectionClosed, asyncio.CancelledError):
            pass
