from dataclasses import dataclass

import pygame as pg

from chessshootout.frontend.focus import layout as focus_layout
from chessshootout.frontend.window_chrome import WindowChrome


RIGHT_PANEL_WIDTH = 360
BOARD_AREA_MARGIN = 12
STRIP_MARGIN = 5
STRIP_HEIGHT_RATIO = 0.075
STRIP_GAP_RATIO = 0.015
PANEL_WIDTH_RATIO = 0.42
RESULT_HEIGHT_RATIO = 0.95
WAIT_HEIGHT_RATIO = 1.6
MENU_FOOTER_RESERVE = 22
MIN_MODAL_WIDTH = 360

UI_SCALE_MIN = 0.72
UI_SCALE_MAX = 1.15
UI_SCALE_REF_W = 1280
UI_SCALE_REF_H = 764


@dataclass
class LayoutRects:
    """
    Every rect and metric one window's worth of interface needs: where the
    board sits, the strips above and below it, the right panel, and the slots
    the shell drops its overlays into. Pure geometry, recomputed per window
    size and handed straight to the widgets that draw
    """

    top: int
    strip_height: float
    board_rect: pg.Rect
    result_rect: pg.Rect
    result_modal_rect: pg.Rect
    flex_rect: pg.Rect
    wide_overlay_rect: pg.Rect
    menu_rect: pg.Rect
    top_strip_rect: pg.Rect
    bottom_strip_rect: pg.Rect
    window_rect: pg.Rect
    scale: float = 1.0


def compute_ui_scale(width: int, height: int) -> float:
    """
    Work out how much to grow or shrink the interface for this window, so the
    same screens stay readable in a small window and do not look sparse in a
    large one. The reference window scores 1.0, and the answer is clamped at
    both ends so nothing ever collapses or bloats

    :param width: window width in pixels
    :param height: usable height in pixels, the window minus the title bar
    :returns: scale factor within the clamped minimum and maximum
    """
    scale = min(width / UI_SCALE_REF_W, height / UI_SCALE_REF_H)
    return max(UI_SCALE_MIN, min(UI_SCALE_MAX, scale))


def centered_rect(cx: float, cy: float, w: float, h: float) -> pg.Rect:
    """
    Build a rect of a given size around a centre point, the shape behind every
    centred overlay in the app -- result cards, waiting cards and the wide
    pickers

    :param cx: centre x in window pixels
    :param cy: centre y in window pixels
    :param w: rect width in pixels
    :param h: rect height in pixels
    :returns: the rect, centred on cx and cy
    """
    return pg.Rect(cx - w / 2, cy - h / 2, w, h)


def compute_layout(window_width: int, window_height: int, *, mode: str, focus_mode: bool,
                   focus_show: str, board_size: int) -> LayoutRects:
    """
    Lay out a whole window: fit the largest square board that still leaves room
    for the right panel, stack the two player strips around it, and mark out
    the slots the shell hands to its overlays. This is the app's one source of
    geometry -- the shell calls it at startup, on a resize and on every screen
    switch, and each screen lays itself out from the same window size

    :param window_width: window width in pixels
    :param window_height: window height in pixels
    :param mode: "menu" while no board is showing, anything else while one is;
        it decides whether overlays centre on the board or on the window
    :param focus_mode: True while the game screen is collapsed to the board
        alone, which recentres the board over the whole window
    :param focus_show: what focus mode keeps beside the board -- "line",
        "strips" or "nothing"
    :param board_size: squares per side of the board, the divisor behind cell
        size and therefore the size of the waiting card
    :returns: the rects and metrics for this window size
    """
    window_rect = pg.Rect(0, 0, window_width, window_height)
    top = WindowChrome.HEIGHT
    avail_height = window_height - top
    scale = compute_ui_scale(window_width, avail_height)
    panel_w = min(RIGHT_PANEL_WIDTH, int(window_width * PANEL_WIDTH_RATIO))
    board_area_w = max(window_width - panel_w, 200)

    board_size_px, strip_height, strip_gap, stack_h = focus_layout.square_stack(
        board_area_w, avail_height, True, STRIP_HEIGHT_RATIO, STRIP_GAP_RATIO,
        BOARD_AREA_MARGIN)

    board_x = (board_area_w - board_size_px) / 2
    board_y = top + (avail_height - stack_h) / 2 + strip_height + strip_gap

    board_rect = pg.Rect(board_x, board_y, board_size_px, board_size_px)
    focus_strip_override = None
    if focus_mode:
        board_rect = focus_layout.focus_square((window_width, window_height), top, focus_show)
        board_x, board_y = board_rect.x, board_rect.y
        board_size_px = board_rect.width
        if focus_show == "strips":
            sh, sg = focus_layout.focus_strip_metrics((window_width, window_height), top)
            focus_strip_override = focus_layout.focus_strip_rects(board_rect, sh, sg)

    cell_size = board_size_px / board_size
    result_width = min(440, board_size_px * 0.92)
    result_height = min(int(result_width * RESULT_HEIGHT_RATIO),
                        avail_height - 2 * BOARD_AREA_MARGIN)
    result_rect = centered_rect(
        board_x + board_size_px / 2, board_y + board_size_px / 2,
        result_width, result_height)
    wait_width = max(result_width, MIN_MODAL_WIDTH)
    wait_height = max(cell_size * WAIT_HEIGHT_RATIO, 200)
    wait_rect = centered_rect(
        board_x + board_size_px / 2, board_y + board_size_px / 2,
        wait_width, wait_height)

    usable_menu_h = max(avail_height - MENU_FOOTER_RESERVE, 200)
    start_width = min(440, window_width - 24)
    start_height = min(max(usable_menu_h - 24, 200), 660)

    wide_overlay_width = min(window_width * 0.9, 1100)
    wide_overlay_height = min(window_height * 0.85, 760)
    wide_overlay_rect = centered_rect(
        window_width / 2, top + avail_height / 2,
        wide_overlay_width, wide_overlay_height)

    menu_modal_width = min(start_width, max(result_width, MIN_MODAL_WIDTH))
    menu_modal_height = min(start_height, max(cell_size * WAIT_HEIGHT_RATIO, 200))
    menu_modal_rect = centered_rect(
        window_width / 2, top + avail_height / 2,
        menu_modal_width, menu_modal_height)

    board_visible = mode != "menu"
    flex_rect = wait_rect if board_visible else menu_modal_rect
    result_modal_rect = result_rect if board_visible else menu_modal_rect

    menu_rect = pg.Rect(
        window_width - panel_w,
        top,
        panel_w,
        avail_height
    )

    strip_x = STRIP_MARGIN
    strip_w = board_area_w - 2 * STRIP_MARGIN
    top_strip_rect = pg.Rect(
        strip_x,
        board_y - strip_height - strip_gap,
        strip_w,
        strip_height,
    )
    bottom_strip_rect = pg.Rect(
        strip_x,
        board_y + board_size_px + strip_gap,
        strip_w,
        strip_height,
    )
    if focus_strip_override is not None:
        top_strip_rect, bottom_strip_rect = focus_strip_override

    return LayoutRects(
        top=top,
        strip_height=strip_height,
        board_rect=board_rect,
        result_rect=result_rect,
        result_modal_rect=result_modal_rect,
        flex_rect=flex_rect,
        wide_overlay_rect=wide_overlay_rect,
        menu_rect=menu_rect,
        top_strip_rect=top_strip_rect,
        bottom_strip_rect=bottom_strip_rect,
        window_rect=window_rect,
        scale=scale,
    )
