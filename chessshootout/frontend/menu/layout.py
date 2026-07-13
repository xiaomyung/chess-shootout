from dataclasses import dataclass

import pygame as pg


RAIL_W = 216
RIGHT_W = 312
MARGIN = 24
SUBVIEW_MAX_W = 860
SCALE_MIN = 0.72
SCALE_MAX = 1.0
SCALE_REF_W = 1280
SCALE_REF_H = 764


@dataclass
class MenuLayout:
    top: int
    scale: float
    rail_rect: pg.Rect
    right_rail_rect: pg.Rect
    hero_rect: pg.Rect
    subview_rect: pg.Rect


def compute_menu_layout(window_width, window_height, top):
    avail_h = max(window_height - top, 1)
    scale = min(window_width / SCALE_REF_W, avail_h / SCALE_REF_H)
    scale = max(SCALE_MIN, min(SCALE_MAX, scale))

    rail_rect = pg.Rect(0, top, RAIL_W, avail_h)
    right_rail_rect = pg.Rect(window_width - MARGIN, top, 0, avail_h)

    hero_left = RAIL_W + MARGIN
    hero_right = window_width - RIGHT_W - MARGIN
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
        hero_rect=hero_rect,
        subview_rect=subview_rect,
    )
