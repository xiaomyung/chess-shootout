import asyncio
import ipaddress
import json
import queue
import threading
from dataclasses import dataclass

import httpx
import websockets


HTTP_TIMEOUT_SECONDS = 5.0
SERVER_FULL_RETRIES = 3
SERVER_FULL_BACKOFF_SECONDS = 1.5
RECONNECT_TOTAL_SECONDS = 60
RECONNECT_INTERVAL_SECONDS = 2
PROTOCOL_VERSION = 1


@dataclass
class Event:
    type: str
    payload: dict


def _looks_like_ip_or_localhost(host):
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _split_addr(addr):
    """Return (scheme, host, port) given an addr like 'localhost:8000',
    'wss://chess.example.com', or 'chess.example.com:443'.
    Falls back to scheme heuristic when none provided."""
    explicit_scheme = None
    rest = addr
    for prefix in ("ws://", "wss://", "http://", "https://"):
        if addr.startswith(prefix):
            explicit_scheme = prefix
            rest = addr[len(prefix):]
            break
    if "/" in rest:
        rest = rest.split("/", 1)[0]
    if ":" in rest:
        host, port_s = rest.rsplit(":", 1)
        port = int(port_s)
    else:
        host = rest
        port = None
    if explicit_scheme:
        ws_scheme = "ws" if explicit_scheme in ("ws://", "http://") else "wss"
    else:
        if _looks_like_ip_or_localhost(host) or port == 8000:
            ws_scheme = "ws"
        else:
            ws_scheme = "wss"
    if port is None:
        port = 8000 if ws_scheme == "ws" else 443
    return ws_scheme, host, port


def _http_url(addr, path):
    ws_scheme, host, port = _split_addr(addr)
    http_scheme = "https" if ws_scheme == "wss" else "http"
    return f"{http_scheme}://{host}:{port}{path}"


def _ws_url(addr, path):
    ws_scheme, host, port = _split_addr(addr)
    return f"{ws_scheme}://{host}:{port}{path}"


class OnlineClient:

    def __init__(self):
        self._inbound = queue.Queue()
        self._loop = None
        self._loop_ready = threading.Event()
        self._thread = None
        self._stop = threading.Event()
        self._outbound_q = None  # asyncio.Queue, set in worker thread
        self._ws = None
        self._addr = None
        self._room_id = None
        self._session_token = None
        self.state = "disconnected"
        self.opp_state = "connected"
        self.ping_ms = None
        self._in_queue = False
        self._game_active = False

    def connect(self, addr, request):
        self._addr = addr
        self._thread = threading.Thread(
            target=self._run_loop, args=(request,), daemon=True,
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
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
                    await http.request(
                        "DELETE", _http_url(self._addr, "/matchmake"),
                        json={"version": PROTOCOL_VERSION,
                              "room_id": self._room_id,
                              "session_token": self._session_token},
                    )
            except Exception:
                pass
        self._in_queue = False
        self._stop.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    def disconnect(self):
        if self._loop is None or not self._loop.is_running():
            self.state = "disconnected"
            return
        self._stop.set()
        if self._ws is not None:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def send_move(self, from_sq, to_sq, promotion=None):
        self._send({"type": "move", "from": from_sq, "to": to_sq,
                    "promotion": promotion})

    def send_resign(self):
        self._send({"type": "resign"})

    def send_draw_offer(self):
        self._send({"type": "draw_offer"})

    def send_draw_response(self, accept):
        self._send({"type": "draw_response", "accept": accept})

    def send_rematch_request(self):
        self._send({"type": "rematch_request"})

    def send_rematch_response(self, accept):
        self._send({"type": "rematch_response", "accept": accept})

    def send_takeback_request(self):
        self._send({"type": "takeback_request"})

    def send_takeback_response(self, accept):
        self._send({"type": "takeback_response", "accept": accept})

    def _send(self, payload):
        payload.setdefault("version", PROTOCOL_VERSION)
        if self._loop is None or self._outbound_q is None:
            return
        self._loop.call_soon_threadsafe(self._outbound_q.put_nowait, payload)

    def drain_inbound(self):
        events = []
        while True:
            try:
                events.append(self._inbound.get_nowait())
            except queue.Empty:
                break
        return events

    # ------- Worker thread -------

    def _run_loop(self, request):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._outbound_q = asyncio.Queue()
        self._loop_ready.set()
        try:
            self._loop.run_until_complete(self._async_main(request))
        except Exception as exc:
            self._inbound.put(Event("error", {"reason": str(exc)}))
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _async_main(self, request):
        try:
            self.state = "connecting"
            mm = await self._matchmake_with_retries(request)
        except Exception as exc:
            self._inbound.put(Event("error", {"reason": str(exc)}))
            self.state = "disconnected"
            return
        self._room_id = mm["room_id"]
        self._session_token = mm["session_token"]
        self._in_queue = True
        self._inbound.put(Event("matchmake_response", mm))
        try:
            await self._run_ws_session()
            while (not self._stop.is_set() and self._game_active
                   and self._session_token is not None):
                self.state = "reconnecting"
                self.opp_state = "reconnecting"
                resumed = await self._resume_with_retries()
                if not resumed:
                    self._inbound.put(Event("error", {"reason": "reconnect_failed"}))
                    break
                self._inbound.put(Event("game_resumed", resumed))
                try:
                    await self._run_ws_session()
                except Exception as exc:
                    self._inbound.put(Event("error", {"reason": str(exc)}))
                    break
        except Exception as exc:
            self._inbound.put(Event("error", {"reason": str(exc)}))
        finally:
            self.state = "disconnected"

    async def _resume_with_retries(self):
        deadline = asyncio.get_event_loop().time() + RECONNECT_TOTAL_SECONDS
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            while asyncio.get_event_loop().time() < deadline and not self._stop.is_set():
                try:
                    r = await http.post(_http_url(self._addr, "/resume"),
                                        json={"version": PROTOCOL_VERSION,
                                              "room_id": self._room_id,
                                              "session_token": self._session_token})
                    if r.status_code == 200:
                        return r.json()
                    if r.status_code in (401, 410, 404):
                        return None
                except (httpx.HTTPError, httpx.TimeoutException):
                    pass
                await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
        return None

    async def _matchmake_with_retries(self, request):
        last_exc = None
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            for attempt in range(SERVER_FULL_RETRIES + 1):
                try:
                    payload = {"version": PROTOCOL_VERSION, **request}
                    r = await http.post(_http_url(self._addr, "/matchmake"),
                                        json=payload)
                    if r.status_code == 503:
                        last_exc = RuntimeError("server_full")
                        await asyncio.sleep(SERVER_FULL_BACKOFF_SECONDS)
                        continue
                    if r.status_code >= 400:
                        raise RuntimeError(_safe_error_reason(r) or f"http_{r.status_code}")
                    return r.json()
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    last_exc = exc
                    if attempt < SERVER_FULL_RETRIES:
                        await asyncio.sleep(SERVER_FULL_BACKOFF_SECONDS)
                        continue
                    raise RuntimeError("server_unreachable") from exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("server_full")

    async def _run_ws_session(self):
        ws_url = _ws_url(self._addr, f"/ws/{self._room_id}")
        async with websockets.connect(ws_url, ping_interval=20,
                                       ping_timeout=30) as ws:
            self._ws = ws
            self.state = "connected"
            await ws.send(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "auth",
                                       "session_token": self._session_token}))
            recv_task = asyncio.create_task(self._recv_loop(ws))
            send_task = asyncio.create_task(self._send_loop(ws))
            try:
                await asyncio.wait({recv_task, send_task},
                                   return_when=asyncio.FIRST_COMPLETED)
            finally:
                recv_task.cancel()
                send_task.cancel()
                self._ws = None

    async def _recv_loop(self, ws):
        try:
            while not self._stop.is_set():
                raw = await ws.recv()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type", "")
                if msg_type == "game_start":
                    self._in_queue = False
                    self._game_active = True
                if msg_type == "result":
                    self._game_active = False
                if msg_type == "connection_status":
                    self.opp_state = msg.get("opp_state", "connected")
                self._inbound.put(Event(msg_type, msg))
                if msg_type == "result":
                    break
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def _send_loop(self, ws):
        try:
            while not self._stop.is_set():
                payload = await self._outbound_q.get()
                await ws.send(json.dumps(payload))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass


def _safe_error_reason(response):
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, dict):
        if "reason" in body:
            return body["reason"]
        detail = body.get("detail")
        if isinstance(detail, dict) and "reason" in detail:
            return detail["reason"]
        if isinstance(detail, str):
            return detail
    return None
