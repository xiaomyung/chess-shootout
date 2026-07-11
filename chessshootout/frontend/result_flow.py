import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import BOT, ONLINE
from chessshootout.domain.result_stats import compute_result_stats
from chessshootout.domain.pgn.generate import format_annotations, generate_pgn, RESULT_CODES
from chessshootout.backend.pieces import PieceColor


log = logging.getLogger("chess.frontend")

AUTOSAVE_THROTTLE_MS = 1000
RESULT_CONFIRM_TIMEOUT_MS = 4000

RESULT_TEXT = {
    "white_wins": ("White wins", "by checkmate"),
    "black_wins": ("Black wins", "by checkmate"),
    "white_wins_on_time": ("White wins", "on time"),
    "black_wins_on_time": ("Black wins", "on time"),
    "white_wins_by_resignation": ("White wins", "by resignation"),
    "black_wins_by_resignation": ("Black wins", "by resignation"),
    "white_wins_by_abandonment": ("White wins", "by abandonment"),
    "black_wins_by_abandonment": ("Black wins", "by abandonment"),
    "draw_stalemate": ("Draw", "by stalemate"),
    "draw_repetition": ("Draw", "by threefold repetition"),
    "draw_fifty_move": ("Draw", "by fifty-move rule"),
    "draw_insufficient_material": ("Draw", "by insufficient material"),
    "draw_agreement": ("Draw", "by agreement"),
    "aborted": ("Game aborted", "no moves played"),
    "aborted_disconnect": ("Game aborted", "opponent disconnected"),
    "server_shutdown": ("Game cancelled", "server shutting down"),
}


def _open_with_default_app(path):
    if sys.platform == "darwin":
        candidates = [["open", path]]
    elif sys.platform.startswith("win"):
        try:
            os.startfile(path)
            return True
        except OSError:
            return False
    else:
        candidates = [
            ["xdg-open", path],
            ["gio", "open", path],
        ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue
    return False


def _score_str(score):
    int_part = int(score)
    has_half = score - int_part >= 0.5 - 1e-9
    if int_part == 0 and has_half:
        return "½"
    if has_half:
        return f"{int_part}½"
    return str(int_part)


class ResultFlow:

    def __init__(self, screen):
        self.screen = screen
        self.app = screen.app
        self._result_cache_key = None
        self._result_cache = None
        self._series_scores = {}
        self._series_score_awarded = False
        self._save_failed = False
        self._save_error_toast_shown = False
        self._autosave_last_write_ms = -AUTOSAVE_THROTTLE_MS
        self._autosave_last_ply = 0
        self._last_saved_pgn_path = None
        self._last_saved_result_tag = None
        self._result_await_since_ms = None
        self._result_logged = False
        self._final_save_attempted_for = None

    def current_result(self):
        screen = self.screen
        clock = screen.match.clock
        flagged = clock.flagged if clock is not None else None
        history = screen.match.move_history
        last_move = history[-1].move if history else None
        key = (len(history), last_move, screen.manual_result, flagged)
        if key != self._result_cache_key:
            self._result_cache_key = key
            self._result_cache = screen.manual_result or screen.match.game_result()
        return self._result_cache

    def result_text(self):
        code = self.app.current_result()
        if code is None:
            return None
        return RESULT_TEXT.get(code)

    def _feed_result_menu(self):
        screen = self.screen
        code = self.app.current_result()
        text = self.result_text()
        if code is None or text is None:
            screen.result_menu.set_result(None, "draw", "")
            return
        title, reason = text
        word, intent = self._outcome_word_intent(code, title)
        moves = (len(screen.match.move_history) + 1) // 2
        full_reason = f"{reason} · {moves} moves" if reason else f"{moves} moves"
        subject = self._result_subject_color(code)
        stats = compute_result_stats(screen.match.move_history, screen.match.clock, subject)
        screen.result_menu.set_result(word, intent, full_reason, stats)
        if self.app.mode == ONLINE:
            screen.result_menu.set_series(
                screen.white_name, screen.black_name,
                _score_str(self._series_scores.get(screen.white_name, 0.0)),
                _score_str(self._series_scores.get(screen.black_name, 0.0)))
        else:
            screen.result_menu.set_series(None, None, None, None)

    def _perspective_color(self):
        if self.app.mode in (ONLINE, BOT):
            return self.screen.match.local_color
        return None

    def _outcome_word_intent(self, code, title):
        if code.startswith("draw"):
            return "DRAW", "draw"
        winner = PieceColor.WHITE if code.startswith("white_wins") else PieceColor.BLACK
        local = self._perspective_color()
        if local is not None:
            if winner == local:
                return "VICTORY", "win"
            return "DEFEAT", "loss"
        return title.upper(), "win"

    def _result_subject_color(self, code):
        local = self._perspective_color()
        if local is not None:
            return local
        if code.startswith("black_wins"):
            return PieceColor.BLACK
        return PieceColor.WHITE

    def _move_visually_settled(self):
        board = self.screen.board
        return not board.is_animating() and not board.effects.captures

    def _update_result_pending(self):
        screen = self.screen
        self._update_incremental_autosave()
        result = self.app.current_result()
        if result is None or screen.pgn_review:
            screen._result_first_seen_at_ms = None
            self._result_await_since_ms = None
            return
        if self.app.mode == ONLINE and screen.manual_result is None:
            if not self.app._resyncing:
                self._promote_awaited_result(result)
            return
        if self.app.mode == ONLINE and self.app._resyncing:
            return
        if RESULT_CODES.get(result) is not None:
            self._on_result_final(result)
        if screen._result_first_seen_at_ms is None and self._move_visually_settled():
            screen._result_first_seen_at_ms = pg.time.get_ticks()
            try:
                screen._trigger_result_effects()
            except Exception:
                log.exception("result effects failed")

    def _promote_awaited_result(self, engine_result):
        now = pg.time.get_ticks()
        if self._result_await_since_ms is None:
            self._result_await_since_ms = now
            return
        if now - self._result_await_since_ms < RESULT_CONFIRM_TIMEOUT_MS:
            return
        self._finalize_result(engine_result)
        log.info("promoted unconfirmed online result locally: %s", engine_result)

    def _award_series_win(self, winner):
        name = self.screen._name_for_color(winner)
        self._series_scores[name] = self._series_scores.get(name, 0.0) + 1

    def _award_series_draw(self):
        for name in (self.screen.white_name, self.screen.black_name):
            self._series_scores[name] = self._series_scores.get(name, 0.0) + 0.5

    def _on_open_pgn(self):
        path = self._last_saved_pgn_path
        if path is None or not os.path.exists(path):
            self.app.toast.show("No saved PGN")
            return
        if not _open_with_default_app(path):
            self.app.toast.show("Could not open PGN")

    def _probe_games_dir_writable(self):
        games_dir = str(paths.get_games_dir())
        try:
            os.makedirs(games_dir, exist_ok=True)
        except OSError:
            self.app.toast.show("Games folder isn't writable — check your data folder")
            return
        if not paths.is_writable_dir(games_dir):
            self.app.toast.show("Games folder isn't writable — check your data folder")

    def _show_save_error_toast_once(self):
        if self._save_error_toast_shown:
            return
        self._save_error_toast_shown = True
        self.app.toast.show("Could not save PGN — check games folder")

    def _remove_quietly(self, path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _reserve_pgn_path(self, directory, prefix):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            log.exception("pgn autosave: could not create games dir %s", directory)
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for suffix in range(1, 1000):
            name = (f"{prefix}-{stamp}.pgn" if suffix == 1
                    else f"{prefix}-{stamp}-{suffix}.pgn")
            candidate = os.path.join(directory, name)
            try:
                with open(candidate, "x", encoding="utf-8"):
                    pass
                return candidate
            except FileExistsError:
                continue
            except OSError:
                log.exception("pgn autosave: could not reserve %s", candidate)
                return None
        return None

    def _write_pgn_atomic(self, path, text):
        directory = os.path.dirname(path)
        tmp_path = os.path.join(directory, f".{os.path.basename(path)}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)
        except (OSError, UnicodeError):
            log.exception("pgn autosave: could not write %s", path)
            self._remove_quietly(tmp_path)
            return "hard_failure"
        try:
            os.replace(tmp_path, path)
        except PermissionError:
            log.debug("pgn autosave: replace skipped (permission) for %s", path)
            self._remove_quietly(tmp_path)
            return "permission_transient"
        except OSError:
            log.exception("pgn autosave: could not replace %s", path)
            self._remove_quietly(tmp_path)
            return "hard_failure"
        return "ok"

    def _commit_pgn_write(self, directory, prefix, text):
        path = self._last_saved_pgn_path
        if path is None or os.path.dirname(path) != os.path.normpath(directory):
            path = self._reserve_pgn_path(directory, prefix)
            if path is None:
                return "hard_failure"
            self._last_saved_pgn_path = path
        return self._write_pgn_atomic(path, text)

    def _auto_save_pgn(self):
        screen = self.screen
        if not screen.match.move_history:
            return None
        tag = RESULT_CODES.get(self.app.current_result(), "*")
        if self._last_saved_pgn_path is not None:
            already_final = self._last_saved_result_tag not in (None, "*")
            if already_final:
                return self._last_saved_pgn_path
        text = self._build_pgn_text()
        prefix = self._auto_save_prefix()
        primary_dir = str(paths.get_games_dir())
        outcome = self._commit_pgn_write(primary_dir, prefix, text)
        if outcome == "hard_failure":
            self._show_save_error_toast_once()
            fallback_dir = str(paths.get_fallback_data_dir() / paths.GAMES_SUBDIR)
            if os.path.normpath(fallback_dir) == os.path.normpath(primary_dir):
                self._save_failed = True
                return None
            outcome = self._commit_pgn_write(fallback_dir, prefix, text)
            if outcome != "ok":
                self._save_failed = True
                return None
        if outcome != "ok":
            return None
        self._save_failed = False
        path = self._last_saved_pgn_path
        self._last_saved_result_tag = tag
        if tag != "*":
            self.app.toast.show(f"Saved {os.path.basename(path)}")
        return path

    def _auto_save_prefix(self):
        if self.app.mode == BOT:
            return "bot"
        return "online" if self.screen.variant == "online" else "local"

    def _update_incremental_autosave(self):
        screen = self.screen
        if (self.app.mode == "menu" or screen.pgn_review or self._save_failed
                or self.app.current_result() is not None):
            return
        ply_count = len(screen.match.move_history)
        if ply_count == 0 or ply_count == self._autosave_last_ply:
            return
        now = pg.time.get_ticks()
        if now - self._autosave_last_write_ms < AUTOSAVE_THROTTLE_MS:
            return
        self._autosave_last_write_ms = now
        self._autosave_last_ply = ply_count
        self._auto_save_pgn()

    def _on_result_final(self, code):
        if code is None:
            return
        if not self._series_score_awarded and self.app.mode == ONLINE:
            if code.startswith("white_wins"):
                self._award_series_win("white")
                self._series_score_awarded = True
            elif code.startswith("black_wins"):
                self._award_series_win("black")
                self._series_score_awarded = True
            elif code.startswith("draw"):
                self._award_series_draw()
                self._series_score_awarded = True
        path = None
        if not self._save_failed or self._final_save_attempted_for != code:
            self._final_save_attempted_for = code
            path = self._auto_save_pgn()
        if not self._result_logged:
            self._result_logged = True
            log.info("game end result=%s saved=%s", code, path or "false")

    def _finalize_result(self, code):
        screen = self.screen
        self._result_await_since_ms = None
        if screen.manual_result is None:
            screen.manual_result = code
        self._on_result_final(code)

    def _build_pgn_text(self):
        screen = self.screen
        result = self.app.current_result()
        time_control = screen._time_control
        return generate_pgn(
            screen.match.move_history, result,
            white_name=screen.white_name, black_name=screen.black_name,
            time_control=time_control,
            match_id=screen._match_session_id,
            annotations=format_annotations(screen.skillcheck_session._skillcheck_log),
        )
