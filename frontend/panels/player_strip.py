import pygame as pg

from backend.pieces import PieceColor
from frontend.visual.clock_visual import LOW_TIME_FRACTION
from frontend.visual.colors import Colors
from frontend.visual.draw import supersample, rounded_rect_surface, blit_centered
from frontend.visual.fonts import get_font, DISPLAY


AUTO_END_RED_THRESHOLD_SECONDS = 10
AUTO_END_BADGE_FONT_SCALE = 0.75
GIVE_TIME_FLASH_MS = 520
GIVE_TIME_FLASH_PEAK_ALPHA = 150
GIVE_TIME_FLOAT_MS = 1000
KO_WINK_MS = 520
TWO_ROW_MIN_IH = 26


def format_clock(seconds):
    if seconds is None:
        return "∞"
    if seconds < 0:
        seconds = 0
    if seconds < 30:
        total_tenths = int(seconds * 10)
        minutes, rem = divmod(total_tenths, 600)
        secs, tenths = divmod(rem, 10)
        return f"{minutes}:{secs:02d}.{tenths}"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def format_countdown(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def give_time_float_alpha(progress):
    if progress < 0 or progress >= 1:
        return 0
    ramp = progress / 0.3 if progress < 0.3 else (1 - progress) / 0.7
    return max(0, min(255, int(255 * ramp)))


class PlayerStrip:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.name = ""
        self.player_color = PieceColor.WHITE
        self.is_bot = False
        self.rating = None
        self.clock_seconds = None
        self.clock_initial_seconds = None
        self.active = False
        self.captured = []
        self.advantage = 0
        self.captured_color = None
        self.connection_state = None
        self.auto_end_label = None
        self.auto_end_seconds = None
        self.ko_count = 0
        self._flash_until_ms = 0
        self._give_time_start_ms = 0
        self._give_time_amount = 0
        self._ko_wink_until_ms = 0
        self.name_font = get_font(14, bold=True)
        self.rating_font = get_font(11, bold=True, mono=True)
        self.clock_font = get_font(16, bold=True, mono=True)
        self.advantage_font = get_font(12, bold=True)
        self.ko_font = get_font(10, bold=True)
        self.letter_font = get_font(18, family=DISPLAY)
        self.auto_end_font = get_font(11, bold=True)
        self.icons = {}
        self._avatar_cache = None

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        h = rect.height
        ih = max(int(h * 0.68), 1)
        self.name_font = get_font(max(int(ih * 0.42), 11), bold=True)
        self.rating_font = get_font(max(int(ih * 0.26), 8), bold=True, mono=True)
        self.clock_font = get_font(max(int(h * 0.5), 14), bold=True, mono=True)
        self.advantage_font = get_font(max(int(ih * 0.26), 8), bold=True)
        self.ko_font = get_font(max(int(ih * 0.3), 8), bold=True)
        self.letter_font = get_font(max(int(ih * 0.5), 11), family=DISPLAY)
        self.auto_end_font = get_font(
            max(int(ih * 0.42 * AUTO_END_BADGE_FONT_SCALE), 9), bold=True)
        self._avatar_cache = None

    def set_piece_icons(self, icons):
        self.icons = icons

    def set_state(self, name, clock_seconds, active, captured=None, advantage=0,
                  captured_color=None, connection_state=None,
                  clock_initial_seconds=None, auto_end_label=None,
                  auto_end_seconds=None, player_color=PieceColor.WHITE,
                  is_bot=False, rating=None, ko_count=0):
        self.name = name
        self.player_color = player_color
        self.is_bot = is_bot
        self.rating = rating
        self.clock_seconds = clock_seconds
        self.clock_initial_seconds = clock_initial_seconds
        self.active = active
        self.captured = captured or []
        self.advantage = advantage
        self.captured_color = captured_color
        self.connection_state = connection_state
        self.auto_end_label = auto_end_label
        self.auto_end_seconds = auto_end_seconds
        if ko_count > self.ko_count:
            self._ko_wink_until_ms = pg.time.get_ticks() + KO_WINK_MS
        self.ko_count = ko_count

    def flash_increment(self, seconds=0, now_ms=None):
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        self._flash_until_ms = now_ms + GIVE_TIME_FLASH_MS
        if seconds > 0:
            self._give_time_start_ms = now_ms
            self._give_time_amount = seconds

    def draw(self):
        h = self.rect.height
        if h <= 0 or self.rect.width <= 0:
            return
        pad = max(int(h * 0.16), 4)
        radius = max(int(h * 0.17), 5)
        pg.draw.rect(self.window, Colors.surface, self.rect, border_radius=radius)

        av_size = max(h - 2 * pad, 1)
        gap = max(int(h * 0.18), 6)

        clock_rect = self._draw_clock(pad, av_size)
        ko_left = self._draw_ko(clock_rect.x - gap, av_size)

        avatar_rect = pg.Rect(self.rect.x + pad, self.rect.y + pad, av_size, av_size)
        self._draw_avatar(avatar_rect)

        who_x = avatar_rect.right + gap
        who_right = (ko_left if ko_left is not None else clock_rect.x) - gap
        self._draw_who(who_x, who_right, av_size)

        if self.active:
            pg.draw.rect(self.window, Colors.accent, self.rect, width=2,
                         border_radius=radius)
        else:
            pg.draw.rect(self.window, Colors.button_border, self.rect, width=1,
                         border_radius=radius)

        self._draw_give_time_float(clock_rect)

    def _avatar_colors(self):
        if self.player_color in (PieceColor.WHITE, "white") and not self.is_bot:
            return (pg.Color(Colors.amber), pg.Color(Colors.accent),
                    pg.Color(Colors.on_accent))
        return (pg.Color(Colors.avatar_slate_top), pg.Color(Colors.avatar_slate_bottom),
                pg.Color(Colors.avatar_letter_dark))

    def _draw_avatar(self, rect):
        top, bottom, letter_color = self._avatar_colors()
        letter = (self.name[:1].upper() if self.name else "?")
        key = (rect.width, top.r, top.g, top.b, bottom.r, bottom.g, bottom.b)
        if self._avatar_cache is None or self._avatar_cache[0] != key:
            self._avatar_cache = (key, self._build_avatar(rect.width, top, bottom))
        self.window.blit(self._avatar_cache[1], rect.topleft)
        glyph = self.letter_font.render(letter, True, letter_color)
        self.window.blit(glyph, (rect.centerx - glyph.get_width() / 2,
                                 rect.centery - glyph.get_height() / 2))

    @staticmethod
    def _build_avatar(size, top, bottom):
        radius = max(int(size * 0.22), 2)

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

    def _draw_who(self, x, right, ih):
        if right <= x:
            return
        two_row = ih >= TWO_ROW_MIN_IH
        base = self.rect.y + (self.rect.height - ih) // 2
        if two_row:
            top_cy = base + int(ih * 0.25)
            bottom_cy = base + int(ih * 0.76)
            pill_max = max(bottom_cy - top_cy - 2, 8)
        else:
            top_cy = bottom_cy = self.rect.centery
            pill_max = ih
        badge_x = self._draw_auto_end_badge(right, top_cy)
        name_right = (badge_x - 8) if badge_x is not None else right
        cursor = x
        if self.connection_state is not None:
            dot_r = max(int(ih * 0.11), 3)
            color = Colors.connection_dots.get(
                self.connection_state, Colors.connection_dots["unknown"])
            pg.draw.circle(self.window, color, (cursor + dot_r, top_cy), dot_r)
            cursor += dot_r * 2 + max(int(ih * 0.12), 4)
        name_surf = self.name_font.render(self.name, True, Colors.white)
        max_name_w = max(name_right - cursor, 1)
        if name_surf.get_width() > max_name_w:
            name_surf = name_surf.subsurface(
                pg.Rect(0, 0, max_name_w, name_surf.get_height()))
        self.window.blit(name_surf, (cursor, top_cy - name_surf.get_height() / 2))
        cursor += name_surf.get_width() + max(int(ih * 0.14), 5)
        if two_row:
            if self.rating is not None:
                self._draw_rating_pill(cursor, top_cy, name_right, pill_max)
            self._draw_captured(x, bottom_cy, right, ih, pill_max)
        else:
            if self.rating is not None:
                cursor = self._draw_rating_pill(cursor, bottom_cy, right, pill_max)
            self._draw_captured(cursor, bottom_cy, right, ih, pill_max)

    def _draw_rating_pill(self, x, cy, right, max_h=10 ** 6):
        text = self.rating_font.render(str(self.rating), True, Colors.text_dim)
        pad_x = max(int(text.get_height() * 0.45), 3)
        w = text.get_width() + 2 * pad_x
        h = min(text.get_height() + 2, max_h)
        if x + w > right:
            return x
        pill = rounded_rect_surface((w, h), max(h // 3, 3), Colors.button_hover)
        self.window.blit(pill, (x, round(cy - h / 2)))
        blit_centered(self.window, text, (x + w / 2, cy))
        return x + w + max(int(self.rect.height * 0.06), 4)

    def _draw_captured(self, x, cy, right, ih, max_h=10 ** 6):
        cursor = x
        last_right = x
        size = max(int(ih * 0.5), 6)
        for piece_type in self.captured:
            icon = self.icons.get((piece_type, self.captured_color))
            if icon is None:
                continue
            if icon.get_height() != size:
                icon = pg.transform.smoothscale(icon, (size, size))
            if cursor + icon.get_width() > right:
                break
            self.window.blit(icon, (cursor, cy - icon.get_height() / 2))
            last_right = cursor + icon.get_width()
            cursor += icon.get_width() - icon.get_width() // 3
        if self.advantage > 0:
            self._draw_advantage_pill(last_right + max(int(ih * 0.18), 5), cy, right, max_h)

    def _draw_advantage_pill(self, x, cy, right, max_h=10 ** 6):
        text = self.advantage_font.render(f"+{self.advantage}", True, Colors.on_accent)
        pad_x = max(int(text.get_height() * 0.55), 4)
        w = text.get_width() + 2 * pad_x
        h = min(text.get_height() + 2, max_h)
        if x + w > right:
            return
        pill = rounded_rect_surface((w, h), h // 2, Colors.amber)
        self.window.blit(pill, (x, round(cy - h / 2)))
        blit_centered(self.window, text, (x + w / 2, cy))

    def _draw_ko(self, right, ih):
        if self.ko_count <= 0:
            return None
        winking = pg.time.get_ticks() < self._ko_wink_until_ms
        label_color = Colors.amber if winking else Colors.text_mute
        text = self.ko_font.render(f"{self.ko_count} KO", True, label_color)
        shell_w = max(int(ih * 0.16), 4)
        shell_h = max(int(ih * 0.42), 7)
        gap = max(int(ih * 0.12), 3)
        block_w = shell_w + gap + text.get_width()
        x = right - block_w
        cy = self.rect.y + self.rect.height // 2
        shell = pg.Rect(x, cy - shell_h // 2, shell_w, shell_h)
        self._draw_shell(shell, winking)
        blit_centered(self.window, text, (shell.right + gap + text.get_width() / 2, cy))
        return x

    def _draw_shell(self, rect, winking):
        self.window.blit(self._build_shell(rect.width, rect.height, winking),
                         rect.topleft)

    @staticmethod
    def _build_shell(w, h, winking):
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

    def _draw_clock(self, pad, av_size):
        text = format_clock(self.clock_seconds)
        surf = self.clock_font.render(text, True, self._clock_text_color())
        hpad = max(int(self.rect.height * 0.22), 8)
        min_w = max(int(self.rect.height * 2.0), 70)
        box_w = max(surf.get_width() + 2 * hpad, min_w)
        box = pg.Rect(self.rect.right - pad - box_w, self.rect.y + pad, box_w, av_size)
        radius = max(int(self.rect.height * 0.14), 5)
        pg.draw.rect(self.window, Colors.app_bg, box, border_radius=radius)
        flash = self._flash_alpha()
        if flash > 0:
            tint = pg.Surface(box.size, pg.SRCALPHA)
            col = pg.Color(Colors.clock_increment_flash)
            col.a = flash
            pg.draw.rect(tint, col, tint.get_rect(), border_radius=radius)
            self.window.blit(tint, box.topleft)
        pg.draw.rect(self.window, self._clock_border_color(), box, width=1,
                     border_radius=radius)
        self.window.blit(surf, (box.centerx - surf.get_width() / 2,
                                box.centery - surf.get_height() / 2))
        return box

    def _is_low_time(self):
        frac = self._clock_fraction()
        return frac is not None and frac < LOW_TIME_FRACTION

    def _clock_text_color(self):
        if self._is_low_time():
            return Colors.clock_low_text
        return Colors.white

    def _clock_border_color(self):
        if self._is_low_time():
            return Colors.clock_low_time
        return Colors.button_border

    def _draw_give_time_float(self, clock_rect):
        if self._give_time_start_ms <= 0:
            return
        progress = (pg.time.get_ticks() - self._give_time_start_ms) / GIVE_TIME_FLOAT_MS
        alpha = give_time_float_alpha(progress)
        if alpha <= 0:
            return
        text = f"+0:{int(self._give_time_amount):02d}"
        surf = self.clock_font.render(text, True, Colors.clock_increment_flash)
        surf.set_alpha(alpha)
        rise = int((6 - 28 * progress))
        self.window.blit(surf, (clock_rect.centerx - surf.get_width() / 2,
                                clock_rect.y - surf.get_height() + rise))

    def _draw_auto_end_badge(self, right, cy):
        if self.auto_end_label is None or self.auto_end_seconds is None:
            return None
        text = f"{self.auto_end_label} {format_countdown(self.auto_end_seconds)}"
        color = (Colors.auto_end_alert
                 if self.auto_end_seconds < AUTO_END_RED_THRESHOLD_SECONDS
                 else Colors.white)
        surf = self.auto_end_font.render(text, True, color)
        badge_x = right - surf.get_width()
        self.window.blit(surf, (badge_x, cy - surf.get_height() / 2))
        return badge_x

    def _clock_fraction(self):
        if (self.clock_seconds is None or self.clock_initial_seconds is None
                or self.clock_initial_seconds <= 0):
            return None
        return max(0.0, self.clock_seconds / self.clock_initial_seconds)

    def _flash_alpha(self, now_ms=None):
        if self._flash_until_ms <= 0:
            return 0
        if now_ms is None:
            now_ms = pg.time.get_ticks()
        remaining = self._flash_until_ms - now_ms
        if remaining <= 0:
            return 0
        progress = remaining / GIVE_TIME_FLASH_MS
        return int(GIVE_TIME_FLASH_PEAK_ALPHA * max(0.0, min(1.0, progress)))
