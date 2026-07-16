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
    top: int
    scale: float
    rail_rect: pg.Rect
    right_rail_rect: pg.Rect
    right_rail_full_rect: pg.Rect
    hero_rect: pg.Rect
    subview_rect: pg.Rect


def compute_menu_layout(window_width, window_height, top, right_rail=False):
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
