from collections import defaultdict
from collections.abc import Iterator

from fastapi import WebSocket
from pydantic import BaseModel

from chessshootout.server import logging_setup
from chessshootout.server.protocol import ConnectionStatusMessage
from chessshootout.server.rooms import Room, RoomManager


log = logging_setup.get_logger("chess.server.app")


class ConnectionRegistry:
    """
    The server's book of live player sockets, one entry per room and per player
    id inside it. Colors are reshuffled at pairing and swapped again at every
    rematch, so a socket is always filed under its owner's identity rather than
    under a side of the board
    """

    def __init__(self) -> None:
        """
        Start with an empty book. One registry is built per application and
        lives for the whole process, alongside the room manager
        """
        self._by_room: dict[str, dict[str, WebSocket]] = defaultdict(dict)

    def add(self, room_id: str, client_uuid: str, ws: WebSocket) -> WebSocket | None:
        """
        File the socket a player is now using for a room, replacing whatever
        they had before. The replaced socket is handed straight back so the
        caller can close it, which is how a reconnect supersedes a stale one

        :param room_id: room the socket is joining
        :param client_uuid: player id owning the socket, the identity that
            survives a color swap
        :param ws: freshly accepted websocket to file
        :returns: the socket that was displaced, or None when there was none or
            the very same socket was re-filed
        """
        displaced = self._by_room[room_id].get(client_uuid)
        self._by_room[room_id][client_uuid] = ws
        return displaced if displaced is not ws else None

    def remove(self, room_id: str, client_uuid: str, ws: WebSocket) -> bool:
        """
        Take a player's socket out of the book when it closes, but only while it
        is still the one on file -- a socket that was already superseded must
        never unregister its replacement. The room's entry disappears with its
        last socket, so an empty room leaves nothing behind

        :param room_id: room the socket belonged to
        :param client_uuid: player id that owned it
        :param ws: socket that closed, compared against the stored one
        :returns: True when this socket was the live one and was removed
        """
        room = self._by_room.get(room_id)
        if room is None or room.get(client_uuid) is not ws:
            return False
        room.pop(client_uuid, None)
        if not room:
            self._by_room.pop(room_id, None)
        return True

    def get_for_color(self, room: Room, color: str) -> WebSocket | None:
        """
        Find the socket of whoever is playing that side of the board right now.
        This is the normal way the server reaches one player, and because the
        lookup goes through the room's slot it follows a rematch color swap

        :param room: room to look inside
        :param color: white or black, as the room currently seats the players
        :returns: that player's socket, or None when the seat is empty or they
            are not connected
        """
        slot = room.slot(color)
        if slot is None:
            return None
        return self._by_room.get(room.room_id, {}).get(slot.client_uuid)

    def get_for_uuid(self, room_id: str, client_uuid: str) -> WebSocket | None:
        """
        Find a player's socket by identity instead of by color, which is what
        the reclaim path needs: it knows who is asking before it knows which
        side of the board they are on

        :param room_id: room to look inside
        :param client_uuid: player id being looked up
        :returns: that player's socket in the room, or None when they have none
        """
        return self._by_room.get(room_id, {}).get(client_uuid)

    def has_both(self, room: Room) -> bool:
        """
        Say whether both players of a paired room are connected right now, the
        condition the server waits for before it starts the game. A room that
        is still waiting for an opponent can never satisfy it

        :param room: room to check
        :returns: True when the room is paired and both players hold a socket
        """
        if not room.is_paired():
            return False
        present = self._by_room.get(room.room_id, {})
        return (room.white.client_uuid in present
                and room.black.client_uuid in present)

    def all_for_room(self, room: Room) -> Iterator[tuple[str, WebSocket]]:
        """
        Walk the connected players of one room in white-then-black order, which
        is what broadcasting a frame to a game iterates over. Missing or
        disconnected sides are simply skipped

        :param room: room whose players are wanted
        :returns: each connected side paired with its socket
        """
        for color in ("white", "black"):
            ws = self.get_for_color(room, color)
            if ws is not None:
                yield color, ws

    def all_active(self) -> Iterator[tuple[str, WebSocket]]:
        """
        Walk every live socket the server holds, across all rooms. Shutdown uses
        it to tell everyone the server is going down before closing them

        :returns: each socket paired with the room id it belongs to
        """
        for room_id, by_uuid in self._by_room.items():
            for ws in by_uuid.values():
                yield room_id, ws


async def send(ws: WebSocket | None, message: BaseModel) -> bool:
    """
    Send one protocol frame to a player, serialised with its wire aliases so
    fields such as from and to keep their protocol spelling. Sending is
    best-effort: a socket that has already gone away is logged and reported,
    never raised, so one dead player cannot break the other's game

    :param ws: target socket, or None when the player is not connected, which
        counts as a successful no-op
    :param message: protocol model to serialise and send
    :returns: True when the frame went out or there was nobody to send it to
    """
    if ws is None:
        return True
    try:
        await ws.send_json(message.model_dump(by_alias=True))
        return True
    except Exception as exc:
        log.warning("ws send failed: %s", exc)
        return False


async def broadcast(rooms: RoomManager, connections: ConnectionRegistry,
                    room: Room, message: BaseModel) -> None:
    """
    Send one frame to both players of a game -- the way every shared event, from
    a move to a result, reaches the board. A player whose socket fails is
    unregistered and marked disconnected on the spot, and the other side is told
    they are reconnecting, so a broken pipe turns into visible status rather
    than silence

    :param rooms: room manager told about the failed side
    :param connections: registry the failed socket is unregistered from
    :param room: room whose players receive the frame
    :param message: protocol model to serialise and send to both sides
    """
    failed = []
    for color, ws in list(connections.all_for_room(room)):
        if not await send(ws, message):
            failed.append((color, ws))
    failed_colors = {color for color, _ in failed}
    for color, ws in failed:
        slot = room.slot(color)
        if slot is not None:
            connections.remove(room.room_id, slot.client_uuid, ws)
        rooms.mark_disconnected(room.room_id, color)
        opp_color = room.opp_color(color)
        if opp_color in failed_colors:
            continue
        opp_ws = connections.get_for_color(room, opp_color)
        if opp_ws is None:
            continue
        await send(opp_ws, ConnectionStatusMessage(opp_state="reconnecting"))
