import math

import pygame as pg

from frontend.visual.colors import Colors


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


def wrap_path(text, font, max_w, max_lines=6):
    tokens = []
    parts = text.split("/")
    for i, part in enumerate(parts):
        token = part + "/" if i < len(parts) - 1 else part
        if token:
            tokens.append(token)
    lines = []
    line = ""
    for token in tokens:
        if line and font.size(line + token)[0] > max_w:
            lines.append(line)
            line = ""
            if len(lines) >= max_lines:
                return lines
        if not line and font.size(token)[0] > max_w:
            for ch in token:
                if line and font.size(line + ch)[0] > max_w:
                    lines.append(line)
                    line = ""
                    if len(lines) >= max_lines:
                        return lines
                line += ch
        else:
            line += token
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines


def _button_bg(rect, force_pressed=False, disabled=False):
    if disabled:
        return Colors.dark_menu, Colors.button_border
    hovered = rect.collidepoint(pg.mouse.get_pos())
    pressed = hovered and pg.mouse.get_pressed()[0]
    if force_pressed or pressed:
        bg = Colors.button_pressed
    elif hovered:
        bg = Colors.button_hover
    else:
        bg = Colors.dark_menu
    return bg, Colors.white


def draw_button(window, rect, label, font, force_pressed=False, disabled=False):
    bg, text_color = _button_bg(rect, force_pressed, disabled)
    pg.draw.rect(window, bg, rect, border_radius=4)
    pg.draw.rect(window, Colors.button_border, rect, 1, border_radius=4)
    text = fit_text_to_rect(font.render(label, True, text_color), rect)
    window.blit(
        text,
        (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
    )


def draw_icon_button(window, rect, icon_fn, force_pressed=False, disabled=False):
    if not disabled:
        hovered = rect.collidepoint(pg.mouse.get_pos())
        pressed = hovered and pg.mouse.get_pressed()[0]
        if force_pressed or pressed:
            pg.draw.rect(window, Colors.button_pressed, rect, border_radius=4)
        elif hovered:
            pg.draw.rect(window, Colors.button_hover, rect, border_radius=4)
    icon_fn(window, rect)


def draw_gear(window, rect):
    ss = 4
    w, h = max(rect.width, 1) * ss, max(rect.height, 1) * ss
    surf = pg.Surface((w, h), pg.SRCALPHA)
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.30
    teeth = 8
    r0, r1 = r * 0.72, r * 1.46
    hw_base, hw_tip = r * 0.30, r * 0.16
    for i in range(teeth):
        a = math.tau * i / teeth
        dx, dy = math.cos(a), math.sin(a)
        px, py = -dy, dx
        pts = [
            (cx + dx * r0 + px * hw_base, cy + dy * r0 + py * hw_base),
            (cx + dx * r0 - px * hw_base, cy + dy * r0 - py * hw_base),
            (cx + dx * r1 - px * hw_tip, cy + dy * r1 - py * hw_tip),
            (cx + dx * r1 + px * hw_tip, cy + dy * r1 + py * hw_tip),
        ]
        pg.draw.polygon(surf, Colors.white, pts)
    hole_r = r * 0.40
    pg.draw.circle(surf, Colors.white, (int(cx), int(cy)), int(r), width=int(r - hole_r))
    window.blit(pg.transform.smoothscale(surf, (rect.width, rect.height)), rect.topleft)


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
