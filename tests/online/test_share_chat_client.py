"""Client-side wiring for shared annotations + quick chat: OnlineClient send
facades enqueue the transport method by name, OnlineCoordinator passthroughs
guard on a live client, and inbound routing forwards to the subscriber. The
board-state guards diverge on purpose: annotations_state/annotation_delta are
buffered mid-resync and replayed in order once the resume lands (the server may
have applied them after the /resume snapshot; delta application is idempotent
so replaying pre-snapshot ones is safe) while quick_chat_received always
forwards immediately (a chat is board-independent and delaying it silently
loses the moment). The buffer dies with the resync: teardown and a failed
resume both clear it. rate_limited feedback for the new msg_types stays on the
transient toast path — it must never escalate to the confirm/retry modal.

The /resume dump pin lives here too: every response dict the client hands the
frontend is model_dump(by_alias=True), so ArrowWire/LockWire/pending keys come
out as their wire aliases ("from"/"to") — exactly what GameScreen's decoders
read. A field-name dump silently drops every shared arrow on restore."""

from unittest.mock import MagicMock, call

import pytest

from tests.conftest import pygame_display
from chessshootout.backend.utils import Square
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.screens.game import GameScreen
from chessshootout.online.client import Event, OnlineClient, fetch_resume
from chessshootout.server.protocol import Reason, ResumeResponse
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)


def _stub_outbound(client):
    client._loop = MagicMock()
    client._loop.is_closed.return_value = False
    client._outbound = MagicMock()


def _enqueued(client):
    client._loop.call_soon_threadsafe.assert_called_once()
    _, (method, method_args) = client._loop.call_soon_threadsafe.call_args.args
    return method, method_args


def test_send_annotations_state_enqueues_transport_method_by_name():
    client = OnlineClient()
    _stub_outbound(client)
    client.send_annotations_state(True, ["e4"], [("e2", "e4")])
    method, method_args = _enqueued(client)
    assert method == "send_annotations_state"
    assert method_args == (True, ["e4"], [("e2", "e4")])


def test_send_annotation_delta_enqueues_all_five_positional_args():
    client = OnlineClient()
    _stub_outbound(client)
    client.send_annotation_delta("add", "arrow", from_sq="e2", to_sq="e4")
    method, method_args = _enqueued(client)
    assert method == "send_annotation_delta"
    assert method_args == ("add", "arrow", None, "e2", "e4")


def test_send_quick_chat_enqueues_transport_method_by_name():
    client = OnlineClient()
    _stub_outbound(client)
    client.send_quick_chat(2)
    method, method_args = _enqueued(client)
    assert method == "send_quick_chat"
    assert method_args == (2,)


def test_send_facades_are_inert_with_no_client():
    app = make_app(1000, 800)
    assert app.coordinator.client is None
    app.coordinator.send_annotations_state(True, ["e4"], [("e2", "e4")])
    app.coordinator.send_annotation_delta("add", "highlight", square="c3")
    app.coordinator.send_quick_chat(0)


def test_send_facades_delegate_to_the_live_client():
    app = make_app(1000, 800)
    client = MagicMock()
    app.coordinator.client = client

    app.coordinator.send_annotations_state(False, ["d5"], [("g1", "f3")])
    client.send_annotations_state.assert_called_once_with(False, ["d5"], [("g1", "f3")])

    app.coordinator.send_annotation_delta("remove", "arrow", from_sq="e2", to_sq="e4")
    client.send_annotation_delta.assert_called_once_with(
        "remove", "arrow", None, "e2", "e4")

    app.coordinator.send_quick_chat(3)
    client.send_quick_chat.assert_called_once_with(3)


def _subscribed_coordinator():
    app = make_app(1000, 800)
    subscriber = MagicMock()
    app.coordinator.subscribe(subscriber)
    return app, subscriber


def test_annotations_state_forwarded_to_subscriber():
    app, subscriber = _subscribed_coordinator()
    payload = {"sharing": True, "highlights": ["e4"], "arrows": [{"from": "e2", "to": "e4"}]}
    app.coordinator._handle_online_event(Event("annotations_state", payload))
    subscriber.on_annotations_state.assert_called_once_with(payload)


def test_annotation_delta_forwarded_to_subscriber():
    app, subscriber = _subscribed_coordinator()
    payload = {"action": "add", "kind": "arrow", "from": "e2", "to": "e4"}
    app.coordinator._handle_online_event(Event("annotation_delta", payload))
    subscriber.on_annotation_delta.assert_called_once_with(payload)


def test_quick_chat_forwarded_to_subscriber():
    app, subscriber = _subscribed_coordinator()
    payload = {"preset": 1, "sender": "white"}
    app.coordinator._handle_online_event(Event("quick_chat_received", payload))
    subscriber.on_quick_chat.assert_called_once_with(payload)


def test_annotations_state_buffered_while_resyncing():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    payload = {"sharing": True, "highlights": [], "arrows": []}
    app.coordinator._handle_online_event(Event("annotations_state", payload))
    subscriber.on_annotations_state.assert_not_called()
    assert app.coordinator._resync_buffer == [("on_annotations_state", payload)]


def test_annotation_delta_buffered_while_resyncing():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    payload = {"action": "add", "kind": "highlight", "square": "c3"}
    app.coordinator._handle_online_event(Event("annotation_delta", payload))
    subscriber.on_annotation_delta.assert_not_called()
    assert app.coordinator._resync_buffer == [("on_annotation_delta", payload)]


def test_buffered_annotation_events_replay_in_order_after_resume():
    """Frames the server applied after its /resume snapshot land on the fresh
    board right after on_resume, in arrival order — not silently lost."""
    app, subscriber = _subscribed_coordinator()
    app.game.variant = Variant.ONLINE
    app.coordinator._resyncing = True
    state = {"sharing": True, "highlights": ["e4"], "arrows": []}
    delta = {"action": "add", "kind": "highlight", "square": "c3"}
    app.coordinator._handle_online_event(Event("annotations_state", state))
    app.coordinator._handle_online_event(Event("annotation_delta", delta))
    manager = MagicMock()
    manager.attach_mock(subscriber, "sub")
    app.coordinator._handle_game_resumed({"move_history": []})
    assert manager.mock_calls == [
        call.sub.on_resume({"move_history": []}),
        call.sub.on_annotations_state(state),
        call.sub.on_annotation_delta(delta),
    ]
    assert app.coordinator._resync_buffer == []
    assert app.coordinator._resyncing is False


def test_resync_buffer_cleared_on_teardown_and_failed_resume():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    app.coordinator._handle_online_event(
        Event("annotation_delta", {"action": "add", "kind": "highlight", "square": "c3"}))
    assert app.coordinator._resync_buffer
    app.coordinator._drop_client()
    assert app.coordinator._resync_buffer == []
    assert app.coordinator._resyncing is False

    app.coordinator._resyncing = True
    app.coordinator._handle_online_event(
        Event("annotations_state", {"sharing": True, "highlights": [], "arrows": []}))
    app.coordinator._handle_game_resumed({"move_history": []})  # variant is LOCAL
    assert app.coordinator._resync_buffer == []
    subscriber.on_annotations_state.assert_not_called()
    subscriber.on_annotation_delta.assert_not_called()


def test_quick_chat_forwarded_even_while_resyncing():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    payload = {"preset": 2, "sender": "black"}
    app.coordinator._handle_online_event(Event("quick_chat_received", payload))
    subscriber.on_quick_chat.assert_called_once_with(payload)


def _stub_resume_response():
    return ResumeResponse(
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        move_history=[],
        clock={"white_remaining": 300.0, "black_remaining": 300.0, "running_for": "white"},
        your_color="white", white_name="alice", black_name="bob",
        time_minutes=5, increment_seconds=0,
        white_annotations={"sharing": True, "highlights": ["c6"],
                           "arrows": [{"from": "e2", "to": "e4"}]},
        skillcheck_locks=[{"from": "e4", "to": "d5"}],
    )


def test_fetch_resume_dumps_by_alias_so_arrow_and_lock_decoders_work(monkeypatch):
    """The /resume restore path: the client's dump keeps the wire aliases, and
    GameScreen._decode_arrow_wires (which reads arrow["from"]/["to"]) actually
    yields the squares. The by_alias=False regression dumped from_sq/to_sq and
    every shared arrow vanished silently on resume/reclaim."""
    transport = MagicMock()
    transport.resume_blocking.return_value = _stub_resume_response()
    monkeypatch.setattr("chessshootout.online.client.ServerTransport",
                        lambda addr: transport)
    resumed = fetch_resume("localhost:1", "room-id", "token")
    arrows = resumed["white_annotations"]["arrows"]
    assert arrows == [{"from": "e2", "to": "e4"}]
    assert GameScreen._decode_arrow_wires(arrows) == [(Square(6, 4), Square(4, 4))]
    assert resumed["skillcheck_locks"] == [{"from": "e4", "to": "d5"}]


@pytest.mark.parametrize("msg_type", ["annotations_state", "quick_chat"])
def test_rate_limited_toasts_and_never_opens_the_confirm_modal(msg_type, monkeypatch):
    app = make_app(1000, 800)
    toasts = []
    monkeypatch.setattr(app.toast, "show", lambda label, **kw: toasts.append(label))
    confirm = MagicMock()
    monkeypatch.setattr(app.confirm_modal, "show", confirm)

    app.coordinator._handle_online_event(
        Event("error", {"reason": Reason.RATE_LIMITED, "msg_type": msg_type}))

    assert toasts == ["Slow down a bit"]
    confirm.assert_not_called()
