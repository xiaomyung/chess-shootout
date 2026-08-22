import pygame as pg

MIN_BOARD_PX = 240
FOCUS_MARGIN = 24
FOCUS_STRIP_MARGIN = 12
FOCUS_STRIP_H_RATIO = 0.052
FOCUS_STRIP_GAP_RATIO = 0.012
FOCUS_LINE_H_RATIO = 0.006
FOCUS_LINE_MIN_H = 3
FOCUS_LINE_MAX_H = 6


def time_line_height(board_w: int) -> int:
    """
    How thick the slim clock bars are for a board of a given width. They scale
    with the board but are clamped at both ends, so they stay a hairline on a
    huge board and stay visible on a small one

    :param board_w: board width in pixels
    :returns: bar thickness in pixels
    """
    return max(min(int(board_w * FOCUS_LINE_H_RATIO), FOCUS_LINE_MAX_H), FOCUS_LINE_MIN_H)


def time_line_rects(board_rect: pg.Rect, grid_top: int, grid_bottom: int,
                    grid_left: int, grid_w: int) -> tuple[pg.Rect, pg.Rect]:
    """
    Place the two clock bars of the leanest focus mode, straddling the top and
    bottom edges of the playing grid so each reads as belonging to the player on
    that side of the board

    :param board_rect: the board plate, whose width sets the bar thickness
    :param grid_top: y of the top edge of the 8x8 grid in window pixels
    :param grid_bottom: y of its bottom edge in window pixels
    :param grid_left: x of its left edge in window pixels
    :param grid_w: grid width in pixels, which the bars span
    :returns: the top and bottom bar rects
    """
    th = time_line_height(board_rect.width)
    top = pg.Rect(grid_left, grid_top - th // 2, grid_w, th)
    bottom = pg.Rect(grid_left, grid_bottom - th // 2, grid_w, th)
    return top, bottom


def square_stack(area_w: int, area_h: int, reserve_strips: bool, strip_h_ratio: float,
                 strip_gap_ratio: float, margin: int,
                 min_px: float = MIN_BOARD_PX) -> tuple[float, float, float, float]:
    """
    Fit the biggest square board into an area, optionally keeping room above and
    below it for the two player strips. This is the one sizing rule the normal
    view and focus mode share, which is why the board never jumps in size for a
    reason the player cannot see

    :param area_w: width available in pixels
    :param area_h: height available in pixels
    :param reserve_strips: True to leave room for a strip and its gap on each
        side of the board, False for a bare square
    :param strip_h_ratio: strip height as a fraction of the board size
    :param strip_gap_ratio: gap between board and strip, same fraction basis
    :param margin: breathing space kept at every edge of the area, in pixels
    :param min_px: smallest board to hand back, even when the area is tighter
    :returns: board size, strip height, strip gap and the height of the whole
        stack, all in pixels
    """
    stack_factor = 1 + 2 * (strip_h_ratio + strip_gap_ratio) if reserve_strips else 1.0
    h_budget = area_w - 2 * margin
    v_budget = (area_h - 2 * margin) / stack_factor
    board_size = max(min(h_budget, v_budget), min_px)
    strip_height = board_size * strip_h_ratio if reserve_strips else 0.0
    strip_gap = board_size * strip_gap_ratio if reserve_strips else 0.0
    stack_h = board_size + 2 * (strip_height + strip_gap)
    return board_size, strip_height, strip_gap, stack_h


def _clamp_inside(rect: pg.Rect, w: int, h: int, top: int) -> pg.Rect:
    """
    Pull a rect back inside the window below the title bar, trimming it rather
    than moving it. It is the safety net for a window too small to hold the
    minimum board, where the square would otherwise hang off an edge

    :param rect: rect to fit, altered in place
    :param w: window width in pixels
    :param h: window height in pixels
    :param top: y below which the rect must stay, the title bar height
    :returns: the same rect, now inside those bounds
    """
    rect.x = max(0, rect.x)
    rect.y = max(top, rect.y)
    if rect.right > w:
        rect.width = w - rect.x
    if rect.bottom > h:
        rect.height = h - rect.y
    return rect


def focus_square(window_size: tuple[int, int], top: int, show_mode: str) -> pg.Rect:
    """
    Where the board sits in focus mode: a centred square filling the window
    below the title bar. Keeping the strips costs it room and a tighter margin,
    while the line and nothing modes both give the full square, so switching
    between those two never resizes the board

    :param window_size: window width and height in pixels
    :param top: title bar height, the first usable row
    :param show_mode: what focus mode keeps on screen, "line", "strips" or
        "nothing", from the CHESS_FOCUS_SHOW setting
    :returns: the board rect in window pixels
    """
    w, h = window_size
    avail = h - top
    reserve = show_mode == "strips"
    margin = FOCUS_STRIP_MARGIN if reserve else FOCUS_MARGIN
    board_size, sh, sg, stack_h = square_stack(
        w, avail, reserve, FOCUS_STRIP_H_RATIO, FOCUS_STRIP_GAP_RATIO, margin)
    board_x = (w - board_size) / 2
    board_y = top + (avail - stack_h) / 2 + sh + sg
    rect = pg.Rect(int(board_x), int(board_y), int(board_size), int(board_size))
    return _clamp_inside(rect, w, h, top)


def focus_strip_metrics(window_size: tuple[int, int], top: int) -> tuple[float, float]:
    """
    How tall the player strips are in focus mode and how far they stand off the
    board. They are read from the same stack the board was sized by, so strips
    and board always agree

    :param window_size: window width and height in pixels
    :param top: title bar height, the first usable row
    :returns: strip height and the gap to the board, in pixels
    """
    w, h = window_size
    _, sh, sg, _ = square_stack(
        w, h - top, True, FOCUS_STRIP_H_RATIO, FOCUS_STRIP_GAP_RATIO, FOCUS_STRIP_MARGIN)
    return sh, sg


def focus_strip_rects(board_rect: pg.Rect, strip_height: float,
                      strip_gap: float) -> tuple[pg.Rect, pg.Rect]:
    """
    Place the two player strips in focus mode, flanking the board and exactly as
    wide as it is. Unlike the normal view, where they run the width of the board
    area, here they frame the board so the pair reads as one object

    :param board_rect: the focus-mode board rect
    :param strip_height: strip height in pixels
    :param strip_gap: gap between board and strip in pixels
    :returns: the top and bottom strip rects
    """
    sh = int(strip_height)
    top_rect = pg.Rect(board_rect.x, int(board_rect.y - strip_height - strip_gap),
                       board_rect.width, sh)
    bottom_rect = pg.Rect(board_rect.x, int(board_rect.bottom + strip_gap),
                          board_rect.width, sh)
    return top_rect, bottom_rect
