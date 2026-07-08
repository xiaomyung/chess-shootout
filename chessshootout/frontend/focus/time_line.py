import pygame as pg

from chessshootout.backend.pieces import PieceColor
from chessshootout.frontend.focus import layout as focus_layout
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION
from chessshootout.frontend.visual.colors import Colors

FOCUS_LINE_TRACK_ALPHA = 46


class TimeLine:

    def rects_for(self, board, board_rect):
        grid = board.cell_size * board.SIZE
        sx = board_rect.width / board.rect.width if board.rect.width else 1.0
        sy = board_rect.height / board.rect.height if board.rect.height else 1.0
        grid_top = board_rect.top + (board.board_offset_y - board.rect.top) * sy
        grid_bottom = board_rect.top + (board.board_offset_y + grid - board.rect.top) * sy
        grid_left = board_rect.left + (board.board_offset_x - board.rect.left) * sx
        grid_w = int(grid * sx)
        return focus_layout.time_line_rects(
            board_rect, int(grid_top), int(grid_bottom), int(grid_left), grid_w)

    def draw(self, window, board, clock, mover, board_rect, alpha=1.0):
        if clock is None:
            return
        top_rect, bottom_rect = self.rects_for(board, board_rect)
        bottom_color = PieceColor.BLACK if board.flipped else PieceColor.WHITE
        top_color = PieceColor.WHITE if board.flipped else PieceColor.BLACK
        self._draw_one(window, top_rect, clock, top_color, mover, alpha)
        self._draw_one(window, bottom_rect, clock, bottom_color, mover, alpha)

    def _draw_one(self, window, rect, clock, color, mover, alpha):
        if alpha <= 0.01 or rect.width < 1 or rect.height < 1:
            return
        initial = clock.initial_seconds
        frac = max(0.0, min(clock.remaining(color) / initial, 1.0)) if initial > 0 else 0.0
        if frac < LOW_TIME_FRACTION:
            base = Colors.check
        elif color == mover:
            base = Colors.accent
        else:
            base = Colors.text_muted
        chip = pg.Surface(rect.size, pg.SRCALPHA)
        area = pg.Rect(0, 0, rect.width, rect.height)
        radius = rect.height // 2
        track = pg.Color(Colors.surface_active)
        track.a = int(FOCUS_LINE_TRACK_ALPHA * alpha)
        pg.draw.rect(chip, track, area, border_radius=radius)
        fill_w = int(rect.width * frac)
        if fill_w > 0:
            fill = pg.Rect(0, 0, fill_w, rect.height)
            fill.center = area.center
            col = pg.Color(base)
            col.a = int(255 * alpha)
            pg.draw.rect(chip, col, fill, border_radius=radius)
        window.blit(chip, rect.topleft)
