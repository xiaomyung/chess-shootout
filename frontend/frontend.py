import glob
import logging
import os
import random
import threading
from datetime import datetime

import pygame as pg

from backend.fen import apply_fen
from backend.match import Match, SINGLE_SCREEN, BOT, ONLINE
from backend.utils import PROMO_TYPE_BY_LETTER, coord_from_square, square_from_coord
from frontend import env
from frontend.audio_panel import AudioPanel
from frontend.board import Board
from frontend.capture_summary import captured_by, material_advantage
from frontend.confirm_modal import ConfirmModal
from frontend.file_picker import FilePicker
from frontend.online_client import OnlineClient, fetch_resume, probe_active_game
from frontend.player_strip import PlayerStrip
from frontend.server_modal import ServerAddressModal
from frontend.wait_modal import WaitModal
from frontend.right_menu import RightMenu, BUTTONS as RIGHT_MENU_BUTTONS, REVIEW_BUTTONS as RIGHT_MENU_REVIEW_BUTTONS
from frontend.result_menu import ResultMenu
from frontend.sound_manager import SoundManager
from frontend.start_menu import StartMenu
from frontend.pgn import generate_pgn, TIMEOUT_RESULTS
from frontend.pgn_load import load_pgn_into_backend
from backend.paths import PROJECT_ROOT, SOUNDS_DIR
from backend.pieces import PieceColor, PieceType, opponent_of


MANUAL_RESULT_TEXT = {
    "white_wins": ("White wins", "by resignation"),
    "black_wins": ("Black wins", "by resignation"),
    "draw_agreement": ("Draw", "by agreement"),
    "aborted": ("Game aborted", "no moves played"),
    "server_shutdown": ("Game cancelled", "server shutting down"),
}

ENGINE_RESULT_TEXT = {
    "white_wins": ("White wins", "by checkmate"),
    "black_wins": ("Black wins", "by checkmate"),
    "draw_stalemate": ("Draw", "by stalemate"),
    "draw_repetition": ("Draw", "by threefold repetition"),
    "draw_fifty_move": ("Draw", "by fifty-move rule"),
    "draw_insufficient_material": ("Draw", "by insufficient material"),
    "white_wins_on_time": ("White wins", "on time"),
    "black_wins_on_time": ("Black wins", "on time"),
}

OPPONENT_NAME_FOR_MODE = {
    SINGLE_SCREEN: "Player 2",
    BOT: "AI Bot",
    ONLINE: "Opponent",
}

ONLINE_WIN_REASONS = {"checkmate", "timeout", "resignation", "abandonment"}
ONLINE_DRAW_REASONS = {
    "draw_agreement", "draw_stalemate", "draw_repetition",
    "draw_fifty_move", "draw_insufficient_material",
}
ONLINE_STATIC_RESULTS = {"aborted", "server_shutdown"}

AUTO_FLIP_DELAY_MS = 200

MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 500

log = logging.getLogger("chess.frontend")


class Frontend:

    def __init__(self, window_width: int, window_height: int):
        self.running = True
        self.target_fps = 60
        self.window_width = max(window_width, MIN_WINDOW_WIDTH)
        self.window_height = max(window_height, MIN_WINDOW_HEIGHT)
        self.window = pg.display.set_mode((self.window_width, self.window_height), pg.RESIZABLE)
        self.clock = pg.time.Clock()

        self.mode = "menu"
        self.manual_result = None
        self._last_turn_for_flip = None
        self.white_name = "Player 1"
        self.black_name = "Player 2"
        self._chosen_side = "white"
        self._time_control = None
        self.pgn_review = False
        self._flag_fall_played = False

        self.match = Match()
        self.sound_manager = SoundManager(SOUNDS_DIR, enabled=pg.mixer.get_init() is not None)
        self.board = Board(self.window, self.match,
                           move_landed_callback=self._on_move_landed,
                           on_premove_queued=self.sound_manager.play_premove_queued)
        self.result_menu = ResultMenu(self.window, {
            "new_game": self._on_new_game,
            "save_pgn": self._on_save_pgn,
            "menu": self._on_back_to_menu,
            "rematch": self._on_rematch,
        })
        self.start_menu = StartMenu(self.window, {
            "start_game": self._on_start_game,
            "load_pgn": self._on_load_last_game,
            "reconnect": self._on_reconnect_active_game,
        })
        self._pending_reconnect = None
        self._pending_reconnect_lock = threading.Lock()
        self.audio_panel = AudioPanel(self.window, self.sound_manager)
        self.right_menu = RightMenu(self.window, self.match, {
            "undo": self._on_undo,
            "resign": self._on_resign,
            "draw": self._on_draw,
            "flip": self._on_flip,
            "menu": self._on_back_to_menu,
        }, board=self.board, buttons_provider=self._right_menu_buttons,
            audio_panel=self.audio_panel)
        self.confirm_modal = ConfirmModal(self.window)
        self.file_picker = FilePicker(self.window)
        self.server_modal = ServerAddressModal(self.window)
        self.wait_modal = WaitModal(self.window)
        self.online_client = None
        self.player_strip_top = PlayerStrip(self.window)
        self.player_strip_bottom = PlayerStrip(self.window)

        self.match.new_game()
        self.board.load_assets()
        self._compute_layout()
        self._refresh_load_pgn_availability()
        self._spawn_reconnect_probe()

        pg.display.set_caption("Chess")

    @property
    def backend(self):
        return self.match.backend

    def current_result(self):
        return self.manual_result or self.match.game_result()

    def result_text(self):
        if self.manual_result is not None:
            return MANUAL_RESULT_TEXT.get(self.manual_result)
        engine = self.match.game_result()
        if engine is None:
            return None
        return ENGINE_RESULT_TEXT.get(engine)

    def _on_new_game(self):
        self._reset_to_new_game()
        self.sound_manager.play_game_start()

    def _on_back_to_menu(self):
        self.mode = "menu"
        pg.display.set_caption("Chess")
        if self.online_client is not None:
            self.online_client.disconnect()
            self.online_client = None
        self.match.mode = SINGLE_SCREEN
        self.match.local_color = None
        self.match.on_local_move_applied = None
        self.right_menu.set_game_info(None)
        self.result_menu.set_online_mode(False)
        self._reset_to_new_game()
        self._refresh_load_pgn_availability()
        self.start_menu.show()

    def _refresh_load_pgn_availability(self):
        self.start_menu.load_pgn_available = self._latest_pgn_path() is not None

    def _latest_pgn_path(self):
        pattern = os.path.join(PROJECT_ROOT, "games", "game-*.pgn")
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    def _on_load_last_game(self):
        games_dir = os.path.join(PROJECT_ROOT, "games")
        self.file_picker.show(
            games_dir, "*.pgn",
            on_select=self._load_pgn_from_path,
        )

    def _load_pgn_from_path(self, path):
        with open(path) as f:
            text = f.read()
        self.mode = SINGLE_SCREEN
        self._time_control = None
        self._reset_to_new_game()
        _, ok = load_pgn_into_backend(self.match, text)
        if not ok:
            return
        if self.match.move_history:
            self.board.review_ply = 0
        self.pgn_review = True
        self.board.read_only = True
        self.start_menu.hide()

    def _spawn_reconnect_probe(self):
        addr = env.get_server_addr()
        client_uuid = env.get_or_create_client_uuid()
        if not addr or not client_uuid:
            return
        thread = threading.Thread(
            target=self._reconnect_probe_worker,
            args=(addr, client_uuid),
            daemon=True,
        )
        thread.start()

    def _reconnect_probe_worker(self, addr, client_uuid):
        reclaim = probe_active_game(addr, client_uuid)
        if reclaim is None:
            return
        resume = fetch_resume(addr, reclaim["room_id"], reclaim["session_token"])
        if resume is None:
            return
        with self._pending_reconnect_lock:
            self._pending_reconnect = {
                "addr": addr,
                "room_id": reclaim["room_id"],
                "session_token": reclaim["session_token"],
                "resume": resume,
            }

    def _refresh_reconnect_button(self):
        with self._pending_reconnect_lock:
            available = self._pending_reconnect is not None
        self.start_menu.set_reconnect_available(available)

    def _on_reconnect_active_game(self):
        with self._pending_reconnect_lock:
            pending = self._pending_reconnect
            self._pending_reconnect = None
        if pending is None:
            return
        self.start_menu.set_reconnect_available(False)
        resume = pending["resume"]
        nickname = (resume["white_name"] if resume["your_color"] == "white"
                    else resume["black_name"])
        self.start_menu.text_input.text = nickname
        self.start_menu.selected_mode = ONLINE
        self.start_menu.selected_time_minutes = resume["time_minutes"]
        self.start_menu.selected_increment_seconds = resume["increment_seconds"]
        self.start_menu.selected_side = resume["your_color"]
        self.online_client = OnlineClient()
        self.match.on_local_move_applied = self._on_local_move_applied
        self.online_client.reconnect_to_existing(
            pending["addr"], pending["room_id"], pending["session_token"], resume,
        )
        self.start_menu.hide()

    def _on_start_game(self, config):
        env.set_last_mode(config["mode"])
        if config["mode"] == ONLINE:
            self._begin_online_flow(config)
            return
        if config["mode"] != SINGLE_SCREEN:
            return

        self.mode = SINGLE_SCREEN

        side = config["side"]
        if side == "random":
            side = random.choice(["white", "black"])
        self._chosen_side = side

        nickname = (config.get("nickname") or "").strip() or "Player 1"
        opponent_name = OPPONENT_NAME_FOR_MODE[config["mode"]]
        self.white_name, self.black_name = (
            (nickname, opponent_name) if side == "white"
            else (opponent_name, nickname)
        )

        self._time_control = (
            (config["time_minutes"] * 60, config["increment_seconds"])
            if config["time_minutes"] is not None else None
        )

        self._reset_to_new_game()
        self.start_menu.hide()
        self.sound_manager.play_game_start()

    def _begin_online_flow(self, config):
        log.info("online flow begin tc=%s+%s side=%s",
                 config.get("time_minutes"), config.get("increment_seconds"),
                 config.get("side"))
        self._online_config = config
        self.start_menu.hide()
        self.server_modal.show(
            prefilled=env.get_server_addr(),
            on_connect=self._on_server_addr_connect,
            on_cancel=self._on_online_cancel,
        )

    def _on_server_addr_connect(self, addr):
        log.info("connect to %s", addr)
        if not addr:
            self._on_online_cancel()
            return
        self.online_client = OnlineClient()
        request = {
            "nickname": (self._online_config.get("nickname") or "").strip() or "Player",
            "client_uuid": env.get_or_create_client_uuid(),
            "time_minutes": self._online_config["time_minutes"] or 5,
            "increment_seconds": self._online_config["increment_seconds"],
            "side_preference": self._online_config["side"],
        }
        self.online_client.connect(addr, request)
        self.wait_modal.show("Searching for opponent…", self._on_online_cancel)

    def _on_online_cancel(self):
        log.info("online flow cancel")
        if self.online_client is not None:
            self.online_client.cancel_queue()
            self.online_client = None
        self.match.on_local_move_applied = None
        self.right_menu.set_game_info(None)
        self.server_modal.hide()
        self.wait_modal.hide()
        self.mode = "menu"
        self.start_menu.show()

    def _drain_online_inbound(self):
        if self.online_client is None:
            return
        for event in self.online_client.drain_inbound():
            try:
                self._handle_online_event(event)
            except Exception:
                log.exception("online event handler failed")

    def _handle_online_event(self, event):
        if event.type == "matchmake_response":
            return
        elif event.type == "game_start":
            self._start_online_game(event.payload)
        elif event.type == "move_applied":
            self._handle_remote_move_applied(event.payload)
        elif event.type == "result":
            self._handle_online_result(event.payload)
        elif event.type == "draw_offered":
            self._show_opp_offer_modal(
                "Opponent offers a draw", self.online_client.send_draw_response,
            )
        elif event.type == "takeback_offered":
            self._show_opp_offer_modal(
                "Opponent requests a takeback",
                self.online_client.send_takeback_response,
            )
        elif event.type == "takeback_applied":
            self._handle_takeback_applied(event.payload)
        elif event.type == "rematch_request":
            self._show_opp_offer_modal(
                "Opponent wants a rematch",
                self.online_client.send_rematch_response,
            )
        elif event.type == "game_resumed":
            self._handle_game_resumed(event.payload)
        elif event.type == "connection_status":
            return
        elif event.type == "error":
            reason = event.payload.get("reason", "")
            game_state_reasons = {
                "not_your_turn", "invalid_move_format", "invalid_message",
                "version_mismatch",
            }
            if reason in game_state_reasons:
                return
            self.wait_modal.hide()
            self.confirm_modal.show(
                reason or "Server unreachable",
                on_yes=lambda: self._on_server_addr_connect(env.get_server_addr()),
                on_no=self._on_online_cancel,
                yes_label="Retry", no_label="Cancel",
            )

    def _show_opp_offer_modal(self, title, send_response):
        self.confirm_modal.show(
            title,
            on_yes=lambda: send_response(True),
            on_no=lambda: send_response(False),
            yes_label="Accept", no_label="Decline",
        )

    def _apply_clock_snap(self, payload, *, default_to_existing):
        clock_snap = payload.get("clock") or {}
        if self.match.clock is None:
            return
        if default_to_existing:
            white_default = self.match.clock.white_remaining
            black_default = self.match.clock.black_remaining
        else:
            white_default = 0.0
            black_default = 0.0
        self.match.clock.restore_from_server(
            clock_snap.get("white_remaining", white_default),
            clock_snap.get("black_remaining", black_default),
            clock_snap.get("running_for"),
        )

    def _handle_game_resumed(self, payload):
        self.match.new_game()
        for entry in payload.get("move_history", []):
            result = self.match.backend.apply_san(entry["san"])
            if not result.legal:
                log.warning("resume: SAN replay failed at %r", entry.get("san"))
                apply_fen(self.match.backend, payload["fen"])
                break
        if self._time_control is not None:
            initial, incr = self._time_control
            self.match.setup_clock(initial, incr)
            self._apply_clock_snap(payload, default_to_existing=False)
        self.board.cancel_animations()
        self.board.selected_square = None
        self.board._clear_premoves()
        self.board.clear_annotations()

    def _handle_takeback_applied(self, payload):
        if self.match.move_history:
            last = self.match.move_history[-1].move
            self.match.undo()
            self.board.start_undo_animation(last)
        self._apply_clock_snap(payload, default_to_existing=True)

    def _handle_remote_move_applied(self, payload):
        self._apply_clock_snap(payload, default_to_existing=True)
        san = payload.get("san")
        last = self.match.move_history[-1] if self.match.move_history else None
        if last is not None and last.san == san:
            return
        from_sq = square_from_coord(payload["from"])
        to_sq = square_from_coord(payload["to"])
        promo = payload.get("promotion")
        promo_type = PROMO_TYPE_BY_LETTER.get(promo) if promo else None
        result = self.match.apply_remote_move(from_sq, to_sq, promo_type)
        if result.legal:
            self.board.animate_remote_move(from_sq, to_sq)

    def _handle_online_result(self, payload):
        reason = payload.get("reason", "")
        winner = payload.get("winner_color")
        if reason in ONLINE_WIN_REASONS:
            self.manual_result = "white_wins" if winner == "white" else "black_wins"
        elif reason in ONLINE_DRAW_REASONS:
            self.manual_result = "draw_agreement"
        elif reason in ONLINE_STATIC_RESULTS:
            self.manual_result = reason
        if self.manual_result is not None:
            if reason == "timeout":
                self.sound_manager.play_flag_fall()
            self._auto_save_online_pgn()

    def _on_rematch(self):
        if self.online_client is None:
            return
        self.online_client.send_rematch_request()

    def _start_online_game(self, payload):
        opp_name = (payload.get("white_name") if payload.get("your_color") == "black"
                    else payload.get("black_name"))
        log.info("game start as %s vs %s", payload.get("your_color"), opp_name)
        pg.display.set_caption(f"Chess — vs {opp_name}")
        self.wait_modal.hide()
        self.confirm_modal.hide()
        self.manual_result = None
        self.result_menu.set_online_mode(True)
        self.mode = ONLINE
        self._online_initial_flip = (payload["your_color"] == "black")
        self._chosen_side = payload["your_color"]
        self.white_name = payload["white_name"]
        self.black_name = payload["black_name"]
        self._time_control = (payload["time_minutes"] * 60,
                              payload["increment_seconds"])
        self.match.mode = ONLINE
        self.match.local_color = (PieceColor.WHITE if payload["your_color"] == "white"
                                  else PieceColor.BLACK)
        self.match.on_local_move_applied = self._on_local_move_applied
        self.right_menu.set_game_info({
            "white_name": payload["white_name"],
            "black_name": payload["black_name"],
            "time_minutes": payload["time_minutes"],
            "increment_seconds": payload["increment_seconds"],
            "ping_ms": None,
        })
        self._reset_to_new_game()
        self.board.flipped = self._online_initial_flip
        self.sound_manager.play_online_game_start()

    def _on_local_move_applied(self, from_sq, to_sq, promotion):
        if self.online_client is None:
            return
        self.online_client.send_move(coord_from_square(from_sq), coord_from_square(to_sq), promotion)

    def _right_menu_buttons(self):
        if self.pgn_review:
            return RIGHT_MENU_REVIEW_BUTTONS
        return RIGHT_MENU_BUTTONS

    def _reset_to_new_game(self):
        self.pgn_review = False
        self.board.read_only = False
        self.sound_manager.stop_all()
        self.manual_result = None
        self._flag_fall_played = False
        self.match.new_game()
        if self._time_control is not None:
            initial, incr = self._time_control
            self.match.setup_clock(initial, incr)
        self.board.flipped = False
        self.board.selected_square = None
        self.board.pending_promotion_square = None
        self.board.cancel_animations()
        self.board._clear_premoves()
        self.board.clear_annotations()
        self.board.end_press()
        self.board.review_ply = None
        self.confirm_modal.hide()
        self._last_turn_for_flip = None

    def _on_save_pgn(self):
        self._write_pgn(prefix="game")

    def _auto_save_online_pgn(self):
        if not self.match.move_history:
            return
        self._write_pgn(prefix="online")

    def _write_pgn(self, prefix):
        result = self.current_result()
        if result is None:
            return
        games_dir = os.path.join(PROJECT_ROOT, "games")
        os.makedirs(games_dir, exist_ok=True)
        filename = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pgn"
        path = os.path.join(games_dir, filename)
        time_control = self._time_control
        termination = "Time forfeit" if result in TIMEOUT_RESULTS else None
        with open(path, "w") as f:
            f.write(generate_pgn(
                self.match.move_history, result,
                white_name=self.white_name, black_name=self.black_name,
                time_control=time_control, termination=termination,
            ))

    def _on_undo(self):
        if self.pgn_review:
            return
        if self.mode == ONLINE and self.online_client is not None:
            self.online_client.send_takeback_request()
            return
        self.board.selected_square = None
        self.board._clear_premoves()
        self.board.clear_annotations()
        self.board.review_ply = None
        if self.manual_result is not None:
            self.manual_result = None
            return
        self.board.cancel_animations()
        if not self.match.move_history:
            return
        self.sound_manager.play_undo()
        move = self.match.move_history[-1].move
        self.match.undo()
        self.board.start_undo_animation(move)

    def _on_resign(self):
        if self.pgn_review or self.current_result() is not None:
            return
        self.confirm_modal.show(
            "Resign?", on_yes=self._perform_resign, yes_label="Resign",
        )

    def _perform_resign(self):
        if self.current_result() is not None:
            return
        if self.mode == ONLINE and self.online_client is not None:
            self.online_client.send_resign()
            return
        loser = self.match.current_turn()
        self._auto_complete_pending_promotion()
        self.manual_result = "black_wins" if loser == PieceColor.WHITE else "white_wins"
        self.board._clear_premoves()
        self.board.clear_annotations()

    def _on_draw(self):
        if self.pgn_review or self.current_result() is not None:
            return
        self.confirm_modal.show(
            "Offer draw?", on_yes=self._perform_draw, yes_label="Draw",
        )

    def _perform_draw(self):
        if self.current_result() is not None:
            return
        if self.mode == ONLINE and self.online_client is not None:
            self.online_client.send_draw_offer()
            return
        self._auto_complete_pending_promotion()
        self.manual_result = "draw_agreement"
        self.board._clear_premoves()
        self.board.clear_annotations()

    def _auto_complete_pending_promotion(self):
        if self.board.pending_promotion_square is None:
            return
        self.match.promote(self.board.pending_promotion_square, PieceType.QUEEN)
        self.board.pending_promotion_square = None

    def _on_flip(self):
        self.board.flipped = not self.board.flipped

    def _on_move_landed(self, entry):
        if entry.gives_checkmate:
            self.sound_manager.play_checkmate()
        elif entry.move.is_castle:
            self.sound_manager.play_castle()
        else:
            self.sound_manager.play_move()
        if entry.move.captured is not None:
            self.sound_manager.play_capture(entry.move.piece.type)
        if entry.gives_check and not entry.gives_checkmate:
            self.sound_manager.play_check()
        self._maybe_flash_increment_for(entry.move.piece.color)

    def _maybe_flash_increment_for(self, mover_color):
        clock = self.match.clock
        if clock is None or clock.increment_seconds <= 0:
            return
        mover_strip = (self.player_strip_top
                       if self._strip_color_top() == mover_color
                       else self.player_strip_bottom)
        mover_strip.flash_increment()

    def _strip_color_top(self):
        return PieceColor.WHITE if self.board.flipped else PieceColor.BLACK

    def run(self):
        while self.running:
            self.check_events()
            self.window.fill("black")
            self.draw_frame()
            self.clock.tick(self.target_fps)
            pg.display.flip()

        pg.quit()

    def draw_frame(self):
        if self.mode != "menu" and self.current_result() is None:
            self.match.tick_clock()

        self._maybe_play_flag_fall()
        self._update_heartbeat()

        now = pg.time.get_ticks()
        post_animation_settled = (
            not self.board.is_animating()
            and now - self.board.last_animation_completed_at_ms >= AUTO_FLIP_DELAY_MS
        )
        if (self.mode == SINGLE_SCREEN
                and self.current_result() is None
                and post_animation_settled):
            current = self.match.current_turn()
            if current != self._last_turn_for_flip:
                self.board.flipped = (current == PieceColor.BLACK)
                self._last_turn_for_flip = current

        if (self.mode != "menu"
                and self.current_result() is None
                and post_animation_settled):
            self.board.try_apply_next_premove()

        self.board.draw_board()
        if self.mode != "menu":
            self._update_player_strips()
            self.player_strip_top.draw()
            self.player_strip_bottom.draw()
            self.right_menu.draw_menu()
            self.result_menu.set_text(self.result_text())
            self.result_menu.draw()
            self.confirm_modal.draw()
        self._refresh_reconnect_button()
        self.start_menu.draw()
        self.file_picker.draw()
        self.server_modal.draw()
        self.wait_modal.draw()
        self._drain_online_inbound()

    def _update_player_strips(self):
        top_color = PieceColor.WHITE if self.board.flipped else PieceColor.BLACK
        bottom_color = PieceColor.BLACK if self.board.flipped else PieceColor.WHITE
        turn = self.match.current_turn()
        over = self.current_result() is not None
        self.player_strip_top.set_state(**self._strip_state(top_color, turn, over))
        self.player_strip_bottom.set_state(**self._strip_state(bottom_color, turn, over))

    def _maybe_play_flag_fall(self):
        if self._flag_fall_played or self.mode == "menu":
            return
        clock = self.match.clock
        if clock is None or clock.flagged is None:
            return
        self.sound_manager.play_flag_fall()
        self._flag_fall_played = True

    def _update_heartbeat(self):
        clock = self.match.clock
        paused = (self.mode == "menu"
                  or self.current_result() is not None
                  or clock is None)
        if paused or clock.initial_seconds <= 0:
            fraction = None
        else:
            fraction = clock.remaining(self.match.current_turn()) / clock.initial_seconds
        self.sound_manager.update_heartbeat(fraction, paused)

    def _strip_state(self, color, turn, over):
        name = self.white_name if color == PieceColor.WHITE else self.black_name
        seconds = (self.match.clock.remaining(color)
                   if self.match.clock is not None else None)
        initial_seconds = (self.match.clock.initial_seconds
                           if self.match.clock is not None else None)
        active = (color == turn) and not over
        history = self.match.move_history
        if self.board.review_ply is not None:
            history = history[:self.board.review_ply]
        captured = captured_by(history, color)
        advantage = material_advantage(history, color)
        connection_state = None
        if (self.mode == ONLINE and self.online_client is not None
                and self.match.local_color is not None
                and color != self.match.local_color):
            connection_state = self.online_client.opp_state
        return {
            "name": name,
            "clock_seconds": seconds,
            "active": active,
            "captured": captured,
            "advantage": advantage,
            "captured_color": opponent_of(color),
            "connection_state": connection_state,
            "clock_initial_seconds": initial_seconds,
        }

    def _compute_layout(self):
        window_width, window_height = self.window.get_size()
        effective = max(min(window_width, window_height), 300)
        board_size_px = effective * self.board.SCREEN_FRACTION_X

        board_x = board_size_px * self.board.OFFSET_FRACTION_X
        board_y = window_height / 2 - board_size_px / 2

        board_rect = pg.Rect(
            board_x,
            board_y,
            board_size_px,
            board_size_px
        )

        cell_size = board_size_px / self.board.SIZE
        result_width = cell_size * 3.5
        result_height = cell_size * 2.5
        result_rect = pg.Rect(
            board_x + board_size_px / 2 - result_width / 2,
            board_y + board_size_px / 2 - result_height / 2,
            result_width,
            result_height
        )
        wait_width = max(result_width, 360)
        wait_height = max(cell_size * 1.6, 200)
        wait_rect = pg.Rect(
            board_x + board_size_px / 2 - wait_width / 2,
            board_y + board_size_px / 2 - wait_height / 2,
            wait_width,
            wait_height,
        )

        start_width = board_size_px * 0.7
        start_height = board_size_px * 0.7
        start_rect = pg.Rect(
            board_x + board_size_px / 2 - start_width / 2,
            board_y + board_size_px / 2 - start_height / 2,
            start_width,
            start_height
        )

        menu_rect = pg.Rect(
            board_rect.right,
            0,
            max(window_width - board_rect.right, 300),
            max(window_height, 500)
        )

        strip_height = board_size_px * 0.075
        strip_gap = board_size_px * 0.015
        top_strip_rect = pg.Rect(
            board_x,
            board_y - strip_height - strip_gap,
            board_size_px,
            strip_height,
        )
        bottom_strip_rect = pg.Rect(
            board_x,
            board_y + board_size_px + strip_gap,
            board_size_px,
            strip_height,
        )

        self.board.font = pg.font.SysFont(
            "Arial",
            int(effective // self.board.board_guides_font_factor),
            bold=True
        )
        self.board.set_rect(board_rect)
        self.result_menu.set_rect(result_rect)
        self.confirm_modal.set_rect(result_rect)
        self.server_modal.set_rect(result_rect)
        self.wait_modal.set_rect(wait_rect)
        self.file_picker.set_rect(start_rect)
        self.start_menu.set_rect(start_rect)
        self.right_menu.set_rect(menu_rect)
        self.player_strip_top.set_rect(top_strip_rect)
        self.player_strip_bottom.set_rect(bottom_strip_rect)
        self._refresh_capture_icons(strip_height)

    def _refresh_capture_icons(self, strip_height):
        if not self.board.piece_images_original:
            return
        target = max(int(strip_height * 0.6), 1)
        icons = {
            key: pg.transform.smoothscale(surface, (target, target))
            for key, surface in self.board.piece_images_original.items()
        }
        self.player_strip_top.set_piece_icons(icons)
        self.player_strip_bottom.set_piece_icons(icons)

    def _right_click_pressed(self, pos):
        if self.mode == "menu" or self.current_result() is not None:
            return
        sq = self.board.cell_at(pos)
        if sq is None:
            return
        if self.board.dragging_from is not None:
            # Right-click during a left-drag is reserved for premove chaining.
            # Even if the chain extension is rejected, do not register the
            # click as a highlight/arrow start.
            self.board.queue_premove_from_drag(sq)
            return
        self.board._right_drag_start_square = sq

    def _right_click_released(self, pos):
        start = self.board._right_drag_start_square
        self.board._right_drag_start_square = None
        if self.mode == "menu" or start is None:
            return
        end = self.board.cell_at(pos)
        if end is None:
            return
        if end == start:
            self.board.toggle_highlight(start)
        else:
            self.board.toggle_arrow(start, end)

    def mouse_left_clicked(self, pos):
        if self.file_picker.is_visible():
            self.file_picker.handle_click(pos)
            return
        if self.server_modal.handle_click(pos):
            return
        if self.server_modal.is_visible():
            return
        if self.wait_modal.handle_click(pos):
            return
        if self.wait_modal.is_visible():
            return
        if self.mode == "menu":
            self.start_menu.handle_click(pos)
            return
        if self.confirm_modal.handle_click(pos):
            return
        if self.confirm_modal.is_visible():
            return
        if self.result_menu.handle_click(pos):
            return
        if self.right_menu.handle_click(pos):
            return
        if self.current_result() is not None:
            return
        square = self.board.cell_at(pos)
        if square is not None:
            if not self.board.is_square_annotated(square):
                self.board.clear_annotations()
            self.board.handle_click(square)

    def _handle_shortcut_key(self, event):
        if self.confirm_modal.is_visible() or self.file_picker.is_visible():
            return False
        if event.key == pg.K_f:
            self._on_flip()
            return True
        if event.key == pg.K_z and (event.mod & pg.KMOD_CTRL):
            self._on_undo()
            return True
        if event.key == pg.K_LEFT:
            self._step_review(-1)
            return True
        if event.key == pg.K_RIGHT:
            self._step_review(1)
            return True
        if event.key == pg.K_HOME:
            if self.match.move_history:
                self.board.review_ply = 0
            return True
        if event.key == pg.K_END:
            self.board.review_ply = None
            return True
        return False

    def _step_review(self, delta):
        history_len = len(self.match.move_history)
        if history_len == 0:
            return
        if self.board._target_ply is not None:
            current = self.board._target_ply
        elif self.board.review_ply is not None:
            current = self.board.review_ply
        else:
            current = history_len
        new_ply = max(0, min(history_len, current + delta))
        if new_ply == current:
            return
        if delta > 0:
            self.board.animate_review_ply(new_ply)
        else:
            self.board.jump_to_review_ply(new_ply)

    def _mouse_left_pressed(self, pos):
        self.mouse_left_clicked(pos)
        if (self.mode != "menu"
                and self.current_result() is None
                and not self.file_picker.is_visible()
                and not self.confirm_modal.is_visible()):
            self.board.begin_press(pos)

    def _mouse_left_released(self, pos):
        self.audio_panel.end_drag()
        was_dragging = self.board.dragging_from is not None
        if was_dragging:
            self.mouse_left_clicked(pos)
        self.board.end_press()

    def check_events(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.running = False

            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE:
                    self.running = False
                    continue
                if self.file_picker.is_visible():
                    continue
                if self.server_modal.is_visible() and self.server_modal.handle_key(event):
                    continue
                if self.server_modal.is_visible():
                    continue
                if self.wait_modal.is_visible():
                    continue
                if self.start_menu.is_visible() and self.start_menu.handle_key(event):
                    continue
                if self.start_menu.is_visible():
                    continue
                self._handle_shortcut_key(event)

            elif event.type == pg.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self._mouse_left_pressed(event.pos)
                elif event.button == 3:
                    self._right_click_pressed(event.pos)

            elif event.type == pg.MOUSEBUTTONUP:
                if event.button == 1:
                    self._mouse_left_released(event.pos)
                elif event.button == 3:
                    self._right_click_released(event.pos)

            elif event.type == pg.MOUSEMOTION:
                if event.buttons[0]:
                    if not self.audio_panel.handle_drag(event.pos, True):
                        self.board.update_drag_motion(event.pos)

            elif event.type == pg.MOUSEWHEEL:
                if self.file_picker.is_visible():
                    self.file_picker.handle_scroll(pg.mouse.get_pos(), event.y)
                elif self.mode != "menu":
                    self.right_menu.handle_scroll(pg.mouse.get_pos(), event.y)

            elif event.type == pg.VIDEORESIZE:
                w = max(event.w, MIN_WINDOW_WIDTH)
                h = max(event.h, MIN_WINDOW_HEIGHT)
                if (w, h) != (event.w, event.h):
                    self.window = pg.display.set_mode((w, h), pg.RESIZABLE)
                self.window_width = w
                self.window_height = h
                self._compute_layout()