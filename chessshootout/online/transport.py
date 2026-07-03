import ipaddress
import json
import logging
import ssl
from typing import Optional

import certifi
import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from chessshootout.server.protocol import (
    AuthMessage, CancelMatchmakeRequest, DrawResponseMessage, HealthResponse,
    MatchmakeRequest, MatchmakeResponse, MoveMessage, PingMessage, PROTOCOL_VERSION,
    Reason, ReclaimRequest, ReclaimResponse, RematchRequestMessage,
    RematchResponseMessage, ResumeRequest, ResumeResponse,
    TakebackResponseMessage,
)

WsConnectionClosed = ConnectionClosed


log = logging.getLogger("chess.client.transport")


HTTP_TIMEOUT_SECONDS = 5.0


_TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class TransportError(Exception):
    pass


class SchemaVersionMismatch(TransportError):
    pass


class TransportHTTPError(TransportError):

    def __init__(self, status_code, reason):
        super().__init__(f"http_{status_code}:{reason}")
        self.status_code = status_code
        self.reason = reason


class FatalResumeError(TransportError):
    pass


def _looks_like_ip_or_localhost(host):
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _split_addr(addr):
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
        try:
            port = int(port_s)
        except ValueError as exc:
            raise TransportError(f"invalid_address: {addr}") from exc
    else:
        host = rest
        port = None
    if explicit_scheme:
        ws_scheme = "ws" if explicit_scheme in ("ws://", "http://") else "wss"
    elif _looks_like_ip_or_localhost(host) or port == 8000:
        ws_scheme = "ws"
    else:
        ws_scheme = "wss"
    if port is None:
        port = 8000 if ws_scheme == "ws" else 443
    return ws_scheme, host, port


class _UrlBuilder:

    def __init__(self, addr):
        ws_scheme, host, port = _split_addr(addr)
        self.host = host
        self.port = port
        self.ws_scheme = ws_scheme
        self.http_scheme = "https" if ws_scheme == "wss" else "http"

    def http(self, path):
        return f"{self.http_scheme}://{self.host}:{self.port}{path}"

    def ws(self, path):
        return f"{self.ws_scheme}://{self.host}:{self.port}{path}"


def _safe_error_reason(response):
    try:
        body = response.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    if "reason" in body:
        return body["reason"]
    detail = body.get("detail")
    if isinstance(detail, dict) and "reason" in detail:
        return detail["reason"]
    if isinstance(detail, str):
        return detail
    return None


class ServerTransport:

    def __init__(self, addr, *, http_client=None, async_http_factory=None):
        self.addr = addr
        self._url = _UrlBuilder(addr)
        self._http = http_client
        self._async_http_factory = async_http_factory or (
            lambda: httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, verify=_TLS_CONTEXT)
        )

    def _sync_request(self, method, path, *, json_body=None, timeout=HTTP_TIMEOUT_SECONDS):
        url = self._url.http(path)
        try:
            if self._http is not None:
                r = self._http.request(method, url, json=json_body, timeout=timeout)
            else:
                r = httpx.request(method, url, json=json_body, timeout=timeout, verify=_TLS_CONTEXT)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise TransportError(str(exc)) from exc
        return r

    def _parse_response(self, response, model):
        if response.status_code >= 400:
            reason = _safe_error_reason(response) or f"http_{response.status_code}"
            if reason == Reason.VERSION_MISMATCH:
                raise SchemaVersionMismatch(reason)
            raise TransportHTTPError(response.status_code, reason)
        if model is None:
            return None
        try:
            return model.model_validate(response.json())
        except (ValueError, json.JSONDecodeError) as exc:
            raise TransportError(f"invalid_response_body: {exc}") from exc

    def healthz(self) -> HealthResponse:
        r = self._sync_request("GET", "/healthz")
        return self._parse_response(r, HealthResponse)

    def reclaim_blocking(self, client_uuid, *, timeout=2.0) -> Optional[ReclaimResponse]:
        body = ReclaimRequest(client_uuid=client_uuid).model_dump()
        try:
            r = self._sync_request("POST", "/reclaim", json_body=body, timeout=timeout)
        except TransportError:
            return None
        if r.status_code != 200:
            return None
        try:
            return ReclaimResponse.model_validate(r.json())
        except (ValueError, json.JSONDecodeError):
            return None

    def resume_blocking(self, room_id, session_token) -> Optional[ResumeResponse]:
        body = ResumeRequest(
            room_id=room_id, session_token=session_token,
        ).model_dump()
        try:
            r = self._sync_request("POST", "/resume", json_body=body)
        except TransportError:
            return None
        if r.status_code != 200:
            return None
        try:
            return ResumeResponse.model_validate(r.json())
        except (ValueError, json.JSONDecodeError):
            return None

    async def healthz_async(self, http) -> Optional[HealthResponse]:
        url = self._url.http("/healthz")
        try:
            r = await http.get(url)
        except (httpx.HTTPError, httpx.TimeoutException):
            return None
        if r.status_code != 200:
            return None
        try:
            return HealthResponse.model_validate(r.json())
        except (ValueError, json.JSONDecodeError):
            return None

    async def matchmake_async(self, req: MatchmakeRequest, http) -> MatchmakeResponse:
        url = self._url.http("/matchmake")
        r = await http.post(url, json=req.model_dump())
        if r.status_code >= 400:
            reason = _safe_error_reason(r) or f"http_{r.status_code}"
            if reason == Reason.VERSION_MISMATCH:
                raise SchemaVersionMismatch(reason)
            raise TransportHTTPError(r.status_code, reason)
        return MatchmakeResponse.model_validate(r.json())

    async def cancel_matchmake_async(self, body: CancelMatchmakeRequest, http) -> None:
        url = self._url.http("/matchmake")
        await http.request("DELETE", url, json=body.model_dump())

    async def resume_async(self, body: ResumeRequest, http) -> Optional[ResumeResponse]:
        url = self._url.http("/resume")
        try:
            r = await http.post(url, json=body.model_dump())
        except (httpx.HTTPError, httpx.TimeoutException):
            return None
        if r.status_code in (401, 410, 404):
            raise FatalResumeError(_safe_error_reason(r) or f"http_{r.status_code}")
        if r.status_code != 200:
            return None
        return ResumeResponse.model_validate(r.json())

    def make_async_http(self):
        return self._async_http_factory()

    async def ws_connect(self, room_id, session_token):
        url = self._url.ws(f"/ws/{room_id}")
        log.info("ws connecting %s", url)
        tls = _TLS_CONTEXT if self._url.ws_scheme == "wss" else None
        ws = await websockets.connect(url, ssl=tls, ping_interval=20, ping_timeout=30)
        await ws.send(AuthMessage(session_token=session_token).model_dump_json())
        return ServerWebSocket(ws)


class ServerWebSocket:

    def __init__(self, ws):
        self._ws = ws

    async def close(self):
        try:
            await self._ws.close()
        except Exception:
            pass

    async def send_move(self, from_sq, to_sq, promotion=None):
        msg = MoveMessage(
            **{"from": from_sq, "to": to_sq}, promotion=promotion,
        )
        await self._send(msg)

    async def send_resign(self):
        await self._send_raw({"type": "resign", "version": PROTOCOL_VERSION})

    async def send_draw_offer(self):
        await self._send_raw({"type": "draw_offer", "version": PROTOCOL_VERSION})

    async def send_draw_response(self, accept):
        await self._send(DrawResponseMessage(accept=accept))

    async def send_rematch_request(self):
        await self._send(RematchRequestMessage())

    async def send_rematch_response(self, accept):
        await self._send(RematchResponseMessage(accept=accept))

    async def send_left_result(self):
        await self._send_raw({"type": "left_result", "version": PROTOCOL_VERSION})

    async def send_takeback_request(self):
        await self._send_raw({"type": "takeback_request", "version": PROTOCOL_VERSION})

    async def send_takeback_response(self, accept):
        await self._send(TakebackResponseMessage(accept=accept))

    async def send_give_time(self, hold_ms):
        await self._send_raw({"type": "give_time", "version": PROTOCOL_VERSION,
                              "hold_ms": hold_ms})

    async def send_ping(self, ply):
        await self._send(PingMessage(ply=ply))

    async def send_skill_check_shot(self, client_elapsed_ms):
        await self._send_raw({"type": "skill_check_shot", "version": PROTOCOL_VERSION,
                              "client_elapsed_ms": client_elapsed_ms})

    async def _send(self, message):
        await self._ws.send(message.model_dump_json(by_alias=True))

    async def _send_raw(self, payload):
        await self._ws.send(json.dumps(payload))

    async def recv(self):
        raw = await self._ws.recv()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
