import logging
import os
from datetime import datetime
from typing import Any

import pygame as pg

from chessshootout import paths
from chessshootout.domain.result_stats import compute_result_stats
from chessshootout.domain.pgn.generate import format_annotations, generate_pgn, RESULT_CODES
from chessshootout.backend.pieces import PieceColor
from chessshootout.frontend.game.variant import Variant
from chessshootout.frontend.pgn_open import NO_MOVES_MESSAGE


log = logging.getLogger("chess.frontend")

AUTOSAVE_THROTTLE_MS = 1000
RESULT_CONFIRM_TIMEOUT_MS = 4000
SAVE_ERROR_TOAST_KEY = "pgn_save_error"
GAMES_FOLDER_HINT = "check the games folder"
GAME_NOT_SAVED_MESSAGE = f"Game not saved — {GAMES_FOLDER_HINT}"
SAVE_FAILED_MESSAGE = f"Could not save PGN — {GAMES_FOLDER_HINT}"

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
    "aborted": ("Game aborted", "the opening was abandoned"),
    "server_shutdown": ("Game cancelled", "server shutting down"),
}


def score_str(score: float) -> str:
    """
    Write a series score the way players say it, with halves as the half
    symbol rather than a decimal, so a drawn series reads as one and a half
    instead of 1.5

    :param score: points won so far, counted in halves
    :returns: the score as it is shown on the result card and the rail
    """
    int_part = int(score)
    has_half = score - int_part >= 0.5 - 1e-9
    if int_part == 0 and has_half:
        return "½"
    if has_half:
        return f"{int_part}½"
    return str(int_part)


class ResultFlow:
    """
    Everything that happens once a game is decided, and the saving that leads
    up to it: it answers what the result is, dresses the result card, keeps the
    running series score for online games and writes the PGN. The PGN is
    autosaved continuously while a game runs and finished off at the end, so a
    crash or a quit still leaves a readable game on disk
    """

    def __init__(self, screen: Any) -> None:
        """
        Set the flow up for the life of the game screen. Only the series score
        is created here -- everything else belongs to a single game and is
        reset for each new one

        :param screen: the GameScreen this flow belongs to, and its only route
            to the match, the result card, toasts and the coordinator
        """
        self.screen = screen
        self.app = screen.app
        self.series_scores = {}
        self.reset_for_new_game()

    def reset_for_new_game(self) -> None:
        """
        Wipe every per-game latch back to its starting state: the result memo,
        the autosave throttle and file, the save-failure and toast latches and
        the once-only logging. The series score deliberately survives, since it
        is what makes a run of online games a series
        """
        self._result_cache_key = None
        self._result_cache = None
        self._series_score_awarded = False
        self._save_failed = False
        self._save_error_toast_shown = False
        self._save_dir = None
        self._autosave_last_write_ms = -AUTOSAVE_THROTTLE_MS
        self._autosave_last_ply = 0
        self._last_saved_pgn_path = None
        self._pgn_openable = False
        self._saved_final = False
        self._result_await_since_ms = None
        self._result_logged = False
        self._not_saved_notified = False
        self._final_save_attempted_for = None

    def current_result(self) -> str | None:
        """
        Say how the game stands, which is the one question the whole screen
        asks about whether it is over. A result somebody declared -- a
        resignation, a server verdict -- wins over the engine's reading, and
        the answer is memoised so the engine is not re-asked every frame

        :returns: the result code, or None while the game is still running
        """
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

    def result_text(self) -> tuple[str, str] | None:
        """
        Put the ending into words for the result card -- who won and by what

        :returns: the headline and the reason under it, or None while the game
            has no result or the code has no wording
        """
        code = self.screen.current_result()
        if code is None:
            return None
        return RESULT_TEXT.get(code)

    def feed_result_menu(self) -> None:
        """
        Fill the result card in for this frame: the verdict word, the reason
        and move count, the end-of-game statistics and, online, the running
        series score between these two players. The verdict is told from the
        local player's point of view, so the same mate reads as a victory on
        one screen and a defeat on the other
        """
        screen = self.screen
        code = screen.current_result()
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
        if screen.variant == Variant.ONLINE:
            screen.result_menu.set_series(
                screen.white_name, screen.black_name,
                score_str(self.series_scores.get(screen.white_name, 0.0)),
                score_str(self.series_scores.get(screen.black_name, 0.0)))
        else:
            screen.result_menu.set_series(None, None, None, None)

    def _perspective_color(self) -> PieceColor | None:
        """
        Name the side the person at this keyboard is playing, which is what
        turns a bare result into victory or defeat. In a local hotseat game
        both sides are played here, so there is no one point of view

        :returns: the local player's colour, or None in a hotseat game
        """
        if self.screen.variant in (Variant.ONLINE, Variant.BOT):
            return self.screen.match.local_color
        return None

    def _outcome_word_intent(self, code: str, title: str) -> tuple[str, str]:
        """
        Choose the big word on the result card and the mood it is drawn in.
        With a local player in the game a decisive result is theirs to win or
        lose; a hotseat game just names the winner

        :param code: result code for the ending
        :param title: neutral wording for it, used when there is no local side
        :returns: the word to shout and the mood -- win, loss or draw -- that
            colours the card
        """
        if code.startswith("draw"):
            return "DRAW", "draw"
        if not code.startswith(("white_wins", "black_wins")):
            return title.upper(), "draw"
        winner = PieceColor.WHITE if code.startswith("white_wins") else PieceColor.BLACK
        local = self._perspective_color()
        if local is not None:
            if winner == local:
                return "VICTORY", "win"
            return "DEFEAT", "loss"
        return title.upper(), "win"

    def _result_subject_color(self, code: str) -> PieceColor:
        """
        Pick the side the end-of-game statistics are told from -- KOs, streak,
        material and time left all belong to somebody. That is the local player
        when there is one, otherwise the winner, so a hotseat card reads as the
        winner's scoreboard

        :param code: result code for the ending
        :returns: the side the numbers are presented for
        """
        local = self._perspective_color()
        if local is not None:
            return local
        if code.startswith("black_wins"):
            return PieceColor.BLACK
        return PieceColor.WHITE

    def _move_visually_settled(self) -> bool:
        """
        Whether the last move has finished playing out on the board, animation
        and capture effects and all. The ending is only shown once it has, so
        the mating move is watched before the card covers it

        :returns: True when nothing is still moving on the board
        """
        board = self.screen.board
        return not board.is_animating() and not board.effects.captures

    def update_result_pending(self) -> None:
        """
        Run the result side of a frame: keep the autosave ticking, and once
        there is a result, adopt it and start the ending sequence. Online the
        server has the last word, so an engine result is only shown as its own
        after a short wait for the server to confirm it, and nothing is adopted
        at all while a resync is in flight
        """
        screen = self.screen
        self._update_incremental_autosave()
        result = screen.current_result()
        if result is None:
            screen._result_first_seen_at_ms = None
            self._result_await_since_ms = None
            return
        if screen.variant == Variant.ONLINE and screen.manual_result is None:
            if not self.app.coordinator._resyncing:
                self._promote_awaited_result(result)
            return
        if screen.variant == Variant.ONLINE and self.app.coordinator._resyncing:
            return
        self.on_result_final(result)
        if screen._result_first_seen_at_ms is None and self._move_visually_settled():
            screen._result_first_seen_at_ms = pg.time.get_ticks()
            try:
                screen._trigger_result_effects()
            except Exception:
                log.exception("result effects failed")

    def _promote_awaited_result(self, engine_result: str) -> None:
        """
        Adopt an ending the local engine can see but the server has not
        confirmed, once the wait has gone on too long. It is the safety net for
        a lost result message: the player is not left staring at a finished
        position wondering whether the game noticed

        :param engine_result: the result code the engine reads on this board
        """
        now = pg.time.get_ticks()
        if self._result_await_since_ms is None:
            self._result_await_since_ms = now
            return
        if now - self._result_await_since_ms < RESULT_CONFIRM_TIMEOUT_MS:
            return
        self.finalize_result(engine_result)
        log.info("promoted unconfirmed online result locally: %s", engine_result)

    def _award_series_win(self, winner: str) -> None:
        """
        Give the winner their point in the running series, which exists only in
        online games and is kept per player name

        :param winner: colour that won, as white or black
        """
        name = self.screen._name_for_color(winner)
        self.series_scores[name] = self.series_scores.get(name, 0.0) + 1

    def _award_series_draw(self) -> None:
        """
        Split the point between both players for a drawn game, the other half
        of how an online series is scored
        """
        for name in (self.screen.white_name, self.screen.black_name):
            self.series_scores[name] = self.series_scores.get(name, 0.0) + 0.5

    def on_open_pgn(self) -> None:
        """
        Open the saved game in whatever app handles PGN files, from the result
        card's Open PGN button. A game with no file behind it explains itself:
        either it was never saved, or there were no moves to save
        """
        empty_message = (GAME_NOT_SAVED_MESSAGE if self.screen.match.move_history
                         else NO_MOVES_MESSAGE)
        self.app.pgn_opener.open(self._last_saved_pgn_path, empty_message=empty_message)

    def pgn_available(self) -> bool:
        """
        Whether there is a saved file worth opening, which is what decides if
        the result card offers an Open PGN button at all

        :returns: True once a PGN with moves in it has been written
        """
        return self._pgn_openable

    def probe_games_dir_writable(self) -> None:
        """
        Check at startup that saved games have somewhere to go, and warn the
        player now rather than at the end of a game they would then lose. The
        folder is created if it is missing and genuinely written to, not just
        inspected
        """
        games_dir = str(paths.get_games_dir())
        try:
            os.makedirs(games_dir, exist_ok=True)
        except OSError:
            self.app.toast.show("Games folder isn't writable — check your data folder")
            return
        if not paths.is_writable_dir(games_dir):
            self.app.toast.show("Games folder isn't writable — check your data folder")

    def _show_save_error_toast_once(self) -> None:
        """
        Complain about a failed save exactly once per game. The autosave runs
        every second or so, and a broken folder would otherwise raise the same
        toast over and over for the rest of the game
        """
        if self._save_error_toast_shown:
            return
        self._save_error_toast_shown = True
        self.app.toast.show(SAVE_FAILED_MESSAGE, key=SAVE_ERROR_TOAST_KEY)

    def _remove_quietly(self, path: str) -> None:
        """
        Delete a file that is only in the way -- a temporary write, or a
        reservation nothing was ever written into -- without letting the
        cleanup itself become a second failure

        :param path: file to remove; a missing or locked file is ignored
        """
        try:
            os.remove(path)
        except OSError:
            pass

    def _reserve_pgn_path(self, directory: str, prefix: str) -> str | None:
        """
        Claim the file this game will be written to, named for the variant and
        the moment it started. The name is taken by creating the file
        exclusively, so two games starting in the same second cannot end up
        writing over each other

        :param directory: folder to save into, created when missing
        :param prefix: leading part of the name, the game's variant
        :returns: the reserved path, or None when the folder or the name could
            not be had
        """
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

    def _write_pgn_atomic(self, path: str, text: str) -> str:
        """
        Replace the saved game in one step, by writing a temporary file beside
        it and moving that over the top. A crash mid-write therefore leaves the
        previous good copy rather than half a game, which matters because this
        runs over and over while the game is played

        :param path: file the game is saved as
        :param text: complete PGN document to store
        :returns: ok, permission_transient when something else briefly held the
            file, or hard_failure when the save really did not happen
        """
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

    def _commit_pgn_write(self, directory: str, prefix: str, text: str) -> str:
        """
        Write this game to its file, reserving one the first time and reusing
        it for every later write, so a whole game is one file rather than a
        pile of snapshots. A failed first write takes its own orphan file back
        out again

        :param directory: folder to save into
        :param prefix: leading part of the name, the game's variant
        :param text: complete PGN document to store
        :returns: ok, permission_transient or hard_failure, as the write
            reported it
        """
        path = self._last_saved_pgn_path
        reserved = False
        if path is None or os.path.dirname(path) != os.path.normpath(directory):
            path = self._reserve_pgn_path(directory, prefix)
            if path is None:
                return "hard_failure"
            reserved = True
            self._last_saved_pgn_path = path
        outcome = self._write_pgn_atomic(path, text)
        if outcome == "ok" and text:
            self._pgn_openable = True
        if outcome == "hard_failure" and reserved:
            self._remove_quietly(path)
            self._last_saved_pgn_path = None
            self._pgn_openable = False
        return outcome

    def auto_save_pgn(self) -> str | None:
        """
        Save the game as it currently stands, which is what both the running
        autosave and the final save call. A live game is written with an open
        result of * and rewritten each time, and once the finished game has
        been stored it is never written again. A folder that refuses the game
        is toasted once and retried in the per-user data folder, so a bad data
        directory does not cost the player their game

        :returns: the path the game was saved as, or None when it could not be
            saved or there were no moves to save
        """
        screen = self.screen
        if not screen.match.move_history:
            return None
        result = screen.current_result()
        if self._last_saved_pgn_path is not None and self._saved_final:
            return self._last_saved_pgn_path
        tag = RESULT_CODES.get(result, "*")
        text = self._build_pgn_text()
        prefix = self._auto_save_prefix()
        primary_dir = self._save_dir or str(paths.get_games_dir())
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
            self._save_dir = fallback_dir
        if outcome != "ok":
            return None
        self._save_failed = False
        path = self._last_saved_pgn_path
        self._saved_final = result is not None
        if tag != "*":
            self.app.toast.show(f"Saved {os.path.basename(path)}")
        return path

    def _auto_save_prefix(self) -> str:
        """
        Name the saved file after the kind of game it was, so the history list
        shows local, bot and online games apart at a glance

        :returns: the leading part of the file name
        """
        return self.screen.variant

    def _update_incremental_autosave(self) -> None:
        """
        Keep the running game on disk while it is played, writing at most once
        a second and only when another ply has actually been made. A finished
        game is left to the final save, a game whose folder has already refused
        it is not hammered, and a screen the player has walked away from stops
        writing
        """
        screen = self.screen
        if (self.app.screen is not screen or self._save_failed
                or screen.current_result() is not None):
            return
        ply_count = len(screen.match.move_history)
        if ply_count == 0 or ply_count == self._autosave_last_ply:
            return
        now = pg.time.get_ticks()
        if now - self._autosave_last_write_ms < AUTOSAVE_THROTTLE_MS:
            return
        self._autosave_last_write_ms = now
        self._autosave_last_ply = ply_count
        self.auto_save_pgn()

    def on_result_final(self, code: str | None) -> None:
        """
        The single point where a game is adopted as over, whoever noticed
        first: the series score is awarded here and the finished game is saved
        here, exactly once per result. Every route in -- the engine, a
        resignation, the server, the walk back to the menu, the quit -- comes
        through this one door, and the save-failure latch never blocks this
        attempt, so a game that could not be autosaved still gets one honest
        try at the end. A game that still could not be saved says so plainly

        :param code: result code being adopted, None while the game is live
        """
        if code is None:
            return
        if not self._series_score_awarded and self.screen.variant == Variant.ONLINE:
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
        if self.screen.match.move_history and self._final_save_attempted_for != code:
            self._final_save_attempted_for = code
            path = self.auto_save_pgn()
        if not self._result_logged:
            self._result_logged = True
            log.info("game end result=%s saved=%s", code, self._save_state_str(path))
        if (self.screen.match.move_history and not self.pgn_available()
                and not self._not_saved_notified):
            self._not_saved_notified = True
            self.app.toast.dismiss(SAVE_ERROR_TOAST_KEY)
            self.app.toast.show(GAME_NOT_SAVED_MESSAGE, key=SAVE_ERROR_TOAST_KEY)

    def _save_state_str(self, path: str | None) -> str:
        """
        Say how the final save went for the one game-end log line, telling a
        game nobody could save apart from one there was nothing to save

        :param path: file the game was saved as, None when it was not
        :returns: the saved path, or a short reason it was skipped or failed
        """
        if path is not None:
            return path
        if not self.screen.match.move_history:
            return "skipped reason=no_moves"
        return "failed"

    def finalize_result(self, code: str) -> None:
        """
        Settle a result that has to stick, used when the player leaves a
        finished game and when an unconfirmed online ending is adopted. The
        code is written onto the screen as its declared result, so the engine
        cannot read the position differently afterwards, and the ending is then
        put through the single result choke point

        :param code: result code to settle on
        """
        screen = self.screen
        self._result_await_since_ms = None
        if screen.manual_result is None:
            screen.manual_result = code
        self.on_result_final(code)

    def _build_pgn_text(self) -> str:
        """
        Write the game out as PGN text, players, time control and match id
        included, with the shootout log attached as move comments. Notation
        comes from the moves as they were recorded and is never worked out
        again here

        :returns: the complete PGN document for the game as it stands
        """
        screen = self.screen
        result = screen.current_result()
        time_control = screen._time_control
        return generate_pgn(
            screen.match.move_history, result,
            white_name=screen.white_name, black_name=screen.black_name,
            time_control=time_control,
            match_id=screen._match_session_id,
            annotations=format_annotations(screen.skillcheck_session.skillcheck_log),
        )
