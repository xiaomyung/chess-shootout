"""Shared annotations + quick chat wired end-to-end through GameScreen.

The SHARE chip broadcasts the mover's live highlights/arrows to the opponent:
toggling on ships a full snapshot, every right-drag ships an incremental delta,
and a left-click that wipes the board's own marks ships an empty-but-still-sharing
state so the mirror clears too. All of that is gated on an ONLINE, live game — a
local game never touches the wire. Inbound, the opponent's set lands in the board's
`opp_*` collections (bad coords dropped, deltas idempotent), a resume restores both
sides' marks + both share flags, and a quick-chat preset pops a speech bubble on the
sender's side. The share flags reset every fresh game (product decision), and the
player strips surface the sharing pill in the owner's colour."""

from unittest.mock import MagicMock

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import Square
from chessshootout.frontend.screens.game import CHAT_PRESETS
from chessshootout.frontend.visual.colors import Colors
from chessshootout.server.protocol import CHAT_PRESET_COUNT
from tests.helpers import make_app as _shared_make_app, start_single_screen


_pygame_init = pygame_display(1000, 800)

HL = Square(2, 2)          # c6
HL2 = Square(5, 5)         # f3
ARROW_FROM = Square(6, 4)  # e2
ARROW_TO = Square(4, 4)    # e4
EMPTY = Square(4, 4)       # unoccupied in the opening


def _online_game(your_color="white"):
    app = _shared_make_app(1000, 800)
    app.switch_to("game", your_color=your_color, white_name="alice",
                  black_name="bob", time_minutes=5, increment_seconds=0,
                  white_country="", black_country="",
                  white_score=0.0, black_score=0.0)
    app.coordinator.send_annotations_state = MagicMock()
    app.coordinator.send_annotation_delta = MagicMock()
    app.coordinator.send_quick_chat = MagicMock()
    return app.game


def _right_gesture(game, from_sq, to_sq):
    game.board.begin_right_press(game.board.cell_rect(from_sq).center)
    game.handle_right_release(game.board.cell_rect(to_sq).center)


# ---- share toggle: full-state broadcast ----------------------------------


def test_toggle_on_broadcasts_the_existing_marks():
    game = _online_game()
    game.board.highlighted_squares = {HL, HL2}
    game.board.arrows = [(ARROW_FROM, ARROW_TO)]
    game._on_share_toggle()
    assert game._share_marks is True
    game.app.coordinator.send_annotations_state.assert_called_once_with(
        True, ["c6", "f3"], [("e2", "e4")])


def test_toggle_off_sends_empty_sharing_off_state():
    game = _online_game()
    game._share_marks = True
    game._on_share_toggle()
    assert game._share_marks is False
    game.app.coordinator.send_annotations_state.assert_called_once_with(False, [], [])


def test_local_variant_toggle_is_inert():
    app = start_single_screen(_shared_make_app(1000, 800))
    app.coordinator.send_annotations_state = MagicMock()
    app.game._on_share_toggle()
    assert app.game._share_marks is False
    app.coordinator.send_annotations_state.assert_not_called()


def test_toggle_is_inert_once_the_game_is_over(monkeypatch):
    game = _online_game()
    monkeypatch.setattr(game, "current_result", lambda: "draw_agreement")
    game._on_share_toggle()
    assert game._share_marks is False
    game.app.coordinator.send_annotations_state.assert_not_called()


def test_signals_provider_reflects_share_state():
    game = _online_game()
    assert game._signals_provider()["share_on"] is False
    game._share_marks = True
    assert game._signals_provider()["share_on"] is True


# ---- right-drag deltas -----------------------------------------------------


def test_highlight_add_delta_sent_when_sharing():
    game = _online_game()
    game._share_marks = True
    _right_gesture(game, HL, HL)
    game.app.coordinator.send_annotation_delta.assert_called_once_with(
        "add", "highlight", square="c6")


def test_highlight_remove_delta_sent_when_sharing():
    game = _online_game()
    game._share_marks = True
    game.board.highlighted_squares = {HL}
    _right_gesture(game, HL, HL)
    game.app.coordinator.send_annotation_delta.assert_called_once_with(
        "remove", "highlight", square="c6")


def test_arrow_add_delta_sent_when_sharing():
    game = _online_game()
    game._share_marks = True
    _right_gesture(game, ARROW_FROM, ARROW_TO)
    game.app.coordinator.send_annotation_delta.assert_called_once_with(
        "add", "arrow", from_sq="e2", to_sq="e4")


def test_arrow_remove_delta_sent_when_sharing():
    game = _online_game()
    game._share_marks = True
    game.board.arrows = [(ARROW_FROM, ARROW_TO)]
    _right_gesture(game, ARROW_FROM, ARROW_TO)
    game.app.coordinator.send_annotation_delta.assert_called_once_with(
        "remove", "arrow", from_sq="e2", to_sq="e4")


def test_no_delta_sent_when_not_sharing():
    game = _online_game()
    assert game._share_marks is False
    _right_gesture(game, HL, HL)
    game.app.coordinator.send_annotation_delta.assert_not_called()
    assert HL in game.board.highlighted_squares  # still drawn locally


def test_no_delta_sent_for_a_local_game():
    app = start_single_screen(_shared_make_app(1000, 800))
    app.coordinator.send_annotation_delta = MagicMock()
    app.game._share_marks = True  # can't happen live, but the gate must still hold
    _right_gesture(app.game, HL, HL)
    app.coordinator.send_annotation_delta.assert_not_called()


# ---- bulk-clear on a left-click -------------------------------------------


def test_bulk_clear_sends_empty_state_when_sharing():
    game = _online_game()
    game._share_marks = True
    game.board.highlighted_squares = {HL}
    game.app.coordinator.send_annotations_state.reset_mock()
    game.handle_click(game.board.cell_rect(EMPTY).center)
    assert not game.board.highlighted_squares
    game.app.coordinator.send_annotations_state.assert_called_once_with(True, [], [])


def test_bulk_clear_silent_when_not_sharing():
    game = _online_game()
    game.board.highlighted_squares = {HL}
    game.handle_click(game.board.cell_rect(EMPTY).center)
    assert not game.board.highlighted_squares
    game.app.coordinator.send_annotations_state.assert_not_called()


# ---- inbound opponent state -----------------------------------------------


def test_on_annotations_state_populates_opp_collections():
    game = _online_game()
    game.on_annotations_state({
        "sharing": True,
        "highlights": ["e4", "c6", "zz", "e44"],
        "arrows": [{"from": "e2", "to": "e4"}, {"from": "bad", "to": "e4"}],
    })
    assert game._opp_sharing is True
    ann = game.board.annotations
    assert ann.opp_highlighted_squares == {Square(4, 4), Square(2, 2)}
    assert ann.opp_arrows == [(Square(6, 4), Square(4, 4))]


def test_on_annotations_state_clears_when_sharing_off():
    game = _online_game()
    game.board.annotations.set_opp({Square(2, 2)}, [(ARROW_FROM, ARROW_TO)])
    game.on_annotations_state({"sharing": False, "highlights": [], "arrows": []})
    assert game._opp_sharing is False
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []


def test_on_annotation_delta_is_idempotent():
    game = _online_game()
    ann = game.board.annotations
    game.on_annotation_delta({"action": "add", "kind": "highlight", "square": "c3"})
    game.on_annotation_delta({"action": "add", "kind": "highlight", "square": "c3"})
    assert ann.opp_highlighted_squares == {Square(5, 2)}
    game.on_annotation_delta({"action": "remove", "kind": "highlight", "square": "h1"})
    assert ann.opp_highlighted_squares == {Square(5, 2)}

    game.on_annotation_delta({"action": "add", "kind": "arrow", "from": "e2", "to": "e4"})
    game.on_annotation_delta({"action": "add", "kind": "arrow", "from": "e2", "to": "e4"})
    assert ann.opp_arrows == [(Square(6, 4), Square(4, 4))]
    game.on_annotation_delta({"action": "remove", "kind": "arrow", "from": "e2", "to": "e4"})
    assert ann.opp_arrows == []
    game.on_annotation_delta({"action": "remove", "kind": "arrow", "from": "e2", "to": "e4"})
    assert ann.opp_arrows == []


def test_on_annotation_delta_drops_malformed_payloads():
    game = _online_game()
    game.on_annotation_delta({"action": "add", "kind": "highlight", "square": "zz"})
    game.on_annotation_delta({"action": "nope", "kind": "highlight", "square": "c3"})
    game.on_annotation_delta({"action": "add", "kind": "arrow", "from": "e2"})
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []


# ---- resume restores everything -------------------------------------------


def test_on_resume_restores_both_sides_and_flags():
    game = _online_game(your_color="white")
    game.on_resume({
        "move_history": [],
        "white_annotations": {
            "sharing": True, "highlights": ["c6"],
            "arrows": [{"from": "e2", "to": "e4"}],
        },
        "black_annotations": {
            "sharing": True, "highlights": ["d5"], "arrows": [],
        },
    })
    assert game._share_marks is True
    assert game.board.highlighted_squares == {Square(2, 2)}
    assert game.board.arrows == [(Square(6, 4), Square(4, 4))]
    assert game._opp_sharing is True
    assert game.board.annotations.opp_highlighted_squares == {Square(3, 3)}


def test_on_resume_maps_mine_and_opp_by_chosen_side():
    game = _online_game(your_color="black")
    game.on_resume({
        "move_history": [],
        "white_annotations": {"sharing": True, "highlights": ["a1"], "arrows": []},
        "black_annotations": {"sharing": False, "highlights": ["h8"], "arrows": []},
    })
    assert game._share_marks is False                       # black is "mine"
    assert game.board.highlighted_squares == {Square(0, 7)}  # h8
    assert game._opp_sharing is True
    assert game.board.annotations.opp_highlighted_squares == {Square(7, 0)}  # a1


# ---- reset + strips + chat -------------------------------------------------


def test_reset_to_new_game_resets_share_flags():
    game = _online_game()
    game._share_marks = True
    game._opp_sharing = True
    game.board.annotations.set_opp({Square(2, 2)}, [(ARROW_FROM, ARROW_TO)])
    game._reset_to_new_game()
    assert game._share_marks is False
    assert game._opp_sharing is False
    assert game.board.annotations.opp_highlighted_squares == set()
    assert game.board.annotations.opp_arrows == []


def test_strip_state_sharing_kwargs_per_side():
    game = _online_game(your_color="white")
    game._share_marks = True
    game._opp_sharing = False
    turn = game.match.current_turn()
    mine = game._strip_state(PieceColor.WHITE, turn, over=False)
    opp = game._strip_state(PieceColor.BLACK, turn, over=False)
    assert mine["sharing"] is True and mine["sharing_color"] == Colors.amber
    assert opp["sharing"] is False and opp["sharing_color"] == Colors.avatar_blue


def test_strip_state_sharing_off_for_local_variant():
    app = start_single_screen(_shared_make_app(1000, 800))
    game = app.game
    game._share_marks = True
    state = game._strip_state(PieceColor.WHITE, game.match.current_turn(), over=False)
    assert state["sharing"] is False
    assert state["sharing_color"] is None


def test_on_quick_chat_pops_bubble_and_plays_sound():
    game = _online_game(your_color="white")
    game.show_speech_bubble = MagicMock()
    game.app.sound_manager.play_chat_receive.reset_mock()
    game.on_quick_chat({"preset": 1})
    game.show_speech_bubble.assert_called_once_with("black", CHAT_PRESETS[1])
    game.app.sound_manager.play_chat_receive.assert_called_once()


def test_on_quick_chat_honours_explicit_sender():
    game = _online_game(your_color="white")
    game.show_speech_bubble = MagicMock()
    game.on_quick_chat({"preset": 0, "sender": "white"})
    game.show_speech_bubble.assert_called_once_with("white", CHAT_PRESETS[0])


@pytest.mark.parametrize("preset", [-1, CHAT_PRESET_COUNT, 99])
def test_on_quick_chat_ignores_out_of_range_presets(preset):
    game = _online_game()
    game.show_speech_bubble = MagicMock()
    game.app.sound_manager.play_chat_receive.reset_mock()
    game.on_quick_chat({"preset": preset})
    game.show_speech_bubble.assert_not_called()
    game.app.sound_manager.play_chat_receive.assert_not_called()


def test_chat_presets_match_the_server_preset_count():
    assert len(CHAT_PRESETS) == CHAT_PRESET_COUNT


# ---- quick chat send (own rail buttons) ------------------------------------


def test_quick_chat_send_relays_echoes_own_bubble_and_arms_cooldown(monkeypatch):
    game = _online_game(your_color="white")
    game.show_speech_bubble = MagicMock()
    ticks = {"t": 5_000}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks["t"])
    assert game._chat_buttons_inert() is False
    game._on_quick_chat_send(2)
    game.app.coordinator.send_quick_chat.assert_called_once_with(2)
    game.show_speech_bubble.assert_called_once_with("white", CHAT_PRESETS[2])
    assert game._chat_buttons_inert() is True


def test_quick_chat_send_echo_is_silent():
    """The local echo pops a bubble but plays no sound — only the inbound
    receive path chimes."""
    game = _online_game(your_color="white")
    game.app.sound_manager.play_chat_receive = MagicMock()
    game._on_quick_chat_send(0)
    game.app.sound_manager.play_chat_receive.assert_not_called()


def test_quick_chat_second_send_within_cooldown_no_ops(monkeypatch):
    game = _online_game(your_color="white")
    ticks = {"t": 5_000}
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks["t"])
    game._on_quick_chat_send(0)
    game.app.coordinator.send_quick_chat.reset_mock()
    ticks["t"] = 7_000
    game._on_quick_chat_send(1)
    game.app.coordinator.send_quick_chat.assert_not_called()
    ticks["t"] = 8_100
    game._on_quick_chat_send(1)
    game.app.coordinator.send_quick_chat.assert_called_once_with(1)


def test_quick_chat_inert_and_no_op_once_game_is_over(monkeypatch):
    game = _online_game(your_color="white")
    monkeypatch.setattr(game, "current_result", lambda: "draw_agreement")
    assert game._chat_buttons_inert() is True
    game._on_quick_chat_send(0)
    game.app.coordinator.send_quick_chat.assert_not_called()


def test_quick_chat_send_is_inert_for_a_local_game():
    app = start_single_screen(_shared_make_app(1000, 800))
    app.coordinator.send_quick_chat = MagicMock()
    app.game._on_quick_chat_send(0)
    app.coordinator.send_quick_chat.assert_not_called()


def test_chat_section_visible_only_online():
    game = _online_game()
    assert game.right_menu.chat_visible_provider() is True
    local = start_single_screen(_shared_make_app(1000, 800)).game
    assert local.right_menu.chat_visible_provider() is False


def test_reset_to_new_game_clears_chat_cooldown(monkeypatch):
    game = _online_game(your_color="white")
    monkeypatch.setattr(pg.time, "get_ticks", lambda: 5_000)
    game._on_quick_chat_send(0)
    assert game._chat_buttons_inert() is True
    game._reset_to_new_game()
    assert game._chat_cooldown_until_ms == 0
    assert game._chat_buttons_inert() is False
