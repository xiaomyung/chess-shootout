import pygame as pg

from frontend.colors import Colors


def _draw_button(window, rect, label, font):
    mouse_pos = pg.mouse.get_pos()
    mouse_down = pg.mouse.get_pressed()[0]
    hovered = rect.collidepoint(mouse_pos)
    pressed = hovered and mouse_down

    if pressed:
        bg = Colors.button_pressed
    elif hovered:
        bg = Colors.button_hover
    else:
        bg = Colors.dark_menu

    pg.draw.rect(window, bg, rect, border_radius=4)
    pg.draw.rect(window, Colors.button_border, rect, 1, border_radius=4)
    text = font.render(label, True, Colors.white)
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
        _draw_button(window, br, label, font)
        button_rects[key] = br
    return button_rects


def draw_button_column(window, rect, buttons, font, gap):
    n = len(buttons)
    btn_h = (rect.height - gap * (n - 1)) / n
    button_rects = {}
    for i, (label, key) in enumerate(buttons):
        y = rect.y + i * (btn_h + gap)
        br = pg.Rect(rect.x, y, rect.width, btn_h)
        _draw_button(window, br, label, font)
        button_rects[key] = br
    return button_rects
