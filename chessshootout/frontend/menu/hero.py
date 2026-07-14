import math

import pygame as pg

from chessshootout import paths
from chessshootout.domain.match import SINGLE_SCREEN, BOT, ONLINE
from chessshootout.infra import env
from chessshootout.frontend.menu.time_picker import CHAMBERS, INCREMENTS, TimePicker
from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.visual.cache import new_cache, memoized_surface, render_text
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    chevron_surface, cut_rect_surface, dashed_rounded_rect_surface, infinity_surface)
from chessshootout.frontend.visual.emoji import blit_emoji
from chessshootout.frontend.visual.fonts import get_display_font, get_font, get_mono_font
from chessshootout.frontend.visual.icons import draw_clock


TITLE = "READY UP."
TAGLINE = "PAWNS GET WHAT THEY DESERVE"
COMING_SOON = "Hold ya horses, I am cooking that..."
COMING_SOON_KEY = "coming_soon"

MODE_CHIPS = (
    ("Local", SINGLE_SCREEN, False),
    ("Online", ONLINE, False),
    ("Bot", BOT, True),
    ("Puzzles", "puzzles", True),
)
SELECTABLE_MODES = (SINGLE_SCREEN, ONLINE)

SIDE_OPTIONS = (
    ("White", "white"),
    ("Random", "random"),
    ("Black", "black"),
)

TITLE_TOP = 60
TITLE_FONT = 60
TITLE_CAP_H = 56
TAGLINE_FONT = 11
TAGLINE_TRACK = 2
TAGLINE_H = 16
TAGLINE_GAP = 26
MODE_GAP = 30
CHIP_H = 44
CHIP_CUT = 8
MODE_CHIP_PAD_X = 16
MODE_CHIP_GAP = 8
SUMMARY_GAP = 14
CTA_H = 78
CTA_FONT = 34
CTA_CUT = 18
CTA_BOTTOM = 16
LINK_H = 24
FEN_GAP = 10
RECON_H = 46
RECON_GAP = 12
TIME_POPOVER_W = 644
TIME_POPOVER_H = 414
SIDE_POPOVER_W = 190
SIDE_ROW_H = 40

SUMMARY_CHIP_PAD_X = 12
SUMMARY_CHIP_GAP = 7
SUMMARY_CHIP_ICON = 16
SUMMARY_CHIP_CHEVRON = 11
SUMMARY_CHIP_SPACING = 12
SIDE_ICON_SPREAD = 1.55
DASH_LEN = 5
DASH_GAP = 4
LOCK_H = 12
LOCK_GAP = 4
PRESS_OFFSET_PX = 1


_HERO_ART_CACHE = new_cache()


def _side_image(color):
    def build():
        try:
            img = pg.image.load(
                str(paths.resource_path("assets", "pieces_png", f"pawn_{color}.png")))
            return img.convert_alpha()
        except (pg.error, OSError):
            return None
    return memoized_surface(_HERO_ART_CACHE, ("side", color), build)


def _tracked_surface(font, text, color, tracking):
    def build():
        glyphs = [render_text(font, ch, color) for ch in text]
        width = sum(g.get_width() for g in glyphs) + tracking * max(len(glyphs) - 1, 0)
        height = max((g.get_height() for g in glyphs), default=1)
        surf = pg.Surface((max(width, 1), height), pg.SRCALPHA)
        x = 0
        for g in glyphs:
            surf.blit(g, (x, 0))
            x += g.get_width() + tracking
        return surf
    key = ("tagline", text, font.get_height(), str(color), tracking)
    return memoized_surface(_HERO_ART_CACHE, key, build)


class PlayView(MenuView):

    name = "play"

    def __init__(self, app):
        super().__init__(app)
        self.visible = True
        self.reconnect_available = False
        last_mode = env.get_last_mode()
        self.selected_mode = last_mode if last_mode in SELECTABLE_MODES else SINGLE_SCREEN
        self.selected_time_minutes = 10
        self.selected_increment_seconds = 5
        self.selected_side = "random"
        self.apply_default_time_settings()

        self._picker = TimePicker(on_change=self._on_picker_change,
                                  on_tick=app.sound_manager.play_ui_tick)
        self._time_open = False
        self._side_open = False

        self._menu_layout = None
        self._scale = 1.0
        self._hero_rect = pg.Rect(0, 0, 0, 0)
        self._recon_rect = pg.Rect(0, 0, 0, 0)
        self._recon_button = pg.Rect(0, 0, 0, 0)
        self._title_pos = (0, 0)
        self._tagline_pos = (0, 0)
        self._title_block = pg.Rect(0, 0, 0, 0)
        self._chips_block = pg.Rect(0, 0, 0, 0)
        self._mode_rects = {}
        self._time_chip = pg.Rect(0, 0, 0, 0)
        self._side_chip = pg.Rect(0, 0, 0, 0)
        self._cta_rect = pg.Rect(0, 0, 0, 0)
        self._fen_rect = pg.Rect(0, 0, 0, 0)
        self._fen_above = True
        self._time_popover = pg.Rect(0, 0, 0, 0)
        self._side_popover = pg.Rect(0, 0, 0, 0)
        self._side_rects = {}
        self._hover_target = None
        self._press_target = None

        self._title_font = get_display_font(TITLE_FONT)
        self._tagline_font = get_mono_font(TAGLINE_FONT, bold=True)
        self._chip_font = get_font(13, bold=True)
        self._value_font = get_mono_font(13, bold=True)
        self._cta_font = get_display_font(CTA_FONT)
        self._link_font = get_font(12, bold=True)
        self._recon_font = get_font(12, bold=True)

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False
        self._close_popovers()
        self._hover_target = None
        self._press_target = None

    def is_visible(self):
        return self.visible

    def enter(self, payload=None):
        self.show()

    def exit(self):
        self._close_popovers()
        self.hide()

    def apply_default_time_settings(self):
        minutes = env.default_time_minutes()
        if minutes in [value for value, _ in CHAMBERS]:
            self.selected_time_minutes = minutes
        seconds = env.default_increment_seconds()
        if seconds in INCREMENTS:
            self.selected_increment_seconds = seconds
        if self.selected_time_minutes is None:
            self.selected_increment_seconds = 0

    def apply_resume_config(self, resume):
        self.selected_mode = ONLINE
        self.selected_time_minutes = resume["time_minutes"]
        self.selected_increment_seconds = resume["increment_seconds"]
        self.selected_side = resume["your_color"]

    def set_reconnect_available(self, available):
        if self.reconnect_available == available:
            return
        self.reconnect_available = available
        if self._menu_layout is not None:
            self._relayout()

    def cta_label(self):
        return "FIND MATCH" if self.selected_mode == ONLINE else "START MATCH"

    def build_config(self):
        return {
            "mode": self.selected_mode,
            "nickname": env.get_nickname(),
            "time_minutes": self.selected_time_minutes,
            "increment_seconds": self.selected_increment_seconds,
            "side": self.selected_side,
        }

    def _on_picker_change(self):
        self.selected_time_minutes = self._picker.selected_minutes
        self.selected_increment_seconds = self._picker.selected_increment
        if self._menu_layout is not None:
            self._relayout()

    def relayout(self, menu_layout):
        self._menu_layout = menu_layout
        self._scale = menu_layout.scale
        self._relayout()
        if self._time_open:
            self._layout_time_popover()
        elif self._side_open:
            self._layout_side_popover()

    def _s(self, value):
        return max(int(value * self._scale), 1)

    def _relayout(self):
        hero = self._menu_layout.hero_rect
        self._hero_rect = pg.Rect(hero)
        self._fit_fonts()
        x = hero.x
        w = hero.width
        top = hero.y + self._s(TITLE_TOP)
        if self.reconnect_available:
            self._recon_rect = pg.Rect(x, top, w, self._s(RECON_H))
            btn_w = self._s(96)
            self._recon_button = pg.Rect(self._recon_rect.right - self._s(12) - btn_w,
                                         self._recon_rect.y + self._s(8),
                                         btn_w, self._s(RECON_H) - self._s(16))
            top = self._recon_rect.bottom + self._s(RECON_GAP)
        else:
            self._recon_rect = pg.Rect(0, 0, 0, 0)
            self._recon_button = pg.Rect(0, 0, 0, 0)
        self._title_pos = (x, top)
        self._tagline_pos = (x, top + self._s(TITLE_CAP_H) + self._s(TAGLINE_GAP))
        self._layout_title_block()

        mode_y = self._tagline_pos[1] + self._s(TAGLINE_H) + self._s(MODE_GAP)
        self._layout_mode_chips(x, mode_y)
        summary_y = mode_y + self._s(CHIP_H) + self._s(SUMMARY_GAP)
        self._layout_summary_chips(x, summary_y)
        self._layout_chips_block()

        cta_h = self._s(CTA_H)
        cta_bottom = hero.bottom - self._s(CTA_BOTTOM)
        self._cta_rect = pg.Rect(x, cta_bottom - cta_h, w, cta_h)
        self._layout_fen_link()

    def _fit_fonts(self):
        self._title_font = get_display_font(self._s(TITLE_FONT))
        self._tagline_font = get_mono_font(self._s(TAGLINE_FONT), bold=True)
        self._chip_font = get_font(self._s(13), bold=True)
        self._value_font = get_mono_font(self._s(13), bold=True)
        self._cta_font = get_display_font(self._s(CTA_FONT))
        self._link_font = get_font(self._s(12), bold=True)
        self._recon_font = get_font(self._s(12), bold=True)

    def _layout_title_block(self):
        x, top = self._title_pos
        title_w = self._title_font.size(TITLE)[0]
        tagline = self._tagline_surface()
        block_w = max(title_w, tagline.get_width())
        bottom = self._tagline_pos[1] + tagline.get_height()
        self._title_block = pg.Rect(x, top, block_w, bottom - top)

    def _tagline_surface(self):
        return _tracked_surface(self._tagline_font, TAGLINE, Colors.text_muted,
                                self._s(TAGLINE_TRACK))

    def _layout_mode_chips(self, x, y):
        pad = self._s(MODE_CHIP_PAD_X)
        gap = self._s(MODE_CHIP_GAP)
        h = self._s(CHIP_H)
        self._mode_rects = {}
        cx = x
        for label, key, locked in MODE_CHIPS:
            w = self._chip_font.size(label)[0] + 2 * pad
            if locked:
                w += self._s(LOCK_H) + self._s(LOCK_GAP)
            self._mode_rects[key] = pg.Rect(cx, y, w, h)
            cx += w + gap

    def _time_value_surface(self):
        if self.selected_time_minutes is None:
            return infinity_surface(self._value_font.get_height(), Colors.amber_hi)
        text = f"{self.selected_time_minutes}+{self.selected_increment_seconds}"
        return render_text(self._value_font, text, Colors.amber_hi)

    def _side_label_text(self):
        return {"white": "WHITE", "random": "RANDOM", "black": "BLACK"}[self.selected_side]

    def _side_icon_width(self, icon_size):
        if self.selected_side == "random":
            return round(icon_size * SIDE_ICON_SPREAD)
        return icon_size

    def _max_time_value_w(self):
        widest = infinity_surface(self._value_font.get_height(), Colors.amber_hi).get_width()
        for minutes, _ in CHAMBERS:
            if minutes is None:
                continue
            for inc in INCREMENTS:
                text = f"{minutes}+{inc}"
                widest = max(widest, render_text(self._value_font, text,
                                                 Colors.amber_hi).get_width())
        return widest

    def _max_side_label_w(self):
        return max(render_text(self._chip_font, label, Colors.text).get_width()
                   for label in ("WHITE", "RANDOM", "BLACK"))

    def _layout_summary_chips(self, x, y):
        pad = self._s(SUMMARY_CHIP_PAD_X)
        gap = self._s(SUMMARY_CHIP_GAP)
        icon = self._s(SUMMARY_CHIP_ICON)
        chevron = self._s(SUMMARY_CHIP_CHEVRON)
        h = self._s(CHIP_H)
        chip_gap = self._s(SUMMARY_CHIP_SPACING)

        time_w = pad + icon + gap + self._max_time_value_w() + gap + chevron + pad
        self._time_chip = pg.Rect(x, y, time_w, h)

        side_icon_w = round(icon * SIDE_ICON_SPREAD)
        side_w = pad + side_icon_w + gap + self._max_side_label_w() + gap + chevron + pad
        self._side_chip = pg.Rect(x + time_w + chip_gap, y, side_w, h)

    def _layout_chips_block(self):
        block = self._time_chip.union(self._side_chip)
        for rect in self._mode_rects.values():
            block = block.union(rect)
        self._chips_block = block

    def _layout_fen_link(self):
        x = self._hero_rect.x
        w = self._hero_rect.width
        link_h = self._s(LINK_H)
        below_top = self._cta_rect.bottom + self._s(FEN_GAP)
        if below_top + link_h <= self._hero_rect.bottom:
            self._fen_rect = pg.Rect(x, below_top, w, link_h)
            self._fen_above = False
        else:
            self._fen_rect = pg.Rect(x, self._cta_rect.top - self._s(FEN_GAP) - link_h, w, link_h)
            self._fen_above = True

    def _fit_popover(self, base_w, base_h, anchor_left, chip):
        win_w, win_h = self.app.window.get_size()
        top_limit = self.app.chrome.HEIGHT
        hero = self._hero_rect
        gap = self._s(8)
        below = (win_h - 4) - (chip.bottom + gap)
        above = (chip.top - gap) - (top_limit + 4)
        avail_v = max(below, above, 1)
        avail_w = max(hero.width, 1)
        shrink = min(1.0, avail_w / base_w, avail_v / base_h)
        pw = min(int(base_w * shrink), avail_w)
        ph = int(base_h * shrink)
        px = min(max(anchor_left, hero.left), hero.right - pw)
        px = min(max(px, 4), win_w - pw - 4)
        if chip.bottom + gap + ph <= win_h - 4:
            py = chip.bottom + gap
        else:
            py = max(chip.top - gap - ph, top_limit + 4)
        return pg.Rect(px, py, max(pw, 1), max(ph, 1)), shrink

    def _layout_time_popover(self):
        self._time_popover, shrink = self._fit_popover(
            self._s(TIME_POPOVER_W), self._s(TIME_POPOVER_H),
            self._hero_rect.x, self._time_chip)
        pad = max(int(self._s(14) * shrink), 4)
        self._picker.set_rect(self._time_popover.inflate(-2 * pad, -2 * pad))

    def _layout_side_popover(self):
        rows = len(SIDE_OPTIONS)
        base_h = self._s(SIDE_ROW_H) * rows + self._s(8) * (rows + 1)
        self._side_popover, shrink = self._fit_popover(
            self._s(SIDE_POPOVER_W), base_h, self._side_chip.x, self._side_chip)
        pad = max(int(self._s(8) * shrink), 3)
        row_h = max(int(self._s(SIDE_ROW_H) * shrink), 1)
        self._side_rects = {}
        ry = self._side_popover.y + pad
        for _, key in SIDE_OPTIONS:
            self._side_rects[key] = pg.Rect(self._side_popover.x + pad, ry,
                                            self._side_popover.width - 2 * pad, row_h)
            ry += row_h + pad

    def _open_time_popover(self):
        self._picker.set_selection(self.selected_time_minutes,
                                   self.selected_increment_seconds)
        self._time_open = True
        self._layout_time_popover()

    def _open_side_popover(self):
        self._side_open = True
        self._layout_side_popover()

    def _close_popovers(self):
        self._time_open = False
        self._side_open = False

    def escape(self):
        if self._time_open or self._side_open:
            self._close_popovers()
            return True
        return False

    def update(self, now):
        if self._time_open:
            self._picker.update(now)

    def active_scrollable(self, pos=None):
        return self._picker if self._time_open else None

    def avoid_rects(self):
        if not self.visible or self._hero_rect.width <= 0:
            return []
        rects = [self._chips_block]
        if self.reconnect_available and self._recon_rect.width > 0:
            rects.append(self._recon_rect)
        if self._time_open:
            rects.append(self._time_popover)
        elif self._side_open:
            rects.append(self._side_popover)
        return rects

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._time_open:
            if self._time_popover.collidepoint(pos):
                self._picker.handle_click(pos)
                self.app.input_router._click_sound_played = True
            else:
                self._close_popovers()
            return True
        if self._side_open:
            if self._side_popover.collidepoint(pos):
                self._handle_side_click(pos)
            else:
                self._close_popovers()
            return True
        return self._handle_hero_click(pos)

    def _handle_hero_click(self, pos):
        if self.reconnect_available and self._recon_button.collidepoint(pos):
            self.app.coordinator.reconnect()
            return True
        for label, key, locked in MODE_CHIPS:
            if self._mode_rects[key].collidepoint(pos):
                if locked:
                    self.app.toast.show(COMING_SOON, key=COMING_SOON_KEY)
                else:
                    self.selected_mode = key
                return True
        if self._time_chip.collidepoint(pos):
            self._open_time_popover()
            return True
        if self._side_chip.collidepoint(pos):
            self._open_side_popover()
            return True
        if self._cta_rect.collidepoint(pos):
            self.app._on_start_game(self.build_config())
            return True
        if self.selected_mode != ONLINE and self._fen_rect.collidepoint(pos):
            self.app._on_open_fen_modal()
            return True
        return False

    def _handle_side_click(self, pos):
        for key, rect in self._side_rects.items():
            if rect.collidepoint(pos):
                self.selected_side = key
                if self._menu_layout is not None:
                    self._relayout()
                return

    def _hover_hit(self, pos):
        if self._cta_rect.collidepoint(pos):
            return "cta"
        for label, key, locked in MODE_CHIPS:
            if locked:
                continue
            if self._mode_rects[key].collidepoint(pos):
                return f"mode:{key}"
        if self._time_chip.collidepoint(pos):
            return "time"
        if self._side_chip.collidepoint(pos):
            return "side"
        return None

    def handle_press(self, pos):
        if not self.visible or self._time_open or self._side_open:
            return False
        target = self._hover_hit(pos)
        if target is None:
            return False
        self._press_target = target
        return True

    def handle_motion(self, pos):
        if not self.visible or self._time_open or self._side_open:
            self._hover_target = None
            return False
        self._hover_target = self._hover_hit(pos)
        return True

    def handle_release(self, pos):
        had_press = self._press_target is not None
        self._press_target = None
        return had_press

    def handle_key(self, event):
        return False

    def draw(self, window, menu_layout):
        if not self.visible:
            return
        if self.reconnect_available:
            self._draw_recon(window)
        window.blit(render_text(self._title_font, TITLE, Colors.text), self._title_pos)
        window.blit(self._tagline_surface(), self._tagline_pos)
        self._draw_mode_chips(window)
        self._draw_time_chip(window)
        self._draw_side_chip(window)
        self._draw_cta(window)
        if self.selected_mode != ONLINE:
            self._draw_fen_link(window)
        if self._time_open:
            self._draw_time_popover(window)
        elif self._side_open:
            self._draw_side_popover(window)

    def _draw_recon(self, window):
        fill = pg.Color(Colors.amber).lerp(pg.Color(Colors.surface_raised), 0.84)
        window.blit(cut_rect_surface(self._recon_rect.size, self._s(CHIP_CUT), fill,
                                     border=Colors.amber, border_width=1,
                                     corners=("tr", "bl")), self._recon_rect.topleft)
        dot = max(self._s(4), 3)
        pg.draw.circle(window, Colors.amber,
                       (self._recon_rect.x + self._s(16), self._recon_rect.centery), dot)
        text = render_text(self._recon_font, "You have a game in progress", Colors.text)
        window.blit(text, (self._recon_rect.x + self._s(30),
                           self._recon_rect.centery - text.get_height() // 2))
        window.blit(cut_rect_surface(self._recon_button.size, self._s(6), Colors.surface,
                                     border=Colors.amber, border_width=1, corners=("tr", "bl")),
                    self._recon_button.topleft)
        label = render_text(self._recon_font, "Reconnect", Colors.amber_hi)
        window.blit(label, (self._recon_button.centerx - label.get_width() // 2,
                            self._recon_button.centery - label.get_height() // 2))

    def _draw_mode_chips(self, window):
        for label, key, locked in MODE_CHIPS:
            rect = self._mode_rects[key]
            if locked:
                window.blit(dashed_rounded_rect_surface(
                    rect.size, self._s(7), Colors.border, border_width=1,
                    dash=self._s(DASH_LEN), gap=self._s(DASH_GAP), fill=Colors.surface),
                    rect.topleft)
                text = render_text(self._chip_font, label, Colors.text_muted)
                lock_h = self._s(LOCK_H)
                gap = self._s(LOCK_GAP)
                total = lock_h + gap + text.get_width()
                lx = rect.centerx - total // 2
                self._draw_lock(window, lx + lock_h // 2, rect.centery, lock_h,
                                Colors.text_muted)
                window.blit(text, (lx + lock_h + gap, rect.centery - text.get_height() // 2))
                continue
            selected = key == self.selected_mode
            target = f"mode:{key}"
            hovered = self._hover_target == target
            pressed = self._press_target == target and hovered
            fill = Colors.surface_raised if selected else (
                Colors.surface_hover if hovered else Colors.surface)
            border = Colors.accent if selected else Colors.border
            color = Colors.text if selected or hovered else Colors.text_dim
            window.blit(cut_rect_surface(rect.size, self._s(CHIP_CUT), fill,
                                         border=border, border_width=1, corners=("tr", "bl")),
                        rect.topleft)
            text = render_text(self._chip_font, label, color)
            offset = self._s(PRESS_OFFSET_PX) if pressed else 0
            window.blit(text, (rect.centerx - text.get_width() // 2,
                               rect.centery - text.get_height() // 2 + offset))

    def _draw_lock(self, window, cx, cy, h, color):
        body_w = max(int(h * 0.72), 4)
        body_h = max(int(h * 0.5), 3)
        body = pg.Rect(cx - body_w // 2, cy - body_h // 2 + int(h * 0.14), body_w, body_h)
        pg.draw.rect(window, color, body, border_radius=max(int(h * 0.12), 1))
        sr = max(int(body_w * 0.3), 2)
        pg.draw.arc(window, color, pg.Rect(cx - sr, body.top - sr, 2 * sr, 2 * sr),
                    0.25, math.pi - 0.25, max(int(h * 0.12), 2))

    def _draw_time_chip(self, window):
        rect = self._time_chip
        hovered = self._hover_target == "time"
        pressed = self._press_target == "time" and hovered
        fill = Colors.surface_hover if hovered else (
            pg.Color(Colors.amber).lerp(pg.Color(Colors.surface_raised), 0.84))
        window.blit(cut_rect_surface(rect.size, self._s(CHIP_CUT), fill,
                                     border=Colors.amber, border_width=1, corners=("tr",)),
                    rect.topleft)
        pad = self._s(SUMMARY_CHIP_PAD_X)
        gap = self._s(SUMMARY_CHIP_GAP)
        icon = self._s(SUMMARY_CHIP_ICON)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        icon_rect = pg.Rect(rect.x + pad, rect.y + offset, icon, rect.height)
        draw_clock(window, icon_rect, Colors.amber_hi)
        value = self._time_value_surface()
        window.blit(value, (icon_rect.right + gap,
                            rect.centery - value.get_height() // 2 + offset))
        chevron = chevron_surface(self._s(SUMMARY_CHIP_CHEVRON), Colors.amber_hi,
                                  up=self._time_open)
        window.blit(chevron, (rect.right - pad - chevron.get_width(),
                              rect.centery - chevron.get_height() // 2 + offset))

    def _draw_side_chip(self, window):
        rect = self._side_chip
        hovered = self._hover_target == "side"
        pressed = self._press_target == "side" and hovered
        border = Colors.accent if self._side_open else (
            Colors.border_strong if hovered else Colors.border)
        fill = Colors.surface_hover if hovered else Colors.surface
        window.blit(cut_rect_surface(rect.size, self._s(CHIP_CUT), fill,
                                     border=border, border_width=1, corners=("tr",)),
                    rect.topleft)
        pad = self._s(SUMMARY_CHIP_PAD_X)
        gap = self._s(SUMMARY_CHIP_GAP)
        icon = self._s(SUMMARY_CHIP_ICON)
        icon_w = self._side_icon_width(icon)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        self._draw_summary_side_icon(window, rect.x + pad, rect.centery + offset, icon)
        label = render_text(self._chip_font, self._side_label_text(), Colors.text)
        window.blit(label, (rect.x + pad + icon_w + gap,
                            rect.centery - label.get_height() // 2 + offset))
        chevron = chevron_surface(self._s(SUMMARY_CHIP_CHEVRON), Colors.text_dim,
                                  up=self._side_open)
        window.blit(chevron, (rect.right - pad - chevron.get_width(),
                              rect.centery - chevron.get_height() // 2 + offset))

    def _draw_summary_side_icon(self, window, x, cy, size):
        if self.selected_side == "random":
            step = round(size * (SIDE_ICON_SPREAD - 1.0))
            self._blit_pawn(window, x + size // 2, cy, size, "white")
            self._blit_pawn(window, x + step + size // 2, cy, size, "black")
        else:
            self._blit_pawn(window, x + size // 2, cy, size, self.selected_side)

    def _blit_pawn(self, window, cx, cy, size, color):
        img = _side_image(color)
        if img is not None:
            scaled = pg.transform.smoothscale(img, (size, size))
            window.blit(scaled, (cx - size // 2, cy - size // 2))

    def _draw_cta(self, window):
        hovered = self._hover_target == "cta"
        pressed = self._press_target == "cta" and hovered
        fill = Colors.accent_press if pressed else (
            Colors.accent_hi if hovered else Colors.accent)
        window.blit(cut_rect_surface(self._cta_rect.size, self._s(CTA_CUT), fill,
                                     corners=("tr", "bl")), self._cta_rect.topleft)
        text = render_text(self._cta_font, self.cta_label(), Colors.on_accent)
        offset = self._s(PRESS_OFFSET_PX) if pressed else 0
        window.blit(text, (self._cta_rect.centerx - text.get_width() // 2,
                           self._cta_rect.centery - text.get_height() // 2 + offset))

    def _draw_fen_link(self, window):
        hovered = self._fen_rect.collidepoint(pg.mouse.get_pos())
        color = Colors.text_dim if hovered else Colors.text_muted
        text = render_text(self._link_font, "Start from FEN", color)
        window.blit(text, (self._fen_rect.x, self._fen_rect.centery - text.get_height() // 2))

    def _draw_time_popover(self, window):
        window.blit(cut_rect_surface(self._time_popover.size, self._s(CTA_CUT),
                                     Colors.surface_raised, border=Colors.border_strong,
                                     border_width=1, corners=("tr", "bl")),
                    self._time_popover.topleft)
        self._picker.draw(window, pg.time.get_ticks())

    def _draw_side_popover(self, window):
        window.blit(cut_rect_surface(self._side_popover.size, self._s(CTA_CUT),
                                     Colors.surface_raised, border=Colors.border_strong,
                                     border_width=1, corners=("tr", "bl")),
                    self._side_popover.topleft)
        mouse = pg.mouse.get_pos()
        for label, key in SIDE_OPTIONS:
            rect = self._side_rects[key]
            selected = key == self.selected_side
            hovered = rect.collidepoint(mouse)
            fill = Colors.surface_active if selected else (
                Colors.surface_hover if hovered else Colors.surface)
            border = Colors.accent if selected else Colors.border
            window.blit(cut_rect_surface(rect.size, self._s(6), fill, border=border,
                                         border_width=1, corners=("tr", "bl")), rect.topleft)
            self._draw_side_icon(window, rect, key)
            color = Colors.text if selected or hovered else Colors.text_dim
            text = render_text(self._chip_font, label, color)
            window.blit(text, (rect.x + self._s(44), rect.centery - text.get_height() // 2))

    def _draw_side_icon(self, window, rect, key):
        size = int(rect.height * 0.7)
        cx = rect.x + self._s(22)
        cy = rect.centery
        if key == "random":
            if not blit_emoji(window, "🎲", (cx, cy), size):
                pg.draw.rect(window, Colors.text_dim,
                             pg.Rect(cx - size // 2, cy - size // 2, size, size), 1,
                             border_radius=4)
            return
        img = _side_image(key)
        if img is not None:
            scaled = pg.transform.smoothscale(img, (size, size))
            window.blit(scaled, (cx - size // 2, cy - size // 2))
