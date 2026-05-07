import pygame as pg

from backend.backend import Backend
from frontend.board import Board
from frontend.right_menu import RightMenu
from frontend.result_menu import ResultMenu


class Frontend:

    def __init__(self, window_width: int, window_height: int):
        self.running = True
        self.target_fps = 60
        self.window_width = window_width
        self.window_height = window_height
        self.window = pg.display.set_mode((self.window_width, self.window_height), pg.RESIZABLE)
        self.clock = pg.time.Clock()

        self.backend = Backend()
        self.board = Board(self.window, self.backend)
        self.result_menu = ResultMenu(self.window)
        self.right_menu = RightMenu(self.window)

        self.backend.new_game()
        self.board.load_assets()
        self._compute_layout()

        pg.display.set_caption("Chess")

    def run(self):
        while self.running:
            self.check_events()
            self.window.fill("black")
            self.draw_frame()
            self.clock.tick(self.target_fps)
            pg.display.flip()

        pg.quit()

    def draw_frame(self):
        pg.display.set_caption(f"{self.clock.get_fps():.1f}")
        self.board.draw_board()
        self.result_menu.draw_result_window()
        self.right_menu.draw_menu()

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

        result_width = self.board.cell_size * 2.5
        result_height = self.board.cell_size * 2.5
        result_rect = pg.Rect(
            board_x + board_size_px / 2 - result_width / 2,
            board_y + board_size_px / 2 - result_height / 2,
            result_width,
            result_height
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
        self.right_menu.set_rect(menu_rect)

    def mouse_left_clicked(self, pos):
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