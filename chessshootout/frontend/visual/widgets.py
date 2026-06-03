import math

import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    supersample, rounded_rect_surface, infinity_surface, blit_centered,
)


SCROLL_FADE_MS = 2000
SCROLL_THUMB_WIDTH = 4
SCROLL_THUMB_RIGHT_OFFSET = 4
SCROLL_THUMB_MIN_HEIGHT = 18
BUTTON_LABEL_PADDING_PX = 6
BUTTON_RADIUS = 8
PILL_PAD_Y = 6
SEGMENT_RADIUS = 8
SEGMENT_INNER_RADIUS = 6
CHIP_RADIUS = 7


def build_shell(w, h, winking=False):
    def render(surf, k):
        width, height = surf.get_size()
        split = int(height * 0.78)
        top = pg.Color(Colors.shell_red_hi if winking else Colors.shell_red)
        red = pg.Color(Colors.shell_red)
        brass = pg.Color(Colors.shell_brass)
        for y in range(height):
            if y < split:
                col = top.lerp(red, y / max(split - 1, 1))
            else:
                col = brass
            surf.fill(col, pg.Rect(0, y, width, 1))
        mask = pg.Surface((width, height), pg.SRCALPHA)
        pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_radius=max(int(2 * k), 1))
        surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
    return supersample((max(w, 1), max(h, 1)), render)


def build_ko_badge(count, font, height, winking=False):
    shell_w = max(int(height * 0.16), 4)
    shell_h = max(int(height * 0.42), 7)
    gap = max(int(height * 0.12), 3)
    text = font.render(f"{count} KO", True,
                       pg.Color(Colors.amber if winking else Colors.text_muted))
    th = text.get_height()
    h = max(shell_h, th)
    surf = pg.Surface((shell_w + gap + text.get_width(), h), pg.SRCALPHA)
    surf.blit(build_shell(shell_w, shell_h, winking), (0, (h - shell_h) // 2))
    surf.blit(text, (shell_w + gap, (h - th) // 2))
    return surf


def build_avatar(size, top, bottom):
    size = max(int(size), 1)
    radius = max(int(size * 0.22), 2)
    top = pg.Color(top)
    bottom = pg.Color(bottom)

    def render(surf, k):
        w = surf.get_width()
        for y in range(w):
            t = y / max(w - 1, 1)
            surf.fill(top.lerp(bottom, t), pg.Rect(0, y, w, 1))
        mask = pg.Surface((w, w), pg.SRCALPHA)
        pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_radius=int(radius * k))
        surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        pg.draw.rect(surf, (0, 0, 0, 80), surf.get_rect(),
                     width=max(int(k), 1), border_radius=int(radius * k))
    return supersample(size, render)


def draw_pill(window, text, x, cy, font, text_color=Colors.amber_hi,
              bg=Colors.mode_pill_bg, border=Colors.mode_pill_border):
    surf = font.render(text, True, text_color)
    pad_x = max(int(surf.get_height() * 0.6), 5)
    w = surf.get_width() + 2 * pad_x
    h = surf.get_height() + PILL_PAD_Y
    chip = rounded_rect_surface((w, h), h // 2, bg,
                                border=border, border_width=1)
    window.blit(chip, (x, round(cy - h / 2)))
    blit_centered(window, surf, (x + w / 2, cy))
    return x + w


def draw_series_chip(window, center, name_a, name_b, score, name_font, score_font,
                     pad_x=12, pad_y=6, gap=10):
    a = name_font.render(name_a, True, Colors.text_dim)
    b = name_font.render(name_b, True, Colors.text_dim)
    sc = score_font.render(score, True, Colors.amber_hi)
    h = max(a.get_height(), b.get_height(), sc.get_height()) + 2 * pad_y
    w = a.get_width() + sc.get_width() + b.get_width() + 2 * gap + 2 * pad_x
    chip = rounded_rect_surface((w, h), h // 2, Colors.surface,
                                border=Colors.border, border_width=1)
    x0 = round(center[0] - w / 2)
    y0 = round(center[1] - h / 2)
    window.blit(chip, (x0, y0))
    cy = center[1]
    x = x0 + pad_x
    blit_centered(window, a, (x + a.get_width() / 2, cy))
    x += a.get_width() + gap
    blit_centered(window, sc, (x + sc.get_width() / 2, cy))
    x += sc.get_width() + gap
    blit_centered(window, b, (x + b.get_width() / 2, cy))
    return pg.Rect(x0, y0, w, h)


def fit_text_to_rect(text_surface, rect, padding=BUTTON_LABEL_PADDING_PX):
    max_w = max(rect.width - 2 * padding, 1)
    max_h = max(rect.height - 2 * padding, 1)
    tw, th = text_surface.get_size()
    if tw <= max_w and th <= max_h:
        return text_surface
    scale = min(max_w / tw, max_h / th)
    new_size = (max(int(tw * scale), 1), max(int(th * scale), 1))
    return pg.transform.smoothscale(text_surface, new_size)


def _hover_state(rect):
    hovered = rect.collidepoint(pg.mouse.get_pos())
    pressed = hovered and pg.mouse.get_pressed()[0]
    return hovered, pressed


def _button_bg(rect, force_pressed=False, disabled=False):
    if disabled:
        return Colors.surface, Colors.text_muted
    hovered, pressed = _hover_state(rect)
    if force_pressed or pressed:
        return Colors.surface_active, Colors.text
    if hovered:
        return Colors.surface_hover, Colors.text
    return Colors.surface_raised, Colors.text_dim


def draw_button(window, rect, label, font, force_pressed=False, disabled=False,
                selected=False, primary=False):
    if primary and not disabled:
        hovered, pressed = _hover_state(rect)
        bg = Colors.accent_press if pressed else (Colors.accent_hi if hovered else Colors.accent)
        text_color = Colors.on_accent
        border = bg
    else:
        bg, text_color = _button_bg(rect, force_pressed or selected, disabled)
        border = Colors.accent if (selected and not disabled) else Colors.border
    window.blit(rounded_rect_surface(rect.size, BUTTON_RADIUS, bg, border=border,
                                     border_width=1), rect.topleft)
    text = fit_text_to_rect(font.render(label, True, text_color), rect)
    window.blit(
        text,
        (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
    )


def draw_icon_button(window, rect, icon_fn, force_pressed=False, disabled=False, muted=False):
    if muted and not disabled:
        pg.draw.rect(window, Colors.surface_active, rect, border_radius=BUTTON_RADIUS)
        pg.draw.rect(window, Colors.accent, rect, 1, border_radius=BUTTON_RADIUS)
    elif not disabled:
        hovered, pressed = _hover_state(rect)
        if force_pressed or pressed:
            bg = Colors.surface_active
        elif hovered:
            bg = Colors.surface_hover
        else:
            bg = Colors.surface_raised
        pg.draw.rect(window, bg, rect, border_radius=BUTTON_RADIUS)
        pg.draw.rect(window, Colors.border, rect, 1, border_radius=BUTTON_RADIUS)
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
            pg.draw.polygon(surf, Colors.text, [
                (cx + dx * r0 + px * hw_base, cy + dy * r0 + py * hw_base),
                (cx + dx * r0 - px * hw_base, cy + dy * r0 - py * hw_base),
                (cx + dx * r1 - px * hw_tip, cy + dy * r1 - py * hw_tip),
                (cx + dx * r1 + px * hw_tip, cy + dy * r1 + py * hw_tip),
            ])
        hole_r = r * 0.40
        pg.draw.circle(surf, Colors.text, (int(cx), int(cy)), int(r), width=int(r - hole_r))

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


def draw_toggle(window, rect, fraction):
    fraction = max(0.0, min(1.0, fraction))
    track = pg.Color(Colors.surface_active).lerp(pg.Color(Colors.accent), fraction)

    def render(surf, k):
        w, h = surf.get_size()
        pg.draw.rect(surf, track, surf.get_rect(), border_radius=h // 2)
        pad = max(int(h * 0.16), 2)
        knob_d = h - 2 * pad
        knob_x = pad + (w - 2 * pad - knob_d) * fraction
        pg.draw.circle(surf, pg.Color(Colors.text),
                       (int(knob_x + knob_d / 2), h // 2), int(knob_d / 2))
    window.blit(supersample(rect.size, render, scale=6), rect.topleft)


def draw_segmented(window, rect, options, selected_key, font, gap=3):
    n = len(options)
    if n == 0 or rect.width <= gap * (n + 1):
        return {}
    window.blit(rounded_rect_surface(rect.size, SEGMENT_RADIUS, Colors.surface_raised,
                                     border=Colors.border, border_width=1),
                rect.topleft)
    inner = rect.inflate(-2 * gap, -2 * gap)
    seg_w = (inner.width - gap * (n - 1)) / n
    rects = {}
    for i, (label, key) in enumerate(options):
        sr = pg.Rect(round(inner.x + i * (seg_w + gap)), inner.y, round(seg_w), inner.height)
        if key == selected_key:
            window.blit(rounded_rect_surface(sr.size, SEGMENT_INNER_RADIUS, Colors.accent),
                        sr.topleft)
            color = Colors.on_accent
        elif sr.collidepoint(pg.mouse.get_pos()):
            color = Colors.text
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
            bg, border = Colors.surface, Colors.border
            color = Colors.text_muted
        elif on:
            bg, border, color = Colors.surface_raised, Colors.accent, Colors.text
        elif is_nav:
            bg, border, color = Colors.surface, Colors.border, Colors.accent_hi
        elif hovered:
            bg, border, color = Colors.surface_hover, Colors.border, Colors.text
        else:
            bg, border, color = Colors.surface, Colors.border, Colors.text_dim
        window.blit(rounded_rect_surface(cr.size, CHIP_RADIUS, bg, border=border, border_width=1),
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
        window, Colors.surface_hover,
        pg.Rect(thumb_x, thumb_y, SCROLL_THUMB_WIDTH, thumb_h),
        border_radius=SCROLL_THUMB_WIDTH // 2,
    )
