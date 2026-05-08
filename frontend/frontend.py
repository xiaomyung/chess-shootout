import os
import random
from datetime import datetime

import pygame as pg

from backend.backend import Backend
from frontend.board import Board
from frontend.player_strip import PlayerStrip
from frontend.right_menu import RightMenu
from frontend.result_menu import ResultMenu
from frontend.sound_manager import SoundManager
from frontend.start_menu import StartMenu
from frontend.pgn import generate_pgn, TIMEOUT_RESULTS
from paths import PROJECT_ROOT, SOUNDS_DIR
from pieces import PieceColor, PieceType


MANUAL_RESULT_TEXT = {
    "white_wins": ("White wins", "by resignation"),
    "black_wins": ("Black wins", "by resignation"),
    "draw_agreement": ("Draw", "by agreement"),
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
    "single_screen": "Player 2",
    "bot": "AI Bot",
    "online": "Opponent",
}

AUTO_FLIP_DELAY_MS = 200

MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 500


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

        self.backend = Backend()
        self.sound_manager = SoundManager(SOUNDS_DIR, enabled=pg.mixer.get_init() is not None)
        self.board = Board(self.window, self.backend, move_landed_callback=self._on_move_landed)
        self.result_menu = ResultMenu(self.window, {
            "new_game": self._on_new_game,
            "save_pgn": self._on_save_pgn,
            "menu": self._on_back_to_menu,
        })
        self.start_menu = StartMenu(self.window, {
            "start_game": self._on_start_game,
        })
        self.right_menu = RightMenu(self.window, self.backend, {
            "undo": self._on_undo,
            "resign": self._on_resign,
            "draw": self._on_draw,
            "flip": self._on_flip,
        })
        self.player_strip_top = PlayerStrip(self.window)
        self.player_strip_bottom = PlayerStrip(self.window)

        self.backend.new_game()
        self.board.load_assets()
        self._compute_layout()

        pg.display.set_caption("Chess")

    def current_result(self):
        return self.manual_result or self.backend.game_result()

    def result_text(self):
        if self.manual_result is not None:
            return MANUAL_RESULT_TEXT.get(self.manual_result)
        engine = self.backend.game_result()
        if engine is None:
            return None
        return ENGINE_RESULT_TEXT.get(engine)

    def _on_new_game(self):
        self._reset_to_new_game()
        self.sound_manager.play_game_start()

    def _on_back_to_menu(self):
        self.mode = "menu"
        self._reset_to_new_game()
        self.start_menu.show()

    def _on_start_game(self, config):
        if config["mode"] != "single_screen":
            return

        self.mode = "single_screen"

        side = config["side"]
        if side == "random":
            side = random.choice(["white", "black"])
        self._chosen_side = side

        nickname = (config.get("nickname") or "").strip() or "Player 1"
        opponent_name = OPPONENT_NAME_FOR_MODE[config["mode"]]
        if side == "white":
            self.white_name, self.black_name = nickname, opponent_name
        else:
            self.white_name, self.black_name = opponent_name, nickname

        if config["time_minutes"] is not None:
            initial = config["time_minutes"] * 60
            incr = config["increment_seconds"]
            self._time_control = (initial, incr)
        else:
            self._time_control = None

        self._reset_to_new_game()
        self.start_menu.hide()
        self.sound_manager.play_game_start()

    def _reset_to_new_game(self):
        self.sound_manager.stop_all()
        self.manual_result = None
        self.backend.new_game()
        if self._time_control is not None:
            initial, incr = self._time_control
            self.backend.setup_clock(initial, incr)
        self.board.flipped = False
        self.board.selected_square = None
        self.board.pending_promotion_square = None
        self.board.cancel_animations()
        self._last_turn_for_flip = None

    def _on_save_pgn(self):
        result = self.current_result()
        if result is None:
            return
        games_dir = os.path.join(PROJECT_ROOT, "games")
        os.makedirs(games_dir, exist_ok=True)
        filename = f"game-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pgn"
        path = os.path.join(games_dir, filename)
        time_control = self._time_control
        termination = "Time forfeit" if result in TIMEOUT_RESULTS else None
        with open(path, "w") as f:
            f.write(generate_pgn(
                self.backend.move_history, result,
                white_name=self.white_name, black_name=self.black_name,
                time_control=time_control, termination=termination,
            ))

    def _on_undo(self):
        if self.manual_result is not None:
            self.manual_result = None
            return
        self.board.cancel_animations()
        if not self.backend.move_history:
            return
        self.sound_manager.play_undo()
        move = self.backend.move_history[-1].move
        self.backend.undo()
        self.board.start_undo_animation(move)

    def _on_resign(self):
        if self.current_result() is not None:
            return
        loser = self.backend.current_turn()
        self._auto_complete_pending_promotion()
        self.manual_result = "black_wins" if loser == PieceColor.WHITE else "white_wins"

    def _on_draw(self):
        if self.current_result() is not None:
            return
        self._auto_complete_pending_promotion()
        self.manual_result = "draw_agreement"

    def _auto_complete_pending_promotion(self):
        if self.board.pending_promotion_square is None:
            return
        self.backend.promote(self.board.pending_promotion_square, PieceType.QUEEN)
        self.board.pending_promotion_square = None

    def _on_flip(self):
        self.board.flipped = not self.board.flipped

    def _on_move_landed(self, entry):
        if entry.gives_checkmate:
            self.sound_manager.play_checkmate()
        else:
            self.sound_manager.play_move()
        if entry.move.captured is not None:
            self.sound_manager.play_capture(entry.move.piece.type)
        if entry.gives_check and not entry.gives_checkmate:
            self.sound_manager.play_check()

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
            self.backend.tick_clock()

        self._update_heartbeat()

        now = pg.time.get_ticks()
        if (self.mode == "single_screen"
                and self.current_result() is None
                and not self.board.is_animating()
                and now - self.board.last_animation_completed_at_ms >= AUTO_FLIP_DELAY_MS):
            current = self.backend.current_turn()
            if current != self._last_turn_for_flip:
                self.board.flipped = (current == PieceColor.BLACK)
                self._last_turn_for_flip = current

        self.board.draw_board()
        if self.mode != "menu":
            self._update_player_strips()
            self.player_strip_top.draw()
            self.player_strip_bottom.draw()
            self.right_menu.draw_menu()
            self.result_menu.set_text(self.result_text())
            self.result_menu.draw()
        self.start_menu.draw()

    def _update_player_strips(self):
        top_color = PieceColor.WHITE if self.board.flipped else PieceColor.BLACK
        bottom_color = PieceColor.BLACK if self.board.flipped else PieceColor.WHITE
        turn = self.backend.current_turn()
        over = self.current_result() is not None
        self.player_strip_top.set_state(*self._strip_state(top_color, turn, over))
        self.player_strip_bottom.set_state(*self._strip_state(bottom_color, turn, over))

    def _update_heartbeat(self):
        clock = self.backend.clock
        paused = (self.mode == "menu"
                  or self.current_result() is not None
                  or clock is None)
        if paused or clock.initial_seconds <= 0:
            fraction = None
        else:
            fraction = clock.remaining(self.backend.current_turn()) / clock.initial_seconds
        self.sound_manager.update_heartbeat(fraction, paused)

    def _strip_state(self, color, turn, over):
        name = self.white_name if color == PieceColor.WHITE else self.black_name
        seconds = (self.backend.clock.remaining(color)
                   if self.backend.clock is not None else None)
        active = (color == turn) and not over
        return name, seconds, active

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
        self.start_menu.set_rect(start_rect)
        self.right_menu.set_rect(menu_rect)
        self.player_strip_top.set_rect(top_strip_rect)
        self.player_strip_bottom.set_rect(bottom_strip_rect)

    def mouse_left_clicked(self, pos):
        if self.mode == "menu":
            self.start_menu.handle_click(pos)
            return
        if self.result_menu.handle_click(pos):
            return
        if self.right_menu.handle_click(pos):
            return
        if self.current_result() is not None:
            return
        square = self.board.cell_at(pos)
        if square is not None:
            self.board.handle_click(square)

    def check_events(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.running = False

            elif event.type == pg.KEYDOWN:
                if self.start_menu.is_visible() and self.start_menu.handle_key(event):
                    continue
                if event.key == pg.K_ESCAPE:
                    self.running = False

            elif event.type == pg.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.mouse_left_clicked(event.pos)

            elif event.type == pg.MOUSEWHEEL:
                if self.mode != "menu":
                    self.right_menu.handle_scroll(pg.mouse.get_pos(), event.y)

            elif event.type == pg.VIDEORESIZE:
                w = max(event.w, MIN_WINDOW_WIDTH)
                h = max(event.h, MIN_WINDOW_HEIGHT)
                if (w, h) != (event.w, event.h):
                    self.window = pg.display.set_mode((w, h), pg.RESIZABLE)
                self.window_width = w
                self.window_height = h
                self._compute_layout()