import math

import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.draw import supersample, rounded_rect_surface, infinity_surface


SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18
BUTTON_LABEL_PADDING_PX = 6
BUTTON_RADIUS = 8


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
    parts = text.split("/")
    tokens = [part + "/" if i < len(parts) - 1 else part for i, part in enumerate(parts)]
    tokens = [token for token in tokens if token]
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


def _hover_state(rect):
    hovered = rect.collidepoint(pg.mouse.get_pos())
    pressed = hovered and pg.mouse.get_pressed()[0]
    return hovered, pressed


def _button_bg(rect, force_pressed=False, disabled=False):
    if disabled:
        return Colors.dark_menu, Colors.footer_text
    hovered, pressed = _hover_state(rect)
    if force_pressed or pressed:
        return Colors.button_pressed, Colors.white
    if hovered:
        return Colors.button_hover, Colors.white
    return Colors.light_grey_menu, Colors.text_dim


def draw_button(window, rect, label, font, force_pressed=False, disabled=False,
                selected=False, primary=False):
    if primary and not disabled:
        hovered, pressed = _hover_state(rect)
        bg = Colors.accent_press if pressed else (Colors.accent_hi if hovered else Colors.accent)
        text_color = Colors.on_accent
        border = bg
    else:
        bg, text_color = _button_bg(rect, force_pressed or selected, disabled)
        border = Colors.accent if (selected and not disabled) else Colors.button_border
    window.blit(rounded_rect_surface(rect.size, BUTTON_RADIUS, bg, border=border,
                                     border_width=1), rect.topleft)
    text = fit_text_to_rect(font.render(label, True, text_color), rect)
    window.blit(
        text,
        (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
    )


def draw_icon_button(window, rect, icon_fn, force_pressed=False, disabled=False, muted=False):
    if muted and not disabled:
        pg.draw.rect(window, Colors.button_pressed, rect, border_radius=BUTTON_RADIUS)
        pg.draw.rect(window, Colors.accent, rect, 1, border_radius=BUTTON_RADIUS)
    elif not disabled:
        hovered, pressed = _hover_state(rect)
        if force_pressed or pressed:
            bg = Colors.button_pressed
        elif hovered:
            bg = Colors.button_hover
        else:
            bg = Colors.light_grey_menu
        pg.draw.rect(window, bg, rect, border_radius=BUTTON_RADIUS)
        pg.draw.rect(window, Colors.button_border, rect, 1, border_radius=BUTTON_RADIUS)
    icon_fn(window, rect)


def draw_gear(window, rect):
    def render(surf, k):
        w, h = surf.get_size()
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.30
        teeth = 8
        r0, r1 = r * 0.72, r * 1.46
        hw_base, hw_tip = r * 0.30, r * 0.16
        for i in range(teeth):
            a = math.tau * i / teeth
            dx, dy = math.cos(a), math.sin(a)
            px, py = -dy, dx
            pg.draw.polygon(surf, Colors.white, [
                (cx + dx * r0 + px * hw_base, cy + dy * r0 + py * hw_base),
                (cx + dx * r0 - px * hw_base, cy + dy * r0 - py * hw_base),
                (cx + dx * r1 - px * hw_tip, cy + dy * r1 - py * hw_tip),
                (cx + dx * r1 + px * hw_tip, cy + dy * r1 + py * hw_tip),
            ])
        hole_r = r * 0.40
        pg.draw.circle(surf, Colors.white, (int(cx), int(cy)), int(r), width=int(r - hole_r))

    window.blit(supersample((max(rect.width, 1), max(rect.height, 1)), render, scale=8),
                rect.topleft)


def draw_button_row(window, rect, buttons, font, gap, disabled_keys=None,
                    primary_keys=None):
    n = len(buttons)
    if n == 0 or rect.width <= gap * (n - 1):
        return {}
    btn_w = (rect.width - gap * (n - 1)) / n
    button_rects = {}
    disabled_keys = disabled_keys or set()
    primary_keys = primary_keys or set()
    for i, (label, key) in enumerate(buttons):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, rect.height)
        draw_button(window, br, label, font, disabled=key in disabled_keys,
                    primary=key in primary_keys)
        button_rects[key] = br
    return button_rects


def draw_selector(window, rect, options, font, gap, selected_key):
    n = len(options)
    if n == 0 or rect.width <= gap * (n - 1):
        return {}
    btn_w = (rect.width - gap * (n - 1)) / n
    button_rects = {}
    for i, (label, key) in enumerate(options):
        x = rect.x + i * (btn_w + gap)
        br = pg.Rect(x, rect.y, btn_w, rect.height)
        draw_button(window, br, label, font, selected=(key == selected_key))
        button_rects[key] = br
    return button_rects


def draw_toggle(window, rect, fraction):
    fraction = max(0.0, min(1.0, fraction))
    track = pg.Color(Colors.button_pressed).lerp(pg.Color(Colors.accent), fraction)

    def render(surf, k):
        w, h = surf.get_size()
        pg.draw.rect(surf, track, surf.get_rect(), border_radius=h // 2)
        pad = max(int(h * 0.16), 2)
        knob_d = h - 2 * pad
        knob_x = pad + (w - 2 * pad - knob_d) * fraction
        pg.draw.circle(surf, pg.Color(Colors.white),
                       (int(knob_x + knob_d / 2), h // 2), int(knob_d / 2))
    window.blit(supersample(rect.size, render, scale=6), rect.topleft)


def draw_segmented(window, rect, options, selected_key, font, gap=3):
    n = len(options)
    if n == 0 or rect.width <= gap * (n + 1):
        return {}
    window.blit(rounded_rect_surface(rect.size, 8, Colors.surface_inset,
                                     border=Colors.button_border, border_width=1),
                rect.topleft)
    inner = rect.inflate(-2 * gap, -2 * gap)
    seg_w = (inner.width - gap * (n - 1)) / n
    rects = {}
    for i, (label, key) in enumerate(options):
        sr = pg.Rect(round(inner.x + i * (seg_w + gap)), inner.y, round(seg_w), inner.height)
        if key == selected_key:
            window.blit(rounded_rect_surface(sr.size, 6, Colors.accent), sr.topleft)
            color = Colors.on_accent
        elif sr.collidepoint(pg.mouse.get_pos()):
            color = Colors.white
        else:
            color = Colors.text_dim
        if label == "∞":
            glyph = infinity_surface(int(sr.height * 0.42), color)
        else:
            glyph = fit_text_to_rect(font.render(label, True, color), sr)
        window.blit(glyph, (sr.centerx - glyph.get_width() / 2,
                            sr.centery - glyph.get_height() / 2))
        rects[key] = sr
    return rects


def draw_chip_row(window, rect, options, selected_key, font, gap=5, locked=False):
    n = len(options)
    if n == 0 or rect.width <= gap * (n - 1):
        return {}
    chip_w = (rect.width - gap * (n - 1)) / n
    rects = {}
    mouse = pg.mouse.get_pos()
    for i, (label, key) in enumerate(options):
        cr = pg.Rect(round(rect.x + i * (chip_w + gap)), rect.y, round(chip_w), rect.height)
        is_nav = isinstance(key, str) and key.startswith("__")
        on = (not is_nav) and key == selected_key
        hovered = (not locked) and cr.collidepoint(mouse)
        if locked:
            bg, border = Colors.dark_menu, Colors.button_border
            color = Colors.text_mute if on else Colors.footer_text
        elif on:
            bg, border, color = Colors.surface_inset, Colors.accent, Colors.white
        elif is_nav:
            bg, border, color = Colors.dark_menu, Colors.button_border, Colors.accent_hi
        elif hovered:
            bg, border, color = Colors.button_hover, Colors.button_border, Colors.white
        else:
            bg, border, color = Colors.dark_menu, Colors.button_border, Colors.text_dim
        window.blit(rounded_rect_surface(cr.size, 7, bg, border=border, border_width=1),
                    cr.topleft)
        if label == "∞":
            glyph = infinity_surface(int(cr.height * 0.42), color)
        else:
            glyph = fit_text_to_rect(font.render(label, True, color), cr)
        window.blit(glyph, (cr.centerx - glyph.get_width() // 2,
                            cr.centery - glyph.get_height() // 2))
        rects[key] = cr
    return rects


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
