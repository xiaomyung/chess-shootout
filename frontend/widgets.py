import pygame as pg

from frontend.colors import Colors


SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18


def draw_button(window, rect, label, font, force_pressed=False, disabled=False):
    if disabled:
        bg = Colors.dark_menu
        text_color = Colors.button_border
    else:
        mouse_pos = pg.mouse.get_pos()
        mouse_down = pg.mouse.get_pressed()[0]
        hovered = rect.collidepoint(mouse_pos)
        pressed = hovered and mouse_down

        if force_pressed or pressed:
            bg = Colors.button_pressed
        elif hovered:
            bg = Colors.button_hover
        else:
            bg = Colors.dark_menu
        text_color = Colors.white

    pg.draw.rect(window, bg, rect, border_radius=4)
    pg.draw.rect(window, Colors.button_border, rect, 1, border_radius=4)
    text = font.render(label, True, text_color)
    window.blit(
        text,
        (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
    )


def draw_button_row(window, rect, buttons, font, gap):
    n = len(buttons)
    btn_w = (rect.width - gap * (n - 1)) / n
    button_rects = {}
    for i, (label, key) in enumerate(buttons):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, rect.height)
        draw_button(window, br, label, font)
        button_rects[key] = br
    return button_rects


def draw_button_column(window, rect, buttons, font, gap):
    n = len(buttons)
    btn_h = (rect.height - gap * (n - 1)) / n
    button_rects = {}
    for i, (label, key) in enumerate(buttons):
        y = rect.y + i * (btn_h + gap)
        br = pg.Rect(rect.x, y, rect.width, btn_h)
        draw_button(window, br, label, font)
        button_rects[key] = br
    return button_rects


def draw_selector(window, rect, options, font, gap, selected_key):
    n = len(options)
    btn_w = (rect.width - gap * (n - 1)) / n
    button_rects = {}
    for i, (label, key) in enumerate(options):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, rect.height)
        draw_button(window, br, label, font, force_pressed=(key == selected_key))
        button_rects[key] = br
    return button_rects


def draw_scroll_thumb(window, track_rect, total, visible, offset_fraction, last_activity_ms):
    if total <= visible or track_rect.height <= 0:
        return
    if pg.time.get_ticks() - last_activity_ms > SCROLL_FADE_MS:
        return
    thumb_h = max(SCROLL_THUMB_MIN_HEIGHT, int(track_rect.height * visible / total))
    thumb_h = min(thumb_h, track_rect.height)
    thumb_y = track_rect.y + int((track_rect.height - thumb_h) * offset_fraction)
    thumb_x = track_rect.right - SCROLL_THUMB_RIGHT_OFFSET - SCROLL_THUMB_WIDTH
    pg.draw.rect(
        window, Colors.button_hover,
        pg.Rect(thumb_x, thumb_y, SCROLL_THUMB_WIDTH, thumb_h),
        border_radius=SCROLL_THUMB_WIDTH // 2,
    )
