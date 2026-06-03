"""Give 15 sec: local clock cap, debounce, toast wording, online round-trip.

The cap (Clock.add_time) and the giver/receiver toast formatters are pure
logic; the two server tests drive a real WebSocket round-trip end-to-end.
"""
import json
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest
from fastapi.testclient import TestClient

from domain.match import ONLINE
from backend.pieces import PieceColor
from server.app import PROTOCOL_VERSION, create_app
from tests.helpers import FakeClock, fake_uuid4


ALICE = fake_uuid4(1)
BOB = fake_uuid4(2)


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


def _make_app():
    from frontend.frontend import Frontend
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    return app


def _start_local(app, time_minutes=3, incr=0):
    app._on_start_game({
        "mode": "single_screen", "nickname": "Alice",
        "time_minutes": time_minutes, "increment_seconds": incr,
        "side": "white",
    })


def test_local_click_gives_time_to_active_clock_side():
    app = _make_app()
    _start_local(app)
    app.match.clock.white_remaining = 100.0
    app._on_give_time()
    assert app.match.clock.white_remaining == 115.0


def test_local_click_after_first_move_gives_time_to_black():
    from backend.utils import Square
    app = _make_app()
    _start_local(app)
    app.match.try_move(Square(6, 4), Square(4, 4))
    app.match.clock.black_remaining = 100.0
    before_white = app.match.clock.white_remaining
    app._on_give_time()
    assert app.match.clock.white_remaining == before_white
    assert app.match.clock.black_remaining == 115.0


def test_local_debounce_blocks_immediate_second_click():
    app = _make_app()
    _start_local(app)
    app.match.clock.white_remaining = 100.0
    app._on_give_time()
    assert app.match.clock.white_remaining == 115.0
    app._on_give_time()
    assert app.match.clock.white_remaining == 115.0


@pytest.mark.parametrize(
    "start_remaining, expected_remaining, toast_fmt",
    [
        pytest.param(
            180.0, 180.0, "{name} already at maximum time",
            id="full_cap_no_add_announces_maximum",
        ),
        pytest.param(
            173.0, 180.0, "Gave 7 sec to {name}",
            id="partial_cap_announces_actual_amount",
        ),
        pytest.param(
            100.0, 115.0, "Gave 15 sec to {name}",
            id="full_amount_uses_recipient_nickname",
        ),
    ],
)
def test_local_give_time_caps_and_toasts(
    monkeypatch, start_remaining, expected_remaining, toast_fmt
):
    app = _make_app()
    _start_local(app, time_minutes=3, incr=0)
    app.match.clock.white_remaining = start_remaining
    toast_calls = []
    monkeypatch.setattr(app.toast, "show", lambda msg, **kw: toast_calls.append(msg))
    app._on_give_time()
    assert app.match.clock.white_remaining == expected_remaining
    assert toast_calls == [toast_fmt.format(name=app.white_name)]


def test_local_noop_when_no_clock():
    app = _make_app()
    app._on_start_game({
        "mode": "single_screen", "nickname": "Alice",
        "time_minutes": None, "increment_seconds": 0,
        "side": "white",
    })
    app._on_give_time()
    assert app.match.clock is None


def test_local_noop_when_game_over():
    app = _make_app()
    _start_local(app)
    app.match.clock.white_remaining = 100.0
    app.manual_result = "white_wins_by_resignation"
    before = app.match.clock.white_remaining
    app._on_give_time()
    assert app.match.clock.white_remaining == before


def test_disabled_keys_excludes_give_time_when_clock_present_and_idle():
    app = _make_app()
    _start_local(app)
    app._last_give_time_at_ms = -10_000
    assert "give_time" not in app._right_menu_disabled_keys()


def test_disabled_keys_includes_give_time_during_debounce():
    app = _make_app()
    _start_local(app)
    app._last_give_time_at_ms = pg.time.get_ticks()
    assert "give_time" in app._right_menu_disabled_keys()


def test_disabled_keys_includes_give_time_when_no_clock():
    app = _make_app()
    app._on_start_game({
        "mode": "single_screen", "nickname": "Alice",
        "time_minutes": None, "increment_seconds": 0,
        "side": "white",
    })
    assert "give_time" in app._right_menu_disabled_keys()


def test_disabled_keys_includes_give_time_after_result():
    app = _make_app()
    _start_local(app)
    app.manual_result = "white_wins_by_resignation"
    assert "give_time" in app._right_menu_disabled_keys()


def test_online_client_send_give_time_enqueues():
    from online.client import OnlineClient
    client = OnlineClient()
    client._loop = MagicMock()
    client._loop.is_closed.return_value = False
    client._outbound = MagicMock()
    client.send_give_time()
    client._loop.call_soon_threadsafe.assert_called_once()
    args = client._loop.call_soon_threadsafe.call_args.args
    method, method_args = args[1]
    assert method == "send_give_time"
    assert method_args == ()


def _online_app():
    app = _make_app()
    app.online_client = MagicMock()
    app.mode = ONLINE
    app.white_name = "Alice"
    app.black_name = "Bob"
    app._chosen_side = "white"
    app.match.mode = ONLINE
    app.match.local_color = PieceColor.WHITE
    return app


@pytest.mark.parametrize(
    "granted_by, seconds_added, expected_toasts",
    [
        pytest.param("white", 15.0, ["Gave 15 sec to Bob"], id="giver_full_recipient_toast"),
        pytest.param("white", 0.0, ["Bob already at maximum time"], id="giver_cap_toast"),
        pytest.param("black", 15.0, ["Bob gave you 15 seconds"], id="receiver_giver_toast"),
        pytest.param("black", 0.0, [], id="receiver_silent_on_zero_add"),
    ],
)
def test_time_granted_routes_toast(monkeypatch, granted_by, seconds_added, expected_toasts):
    app = _online_app()
    toast_calls = []
    monkeypatch.setattr(app.toast, "show", lambda msg, **kw: toast_calls.append(msg))
    app._handle_time_granted({
        "granted_by": granted_by, "seconds_added": seconds_added, "clock": {},
    })
    assert toast_calls == expected_toasts


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app_server(clock):
    return create_app(now_provider=clock, max_rooms=8)


@pytest.fixture
def client(app_server):
    return TestClient(app_server)


def _matchmake(client, *, uuid, nickname, side, time=5, inc=0):
    return client.post("/matchmake", json={
        "version": PROTOCOL_VERSION,
        "client_uuid": uuid, "nickname": nickname,
        "time_minutes": time, "increment_seconds": inc,
        "side_preference": side,
    }).json()


def _auth(token):
    return {"version": PROTOCOL_VERSION, "type": "auth", "session_token": token}


def test_server_broadcasts_time_granted_to_both_peers(client):
    random.seed(0)
    a = _matchmake(client, uuid=ALICE, nickname="Alice", side="white",
                   time=5, inc=0)
    b = _matchmake(client, uuid=BOB, nickname="Bob", side="black",
                   time=5, inc=0)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            room = client.app.state.rooms.get(a["room_id"])
            room.backend.clock.white_remaining = 200.0
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "give_time"}))
            granted_w = json.loads(ws_w.receive_text())
            granted_b = json.loads(ws_b.receive_text())
            assert granted_w["type"] == "time_granted"
            assert granted_w["granted_by"] == "black"
            assert granted_w["seconds_added"] == pytest.approx(15.0)
            assert granted_w["clock"]["white_remaining"] == pytest.approx(215.0, abs=1.0)
            assert granted_b == granted_w


def test_server_caps_at_initial_seconds_and_still_broadcasts(client):
    random.seed(0)
    a = _matchmake(client, uuid=ALICE, nickname="Alice", side="white",
                   time=5, inc=0)
    b = _matchmake(client, uuid=BOB, nickname="Bob", side="black",
                   time=5, inc=0)
    with client.websocket_connect(f"/ws/{a['room_id']}") as ws_w:
        ws_w.send_text(json.dumps(_auth(a["session_token"])))
        with client.websocket_connect(f"/ws/{b['room_id']}") as ws_b:
            ws_b.send_text(json.dumps(_auth(b["session_token"])))
            ws_w.receive_text()
            ws_b.receive_text()
            ws_b.send_text(json.dumps({"version": PROTOCOL_VERSION,
                                       "type": "give_time"}))
            granted = json.loads(ws_w.receive_text())
            ws_b.receive_text()
            assert granted["type"] == "time_granted"
            assert granted["seconds_added"] == pytest.approx(0.0)
            assert granted["granted_by"] == "black"
