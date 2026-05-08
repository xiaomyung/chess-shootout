import pygame as pg

from frontend.colors import Colors


def format_clock(seconds):
    if seconds is None:
        return "—:—"
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


class PlayerStrip:

    def __init__(self, window):
        self.window = window
        self.rect = pg.Rect(0, 0, 0, 0)
        self.name = ""
        self.clock_seconds = None
        self.active = False
        self.captured = []
        self.advantage = 0
        self.captured_color = None
        self.connection_state = None
        self.padding = 10
        self.pocket_inset = 4
        self.pocket_fraction = 0.28
        self.name_font = pg.font.SysFont("Arial", 14, bold=True)
        self.clock_font = pg.font.SysFont("monospace", 16, bold=True)
        self.advantage_font = pg.font.SysFont("Arial", 14, bold=True)
        self.icons = {}

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        name_size = max(int(rect.height * 0.45), 12)
        clock_size = max(int(rect.height * 0.55), 14)
        adv_size = max(int(rect.height * 0.4), 10)
        self.name_font = pg.font.SysFont("Arial", name_size, bold=True)
        self.clock_font = pg.font.SysFont("monospace", clock_size, bold=True)
        self.advantage_font = pg.font.SysFont("Arial", adv_size, bold=True)

    def set_piece_icons(self, icons):
        self.icons = icons

    def set_state(self, name, clock_seconds, active, captured=None, advantage=0,
                  captured_color=None, connection_state=None):
        self.name = name
        self.clock_seconds = clock_seconds
        self.active = active
        self.captured = captured or []
        self.advantage = advantage
        self.captured_color = captured_color
        self.connection_state = connection_state

    def draw(self):
        pg.draw.rect(self.window, Colors.dark_menu, self.rect, border_radius=4)

        pocket_w = int(self.rect.width * self.pocket_fraction)
        pocket_rect = pg.Rect(
            self.rect.right - pocket_w - self.pocket_inset,
            self.rect.y + self.pocket_inset,
            pocket_w,
            self.rect.height - 2 * self.pocket_inset,
        )

        name_region = pg.Rect(
            self.rect.x + self.pocket_inset,
            self.rect.y + self.pocket_inset,
            pocket_rect.x - self.rect.x - 2 * self.pocket_inset,
            self.rect.height - 2 * self.pocket_inset,
        )

        if self.active:
            pg.draw.rect(self.window, Colors.button_hover, name_region, border_radius=3)

        dot_offset = 0
        if self.connection_state is not None:
            dot_radius = max(int(self.rect.height * 0.10), 4)
            dot_color = {
                "connected": (60, 200, 90),
                "reconnecting": (220, 180, 40),
                "disconnected": (210, 60, 60),
            }.get(self.connection_state, (140, 140, 140))
            dot_x = name_region.x + self.pocket_inset + dot_radius
            dot_y = name_region.centery
            pg.draw.circle(self.window, dot_color, (dot_x, dot_y), dot_radius)
            dot_offset = dot_radius * 2 + 6

        name_surf = self.name_font.render(self.name, True, Colors.white)
        max_w = name_region.width - 2 * self.pocket_inset - dot_offset
        if name_surf.get_width() > max_w > 0:
            name_surf = name_surf.subsurface(pg.Rect(0, 0, max_w, name_surf.get_height()))
        name_x = name_region.x + self.pocket_inset + dot_offset
        name_y = name_region.centery - name_surf.get_height() / 2
        self.window.blit(name_surf, (name_x, name_y))

        self._draw_captures(name_region, name_x + name_surf.get_width())

        pg.draw.rect(self.window, Colors.light_grey_menu, pocket_rect, border_radius=3)
        clock_text = format_clock(self.clock_seconds)
        clock_surf = self.clock_font.render(clock_text, True, Colors.white)
        self.window.blit(
            clock_surf,
            (pocket_rect.centerx - clock_surf.get_width() / 2,
             pocket_rect.centery - clock_surf.get_height() / 2),
        )

    def _draw_captures(self, name_region, start_x):
        if not self.captured or self.captured_color is None or not self.icons:
            return
        gap = 6
        x = start_x + gap
        max_x = name_region.right - self.pocket_inset
        for piece_type in self.captured:
            icon = self.icons.get((piece_type, self.captured_color))
            if icon is None:
                continue
            if x + icon.get_width() > max_x:
                return
            self.window.blit(icon, (x, name_region.centery - icon.get_height() / 2))
            x += icon.get_width() - icon.get_width() // 3

        if self.advantage > 0:
            adv_surf = self.advantage_font.render(
                f"+{self.advantage}", True, Colors.white,
            )
            adv_x = x + 12
            if adv_x + adv_surf.get_width() <= max_x:
                self.window.blit(
                    adv_surf,
                    (adv_x, name_region.centery - adv_surf.get_height() / 2),
                )
