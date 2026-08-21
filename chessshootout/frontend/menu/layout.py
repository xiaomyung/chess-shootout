from dataclasses import dataclass

import pygame as pg

from chessshootout.frontend.layout import compute_ui_scale


RAIL_W = 216
RIGHT_W = 312
MARGIN = 24
HERO_PAD_LEFT = 48
HERO_GAP_RIGHT = 24
SUBVIEW_MAX_W = 860


@dataclass
class MenuLayout:
    """
    Every rect the menu draws into for one window size, worked out in one
    place so the rail, the sub-views and the right-hand cards cannot disagree
    about where they are. The menu screen holds the current one and hands it
    to each sub-view on relayout and on every draw
    """

    top: int
    scale: float
    rail_rect: pg.Rect
    right_rail_rect: pg.Rect
    right_rail_full_rect: pg.Rect
    hero_rect: pg.Rect
    subview_rect: pg.Rect


def compute_menu_layout(window_width: int, window_height: int, top: int,
                        right_rail: bool = False) -> MenuLayout:
    """
    Work out the whole menu's geometry for one window size. It is pure
    arithmetic -- no pygame drawing, no state -- so the menu screen can call it
    on every resize and the tests can check the rects without a window. Only
    the Play view keeps the right-hand card column, so that space either goes
    to the cards or is given back to the sub-view beside the rail

    :param window_width: window width in pixels
    :param window_height: window height in pixels, title bar included
    :param top: y where the menu starts, below the window chrome
    :param right_rail: True on the Play view, which is the only view that
        reserves the right-hand card column
    :returns: the rects and the interface scale for this window size
    """
    avail_h = max(window_height - top, 1)
    scale = compute_ui_scale(window_width, avail_h)

    rail_rect = pg.Rect(0, top, RAIL_W, avail_h)
    if right_rail:
        right_rail_rect = pg.Rect(window_width - RIGHT_W - MARGIN, top + MARGIN,
                                  RIGHT_W, max(avail_h - 2 * MARGIN, 1))
        right_rail_full_rect = pg.Rect(window_width - RIGHT_W - 2 * MARGIN, top,
                                       RIGHT_W + 2 * MARGIN, avail_h)
        hero_right = right_rail_full_rect.left - round(HERO_GAP_RIGHT * scale)
    else:
        right_rail_rect = pg.Rect(window_width, top + MARGIN, 0, max(avail_h - 2 * MARGIN, 1))
        right_rail_full_rect = pg.Rect(window_width, top, 0, avail_h)
        hero_right = window_width - MARGIN

    hero_left = RAIL_W + round(HERO_PAD_LEFT * scale)
    hero_rect = pg.Rect(hero_left, top + MARGIN, max(hero_right - hero_left, 1),
                        max(avail_h - 2 * MARGIN, 1))

    content_left = RAIL_W + MARGIN
    content_right = window_width - MARGIN
    content_w = max(content_right - content_left, 1)
    sub_w = min(content_w, SUBVIEW_MAX_W)
    sub_x = content_left + (content_w - sub_w) // 2
    subview_rect = pg.Rect(sub_x, top + MARGIN, sub_w, max(avail_h - 2 * MARGIN, 1))

    return MenuLayout(
        top=top,
        scale=scale,
        rail_rect=rail_rect,
        right_rail_rect=right_rail_rect,
        right_rail_full_rect=right_rail_full_rect,
        hero_rect=hero_rect,
        subview_rect=subview_rect,
    )
