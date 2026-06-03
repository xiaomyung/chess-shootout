import pygame as pg

from backend.pieces import PieceColor
from infra.countries import flag_emoji, name_for
from frontend.visual.clock_visual import LOW_TIME_FRACTION
from frontend.visual.colors import Colors
from frontend.visual.draw import rounded_rect_surface, blit_centered, circle_surface
from frontend.visual.emoji import emoji_surface
from frontend.visual.fonts import get_font, DISPLAY
from frontend.visual.widgets import build_avatar, build_ko_badge


AUTO_END_RED_THRESHOLD_SECONDS = 10
AUTO_END_BADGE_FONT_SCALE = 0.75
GIVE_TIME_FLASH_MS = 520
GIVE_TIME_FLASH_PEAK_ALPHA = 150
GIVE_TIME_FLOAT_MS = 1000
KO_WINK_MS = 520
TWO_ROW_MIN_IH = 26
TOOLTIP_EASE = 0.22
GIVE_TIME_FADE_IN_FRACTION = 0.3
GIVE_TIME_FADE_OUT_FRACTION = 1 - GIVE_TIME_FADE_IN_FRACTION
GIVE_TIME_FLOAT_RISE_PX = 6
GIVE_TIME_FLOAT_TRAVEL_PX = 28
NO_PILL_HEIGHT_CAP = 10 ** 6
TOOLTIP_PAD_X = 9
TOOLTIP_PAD_Y = 5
TOOLTIP_RADIUS = 6
TOOLTIP_RISE_PX = 5
TOOLTIP_GAP_PX = 5
TOOLTIP_EDGE_MARGIN_PX = 2


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
    ramp = (progress / GIVE_TIME_FADE_IN_FRACTION
            if progress < GIVE_TIME_FADE_IN_FRACTION
            else (1 - progress) / GIVE_TIME_FADE_OUT_FRACTION)
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
        self.country = None
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
        self._flag_cache = None
        self._flag_rect = pg.Rect(0, 0, 0, 0)
        self._tooltip_alpha = 0.0
        self.tooltip_font = get_font(12, bold=True)

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
        self.tooltip_font = get_font(max(int(ih * 0.34), 11), bold=True)
        self._avatar_cache = None

    def set_piece_icons(self, icons):
        self.icons = icons

    def set_state(self, name, clock_seconds, active, captured=None, advantage=0,
                  captured_color=None, connection_state=None,
                  clock_initial_seconds=None, auto_end_label=None,
                  auto_end_seconds=None, player_color=PieceColor.WHITE,
                  is_bot=False, rating=None, ko_count=0, country=None):
        self.name = name
        self.player_color = player_color
        self.is_bot = is_bot
        self.rating = rating
        self.country = country
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
        self._flag_rect = pg.Rect(0, 0, 0, 0)
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
            pg.draw.rect(self.window, Colors.border, self.rect, width=1,
                         border_radius=radius)

        self._draw_give_time_float(clock_rect)
        self._draw_flag_tooltip()

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
        return build_avatar(size, top, bottom)

    def _flag_surface(self, height):
        char = flag_emoji(self.country)
        if not char:
            return None
        key = (char, height)
        if self._flag_cache is None or self._flag_cache[0] != key:
            self._flag_cache = (key, emoji_surface(char, height))
        return self._flag_cache[1]

    def _advance_tooltip(self, hovering):
        target = 1.0 if hovering else 0.0
        self._tooltip_alpha += (target - self._tooltip_alpha) * TOOLTIP_EASE
        if abs(self._tooltip_alpha - target) < 0.01:
            self._tooltip_alpha = target
        return self._tooltip_alpha

    def _draw_flag_tooltip(self):
        name = name_for(self.country)
        if not name or self._flag_rect.width == 0:
            self._tooltip_alpha = 0.0
            return
        hovering = self._flag_rect.collidepoint(pg.mouse.get_pos())
        self._advance_tooltip(hovering)
        if self._tooltip_alpha <= 0.02:
            return
        self._blit_tooltip(name)

    def _blit_tooltip(self, name):
        alpha = int(max(0.0, min(1.0, self._tooltip_alpha)) * 255)
        text = self.tooltip_font.render(name, True, Colors.text)
        pad_x, pad_y = TOOLTIP_PAD_X, TOOLTIP_PAD_Y
        w = text.get_width() + 2 * pad_x
        h = text.get_height() + 2 * pad_y
        bubble = pg.Surface((w, h), pg.SRCALPHA)
        bubble.blit(rounded_rect_surface((w, h), TOOLTIP_RADIUS, Colors.bg,
                                         border=Colors.border, border_width=1), (0, 0))
        bubble.blit(text, (pad_x, pad_y))
        bubble.set_alpha(alpha)
        rise = int(TOOLTIP_RISE_PX * (1 - self._tooltip_alpha))
        if self.rect.centery < self.window.get_height() / 2:
            by = self._flag_rect.bottom + TOOLTIP_GAP_PX + rise
        else:
            by = self._flag_rect.top - h - TOOLTIP_GAP_PX - rise
        bx = self._flag_rect.centerx - w // 2
        bx = max(TOOLTIP_EDGE_MARGIN_PX,
                 min(bx, self.window.get_width() - w - TOOLTIP_EDGE_MARGIN_PX))
        self.window.blit(bubble, (bx, by))

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
        badge_x = self._draw_auto_end_badge(right, self.rect.centery)
        name_right = (badge_x - 8) if badge_x is not None else right
        cursor = x
        if self.connection_state is not None:
            dot_r = max(int(ih * 0.11), 3)
            color = getattr(Colors, "dot_" + self.connection_state, Colors.dot_unknown)
            dot = circle_surface(dot_r * 2, color)
            self.window.blit(dot, (cursor, top_cy - dot_r))
            cursor += dot_r * 2 + max(int(ih * 0.12), 4)
        flag = self._flag_surface(max(int(ih * 0.42), 10))
        if flag is not None and cursor + flag.get_width() <= name_right:
            self.window.blit(flag, (cursor, top_cy - flag.get_height() // 2))
            self._flag_rect = pg.Rect(cursor, top_cy - flag.get_height() // 2,
                                      flag.get_width(), flag.get_height())
            cursor += flag.get_width() + max(int(ih * 0.1), 4)
        name_surf = self.name_font.render(self.name, True, Colors.text)
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

    def _draw_text_pill(self, x, cy, right, text, bg, *,
                        pad_ratio, pad_min, radius_div, radius_min, max_h):
        pad_x = max(int(text.get_height() * pad_ratio), pad_min)
        w = text.get_width() + 2 * pad_x
        h = min(text.get_height() + 2, max_h)
        if x + w > right:
            return None
        pill = rounded_rect_surface((w, h), max(h // radius_div, radius_min), bg)
        self.window.blit(pill, (x, round(cy - h / 2)))
        blit_centered(self.window, text, (x + w / 2, cy))
        return x + w

    def _draw_rating_pill(self, x, cy, right, max_h=NO_PILL_HEIGHT_CAP):
        text = self.rating_font.render(str(self.rating), True, Colors.text_dim)
        end = self._draw_text_pill(x, cy, right, text, Colors.surface_hover,
                                   pad_ratio=0.45, pad_min=3, radius_div=3, radius_min=3,
                                   max_h=max_h)
        if end is None:
            return x
        return end + max(int(self.rect.height * 0.06), 4)

    def _draw_captured(self, x, cy, right, ih, max_h=NO_PILL_HEIGHT_CAP):
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

    def _draw_advantage_pill(self, x, cy, right, max_h=NO_PILL_HEIGHT_CAP):
        text = self.advantage_font.render(f"+{self.advantage}", True, Colors.on_accent)
        self._draw_text_pill(x, cy, right, text, Colors.amber,
                             pad_ratio=0.55, pad_min=4, radius_div=2, radius_min=0, max_h=max_h)

    def _draw_ko(self, right, ih):
        if self.ko_count <= 0:
            return None
        winking = pg.time.get_ticks() < self._ko_wink_until_ms
        badge = build_ko_badge(self.ko_count, self.ko_font, ih, winking)
        x = right - badge.get_width()
        cy = self.rect.y + self.rect.height // 2
        self.window.blit(badge, (x, cy - badge.get_height() // 2))
        return x

    def _draw_clock(self, pad, av_size):
        text = format_clock(self.clock_seconds)
        surf = self.clock_font.render(text, True, self._clock_text_color())
        hpad = max(int(self.rect.height * 0.22), 8)
        min_w = max(int(self.rect.height * 2.0), 70)
        box_w = max(surf.get_width() + 2 * hpad, min_w)
        box = pg.Rect(self.rect.right - pad - box_w, self.rect.y + pad, box_w, av_size)
        radius = max(int(self.rect.height * 0.14), 5)
        pg.draw.rect(self.window, Colors.bg, box, border_radius=radius)
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
        return Colors.text

    def _clock_border_color(self):
        if self._is_low_time():
            return Colors.clock_low_time
        return Colors.border

    def _draw_give_time_float(self, clock_rect):
        if self._give_time_start_ms <= 0:
            return
        progress = (pg.time.get_ticks() - self._give_time_start_ms) / GIVE_TIME_FLOAT_MS
        alpha = give_time_float_alpha(progress)
        if alpha <= 0:
            return
        text = f"+0:{int(self._give_time_amount):02d}"
        float_font = get_font(max(int(self.rect.height * 0.24), 11), bold=True, mono=True)
        surf = float_font.render(text, True, Colors.clock_increment_flash)
        surf.set_alpha(alpha)
        rise = int(GIVE_TIME_FLOAT_RISE_PX - GIVE_TIME_FLOAT_TRAVEL_PX * progress)
        self.window.blit(surf, (clock_rect.centerx - surf.get_width() / 2,
                                clock_rect.y - surf.get_height() + rise))

    def _draw_auto_end_badge(self, right, cy):
        if self.auto_end_label is None or self.auto_end_seconds is None:
            return None
        text = f"{self.auto_end_label} {format_countdown(self.auto_end_seconds)}"
        color = (Colors.loss
                 if self.auto_end_seconds < AUTO_END_RED_THRESHOLD_SECONDS
                 else Colors.text)
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
