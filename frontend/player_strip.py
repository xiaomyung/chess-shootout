import pygame as pg

from frontend.colors import Colors


def format_clock(seconds):
    if seconds is None:
        return "—:—"
    if seconds < 0:
        seconds = 0
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
        self.padding = 10
        self.pocket_inset = 4
        self.pocket_fraction = 0.28
        self.name_font = pg.font.SysFont("Arial", 14, bold=True)
        self.clock_font = pg.font.SysFont("monospace", 16, bold=True)

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        name_size = max(int(rect.height * 0.45), 12)
        clock_size = max(int(rect.height * 0.55), 14)
        self.name_font = pg.font.SysFont("Arial", name_size, bold=True)
        self.clock_font = pg.font.SysFont("monospace", clock_size, bold=True)

    def set_state(self, name, clock_seconds, active):
        self.name = name
        self.clock_seconds = clock_seconds
        self.active = active

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

        name_surf = self.name_font.render(self.name, True, Colors.white)
        max_w = name_region.width - 2 * self.pocket_inset
        if name_surf.get_width() > max_w > 0:
            name_surf = name_surf.subsurface(pg.Rect(0, 0, max_w, name_surf.get_height()))
        self.window.blit(
            name_surf,
            (name_region.x + self.pocket_inset,
             name_region.centery - name_surf.get_height() / 2),
        )

        pg.draw.rect(self.window, Colors.light_grey_menu, pocket_rect, border_radius=3)
        clock_text = format_clock(self.clock_seconds)
        clock_surf = self.clock_font.render(clock_text, True, Colors.white)
        self.window.blit(
            clock_surf,
            (pocket_rect.centerx - clock_surf.get_width() / 2,
             pocket_rect.centery - clock_surf.get_height() / 2),
        )
