import pygame as pg

from frontend.colors import Colors


SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18
BUTTON_LABEL_PADDING_PX = 6


def fit_text_to_rect(text_surface, rect, padding=BUTTON_LABEL_PADDING_PX):
    max_w = max(rect.width - 2 * padding, 1)
    max_h = max(rect.height - 2 * padding, 1)
    tw, th = text_surface.get_size()
    if tw <= max_w and th <= max_h:
        return text_surface
    scale = min(max_w / tw, max_h / th)
    new_size = (max(int(tw * scale), 1), max(int(th * scale), 1))
    return pg.transform.smoothscale(text_surface, new_size)


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
    text = fit_text_to_rect(font.render(label, True, text_color), rect)
    window.blit(
        text,
        (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
    )


def draw_button_row(window, rect, buttons, font, gap, disabled_keys=None):
    n = len(buttons)
    btn_w = (rect.width - gap * (n - 1)) / n
    button_rects = {}
    disabled_keys = disabled_keys or set()
    for i, (label, key) in enumerate(buttons):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, rect.height)
        draw_button(window, br, label, font, disabled=key in disabled_keys)
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
