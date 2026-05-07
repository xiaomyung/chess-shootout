import pygame as pg

from frontend.colors import Colors


def draw_button_row(window, rect, buttons, font, gap):
    n = len(buttons)
    btn_w = (rect.width - gap * (n - 1)) / n
    btn_h = rect.height

    mouse_pos = pg.mouse.get_pos()
    mouse_down = pg.mouse.get_pressed()[0]

    button_rects = {}
    for i, (label, key) in enumerate(buttons):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, btn_h)

        hovered = br.collidepoint(mouse_pos)
        pressed = hovered and mouse_down

        if pressed:
            bg = Colors.button_pressed
        elif hovered:
            bg = Colors.button_hover
        else:
            bg = Colors.dark_menu

        pg.draw.rect(window, bg, br, border_radius=4)
        pg.draw.rect(window, Colors.button_border, br, 1, border_radius=4)
        text = font.render(label, True, Colors.white)
        window.blit(
            text,
            (br.centerx - text.get_width() / 2, br.centery - text.get_height() / 2),
        )
        button_rects[key] = br

    return button_rects
