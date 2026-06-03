import pygame as pg

from frontend.visual.colors import Colors
from frontend.visual.draw import rounded_rect_surface
from frontend.visual.emoji import emoji_surface
from frontend.visual.fonts import get_font


PAD_L = 18
PAD_R = 16
PAD_V = 13
GAP = 14
ACTS_GAP = 8
ICON_SIZE = 30
TOP_MARGIN = 14
STACK_GAP = 9
BTN_MIN_W = 78
BTN_RADIUS = 7
BTN_PAD_X = 14
BTN_PAD_Y = 8
SLIDE_MS = 260


def _button_surface(label, font, ok):
    text = font.render(label, True, Colors.on_accent if ok else Colors.text)
    w = max(text.get_width() + 2 * BTN_PAD_X, BTN_MIN_W)
    h = text.get_height() + 2 * BTN_PAD_Y
    if ok:
        surf = rounded_rect_surface((w, h), BTN_RADIUS, Colors.accent)
    else:
        surf = rounded_rect_surface((w, h), BTN_RADIUS, Colors.surface_raised,
                                    border=Colors.border, border_width=1)
    surf.blit(text, ((w - text.get_width()) / 2, (h - text.get_height()) / 2))
    return surf


class OfferBanners:

    def __init__(self, window):
        self.window = window
        self._banners = []

    def push(self, key, icon, name, verb, ok_label, no_label, on_ok, on_no):
        self._banners = [b for b in self._banners if b["key"] != key]
        self._banners.append({
            "key": key, "icon": icon, "name": name, "verb": verb,
            "ok_label": ok_label, "no_label": no_label,
            "on_ok": on_ok, "on_no": on_no,
            "pushed_at": pg.time.get_ticks(),
            "ok_rect": pg.Rect(0, 0, 0, 0), "no_rect": pg.Rect(0, 0, 0, 0),
        })

    def clear(self):
        self._banners = []

    def is_empty(self):
        return not self._banners

    def count(self):
        return len(self._banners)

    def _banner_height(self, name_font, btn_font):
        content_h = max(ICON_SIZE, name_font.get_height(),
                        btn_font.get_height() + 2 * BTN_PAD_Y)
        return content_h + 2 * PAD_V

    def draw(self, board_rect):
        if not self._banners or board_rect.width <= 0:
            return
        name_font = get_font(13, bold=True)
        verb_font = get_font(13, bold=True)
        btn_font = get_font(12, bold=True)
        h = self._banner_height(name_font, btn_font)
        now = pg.time.get_ticks()
        prev_clip = self.window.get_clip()
        self.window.set_clip(board_rect)
        target_y = board_rect.top + TOP_MARGIN
        for b in self._banners:
            t = min(1.0, (now - b["pushed_at"]) / SLIDE_MS)
            eased = 1 - (1 - t) ** 3
            start_y = board_rect.top - h
            y = start_y + (target_y - start_y) * eased
            self._draw_one(b, board_rect, y, h, name_font, verb_font, btn_font)
            target_y += h + STACK_GAP
        self.window.set_clip(prev_clip)

    def _draw_one(self, b, board_rect, y, h, name_font, verb_font, btn_font):
        name_surf = name_font.render(b["name"], True, Colors.amber_hi)
        verb_surf = verb_font.render(f" {b['verb']}", True, Colors.text)
        msg_w = name_surf.get_width() + verb_surf.get_width()
        no_surf = _button_surface(b["no_label"], btn_font, False)
        ok_surf = _button_surface(b["ok_label"], btn_font, True)
        acts_w = no_surf.get_width() + ACTS_GAP + ok_surf.get_width()
        w = PAD_L + ICON_SIZE + GAP + msg_w + GAP + acts_w + PAD_R
        x = board_rect.centerx - w / 2
        pill = rounded_rect_surface((int(w), int(h)), h // 2, Colors.surface,
                                    border=Colors.border_strong, border_width=1)
        self.window.blit(pill, (x, y))
        cy = y + h / 2
        ix = x + PAD_L
        chip = rounded_rect_surface((ICON_SIZE, ICON_SIZE), 8, Colors.icon_chip_bg)
        self.window.blit(chip, (ix, cy - ICON_SIZE / 2))
        glyph = emoji_surface(b["icon"], 17)
        if glyph is not None:
            self.window.blit(glyph, (ix + (ICON_SIZE - glyph.get_width()) / 2,
                                     cy - glyph.get_height() / 2))
        mx = ix + ICON_SIZE + GAP
        self.window.blit(name_surf, (mx, cy - name_surf.get_height() / 2))
        self.window.blit(verb_surf, (mx + name_surf.get_width(),
                                     cy - verb_surf.get_height() / 2))
        ax = mx + msg_w + GAP
        self.window.blit(no_surf, (ax, cy - no_surf.get_height() / 2))
        ox = ax + no_surf.get_width() + ACTS_GAP
        self.window.blit(ok_surf, (ox, cy - ok_surf.get_height() / 2))
        b["no_rect"] = pg.Rect(ax, cy - no_surf.get_height() / 2,
                               no_surf.get_width(), no_surf.get_height())
        b["ok_rect"] = pg.Rect(ox, cy - ok_surf.get_height() / 2,
                               ok_surf.get_width(), ok_surf.get_height())

    def handle_click(self, pos):
        for b in list(self._banners):
            if b["ok_rect"].collidepoint(pos):
                self._banners.remove(b)
                b["on_ok"]()
                return True
            if b["no_rect"].collidepoint(pos):
                self._banners.remove(b)
                b["on_no"]()
                return True
        return False
