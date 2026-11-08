"""Two real Frontends, one real server -- Deck #99, the declined rematch whose
decliner pressed New Search and was not searched for.

The faked-server tests in test_online_ux.py pin each coordinator step on its
own. This file drives the whole thing unfaked: FIND MATCH through the Play
panel's own CTA, real HTTP + WebSockets, real frames on both apps, the result
card's Rematch and the banner's Deny answered by clicks through the input
router, then New Search on both closed cards until the two players meet again
in a fresh room.

Three things make two Frontends in one process behave like two installations:
- an identity holder: env.get_or_create_client_uuid and env.get_nickname are
  read through the seat whose frame or click is running right now;
- a tap on every OnlineClient the coordinator builds, recording each request it
  queues with and every event its network thread delivers (the coordinator may
  drop the client before it drains the tail, so the tap is the only honest
  witness of what the server sent);
- the background /reclaim probe is switched off, because two apps polling one
  server would trip its per-IP limit. The reconnected-decliner case runs the
  real probe worker exactly once, by hand.
"""
import queue
import time
from contextlib import contextmanager

import pytest

from chessshootout.backend.utils import square_from_coord
from chessshootout.domain.match import ONLINE
from chessshootout.frontend import online_coordinator as coordinator_module
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.modals.result import ResultButtons
from chessshootout.frontend.online_coordinator import OnlineCoordinator
from chessshootout.infra import env
from chessshootout.online.client import OnlineClient
from chessshootout.server.protocol import Reason
from tests.conftest import pygame_display
from tests.helpers import fake_uuid4, make_app


_pygame_init = pygame_display(1000, 800)

FRAME_SLEEP_SECONDS = 0.005
SETTLE_TIMEOUT_SECONDS = 15.0
# The server's half of a socket close -- registry remove, then the opponent
# notice the old code sent -- runs in one coroutine right after the remove, so
# this window is generous.
LATE_CLOSE_WINDOW_SECONDS = 0.5
DISCONNECTED_TOAST_FRAGMENT = "disconnected — waiting"
WINDOW_CLOSED_TOAST = "Rematch window closed"
ORDERS = ["decliner_first", "offerer_first", "reconnected_decliner"]
# A freshly started installation's Play panel, which Reconnect dresses with the
# room's time control but must leave on its own side preference.
RESTARTED_PANEL_SIDE = "random"


class _TapQueue(queue.Queue):
    """An inbound queue that also remembers every event ever put on it."""

    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def put(self, item, block=True, timeout=None):
        self._sink.append(item)
        super().put(item, block, timeout)


class _Identity:
    """Which seat is acting right now. Both apps share one process, one env
    module and one data dir, so the identity the coordinator reads has to be
    switched per seat before each of its frames and clicks."""

    def __init__(self):
        self.seat = None

    def uuid(self):
        return self.seat.uuid

    def nickname(self):
        return self.seat.nickname


def _tap_client_class(identity):
    """An OnlineClient that files itself under the seat that built it and
    records its matchmake request and every inbound event."""

    class _TapClient(OnlineClient):
        def __init__(self):
            super().__init__()
            self.seen = []
            self.requests = []
            self._inbound = _TapQueue(self.seen)
            identity.seat.clients.append(self)

        def connect(self, addr, request):
            self.requests.append(dict(request))
            super().connect(addr, request)

    return _TapClient


class _Seat:
    """One installation: its own Frontend, identity and every client it ran."""

    def __init__(self, identity, name, uuid, side):
        self.identity = identity
        self.nickname = name
        self.uuid = uuid
        self.side = side
        self.clients = []
        self.identity.seat = self
        self.app = make_app(1000, 800)

    @property
    def coordinator(self):
        return self.app.coordinator

    @property
    def game(self):
        return self.app.game

    @property
    def card(self):
        return self.app.game.result_menu

    @property
    def play_view(self):
        return self.app.menu.play_view

    def frame(self):
        self.identity.seat = self
        self.app.draw_frame()
        self.app._execute_pending_nav()

    def click(self, pos):
        self.identity.seat = self
        self.app.input_router.mouse_left_clicked(pos)
        self.app._execute_pending_nav()

    def search_config(self):
        self.identity.seat = self
        return self.play_view.build_online_config()

    def plies(self):
        return len(self.game.match.move_history)

    def on_board(self):
        return (self.app.screen is self.game and self.game.variant == Variant.ONLINE
                and self.coordinator._pending_game_start_payload is None
                and self.coordinator.client is not None
                and self.coordinator.client.state == "connected")

    def closed(self):
        return (self.card.button_state is ResultButtons.ONLINE_CLOSED
                and self.coordinator.client is None)


def _pump(seats, seconds):
    """Run real frames on the given apps for a wall-clock window."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        for seat in seats:
            seat.frame()
        time.sleep(FRAME_SLEEP_SECONDS)


def _pump_until(seats, predicate, timeout=SETTLE_TIMEOUT_SECONDS, each_frame=None):
    """Run real frames on the given apps until a condition holds, or give up.
    each_frame, when given, is checked after every round of frames, which is
    how a "never shows" assertion covers every frame rather than a sample."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for seat in seats:
            seat.frame()
        if each_frame is not None:
            each_frame()
        if predicate():
            return True
        time.sleep(FRAME_SLEEP_SECONDS)
    return predicate()


def _wait(predicate, timeout=SETTLE_TIMEOUT_SECONDS):
    """Poll a condition without running any frames."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(FRAME_SLEEP_SECONDS)
    return predicate()


def _find_match(seat):
    """Press FIND MATCH the way a player does: frame the menu, click the
    Online chip, pick the side, click the CTA."""
    seat.frame()
    view = seat.play_view
    seat.click(view._mode_rects[ONLINE].center)
    view.selected_side = seat.side
    view.selected_time_minutes, view.selected_increment_seconds = 5, 0
    seat.frame()
    seat.click(view._cta_rect.center)
    assert seat.coordinator.wait_modal.is_visible(), "FIND MATCH starts a search"


def _quiet_move(seats, mover, frm, to, ply):
    """Play a non-capturing move through the online gate and wait for the
    server's confirmation to reach both boards."""
    mover.identity.seat = mover
    from_sq, to_sq = square_from_coord(frm), square_from_coord(to)
    assert mover.game.skillcheck_session.skillcheck_gate(from_sq, to_sq) is False
    assert mover.game.match.try_move(from_sq, to_sq).legal
    assert _pump_until(seats, lambda: all(s.plies() == ply for s in seats)), \
        f"{frm}{to} never reached both boards"


def _events(client, start=0):
    return [(event.type, event.payload) for event in client.seen[start:]]


def _rematch_events(client, start=0):
    return [payload.get("event") for kind, payload in _events(client, start)
            if kind == "rematch_update"]


def _active_room_ids(server_app):
    return set(server_app.state.rooms._active)


def _reconnect(identity, addr, seat):
    """Restart this seat's installation and bring it back through the menu's
    Reconnect button: a fresh Frontend, one real /reclaim probe run by hand,
    then the click. The rebuilt session never searched, so it carries no
    search config -- the state Deck #99's decliner was in."""
    for client in seat.clients:
        client.disconnect()
    restarted = _Seat(identity, seat.nickname, seat.uuid, seat.side)
    coordinator = restarted.coordinator
    coordinator._reconnect_probe_worker(addr, seat.uuid, coordinator._reconnect_probe_gen)
    assert coordinator.reconnect_available(), "the probe found the waiting game"
    restarted.frame()
    restarted.frame()
    restarted.click(restarted.play_view._recon_button.center)
    return restarted


@contextmanager
def _table(server_with_app, monkeypatch, tmp_path, base):
    """Two installations aimed at the running server. Every client either one
    ever built is disconnected on the way out, whatever happened."""
    port, server_app = server_with_app
    addr = f"localhost:{port}"
    monkeypatch.setenv("CHESS_SERVER_ADDR", addr)
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(OnlineCoordinator, "_spawn_reconnect_probe", lambda self: None)
    identity = _Identity()
    monkeypatch.setattr(env, "get_or_create_client_uuid", identity.uuid)
    monkeypatch.setattr(env, "get_nickname", identity.nickname)
    monkeypatch.setattr(coordinator_module, "OnlineClient", _tap_client_class(identity))
    seats = []
    try:
        ann = _Seat(identity, "Ann", fake_uuid4(base), "white")
        seats.append(ann)
        bob = _Seat(identity, "Bob", fake_uuid4(base + 1), "black")
        seats.append(bob)
        yield identity, addr, server_app, ann, bob, seats
    finally:
        for seat in seats:
            for client in seat.clients:
                client.disconnect()


def _play_to_offer(identity, addr, server_app, ann, bob, seats, *, reconnect_bob):
    """FIND MATCH on both, e4 e5 so the resign scores, Ann resigns and asks
    for a rematch from her card, until Bob's banner shows the offer. With
    reconnect_bob, Bob's installation is restarted at ply 2 and rejoins
    through Reconnect before the resign. Returns Bob as he now is, plus the
    first room's id."""
    _find_match(ann)
    _find_match(bob)
    assert _pump_until((ann, bob), lambda: ann.on_board() and bob.on_board()), \
        "FIND MATCH on both never paired them onto a board"
    (first_room,) = _active_room_ids(server_app)
    _quiet_move((ann, bob), ann, "e2", "e4", 1)
    _quiet_move((ann, bob), bob, "e7", "e5", 2)

    if reconnect_bob:
        bob = _reconnect(identity, addr, bob)
        seats.append(bob)
        assert _pump_until((ann, bob), bob.on_board), "Reconnect never rejoined the game"
        assert bob.plies() == 2
        assert bob.coordinator._online_config is None, \
            "a session rebuilt by Reconnect never searched"
        assert bob.play_view.selected_side == RESTARTED_PANEL_SIDE, \
            "the colour held in the room is not a side preference"
        assert bob.play_view.selected_mode == ONLINE
        assert (bob.play_view.selected_time_minutes,
                bob.play_view.selected_increment_seconds) == (5, 0)

    ann.identity.seat = ann
    assert ann.coordinator.send_resign()
    assert _pump_until((ann, bob), lambda: "rematch" in ann.card.button_rects
                       and bob.game.current_result() is not None), \
        "the result never reached both cards"
    assert bob.game.result_flow.series_score("black") == 1.0, "a ply-2 resign scores"

    ann.click(ann.card.button_rects["rematch"].center)
    assert _pump_until((ann, bob), lambda: bob.coordinator._rematch_offered
                       and bob.coordinator.offer_banners.count() == 1
                       and bob.coordinator.offer_banners._banners[0]["no_rect"].width > 0), \
        "Bob never saw Ann's rematch offer"
    return bob, first_room


def _rematch_hidden_on(seat):
    """A per-frame check: once the decliner has said no, the online row never
    offers Rematch again."""
    def check():
        if seat.card.button_state is ResultButtons.ONLINE:
            assert "rematch" not in seat.card.button_rects, \
                "the decliner's Rematch flashed back after Deny"
    return check


def _decline(bob):
    """Bob clicks the banner's Deny; returns where his client's tap stood.

    The card is repainted on its own straight after the click, before any
    coordinator update can drain the server's echo: that one paint is the
    moment the old code flashed Rematch back into New Search's slot, and a
    full frame cannot be relied on to land in it on a fast loopback."""
    client = bob.coordinator.client
    mark = len(client.seen)
    bob.click(bob.coordinator.offer_banners._banners[0]["no_rect"].center)
    assert bob.coordinator._rematch_offered is False
    assert bob.coordinator.client is client, "the client lives until the server's echo"
    assert bob.card.button_state is ResultButtons.ONLINE
    bob.card.draw()
    assert "rematch" not in bob.card.button_rects, "Rematch flashed back after Deny"
    assert "menu" in bob.card.button_rects, "the row itself is still drawn"
    return client, mark


@pytest.mark.parametrize("order", ORDERS)
def test_the_decliner_and_the_offerer_both_search_again_after_a_declined_rematch(
        server_with_app, monkeypatch, tmp_path, order):
    """Deny the rematch, then New Search on both closed cards: each search
    queues, and the second pairs them into a brand-new room at 0-0."""
    with _table(server_with_app, monkeypatch, tmp_path, 61) as (
            identity, addr, server_app, ann, bob, seats):
        bob, first_room = _play_to_offer(identity, addr, server_app, ann, bob, seats,
                                         reconnect_bob=order == "reconnected_decliner")
        ann_client = ann.coordinator.client
        bob_client, mark = _decline(bob)
        hidden = _rematch_hidden_on(bob)

        # Hold Bob's frames while Ann's card closes and her socket goes: a
        # decliner still connected at that moment is exactly who the old
        # ws_session finally used to tell "opponent reconnecting" about a room
        # it had already dropped.
        assert _pump_until((ann,), ann.closed), "the offerer's card never closed"
        assert "declined" in _rematch_events(ann_client)
        assert ann.app.toast.message == f"{bob.nickname} declined the rematch"
        assert _wait(lambda: server_app.state.connections.get_for_uuid(
            first_room, ann.uuid) is None), "the server never saw Ann's socket go"
        time.sleep(LATE_CLOSE_WINDOW_SECONDS)
        assert bob_client.state == "connected", "Bob was still there to be told"
        assert "opponent_reconnecting" not in _rematch_events(bob_client, mark), \
            "a dropped room sent its decliner a reconnecting notice"

        assert _pump_until((ann, bob), bob.closed, each_frame=hidden), \
            "the decliner's card never closed"
        hidden()
        assert _rematch_events(bob_client, mark) == ["window_expired"]
        assert DISCONNECTED_TOAST_FRAGMENT not in (bob.app.toast.message or "")
        assert bob.app.toast.message == WINDOW_CLOSED_TOAST
        assert ann.closed() and bob.closed()
        assert first_room not in _active_room_ids(server_app)
        for seat in (ann, bob):
            assert seat.game.variant == Variant.ONLINE, "the closed card keeps the board"
            assert seat.app.screen is seat.game

        first, second = (ann, bob) if order == "offerer_first" else (bob, ann)
        for seat in (first, second):
            assert _pump_until((ann, bob), lambda: "new_search" in seat.card.button_rects), \
                "the closed card never offered New Search"

        expected = {seat: seat.search_config() for seat in (ann, bob)}
        before = {seat: len(seat.clients) for seat in (ann, bob)}
        first.click(first.card.button_rects["new_search"].center)
        assert first.coordinator.wait_modal.is_visible(), "New Search shows the wait card"
        assert first.app.screen is first.app.menu
        assert _pump_until((ann, bob), lambda: first.coordinator.client is not None
                           and first.coordinator.client.state == "connected"
                           and server_app.state.rooms.queue_depth == 1), \
            "the first New Search never queued on the server"
        assert second.coordinator.client is None, "the other card is still closed"

        second.click(second.card.button_rects["new_search"].center)
        assert second.coordinator.wait_modal.is_visible()
        assert _pump_until((ann, bob), lambda: ann.on_board() and bob.on_board()), \
            "the two New Searches never paired"
        assert server_app.state.rooms.queue_depth == 0
        (second_room,) = _active_room_ids(server_app)
        assert second_room != first_room, "a fresh pairing, not the declined room"

        for seat in (ann, bob):
            (request,) = [client.requests[0] for client in seat.clients[before[seat]:]]
            config = expected[seat]
            assert request["client_uuid"] == seat.uuid
            assert request["nickname"] == seat.nickname == config["nickname"]
            assert request["side_preference"] == config["side"]
            assert request["time_minutes"] == config["time_minutes"]
            assert request["increment_seconds"] == config["increment_seconds"]
            assert seat.app.screen is seat.game
            assert seat.game.variant == Variant.ONLINE
            assert seat.game.result_flow.series_score("white") == 0.0
            assert seat.game.result_flow.series_score("black") == 0.0
            assert seat.plies() == 0
        assert {ann.coordinator.client._room_id, bob.coordinator.client._room_id} == \
            {second_room}
        if order == "reconnected_decliner":
            # The rebuilt session searched with its own Play panel's side, not
            # the colour it happened to hold in the resumed room.
            assert expected[bob]["side"] == RESTARTED_PANEL_SIDE
            assert bob.game.match.local_color is not None


def test_a_rematch_asked_for_on_the_declined_room_is_unavailable(
        server_with_app, monkeypatch, tmp_path):
    """The decliner's socket outlives the room by a round trip. A rematch
    request sent down it in that gap must be refused, not relayed to an
    offerer who is no longer in any game."""
    with _table(server_with_app, monkeypatch, tmp_path, 71) as (
            identity, addr, server_app, ann, bob, seats):
        bob, first_room = _play_to_offer(identity, addr, server_app, ann, bob, seats,
                                         reconnect_bob=False)
        ann_client = ann.coordinator.client
        bob_client, mark = _decline(bob)
        ann_mark = len(ann_client.seen)
        bob_client.send_rematch_request()

        def refused():
            return any(kind == "error" and payload.get("reason") == Reason.REMATCH_UNAVAILABLE
                       for kind, payload in _events(bob_client, mark))

        assert _wait(refused), "the dead room's rematch request was not refused"
        events = _events(bob_client, mark)
        expired = events.index(("rematch_update", next(
            payload for kind, payload in events
            if kind == "rematch_update" and payload.get("event") == "window_expired")))
        assert expired < next(i for i, (kind, _) in enumerate(events) if kind == "error"), \
            "the decline closed the window before the late request was judged"
        assert first_room not in _active_room_ids(server_app)
        assert not any(kind == "rematch_request" for kind, _ in _events(ann_client, ann_mark)), \
            "the offerer was never asked again"

        assert _pump_until((ann, bob), lambda: ann.closed() and bob.closed()), \
            "the cards never closed"
        assert DISCONNECTED_TOAST_FRAGMENT not in (bob.app.toast.message or "")
