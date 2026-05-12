from collections import defaultdict

from fastapi import WebSocket

from server import logging_setup
from server.protocol import ConnectionStatusMessage


log = logging_setup.get_logger("chess.server.app")


class ConnectionRegistry:

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


async def send(ws, message):
    if ws is None:
        return True
    try:
        await ws.send_json(message.model_dump(by_alias=True))
        return True
    except Exception as exc:
        log.warning("ws send failed: %s", exc)
        return False


async def broadcast(connections, room, message):
    failed_colors = []
    for color, ws in list(connections.all_for_room(room)):
        if not await send(ws, message):
            failed_colors.append(color)
    for color in failed_colors:
        slot = room.slot(color)
        if slot is not None:
            connections.remove(room.room_id, slot.client_uuid)
        opp_color = room.opp_color(color)
        if opp_color in failed_colors:
            continue
        opp_ws = connections.get_for_color(room, opp_color)
        if opp_ws is None:
            continue
        await send(opp_ws, ConnectionStatusMessage(opp_state="reconnecting"))
