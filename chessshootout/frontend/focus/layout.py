import pygame as pg

MIN_BOARD_PX = 240
FOCUS_MARGIN = 24
FOCUS_STRIP_MARGIN = 12
FOCUS_STRIP_H_RATIO = 0.052
FOCUS_STRIP_GAP_RATIO = 0.012
FOCUS_LINE_H_RATIO = 0.006
FOCUS_LINE_MIN_H = 3
FOCUS_LINE_MAX_H = 6


def time_line_height(board_w):
    return max(min(int(board_w * FOCUS_LINE_H_RATIO), FOCUS_LINE_MAX_H), FOCUS_LINE_MIN_H)


def time_line_rects(board_rect, grid_top, grid_bottom, grid_left, grid_w):
    th = time_line_height(board_rect.width)
    top = pg.Rect(grid_left, grid_top - th // 2, grid_w, th)
    bottom = pg.Rect(grid_left, grid_bottom - th // 2, grid_w, th)
    return top, bottom


def square_stack(area_w, area_h, reserve_strips, strip_h_ratio, strip_gap_ratio,
                 margin, min_px=MIN_BOARD_PX):
    stack_factor = 1 + 2 * (strip_h_ratio + strip_gap_ratio) if reserve_strips else 1.0
    h_budget = area_w - 2 * margin
    v_budget = (area_h - 2 * margin) / stack_factor
    board_size = max(min(h_budget, v_budget), min_px)
    strip_height = board_size * strip_h_ratio if reserve_strips else 0.0
    strip_gap = board_size * strip_gap_ratio if reserve_strips else 0.0
    stack_h = board_size + 2 * (strip_height + strip_gap)
    return board_size, strip_height, strip_gap, stack_h


def _clamp_inside(rect, w, h, top):
    rect.x = max(0, rect.x)
    rect.y = max(top, rect.y)
    if rect.right > w:
        rect.width = w - rect.x
    if rect.bottom > h:
        rect.height = h - rect.y
    return rect


def focus_square(window_size, top, show_mode, strip_h_ratio, strip_gap_ratio):
    w, h = window_size
    avail = h - top
    if show_mode == "strips":
        board_size, sh, sg, stack_h = square_stack(
            w, avail, True, FOCUS_STRIP_H_RATIO, FOCUS_STRIP_GAP_RATIO, FOCUS_STRIP_MARGIN)
    else:
        board_size, sh, sg, stack_h = square_stack(
            w, avail, False, strip_h_ratio, strip_gap_ratio, FOCUS_MARGIN)
    board_x = (w - board_size) / 2
    board_y = top + (avail - stack_h) / 2 + sh + sg
    rect = pg.Rect(int(board_x), int(board_y), int(board_size), int(board_size))
    return _clamp_inside(rect, w, h, top)


def focus_strip_metrics(window_size, top, strip_h_ratio, strip_gap_ratio):
    w, h = window_size
    _, sh, sg, _ = square_stack(
        w, h - top, True, FOCUS_STRIP_H_RATIO, FOCUS_STRIP_GAP_RATIO, FOCUS_STRIP_MARGIN)
    return sh, sg


def focus_strip_rects(board_rect, strip_height, strip_gap):
    sh = int(strip_height)
    top_rect = pg.Rect(board_rect.x, int(board_rect.y - strip_height - strip_gap),
                       board_rect.width, sh)
    bottom_rect = pg.Rect(board_rect.x, int(board_rect.bottom + strip_gap),
                          board_rect.width, sh)
    return top_rect, bottom_rect
