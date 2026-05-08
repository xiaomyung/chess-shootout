import os
from datetime import datetime

import pygame as pg

from backend.backend import Backend
from frontend.board import Board
from frontend.right_menu import RightMenu
from frontend.result_menu import ResultMenu
from frontend.start_menu import StartMenu
from frontend.pgn import generate_pgn
from paths import PROJECT_ROOT
from pieces.pieces import PieceColor, PieceType


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
}

AUTO_FLIP_DELAY_MS = 200


class Frontend:

    def __init__(self, window_width: int, window_height: int):
        self.running = True
        self.target_fps = 60
        self.window_width = window_width
        self.window_height = window_height
        self.window = pg.display.set_mode((self.window_width, self.window_height), pg.RESIZABLE)
        self.clock = pg.time.Clock()

        self.mode = "menu"
        self.manual_result = None
        self._last_turn_for_flip = None

        self.backend = Backend()
        self.board = Board(self.window, self.backend)
        self.result_menu = ResultMenu(self.window, {
            "new_game": self._on_new_game,
            "save_pgn": self._on_save_pgn,
            "menu": self._on_back_to_menu,
        })
        self.start_menu = StartMenu(self.window, {
            "single_screen": self._on_single_screen,
            "bot": self._on_bot,
            "online": self._on_online,
        })
        self.right_menu = RightMenu(self.window, self.backend, {
            "undo": self._on_undo,
            "resign": self._on_resign,
            "draw": self._on_draw,
            "flip": self._on_flip,
        })

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

    def _on_back_to_menu(self):
        self.mode = "menu"
        self._reset_to_new_game()
        self.start_menu.show()

    def _on_single_screen(self):
        self.mode = "single_screen"
        self._reset_to_new_game()
        self.start_menu.hide()

    def _on_bot(self):
        pass

    def _on_online(self):
        pass

    def _reset_to_new_game(self):
        self.manual_result = None
        self.backend.new_game()
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
        with open(path, "w") as f:
            f.write(generate_pgn(self.backend.move_history, result))

    def _on_undo(self):
        if self.manual_result is not None:
            self.manual_result = None
            return
        self.board.cancel_animations()
        self.backend.undo()

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

    def run(self):
        while self.running:
            self.check_events()
            self.window.fill("black")
            self.draw_frame()
            self.clock.tick(self.target_fps)
            pg.display.flip()

        pg.quit()

    def draw_frame(self):
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
            self.right_menu.draw_menu()
            self.result_menu.set_text(self.result_text())
            self.result_menu.draw()
        self.start_menu.draw()

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

        start_width = cell_size * 4
        start_height = cell_size * 3.5
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

        self.board.font = pg.font.SysFont(
            "Arial",
            int(effective // self.board.board_guides_font_factor),
            bold=True
        )
        self.board.set_rect(board_rect)
        self.result_menu.set_rect(result_rect)
        self.start_menu.set_rect(start_rect)
        self.right_menu.set_rect(menu_rect)

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
                if event.key == pg.K_ESCAPE:
                    self.running = False

            elif event.type == pg.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.mouse_left_clicked(event.pos)

            elif event.type == pg.VIDEORESIZE:
                self._compute_layout()