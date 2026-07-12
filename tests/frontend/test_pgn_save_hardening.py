"""PGN save-pipeline hardening (v2.7.0).

Covers the single result-adoption choke point (_on_result_final: promote +
award + save, called at adoption rather than on the next painted frame),
incremental "*"-tag autosave while a game is live (ply+throttle gated, atomic
tmp-write + os.replace, reservation collision handling), the bounded failure
UX (one-time toast, one fallback-dir retry, a per-game latch that stops the
incremental driver but never blocks the finalize save), and the teardown
backstops (_on_back_to_menu force-promotes an unconfirmed online result before
leaving; draw_frame drains inbound online events before _update_result_pending
so a result queued the same frame the player quits is still saved).
"""
import os

from datetime import datetime
from unittest.mock import MagicMock

import pygame as pg

from tests.conftest import pygame_display
from chessshootout import paths
from chessshootout.backend.utils import coord_from_square
from chessshootout.frontend.frontend import Frontend
from chessshootout.frontend.result_flow import AUTOSAVE_THROTTLE_MS
from chessshootout.online.client import Event
from tests.helpers import B, BLACK, K, P, Q, WHITE, make_backend, piece, sq


_pygame_init = pygame_display(1000, 800)


class FakeOnlineClient:

    def __init__(self, room_id="room-1"):
        self.room_id = room_id
        self.state = "connected"
        self.opp_state = "connected"
        self.sent_moves = []
        self.shots = 0
        self.state_syncs = 0
        self._queue = []

    def queue(self, event):
        self._queue.append(event)

    def drain_inbound(self):
        events = self._queue
        self._queue = []
        return events

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

    def force_reconnect(self):
        pass

    def send_left_result(self):
        pass

    def cancel_queue(self):
        pass

    def send_draw_response(self, accept):
        pass

    def send_takeback_response(self, accept):
        pass

    def send_rematch_response(self, accept):
        pass


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


def _local_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path))
    app = Frontend(1000, 800)
    app.sound_manager = MagicMock()
    app._on_start_game({
        "mode": "single_screen", "nickname": "alice",
        "time_minutes": None, "increment_seconds": 0, "side": "white",
    })
    return app


def _pgn_files(tmp_path):
    return list((tmp_path / "games").glob("*.pgn"))


def _e4(app):
    app.game.match.try_move(sq(6, 4), sq(4, 4))


def _e5(app):
    app.game.match.try_move(sq(1, 4), sq(3, 4))


def _capture_mate_board(app):
    """White Qg1, Bb2 (defends g7), Ka1; Black Kh8, pawn g7. Qxg7# is mate."""
    app.game.match.backend = make_backend({
        sq(0, 7): piece(K, BLACK), sq(1, 6): piece(P, BLACK),
        sq(7, 6): piece(Q, WHITE), sq(6, 1): piece(B, WHITE),
        sq(7, 0): piece(K, WHITE),
    }, turn=WHITE)


def test_hard_os_error_tries_the_fallback_dir_then_latches(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: fallback_dir)
    attempted_dirs = []

    def failing_reserve(directory, prefix):
        attempted_dirs.append(os.path.normpath(str(directory)))
        return None

    app.game.result_flow._reserve_pgn_path = failing_reserve
    _e4(app)
    assert app.game.result_flow._auto_save_pgn() is None
    assert len(attempted_dirs) == 2, "both the primary AND the fallback dir were tried"
    assert os.path.normpath(str(paths.get_games_dir())) in attempted_dirs
    assert os.path.normpath(str(fallback_dir / paths.GAMES_SUBDIR)) in attempted_dirs
    assert app.game.result_flow._save_failed is True


def test_unwritable_primary_reuses_one_fallback_file_across_incremental_writes(
        tmp_path, monkeypatch):
    """When the primary games dir stays unwritable but the fallback is fine, the
    incremental driver must keep updating ONE fallback file, not reserve a fresh
    timestamped file every throttled tick (which orphaned N-1 partial PGNs)."""
    app = _local_app(tmp_path, monkeypatch)
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: fallback_dir)
    primary = os.path.normpath(str(paths.get_games_dir()))
    real_reserve = app.game.result_flow._reserve_pgn_path

    def reserve(directory, prefix):
        if os.path.normpath(str(directory)) == primary:
            return None  # the primary games dir is unwritable all game
        return real_reserve(directory, prefix)

    app.game.result_flow._reserve_pgn_path = reserve
    now = [2_000_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: now[0])

    _e4(app)
    app.game.result_flow._update_incremental_autosave()
    _e5(app)
    now[0] += AUTOSAVE_THROTTLE_MS + 100
    app.game.result_flow._update_incremental_autosave()
    app.game.match.try_move(sq(6, 3), sq(4, 3))  # a third ply (d4)
    now[0] += AUTOSAVE_THROTTLE_MS + 100
    app.game.result_flow._update_incremental_autosave()

    fallback_games = list((fallback_dir / paths.GAMES_SUBDIR).glob("*.pgn"))
    assert len(fallback_games) == 1, "one fallback file, reused across ticks — not one per ply"
    assert _pgn_files(tmp_path) == [], "nothing lands in the unwritable primary dir"
    text = fallback_games[0].read_text(encoding="utf-8")
    assert "e4 e5" in text and '[Result "*"]' in text


def test_hard_os_error_shows_the_toast_exactly_once(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: tmp_path / "fallback")
    app.game.result_flow._reserve_pgn_path = lambda directory, prefix: None
    shown = []
    monkeypatch.setattr(app.toast, "show", lambda msg, *a, **k: shown.append(msg))
    _e4(app)
    app.game.result_flow._auto_save_pgn()
    _e5(app)
    app.game.result_flow._auto_save_pgn()
    error_toasts = [m for m in shown if "Could not save PGN" in m]
    assert len(error_toasts) == 1


def test_latch_stops_the_incremental_driver_from_retrying_every_frame(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: tmp_path / "fallback")
    app.game.result_flow._reserve_pgn_path = lambda directory, prefix: None
    _e4(app)
    app.game.result_flow._auto_save_pgn()
    assert app.game.result_flow._save_failed is True

    calls = []
    monkeypatch.setattr(app.game.result_flow, "_auto_save_pgn", lambda: calls.append(1))
    _e5(app)
    now = [5_000_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: now[0])
    app.game.result_flow._autosave_last_write_ms = now[0] - AUTOSAVE_THROTTLE_MS
    app.game.result_flow._update_incremental_autosave()
    assert calls == [], "the latch keeps the per-frame incremental driver from retrying"


def test_hard_failure_finalize_retries_once_per_result_code(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "get_fallback_data_dir", lambda: tmp_path / "fallback")
    app.game.result_flow._reserve_pgn_path = lambda directory, prefix: None
    _e4(app)

    calls = []
    real = app.game.result_flow._auto_save_pgn

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(app.game.result_flow, "_auto_save_pgn", counting)
    app.game.result_flow._on_result_final("white_wins_by_resignation")
    assert app.game.result_flow._save_failed is True
    app.game.result_flow._on_result_final("white_wins_by_resignation")
    app.game.result_flow._on_result_final("white_wins_by_resignation")
    assert len(calls) == 1

    app.game.result_flow._on_result_final("white_wins")
    assert len(calls) == 2


def test_latch_never_blocks_the_finalize_save(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    _e4(app)
    app.game.result_flow._save_failed = True
    app.game.manual_result = "white_wins_by_resignation"
    app.game.result_flow._on_result_final(app.game.manual_result)
    files = _pgn_files(tmp_path)
    assert len(files) == 1, "finalize always gets a fresh attempt, latch or not"
    assert '[Result "1-0"]' in files[0].read_text(encoding="utf-8")


def test_permission_error_on_replace_is_skipped_without_latching(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    _e4(app)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked by another process")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    now = [3_000_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: now[0])
    app.game.result_flow._autosave_last_write_ms = now[0] - AUTOSAVE_THROTTLE_MS
    app.game.result_flow._update_incremental_autosave()
    assert app.game.result_flow._save_failed is False, \
        "PermissionError on replace is transient, not latched"
    files = _pgn_files(tmp_path)
    assert len(files) == 1, "the path is reserved even though the content write failed"
    assert files[0].read_text(encoding="utf-8") == ""

    _e5(app)
    now[0] += AUTOSAVE_THROTTLE_MS
    app.game.result_flow._update_incremental_autosave()
    files = _pgn_files(tmp_path)
    assert len(files) == 1, "the same reserved file, no duplicate"
    text = files[0].read_text(encoding="utf-8")
    assert "e4 e5" in text, "the next throttled write succeeds"


def test_back_to_menu_during_result_confirm_window_force_saves_real_result(
        tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _capture_mate_board(app)
    app.game.match.try_move(sq(7, 6), sq(1, 6))
    assert app.game.match.game_result() == "white_wins"
    assert app.game.manual_result is None, "still waiting on the server confirm"
    app._on_back_to_menu()
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    assert '[Result "1-0"]' in files[0].read_text(encoding="utf-8")


def test_esc_during_result_confirm_window_saves_via_handle_escape(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _capture_mate_board(app)
    app.game.match.try_move(sq(7, 6), sq(1, 6))
    assert app.game.current_result() == "white_wins"
    app.input_router._handle_escape()
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    assert '[Result "1-0"]' in files[0].read_text(encoding="utf-8")


def test_tear_down_online_session_saves_a_midgame_partial(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _e4(app)
    app.coordinator._tear_down_online_session()
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    assert '[Result "*"]' in files[0].read_text(encoding="utf-8")


def test_tear_down_online_session_is_a_no_op_on_empty_history(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    app.coordinator._tear_down_online_session()
    assert _pgn_files(tmp_path) == []


def test_result_drained_and_saved_within_a_single_draw_frame_call(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _e4(app)
    app.coordinator.client.queue(Event("result", {
        "reason": "resignation", "winner_color": "white"}))
    app.draw_frame()
    assert app.game.manual_result == "white_wins_by_resignation"
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    assert '[Result "1-0"]' in files[0].read_text(encoding="utf-8")


def test_drain_reorder_skillcheck_required_still_opens_the_overlay_same_frame(
        tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 3): piece(Q, WHITE), sq(3, 3): piece(P, BLACK),
    }, turn=WHITE)
    frm, to = sq(4, 3), sq(3, 3)
    app.coordinator.client.queue(Event("skill_check_required", {
        "kind": "wheel", "seed": "s1", "value_diff": 8, "deadline_ms": 5000.0,
        "elapsed_ms": 0.0, "miss_count": 0,
        "from": coord_from_square(frm), "to": coord_from_square(to),
        "promotion": None,
    }))
    app.draw_frame()
    assert app.game.skillcheck_overlay.is_active()


def test_drain_reorder_offer_banner_still_shows_the_same_frame(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    app.coordinator.client.queue(Event("draw_offered", {}))
    app.draw_frame()
    assert not app.coordinator.offer_banners.is_empty()


class _FrozenDatetime(datetime):
    _frozen = datetime(2026, 7, 9, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls._frozen


def test_filename_collision_within_one_second_gets_dash2_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr("chessshootout.frontend.result_flow.datetime", _FrozenDatetime)

    app1 = _local_app(tmp_path, monkeypatch)
    _e4(app1)
    app1.game.manual_result = "white_wins_by_resignation"
    path1 = app1.game.result_flow._auto_save_pgn()

    app2 = _local_app(tmp_path, monkeypatch)
    _e4(app2)
    app2.game.manual_result = "black_wins_by_resignation"
    path2 = app2.game.result_flow._auto_save_pgn()

    assert path1 != path2
    assert os.path.basename(path2).endswith("-2.pgn")
    assert os.path.exists(path1)
    with open(path1, encoding="utf-8") as f:
        assert '[Result "1-0"]' in f.read(), "the first file is intact, not overwritten"
    with open(path2, encoding="utf-8") as f:
        assert '[Result "0-1"]' in f.read()


def test_local_resign_saves_immediately_without_a_follow_up_frame(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    _e4(app)
    app.game._perform_resign()
    assert app.game.manual_result == "white_wins_by_resignation", "black (to move) resigned"
    files = _pgn_files(tmp_path)
    assert len(files) == 1, "the perform-path itself saved it, no draw_frame() needed"
    assert '[Result "1-0"]' in files[0].read_text(encoding="utf-8")


def test_local_draw_agreement_saves_immediately_without_a_follow_up_frame(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    _e4(app)
    app.game._perform_draw()
    assert app.game.manual_result == "draw_agreement"
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    assert '[Result "1/2-1/2"]' in files[0].read_text(encoding="utf-8")


def test_online_stalemate_keeps_its_own_reason_not_agreement(tmp_path, monkeypatch):
    app = _online_app(tmp_path, monkeypatch)
    _e4(app)
    app.coordinator._handle_online_result({"reason": "draw_stalemate"})
    assert app.game.manual_result == "draw_stalemate"
    assert app.game.result_text() == ("Draw", "by stalemate")
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    assert '[Result "1/2-1/2"]' in files[0].read_text(encoding="utf-8")


def test_incremental_autosave_writes_star_tag_throttled_then_finalizes(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    now = [1_000_000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: now[0])

    assert _pgn_files(tmp_path) == [], "nothing written before any ply lands"
    _e4(app)
    app.game.result_flow._update_incremental_autosave()
    files = _pgn_files(tmp_path)
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert '[Result "*"]' in text
    assert "1. e4" in text

    _e5(app)
    now[0] += AUTOSAVE_THROTTLE_MS - 100
    app.game.result_flow._update_incremental_autosave()
    text = files[0].read_text(encoding="utf-8")
    assert "e4 e5" not in text, "throttled: no write within 1s of the previous one"

    now[0] += 200
    app.game.result_flow._update_incremental_autosave()
    text = files[0].read_text(encoding="utf-8")
    assert "e4 e5" in text
    assert '[Result "*"]' in text

    app.game.manual_result = "white_wins_by_resignation"
    app.game.result_flow._on_result_final(app.game.manual_result)
    text = files[0].read_text(encoding="utf-8")
    assert '[Result "1-0"]' in text
    assert len(_pgn_files(tmp_path)) == 1, "the finalize rewrites the same file"


def test_incremental_autosave_skips_when_result_already_showing(tmp_path, monkeypatch):
    app = _local_app(tmp_path, monkeypatch)
    _e4(app)
    app.game.manual_result = "white_wins_by_resignation"
    app.game.result_flow._update_incremental_autosave()
    assert _pgn_files(tmp_path) == [], "a finished game is the finalize path's job, not this one"
