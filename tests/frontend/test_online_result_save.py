"""The unified, server-authoritative online PGN save (v2.4.1 Bug 1).

An online game must save its PGN once it reaches a server-confirmed result, and
must NOT depend on the result arriving through the fragile verdict/teardown path.
These tests drive the real handlers for a capture-checkmate (Qxg7#, which fires a
skill-check) and assert the FULL game is saved with the right result tag — never a
truncated file, never a missing save. Covers: the normal path, a missed `result`
message (recovered by the local-promotion watchdog), a verdict that raises
(truth-first + resync recovery), server-fault partials, tag-aware idempotency, and
the local-mode parity + 0-move guard.
"""

from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from chessshootout.backend.utils import coord_from_square
from chessshootout.domain.match import SINGLE_SCREEN
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.game.result_flow import RESULT_CONFIRM_TIMEOUT_MS
from tests.helpers import BLACK, B, K, P, Q, WHITE, make_backend, piece, sq


_pygame_init = pygame_display(1000, 800)


class FakeOnlineClient:
    def __init__(self, room_id="room-1"):
        self.room_id = room_id
        self.state = "connected"
        self.opp_state = "connected"
        self.sent_moves = []
        self.shots = 0
        self.state_syncs = 0

    def disconnect(self):
        self.state = "disconnected"

    def send_ping(self, ply):
        pass

    def is_connected(self):
        return self.state == "connected"

    def is_server_silent(self):
        return False

    def heartbeat_interval(self):
        return 2.0

    def send_move(self, from_sq, to_sq, promotion=None):
        self.sent_moves.append((from_sq, to_sq, promotion))

    def send_skill_check_shot(self, client_elapsed_ms=0.0):
        self.shots += 1

    def request_state_sync(self):
        self.state_syncs += 1

    def get_ping_ms(self):
        return None


def _online_app(tmp_path, monkeypatch, your_color="white"):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.coordinator.client = FakeOnlineClient()
    app.coordinator._start_online_game({
        "white_name": "alice", "black_name": "bob", "your_color": your_color,
        "time_minutes": 5, "increment_seconds": 0,
        "white_country": "", "black_country": "",
        "white_score": 0.0, "black_score": 0.0,
    })
    return app


def _capture_mate_board(app):
    """White Qg1, Bb2 (defends g7), Ka1; Black Kh8, pawn g7. Qxg7# is a capture-mate."""
    app.game.match.backend = make_backend({
        sq(0, 7): piece(K, BLACK), sq(1, 6): piece(P, BLACK),
        sq(7, 6): piece(Q, WHITE), sq(6, 1): piece(B, WHITE),
        sq(7, 0): piece(K, WHITE),
    }, turn=WHITE)
    return sq(7, 6), sq(1, 6)


def _required_payload(frm, to, kind="wheel", value_diff=8):
    return {
        "kind": kind, "seed": "seed-1", "value_diff": value_diff,
        "deadline_ms": 5000.0, "elapsed_ms": 0.0, "miss_count": 0,
        "from": coord_from_square(frm), "to": coord_from_square(to),
        "promotion": None,
    }


def _move_applied(frm, to, ply, *, kind="wheel", won=True, san="Qxg7#"):
    return {
        "from": coord_from_square(frm), "to": coord_from_square(to), "san": san,
        "clock": {"white_remaining": 300.0, "black_remaining": 300.0, "running_for": "black"},
        "ply": ply, "skill_check_kind": kind, "skill_check_won": won,
    }


def _land_capture_mate(app):
    """Drive gate -> required -> move_applied(won) -> verdict hold so Qxg7# lands."""
    frm, to = _capture_mate_board(app)
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    app.coordinator._handle_skill_check_required(_required_payload(frm, to))
    app.coordinator._handle_remote_move_applied(_move_applied(frm, to, 1))
    app.game.skillcheck_overlay.update(pg.time.get_ticks() + 500)  # run the deferred apply
    return frm, to


def _settle(app):
    app.game.board.cancel_animations()
    app.game.board.effects.clear()


def _saved_text(app):
    assert app.game.result_flow._last_saved_pgn_path is not None, "a PGN was saved"
    with open(app.game.result_flow._last_saved_pgn_path, encoding="utf-8") as f:
        return f.read()


def _pgn_files(tmp_path):
    return list((tmp_path / "games").glob("*.pgn"))


def test_online_capture_mate_saves_full_game_with_result(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    assert app.game.match.game_result() == "white_wins", "the mate landed"
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    _settle(app)
    app.game.result_flow.update_result_pending()
    text = _saved_text(app)
    assert "Qxg7#" in text, "the mating ply is in the saved PGN (not truncated)"
    assert '[Result "1-0"]' in text
    assert len(_pgn_files(tmp_path)) == 1


def test_online_capture_mate_writes_utf8_bytes(tmp_path, monkeypatch):
    """The Windows crash site: the mate PGN embeds a skill-check glyph ({Wheel ✓}).
    _auto_save_pgn must emit UTF-8 bytes on every platform, never the locale codec."""
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    _settle(app)
    app.game.result_flow.update_result_pending()
    text = _saved_text(app)
    assert "{Wheel ✓}" in text
    with open(app.game.result_flow._last_saved_pgn_path, "rb") as f:
        data = f.read()
    assert "✓".encode("utf-8") in data
    assert data.decode("utf-8") == text
    assert data.decode("cp1252", errors="replace") != text


def test_auto_save_survives_surrogate_nickname_without_crashing(tmp_path, monkeypatch):
    """A lone surrogate in a nickname (Windows argv/env surrogateescape) is not
    UTF-8 encodable even with encoding='utf-8'; the save must degrade to None via the
    widened except, not take down the app mid-frame. A clean save still works after."""
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    _settle(app)
    app.game.white_name = "bad\udce9name"
    app.game.result_flow._last_saved_pgn_path = None
    app.game.result_flow._last_saved_result_tag = None
    assert app.game.result_flow.auto_save_pgn() is None
    app.game.white_name = "alice"
    app.game.result_flow._last_saved_pgn_path = None
    app.game.result_flow._last_saved_result_tag = None
    assert app.game.result_flow.auto_save_pgn() is not None


def test_startup_toasts_when_stored_nickname_needs_sanitizing(tmp_path, monkeypatch):
    """A legacy .env carrying a non-ASCII nickname is cleaned on launch (persisted to
    env, read back by the play hero) and the player is told via a toast."""
    from chessshootout.infra import env
    monkeypatch.setattr(env, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("CHESS_NICKNAME", "Bob Щ")
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = Frontend(1000, 800)
    messages = [b["message"] for b in app.toast._bubbles]
    assert "Your nickname contained non ASCII symbols, I cleaned them :3" in messages
    assert env.get_nickname() == "Bob"


def test_online_mate_saved_via_watchdog_when_result_message_is_missed(tmp_path, monkeypatch):
    """The reconnect-storm case: move_applied lands the mate but the `result`
    message never arrives. The local-promotion path must recover + save.

    The save must land on the SAME frame that promotes the result (result
    adoption, not the next painted frame) — no extra _update_result_pending()
    call is needed between promotion and the save landing on disk."""
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    _settle(app)
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    app.game.result_flow.update_result_pending()  # arms await; no save (server-authoritative)
    assert app.game.result_flow._last_saved_pgn_path is None
    assert app.game.manual_result is None
    fake_now[0] += RESULT_CONFIRM_TIMEOUT_MS + 100
    app.game.result_flow.update_result_pending()  # promotes AND saves in the same call
    assert app.game.manual_result == "white_wins"
    text = _saved_text(app)
    assert "Qxg7#" in text and '[Result "1-0"]' in text


def test_watchdog_awards_score_for_on_time_win(tmp_path, monkeypatch):
    """A locally-flagged clock produces a *_on_time result; promotion must still
    credit the winner's series score (the suffix must not be missed)."""
    app = _online_app(tmp_path, monkeypatch)
    app.game.match.try_move(sq(6, 4), sq(4, 4))            # e4, so there's a game to save
    app.game.match.clock.flagged = BLACK                   # black flags -> white wins on time
    assert app.game.match.game_result() == "white_wins_on_time"
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    app.game.result_flow.update_result_pending()
    fake_now[0] += RESULT_CONFIRM_TIMEOUT_MS + 100
    app.game.result_flow.update_result_pending()
    assert app.game.manual_result == "white_wins_on_time"
    assert app.game.result_flow.series_scores.get("alice") == 1.0, "on-time win still scores"


def test_online_result_saves_before_the_move_animation_settles(tmp_path, monkeypatch):
    """The save must not wait for the capture animation — otherwise closing the
    window mid-animation would lose the game."""
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.game.board.is_animating() or app.game.board.effects.captures, "still animating"
    app.game.result_flow.update_result_pending()
    assert app.game.result_flow._last_saved_pgn_path is not None, \
        "saved despite the unsettled board"


def test_finished_game_resume_does_not_replay_result_effects(tmp_path, monkeypatch):
    """A transient reconnect to an already-finished game must not re-fire the win
    sound / checkmate takeover (the result latch must survive the resume)."""
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    _settle(app)
    app.game.result_flow.update_result_pending()                     # latches + fires effects once
    assert app.game._result_first_seen_at_ms is not None
    latch = app.game._result_first_seen_at_ms
    app.coordinator._handle_game_resumed({
        "move_history": [{"san": s} for s in SCHOLARS_MATE],
        "fen": "", "result_reason": "checkmate", "result_winner": "white",
        "skillcheck_log": [], "skillcheck_locks": [], "pending_skillcheck": None,
    })
    assert app.game._result_first_seen_at_ms == latch, "resume must not re-arm the effects"


def test_resumed_static_result_saves_partial(tmp_path, monkeypatch):
    """A player who reconnects into an aborted_disconnect/server_shutdown keeps the
    partial archive too — symmetric with the still-connected opponent."""
    app = _online_app(tmp_path, monkeypatch)
    app.coordinator._handle_game_resumed({
        "move_history": [{"san": s} for s in ["e4", "e5"]],
        "fen": "", "result_reason": "aborted_disconnect", "result_winner": None,
        "skillcheck_log": [], "skillcheck_locks": [], "pending_skillcheck": None,
    })
    assert app.game.manual_result == "aborted_disconnect"
    assert '[Result "*"]' in _saved_text(app)


def test_watchdog_does_not_fire_before_timeout(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    app.game.result_flow.update_result_pending()
    fake_now[0] += RESULT_CONFIRM_TIMEOUT_MS - 500
    app.game.result_flow.update_result_pending()
    assert app.game.manual_result is None, "must give the server result time to arrive on high ping"


def test_verdict_failure_still_sets_result_and_resyncs_without_truncating(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    frm, to = _capture_mate_board(app)
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    app.coordinator._handle_skill_check_required(_required_payload(frm, to))
    app.coordinator._handle_remote_move_applied(_move_applied(frm, to, 1))
    # The deferred apply blows up when the result forces it early.
    app.game.skillcheck_session.online_verdict_action = (
        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.game.manual_result == "white_wins", \
        "truth (result) is set before the fragile visuals"
    assert app.coordinator._resyncing is True, "the apply failure escalates to a resync"
    _settle(app)
    app.game.result_flow.update_result_pending()
    assert app.game.result_flow._last_saved_pgn_path is None, "no truncated save while resyncing"


SCHOLARS_MATE = ["e4", "e5", "Bc4", "Bc5", "Qh5", "Nf6", "Qxf7#"]


def test_resync_recovery_saves_the_complete_game(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    frm, to = _capture_mate_board(app)
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    app.coordinator._handle_skill_check_required(_required_payload(frm, to))
    app.coordinator._handle_remote_move_applied(_move_applied(frm, to, 1))
    app.game.skillcheck_session.online_verdict_action = (
        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    app.coordinator._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    # Server state-sync returns the full move list + the authoritative result.
    app.coordinator._handle_game_resumed({
        "move_history": [{"san": s} for s in SCHOLARS_MATE],
        "fen": "", "result_reason": "checkmate", "result_winner": "white",
        "skillcheck_log": [], "skillcheck_locks": [], "pending_skillcheck": None,
    })
    assert app.coordinator._resyncing is False
    assert app.game.manual_result == "white_wins"
    _settle(app)
    app.game.result_flow.update_result_pending()
    text = _saved_text(app)
    assert "Qxf7#" in text and '[Result "1-0"]' in text
    assert len(_pgn_files(tmp_path)) == 1


def test_result_redelivery_saves_once_and_scores_once(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    result = {"reason": "checkmate", "winner_color": "white"}
    app.coordinator._handle_online_result(result)
    _settle(app)
    app.game.result_flow.update_result_pending()
    app.coordinator._handle_online_result(result)                # reconnect re-delivery
    app.game.result_flow.update_result_pending()
    assert len(_pgn_files(tmp_path)) == 1, "one file despite re-delivery"
    assert app.game.result_flow.series_scores.get("alice") == 1.0, "scored exactly once"


def _one_quiet_move(app):
    """A legal 1-ply game with no result (kings + a pushed pawn)."""
    app.game.match.backend = make_backend({
        sq(0, 4): piece(K, BLACK), sq(7, 4): piece(K, WHITE), sq(6, 4): piece(P, WHITE),
    }, turn=WHITE)
    app.game.match.try_move(sq(6, 4), sq(4, 4))            # e4
    assert app.game.current_result() is None


def test_partial_star_upgrades_to_decisive_result(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _one_quiet_move(app)
    app.game.result_flow.auto_save_pgn()  # forced partial save (result None -> *)
    assert app.game.result_flow._last_saved_result_tag == "*"
    first = app.game.result_flow._last_saved_pgn_path
    assert '[Result "*"]' in _saved_text(app)
    app.game.manual_result = "white_wins_by_resignation"
    app.game.result_flow.auto_save_pgn()
    assert app.game.result_flow._last_saved_pgn_path == first, \
        "overwrites the same file, no duplicate"
    assert '[Result "1-0"]' in _saved_text(app)
    assert len(_pgn_files(tmp_path)) == 1


def test_aborted_result_shows_neutral_headline_for_both_sides(tmp_path, monkeypatch):
    """REGRESSION: no-winner codes fell into the winner branch (anything not
    white_wins* read as a black win), so a zero-move abort showed VICTORY to
    black and DEFEAT to white. Aborted/cancelled games are nobody's result:
    both perspectives get the neutral GAME ABORTED headline with draw intent."""
    for side in ("white", "black"):
        app = _online_app(tmp_path, monkeypatch, your_color=side)
        app.coordinator._handle_online_result({"reason": "aborted"})
        word, intent = app.game.result_flow._outcome_word_intent(
            "aborted", "Game aborted")
        assert word == "GAME ABORTED"
        assert intent == "draw"


def test_room_lost_midgame_saves_partial(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _one_quiet_move(app)
    app.coordinator._handle_online_error({"reason": "room_lost"})
    assert '[Result "*"]' in _saved_text(app), "a server fault never costs the player their game"


def test_server_shutdown_saves_partial_but_first_move_abort_does_not(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _one_quiet_move(app)
    app.coordinator._handle_online_result({"reason": "server_shutdown"})
    assert app.game.result_flow._last_saved_pgn_path is not None, "server_shutdown with moves saves"
    app2 = _online_app(tmp_path, monkeypatch)         # fresh, 0 moves
    app2.coordinator._handle_online_result({"reason": "aborted"})
    assert app2.game.result_flow._last_saved_pgn_path is None, \
        "an empty first-move abort is not saved"


def test_local_capture_mate_still_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.mode = SINGLE_SCREEN
    app.game.match.new_game()
    app.game.match.backend = make_backend({
        sq(0, 7): piece(K, BLACK), sq(1, 6): piece(P, BLACK),
        sq(7, 6): piece(Q, WHITE), sq(6, 1): piece(B, WHITE),
        sq(7, 0): piece(K, WHITE),
    }, turn=WHITE)
    app.game.match.try_move(sq(7, 6), sq(1, 6))
    assert app.game.match.game_result() == "white_wins"
    _settle(app)
    app.game.result_flow.update_result_pending()
    text = _saved_text(app)
    assert "Qxg7#" in text and '[Result "1-0"]' in text
