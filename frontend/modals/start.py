import pygame as pg

import paths
from backend.match import SINGLE_SCREEN, BOT, ONLINE
from frontend import env
from frontend.visual.colors import Colors
from frontend.visual.draw import rounded_rect_surface, supersample
from frontend.visual.emoji import blit_emoji, emoji_surface
from frontend.visual.fonts import get_display_font, get_font, get_mono_font
from frontend.visual.text_input import TextInput
from frontend.visual.widgets import draw_chip_row, draw_gear, draw_segmented


MODE_OPTIONS = [
    ("Local", SINGLE_SCREEN),
    ("vs Bot", BOT),
    ("Online", ONLINE),
]

TIME_PAGES = [
    [("10", 10), ("15", 15), ("30", 30), ("∞", None)],
    [("1", 1), ("2", 2), ("3", 3), ("5", 5)],
]

INCREMENT_OPTIONS = [("0", 0), ("2", 2), ("5", 5), ("10", 10), ("15", 15)]

SIDE_OPTIONS = [
    ("White", "white"),
    ("Random", "random"),
    ("Black", "black"),
]

ALL_TIME_VALUES = [value for page in TIME_PAGES for _, value in page]

WORDMARK_TOP = "CHESS"
WORDMARK_BOTTOM = "SHOOTOUT"
TAGLINE = "PAWNS GET WHAT THEY DESERVE"

FOOTER_PREFIX = "Chess Shootout {label} - Designed and developed by "
FOOTER_LINK_TEXT = "xiaomyung"
FOOTER_URL = "https://github.com/xiaomyung"
FOOTER_MARGIN_PX = 10
FOOTER_LINK_HITBOX_PAD_PX = 9
FOOTER_SHINE_PERIOD_MS = 10000
FOOTER_SHINE_SWEEP_MS = 1100
FOOTER_SHINE_HOVER_PERIOD_MS = 500
FOOTER_SHINE_HOVER_SWEEP_MS = 450
FOOTER_SHINE_MAX_ALPHA = 200


def footer_prefix_text():
    version = paths.get_app_version()
    label = "v" + version if version else "(dev)"
    return FOOTER_PREFIX.format(label=label)


class StartMenu:

    def __init__(self, window, callbacks):
        self.window = window
        self.callbacks = callbacks
        self.visible = True

        self.text_input = TextInput(window, max_chars=20, placeholder="Enter a nickname")
        self.text_input.text = env.get_nickname()

        last_mode = env.get_last_mode()
        self.selected_mode = (
            last_mode if last_mode in (SINGLE_SCREEN, BOT, ONLINE) else SINGLE_SCREEN
        )
        self.selected_time_minutes = 10
        self.selected_increment_seconds = 5
        self.selected_side = "random"
        self.apply_default_time_settings()
        self._time_page = 0

        self._side_imgs = {}
        for color in ("white", "black"):
            try:
                img = pg.image.load(
                    str(paths.resource_path("assets", "pieces_img", f"pawn_{color}.png")))
                self._side_imgs[color] = img.convert_alpha()
            except (pg.error, OSError):
                self._side_imgs[color] = None
        try:
            self._brand_mark = pg.image.load(
                str(paths.resource_path("assets", "icons", "brand_mark.png"))).convert_alpha()
        except (pg.error, OSError):
            self._brand_mark = None

        self._outer = pg.Rect(0, 0, 0, 0)
        self._scale = 1.0
        self._tile_cache = None
        self._start_cache = None
        self._gear_rect = pg.Rect(0, 0, 0, 0)
        self._tile_rect = pg.Rect(0, 0, 0, 0)
        self._wordmark_top = (0, 0)
        self._wordmark_bottom = (0, 0)
        self._tagline_pos = (0, 0)
        self._recon_rect = pg.Rect(0, 0, 0, 0)
        self._recon_button_rect = pg.Rect(0, 0, 0, 0)
        self._input_rect = pg.Rect(0, 0, 0, 0)
        self._mode_label_pos = (0, 0)
        self._mode_rect = pg.Rect(0, 0, 0, 0)
        self._time_label_pos = (0, 0)
        self._incr_label_pos = (0, 0)
        self._time_rect = pg.Rect(0, 0, 0, 0)
        self._incr_rect = pg.Rect(0, 0, 0, 0)
        self._side_label_pos = (0, 0)
        self._side_rect = pg.Rect(0, 0, 0, 0)
        self._start_rect = pg.Rect(0, 0, 0, 0)
        self._history_rect = pg.Rect(0, 0, 0, 0)
        self._fen_rect = pg.Rect(0, 0, 0, 0)

        self._mode_rects = {}
        self._time_rects = {}
        self._incr_rects = {}
        self._side_rects = {}

        self.label_font = get_font(11, bold=True)
        self.seg_font = get_font(13, bold=True)
        self.chip_font = get_mono_font(13, bold=True)
        self.button_font = get_font(13, bold=True)
        self.wordmark_font = get_display_font(34)
        self.tagline_font = get_font(10, bold=True)
        self.start_font = get_display_font(22)
        self.recon_font = get_font(12, bold=True)

        self._footer_prefix_surf = None
        self._footer_link_surf = None
        self._footer_link_mask_surf = None
        self._footer_shine_band = None
        self._footer_shine_w = 0
        self._footer_prefix_pos = (0, 0)
        self._footer_link_rect = pg.Rect(0, 0, 0, 0)
        self._footer_link_hitbox = pg.Rect(0, 0, 0, 0)
        self._footer_underline_y = 0

        self.load_pgn_available = False
        self.reconnect_available = False

    def apply_default_time_settings(self):
        minutes = env.default_time_minutes()
        if minutes in ALL_TIME_VALUES:
            self.selected_time_minutes = minutes
        seconds = env.default_increment_seconds()
        if seconds in [value for _, value in INCREMENT_OPTIONS]:
            self.selected_increment_seconds = seconds
        if self.selected_time_minutes is None:
            self.selected_increment_seconds = 0

    def set_reconnect_available(self, available):
        if self.reconnect_available == available:
            return
        self.reconnect_available = available
        if self._outer.width > 0:
            self.set_rect(self._outer)

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def is_visible(self):
        return self.visible

    def build_config(self):
        return {
            "mode": self.selected_mode,
            "nickname": self.text_input.text,
            "time_minutes": self.selected_time_minutes,
            "increment_seconds": self.selected_increment_seconds,
            "side": self.selected_side,
        }

    def set_rect(self, rect):
        self._avail = pg.Rect(rect)
        recon = 1 if self.reconnect_available else 0
        natural = 124 + 64 + 66 + 54 + 66 + 48 + 42 + recon * 58 + 15 * (6 + recon)
        scale = min(1.0, max((rect.height - 44) / natural, 0.5))
        self._scale = scale
        s = scale

        self.label_font = get_font(max(int(11 * s), 9), bold=True)
        self.seg_font = get_font(max(int(13 * s), 10), bold=True)
        self.chip_font = get_mono_font(max(int(13 * s), 10), bold=True)
        self.button_font = get_font(max(int(13 * s), 10), bold=True)
        self.wordmark_font = get_display_font(max(int(34 * s), 18))
        self.tagline_font = get_font(max(int(10 * s), 8), bold=True)
        self.start_font = get_display_font(max(int(22 * s), 14))
        self.recon_font = get_font(max(int(12 * s), 9), bold=True)

        pad = int(22 * s)
        bottom = self._layout(rect.y)
        content_h = bottom - rect.y + pad
        card_top = rect.y + max((rect.height - content_h) // 2, 0)
        if card_top != rect.y:
            self._layout(card_top)
        self._outer = pg.Rect(rect.x, card_top, rect.width, content_h)
        self._tile_cache = None
        self._start_cache = None
        self._build_footer()

    def _layout(self, oy):
        rect = self._avail
        s = self._scale
        pad = int(22 * s)
        x = rect.x + pad
        w = rect.width - 2 * pad
        gap = max(int(15 * s), 6)
        label_gap = max(int(6 * s), 3)
        label_h = self.label_font.get_height()
        y = oy + pad

        gear = int(34 * s)
        self._gear_rect = pg.Rect(rect.right - int(16 * s) - gear, oy + int(16 * s),
                                  gear, gear)

        tile = int(52 * s)
        self._tile_rect = pg.Rect(rect.centerx - tile // 2, y, tile, tile)
        y += tile + max(int(4 * s), 2)
        top_h = self.wordmark_font.get_height()
        self._wordmark_top = (rect.centerx, y)
        y += int(top_h * 0.78)
        self._wordmark_bottom = (rect.centerx, y)
        y += int(top_h * 0.86)
        self._tagline_pos = (rect.centerx, y)
        y += self.tagline_font.get_height() + gap

        if self.reconnect_available:
            recon_h = int(40 * s)
            self._recon_rect = pg.Rect(x, y, w, recon_h)
            btn_w = int(86 * s)
            self._recon_button_rect = pg.Rect(
                self._recon_rect.right - int(11 * s) - btn_w,
                y + (recon_h - int(26 * s)) // 2, btn_w, int(26 * s))
            y += recon_h + gap
        else:
            self._recon_rect = pg.Rect(0, 0, 0, 0)
            self._recon_button_rect = pg.Rect(0, 0, 0, 0)

        self._nick_label_y = y
        self._input_rect = pg.Rect(x, y + label_h + label_gap, w, int(42 * s))
        y = self._input_rect.bottom + gap

        seg_h = int(44 * s)
        self._mode_label_pos = (x, y)
        self._mode_rect = pg.Rect(x, y + label_h + label_gap, w, seg_h)
        y = self._mode_rect.bottom + gap

        col_gap = int(12 * s)
        col_w = (w - col_gap) // 2
        self._time_label_pos = (x, y)
        self._incr_label_pos = (x + col_w + col_gap, y)
        chips_y = y + label_h + label_gap
        self._time_rect = pg.Rect(x, chips_y, col_w, int(34 * s))
        self._incr_rect = pg.Rect(x + col_w + col_gap, chips_y, col_w, int(34 * s))
        y = self._time_rect.bottom + gap

        self._side_label_pos = (x, y)
        self._side_rect = pg.Rect(x, y + label_h + label_gap, w, seg_h)
        y = self._side_rect.bottom + gap

        self._start_rect = pg.Rect(x, y, w, int(48 * s))
        y = self._start_rect.bottom + gap

        ghost_h = int(40 * s)
        ghost_w = (w - col_gap) // 2
        self._history_rect = pg.Rect(x, y, ghost_w, ghost_h)
        self._fen_rect = pg.Rect(x + ghost_w + col_gap, y, w - ghost_w - col_gap, ghost_h)
        return self._fen_rect.bottom

    def _build_footer(self):
        win_w, win_h = self.window.get_size()
        font = get_font(max(int(win_h / 64), 9))
        prefix = footer_prefix_text()
        self._footer_prefix_surf = font.render(prefix, True, Colors.footer_text)
        self._footer_link_surf = font.render(FOOTER_LINK_TEXT, True, Colors.footer_link)
        self._footer_link_mask_surf = font.render(FOOTER_LINK_TEXT, True, Colors.white)
        prefix_w = self._footer_prefix_surf.get_width()
        link_w, link_h = self._footer_link_surf.get_size()
        fx = (win_w - prefix_w - link_w) // 2
        fy = win_h - FOOTER_MARGIN_PX - link_h
        self._footer_prefix_pos = (fx, fy)
        self._footer_link_rect = pg.Rect(fx + prefix_w, fy, link_w, link_h)
        self._footer_link_hitbox = self._footer_link_rect.inflate(
            FOOTER_LINK_HITBOX_PAD_PX * 2, FOOTER_LINK_HITBOX_PAD_PX * 2)
        self._footer_underline_y = fy + link_h - 1
        band_w = max(int(link_w * 0.5), 12)
        band = pg.Surface((band_w, link_h), pg.SRCALPHA)
        half = band_w / 2
        for col in range(band_w):
            alpha = int(FOOTER_SHINE_MAX_ALPHA * (1 - abs(col - half) / half))
            pg.draw.line(band, (255, 255, 255, alpha), (col, 0), (col, link_h))
        self._footer_shine_band = band
        self._footer_shine_w = band_w

    def _brand_tile(self):
        size = self._tile_rect.size
        if self._tile_cache is not None and self._tile_cache[0] == size:
            return self._tile_cache[1]
        if self._brand_mark is not None:
            tile = pg.transform.smoothscale(self._brand_mark, size).convert_alpha()
        else:
            tile = rounded_rect_surface(size, 14, Colors.accent)
        mask = supersample(size, lambda s, k: pg.draw.rect(
            s, (255, 255, 255, 255), s.get_rect(), border_radius=int(14 * k)))
        tile.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self._tile_cache = (size, tile)
        return tile

    def _start_surfaces(self):
        size = self._start_rect.size
        if self._start_cache is not None and self._start_cache[0] == size:
            return self._start_cache[1:]

        def render(surf, k):
            wpx, hpx = surf.get_size()
            top, bot = pg.Color(Colors.accent_hi), pg.Color(Colors.accent)
            for yy in range(hpx):
                surf.fill(top.lerp(bot, yy / max(hpx - 1, 1)), pg.Rect(0, yy, wpx, 1))
            mask = pg.Surface((wpx, hpx), pg.SRCALPHA)
            pg.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                         border_radius=int(11 * k))
            surf.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)

        base = supersample(size, render)
        glow = rounded_rect_surface(size, 11, (255, 255, 255, 30))
        press = rounded_rect_surface(size, 11, (0, 0, 0, 50))
        self._start_cache = (size, base, glow, press)
        return base, glow, press

    def _draw_start(self):
        base, glow, press = self._start_surfaces()
        hovered = self._start_rect.collidepoint(pg.mouse.get_pos())
        pressed = hovered and pg.mouse.get_pressed()[0]
        dy = 1 if pressed else 0
        pos = (self._start_rect.x, self._start_rect.y + dy)
        self.window.blit(base, pos)
        if pressed:
            self.window.blit(press, pos)
        elif hovered:
            self.window.blit(glow, pos)
        label = self.start_font.render("START", True, Colors.on_accent)
        self.window.blit(label, (self._start_rect.centerx - label.get_width() // 2,
                                 self._start_rect.centery + dy - label.get_height() // 2))

    def draw(self):
        if not self.visible:
            self._mode_rects = self._time_rects = self._incr_rects = self._side_rects = {}
            return
        r = self._outer
        self.window.blit(rounded_rect_surface(r.size, 18, Colors.surface,
                                              border=Colors.border_strong, border_width=1),
                         r.topleft)
        gear = self._gear_rect
        gear_hover = gear.collidepoint(pg.mouse.get_pos())
        self.window.blit(rounded_rect_surface(
            gear.size, max(int(9 * self._scale), 5),
            Colors.button_hover if gear_hover else Colors.surface_inset,
            border=Colors.button_border, border_width=1), gear.topleft)
        draw_gear(self.window, gear.inflate(-int(gear.width * 0.44),
                                            -int(gear.height * 0.44)))

        self.window.blit(self._brand_tile(), self._tile_rect.topleft)
        top_surf = self.wordmark_font.render(WORDMARK_TOP, True, Colors.white)
        self.window.blit(top_surf, (self._wordmark_top[0] - top_surf.get_width() // 2,
                                    self._wordmark_top[1]))
        bot_surf = self.wordmark_font.render(WORDMARK_BOTTOM, True, Colors.accent)
        self.window.blit(bot_surf, (self._wordmark_bottom[0] - bot_surf.get_width() // 2,
                                    self._wordmark_bottom[1]))
        tag_surf = self.tagline_font.render(TAGLINE, True, Colors.text_mute)
        self.window.blit(tag_surf, (self._tagline_pos[0] - tag_surf.get_width() // 2,
                                    self._tagline_pos[1]))

        if self.reconnect_available:
            self._draw_recon()

        self._draw_label("NICKNAME", (self._input_rect.x, self._nick_label_y))
        self.text_input.set_rect(self._input_rect)
        self.text_input.draw()

        self._draw_label("MODE", self._mode_label_pos)
        self._mode_rects = draw_segmented(self.window, self._mode_rect, MODE_OPTIONS,
                                          self.selected_mode, self.seg_font)

        self._draw_label("TIME", self._time_label_pos)
        self._draw_label("INCREMENT", self._incr_label_pos)
        self._time_rects = draw_chip_row(self.window, self._time_rect, self._time_options(),
                                         self.selected_time_minutes, self.chip_font)
        self._incr_rects = draw_chip_row(self.window, self._incr_rect, INCREMENT_OPTIONS,
                                         self.selected_increment_seconds, self.chip_font,
                                         locked=self.selected_time_minutes is None)

        self._draw_label("YOUR SIDE", self._side_label_pos)
        self._draw_side()

        self._draw_start()
        self._draw_ghost(self._history_rect, "🕑", "History",
                         disabled=not self.load_pgn_available)
        self._draw_ghost(self._fen_rect, "📋", "Paste FEN",
                         disabled=self.selected_mode == "online")

        self._draw_footer()

    def _time_options(self):
        page = TIME_PAGES[self._time_page]
        if self._time_page == 0:
            return page + [("→", "__next__")]
        return page + [("←", "__prev__")]

    def _draw_label(self, text, pos):
        self.window.blit(self.label_font.render(text, True, Colors.text_mute), pos)

    def _draw_recon(self):
        fill = pg.Color(Colors.amber).lerp(pg.Color(Colors.surface_inset), 0.84)
        border = pg.Color(Colors.amber).lerp(pg.Color(Colors.surface_inset), 0.55)
        self.window.blit(rounded_rect_surface(self._recon_rect.size, 9, fill,
                                              border=border, border_width=1),
                         self._recon_rect.topleft)
        dot_r = max(int(4 * self._scale), 3)
        pg.draw.circle(self.window, Colors.amber,
                       (self._recon_rect.x + int(14 * self._scale), self._recon_rect.centery),
                       dot_r)
        text = self.recon_font.render("You have a game in progress", True, Colors.white)
        self.window.blit(text, (self._recon_rect.x + int(26 * self._scale),
                                self._recon_rect.centery - text.get_height() // 2))
        self.window.blit(rounded_rect_surface(self._recon_button_rect.size, 6, Colors.surface,
                                              border=Colors.amber, border_width=1),
                         self._recon_button_rect.topleft)
        label = self.recon_font.render("Reconnect", True, Colors.amber_hi)
        self.window.blit(label, (self._recon_button_rect.centerx - label.get_width() // 2,
                                 self._recon_button_rect.centery - label.get_height() // 2))

    def _draw_side(self):
        self.window.blit(rounded_rect_surface(self._side_rect.size, 9, Colors.surface_inset,
                                              border=Colors.button_border, border_width=1),
                         self._side_rect.topleft)
        pad = max(int(4 * self._scale), 2)
        inner = self._side_rect.inflate(-2 * pad, -2 * pad)
        seg_gap = max(int(5 * self._scale), 2)
        cell_w = (inner.width - seg_gap * 2) / 3
        self._side_rects = {}
        for i, (label, key) in enumerate(SIDE_OPTIONS):
            cr = pg.Rect(round(inner.x + i * (cell_w + seg_gap)), inner.y,
                         round(cell_w), inner.height)
            color = Colors.text_dim
            if key == self.selected_side:
                self.window.blit(rounded_rect_surface(cr.size, 6, Colors.button_pressed,
                                                      border=Colors.accent, border_width=1),
                                 cr.topleft)
                color = Colors.white
            elif cr.collidepoint(pg.mouse.get_pos()):
                color = Colors.white
            self._draw_side_cell(cr, label, key, color)
            self._side_rects[key] = cr

    def _draw_side_cell(self, cr, label, key, color):
        icon_size = int(cr.height * (0.66 if key == "random" else 0.95))
        text = self.seg_font.render(label, True, color)
        total_w = icon_size + max(int(5 * self._scale), 3) + text.get_width()
        ix = cr.centerx - total_w // 2
        iy = cr.centery
        if key == "random":
            if not blit_emoji(self.window, "🎲", (ix + icon_size // 2, iy), icon_size):
                pg.draw.rect(self.window, color,
                             pg.Rect(ix, iy - icon_size // 2, icon_size, icon_size),
                             1, border_radius=4)
        else:
            img = self._side_imgs.get(key)
            if img is not None:
                scaled = pg.transform.smoothscale(img, (icon_size, icon_size))
                self.window.blit(scaled, (ix, iy - icon_size // 2))
        self.window.blit(text, (ix + icon_size + max(int(5 * self._scale), 3),
                                iy - text.get_height() // 2))

    def _draw_ghost(self, rect, emoji, label, disabled):
        hovered = rect.collidepoint(pg.mouse.get_pos()) and not disabled
        bg = Colors.light_grey_menu if hovered else Colors.surface
        text_color = Colors.footer_text if disabled else (
            Colors.white if hovered else Colors.text_dim)
        self.window.blit(rounded_rect_surface(rect.size, 8, bg,
                                              border=Colors.button_border, border_width=1),
                         rect.topleft)
        text = self.button_font.render(label, True, text_color)
        icon = emoji_surface(emoji, int(rect.height * 0.5))
        igap = max(int(6 * self._scale), 3)
        if icon is not None:
            total = icon.get_width() + igap + text.get_width()
            ix = rect.centerx - total // 2
            self.window.blit(icon, (ix, rect.centery - icon.get_height() // 2))
            self.window.blit(text, (ix + icon.get_width() + igap,
                                    rect.centery - text.get_height() // 2))
        else:
            self.window.blit(text, (rect.centerx - text.get_width() // 2,
                                    rect.centery - text.get_height() // 2))

    def _footer_link_hovered(self):
        return bool(self._footer_link_hitbox.collidepoint(pg.mouse.get_pos()))

    def _draw_footer(self):
        if self._footer_prefix_surf is None:
            return
        self.window.blit(self._footer_prefix_surf, self._footer_prefix_pos)
        self.window.blit(self._footer_link_surf, self._footer_link_rect.topleft)
        pg.draw.line(self.window, Colors.footer_link,
                     (self._footer_link_rect.x, self._footer_underline_y),
                     (self._footer_link_rect.right - 1, self._footer_underline_y))
        hovered = self._footer_link_hovered()
        period = FOOTER_SHINE_HOVER_PERIOD_MS if hovered else FOOTER_SHINE_PERIOD_MS
        sweep = FOOTER_SHINE_HOVER_SWEEP_MS if hovered else FOOTER_SHINE_SWEEP_MS
        elapsed = pg.time.get_ticks() % period
        if elapsed >= sweep:
            return
        progress = elapsed / sweep
        link_w = self._footer_link_rect.width
        link_h = self._footer_link_rect.height
        offset = int(progress * (link_w + self._footer_shine_w) - self._footer_shine_w)
        shine = pg.Surface((link_w, link_h), pg.SRCALPHA)
        shine.blit(self._footer_shine_band, (offset, 0))
        shine.blit(self._footer_link_mask_surf, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self.window.blit(shine, self._footer_link_rect.topleft)

    def handle_click(self, pos):
        if not self.visible:
            return False
        if self._gear_rect.collidepoint(pos):
            if "options" in self.callbacks:
                self.callbacks["options"]()
            return True
        if self._footer_link_hitbox.collidepoint(pos):
            if "open_url" in self.callbacks:
                self.callbacks["open_url"](FOOTER_URL)
            return True
        if self.reconnect_available and self._recon_button_rect.collidepoint(pos):
            if "reconnect" in self.callbacks:
                self.callbacks["reconnect"]()
            return True
        if self._input_rect.collidepoint(pos):
            self.text_input.handle_click(pos)
            return True
        self.text_input.handle_click(pos)
        for key, br in self._mode_rects.items():
            if br.collidepoint(pos):
                self.selected_mode = key
                return True
        for key, br in self._time_rects.items():
            if br.collidepoint(pos):
                if key == "__next__":
                    self._time_page = 1
                elif key == "__prev__":
                    self._time_page = 0
                else:
                    self.selected_time_minutes = key
                    if key is None:
                        self.selected_increment_seconds = 0
                return True
        if self.selected_time_minutes is not None:
            for key, br in self._incr_rects.items():
                if br.collidepoint(pos):
                    self.selected_increment_seconds = key
                    return True
        for key, br in self._side_rects.items():
            if br.collidepoint(pos):
                self.selected_side = key
                return True
        if self._history_rect.collidepoint(pos):
            if self.load_pgn_available and "load_pgn" in self.callbacks:
                self.callbacks["load_pgn"]()
            return True
        if self._fen_rect.collidepoint(pos):
            if self.selected_mode != "online" and "fen" in self.callbacks:
                self.callbacks["fen"]()
            return True
        if self._start_rect.collidepoint(pos):
            self.callbacks["start_game"](self.build_config())
            return True
        return False

    def handle_key(self, event):
        return self.text_input.handle_key(event)
