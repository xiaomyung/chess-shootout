"""Client-side wiring for shared annotations + quick chat: OnlineClient send
facades enqueue the transport method by name, OnlineCoordinator passthroughs
guard on a live client, and inbound routing forwards to the subscriber. The
board-state guards diverge on purpose: annotations_state/annotation_delta are
dropped mid-resync (resume repopulates marks, so a delta against a stale board
is worse than nothing) while quick_chat_received always forwards (a chat is
board-independent and dropping it silently loses the message). rate_limited
feedback for the new msg_types stays on the transient toast path — it must
never escalate to the confirm/retry modal."""

from unittest.mock import MagicMock

import pytest

from tests.conftest import pygame_display
from chessshootout.online.client import Event, OnlineClient
from chessshootout.server.protocol import Reason
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


def test_annotations_state_dropped_while_resyncing():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    app.coordinator._handle_online_event(
        Event("annotations_state", {"sharing": True, "highlights": [], "arrows": []}))
    subscriber.on_annotations_state.assert_not_called()


def test_annotation_delta_dropped_while_resyncing():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    app.coordinator._handle_online_event(
        Event("annotation_delta", {"action": "add", "kind": "highlight", "square": "c3"}))
    subscriber.on_annotation_delta.assert_not_called()


def test_quick_chat_forwarded_even_while_resyncing():
    app, subscriber = _subscribed_coordinator()
    app.coordinator._resyncing = True
    payload = {"preset": 2, "sender": "black"}
    app.coordinator._handle_online_event(Event("quick_chat_received", payload))
    subscriber.on_quick_chat.assert_called_once_with(payload)


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
