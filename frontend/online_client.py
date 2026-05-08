"""OnlineClient stub. Phase 4 ships canned responses so the modal flow can
be QA'd visually without a server. Phase 5 replaces this with a real WS
client running on a background thread."""
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Event:
    type: str
    payload: dict


class OnlineClient:

    def __init__(self):
        self._inbound = deque()
        self._scheduled = []
        self.state = "disconnected"
        self.ping_ms = None
        self._addr = None

    def connect(self, addr, request):
        self._addr = addr
        self.state = "connected"
        now = time.monotonic()
        # Canned: pretend the server matchmade, paired us, and started the game.
        self._scheduled.append((now + 0.2, Event("matchmake_response", {
            "room_id": "stub-room", "session_token": "stub-token",
        })))
        your_color = "white"
        opp_color = "black"
        self._scheduled.append((now + 1.5, Event("game_start", {
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "white_name": request.get("nickname", "You"),
            "black_name": "StubOpponent",
            "time_minutes": request.get("time_minutes", 5),
            "increment_seconds": request.get("increment_seconds", 0),
            "your_color": your_color,
        })))

    def cancel_queue(self):
        self._scheduled = []
        self._inbound.clear()
        self.state = "disconnected"

    def disconnect(self):
        self._scheduled = []
        self.state = "disconnected"

    def send_move(self, from_sq, to_sq, promotion=None):
        pass

    def send_resign(self):
        pass

    def send_draw_offer(self):
        pass

    def send_draw_response(self, accept):
        pass

    def send_rematch_request(self):
        pass

    def send_rematch_response(self, accept):
        pass

    def send_takeback_request(self):
        pass

    def send_takeback_response(self, accept):
        pass

    def drain_inbound(self):
        now = time.monotonic()
        ready = [ev for ts, ev in self._scheduled if ts <= now]
        self._scheduled = [(ts, ev) for ts, ev in self._scheduled if ts > now]
        return ready
