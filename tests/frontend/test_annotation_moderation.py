"""Client-side annotation moderation UX (v2.11.0).

The client trusts the server's verdicts entirely -- there is NO client detector.
When the server hard-blocks a drawer's marks it echoes `annotations_blocked`
(action="blocked") carrying the matched arrows/highlights; GameScreen recolors
exactly those OWN marks red via `Annotations.flag_own` and shows a deliberately
vague toast (FP victims must not be insulted). A soft flag (action="suspect")
only warns -- the marks stay amber and keep relaying. Three trips mute sharing:
the blocked message's `share_muted` disables the SHARE chip and adds a muted
toast. The relay-opt-out `SHARE_MUTED` / `OPP_HIDES_MARKS` reasons arrive as
plain `ErrorMessage` transients and route through the coordinator's existing
transient-toast map. Inbound `annotations_blocked` buffers during a resync and
replays in order, exactly like `annotations_state`. The flagged set is OWN-only,
cleared on the same wipes as own marks (move/takeback/new-game) and on delete,
and the resume path clears it explicitly because it bypasses `Annotations.clear`.
The "Hide opponent's marks" option persists to .env, threads into the matchmake
request, and -- toggled mid-game -- sends `set_marks_visibility` (clearing the
already-received opponent set and the opp-sharing indicator locally when
turning the shield on). Because opponent annotation events can still be
in-flight (queued client-side, or relayed by the server before it processes
the visibility message, or sitting in the resync buffer), GameScreen drops
inbound opponent annotation traffic -- state, delta, and the resume opponent
set -- whenever the local hide preference is on; otherwise a single racing
delta would repopulate the just-cleared shield until the next move wipe.
Once muted, the client also STOPS sending -- `_share_active` gates every
outbound share site -- so the drawer doesn't earn a `SHARE_MUTED` error toast
for every mark drawn after the mute."""

from unittest.mock import ANY, MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.backend import Backend
from chessshootout.backend.utils import Square
from chessshootout.frontend.board import Board
from chessshootout.frontend.visual.colors import Colors
from chessshootout.infra import env
from chessshootout.server.protocol import Reason
from tests.helpers import make_app as _shared_make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)

HL = Square(2, 2)          # c6
HL2 = Square(5, 5)         # f3
ARROW_FROM = Square(6, 4)  # e2
ARROW_TO = Square(4, 4)    # e4
ARROW2 = (Square(6, 3), Square(4, 3))  # d2 -> d4


@pytest.fixture
def board():
    backend = Backend()
    backend.new_game()
    bd = Board(pg.display.get_surface(), backend)
    bd.load_assets()
    bd.set_rect(pg.Rect(0, 0, 400, 400))
    return bd


def _online_game(your_color="white"):
    app = _shared_make_app(1000, 800)
    app.switch_to("game", your_color=your_color, white_name="alice",
                  black_name="bob", time_minutes=5, increment_seconds=0,
                  white_country="", black_country="",
                  white_score=0.0, black_score=0.0)
    app.coordinator.send_annotations_state = MagicMock()
    app.coordinator.send_annotation_delta = MagicMock()
    return app.game


# ---- flagged-set rendering (red recolor) ----------------------------------


def test_flagged_own_arrow_renders_red_unflagged_stays_amber(board):
    board.arrows = [(ARROW_FROM, ARROW_TO), ARROW2]
    board.annotations.flag_own([(ARROW_FROM, ARROW_TO)], [])
    seen = {}
    board.annotations._render_arrow = (
        lambda layer, scale, fr, to, color: seen.__setitem__((fr, to), color))
    board.annotations._arrow_cache = None
    board.annotations._draw_arrows()
    assert seen[(ARROW_FROM, ARROW_TO)] == Colors.annotation_arrow_flagged
    assert seen[ARROW2] == Colors.annotation_arrow


def test_flagged_own_highlight_renders_red_unflagged_stays_amber(board):
    board.highlighted_squares = {HL, HL2}
    board.annotations.flag_own([], [HL])
    colors = []
    board.annotations.board._cell_overlay = (
        lambda c: colors.append(c) or pg.Surface((1, 1), pg.SRCALPHA))
    board.annotations._draw_annotation_highlights()
    assert Colors.annotation_highlight_flagged in colors
    assert Colors.annotation_highlight in colors


def test_flagged_cleared_on_own_wipe(board):
    board.arrows = [(ARROW_FROM, ARROW_TO)]
    board.annotations.flag_own([(ARROW_FROM, ARROW_TO)], [HL])
    board.annotations.clear()
    assert board.annotations.flagged == set()


def test_flagged_discarded_when_mark_deleted(board):
    board.annotations.toggle_arrow(ARROW_FROM, ARROW_TO)
    board.annotations.flag_own([(ARROW_FROM, ARROW_TO)], [])
    board.annotations.toggle_arrow(ARROW_FROM, ARROW_TO)  # removes it
    assert (ARROW_FROM, ARROW_TO) not in board.annotations.flagged
    board.annotations.toggle_highlight(HL)
    board.annotations.flag_own([], [HL])
    board.annotations.toggle_highlight(HL)  # removes it
    assert HL not in board.annotations.flagged


def test_flag_own_tolerates_absent_marks(board):
    # A resync-buffered blocked message can replay after resume already stripped
    # the referenced marks -- flag_own must not raise and rendering must be safe.
    assert board.arrows == []
    assert board.highlighted_squares == set()
    board.annotations.flag_own([(ARROW_FROM, ARROW_TO)], [HL])
    assert (ARROW_FROM, ARROW_TO) in board.annotations.flagged
    assert HL in board.annotations.flagged
    board.annotations._arrow_cache = None
    board.annotations._draw_arrows()
    board.annotations._draw_annotation_highlights()
    assert board.annotations.flagged == {(ARROW_FROM, ARROW_TO), HL}


# ---- on_annotations_blocked (blocked / suspect / muted) -------------------


def test_blocked_flags_matched_own_marks_and_toasts():
    game = _online_game()
    game.app.toast.show = MagicMock()
    game.board.arrows = [(ARROW_FROM, ARROW_TO)]
    game.board.highlighted_squares = {HL}
    game.on_annotations_blocked({
        "action": "blocked",
        "arrows": [{"from": "e2", "to": "e4"}],
        "highlights": ["c6"],
        "share_muted": False,
    })
    assert (ARROW_FROM, ARROW_TO) in game.board.annotations.flagged
    assert HL in game.board.annotations.flagged
    game.app.toast.show.assert_any_call("Some marks can't be shared", key="marks_blocked")
    assert game._share_muted is False


def test_suspect_warns_without_flagging():
    game = _online_game()
    game.app.toast.show = MagicMock()
    game.board.arrows = [(ARROW_FROM, ARROW_TO)]
    game.on_annotations_blocked({
        "action": "suspect", "arrows": [{"from": "e2", "to": "e4"}], "highlights": [],
    })
    assert game.board.annotations.flagged == set()
    game.app.toast.show.assert_called_once_with("Those marks look suspicious",
                                                key="marks_suspect")


def test_muted_disables_share_chip_and_toasts():
    game = _online_game()
    game.app.toast.show = MagicMock()
    assert game._signals_provider()["share_enabled"] is True
    game.on_annotations_blocked({
        "action": "blocked", "arrows": [], "highlights": [], "share_muted": True,
    })
    assert game._share_muted is True
    assert game._signals_provider()["share_enabled"] is False
    game.app.toast.show.assert_any_call("Mark sharing is muted for this game",
                                        key="marks_muted")


def test_reset_to_new_game_clears_mute():
    game = _online_game()
    game._share_muted = True
    game._reset_to_new_game()
    assert game._share_muted is False


def test_clicking_muted_share_reshows_the_muted_toast():
    game = _online_game()
    game._share_muted = True
    game.app.toast.show = MagicMock()
    game._on_share_blocked()
    game.app.toast.show.assert_called_once_with(
        "Mark sharing is muted for this game", key="marks_muted")


def test_share_blocked_is_silent_when_not_muted():
    game = _online_game()
    game._share_muted = False
    game.app.toast.show = MagicMock()
    game._on_share_blocked()
    game.app.toast.show.assert_not_called()


def test_muted_share_stops_client_sends():
    game = _online_game()
    game._share_marks = True
    game._share_muted = True
    game.app.coordinator.send_annotations_state = MagicMock()
    assert game._share_active() is False
    game._maybe_sync_marks_cleared(True)
    game.app.coordinator.send_annotations_state.assert_not_called()


# ---- resume path clears the flagged set + reflects mute -------------------


def test_restore_resumed_annotations_clears_flagged():
    game = _online_game()
    game.board.annotations.flagged = {(ARROW_FROM, ARROW_TO), HL}
    game._restore_resumed_annotations({
        "white_annotations": {"highlights": ["c6"], "arrows": []},
        "black_annotations": {},
    })
    assert game.board.annotations.flagged == set()


def test_restore_resumed_annotations_reflects_mute():
    game = _online_game()
    game._restore_resumed_annotations({
        "share_muted": True, "white_annotations": {}, "black_annotations": {},
    })
    assert game._share_muted is True


def test_restore_resumed_annotations_shields_opp_when_hidden():
    game = _online_game()
    env.set_hide_opp_marks(True)
    game._restore_resumed_annotations({
        "white_annotations": {"highlights": ["c6"], "arrows": [], "sharing": True},
        "black_annotations": {"highlights": ["d5"],
                              "arrows": [{"from": "e7", "to": "e5"}],
                              "sharing": True},
    })
    assert game.board.highlighted_squares == {HL}
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []
    assert game._opp_sharing is False


# ---- transient relay-opt-out toasts (via ErrorMessage) --------------------


def test_share_muted_reason_toasts_transiently():
    game = _online_game()
    coord = game.app.coordinator
    game.app.toast.show = MagicMock()
    coord._handle_online_error({"reason": Reason.SHARE_MUTED})
    game.app.toast.show.assert_called_once_with("Mark sharing is muted for this game")


def test_opp_hides_marks_reason_toasts_transiently():
    game = _online_game()
    coord = game.app.coordinator
    game.app.toast.show = MagicMock()
    coord._handle_online_error({"reason": Reason.OPP_HIDES_MARKS})
    game.app.toast.show.assert_called_once_with("Opponent hides shared marks")


# ---- coordinator buffers annotations_blocked during resync ----------------


def test_annotations_blocked_buffered_during_resync_then_replayed():
    game = _online_game()
    coord = game.app.coordinator
    game.board.arrows = [(ARROW_FROM, ARROW_TO)]
    coord._resyncing = True
    coord._handle_annotations_blocked({
        "action": "blocked", "arrows": [{"from": "e2", "to": "e4"}],
        "highlights": [], "share_muted": False,
    })
    assert (ARROW_FROM, ARROW_TO) not in game.board.annotations.flagged
    assert coord._resync_buffer == [("on_annotations_blocked", ANY)]
    coord._resyncing = False
    coord._replay_resync_buffer()
    assert (ARROW_FROM, ARROW_TO) in game.board.annotations.flagged


# ---- Hide-opponent-marks option -------------------------------------------


def test_hide_opp_marks_option_persists_offline_without_send():
    app = _shared_make_app(1000, 800)
    app.coordinator.set_marks_visibility = MagicMock()
    app.settings.apply_hide_opp_marks(True)
    assert env.get_hide_opp_marks() is True
    app.coordinator.set_marks_visibility.assert_not_called()


def test_hide_opp_marks_toggle_on_sends_and_clears_opp_mid_game():
    game = _online_game()
    app = game.app
    app.coordinator.set_marks_visibility = MagicMock()
    app.coordinator.is_connected = lambda: True
    game.board.annotations.set_opp({HL}, [(ARROW_FROM, ARROW_TO)])
    game._opp_sharing = True
    app.settings.apply_hide_opp_marks(True)
    assert env.get_hide_opp_marks() is True
    app.coordinator.set_marks_visibility.assert_called_once_with(True)
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []
    assert game._opp_sharing is False


def test_opp_annotation_events_dropped_while_hide_pref_on():
    game = _online_game()
    env.set_hide_opp_marks(True)
    game.on_annotations_state({
        "sharing": True, "highlights": ["c6"],
        "arrows": [{"from": "e7", "to": "e5"}],
    })
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []
    assert game._opp_sharing is False
    game.on_annotation_delta({"action": "add", "kind": "highlight", "square": "d5"})
    game.on_annotation_delta({"action": "add", "kind": "arrow",
                              "from": "e7", "to": "e5"})
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []


def test_hide_opp_marks_toggle_off_sends_without_clearing_opp():
    game = _online_game()
    app = game.app
    app.coordinator.set_marks_visibility = MagicMock()
    app.coordinator.is_connected = lambda: True
    game.board.annotations.set_opp({HL}, [])
    app.settings.apply_hide_opp_marks(False)
    app.coordinator.set_marks_visibility.assert_called_once_with(False)
    assert game.board.annotations.opp_highlighted_squares == {HL}


def test_matchmake_request_carries_hide_preference():
    app = _shared_make_app(1000, 800)
    env.set_hide_opp_marks(True)
    captured = {}
    app.coordinator.client = None

    class _FakeClient:
        state = "connecting"

        def connect(self, addr, request):
            captured.update(request)

    def _fake_online_client():
        return _FakeClient()

    import chessshootout.frontend.online_coordinator as oc
    original = oc.OnlineClient
    oc.OnlineClient = _fake_online_client
    try:
        app.coordinator._online_config = {
            "nickname": "alice", "time_minutes": 5, "increment_seconds": 0,
            "side": "random",
        }
        app.coordinator._on_server_addr_connect("localhost:8000")
    finally:
        oc.OnlineClient = original
    assert captured["hide_opp_marks"] is True


# ---- in-game HIDE signal chip (mirrors the Options toggle) -----------------


def test_hide_chip_state_reflects_env():
    game = _online_game()
    assert game._signals_provider()["hide_on"] is False
    env.set_hide_opp_marks(True)
    assert game._signals_provider()["hide_on"] is True


def test_hide_chip_enabled_online_disabled_offline():
    game = _online_game()
    assert game._signals_provider()["hide_enabled"] is True
    local = _shared_make_app(1000, 800)
    start_single_screen(local)
    assert local.game._signals_provider()["hide_enabled"] is False


def test_hide_chip_toggle_on_sends_and_shields_mid_game():
    game = _online_game()
    app = game.app
    app.coordinator.set_marks_visibility = MagicMock()
    app.coordinator.is_connected = lambda: True
    game.board.annotations.set_opp({HL}, [(ARROW_FROM, ARROW_TO)])
    game._opp_sharing = True
    game._on_hide_marks_toggle()
    assert env.get_hide_opp_marks() is True
    app.coordinator.set_marks_visibility.assert_called_once_with(True)
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []
    assert game._opp_sharing is False


def test_hide_chip_toggle_off_sends_without_shielding():
    game = _online_game()
    app = game.app
    env.set_hide_opp_marks(True)
    app.coordinator.set_marks_visibility = MagicMock()
    app.coordinator.is_connected = lambda: True
    game.board.annotations.set_opp({HL}, [])
    game._on_hide_marks_toggle()
    assert env.get_hide_opp_marks() is False
    app.coordinator.set_marks_visibility.assert_called_once_with(False)
    assert game.board.annotations.opp_highlighted_squares == {HL}


def test_hide_chip_and_options_toggle_stay_in_sync():
    """The chip and the Options row both read and write the same env key, so a
    flip from either surface is immediately visible through the other."""
    game = _online_game()
    app = game.app
    app.coordinator.set_marks_visibility = MagicMock()
    app.coordinator.is_connected = lambda: True
    game._on_hide_marks_toggle()
    assert env.get_hide_opp_marks() is True
    assert game._signals_provider()["hide_on"] is True
    app.settings.apply_hide_opp_marks(False)
    assert env.get_hide_opp_marks() is False
    assert game._signals_provider()["hide_on"] is False


# ---- resume re-syncs a stale hide preference -------------------------------


def test_resume_pushes_hide_preference_when_server_slot_is_stale():
    """Toggling the option while disconnected never reaches the server (the
    send is gated on is_connected), so the server slot can drift; /resume
    echoes the slot's view, and a mismatch must re-push the client's desired
    value or the stale slot keeps suppressing (or leaking) opponent marks for
    the rest of the game."""
    game = _online_game()
    coord = game.app.coordinator
    coord.set_marks_visibility = MagicMock()
    coord._subscriber = MagicMock()
    env.set_hide_opp_marks(True)
    coord._handle_game_resumed({"hide_opp_marks": False})
    coord.set_marks_visibility.assert_called_once_with(True)
    coord._subscriber.on_resume.assert_called_once()


def test_resume_matching_hide_preference_sends_nothing():
    game = _online_game()
    coord = game.app.coordinator
    coord.set_marks_visibility = MagicMock()
    coord._subscriber = MagicMock()
    env.set_hide_opp_marks(False)
    coord._handle_game_resumed({"hide_opp_marks": False})
    coord.set_marks_visibility.assert_not_called()
