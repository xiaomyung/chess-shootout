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
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from unittest.mock import MagicMock

import pygame as pg
import pytest

from chessshootout.backend.utils import coord_from_square
from chessshootout.domain.match import SINGLE_SCREEN
from chessshootout.frontend.frontend import Frontend, RESULT_CONFIRM_TIMEOUT_MS
from tests.helpers import BLACK, B, K, P, Q, WHITE, make_backend, piece, sq


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pg.init()
    pg.display.set_mode((1000, 800))
    yield
    pg.quit()


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
    app.online_client = FakeOnlineClient()
    app._start_online_game({
        "white_name": "alice", "black_name": "bob", "your_color": your_color,
        "time_minutes": 5, "increment_seconds": 0,
        "white_country": "", "black_country": "",
        "white_score": 0.0, "black_score": 0.0,
    })
    return app


def _capture_mate_board(app):
    """White Qg1, Bb2 (defends g7), Ka1; Black Kh8, pawn g7. Qxg7# is a capture-mate."""
    app.match.backend = make_backend({
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
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_remote_move_applied(_move_applied(frm, to, 1))
    app.skillcheck_overlay.update(pg.time.get_ticks() + 500)  # run the deferred apply
    return frm, to


def _settle(app):
    app.board.cancel_animations()
    app.board.effects.clear()


def _saved_text(app):
    assert app._last_saved_pgn_path is not None, "a PGN was saved"
    with open(app._last_saved_pgn_path) as f:
        return f.read()


def _pgn_files(tmp_path):
    return list((tmp_path / "games").glob("*.pgn"))


# ---- the core: a capture-mate must save the full game ----------------------

def test_online_capture_mate_saves_full_game_with_result(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    assert app.match.game_result() == "white_wins", "the mate landed"
    app._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    _settle(app)
    app._update_result_pending()
    text = _saved_text(app)
    assert "Qxg7#" in text, "the mating ply is in the saved PGN (not truncated)"
    assert '[Result "1-0"]' in text
    assert len(_pgn_files(tmp_path)) == 1


def test_online_mate_saved_via_watchdog_when_result_message_is_missed(tmp_path, monkeypatch):
    """The reconnect-storm case: move_applied lands the mate but the `result`
    message never arrives. The local-promotion watchdog must recover + save."""
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    _settle(app)
    # No result message delivered. Frame loop must NOT save yet (server-authoritative).
    app._update_result_pending()
    assert app._last_saved_pgn_path is None
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    app._update_online_phase()                       # arms the await timer
    assert app.manual_result is None
    fake_now[0] += RESULT_CONFIRM_TIMEOUT_MS + 100
    app._update_online_phase()                       # promotes the position-proved result
    assert app.manual_result == "white_wins"
    app._update_result_pending()
    text = _saved_text(app)
    assert "Qxg7#" in text and '[Result "1-0"]' in text


def test_watchdog_awards_score_for_on_time_win(tmp_path, monkeypatch):
    """A locally-flagged clock produces a *_on_time result; the watchdog must still
    credit the winner's series score (the suffix must not be missed)."""
    app = _online_app(tmp_path, monkeypatch)
    app.match.try_move(sq(6, 4), sq(4, 4))            # e4, so there's a game to save
    app.match.clock.flagged = BLACK                   # black flags -> white wins on time
    assert app.match.game_result() == "white_wins_on_time"
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    app._update_online_phase()
    fake_now[0] += RESULT_CONFIRM_TIMEOUT_MS + 100
    app._update_online_phase()
    assert app.manual_result == "white_wins_on_time"
    assert app._series_scores.get("alice") == 1.0, "on-time win still scores"


def test_resumed_static_result_saves_partial(tmp_path, monkeypatch):
    """A player who reconnects into an aborted_disconnect/server_shutdown keeps the
    partial archive too — symmetric with the still-connected opponent."""
    app = _online_app(tmp_path, monkeypatch)
    app._handle_game_resumed({
        "move_history": [{"san": s} for s in ["e4", "e5"]],
        "fen": "", "result_reason": "aborted_disconnect", "result_winner": None,
        "skillcheck_log": [], "skillcheck_locks": [], "pending_skillcheck": None,
    })
    assert app.manual_result == "aborted_disconnect"
    assert '[Result "*"]' in _saved_text(app)


def test_watchdog_does_not_fire_before_timeout(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    fake_now = [10_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: fake_now[0])
    app._update_online_phase()
    fake_now[0] += RESULT_CONFIRM_TIMEOUT_MS - 500
    app._update_online_phase()
    assert app.manual_result is None, "must give the server result time to arrive on high ping"


# ---- verdict/apply failure: truth-first + resync, never truncated ----------

def test_verdict_failure_still_sets_result_and_resyncs_without_truncating(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    frm, to = _capture_mate_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_remote_move_applied(_move_applied(frm, to, 1))
    # The deferred apply blows up when the result forces it early.
    app._online_verdict_action = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    app._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    assert app.manual_result == "white_wins", "truth (result) is set before the fragile visuals"
    assert app._resyncing is True, "the apply failure escalates to a resync"
    _settle(app)
    app._update_result_pending()
    assert app._last_saved_pgn_path is None, "no truncated save while resyncing"


SCHOLARS_MATE = ["e4", "e5", "Bc4", "Bc5", "Qh5", "Nf6", "Qxf7#"]


def test_resync_recovery_saves_the_complete_game(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    frm, to = _capture_mate_board(app)
    app._skillcheck_gate(frm, to)
    app._handle_skill_check_required(_required_payload(frm, to))
    app._handle_remote_move_applied(_move_applied(frm, to, 1))
    app._online_verdict_action = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    app._handle_online_result({"reason": "checkmate", "winner_color": "white"})
    # Server state-sync returns the full move list + the authoritative result.
    app._handle_game_resumed({
        "move_history": [{"san": s} for s in SCHOLARS_MATE],
        "fen": "", "result_reason": "checkmate", "result_winner": "white",
        "skillcheck_log": [], "skillcheck_locks": [], "pending_skillcheck": None,
    })
    assert app._resyncing is False
    assert app.manual_result == "white_wins"
    _settle(app)
    app._update_result_pending()
    text = _saved_text(app)
    assert "Qxf7#" in text and '[Result "1-0"]' in text
    assert len(_pgn_files(tmp_path)) == 1


# ---- idempotency + score integrity -----------------------------------------

def test_result_redelivery_saves_once_and_scores_once(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _land_capture_mate(app)
    result = {"reason": "checkmate", "winner_color": "white"}
    app._handle_online_result(result)
    _settle(app)
    app._update_result_pending()
    app._handle_online_result(result)                # reconnect re-delivery
    app._update_result_pending()
    assert len(_pgn_files(tmp_path)) == 1, "one file despite re-delivery"
    assert app._series_scores.get("alice") == 1.0, "scored exactly once"


def _one_quiet_move(app):
    """A legal 1-ply game with no result (kings + a pushed pawn)."""
    app.match.backend = make_backend({
        sq(0, 4): piece(K, BLACK), sq(7, 4): piece(K, WHITE), sq(6, 4): piece(P, WHITE),
    }, turn=WHITE)
    app.match.try_move(sq(6, 4), sq(4, 4))            # e4
    assert app.current_result() is None


def test_partial_star_upgrades_to_decisive_result(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _one_quiet_move(app)
    app._auto_save_pgn()                              # forced partial save (result None -> *)
    assert app._last_saved_result_tag == "*"
    first = app._last_saved_pgn_path
    assert '[Result "*"]' in _saved_text(app)
    app.manual_result = "white_wins_by_resignation"
    app._auto_save_pgn()
    assert app._last_saved_pgn_path == first, "overwrites the same file, no duplicate"
    assert '[Result "1-0"]' in _saved_text(app)
    assert len(_pgn_files(tmp_path)) == 1


# ---- server-fault partials + abort policy ----------------------------------

def test_room_lost_midgame_saves_partial(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _one_quiet_move(app)
    app._handle_online_error({"reason": "room_lost"})
    assert '[Result "*"]' in _saved_text(app), "a server fault never costs the player their game"


def test_server_shutdown_saves_partial_but_first_move_abort_does_not(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _one_quiet_move(app)
    app._handle_online_result({"reason": "server_shutdown"})
    assert app._last_saved_pgn_path is not None, "server_shutdown with moves saves"
    app2 = _online_app(tmp_path, monkeypatch)         # fresh, 0 moves
    app2._handle_online_result({"reason": "aborted"})
    assert app2._last_saved_pgn_path is None, "an empty first-move abort is not saved"


# ---- parity: local mate still saves ----------------------------------------

def test_local_capture_mate_still_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app.mode = SINGLE_SCREEN
    app.match.new_game()
    app.match.backend = make_backend({
        sq(0, 7): piece(K, BLACK), sq(1, 6): piece(P, BLACK),
        sq(7, 6): piece(Q, WHITE), sq(6, 1): piece(B, WHITE),
        sq(7, 0): piece(K, WHITE),
    }, turn=WHITE)
    app.match.try_move(sq(7, 6), sq(1, 6))
    assert app.match.game_result() == "white_wins"
    _settle(app)
    app._update_result_pending()
    text = _saved_text(app)
    assert "Qxg7#" in text and '[Result "1-0"]' in text
