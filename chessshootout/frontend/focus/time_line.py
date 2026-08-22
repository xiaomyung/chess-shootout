import pygame as pg

from chessshootout.backend.clock import Clock
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import BOARD_SIZE
from chessshootout.frontend.board.board import Board
from chessshootout.frontend.focus import layout as focus_layout
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION
from chessshootout.frontend.visual.colors import Colors

FOCUS_LINE_TRACK_ALPHA = 46


class TimeLine:
    """
    The pair of slim bars above and below the board that stand in for the
    clocks in the leanest focus mode. Each drains as its player's time runs
    down, so both clocks can be read at a glance without a number on screen
    """

    def rects_for(self, board: Board, board_rect: pg.Rect) -> tuple[pg.Rect, pg.Rect]:
        """
        Work out where the two bars belong for a board drawn at a given rect.
        The board's own grid geometry is scaled into that rect, so the bars
        still line up with the playing grid while a focus transition is moving
        and resizing the board under them

        :param board: the board whose grid the bars follow
        :param board_rect: rect the board is being drawn at, which is not its
            own rect during a transition
        :returns: the top and bottom bar rects in window pixels
        """
        grid = board.cell_size * BOARD_SIZE
        sx = board_rect.width / board.rect.width if board.rect.width else 1.0
        sy = board_rect.height / board.rect.height if board.rect.height else 1.0
        grid_top = board_rect.top + (board.board_offset_y - board.rect.top) * sy
        grid_bottom = board_rect.top + (board.board_offset_y + grid - board.rect.top) * sy
        grid_left = board_rect.left + (board.board_offset_x - board.rect.left) * sx
        grid_w = int(grid * sx)
        return focus_layout.time_line_rects(
            board_rect, int(grid_top), int(grid_bottom), int(grid_left), grid_w)

    def draw(self, window: pg.Surface, board: Board, clock: Clock | None,
             mover: PieceColor, board_rect: pg.Rect, alpha: float = 1.0) -> None:
        """
        Draw both bars, each on the side of the board its player sits on, so a
        flipped board flips them too. An untimed game has no clock and draws
        nothing at all

        :param window: surface to draw on
        :param board: board the bars belong to, read for its geometry and flip
        :param clock: the game clock, or None in an untimed game
        :param mover: side to move, which gets the highlighted bar
        :param board_rect: rect the board is being drawn at
        :param alpha: fade factor from 0 to 1, used while a focus transition
            brings the bars in or takes them away
        """
        if clock is None:
            return
        top_rect, bottom_rect = self.rects_for(board, board_rect)
        bottom_color = PieceColor.BLACK if board.flipped else PieceColor.WHITE
        top_color = PieceColor.WHITE if board.flipped else PieceColor.BLACK
        self._draw_one(window, top_rect, clock, top_color, mover, alpha)
        self._draw_one(window, bottom_rect, clock, bottom_color, mover, alpha)

    def _draw_one(self, window: pg.Surface, rect: pg.Rect, clock: Clock,
                  color: PieceColor, mover: PieceColor, alpha: float) -> None:
        """
        Draw one player's bar: a dim track with a fill as long as the share of
        their starting time they still hold. The fill turns to the warning
        colour once they are low, is bright while it is their move and stays
        muted while they wait

        :param window: surface to draw on
        :param rect: where the bar goes, in window pixels
        :param clock: the game clock, read for this side's time
        :param color: side this bar belongs to
        :param mover: side to move, compared against color for the highlight
        :param alpha: fade factor from 0 to 1
        """
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
