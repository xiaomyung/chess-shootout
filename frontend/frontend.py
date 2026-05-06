import pygame as pg

from backend.backend import Backend
from frontend.board import Board
from frontend.right_menu import RightMenu


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
        self.right_menu.draw_menu()

    def _compute_layout(self):
        window_width, window_height = self.window.get_size()
        effective = max(min(window_width, window_height), 300)
        board_size_px = effective * self.board.SCREEN_FRACTION_X

        board_x = board_size_px * self.board.OFFSET_FRACTION_X
        board_y = window_height // 2 - board_size_px // 2
        board_rect = pg.Rect(board_x, board_y, board_size_px, board_size_px)

        menu_rect = pg.Rect(
            board_rect.right, 0,
            window_width - board_rect.right, window_height
        )

        self.board.set_rect(board_rect)
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